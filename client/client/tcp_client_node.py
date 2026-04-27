from __future__ import annotations

import base64
import json
import logging
import socket
import threading
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np

from client.config import build_argument_parser, config_from_args
from client.image_utils import encode_bgr_as_jpeg
from client.tcp_protocol import ConnectionClosedError, ProtocolError, receive_json_message, send_json_message


@dataclass(slots=True)
class ServerRequestResult:
    ok: bool
    code: str
    message: str
    response_json: str = ""


class TcpClientNode:
    def __init__(
        self,
        *,
        server_host: str = "127.0.0.1",
        server_port: int = 9000,
        connect_timeout_sec: float = 3.0,
        request_timeout_sec: float = 15.0,
        jpeg_quality: int = 90,
        logger: logging.Logger | None = None,
    ) -> None:
        self.logger = logger or logging.getLogger("client.tcp")
        self.server_host = server_host
        self.server_port = int(server_port)
        self.connect_timeout_sec = float(connect_timeout_sec)
        self.request_timeout_sec = float(request_timeout_sec)
        self.jpeg_quality = int(jpeg_quality)

        self._socket_lock = threading.Lock()
        self._socket: socket.socket | None = None

    def close(self) -> None:
        with self._socket_lock:
            self._close_socket_locked()

    def check_connection(self) -> tuple[bool, str]:
        try:
            with self._socket_lock:
                self._ensure_connection_locked()
            return True, f"Connected to {self.server_host}:{self.server_port}"
        except Exception as exc:
            return False, str(exc)

    def send_server_request(
        self,
        *,
        request_type: str,
        image: np.ndarray | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ServerRequestResult:
        try:
            body = self._build_request_body(request_type=request_type, image=image, payload=payload)
        except Exception as exc:
            return ServerRequestResult(ok=False, code="INVALID_REQUEST", message=str(exc))

        try:
            response_payload = self._perform_request(body)
        except (OSError, TimeoutError, ConnectionClosedError) as exc:
            return ServerRequestResult(ok=False, code="TCP_ERROR", message=str(exc))
        except ProtocolError as exc:
            return ServerRequestResult(ok=False, code="PROTOCOL_ERROR", message=str(exc))
        except Exception as exc:
            return ServerRequestResult(ok=False, code="INTERNAL_ERROR", message=str(exc))

        response_json = json.dumps(response_payload, ensure_ascii=False)
        if response_payload.get("ok") is True:
            return ServerRequestResult(
                ok=True,
                code="",
                message="Request completed successfully",
                response_json=response_json,
            )

        error = response_payload.get("error")
        if not isinstance(error, dict):
            return ServerRequestResult(
                ok=False,
                code="INVALID_RESPONSE",
                message="Server returned an invalid error payload",
                response_json=response_json,
            )

        return ServerRequestResult(
            ok=False,
            code=str(error.get("code", "UNKNOWN_ERROR")),
            message=str(error.get("message", "Server returned an error")),
            response_json=response_json,
        )

    def _build_request_body(
        self,
        *,
        request_type: str,
        image: np.ndarray | None,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        normalized_type = request_type.strip()
        if normalized_type not in {"face_image", "material_image", "inventory_record"}:
            raise ValueError(f"Unsupported request type: {request_type}")

        if normalized_type in {"face_image", "material_image"}:
            if image is None:
                raise ValueError(f"image is required for {normalized_type}")
            request_payload: dict[str, Any] = {
                "image_base64": base64.b64encode(encode_bgr_as_jpeg(image, quality=self.jpeg_quality)).decode("ascii"),
                "image_format": "jpg",
            }
        else:
            if not isinstance(payload, dict):
                raise ValueError("payload is required for inventory_record")
            request_payload = payload

        return {
            "type": normalized_type,
            "request_id": uuid.uuid4().hex,
            "payload": request_payload,
        }

    def _perform_request(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._socket_lock:
            last_error: Exception | None = None
            for _ in range(2):
                try:
                    sock = self._ensure_connection_locked()
                    send_json_message(sock, body)
                    return receive_json_message(sock)
                except (OSError, TimeoutError, ConnectionClosedError, ProtocolError) as exc:
                    last_error = exc
                    self._close_socket_locked()

        if last_error is None:
            raise RuntimeError("TCP request failed without an exception")
        raise last_error

    def _ensure_connection_locked(self) -> socket.socket:
        if self._socket is not None:
            return self._socket

        sock = socket.create_connection((self.server_host, self.server_port), timeout=self.connect_timeout_sec)
        sock.settimeout(self.request_timeout_sec)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._socket = sock
        self.logger.info("Connected to TCP server %s:%s", self.server_host, self.server_port)
        return sock

    def _close_socket_locked(self) -> None:
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


def main(argv: list[str] | None = None) -> None:
    parser = build_argument_parser(
        "Check whether the standalone client can connect to the remote TCP server.",
        include_camera=False,
        include_server=True,
        include_workflow=False,
    )
    args = parser.parse_args(argv)
    config = config_from_args(args)

    logging.basicConfig(level=getattr(logging, config.log_level), format="[%(levelname)s] %(name)s: %(message)s")
    tcp_client = TcpClientNode(
        server_host=config.server_host,
        server_port=config.server_port,
        connect_timeout_sec=config.connect_timeout_sec,
        request_timeout_sec=config.request_timeout_sec,
        jpeg_quality=config.jpeg_quality,
    )

    try:
        ok, message = tcp_client.check_connection()
        if not ok:
            raise RuntimeError(message)
        print(message)
    finally:
        tcp_client.close()


if __name__ == "__main__":
    main()
