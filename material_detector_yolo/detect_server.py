from __future__ import annotations

import argparse
import socket
import threading
from typing import Any

from detector import MaterialDetector
from protocol import recv_command_with_length, recv_exact, recv_text, send_json_payload, send_text


class MaterialDetectServer:
    def __init__(
        self,
        host: str,
        port: int,
        detector: MaterialDetector,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.detector = detector
        self.server_socket: socket.socket | None = None
        self.running = False

    def start(self) -> None:
        if self.running:
            return

        self.running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.server_socket.settimeout(1.0)

        print(f"[server] listening on {self.host or '0.0.0.0'}:{self.port}")
        print(f"[server] detector model: {self.detector.model_path}")
        print(f"[server] detector device: {self.detector.device}")

        try:
            while self.running:
                try:
                    client_socket, client_address = self.server_socket.accept()
                except socket.timeout:
                    continue

                worker = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, client_address),
                    daemon=True,
                )
                worker.start()
        finally:
            self.stop()

    def stop(self) -> None:
        if not self.running and self.server_socket is None:
            return

        self.running = False
        if self.server_socket is not None:
            try:
                self.server_socket.close()
            except OSError:
                pass
            self.server_socket = None
        print("[server] stopped")

    def handle_client(self, client_socket: socket.socket, address: tuple[str, int]) -> None:
        client_socket.settimeout(self.timeout)
        print(f"[client] connected: {address}")

        try:
            while self.running:
                try:
                    message = recv_text(client_socket, max_bytes=4096)
                except ConnectionError:
                    break

                if not message:
                    break

                command, payload_size = recv_command_with_length(message)
                if command != "DETECT_MATERIALS":
                    response: dict[str, Any] = {
                        "ok": False,
                        "error": f"Unknown command: {command}",
                    }
                    send_json_payload(client_socket, response)
                    continue

                send_text(client_socket, "ok")
                image_bytes = recv_exact(client_socket, payload_size)

                try:
                    result = self.detector.predict_jpeg_bytes(image_bytes)
                    response = {
                        "ok": True,
                        "counts": result["counts"],
                        "total_objects": result["total_objects"],
                        "detections": result["detections"],
                        "latency_ms": result["latency_ms"],
                        "device": result["device"],
                    }
                except Exception as exc:
                    response = {
                        "ok": False,
                        "error": str(exc),
                    }

                send_json_payload(client_socket, response)
        except Exception as exc:
            print(f"[client] error {address}: {exc}")
        finally:
            try:
                client_socket.close()
            except OSError:
                pass
            print(f"[client] disconnected: {address}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YOLO material detection server")
    parser.add_argument("--host", default="", help="bind host, default all interfaces")
    parser.add_argument("--port", type=int, default=8090, help="bind port")
    parser.add_argument("--model", required=True, help="YOLO model path (.pt/.onnx)")
    parser.add_argument("--classes", default="", help="class names txt file (optional)")
    parser.add_argument("--device", default="auto", help="cuda device index, cuda:0, or cpu")
    parser.add_argument("--conf", type=float, default=0.35, help="confidence threshold")
    parser.add_argument("--iou", type=float, default=0.45, help="IoU threshold")
    parser.add_argument("--imgsz", type=int, default=640, help="inference image size")
    parser.add_argument("--timeout", type=float, default=15.0, help="socket timeout seconds")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    detector = MaterialDetector(
        model_path=args.model,
        class_names=args.classes or None,
        conf_threshold=args.conf,
        iou_threshold=args.iou,
        device=args.device,
        imgsz=args.imgsz,
    )

    server = MaterialDetectServer(
        host=args.host,
        port=args.port,
        detector=detector,
        timeout=args.timeout,
    )

    try:
        server.start()
    except KeyboardInterrupt:
        print("\n[server] keyboard interrupt")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
