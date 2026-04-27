from __future__ import annotations

import csv
import json
import socket
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

from server.image_utils import bgr_to_image_msg, resolve_default_inventory_csv_path
from server.tcp_protocol import (
    ConnectionClosedError,
    InventoryRecord,
    ProtocolError,
    decode_image_payload,
    make_error_response,
    make_success_response,
    receive_json_message,
    send_json_message,
    validate_inventory_payload,
)


CSV_FIELDNAMES = [
    "request_id",
    "record_time",
    "person",
    "action",
    "material_name",
    "quantity",
    "received_at",
]


@dataclass
class PendingResponse:
    event: threading.Event
    response: dict[str, Any] | None = None


class TcpBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__("tcp_bridge_node")

        self.declare_parameter("host", "0.0.0.0")
        self.declare_parameter("port", 9000)
        self.declare_parameter("request_timeout_sec", 15.0)
        self.declare_parameter("material_image_topic", "/material_counter/image")
        self.declare_parameter("material_result_topic", "/material_counter/counts")
        self.declare_parameter("face_image_topic", "/face_recognize/image")
        self.declare_parameter("face_result_topic", "/face_recognize/result")
        self.declare_parameter("inventory_csv_path", "auto")

        self.host = str(self.get_parameter("host").value)
        self.port = int(self.get_parameter("port").value)
        self.request_timeout_sec = float(self.get_parameter("request_timeout_sec").value)
        inventory_csv_path_value = str(self.get_parameter("inventory_csv_path").value).strip()
        if not inventory_csv_path_value or inventory_csv_path_value == "auto":
            self.inventory_csv_path = resolve_default_inventory_csv_path()
        else:
            self.inventory_csv_path = Path(inventory_csv_path_value).expanduser().resolve()

        material_image_topic = str(self.get_parameter("material_image_topic").value)
        material_result_topic = str(self.get_parameter("material_result_topic").value)
        face_image_topic = str(self.get_parameter("face_image_topic").value)
        face_result_topic = str(self.get_parameter("face_result_topic").value)

        self.material_publisher = self.create_publisher(Image, material_image_topic, 10)
        self.face_publisher = self.create_publisher(Image, face_image_topic, 10)
        self.material_subscription = self.create_subscription(
            String, material_result_topic, self._material_result_callback, 10
        )
        self.face_subscription = self.create_subscription(String, face_result_topic, self._face_result_callback, 10)

        self._pending_lock = threading.Lock()
        self._pending: dict[str, PendingResponse] = {}
        self._csv_lock = threading.Lock()
        self._publish_lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._shutdown_complete = False
        self._stop_event = threading.Event()
        self._client_threads: set[threading.Thread] = set()
        self._client_sockets: set[socket.socket] = set()
        self._client_lock = threading.Lock()

        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen()
        self._accept_thread = threading.Thread(target=self._accept_loop, name="tcp-bridge-accept", daemon=True)
        self._accept_thread.start()

        self.get_logger().info(f"Listening for TCP clients on {self.host}:{self.port}")
        self.get_logger().info(f"Material image topic: {material_image_topic}")
        self.get_logger().info(f"Material result topic: {material_result_topic}")
        self.get_logger().info(f"Face image topic: {face_image_topic}")
        self.get_logger().info(f"Face result topic: {face_result_topic}")
        self.get_logger().info(f"Inventory CSV path: {self.inventory_csv_path}")

    def destroy_node(self) -> bool:
        self._shutdown_server()
        return super().destroy_node()

    def _shutdown_server(self) -> None:
        with self._shutdown_lock:
            if self._shutdown_complete:
                return
            self._shutdown_complete = True

        self._stop_event.set()

        try:
            self._server_socket.close()
        except OSError:
            pass

        with self._client_lock:
            client_sockets = list(self._client_sockets)
        for client_socket in client_sockets:
            try:
                client_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client_socket.close()
            except OSError:
                pass

        if self._accept_thread.is_alive():
            self._accept_thread.join(timeout=1.0)

        with self._client_lock:
            client_threads = list(self._client_threads)
        for thread in client_threads:
            if thread.is_alive():
                thread.join(timeout=1.0)

        with self._pending_lock:
            pending_entries = list(self._pending.items())
            self._pending.clear()
        for request_id, pending in pending_entries:
            pending.response = make_error_response("SHUTDOWN", "TCP bridge node is shutting down", request_id)
            pending.event.set()

    def _accept_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                client_socket, address = self._server_socket.accept()
            except OSError:
                if self._stop_event.is_set():
                    break
                self.get_logger().error("Failed to accept TCP client connection")
                continue

            client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            thread = threading.Thread(
                target=self._client_loop,
                args=(client_socket, address),
                name=f"tcp-client-{address[0]}:{address[1]}",
                daemon=True,
            )
            with self._client_lock:
                self._client_sockets.add(client_socket)
                self._client_threads.add(thread)
            thread.start()

    def _client_loop(self, client_socket: socket.socket, address: tuple[str, int]) -> None:
        peer = f"{address[0]}:{address[1]}"
        self.get_logger().info(f"TCP client connected: {peer}")

        try:
            while not self._stop_event.is_set():
                request_id: str | None = None
                try:
                    request = receive_json_message(client_socket)
                    request_id = self._resolve_request_id(request.get("request_id"))
                    response = self._handle_request(request, request_id)
                except ConnectionClosedError:
                    break
                except ProtocolError as exc:
                    request_id = request_id or self._generate_request_id()
                    response = make_error_response(exc.code, exc.message, request_id)
                except Exception as exc:
                    request_id = request_id or self._generate_request_id()
                    self.get_logger().error(f"Unexpected TCP request failure from {peer}: {exc}")
                    response = make_error_response("INTERNAL_ERROR", str(exc), request_id)

                try:
                    send_json_message(client_socket, response)
                except OSError:
                    break
        finally:
            with self._client_lock:
                self._client_sockets.discard(client_socket)
                self._client_threads.discard(threading.current_thread())
            try:
                client_socket.close()
            except OSError:
                pass
            self.get_logger().info(f"TCP client disconnected: {peer}")

    def _handle_request(self, request: dict[str, Any], request_id: str) -> dict[str, Any]:
        request_type = request.get("type")
        payload = request.get("payload")

        if not isinstance(request_type, str) or not request_type.strip():
            raise ProtocolError("INVALID_REQUEST", "type must be a non-empty string")

        if request_type == "material_image":
            image = decode_image_payload(payload)
            result = self._submit_image_request(self.material_publisher, request_id, image, "material_image_result")
            return result

        if request_type == "face_image":
            image = decode_image_payload(payload)
            result = self._submit_image_request(self.face_publisher, request_id, image, "face_image_result")
            return result

        if request_type == "inventory_record":
            record = validate_inventory_payload(payload)
            data = self._write_inventory_record(request_id, record)
            return make_success_response("inventory_record_result", request_id, data)

        raise ProtocolError("UNKNOWN_TYPE", f"Unsupported request type: {request_type}")

    def _submit_image_request(
        self,
        publisher,
        request_id: str,
        image,
        response_type: str,
    ) -> dict[str, Any]:
        pending = PendingResponse(event=threading.Event())
        with self._pending_lock:
            if request_id in self._pending:
                raise ProtocolError("DUPLICATE_REQUEST_ID", f"request_id is already pending: {request_id}")
            self._pending[request_id] = pending

        try:
            msg = bgr_to_image_msg(image, frame_id=request_id)
            msg.header.stamp = self.get_clock().now().to_msg()
            with self._publish_lock:
                publisher.publish(msg)

            if not pending.event.wait(self.request_timeout_sec):
                raise ProtocolError("TIMEOUT", f"Timed out waiting for {response_type}")

            if pending.response is None:
                raise ProtocolError("INTERNAL_ERROR", "Received empty pending response")
            return pending.response
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def _material_result_callback(self, msg: String) -> None:
        self._complete_pending_from_result(msg.data, "material_image_result")

    def _face_result_callback(self, msg: String) -> None:
        self._complete_pending_from_result(msg.data, "face_image_result")

    def _complete_pending_from_result(self, payload_text: str, response_type: str) -> None:
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            self.get_logger().error(f"Received invalid JSON on result topic: {exc}")
            return

        if not isinstance(payload, dict):
            self.get_logger().error("Received non-object JSON on result topic")
            return

        request_id = payload.get("frame_id")
        if not isinstance(request_id, str) or not request_id:
            return

        with self._pending_lock:
            pending = self._pending.get(request_id)

        if pending is None:
            return

        pending.response = make_success_response(response_type, request_id, payload)
        pending.event.set()

    def _write_inventory_record(self, request_id: str, record: InventoryRecord) -> dict[str, Any]:
        received_at = datetime.now().astimezone().isoformat(timespec="seconds")
        rows = [
            {
                "request_id": request_id,
                "record_time": record.record_time,
                "person": record.person,
                "action": record.action,
                "material_name": item.name,
                "quantity": item.quantity,
                "received_at": received_at,
            }
            for item in record.items
        ]

        self.inventory_csv_path.parent.mkdir(parents=True, exist_ok=True)
        with self._csv_lock:
            write_header = not self.inventory_csv_path.exists() or self.inventory_csv_path.stat().st_size == 0
            with self.inventory_csv_path.open("a", newline="", encoding="utf-8") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDNAMES)
                if write_header:
                    writer.writeheader()
                writer.writerows(rows)

        return {
            "csv_path": str(self.inventory_csv_path),
            "rows_written": len(rows),
            "received_at": received_at,
        }

    @staticmethod
    def _generate_request_id() -> str:
        return uuid.uuid4().hex

    def _resolve_request_id(self, value: Any) -> str:
        if value is None:
            return self._generate_request_id()
        text = str(value).strip()
        if not text:
            return self._generate_request_id()
        return text


def main() -> None:
    rclpy.init()
    node = TcpBridgeNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
