from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional

import cv2


# 本脚本位于 scripts/ 目录，向上一级就是项目根目录；默认路径都以项目根目录为基准。
ROOT = Path(__file__).resolve().parents[1]

# rknn-toolkit 1.x 中 RK3399Pro 的平台名称。
DEFAULT_TARGET_PLATFORM = "rk3399pro"

# 生成 int8 量化校准集时接受的图片格式。
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def resolve_path(path: str) -> Path:
    """把命令行传入的路径转换为绝对路径，保证从任意目录执行脚本都能找到文件。"""
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return (ROOT / candidate).resolve()


def run_command(command: List[str]) -> None:
    """执行外部命令；一旦失败立即抛错，避免继续使用不完整的中间模型。"""
    print("执行命令：" + " ".join(command))
    subprocess.run(command, check=True, cwd=str(ROOT))


def export_pt_to_onnx(
    weights_path: Path,
    onnx_path: Path,
    image_size: int,
    opset: int,
    device: Optional[str],
    conda_env: str,
    force_export: bool,
) -> None:
    """把 Ultralytics 的 last.pt 导出成 ONNX；RKNN 工具链无法直接读取 .pt。"""
    if onnx_path.exists() and not force_export:
        print(f"ONNX 已存在，跳过导出：{onnx_path}")
        return

    if not weights_path.exists():
        raise FileNotFoundError(f"找不到 PyTorch 权重：{weights_path}")

    onnx_path.parent.mkdir(parents=True, exist_ok=True)
    default_export_path = weights_path.with_suffix(".onnx")

    try:
        # 当前环境如果有 ultralytics，就直接导出，速度最快。
        from ultralytics import YOLO

        model = YOLO(str(weights_path))
        exported_path = Path(
            model.export(
                format="onnx",
                imgsz=image_size,
                opset=opset,
                simplify=True,
                dynamic=False,
                device=device,
            )
        ).resolve()
    except ModuleNotFoundError:
        # rknn-toolkit 1.7.5 通常装在 Python 3.8 环境，而项目训练环境 alg 有 ultralytics。
        command = [
            "conda",
            "run",
            "-n",
            conda_env,
            "python",
            "scripts/export.py",
            "--weights",
            str(weights_path),
            "--format",
            "onnx",
            "--imgsz",
            str(image_size),
            "--opset",
            str(opset),
            "--simplify",
        ]
        if device:
            command.extend(["--device", device])
        run_command(command)
        exported_path = default_export_path.resolve()

    if not exported_path.exists():
        raise FileNotFoundError(f"ONNX 导出失败，未找到：{exported_path}")

    if exported_path != onnx_path:
        shutil.copy2(exported_path, onnx_path)
    print(f"ONNX 模型路径：{onnx_path}")


def iter_image_paths(image_dir: Path) -> Iterable[Path]:
    """递归收集图片并排序，保证每次生成的量化列表顺序一致。"""
    for path in sorted(image_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            yield path


def letterbox_image(image, image_size: int):
    """按照 YOLO 的 letterbox 方式缩放补边，减少量化输入和真实推理输入的分布差异。"""
    height, width = image.shape[:2]
    scale = min(image_size / height, image_size / width)
    resized_width = int(round(width * scale))
    resized_height = int(round(height * scale))
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)

    pad_width = image_size - resized_width
    pad_height = image_size - resized_height
    left = pad_width // 2
    right = pad_width - left
    top = pad_height // 2
    bottom = pad_height - top

    # 114 是 Ultralytics YOLO 默认补边颜色，量化时也使用它。
    return cv2.copyMakeBorder(
        resized,
        top,
        bottom,
        left,
        right,
        cv2.BORDER_CONSTANT,
        value=(114, 114, 114),
    )


def prepare_quantization_dataset(
    image_dir: Path,
    dataset_txt: Path,
    prepared_dir: Path,
    image_size: int,
    max_images: int,
) -> None:
    """生成 RKNN int8 量化所需 dataset.txt，并把图片预处理到固定输入尺寸。"""
    if not image_dir.exists():
        raise FileNotFoundError(f"找不到量化图片目录：{image_dir}")

    image_paths = list(iter_image_paths(image_dir))
    if not image_paths:
        raise FileNotFoundError(f"量化图片目录中没有可用图片：{image_dir}")

    selected_paths = image_paths[:max_images]
    prepared_dir.mkdir(parents=True, exist_ok=True)
    dataset_txt.parent.mkdir(parents=True, exist_ok=True)

    dataset_lines = []
    for index, image_path in enumerate(selected_paths):
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            print(f"跳过无法读取的图片：{image_path}")
            continue

        prepared = letterbox_image(image, image_size)
        prepared_path = prepared_dir / f"calib_{index:04d}{image_path.suffix.lower()}"
        cv2.imwrite(str(prepared_path), prepared)

        # RKNN dataset.txt 每行一个图片路径；使用绝对路径能避免工具链内部工作目录变化导致找不到文件。
        dataset_lines.append(str(prepared_path))

    if not dataset_lines:
        raise RuntimeError("没有成功生成任何量化校准图片")

    dataset_txt.write_text("\n".join(dataset_lines) + "\n", encoding="utf-8")
    print(f"量化校准列表：{dataset_txt}")
    print(f"量化校准图片数：{len(dataset_lines)}")


