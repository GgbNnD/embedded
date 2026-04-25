from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import yaml


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate YOLO dataset structure and labels.")
    parser.add_argument("--data", default="datasets/materials/data.yaml", help="Path to YOLO data config.")
    return parser.parse_args()


def load_names(data_path: Path) -> dict[int, str]:
    with data_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    names = data.get("names")
    if isinstance(names, list):
        return {idx: name for idx, name in enumerate(names)}
    if isinstance(names, dict):
        return {int(idx): name for idx, name in names.items()}
    raise ValueError(f"Unsupported names format in {data_path}")


def split_paths(data_path: Path) -> tuple[Path, dict[str, Path]]:
    with data_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    raw_root = Path(data["path"])
    if raw_root.is_absolute():
        dataset_root = raw_root
    else:
        candidate_from_cwd = (Path.cwd() / raw_root).resolve()
        candidate_from_yaml = (data_path.parent / raw_root).resolve()
        dataset_root = candidate_from_cwd if candidate_from_cwd.exists() else candidate_from_yaml

    splits = {
        "train": dataset_root / data["train"],
        "val": dataset_root / data["val"],
        "test": dataset_root / data["test"],
    }
    return dataset_root, splits


def label_dir_from_image_dir(image_dir: Path) -> Path:
    return image_dir.parents[1] / "labels" / image_dir.name


def validate_split(name_map: dict[int, str], split: str, image_dir: Path, label_dir: Path) -> tuple[list[str], Counter]:
    issues: list[str] = []
    class_counts: Counter[str] = Counter()
    class_order = [name_map[idx] for idx in sorted(name_map)]

    images = sorted(p for p in image_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
    labels = sorted(p for p in label_dir.iterdir() if p.is_file() and p.suffix.lower() == ".txt" and p.name != "classes.txt")
    image_stems = {p.stem for p in images}
    label_stems = {p.stem for p in labels}
    classes_file = label_dir / "classes.txt"

    if classes_file.exists():
        declared_order = [line.strip() for line in classes_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        if declared_order != class_order:
            issues.append(
                f"[{split}] classes.txt order {declared_order} does not match data.yaml order {class_order}"
            )

    missing_labels = sorted(image_stems - label_stems)
    missing_images = sorted(label_stems - image_stems)
    if missing_labels:
        issues.append(f"[{split}] missing labels for images: {missing_labels[:5]}")
    if missing_images:
        issues.append(f"[{split}] missing images for labels: {missing_images[:5]}")

    for label_path in labels:
        lines = label_path.read_text(encoding="utf-8").strip().splitlines()
        if not lines:
            issues.append(f"[{split}] empty label file: {label_path.name}")
            continue

        for line_no, line in enumerate(lines, 1):
            parts = line.split()
            if len(parts) != 5:
                issues.append(f"[{split}] {label_path.name}:{line_no} has {len(parts)} fields")
                continue

            try:
                class_id = int(parts[0])
                coords = [float(value) for value in parts[1:]]
            except ValueError:
                issues.append(f"[{split}] {label_path.name}:{line_no} failed to parse")
                continue

            if class_id not in name_map:
                issues.append(f"[{split}] {label_path.name}:{line_no} invalid class id {class_id}")
                continue
            if any(value < 0.0 or value > 1.0 for value in coords):
                issues.append(f"[{split}] {label_path.name}:{line_no} has out-of-range coordinates")
                continue

            class_counts[name_map[class_id]] += 1

    print(
        f"[{split}] images={len(images)} labels={len(labels)} "
        f"objects={sum(class_counts.values())} classes={dict(class_counts)}"
    )
    return issues, class_counts


def main() -> None:
    args = parse_args()
    data_path = Path(args.data).resolve()
    if not data_path.exists():
        raise FileNotFoundError(f"Data config not found: {data_path}")

    name_map = load_names(data_path)
    _, image_splits = split_paths(data_path)

    all_issues: list[str] = []
    for split, image_dir in image_splits.items():
        label_dir = label_dir_from_image_dir(image_dir)
        issues, _ = validate_split(name_map, split, image_dir, label_dir)
        all_issues.extend(issues)

    if all_issues:
        print("\nIssues found:")
        for issue in all_issues:
            print(f"- {issue}")
        raise SystemExit(1)

    print("\nDataset check passed.")


if __name__ == "__main__":
    main()
