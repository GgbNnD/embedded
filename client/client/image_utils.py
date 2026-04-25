from __future__ import annotations

import cv2
import numpy as np
from sensor_msgs.msg import Image


def image_msg_to_bgr(msg: Image) -> np.ndarray:
    channels_by_encoding = {
        "bgr8": 3,
        "rgb8": 3,
        "mono8": 1,
    }
    if msg.encoding not in channels_by_encoding:
        raise ValueError(f"Unsupported encoding: {msg.encoding}")

    channels = channels_by_encoding[msg.encoding]
    row_width = msg.width * channels
    array = np.frombuffer(msg.data, dtype=np.uint8)
    array = array.reshape((msg.height, msg.step))
    array = array[:, :row_width]

    if channels == 1:
        gray = array.reshape((msg.height, msg.width))
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    image = array.reshape((msg.height, msg.width, 3))
    if msg.encoding == "rgb8":
        image = image[:, :, ::-1]
    return np.ascontiguousarray(image)


def bgr_to_image_msg(image: np.ndarray, *, frame_id: str = "") -> Image:
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Expected a BGR image with shape (H, W, 3)")

    image = np.ascontiguousarray(image)
    msg = Image()
    msg.height = int(image.shape[0])
    msg.width = int(image.shape[1])
    msg.encoding = "bgr8"
    msg.is_bigendian = False
    msg.step = int(image.shape[1] * image.shape[2])
    msg.data = image.tobytes()
    msg.header.frame_id = frame_id
    return msg


def encode_bgr_as_jpeg(image: np.ndarray, *, quality: int = 90) -> bytes:
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Expected a BGR image with shape (H, W, 3)")

    success, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not success:
        raise ValueError("Failed to encode image as JPEG")
    return encoded.tobytes()


def compute_gray_mean(image: np.ndarray) -> float:
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Expected a BGR image with shape (H, W, 3)")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(gray.mean())
