from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

import cv2
import numpy as np


def _normalize_names(raw_names: Any) -> dict[int, str]:
    if raw_names is None:
        return {}

    if isinstance(raw_names, dict):
        normalized: dict[int, str] = {}
        for key, value in raw_names.items():
            try:
                class_id = int(key)
            except (TypeError, ValueError):
                continue
            normalized[class_id] = str(value)
        return normalized

    if isinstance(raw_names, (list, tuple)):
        return {index: str(value) for index, value in enumerate(raw_names)}

    return {}


def load_class_names(class_file: str | Path | None) -> dict[int, str] | None:
    if not class_file:
        return None

    path = Path(class_file).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Class file not found: {path}")

    names: dict[int, str] = {}
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            names[len(names)] = value

    if not names:
        raise ValueError(f"Class file is empty: {path}")
    return names


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default

    if hasattr(value, "item"):
        try:
            return float(value.item())
        except (TypeError, ValueError):
            return default

    if isinstance(value, np.ndarray):
        if value.size == 0:
            return default
        return float(value.reshape(-1)[0])

    if isinstance(value, (list, tuple)):
        if not value:
            return default
        return _to_float(value[0], default=default)

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_xyxy_list(value: Any) -> list[float]:
    if value is None:
        return []

    raw = value
    if hasattr(raw, "tolist"):
        raw = raw.tolist()

    if isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], (list, tuple)):
        raw = raw[0]

    if not isinstance(raw, (list, tuple)):
        return []

    values = []
    for item in raw[:4]:
        values.append(_to_float(item, default=0.0))
    return values


class MaterialDetector:
    def __init__(
        self,
        model_path: str | Path,
        class_names: str | Path | None = None,
        conf_threshold: float = 0.35,
        iou_threshold: float = 0.45,
        device: str | int | None = None,
        imgsz: int = 640,
    ) -> None:
        self.model_path = Path(model_path).expanduser().resolve()
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Model file not found: {self.model_path}")

        self.class_names = load_class_names(class_names)
        self.conf_threshold = float(conf_threshold)
        self.iou_threshold = float(iou_threshold)
        self.device = self._resolve_device(device)
        self.imgsz = int(imgsz)

        self.model = self._load_ultralytics_model()
        self.model_names = self._resolve_model_names()

    @staticmethod
    def _resolve_device(device: str | int | None) -> str | int:
        if isinstance(device, str):
            stripped = device.strip().lower()
            if stripped and stripped != "auto":
                if stripped.isdigit():
                    return int(stripped)
                return device
        elif device is not None:
            return device

        try:
            import torch
        except Exception:
            return "cpu"

        return 0 if torch.cuda.is_available() else "cpu"

    def _load_ultralytics_model(self) -> Any:
        try:
            from ultralytics import YOLO
        except Exception as exc:
            raise RuntimeError(
                "ultralytics is not installed. Install dependencies from "
                "material_detector_yolo/requirements.txt"
            ) from exc

        return YOLO(str(self.model_path))

    def _resolve_model_names(self) -> dict[int, str]:
        if self.class_names:
            return self.class_names

        for obj in (self.model, getattr(self.model, "model", None)):
            names = _normalize_names(getattr(obj, "names", None))
            if names:
                return names

        return {}

    @staticmethod
    def decode_jpeg(image_bytes: bytes) -> np.ndarray | None:
        encoded = np.frombuffer(image_bytes, dtype=np.uint8)
        if encoded.size == 0:
            return None
        return cv2.imdecode(encoded, cv2.IMREAD_COLOR)

    def predict_jpeg_bytes(
        self,
        image_bytes: bytes,
        conf_threshold: float | None = None,
        iou_threshold: float | None = None,
    ) -> dict[str, Any]:
        frame = self.decode_jpeg(image_bytes)
        if frame is None:
            raise ValueError("Image decode failed")
        return self.predict(frame, conf_threshold=conf_threshold, iou_threshold=iou_threshold)

    def predict(
        self,
        frame: np.ndarray,
        conf_threshold: float | None = None,
        iou_threshold: float | None = None,
    ) -> dict[str, Any]:
        if frame is None or frame.size == 0:
            raise ValueError("Input frame is empty")

        conf = self.conf_threshold if conf_threshold is None else float(conf_threshold)
        iou = self.iou_threshold if iou_threshold is None else float(iou_threshold)

        started = perf_counter()
        results = self.model.predict(
            source=frame,
            conf=conf,
            iou=iou,
            imgsz=self.imgsz,
            device=self.device,
            verbose=False,
        )
        latency_ms = (perf_counter() - started) * 1000.0

        detections = self._parse_detections(results[0])
        counts: dict[str, int] = {}
        for item in detections:
            label = item["label"]
            counts[label] = counts.get(label, 0) + 1

        return {
            "counts": counts,
            "total_objects": len(detections),
            "detections": detections,
            "latency_ms": round(latency_ms, 2),
            "device": self.device,
            "model_path": str(self.model_path),
        }

    def _parse_detections(self, result: Any) -> list[dict[str, Any]]:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return []

        names = _normalize_names(getattr(result, "names", None))
        if not names:
            names = self.model_names

        detections: list[dict[str, Any]] = []
        for box in boxes:
            class_id = int(_to_float(getattr(box, "cls", None), default=-1))
            confidence = _to_float(getattr(box, "conf", None), default=0.0)
            raw_xyxy = _to_xyxy_list(getattr(box, "xyxy", None))
            if len(raw_xyxy) != 4:
                continue

            x1, y1, x2, y2 = [int(round(value)) for value in raw_xyxy]
            label = names.get(class_id, f"class_{class_id}")

            detections.append(
                {
                    "class_id": class_id,
                    "label": label,
                    "conf": round(confidence, 4),
                    "bbox": [x1, y1, x2, y2],
                }
            )

        return detections

    @staticmethod
    def draw_detections(
        frame: np.ndarray,
        detections: list[dict[str, Any]],
        color: tuple[int, int, int] = (0, 200, 0),
    ) -> np.ndarray:
        output = frame.copy()
        for item in detections:
            bbox = item.get("bbox", [0, 0, 0, 0])
            if len(bbox) != 4:
                continue
            x1, y1, x2, y2 = bbox
            conf = float(item.get("conf", 0.0))
            label = str(item.get("label", "unknown"))

            cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
            text = f"{label} {conf:.2f}"
            cv2.putText(
                output,
                text,
                (x1, max(16, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
            )

        return output
