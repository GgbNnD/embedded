from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLIT_NAMES = ("train", "val", "test")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize image names and split datasets/pic into train/val/test."
    )
    parser.add_argument(
        "--source-dir",
        default="datasets/pic",
        help="Directory containing the original images.",
    )
    parser.add_argument(
        "--output-dir",
        default="datasets/materials/images",
        help="Directory used to store train/val/test.",
    )
    parser.add_argument(
        "--prefix",
        default="image",
        help="Normalized filename prefix, e.g. image -> image_0001.jpg.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed used before splitting.",
    )
    parser.add_argument(
        "--train-ratio",
        type=int,
        default=6,
        help="Train split ratio.",
    )
    parser.add_argument(
        "--val-ratio",
        type=int,
        default=3,
        help="Validation split ratio.",
    )
    parser.add_argument(
        "--test-ratio",
        type=int,
        default=1,
        help="Test split ratio.",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy files instead of moving them.",
    )
    return parser.parse_args()


def collect_images(source_dir: Path) -> list[Path]:
    return sorted(
        file_path
        for file_path in source_dir.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in IMAGE_EXTENSIONS
    )


def compute_split_counts(total: int, ratios: tuple[int, int, int]) -> dict[str, int]:
    ratio_sum = sum(ratios)
    if ratio_sum <= 0:
        raise ValueError("The sum of split ratios must be greater than 0.")

    train_count = total * ratios[0] // ratio_sum
    val_count = total * ratios[1] // ratio_sum
    test_count = total - train_count - val_count
    return {"train": train_count, "val": val_count, "test": test_count}


def split_images(files: list[Path], counts: dict[str, int]) -> dict[str, list[Path]]:
    train_end = counts["train"]
    val_end = train_end + counts["val"]
    return {
        "train": files[:train_end],
        "val": files[train_end:val_end],
        "test": files[val_end:],
    }


def ensure_output_dirs(output_dir: Path) -> None:
    for split_name in SPLIT_NAMES:
        (output_dir / split_name).mkdir(parents=True, exist_ok=True)


def write_split(
    split_name: str,
    files: list[Path],
    output_dir: Path,
    prefix: str,
    copy_files: bool,
) -> None:
    for index, file_path in enumerate(files, start=1):
        new_name = f"{prefix}_{split_name}_{index:04d}{file_path.suffix.lower()}"
        destination = output_dir / split_name / new_name
        if destination.exists():
            raise FileExistsError(f"Target file already exists: {destination}")

        if copy_files:
            shutil.copy2(file_path, destination)
        else:
            shutil.move(str(file_path), destination)


def main() -> None:
    args = parse_args()
    source_dir = Path(args.source_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Source path is not a directory: {source_dir}")

    ratios = (args.train_ratio, args.val_ratio, args.test_ratio)
    if any(ratio < 0 for ratio in ratios):
        raise ValueError("Split ratios cannot be negative.")

    image_files = collect_images(source_dir)
    if not image_files:
        raise ValueError(f"No supported images found in {source_dir}")

    rng = random.Random(args.seed)
    rng.shuffle(image_files)

    split_counts = compute_split_counts(len(image_files), ratios)
    split_mapping = split_images(image_files, split_counts)
    ensure_output_dirs(output_dir)

    for split_name in SPLIT_NAMES:
        write_split(
            split_name=split_name,
            files=split_mapping[split_name],
            output_dir=output_dir,
            prefix=args.prefix,
            copy_files=args.copy,
        )

    action = "Copied" if args.copy else "Moved"
    print(f"{action} {len(image_files)} images from {source_dir} to {output_dir}.")
    print(
        "Split summary: "
        f"train={split_counts['train']}, "
        f"val={split_counts['val']}, "
        f"test={split_counts['test']}"
    )


if __name__ == "__main__":
    main()
