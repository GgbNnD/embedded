from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a YOLO model for materials detection.")
    parser.add_argument("--data", default="datasets/materials/data.yaml", help="Path to YOLO data config.")
    parser.add_argument("--model", default="yolo11n.pt", help="Model checkpoint or model name.")
    parser.add_argument("--epochs", type=int, default=100, help="Training epochs.")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size.")
    parser.add_argument("--batch", type=int, default=16, help="Batch size.")
    parser.add_argument("--device", default=None, help="Training device, e.g. cpu, 0, 0,1. Defaults to auto.")
    parser.add_argument("--project", default="runs/detect", help="Output project directory.")
    parser.add_argument("--name", default="materials_yolo", help="Run name.")
    parser.add_argument("--workers", type=int, default=4, help="Data loader workers.")
    parser.add_argument("--patience", type=int, default=30, help="Early stopping patience.")
    parser.add_argument("--save-period", type=int, default=10, help="Save checkpoint every N epochs.")
    parser.add_argument("--resume", action="store_true", help="Resume training from the latest checkpoint.")
    parser.add_argument("--resume-from", default=None, help="Resume training from a specific last.pt checkpoint.")
    return parser.parse_args()


def validate_data_config(data_path: Path) -> None:
    if not data_path.exists():
        raise FileNotFoundError(f"Data config not found: {data_path}")

    with data_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if "names" not in data or not data["names"]:
        raise ValueError(f"'names' is missing or empty in {data_path}")


def resolve_resume_checkpoint(project: str, name: str, resume_from: str | None) -> Path:
    if resume_from:
        checkpoint = Path(resume_from)
    else:
        checkpoint = Path(project) / name / "weights" / "last.pt"

    if not checkpoint.exists():
        raise FileNotFoundError(f"Resume checkpoint not found: {checkpoint}")
    return checkpoint


def main() -> None:
    args = parse_args()
    data_path = Path(args.data)
    validate_data_config(data_path)
    project_dir = str(Path(args.project).resolve())

    if args.resume:
        checkpoint = resolve_resume_checkpoint(project_dir, args.name, args.resume_from)
        print(f"Resuming from checkpoint: {checkpoint}")
        model = YOLO(str(checkpoint))
        results = model.train(resume=True, device=args.device)
    else:
        model = YOLO(args.model)
        results = model.train(
            data=str(data_path),
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            device=args.device,
            project=project_dir,
            name=args.name,
            workers=args.workers,
            patience=args.patience,
            pretrained=True,
            save_period=args.save_period,
        )

    save_dir = getattr(results, "save_dir", None)
    if save_dir:
        print(f"Training artifacts saved to: {save_dir}")


if __name__ == "__main__":
    main()
