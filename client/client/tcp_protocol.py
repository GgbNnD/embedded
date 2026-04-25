from __future__ import annotations

import json
import socket
import struct
from typing import Any


LENGTH_PREFIX = struct.Struct("!I")


class ConnectionClosedError(RuntimeError):
    """Raised when the remote peer closes the TCP connection."""


class ProtocolError(ValueError):
    """Raised when a TCP payload does not match the expected protocol."""


def recv_exactly(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        data = sock.recv(size - len(chunks))
        if not data:
            raise ConnectionClosedError("Peer closed the connection")
        chunks.extend(data)
    return bytes(chunks)


def send_json_message(sock: socket.socket, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sock.sendall(LENGTH_PREFIX.pack(len(encoded)) + encoded)


def receive_json_message(sock: socket.socket) -> dict[str, Any]:
    header = recv_exactly(sock, LENGTH_PREFIX.size)
    (message_length,) = LENGTH_PREFIX.unpack(header)
    if message_length <= 0:
        raise ProtocolError("Message length must be greater than 0")

    body = recv_exactly(sock, message_length)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"Failed to decode JSON body: {exc}") from exc

    if not isinstance(payload, dict):
        raise ProtocolError("Top-level JSON payload must be an object")
    return payload
