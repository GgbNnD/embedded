from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train YOLO detector for material counting")
    parser.add_argument("--data", required=True, help="dataset yaml path")
    parser.add_argument("--model", default="yolov8n.pt", help="base model path or model name")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default="0", help="GPU index, cuda:0, or cpu")
    parser.add_argument("--project", default="material_detector_yolo/artifacts")
    parser.add_argument("--name", default="yolov8n_material")
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        from ultralytics import YOLO
    except Exception as exc:
        raise RuntimeError("ultralytics is required. Install requirements.txt first.") from exc

    data_path = Path(args.data).expanduser().resolve()
    if not data_path.is_file():
        raise FileNotFoundError(f"Data yaml not found: {data_path}")

    model = YOLO(args.model)
    model.train(
        data=str(data_path),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=args.name,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
