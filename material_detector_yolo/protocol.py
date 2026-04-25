from __future__ import annotations

import json
import socket
from typing import Any


ENCODING = "utf-8"
CHUNK_SIZE = 256000


def recv_exact(sock: socket.socket, size: int) -> bytes:
    if size < 0:
        raise ValueError("size must be >= 0")

    data = bytearray()
    while len(data) < size:
        packet = sock.recv(min(CHUNK_SIZE, size - len(data)))
        if not packet:
            raise ConnectionError("Peer closed connection while receiving data")
        data.extend(packet)
    return bytes(data)


def send_text(sock: socket.socket, text: str) -> None:
    sock.sendall(text.encode(ENCODING))


def recv_text(sock: socket.socket, max_bytes: int = 4096) -> str:
    payload = sock.recv(max_bytes)
    if not payload:
        raise ConnectionError("Peer closed connection while receiving text")
    return payload.decode(ENCODING).strip()


def send_json_payload(sock: socket.socket, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode(ENCODING)
    send_text(sock, f"RESULT,{len(body)}")
    ack = recv_text(sock)
    if ack.lower() != "ok":
        raise ConnectionError(f"Unexpected ack before json body: {ack}")
    sock.sendall(body)


def recv_command_with_length(message: str) -> tuple[str, int]:
    parts = message.split(",", maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f"Invalid command format: {message}")

    command = parts[0].strip().upper()
    try:
        size = int(parts[1].strip())
    except ValueError as exc:
        raise ValueError(f"Invalid payload size in command: {message}") from exc

    if size < 0:
        raise ValueError(f"Payload size must be >= 0: {size}")

    return command, size
