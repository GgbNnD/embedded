from __future__ import annotations

import base64
import socket
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from tcp_protocol import (  # noqa: E402
    ConnectionClosedError,
    ProtocolError,
    decode_image_payload,
    receive_json_message,
    send_json_message,
    validate_inventory_payload,
)


class TcpProtocolTests(unittest.TestCase):
    def test_send_and_receive_json_message(self) -> None:
        left, right = socket.socketpair()
        try:
            payload = {"type": "inventory_record", "request_id": "req-1", "payload": {"value": 1}}
            send_json_message(left, payload)
            decoded = receive_json_message(right)
            self.assertEqual(decoded, payload)
        finally:
            left.close()
            right.close()

    def test_receive_json_message_rejects_invalid_json(self) -> None:
        left, right = socket.socketpair()
        try:
            left.sendall((4).to_bytes(4, "big") + b"nope")
            with self.assertRaises(ProtocolError) as context:
                receive_json_message(right)
            self.assertEqual(context.exception.code, "INVALID_JSON")
        finally:
            left.close()
            right.close()

    def test_receive_json_message_detects_disconnect(self) -> None:
        left, right = socket.socketpair()
        try:
            left.close()
            with self.assertRaises(ConnectionClosedError):
                receive_json_message(right)
        finally:
            right.close()

    def test_decode_image_payload(self) -> None:
        image = np.zeros((8, 8, 3), dtype=np.uint8)
        image[:, :] = (10, 20, 30)
        success, buffer = cv2.imencode(".jpg", image)
        self.assertTrue(success)

        decoded = decode_image_payload(
            {
                "image_base64": base64.b64encode(buffer.tobytes()).decode("ascii"),
                "image_format": "jpg",
            }
        )

        self.assertEqual(decoded.shape, image.shape)

    def test_decode_image_payload_rejects_bad_base64(self) -> None:
        with self.assertRaises(ProtocolError) as context:
            decode_image_payload({"image_base64": "%%%", "image_format": "jpg"})
        self.assertEqual(context.exception.code, "INVALID_IMAGE")

    def test_validate_inventory_payload_normalizes_action_and_quantity(self) -> None:
        record = validate_inventory_payload(
            {
                "time": "2026-04-25T21:30:00+08:00",
                "person": "cells",
                "action": "out",
                "items": [
                    {"name": "cboard", "quantity": 2.0},
                    {"name": "m3508", "quantity": 1.5},
                ],
            }
        )

        self.assertEqual(record.action, "出库")
        self.assertEqual(record.items[0].quantity, 2)
        self.assertEqual(record.items[1].quantity, 1.5)

    def test_validate_inventory_payload_rejects_bad_quantity(self) -> None:
        with self.assertRaises(ProtocolError) as context:
            validate_inventory_payload(
                {
                    "time": "2026-04-25T21:30:00+08:00",
                    "person": "cells",
                    "action": "in",
                    "items": [{"name": "cboard", "quantity": "two"}],
                }
            )
        self.assertEqual(context.exception.code, "INVALID_INVENTORY")


if __name__ == "__main__":
    unittest.main()
