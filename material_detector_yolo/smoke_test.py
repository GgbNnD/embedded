from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from detector import MaterialDetector


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local smoke test for material detector")
    parser.add_argument("--model", required=True, help="model path (.pt/.onnx)")
    parser.add_argument("--image", required=True, help="test image path")
    parser.add_argument("--classes", default="", help="optional class names file")
    parser.add_argument("--out", default="", help="optional output image with boxes")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--iou", type=float, default=0.45)
    parser.add_argument("--imgsz", type=int, default=640)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image_path = Path(args.image).expanduser().resolve()
    if not image_path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    frame = cv2.imread(str(image_path))
    if frame is None:
        raise RuntimeError(f"Failed to read image: {image_path}")

    detector = MaterialDetector(
        model_path=args.model,
        class_names=args.classes or None,
        conf_threshold=args.conf,
        iou_threshold=args.iou,
        device=args.device,
        imgsz=args.imgsz,
    )
    result = detector.predict(frame)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.out:
        output_path = Path(args.out).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rendered = detector.draw_detections(frame, result["detections"])
        ok = cv2.imwrite(str(output_path), rendered)
        if not ok:
            raise RuntimeError(f"Failed to write output image: {output_path}")
        print(f"Saved rendered image: {output_path}")


if __name__ == "__main__":
    main()