def convert_onnx_to_rknn(
    onnx_path: Path,
    rknn_path: Path,
    dataset_txt: Path,
    target_platform: str,
) -> None:
    """调用 rknn-toolkit 1.7.5，把 ONNX 转为 RK3399Pro 可加载的 int8 RKNN。"""
    try:
        from rknn.api import RKNN
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "当前 Python 环境未安装 rknn-toolkit。请使用 Python 3.8 环境安装 "
            "packages/rknn_toolkit-1.7.5-cp38-cp38-linux_x86_64.whl 后再运行。"
        ) from exc

    if not onnx_path.exists():
        raise FileNotFoundError(f"找不到 ONNX 模型：{onnx_path}")
    if not dataset_txt.exists():
        raise FileNotFoundError(f"找不到量化校准列表：{dataset_txt}")

    rknn_path.parent.mkdir(parents=True, exist_ok=True)
    rknn = RKNN(verbose=True)

    print("配置 RKNN 预处理参数")
    config_ret = rknn.config(
        mean_values=[[0, 0, 0]],
        std_values=[[255, 255, 255]],
        reorder_channel="0 1 2",
        target_platform=target_platform,
    )
    if config_ret != 0:
        raise RuntimeError(f"rknn.config 失败，返回码：{config_ret}")

    print("加载 ONNX 模型")
    load_ret = rknn.load_onnx(model=str(onnx_path))
    if load_ret != 0:
        raise RuntimeError(f"rknn.load_onnx 失败，返回码：{load_ret}")

    print("构建 int8 量化 RKNN 模型")
    build_ret = rknn.build(do_quantization=True, dataset=str(dataset_txt))
    if build_ret != 0:
        raise RuntimeError(f"rknn.build 失败，返回码：{build_ret}")

    print("导出 RKNN 模型")
    export_ret = rknn.export_rknn(str(rknn_path))
    if export_ret != 0:
        raise RuntimeError(f"rknn.export_rknn 失败，返回码：{export_ret}")

    rknn.release()
    print(f"RKNN int8 模型路径：{rknn_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将 weights/materials_yolo/last.pt 转为 RK3399Pro int8 RKNN 模型。")
    parser.add_argument("--weights", default="weights/materials_yolo/last.pt", help="输入 PyTorch 权重路径。")
    parser.add_argument("--onnx", default="weights/materials_yolo/last.onnx", help="中间 ONNX 输出路径。")
    parser.add_argument("--rknn", default="weights/materials_yolo/last_int8_rk3399pro.rknn", help="最终 RKNN 输出路径。")
    parser.add_argument("--calib-images", default="datasets/materials/images/train", help="int8 量化校准图片目录。")
    parser.add_argument("--dataset-txt", default="build/rknn/materials_calib_dataset.txt", help="RKNN 量化图片列表输出路径。")
    parser.add_argument("--prepared-dir", default="build/rknn/calib_images", help="预处理后的量化图片输出目录。")
    parser.add_argument("--imgsz", type=int, default=640, help="模型输入尺寸，需和训练/导出一致。")
    parser.add_argument("--opset", type=int, default=12, help="ONNX opset 版本。")
    parser.add_argument("--max-calib-images", type=int, default=1, help="最多使用多少张图片做 int8 量化校准；RKNN 1.7.5 转 YOLO11 时建议保持 1，避免检测头批大小推断错误。")
    parser.add_argument("--target-platform", default=DEFAULT_TARGET_PLATFORM, help="RKNN 目标平台。")
    parser.add_argument("--device", default=None, help="导出 ONNX 时使用的设备，例如 cpu 或 0。")
    parser.add_argument("--export-conda-env", default="alg", help="当前环境无 ultralytics 时，用哪个 conda 环境导出 ONNX。")
    parser.add_argument("--force-export", action="store_true", help="即使 ONNX 已存在也重新从 .pt 导出。")
    parser.add_argument("--skip-onnx-export", action="store_true", help="跳过 .pt 到 ONNX，只执行 RKNN 转换。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    weights_path = resolve_path(args.weights)
    onnx_path = resolve_path(args.onnx)
    rknn_path = resolve_path(args.rknn)
    calib_images_dir = resolve_path(args.calib_images)
    dataset_txt = resolve_path(args.dataset_txt)
    prepared_dir = resolve_path(args.prepared_dir)

    if not args.skip_onnx_export:
        export_pt_to_onnx(
            weights_path=weights_path,
            onnx_path=onnx_path,
            image_size=args.imgsz,
            opset=args.opset,
            device=args.device,
            conda_env=args.export_conda_env,
            force_export=args.force_export,
        )

    prepare_quantization_dataset(
        image_dir=calib_images_dir,
        dataset_txt=dataset_txt,
        prepared_dir=prepared_dir,
        image_size=args.imgsz,
        max_images=args.max_calib_images,
    )
    convert_onnx_to_rknn(
        onnx_path=onnx_path,
        rknn_path=rknn_path,
        dataset_txt=dataset_txt,
        target_platform=args.target_platform,
    )


if __name__ == "__main__":
    main()
