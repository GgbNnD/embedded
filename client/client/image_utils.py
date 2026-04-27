from __future__ import annotations

import cv2
import numpy as np


def ensure_bgr_image(image: np.ndarray) -> np.ndarray:
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Expected a BGR image with shape (H, W, 3)")
    return np.ascontiguousarray(image)


def encode_bgr_as_jpeg(image: np.ndarray, *, quality: int = 90) -> bytes:
    image = ensure_bgr_image(image)
    success, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not success:
        raise ValueError("Failed to encode image as JPEG")
    return encoded.tobytes()


def compute_gray_mean(image: np.ndarray) -> float:
    image = ensure_bgr_image(image)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(gray.mean())
