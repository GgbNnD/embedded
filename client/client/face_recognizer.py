"""
本地人脸识别模块
================
从 server/server/face_database.py 适配, 在 RK3399Pro 板端本地运行。
使用 dlib + face_recognition 库进行人脸检测和识别。

核心功能:
  - 加载已知人脸数据库 (从图片目录)
  - 对输入图像执行人脸检测和识别
  - 返回识别到的人名列表和边界框

已知人脸数据库格式:
  图片目录 (如 assets/known_faces/) 下的文件/子目录结构:
    assets/known_faces/
      ├── 张三.jpg         → 文件名作为人名
      ├── 李四.jpg
      └── 王五/            → 子目录名作为人名
          ├── photo1.jpg
          └── photo2.jpg   → 多张照片取第一张的编码

支持图片格式: .jpg, .jpeg, .png, .bmp

注意:
  - dlib 在 aarch64 上需要从源码编译, 可能需要较长时间
  - 首次加载人脸编码也需要一定时间 (取决于图片数量)
"""

from pathlib import Path
import logging

import cv2
import face_recognition
import numpy as np


# 支持的图片格式
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


class FaceRecognizer:
    """本地人脸识别器

    加载已知人脸数据库, 对灰度/BGR图像执行人脸检测和识别.

    典型用法:
        recognizer = FaceRecognizer(known_face_dir="assets/known_faces")
        recognizer.load()
        results = recognizer.recognize(bgr_image)
        for r in results:
            print(f"Name: {r['name']}, Box: {r['box']}")
    """

    def __init__(self,
                 known_face_dir,
                 tolerance=0.45,
                 detection_model="hog",
                 unknown_label="unknown",
                 logger=None):
        """初始化人脸识别器

        Args:
            known_face_dir: 已知人脸图片目录路径
            tolerance: 人脸匹配容差 (值越小越严格, 默认 0.45)
            detection_model: 人脸检测模型, "hog"(CPU快速) 或 "cnn"(GPU精确)
            unknown_label: 未识别到的人名标签 (默认 "unknown")
            logger: 日志记录器
        """
        self._log = logger or logging.getLogger("client.face")

        self._known_face_dir = Path(known_face_dir).expanduser().resolve()
        self._tolerance = float(tolerance)
        self._detection_model = detection_model
        self._unknown_label = unknown_label

        # 已知人脸编码和对应的名字
        self._known_encodings = []   # list[np.ndarray] 人脸编码向量
        self._known_names = []       # list[str] 对应的人名

        self._loaded = False

    # ─── 加载 ───

    def load(self):
        """扫描已知人脸目录, 加载所有人脸编码

        遍历 known_face_dir 下的所有图片:
          - 文件名 (无后缀) 作为人名
          - 子目录名作为人名
          - 每组人名可以有多个照片文件, 取每张照片的第一个人脸编码

        Raises:
            FileNotFoundError: 已知人脸目录不存在
        """
        if not self._known_face_dir.exists():
            raise FileNotFoundError(f"已知人脸目录不存在: {self._known_face_dir}")

        encodings = []
        names = []

        # 遍历目录, 收集所有 (人名, 图片路径) 对
        for person_name, image_path in self._discover_face_images():
            # 使用 face_recognition 加载图片并提取人脸编码
            image = face_recognition.load_image_file(str(image_path))
            face_encodings = face_recognition.face_encodings(image)

            if not face_encodings:
                self._log.warning("已知人脸图片中未检测到人脸, 已跳过: %s", image_path)
                continue

            if len(face_encodings) > 1:
                self._log.warning("已知人脸图片中检测到多张人脸, 仅使用第一张: %s", image_path)

            # 取第一个检测到的人脸编码
            encodings.append(face_encodings[0])
            names.append(person_name)

        self._known_encodings = encodings
        self._known_names = names
        self._loaded = True

        self._log.info("已加载 %s 个已知人脸编码 (来自 %s)", len(encodings), self._known_face_dir)

    # ─── 识别 ───

    def recognize(self, image_bgr):
        """对 BGR 图像执行人脸检测和识别

        处理流程:
          1. BGR → RGB (face_recognition 要求 RGB 输入)
          2. 检测所有人脸位置 (HOG 或 CNN 模型)
          3. 对每张人脸提取 128 维编码向量
          4. 与已知人脸编码比对, 取最小距离作为匹配结果
          5. 距离 <= 容差 → 判定为已知人; 否则标记为 unknown

        Args:
            image_bgr: OpenCV BGR 格式图像 (np.ndarray)

        Returns:
            识别结果列表, 每个元素为:
            {
                "name": str,        # 人名或 "unknown"
                "distance": float,  # 与已知人脸编码的欧氏距离 (或 None)
                "box": {            # 人脸边界框 (top, right, bottom, left)
                    "top": int,
                    "right": int,
                    "bottom": int,
                    "left": int,
                },
            }
        """
        if not self._loaded:
            self.load()

        # BGR → RGB (face_recognition 使用 RGB)
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)

        # 检测人脸位置 (返回 [(top, right, bottom, left), ...])
        face_locations = face_recognition.face_locations(
            image_rgb,
            model=self._detection_model,
        )

        # 提取每张人脸的 128 维编码向量
        face_encodings = face_recognition.face_encodings(image_rgb, face_locations)

        results = []
        for (top, right, bottom, left), encoding in zip(face_locations, face_encodings):
            name = self._unknown_label
            distance = None

            # 与已知人脸库中的所有人脸比对
            if self._known_encodings:
                distances = face_recognition.face_distance(self._known_encodings, encoding)
                best_index = int(np.argmin(distances))
                best_distance = float(distances[best_index])

                # 最小距离 <= 容差 → 判定为这个人
                if best_distance <= self._tolerance:
                    name = self._known_names[best_index]
                distance = best_distance

            results.append({
                "name": name,
                "distance": distance,
                "box": {
                    "top": int(top),
                    "right": int(right),
                    "bottom": int(bottom),
                    "left": int(left),
                },
            })

        return results

    def get_single_known_person(self, image_bgr):
        """识别图像中的单张已知人脸

        仅当恰好检测到 1 张人脸, 且该人脸与已知数据库匹配时, 返回人名。
        适用于出入库操作前的人脸认证场景。

        Args:
            image_bgr: OpenCV BGR 格式图像

        Returns:
            人名 str (如 "张三"), 若无单张已知人脸则返回 None
        """
        results = self.recognize(image_bgr)

        # 需要恰好 1 张人脸, 且人名不是 unknown
        if len(results) != 1:
            return None

        name = results[0]["name"]
        if name == self._unknown_label:
            return None

        return name

    # ─── 内部辅助 ───

    def _discover_face_images(self):
        """扫描已知人脸目录, 生成 (人名, 图片路径) 迭代器

        支持两种组织方式:
          1. 扁平文件:  known_faces/张三.jpg → 人名为 "张三"
          2. 子目录:    known_faces/张三/photo1.jpg → 人名为 "张三"

        Returns:
            iterable of (person_name: str, image_path: Path)
        """
        entries = []

        for path in sorted(self._known_face_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                # 扁平文件: 文件名 (无后缀) 作为人名
                entries.append((path.stem, path))
            elif path.is_dir():
                # 子目录: 目录名作为人名
                person_name = path.name
                for image_path in sorted(path.iterdir()):
                    if image_path.is_file() and image_path.suffix.lower() in IMAGE_SUFFIXES:
                        entries.append((person_name, image_path))

        return entries


def annotate_faces(image_bgr, results):
    """在图像上绘制人脸边界框和名字

    用于 UI 预览或调试可视化. 绿色矩形框 + 黑色背景白色文字标签.

    Args:
        image_bgr: OpenCV BGR 格式图像
        results: FaceRecognizer.recognize() 返回的结果列表

    Returns:
        标注后图像的副本 (原始图像不被修改)
    """
    annotated = image_bgr.copy()
    for result in results:
        box = result["box"]
        left = int(box["left"])
        top = int(box["top"])
        right = int(box["right"])
        bottom = int(box["bottom"])
        name = str(result["name"])

        # 画绿色矩形框
        cv2.rectangle(annotated, (left, top), (right, bottom), (0, 255, 0), 2)
        # 画标签背景 (黑色填充)
        cv2.rectangle(annotated, (left, max(top - 28, 0)), (right, top), (0, 255, 0), cv2.FILLED)
        # 写文字
        cv2.putText(
            annotated,
            name,
            (left + 4, max(top - 8, 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

    return annotated
