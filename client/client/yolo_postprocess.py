"""
YOLO 后处理工具模块
===================
从 scripts/simulate_rk3399pro_npu.py 提取并适配。
用于解析 RKNN/YOLO 模型的输出, 包括:

  - letterbox 图像缩放补边 (与训练时一致的预处理)
  - 模型输出解析 (提取检测框、类别、置信度)
  - NMS 非极大值抑制 (去除重复检测)
  - 坐标还原 (从 640x640 letterbox 还原到原始图像坐标系)

这是一套纯 numpy 实现的 YOLO 后处理, 不依赖 ultralytics 库。
适配所有 YOLO v8/v11 模型的标准输出格式: [1, num_classes+4, num_boxes]

YOLO 输出格式说明:
  输出形状通常为 [1, 7, 8400] (1 batch × 7 通道 × 8400 个锚点)
  每个锚点包含:
    [cx, cy, w, h, class_score_0, class_score_1, class_score_2]
    其中 7 = 4(边界框) + 3(类别数: cboard, dmj4310, m3508)
"""

import numpy as np
import cv2

# 当前材料检测模型的类别顺序, 必须与训练数据 datasets/materials/data.yaml 一致
CLASS_NAMES = ["cboard", "dmj4310", "m3508"]


# ═══════════════════════════════════════════════════════════════════════════════
# Letterbox 预处理
# ═══════════════════════════════════════════════════════════════════════════════

def letterbox_image(image, image_size=640):
    """把原图等比例缩放并补边到固定尺寸 (保持宽高比)

    与训练/量化时使用的 letterbox 完全一致, 确保推理精度。
    补边颜色为 (114, 114, 114), 与 Ultralytics YOLO 默认值一致。

    Args:
        image: OpenCV BGR 格式图像 (np.ndarray, 形状 [H, W, 3])
        image_size: 目标正方形边长, 默认 640

    Returns:
        (padded_image, scale, pad_left, pad_top)
        padded_image: 缩放并补边后的图像 [image_size, image_size, 3]
        scale: 缩放比例 (原始尺寸到目标尺寸的缩放因子)
        pad_left: 左边补边像素数
        pad_top: 上边补边像素数
    """
    height, width = image.shape[:2]
    scale = min(image_size / height, image_size / width)

    # 等比例缩放
    resized_width = int(round(width * scale))
    resized_height = int(round(height * scale))
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)

    # 计算补边量
    pad_width = image_size - resized_width
    pad_height = image_size - resized_height
    left = pad_width // 2
    right = pad_width - left
    top = pad_height // 2
    bottom = pad_height - top

    # 补边, 颜色 114 (Ultralytics YOLO 默认灰色)
    padded = cv2.copyMakeBorder(
        resized, top, bottom, left, right,
        cv2.BORDER_CONSTANT,
        value=(114, 114, 114),
    )
    return padded, scale, left, top


def prepare_input_tensor(image, image_size=640):
    """构造 RKNN 模型输入张量

    RKNN 模型接收 NHWC uint8 格式输入, 归一化由 rknn.config 中的 mean/std 参数完成。

    Args:
        image: OpenCV BGR 格式图像
        image_size: 模型输入尺寸

    Returns:
        (input_tensor, scale, pad_left, pad_top)
        input_tensor: np.ndarray [1, image_size, image_size, 3] uint8 NHWC
    """
    padded, scale, pad_left, pad_top = letterbox_image(image, image_size)
    # BGR → RGB (RKNN 模型通常要求 RGB 输入)
    rgb = np.ascontiguousarray(padded[:, :, ::-1])  # BGR to RGB
    input_tensor = np.expand_dims(rgb, axis=0).astype(np.uint8)
    return input_tensor, scale, pad_left, pad_top


# ═══════════════════════════════════════════════════════════════════════════════
# 检测结果解析
# ═══════════════════════════════════════════════════════════════════════════════

def xywh_to_xyxy(box):
    """把 YOLO 输出的中心点-宽高格式转换为左上角-右下角格式

    Args:
        box: (cx, cy, w, h) 列表或元组

    Returns:
        (x1, y1, x2, y2) 元组
    """
    cx, cy, w, h = box[:4]
    half_w = w / 2.0
    half_h = h / 2.0
    return (cx - half_w, cy - half_h, cx + half_w, cy + half_h)


def restore_box_to_original(box, scale, pad_left, pad_top, orig_width, orig_height):
    """把 640x640 letterbox 坐标还原到原始图片坐标系

    Args:
        box: (x1, y1, x2, y2) 在 letterbox 坐标系中的框
        scale: 缩放比例
        pad_left: 左边补边像素
        pad_top: 上边补边像素
        orig_width: 原始图片宽度
        orig_height: 原始图片高度

    Returns:
        (x1, y1, x2, y2) 在原始坐标系中的框, 已裁剪到图像边界内
    """
    x1, y1, x2, y2 = box
    x1 = (x1 - pad_left) / scale
    y1 = (y1 - pad_top) / scale
    x2 = (x2 - pad_left) / scale
    y2 = (y2 - pad_top) / scale

    # 裁剪到图像边界内
    return (
        max(0.0, min(float(orig_width - 1), x1)),
        max(0.0, min(float(orig_height - 1), y1)),
        max(0.0, min(float(orig_width - 1), x2)),
        max(0.0, min(float(orig_height - 1), y2)),
    )


