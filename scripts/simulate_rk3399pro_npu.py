from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import cv2
import numpy as np


# 本脚本位于 scripts/ 目录，向上一级就是项目根目录；默认路径都以项目根目录为基准。
ROOT = Path(__file__).resolve().parents[1]

# 当前材料检测模型的类别顺序必须和训练数据 datasets/materials/data.yaml 保持一致。
CLASS_NAMES = ["cboard", "dmj4310", "m3508"]


Box = Tuple[float, float, float, float]
Detection = Dict[str, object]


def resolve_path(path: str) -> Path:
    """把命令行传入的相对路径转换为项目内绝对路径。"""
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return (ROOT / candidate).resolve()


def letterbox_image(image: np.ndarray, image_size: int) -> Tuple[np.ndarray, float, int, int]:
    """把原图等比例缩放并补边到 640x640，同时返回还原坐标需要的缩放比例和补边量。"""
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

    padded = cv2.copyMakeBorder(
        resized,
        top,
        bottom,
        left,
        right,
        cv2.BORDER_CONSTANT,
        value=(114, 114, 114),
    )
    return padded, scale, left, top


def prepare_rknn_input(image: np.ndarray, image_size: int) -> Tuple[np.ndarray, float, int, int]:
    """构造 RKNN 输入张量；这里保持 NHWC uint8，由 rknn.config 中的 mean/std 完成归一化。"""
    padded, scale, pad_left, pad_top = letterbox_image(image, image_size)
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    input_tensor = np.expand_dims(rgb, axis=0).astype(np.uint8)
    return input_tensor, scale, pad_left, pad_top


def prepare_onnx_input(image: np.ndarray, image_size: int) -> Tuple[np.ndarray, float, int, int]:
    """构造 ONNXRuntime 本机验证输入；ONNX 需要 NCHW float32，像素值范围为 0~1。"""
    padded, scale, pad_left, pad_top = letterbox_image(image, image_size)
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    chw = rgb.transpose(2, 0, 1).astype(np.float32) / 255.0
    input_tensor = np.expand_dims(chw, axis=0)
    return input_tensor, scale, pad_left, pad_top


def xywh_to_xyxy(box: Sequence[float]) -> Box:
    """把 YOLO 输出的中心点宽高格式转换为左上角/右下角格式。"""
    center_x, center_y, width, height = box
    half_width = width / 2.0
    half_height = height / 2.0
    return (
        center_x - half_width,
        center_y - half_height,
        center_x + half_width,
        center_y + half_height,
    )


def restore_box_to_original_image(
    box: Box,
    scale: float,
    pad_left: int,
    pad_top: int,
    original_width: int,
    original_height: int,
) -> Box:
    """把 640x640 letterbox 输入坐标还原到原始图片坐标。"""
    x1, y1, x2, y2 = box
    x1 = (x1 - pad_left) / scale
    y1 = (y1 - pad_top) / scale
    x2 = (x2 - pad_left) / scale
    y2 = (y2 - pad_top) / scale

    restored_box = (
        max(0.0, min(float(original_width - 1), x1)),
        max(0.0, min(float(original_height - 1), y1)),
        max(0.0, min(float(original_width - 1), x2)),
        max(0.0, min(float(original_height - 1), y2)),
    )
    return tuple(float(value) for value in restored_box)


def intersection_over_union(box_a: Box, box_b: Box) -> float:
    """计算两个检测框的 IoU，用于 NMS 去掉高度重叠的重复框。"""
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    inter_width = max(0.0, inter_x2 - inter_x1)
    inter_height = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_width * inter_height

    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union_area = area_a + area_b - inter_area

    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def non_max_suppression(detections: List[Detection], iou_threshold: float) -> List[Detection]:
    """按类别分别做 NMS，避免不同类别之间互相抑制。"""
    kept: List[Detection] = []
    class_ids = sorted({int(det["class_id"]) for det in detections})

    for class_id in class_ids:
        class_detections = [det for det in detections if int(det["class_id"]) == class_id]
        class_detections.sort(key=lambda item: float(item["score"]), reverse=True)

        while class_detections:
            best = class_detections.pop(0)
            kept.append(best)
            class_detections = [
                det
                for det in class_detections
                if intersection_over_union(best["box"], det["box"]) < iou_threshold
            ]

    kept.sort(key=lambda item: float(item["score"]), reverse=True)
    return kept


