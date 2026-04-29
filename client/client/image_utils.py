from __future__ import annotations

import cv2
import numpy as np

SUPPORTED_IMAGE_FORMATS = {"jpg", "jpeg", "png", "webp"}


def ensure_bgr_image(image: np.ndarray) -> np.ndarray:
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Expected a BGR image with shape (H, W, 3)")
    return np.ascontiguousarray(image)


def normalize_image_format(image_format: str) -> str:
    normalized = image_format.strip().lower()
    if normalized not in SUPPORTED_IMAGE_FORMATS:
        supported = ", ".join(sorted(SUPPORTED_IMAGE_FORMATS))
        raise ValueError(f"Unsupported image_format '{image_format}', expected one of: {supported}")
    return normalized


def encode_bgr_image(image: np.ndarray, *, image_format: str = "webp", quality: int = 75) -> bytes:
    image = ensure_bgr_image(image)
    normalized_format = normalize_image_format(image_format)
    quality = max(1, min(int(quality), 100))

    if normalized_format in {"jpg", "jpeg"}:
        extension = ".jpg"
        params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    elif normalized_format == "webp":
        extension = ".webp"
        params = [int(cv2.IMWRITE_WEBP_QUALITY), quality]
    else:
        extension = ".png"
        compression = int(round((100 - quality) * 9 / 99))
        params = [int(cv2.IMWRITE_PNG_COMPRESSION), max(0, min(compression, 9))]

    success, encoded = cv2.imencode(extension, image, params)
    if not success:
        raise ValueError(f"Failed to encode image as {normalized_format}")
    return encoded.tobytes()


def encode_bgr_as_jpeg(image: np.ndarray, *, quality: int = 90) -> bytes:
    return encode_bgr_image(image, image_format="jpg", quality=quality)


def compute_gray_mean(image: np.ndarray) -> float:
    image = ensure_bgr_image(image)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(gray.mean())
