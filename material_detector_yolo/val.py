from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate YOLO detector")
    parser.add_argument("--model", required=True, help="trained model path")
    parser.add_argument("--data", required=True, help="dataset yaml path")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="0")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        from ultralytics import YOLO
    except Exception as exc:
        raise RuntimeError("ultralytics is required. Install requirements.txt first.") from exc

    model_path = Path(args.model).expanduser().resolve()
    data_path = Path(args.data).expanduser().resolve()
    if not model_path.is_file():
        raise FileNotFoundError(f"Model not found: {model_path}")
    if not data_path.is_file():
        raise FileNotFoundError(f"Data yaml not found: {data_path}")

    model = YOLO(str(model_path))
    metrics = model.val(data=str(data_path), imgsz=args.imgsz, device=args.device)
    print(metrics)


if __name__ == "__main__":
    main()
