from __future__ import annotations

import json
import queue
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from server.image_utils import resolve_default_inventory_csv_path
from server.inventory_dashboard import build_dashboard_data
from server.inventory_dashboard_page import render_dashboard_page


class DashboardStore:
    def __init__(self, csv_path: Path) -> None:
        self.csv_path = Path(csv_path)
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue[str | None]] = set()
        self._signature = ""
        self._version = 0
        self._payload: dict[str, Any] = {
            "generated_at": "-",
            "source_csv": str(self.csv_path),
            "stats": {
                "material_types": 0,
                "total_quantity": 0,
                "active_people": 0,
                "low_stock_types": 0,
                "total_transactions": 0,
                "latest_event_time": "-",
            },
            "materials": [],
            "recent_events": [],
            "version": 0,
        }
        self._details_map: dict[str, dict[str, Any]] = {}
        self._closed = False

    def refresh(self) -> bool:
        raw_payload, details_map = build_dashboard_data(self.csv_path)
        signature = json.dumps(raw_payload, ensure_ascii=False, sort_keys=True)
        now_text = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            if signature == self._signature:
                return False

            self._version += 1
            self._signature = signature
            self._payload = {
                **raw_payload,
                "generated_at": now_text,
                "version": self._version,
            }
            self._details_map = details_map
            subscribers = list(self._subscribers)
            encoded = json.dumps(self._payload, ensure_ascii=False)

        for subscriber in subscribers:
            self._offer(subscriber, encoded)
        return True

    def get_summary(self) -> dict[str, Any]:
        with self._lock:
            return self._payload

    def get_material_detail(self, material_key: str) -> dict[str, Any] | None:
        with self._lock:
            detail = self._details_map.get(material_key)
            if detail is None:
                return None
            return detail

    def subscribe(self) -> queue.Queue[str | None]:
        subscriber: queue.Queue[str | None] = queue.Queue(maxsize=1)
        with self._lock:
            if self._closed:
                raise RuntimeError("Dashboard store already closed")
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[str | None]) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            subscribers = list(self._subscribers)
            self._subscribers.clear()

        for subscriber in subscribers:
            self._offer(subscriber, None)

    @staticmethod
    def _offer(subscriber: queue.Queue[str | None], value: str | None) -> None:
        try:
            subscriber.put_nowait(value)
            return
        except queue.Full:
            pass

        try:
            subscriber.get_nowait()
        except queue.Empty:
            pass

        try:
            subscriber.put_nowait(value)
        except queue.Full:
            pass


class InventoryDashboardHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class,
        *,
        store: DashboardStore,
        board_title: str,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.store = store
        self.board_title = board_title


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server_version = "EmbeddedInventoryDashboard/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            html_page = render_dashboard_page(self._server.board_title)
            self._send_bytes(200, "text/html; charset=utf-8", html_page.encode("utf-8"))
            return

        if path == "/api/summary":
            self._send_json(self._server.store.get_summary())
            return

        if path.startswith("/api/material/"):
            material_key = unquote(path.replace("/api/material/", "", 1)).strip()
            detail = self._server.store.get_material_detail(material_key)
            if detail is None:
                self._send_json({"error": "material not found", "material_key": material_key}, status=404)
                return
            self._send_json(detail)
            return

        if path == "/api/stream":
            self._handle_stream()
            return

        if path == "/healthz":
            self._send_json({"ok": True})
            return

        self._send_json({"error": "not found", "path": path}, status=404)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    @property
    def _server(self) -> InventoryDashboardHttpServer:
        return cast(InventoryDashboardHttpServer, self.server)

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", body)

    def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle_stream(self) -> None:
        subscriber = self._server.store.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()

            initial_payload = json.dumps(self._server.store.get_summary(), ensure_ascii=False)
            self._write_sse("summary", initial_payload)

            while True:
                try:
                    payload = subscriber.get(timeout=15.0)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue

                if payload is None:
                    break
                self._write_sse("summary", payload)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self._server.store.unsubscribe(subscriber)

    def _write_sse(self, event_name: str, payload: str) -> None:
        message = f"event: {event_name}\ndata: {payload}\n\n".encode("utf-8")
        self.wfile.write(message)
        self.wfile.flush()


class InventoryWebNode(Node):
    def __init__(self) -> None:
        super().__init__("inventory_web_node")

        self.declare_parameter("host", "127.0.0.1")
        self.declare_parameter("port", 8600)
        self.declare_parameter("inventory_csv_path", "auto")
        self.declare_parameter("refresh_interval_sec", 1.0)
        self.declare_parameter("board_title", "嵌入式物资实时看板")

        inventory_csv_path_value = str(self.get_parameter("inventory_csv_path").value).strip()
        if not inventory_csv_path_value or inventory_csv_path_value == "auto":
            inventory_csv_path = resolve_default_inventory_csv_path()
        else:
            inventory_csv_path = Path(inventory_csv_path_value).expanduser().resolve()

        self.host = str(self.get_parameter("host").value)
        self.port = int(self.get_parameter("port").value)
        self.refresh_interval_sec = max(0.5, float(self.get_parameter("refresh_interval_sec").value))
        self.board_title = str(self.get_parameter("board_title").value).strip() or "嵌入式物资实时看板"

        self._store = DashboardStore(inventory_csv_path)
        self._store.refresh()

        self._http_server = InventoryDashboardHttpServer(
            (self.host, self.port),
            DashboardRequestHandler,
            store=self._store,
            board_title=self.board_title,
        )
        self._http_thread = threading.Thread(
            target=self._http_server.serve_forever,
            kwargs={"poll_interval": 0.5},
            name="inventory-dashboard-http",
            daemon=True,
        )
        self._http_thread.start()
        self._refresh_timer = self.create_timer(self.refresh_interval_sec, self._refresh_dashboard)

        self.get_logger().info(f"Inventory dashboard CSV: {inventory_csv_path}")
        self.get_logger().info(f"Inventory dashboard available at: http://{self.host}:{self.port}")
        self.get_logger().info(f"Refresh interval: {self.refresh_interval_sec:.1f}s")

    def destroy_node(self) -> bool:
        self._store.close()
        self._http_server.shutdown()
        self._http_server.server_close()
        if self._http_thread.is_alive():
            self._http_thread.join(timeout=1.0)
        return super().destroy_node()

    def _refresh_dashboard(self) -> None:
        try:
            self._store.refresh()
        except Exception as exc:
            self.get_logger().error(f"Failed to refresh inventory dashboard: {exc}")


def main() -> None:
    rclpy.init()
    node = InventoryWebNode()
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
