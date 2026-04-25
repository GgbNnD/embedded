from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a trained YOLO materials model.")
    parser.add_argument("--weights", required=True, help="Path to trained weights, usually best.pt.")
    parser.add_argument("--format", default="onnx", help="Export format, e.g. onnx, torchscript, engine.")
    parser.add_argument("--imgsz", type=int, default=640, help="Export image size.")
    parser.add_argument("--device", default=None, help="Export device, e.g. cpu or 0. Defaults to auto.")
    parser.add_argument("--half", action="store_true", help="Export half precision model when supported.")
    parser.add_argument("--dynamic", action="store_true", help="Enable dynamic input shape when supported.")
    parser.add_argument("--simplify", action="store_true", help="Simplify exported graph when supported.")
    parser.add_argument("--opset", type=int, default=12, help="ONNX opset version.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    weights_path = Path(args.weights)
    if not weights_path.exists():
        raise FileNotFoundError(f"Weights not found: {weights_path}")

    model = YOLO(str(weights_path))
    exported_path = model.export(
        format=args.format,
        imgsz=args.imgsz,
        device=args.device,
        half=args.half,
        dynamic=args.dynamic,
        simplify=args.simplify,
        opset=args.opset,
    )
    print(f"Exported model: {exported_path}")


if __name__ == "__main__":
    main()