def parse_yolo_output(
    outputs: Sequence[np.ndarray],
    conf_threshold: float,
    iou_threshold: float,
    scale: float,
    pad_left: int,
    pad_top: int,
    original_width: int,
    original_height: int,
) -> List[Detection]:
    """解析 Ultralytics YOLO 导出的 ONNX/RKNN 输出，当前模型输出形状通常为 [1, 7, 8400]。"""
    output = np.asarray(outputs[0])

    if output.ndim == 3:
        output = output[0]
    if output.shape[0] < output.shape[1]:
        output = output.T

    detections: List[Detection] = []
    class_count = len(CLASS_NAMES)

    for prediction in output:
        box_xywh = prediction[:4]
        class_scores = prediction[4 : 4 + class_count]
        class_id = int(np.argmax(class_scores))
        score = float(class_scores[class_id])

        if score < conf_threshold:
            continue

        input_box = xywh_to_xyxy(box_xywh)
        original_box = restore_box_to_original_image(
            input_box,
            scale=scale,
            pad_left=pad_left,
            pad_top=pad_top,
            original_width=original_width,
            original_height=original_height,
        )
        detections.append(
            {
                "class_id": class_id,
                "class_name": CLASS_NAMES[class_id],
                "score": score,
                "box": list(original_box),
            }
        )

    return non_max_suppression(detections, iou_threshold)


def draw_detections(image: np.ndarray, detections: Sequence[Detection]) -> np.ndarray:
    """把检测框、类别名和置信度画到图片上，便于在板端部署前快速检查结果。"""
    annotated = image.copy()

    for det in detections:
        x1, y1, x2, y2 = [int(round(value)) for value in det["box"]]
        class_name = str(det["class_name"])
        score = float(det["score"])
        label = f"{class_name} {score:.2f}"

        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label_y = max(0, y1 - 8)
        cv2.putText(
            annotated,
            label,
            (x1, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )

    return annotated


def summarize_counts(detections: Sequence[Detection]) -> Dict[str, int]:
    """统计每个类别的检测数量，输出格式和项目中原来的 PyTorch 推理脚本保持一致。"""
    counts: Dict[str, int] = {}
    for det in detections:
        class_name = str(det["class_name"])
        counts[class_name] = counts.get(class_name, 0) + 1
    return dict(sorted(counts.items()))


def run_rknn_inference(rknn_path: Path, input_tensor: np.ndarray, target: str, device_id: str | None):
    """初始化 RKNN runtime 并执行一次推理；连接 RK3399Pro 开发板时会在板端 NPU 上运行。"""
    try:
        from rknn.api import RKNN
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "当前 Python 环境未安装 rknn-toolkit。请用 Python 3.8 环境安装 packages 下的 rknn_toolkit wheel 后运行。"
        ) from exc

    if not rknn_path.exists():
        raise FileNotFoundError(f"找不到 RKNN 模型：{rknn_path}")

    rknn = RKNN(verbose=True)

    print("加载 RKNN 模型")
    load_ret = rknn.load_rknn(str(rknn_path))
    if load_ret != 0:
        raise RuntimeError(f"rknn.load_rknn 失败，返回码：{load_ret}")

    print("初始化 RK3399Pro runtime")
    if device_id:
        init_ret = rknn.init_runtime(target=target, device_id=device_id)
    else:
        init_ret = rknn.init_runtime(target=target)
    if init_ret != 0:
        raise RuntimeError(f"rknn.init_runtime 失败，返回码：{init_ret}")

    print("执行 NPU 推理")
    outputs = rknn.inference(inputs=[input_tensor])
    rknn.release()

    if outputs is None:
        raise RuntimeError("rknn.inference 未返回输出")
    return outputs


