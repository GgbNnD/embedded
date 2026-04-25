from __future__ import annotations

import base64
import json
import socket
import threading
import uuid
from typing import Any

import rclpy
from rclpy.node import Node

from client.image_utils import encode_bgr_as_jpeg, image_msg_to_bgr
from client.srv import SendServerRequest
from client.tcp_protocol import ConnectionClosedError, ProtocolError, receive_json_message, send_json_message


class TcpClientNode(Node):
    def __init__(self) -> None:
        super().__init__("tcp_client_node")

        self.declare_parameter("server_host", "127.0.0.1")
        self.declare_parameter("server_port", 9000)
        self.declare_parameter("connect_timeout_sec", 3.0)
        self.declare_parameter("request_timeout_sec", 15.0)
        self.declare_parameter("jpeg_quality", 90)
        self.declare_parameter("service_name", "/client/tcp/send_server_request")

        self.server_host = str(self.get_parameter("server_host").value)
        self.server_port = int(self.get_parameter("server_port").value)
        self.connect_timeout_sec = float(self.get_parameter("connect_timeout_sec").value)
        self.request_timeout_sec = float(self.get_parameter("request_timeout_sec").value)
        self.jpeg_quality = int(self.get_parameter("jpeg_quality").value)

        service_name = str(self.get_parameter("service_name").value)

        self._socket_lock = threading.Lock()
        self._socket: socket.socket | None = None
        self._service = self.create_service(SendServerRequest, service_name, self._handle_send_server_request)

        self.get_logger().info(f"TCP server endpoint: {self.server_host}:{self.server_port}")
        self.get_logger().info(f"Service name: {service_name}")

    def _ensure_connection(self) -> socket.socket:
        if self._socket is not None:
            return self._socket

        sock = socket.create_connection((self.server_host, self.server_port), timeout=self.connect_timeout_sec)
        sock.settimeout(self.request_timeout_sec)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._socket = sock
        self.get_logger().info(f"Connected to TCP server {self.server_host}:{self.server_port}")
        return sock

    def _close_socket(self) -> None:
        if self._socket is None:
            return

        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._socket.close()
        except OSError:
            pass
        self._socket = None

    def _handle_send_server_request(
        self,
        request: SendServerRequest.Request,
        response: SendServerRequest.Response,
    ) -> SendServerRequest.Response:
        try:
            body = self._build_request_body(request)
        except Exception as exc:
            response.ok = False
            response.code = "INVALID_REQUEST"
            response.message = str(exc)
            return response

        try:
            payload = self._perform_request(body)
        except (OSError, TimeoutError, ConnectionClosedError) as exc:
            response.ok = False
            response.code = "TCP_ERROR"
            response.message = str(exc)
            return response
        except ProtocolError as exc:
            response.ok = False
            response.code = "PROTOCOL_ERROR"
            response.message = str(exc)
            return response
        except Exception as exc:
            response.ok = False
            response.code = "INTERNAL_ERROR"
            response.message = str(exc)
            return response

        response.response_json = json.dumps(payload, ensure_ascii=False)
        if payload.get("ok") is True:
            response.ok = True
            response.code = ""
            response.message = "Request completed successfully"
        else:
            error = payload.get("error")
            if not isinstance(error, dict):
                response.ok = False
                response.code = "INVALID_RESPONSE"
                response.message = "Server returned an invalid error payload"
            else:
                response.ok = False
                response.code = str(error.get("code", "UNKNOWN_ERROR"))
                response.message = str(error.get("message", "Server returned an error"))
        return response

    def _build_request_body(self, request: SendServerRequest.Request) -> dict[str, Any]:
        request_type = request.request_type.strip()
        if request_type not in {"face_image", "material_image", "inventory_record"}:
            raise ValueError(f"Unsupported request type: {request.request_type}")

        payload: dict[str, Any]
        if request_type in {"face_image", "material_image"}:
            image = image_msg_to_bgr(request.image)
            image_base64 = base64.b64encode(encode_bgr_as_jpeg(image, quality=self.jpeg_quality)).decode("ascii")
            payload = {
                "image_base64": image_base64,
                "image_format": "jpg",
            }
        else:
            if not request.payload_json.strip():
                raise ValueError("payload_json is required for inventory_record")
            inventory_payload = json.loads(request.payload_json)
            if not isinstance(inventory_payload, dict):
                raise ValueError("payload_json must decode to a JSON object")
            payload = inventory_payload

        return {
            "type": request_type,
            "request_id": uuid.uuid4().hex,
            "payload": payload,
        }

    def _perform_request(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._socket_lock:
            last_error: Exception | None = None
            for _ in range(2):
                try:
                    sock = self._ensure_connection()
                    send_json_message(sock, body)
                    return receive_json_message(sock)
                except (OSError, TimeoutError, ConnectionClosedError, ProtocolError) as exc:
                    last_error = exc
                    self._close_socket()
            if last_error is None:
                raise RuntimeError("TCP request failed without an exception")
            raise last_error

    def destroy_node(self) -> bool:
        with self._socket_lock:
            self._close_socket()
        return super().destroy_node()


def main() -> None:
    rclpy.init()
    node = TcpClientNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
