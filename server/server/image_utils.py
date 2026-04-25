from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from ament_index_python.packages import get_package_share_directory
from sensor_msgs.msg import Image


def resolve_default_model_path() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "weights" / "materials_yolo" / "best.pt"
        if candidate.exists():
            return candidate

    share_dir = Path(get_package_share_directory("server"))
    packaged_model = share_dir / "models" / "best.pt"
    if packaged_model.exists():
        return packaged_model

    raise FileNotFoundError("Unable to locate weights/materials_yolo/best.pt")


def resolve_default_known_face_dir() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "assets" / "known_face"
        if candidate.exists():
            return candidate

    share_dir = Path(get_package_share_directory("server"))
    packaged_dir = share_dir / "assets" / "known_face"
    if packaged_dir.exists():
        return packaged_dir

    raise FileNotFoundError("Unable to locate server/assets/known_face directory")


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


def load_bgr_image(image_path: str) -> np.ndarray:
    image = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Failed to read image: {image_path}")
    return image
