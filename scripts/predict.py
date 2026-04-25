from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.materials_detector.io_utils import dump_json, dump_lines
from src.materials_detector.results import summarize_counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run single-image inference and count materials.")
    parser.add_argument("--weights", required=True, help="Path to trained weights.")
    parser.add_argument("--source", required=True, help="Path to input image.")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold.")
    parser.add_argument("--device", default=None, help="Inference device, e.g. cpu or 0. Defaults to auto.")
    parser.add_argument("--output-dir", default="outputs/predict", help="Directory for saved outputs.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    weights_path = Path(args.weights)
    source_path = Path(args.source)

    if not weights_path.exists():
        raise FileNotFoundError(f"Weights not found: {weights_path}")
    if not source_path.exists():
        raise FileNotFoundError(f"Source image not found: {source_path}")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    model = YOLO(str(weights_path))
    predictions = model.predict(
        source=str(source_path),
        conf=args.conf,
        device=args.device,
        save=True,
        project=str(output_dir),
        name="visualized",
        exist_ok=True,
    )

    result = predictions[0]
    counts = summarize_counts(result)
    stem = source_path.stem

    dump_json(output_dir / f"{stem}_counts.json", counts)
    dump_lines(output_dir / f"{stem}_counts.txt", counts)

    print(f"Saved visualized prediction to: {output_dir / 'visualized'}")
    print("Counts:")
    for class_name, count in counts.items():
        print(f"{class_name}: {count}")


if __name__ == "__main__":
    main()
