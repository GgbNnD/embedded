"""
RKNN NPU YOLO 物资检测模块
==========================
在 RK3399Pro 的 NPU 上运行 YOLO 模型进行物资检测。

使用 RKNN Toolkit Lite 进行推理:
  - 在 aarch64 板端使用 rknnlite.api.RKNNLite
  - 在 x86 开发机上可使用模拟模式 (ONNX 或跳过)

模型要求:
  - 已转换为 RK3399Pro 兼容的 .rknn 文件 (int8 量化)
  - 模型路径: models/last_int8_rk3399pro.rknn

推理流程:
  1. 加载 RKNN 模型 (load_rknn)
  2. 初始化 NPU runtime (init_runtime)
  3. 预处理输入图像 (letterbox + BGR→RGB + uint8 NHWC)
  4. 执行 NPU 推理 (inference)
  5. 后处理输出 (yolo_postprocess.parse_yolo_output)
  6. 返回检测结果和物资计数

注意:
  - rknn-toolkit (PC端) 和 rknn-toolkit-lite (板端) 的 API 非常相似
  - 在板端, init_runtime() 不需要指定 target 参数
  - 在 PC 端开发时, 使用 onnx 后端进行模拟验证
"""

from pathlib import Path
import logging

import cv2
import numpy as np

from client.yolo_postprocess import (
    prepare_input_tensor,
    parse_yolo_output,
    summarize_counts,
    CLASS_NAMES,
)


