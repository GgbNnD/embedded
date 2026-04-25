from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import cv2

from protocol import recv_exact, recv_text, send_text


def capture_with_rpicam(output_path: Path, width: int, height: int) -> None:
    command = [
        "rpicam-still",
        "-n",
        "-t",
        "1",
        "--width",
        str(width),
        "--height",
        str(height),
        "-o",
        str(output_path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def capture_with_opencv(output_path: Path, width: int, height: int) -> None:
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("OpenCV camera open failed")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError("OpenCV camera capture failed")

    success = cv2.imwrite(str(output_path), frame)
    if not success:
        raise RuntimeError(f"Failed to write image: {output_path}")


def capture_frame(output_path: Path, width: int, height: int, backend: str) -> None:
    if backend == "rpicam":
        capture_with_rpicam(output_path, width, height)
        return

    if backend == "opencv":
        capture_with_opencv(output_path, width, height)
        return

    try:
        capture_with_rpicam(output_path, width, height)
    except Exception:
        capture_with_opencv(output_path, width, height)


def send_detect_request(host: str, port: int, image_bytes: bytes, timeout: float) -> dict[str, Any]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect((host, port))

        send_text(sock, f"DETECT_MATERIALS,{len(image_bytes)}")
        ack = recv_text(sock)
        if ack.lower() != "ok":
            raise RuntimeError(f"Unexpected server ack: {ack}")

        sock.sendall(image_bytes)

        header = recv_text(sock)
        if not header.startswith("RESULT,"):
            raise RuntimeError(f"Unexpected server header: {header}")

        _, length_text = header.split(",", maxsplit=1)
        payload_len = int(length_text)
        send_text(sock, "ok")
        body = recv_exact(sock, payload_len)

    return json.loads(body.decode("utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Raspberry Pi image capture client for material detection")
    parser.add_argument("--host", required=True, help="server host")
    parser.add_argument("--port", type=int, default=8090, help="server port")
    parser.add_argument("--image", default="", help="existing image path (skip camera capture)")
    parser.add_argument("--backend", choices=["auto", "rpicam", "opencv"], default="auto")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.image:
        image_path = Path(args.image).expanduser().resolve()
        if not image_path.is_file():
            raise FileNotFoundError(f"Image not found: {image_path}")
        image_bytes = image_path.read_bytes()
        source_label = str(image_path)
    else:
        tmp_dir = Path(tempfile.gettempdir())
        image_path = tmp_dir / "material_capture.jpg"
        capture_frame(image_path, width=args.width, height=args.height, backend=args.backend)
        image_bytes = image_path.read_bytes()
        source_label = f"camera:{args.backend}"

    result = send_detect_request(
        host=args.host,
        port=args.port,
        image_bytes=image_bytes,
        timeout=args.timeout,
    )

    print(f"[client] source: {source_label}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
