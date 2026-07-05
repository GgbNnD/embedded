from __future__ import annotations

import csv
import json
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import rclpy
from rclpy.executors import MultiThreadedExecutor

# ─── 新增: UDP 发现 + ECDH 握手 + 加密协议模块 ───
from server.discovery_handlers import (
    ServerDiscoveryService,
    EcdhSignalingServer,
    ServerPeerKey,
    DATA_PORT as ENCRYPTED_DATA_PORT,
    DISCOVERY_PORT,
    SIGNALING_PORT,
)
from server.encrypted_protocol import (
    recv_encrypted_message,
    send_encrypted_message,
    make_success_ack,
    make_error_ack,
    ConnectionClosedError as EncryptedConnectionClosedError,
    ProtocolError as EncryptedProtocolError,
)
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
    receive_message,
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

HEALTH_LOG_INTERVAL_SEC = 30.0


@dataclass
class PendingResponse:
    event: threading.Event
    response: dict[str, Any] | None = None


@dataclass
class ClientSession:
    address: tuple[str, int]
    connected_at: float
    lock: threading.Lock = field(default_factory=threading.Lock)
    request_count: int = 0
    error_count: int = 0
    bytes_received: int = 0
    bytes_sent: int = 0
    last_active: float = field(default_factory=time.monotonic)


class TcpBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__("tcp_bridge_node")

        self.declare_parameter("host", "0.0.0.0")
        self.declare_parameter("port", 9000)
        self.declare_parameter("request_timeout_sec", 15.0)
        self.declare_parameter("max_connections", 10)
        self.declare_parameter("health_log_interval_sec", HEALTH_LOG_INTERVAL_SEC)
        self.declare_parameter("material_image_topic", "/material_counter/image")
        self.declare_parameter("material_result_topic", "/material_counter/counts")
        self.declare_parameter("face_image_topic", "/face_recognize/image")
        self.declare_parameter("face_result_topic", "/face_recognize/result")
        self.declare_parameter("inventory_csv_path", "auto")

        self.host = str(self.get_parameter("host").value)
        self.port = int(self.get_parameter("port").value)
        self.request_timeout_sec = float(self.get_parameter("request_timeout_sec").value)
        self.max_connections = int(self.get_parameter("max_connections").value)
        if self.max_connections <= 0:
            self.max_connections = 0
        self.health_log_interval_sec = max(5.0, float(self.get_parameter("health_log_interval_sec").value))
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
        self._session_lock = threading.Lock()
        self._sessions: dict[str, ClientSession] = {}
        self._total_requests: int = 0
        self._start_time_sec: float = time.monotonic()

        self._health_timer = self.create_timer(self.health_log_interval_sec, self._log_health_report)

        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen()
        self._accept_thread = threading.Thread(target=self._accept_loop, name="tcp-bridge-accept", daemon=True)
        self._accept_thread.start()

        # ─── 新增: 启动 U[D P 组播发现服务 ───
        # 生成服务器唯一标识
        self._server_device_id = uuid.uuid4().hex
        self._server_device_name = "inventory_server"

        # 初始化 UDP 组播发现服务 (端口 8888)
        self._discovery_service = ServerDiscoveryService(
            device_id=self._server_device_id,
            device_name=self._server_device_name,
            port=DISCOVERY_PORT,
            logger=self.get_logger(),
        )
        self._discovery_service.start()

        # 初始化 ECDH 信令服务器 (端口 8889, 处理客户端密钥交换)
        self._ecdh_server = EcdhSignalingServer(
            port=SIGNALING_PORT,
            logger=self.get_logger(),
        )
        self._ecdh_server.start()

        # 初始化 AES-GCM 加密数据通道监听线程 (端口 8890)
        self._encrypted_data_running = False
        self._encrypted_data_sock = None
        self._encrypted_data_thread = None
        self._encrypted_data_clients = set()
        self._start_encrypted_data_server()

        self.get_logger().info("加密通信服务: 发现=%s, 信令=%s, 数据=%s",
                               DISCOVERY_PORT, SIGNALING_PORT, ENCRYPTED_DATA_PORT)

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

        # ─── 新增: 停止加密通信服务 ───
        self._stop_encrypted_data_server()
        if hasattr(self, '_ecdh_server'):
            self._ecdh_server.stop()
        if hasattr(self, '_discovery_service'):
            self._discovery_service.stop()

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

            peer_key = f"{address[0]}:{address[1]}"
            if self.max_connections > 0:
                with self._session_lock:
                    active = len(self._sessions)
                if active >= self.max_connections:
                    self.get_logger().warn(
                        f"Rejected connection from {peer_key} — {active}/{self.max_connections} slots occupied"
                    )
                    try:
                        client_socket.close()
                    except OSError:
                        pass
                    continue

            client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self._session_lock:
                self._sessions[peer_key] = ClientSession(address=address, connected_at=time.monotonic())
            thread = threading.Thread(
                target=self._client_loop,
                args=(client_socket, address),
                name=f"tcp-client-{peer_key}",
                daemon=True,
            )
            with self._client_lock:
                self._client_sockets.add(client_socket)
                self._client_threads.add(thread)
            thread.start()

    def _client_loop(self, client_socket: socket.socket, address: tuple[str, int]) -> None:
        peer = f"{address[0]}:{address[1]}"
        self.get_logger().info(f"TCP client connected: {peer}  [active={self._active_session_count()}]")

        try:
            while not self._stop_event.is_set():
                request_id: str | None = None
                try:
                    request, attachment = receive_message(client_socket)
                    self._record_session_stats(peer, request_count=1, bytes_recv=len(json.dumps(request, ensure_ascii=False).encode("utf-8")) + len(attachment))
                    request_id = self._resolve_request_id(request.get("request_id"))
                    response = self._handle_request(request, request_id, attachment)
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
                    response_bytes = json.dumps(response, ensure_ascii=False).encode("utf-8")
                    send_json_message(client_socket, response)
                    self._record_session_stats(peer, bytes_sent=len(response_bytes))
                except OSError:
                    break
        finally:
            with self._session_lock:
                self._sessions.pop(peer, None)
            with self._client_lock:
                self._client_sockets.discard(client_socket)
                self._client_threads.discard(threading.current_thread())
            try:
                client_socket.close()
            except OSError:
                pass
            self.get_logger().info(f"TCP client disconnected: {peer}  [active={self._active_session_count()}]")

    def _active_session_count(self) -> int:
        with self._session_lock:
            return len(self._sessions)

    def _record_session_stats(
        self,
        peer: str,
        *,
        request_count: int = 0,
        error_count: int = 0,
        bytes_recv: int = 0,
        bytes_sent: int = 0,
    ) -> None:
        with self._session_lock:
            session = self._sessions.get(peer)
        if session is None:
            return
        with session.lock:
            session.request_count += request_count
            session.error_count += error_count
            session.bytes_received += bytes_recv
            session.bytes_sent += bytes_sent
            session.last_active = time.monotonic()
        self._total_requests += request_count

    def _log_health_report(self) -> None:
        with self._session_lock:
            sessions = list(self._sessions.items())
            total = len(sessions)

        if total == 0:
            self.get_logger().info("TCP health report: 0 active connections")
            return

        uptime_sec = time.monotonic() - self._start_time_sec
        lines = [f"TCP health report — uptime {uptime_sec:.0f}s, {total} connections, {self._total_requests} total requests"]
        for peer, session in sessions:
            with session.lock:
                conn_sec = time.monotonic() - session.connected_at
                lines.append(
                    f"  {peer}  id={conn_sec:.0f}s  req={session.request_count}  "
                    f"err={session.error_count}  rx={session.bytes_received}B  tx={session.bytes_sent}B"
                )
        self.get_logger().info("\n".join(lines))

    def _handle_request(self, request: dict[str, Any], request_id: str, attachment: bytes) -> dict[str, Any]:
        request_type = request.get("type")
        payload = request.get("payload")

        if not isinstance(request_type, str) or not request_type.strip():
            raise ProtocolError("INVALID_REQUEST", "type must be a non-empty string")

        if request_type == "material_image":
            image = decode_image_payload(payload, attachment)
            result = self._submit_image_request(self.material_publisher, request_id, image, "material_image_result")
            return result

        if request_type == "face_image":
            image = decode_image_payload(payload, attachment)
            result = self._submit_image_request(self.face_publisher, request_id, image, "face_image_result")
            return result

        if request_type == "inventory_record":
            if attachment:
                raise ProtocolError("INVALID_REQUEST", "inventory_record does not accept a binary attachment")
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

    # ─── 新增: AES-GCM 加密数据通道服务器 (端口 8890) ───────────────
    #
    # 该通道接收客户端发来的加密出入库记录 (INVENTORY_RECORD),
    # 解密后写入 CSV, 并返回加密的 ACK 响应.
    # 所有通信使用 AES-256-GCM 加密, 密钥由 ECDH 握手中协商产生.
    #
    # 与原有 TCP 桥接 (端口 9000, 明文) 并行运行, 互不影响.

    def _start_encrypted_data_server(self):
        """启动加密数据通道监听 (端口 8890)

        创建 TCP 监听套接字, 启动 accept 线程.
        每个客户端连接在一个独立的 handler 线程中处理.
        """
        self._encrypted_data_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._encrypted_data_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._encrypted_data_sock.bind(("0.0.0.0", ENCRYPTED_DATA_PORT))
        self._encrypted_data_sock.listen(32)
        self._encrypted_data_sock.settimeout(0.2)

        self._encrypted_data_running = True
        self._encrypted_data_thread = threading.Thread(
            target=self._encrypted_accept_loop,
            name="encrypted-data-accept",
            daemon=True,
        )
        self._encrypted_data_thread.start()
        self.get_logger().info("AES-GCM 加密数据通道已启动: 0.0.0.0:%s", ENCRYPTED_DATA_PORT)

    def _stop_encrypted_data_server(self):
        """停止加密数据通道"""
        self._encrypted_data_running = False
        if self._encrypted_data_sock:
            try:
                self._encrypted_data_sock.close()
                self._encrypted_data_sock = None
            except OSError:
                pass
        if self._encrypted_data_thread and self._encrypted_data_thread.is_alive():
            self._encrypted_data_thread.join(timeout=2)

    def _encrypted_accept_loop(self):
        """加密数据通道 accept 循环

        接受客户端 TCP 连接, 为每个连接创建 handler 线程.
        """
        while self._encrypted_data_running:
            if self._encrypted_data_sock is None:
                break
            try:
                client_sock, addr = self._encrypted_data_sock.accept()
            except (socket.timeout, BlockingIOError):
                continue
            except OSError:
                if self._encrypted_data_running:
                    continue
                break

            client_ip = addr[0]
            client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            client_sock.settimeout(15)

            t = threading.Thread(
                target=self._handle_encrypted_client,
                args=(client_sock, client_ip),
                name=f"encrypted-client-{client_ip}",
                daemon=True,
            )
            t.start()
            self._encrypted_data_clients.add(t)

    def _handle_encrypted_client(self, sock, client_ip):
        """处理加密数据通道的单个客户端连接

        持续接收加密消息, 解密后处理出入库记录:
          收到 INVENTORY_RECORD → 写入 CSV → 返回 ACK
          连接关闭或解密失败 → 断开客户端

        Args:
            sock: 客户端 TCP 套接字
            client_ip: 客户端 IP 地址 (用于查找 AES 密钥)
        """
        peer = f"{client_ip}:encrypted"
        self.get_logger().info("加密客户端已连接: %s", peer)

        try:
            while not self._stop_event.is_set():
                # 接收并解密一条消息
                try:
                    msg = recv_encrypted_message(sock, client_ip)
                except (EncryptedConnectionClosedError, EncryptedProtocolError) as e:
                    self.get_logger().warning("加密消息接收失败 [%s]: %s", client_ip, e)
                    break
                except Exception as e:
                    self.get_logger().error("加密通道异常 [%s]: %s", client_ip, e)
                    break

                if msg is None:
                    self.get_logger().warning("加密客户端 %s 发送了空消息", client_ip)
                    continue

                # 处理消息
                response = self._handle_encrypted_request(msg, client_ip)

                # 发送加密的 ACK 响应
                try:
                    send_encrypted_message(sock, response, client_ip)
                except Exception as e:
                    self.get_logger().error("加密响应发送失败 [%s]: %s", client_ip, e)
                    break

        finally:
            try:
                sock.close()
            except OSError:
                pass
            self._encrypted_data_clients.discard(threading.current_thread())
            self.get_logger().info("加密客户端已断开: %s", peer)

    def _handle_encrypted_request(self, msg, client_ip):
        """处理解密后的出入库记录请求

        支持的消息类型:
          - inventory_record: 出入库记录, 写入 CSV

        Args:
            msg: 解密后的 JSON 字典消息
            client_ip: 客户端 IP

        Returns:
            dict: ACK 响应消息 (将被加密后发送回客户端)
        """
        request_type = msg.get("type", "")

        if request_type == "inventory_record":
            return self._process_encrypted_inventory_record(msg)

        # 未知消息类型
        self.get_logger().warning(
            "加密通道收到未知消息类型: %s (来自 %s)", request_type, client_ip
        )
        return make_error_ack(f"不支持的消息类型: {request_type}")

    def _process_encrypted_inventory_record(self, msg):
        """处理加密通道的出入库记录

        复用现有的 CSV 写入逻辑 (_write_inventory_record),
        但不需要 InventoryRecord 数据类 (直接从 msg 提取字段).

        Args:
            msg: 解密后的 INVENTORY_RECORD 消息字典

        Returns:
            ACK 响应
        """
        try:
            # 验证必填字段
            record_time = msg.get("time", "")
            person = msg.get("person", "")
            action = msg.get("action", "")
            items = msg.get("items", [])

            if not record_time or not person or not action or not items:
                return make_error_ack("缺少必填字段: time/person/action/items 不能为空")

            # 标准化 action 字段 (与原有协议兼容)
            normalized_action = action
            if action in ("in", "入库"):
                normalized_action = "入库"
            elif action in ("out", "出库"):
                normalized_action = "出库"

            # 写入 CSV
            received_at = datetime.now().astimezone().isoformat(timespec="seconds")
            request_id = uuid.uuid4().hex
            rows = []
            for item in items:
                if isinstance(item, dict) and "name" in item and "quantity" in item:
                    rows.append({
                        "request_id": request_id,
                        "record_time": record_time,
                        "person": person,
                        "action": normalized_action,
                        "material_name": item["name"],
                        "quantity": item.get("quantity", 0),
                        "received_at": received_at,
                    })

            if not rows:
                return make_error_ack("items 列表为空或格式无效")

            # 写入 CSV 文件
            self.inventory_csv_path.parent.mkdir(parents=True, exist_ok=True)
            with self._csv_lock:
                write_header = (
                    not self.inventory_csv_path.exists()
                    or self.inventory_csv_path.stat().st_size == 0
                )
                with self.inventory_csv_path.open("a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
                    if write_header:
                        writer.writeheader()
                    writer.writerows(rows)

            self.get_logger().info(
                "加密通道: 收到出入库记录 %s (操作人=%s, 操作=%s, 物品数=%s)",
                request_id, person, normalized_action, len(rows),
            )

            return make_success_ack(
                "出入库记录已保存",
                data={
                    "request_id": request_id,
                    "rows_written": len(rows),
                },
            )

        except Exception as e:
            self.get_logger().error("处理加密出入库记录失败: %s", e)
            return make_error_ack(f"服务器内部错误: {e}")


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