class YoloDetector:
    """RKNN NPU YOLO 物资检测器

    封装了模型加载、NPU 推理、结果解析的完整流程。

    典型用法:
        detector = YoloDetector(model_path="models/last_int8_rk3399pro.rknn")
        detector.load()
        counts = detector.detect(bgr_image)
        # counts = {"cboard": 2, "m3508": 1}
        detector.release()
    """

    def __init__(self,
                 model_path,
                 conf_threshold=0.25,
                 iou_threshold=0.45,
                 image_size=640,
                 logger=None):
        """初始化 YOLO 检测器

        Args:
            model_path: RKNN 模型文件路径 (.rknn)
            conf_threshold: 置信度阈值 (0~1), 默认 0.25
            iou_threshold: NMS IoU 阈值 (0~1), 默认 0.45
            image_size: 模型输入尺寸 (正方形), 默认 640
            logger: 日志记录器
        """
        self._log = logger or logging.getLogger("client.yolo")

        self._model_path = Path(model_path).expanduser().resolve()
        self._conf_threshold = float(conf_threshold)
        self._iou_threshold = float(iou_threshold)
        self._image_size = int(image_size)

        # RKNN Lite runtime 对象 (板端使用 RKNNLite, PC 端可能为 None)
        self._rknn = None
        self._loaded = False

    # ─── 生命周期 ───

    def load(self):
        """加载 RKNN 模型并初始化 NPU runtime

        在 RK3399Pro 板端:
          - 使用 rknnlite.api.RKNNLite
          - init_runtime() 不传 target (aarch64 自动识别)

        在 x86 开发机:
          - 尝试导入 RKNNLite for x86 (模拟)
          - 若不可用, 抛出 RuntimeError

        Raises:
            FileNotFoundError: 模型文件不存在
            RuntimeError: NPU 初始化失败
        """
        if not self._model_path.exists():
            raise FileNotFoundError(f"RKNN 模型文件不存在: {self._model_path}")

        # 尝试加载 RKNN Toolkit Lite
        try:
            from rknnlite.api import RKNNLite
            self._rknn = RKNNLite()
            self._log.info("使用 RKNN Toolkit Lite API")
        except ImportError:
            raise RuntimeError(
                "未安装 rknn-toolkit-lite。请在 RK3399Pro 板端安装:\n"
                "  rknn_toolkit_lite-1.7.5-cp38-cp38-linux_aarch64.whl"
            )

        # 加载 RKNN 模型
        self._log.info("正在加载 RKNN 模型: %s", self._model_path)
        ret = self._rknn.load_rknn(str(self._model_path))
        if ret != 0:
            raise RuntimeError(f"加载 RKNN 模型失败, 返回码: {ret}")

        # 初始化 NPU runtime (RK3399Pro aarch64 不需要 target 参数)
        self._log.info("正在初始化 NPU runtime...")
        ret = self._rknn.init_runtime()
        if ret != 0:
            raise RuntimeError(f"初始化 NPU runtime 失败, 返回码: {ret}")

        self._loaded = True
        self._log.info("RKNN YOLO 检测器加载完成, 类别: %s", CLASS_NAMES)

    def release(self):
        """释放 RKNN runtime 资源"""
        if self._rknn is not None:
            try:
                self._rknn.release()
            except Exception:
                pass
            self._rknn = None
            self._loaded = False
        self._log.info("RKNN YOLO 检测器已释放")

    # ─── 推理 ───

    def detect(self, image_bgr):
        """对 BGR 图像执行 YOLO 物资检测

        完整流程:
          1. 检查模型是否已加载
          2. Letterbox 预处理 (缩放 + 补边到 640x640)
          3. BGR → RGB + 扩展 batch 维度
          4. NPU 推理
          5. 解析输出 (置信度过滤 + NMS + 坐标还原)
          6. 统计物资数量

        Args:
            image_bgr: OpenCV BGR 格式图像 (np.ndarray, [H, W, 3])

        Returns:
            dict: 物资计数结果 {"cboard": 2, "dmj4310": 0, "m3508": 1}
                  以及中间检测结果 (可选, 用于 debug)
        """
        if not self._loaded:
            self.load()

        original_height, original_width = image_bgr.shape[:2]

        # 步骤1: 预处理 (letterbox + BGR→RGB + uint8 NHWC)
        input_tensor, scale, pad_left, pad_top = prepare_input_tensor(
            image_bgr, self._image_size,
        )

        # 步骤2: NPU 推理
        self._log.debug("执行 NPU 推理...")
        outputs = self._rknn.inference(inputs=[input_tensor])

        if outputs is None:
            raise RuntimeError("NPU 推理未返回输出")

        # 步骤3: 后处理 (解析检测结果)
        detections = parse_yolo_output(
            outputs,
            conf_threshold=self._conf_threshold,
            iou_threshold=self._iou_threshold,
            scale=scale,
            pad_left=pad_left,
            pad_top=pad_top,
            original_width=original_width,
            original_height=original_height,
        )

        # 步骤4: 统计数量
        counts = summarize_counts(detections)

        self._log.debug("检测结果: %s", counts)
        return counts

    def detect_with_details(self, image_bgr):
        """对 BGR 图像执行检测, 返回详细结果 (包含边界框)

        与 detect() 类似, 但额外返回所有检测框的详细信息。

        Args:
            image_bgr: OpenCV BGR 格式图像

        Returns:
            (counts: dict, detections: list)
            counts: {"cboard": 2, ...}
            detections: [{"class_id": 0, "class_name": "cboard", "score": 0.95, "box": [x1,y1,x2,y2]}, ...]
        """
        if not self._loaded:
            self.load()

        original_height, original_width = image_bgr.shape[:2]

        # 预处理
        input_tensor, scale, pad_left, pad_top = prepare_input_tensor(
            image_bgr, self._image_size,
        )

        # NPU 推理
        outputs = self._rknn.inference(inputs=[input_tensor])
        if outputs is None:
            raise RuntimeError("NPU 推理未返回输出")

        # 后处理
        detections = parse_yolo_output(
            outputs,
            conf_threshold=self._conf_threshold,
            iou_threshold=self._iou_threshold,
            scale=scale,
            pad_left=pad_left,
            pad_top=pad_top,
            original_width=original_width,
            original_height=original_height,
        )

        counts = summarize_counts(detections)
        return counts, detections
