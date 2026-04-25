from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a trained YOLO materials model.")
    parser.add_argument("--weights", required=True, help="Path to trained weights.")
    parser.add_argument("--data", default="datasets/materials/data.yaml", help="Path to YOLO data config.")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size.")
    parser.add_argument("--device", default=None, help="Validation device, e.g. cpu or 0. Defaults to auto.")
    parser.add_argument("--split", default="val", choices=["train", "val", "test"], help="Dataset split.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    weights_path = Path(args.weights)
    if not weights_path.exists():
        raise FileNotFoundError(f"Weights not found: {weights_path}")

    model = YOLO(str(weights_path))
    metrics = model.val(
        data=args.data,
        imgsz=args.imgsz,
        device=args.device,
        split=args.split,
    )

    box = metrics.box
    print(f"mAP50: {box.map50:.4f}")
    print(f"mAP50-95: {box.map:.4f}")
    print(f"Precision: {box.mp:.4f}")
    print(f"Recall: {box.mr:.4f}")


if __name__ == "__main__":
    main()