def compute_iou(box_a, box_b):
    """计算两个边界框的 IoU (交并比)

    用于 NMS 中判断两个框是否重叠过多。

    Args:
        box_a: (x1, y1, x2, y2)
        box_b: (x1, y1, x2, y2)

    Returns:
        IoU 值 (0.0 ~ 1.0), 越高表示重叠越多
    """
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    # 交集区域
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter_area = iw * ih

    # 并集区域
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union_area = area_a + area_b - inter_area

    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def non_max_suppression(detections, iou_threshold=0.45):
    """非极大值抑制 (NMS): 按类别分别去除重叠过多的重复检测框

    算法:
      1. 按类别分组
      2. 每组内按置信度降序排序
      3. 依次选择最高置信度的框, 移除与它 IoU > threshold 的其他框
      4. 重复步骤 3 直到该类别无剩余

    Args:
        detections: 检测结果列表 [{"class_id": int, "class_name": str, "score": float, "box": (x1,y1,x2,y2)}, ...]
        iou_threshold: IoU 阈值 (0~1), 默认 0.45

    Returns:
        去重后的检测结果列表, 按置信度降序排列
    """
    kept = []
    class_ids = sorted({int(d["class_id"]) for d in detections})

    for cid in class_ids:
        # 提取该类别的所有检测结果
        class_dets = [d for d in detections if int(d["class_id"]) == cid]
        # 按置信度降序排序
        class_dets.sort(key=lambda d: float(d["score"]), reverse=True)

        while class_dets:
            best = class_dets.pop(0)
            kept.append(best)
            # 移除与当前"最佳框"重叠过多 (IoU > threshold) 的框
            class_dets = [
                d for d in class_dets
                if compute_iou(best["box"], d["box"]) < iou_threshold
            ]

    kept.sort(key=lambda d: float(d["score"]), reverse=True)
    return kept


# ═══════════════════════════════════════════════════════════════════════════════
# 主解析函数
# ═══════════════════════════════════════════════════════════════════════════════

def parse_yolo_output(outputs, conf_threshold=0.25, iou_threshold=0.45,
                      scale=1.0, pad_left=0, pad_top=0,
                      original_width=640, original_height=640):
    """解析 YOLO 模型输出, 返回检测结果列表

    该函数封装了完整的 YOLO 后处理流程:
      outputs → 提取预测 → 坐标转换 → NMS → 结果列表

    Args:
        outputs: 模型推理输出, 通常为 list of np.ndarray
                 第一个元素形状为 [1, num_classes+4, num_boxes] 或 [num_boxes, num_classes+4]
        conf_threshold: 置信度阈值 (低于此值的预测被丢弃), 默认 0.25
        iou_threshold: NMS IoU 阈值, 默认 0.45
        scale: letterbox 缩放比例 (用于坐标还原)
        pad_left: 左边补边像素 (用于坐标还原)
        pad_top: 上边补边像素 (用于坐标还原)
        original_width: 原始图像宽度 (用于坐标还原)
        original_height: 原始图像高度 (用于坐标还原)

    Returns:
        list of dict:
        [{
            "class_id": int,       # 类别 ID (0/1/2)
            "class_name": str,     # 类别名称 ("cboard"/"dmj4310"/"m3508")
            "score": float,        # 置信度 (0~1)
            "box": [x1, y1, x2, y2],  # 在原始图像坐标系中的边界框
        }, ...]
    """
    # 提取第一个输出
    output = np.asarray(outputs[0])

    # 统一形状: 确保是 (num_boxes, num_classes+4) 的 2D 数组
    if output.ndim == 3:
        output = output[0]               # [1, 7, 8400] → [7, 8400]
    if output.shape[0] < output.shape[1]:
        output = output.T                # [7, 8400] → [8400, 7]

    detections = []
    num_classes = len(CLASS_NAMES)

    for prediction in output:
        # 解析单个预测: [cx, cy, w, h, score_0, score_1, score_2]
        box_xywh = prediction[:4]
        class_scores = prediction[4:4 + num_classes]

        # 取最高分值的类别
        class_id = int(np.argmax(class_scores))
        score = float(class_scores[class_id])

        # 置信度过滤
        if score < conf_threshold:
            continue

        # 坐标转换: letterbox → 原始图像
        letterbox_box = xywh_to_xyxy(box_xywh)
        original_box = restore_box_to_original(
            letterbox_box, scale, pad_left, pad_top,
            original_width, original_height,
        )

        detections.append({
            "class_id": class_id,
            "class_name": CLASS_NAMES[class_id],
            "score": score,
            "box": list(original_box),
        })

    # 执行 NMS 去除重复框
    return non_max_suppression(detections, iou_threshold)


def summarize_counts(detections):
    """统计每个类别的检测数量

    输出格式与项目中原来的 PyTorch 推理脚本保持一致。

    Args:
        detections: parse_yolo_output() 返回的检测结果列表

    Returns:
        dict: {"cboard": 2, "dmj4310": 1, ...} 按类别名排序
    """
    counts = {}
    for det in detections:
        name = det["class_name"]
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


# ═══════════════════════════════════════════════════════════════════════════════
# 调试可视化
# ═══════════════════════════════════════════════════════════════════════════════

def draw_detections(image, detections):
    """在图像上绘制检测框、类别名和置信度

    用于调试和可视化验证, 不用于生产环境。

    Args:
        image: OpenCV BGR 图像
        detections: parse_yolo_output() 返回的检测结果列表

    Returns:
        标注后图像的副本
    """
    annotated = image.copy()
    for det in detections:
        x1, y1, x2, y2 = [int(round(v)) for v in det["box"]]
        class_name = det["class_name"]
        score = det["score"]
        label = f"{class_name} {score:.2f}"

        # 绿色矩形框
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
        # 文字标签
        label_y = max(0, y1 - 8)
        cv2.putText(
            annotated, label,
            (x1, label_y),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA,
        )

    return annotated
