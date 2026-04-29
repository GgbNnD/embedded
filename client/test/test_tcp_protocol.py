from __future__ import annotations

import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))

from tcp_protocol import (  # noqa: E402
    ConnectionClosedError,
    ProtocolError,
    receive_json_message,
    receive_message,
    send_json_message,
    send_message,
)


class TcpProtocolTests(unittest.TestCase):
    def test_send_and_receive_json_message(self) -> None:
        left, right = socket.socketpair()
        try:
            payload = {"type": "face_image", "request_id": "req-1", "payload": {"hello": "world"}}
            send_json_message(left, payload)
            self.assertEqual(receive_json_message(right), payload)
        finally:
            left.close()
            right.close()

    def test_receive_json_message_rejects_invalid_json(self) -> None:
        left, right = socket.socketpair()
        try:
            left.sendall((4).to_bytes(4, "big") + (0).to_bytes(4, "big") + b"oops")
            with self.assertRaises(ProtocolError):
                receive_json_message(right)
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

    def test_send_and_receive_message_with_binary_attachment(self) -> None:
        left, right = socket.socketpair()
        try:
            payload = {"type": "material_image", "request_id": "req-2", "payload": {"image_format": "webp"}}
            attachment = b"compressed-image"
            send_message(left, payload, attachment)
            decoded_payload, decoded_attachment = receive_message(right)
            self.assertEqual(decoded_payload, payload)
            self.assertEqual(decoded_attachment, attachment)
        finally:
            left.close()
            right.close()

    def test_receive_json_message_rejects_binary_attachment(self) -> None:
        left, right = socket.socketpair()
        try:
            send_message(left, {"type": "face_image"}, b"abc")
            with self.assertRaises(ProtocolError):
                receive_json_message(right)
        finally:
            left.close()
            right.close()


if __name__ == "__main__":
    unittest.main()
