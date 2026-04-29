from __future__ import annotations

import base64
import binascii
import json
import socket
import struct
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


MESSAGE_PREFIX = struct.Struct("!II")
SUPPORTED_IMAGE_FORMATS = {"jpg", "jpeg", "png", "webp"}


class ConnectionClosedError(RuntimeError):
    """Raised when the peer closes the TCP connection."""


class ProtocolError(ValueError):
    """Raised when a TCP request violates the expected protocol."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class InventoryItem:
    name: str
    quantity: int | float


@dataclass(frozen=True)
class InventoryRecord:
    record_time: str
    person: str
    action: str
    items: list[InventoryItem]


def recv_exactly(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        data = sock.recv(size - len(chunks))
        if not data:
            raise ConnectionClosedError("Peer closed the connection")
        chunks.extend(data)
    return bytes(chunks)


def receive_message(sock: socket.socket) -> tuple[dict[str, Any], bytes]:
    header = recv_exactly(sock, MESSAGE_PREFIX.size)
    message_length, attachment_length = MESSAGE_PREFIX.unpack(header)
    if message_length <= 0:
        raise ProtocolError("INVALID_LENGTH", "Message length must be greater than 0")
    if attachment_length < 0:
        raise ProtocolError("INVALID_LENGTH", "Attachment length must not be negative")

    body = recv_exactly(sock, message_length)
    attachment = recv_exactly(sock, attachment_length) if attachment_length else b""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("INVALID_JSON", f"Failed to decode JSON body: {exc}") from exc

    if not isinstance(payload, dict):
        raise ProtocolError("INVALID_REQUEST", "Top-level JSON payload must be an object")
    return payload, attachment


def receive_json_message(sock: socket.socket) -> dict[str, Any]:
    payload, attachment = receive_message(sock)
    if attachment:
        raise ProtocolError("INVALID_REQUEST", "Expected a JSON-only message but received a binary attachment")
    return payload


def send_message(sock: socket.socket, payload: dict[str, Any], attachment: bytes = b"") -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sock.sendall(MESSAGE_PREFIX.pack(len(encoded), len(attachment)) + encoded + attachment)


def send_json_message(sock: socket.socket, payload: dict[str, Any]) -> None:
    send_message(sock, payload)


def decode_image_payload(payload: Any, image_bytes: bytes | None = None) -> np.ndarray:
    if not isinstance(payload, dict):
        raise ProtocolError("INVALID_PAYLOAD", "Payload must be an object")

    image_format = payload.get("image_format")
    if image_format is not None:
        if not isinstance(image_format, str) or image_format.lower() not in SUPPORTED_IMAGE_FORMATS:
            supported = ", ".join(sorted(SUPPORTED_IMAGE_FORMATS))
            raise ProtocolError("INVALID_IMAGE_FORMAT", f"payload.image_format must be one of: {supported}")

    expected_size = payload.get("image_size_bytes")
    if expected_size is not None:
        if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
            raise ProtocolError("INVALID_IMAGE", "payload.image_size_bytes must be a non-negative integer")

    if image_bytes:
        image_encoding = payload.get("image_encoding")
        if image_encoding is not None and image_encoding != "binary":
            raise ProtocolError("INVALID_IMAGE", "payload.image_encoding must be 'binary' when a binary attachment is sent")
        if expected_size is not None and expected_size != len(image_bytes):
            raise ProtocolError("INVALID_IMAGE", "payload.image_size_bytes does not match the binary attachment size")
    else:
        image_base64 = payload.get("image_base64")
        if not isinstance(image_base64, str) or not image_base64.strip():
            raise ProtocolError(
                "INVALID_IMAGE",
                "payload.image_base64 must be a non-empty string when no binary attachment is sent",
            )
        try:
            image_bytes = base64.b64decode(image_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ProtocolError("INVALID_IMAGE", f"payload.image_base64 is not valid base64: {exc}") from exc

    if not image_bytes:
        raise ProtocolError("INVALID_IMAGE", "Decoded image bytes are empty")

    buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise ProtocolError("INVALID_IMAGE", "Failed to decode image bytes as jpg/png/webp")
    return np.ascontiguousarray(image)


def validate_inventory_payload(payload: Any) -> InventoryRecord:
    if not isinstance(payload, dict):
        raise ProtocolError("INVALID_PAYLOAD", "Payload must be an object")

    record_time = payload.get("time")
    if not isinstance(record_time, str) or not record_time.strip():
        raise ProtocolError("INVALID_INVENTORY", "payload.time must be a non-empty string")

    person = payload.get("person")
    if not isinstance(person, str) or not person.strip():
        raise ProtocolError("INVALID_INVENTORY", "payload.person must be a non-empty string")

    action = normalize_action(payload.get("action"))

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ProtocolError("INVALID_INVENTORY", "payload.items must be a non-empty array")

    normalized_items: list[InventoryItem] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ProtocolError("INVALID_INVENTORY", f"payload.items[{index}] must be an object")

        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ProtocolError("INVALID_INVENTORY", f"payload.items[{index}].name must be a non-empty string")

        quantity = normalize_quantity(item.get("quantity"), index=index)
        normalized_items.append(InventoryItem(name=name.strip(), quantity=quantity))

    return InventoryRecord(
        record_time=record_time.strip(),
        person=person.strip(),
        action=action,
        items=normalized_items,
    )


def normalize_action(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError("INVALID_INVENTORY", "payload.action must be a non-empty string")

    normalized = value.strip().lower()
    if normalized in {"入库", "in"}:
        return "入库"
    if normalized in {"出库", "out"}:
        return "出库"
    raise ProtocolError("INVALID_INVENTORY", "payload.action must be one of: 入库, 出库, in, out")


def normalize_quantity(value: Any, *, index: int) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError("INVALID_INVENTORY", f"payload.items[{index}].quantity must be numeric")

    if isinstance(value, int):
        return value

    if not np.isfinite(value):
        raise ProtocolError("INVALID_INVENTORY", f"payload.items[{index}].quantity must be finite")

    if float(value).is_integer():
        return int(value)
    return float(value)


def make_success_response(response_type: str, request_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "type": response_type,
        "request_id": request_id,
        "data": data,
    }


def make_error_response(code: str, message: str, request_id: str | None) -> dict[str, Any]:
    return {
        "ok": False,
        "type": "error",
        "request_id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