def run_onnx_inference(onnx_path: Path, input_tensor: np.ndarray):
    """在没有 RK3399Pro 板子时，用 ONNXRuntime 在 PC 上验证同一套预处理和后处理逻辑。"""
    try:
        import onnxruntime as ort
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("当前 Python 环境未安装 onnxruntime，无法使用 --backend onnx 本机验证。") from exc

    if not onnx_path.exists():
        raise FileNotFoundError(f"找不到 ONNX 模型：{onnx_path}")

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    return session.run(None, {input_name: input_tensor})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="模拟在 RK3399Pro NPU 上部署并推理材料检测模型。")
    parser.add_argument("--backend", choices=["rknn", "onnx"], default="rknn", help="rknn 表示连接 RK3399Pro 板端 NPU；onnx 表示在 PC 上验证预处理和后处理。")
    parser.add_argument("--rknn", default="weights/materials_yolo/last_int8_rk3399pro.rknn", help="RKNN 模型路径。")
    parser.add_argument("--onnx", default="weights/materials_yolo/last.onnx", help="ONNX 本机验证模型路径。")
    parser.add_argument("--image", default="test.jpg", help="输入测试图片路径。")
    parser.add_argument("--imgsz", type=int, default=640, help="模型输入尺寸。")
    parser.add_argument("--conf", type=float, default=0.25, help="置信度阈值。")
    parser.add_argument("--iou", type=float, default=0.45, help="NMS IoU 阈值。")
    parser.add_argument("--target", default="rk3399pro", help="RKNN runtime 目标平台。")
    parser.add_argument("--device-id", default=None, help="多设备连接时指定板端 device_id。")
    parser.add_argument("--output-dir", default="outputs/rknn", help="结果输出目录。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    rknn_path = resolve_path(args.rknn)
    onnx_path = resolve_path(args.onnx)
    image_path = resolve_path(args.image)
    output_dir = resolve_path(args.output_dir)

    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"无法读取输入图片：{image_path}")

    if args.backend == "rknn":
        input_tensor, scale, pad_left, pad_top = prepare_rknn_input(image, args.imgsz)
        outputs = run_rknn_inference(
            rknn_path=rknn_path,
            input_tensor=input_tensor,
            target=args.target,
            device_id=args.device_id,
        )
        model_path = rknn_path
    else:
        input_tensor, scale, pad_left, pad_top = prepare_onnx_input(image, args.imgsz)
        outputs = run_onnx_inference(onnx_path=onnx_path, input_tensor=input_tensor)
        model_path = onnx_path

    original_height, original_width = image.shape[:2]
    detections = parse_yolo_output(
        outputs=outputs,
        conf_threshold=args.conf,
        iou_threshold=args.iou,
        scale=scale,
        pad_left=pad_left,
        pad_top=pad_top,
        original_width=original_width,
        original_height=original_height,
    )
    counts = summarize_counts(detections)

    output_dir.mkdir(parents=True, exist_ok=True)
    annotated = draw_detections(image, detections)
    annotated_path = output_dir / f"{image_path.stem}_rknn.jpg"
    json_path = output_dir / f"{image_path.stem}_rknn.json"

    cv2.imwrite(str(annotated_path), annotated)
    json_path.write_text(
        json.dumps(
            {
                "image": str(image_path),
                "model": str(model_path),
                "counts": counts,
                "detections": detections,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"检测数量：{counts}")
    print(f"可视化结果：{annotated_path}")
    print(f"JSON 结果：{json_path}")


if __name__ == "__main__":
    main()
