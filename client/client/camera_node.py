"""
OpenCV 摄像头捕获模块 (RK3399Pro 简化版)
==========================================
从原有的 client/camera_node.py 简化而来。

变更说明:
  - 移除了 rpicam 后端 (RK3399Pro 不使用 Raspberry Pi 摄像头专用 API)
  - 仅保留 OpenCV (cv2.VideoCapture) 后端
  - 移除了 camera_backend.py 依赖
  - 保持了原有的接口兼容: CaptureResult, get_latest_frame_snapshot(), capture_image()
  - 摄像头自动重新打开机制 (reopen_interval_sec 间隔)

在 RK3399Pro 上, 摄像头通常是 USB 摄像头或 MIPI CSI 摄像头,
两者都可以通过 OpenCV 的 VideoCapture 接口访问。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass
class CaptureResult:
    """摄像头捕获结果"""
    ok: bool                              # 捕获是否成功
    message: str                          # 状态消息
    image: Optional[np.ndarray] = None    # 捕获到的图像 (BGR 格式)


class CameraNode:
    """OpenCV 摄像头节点 (RK3399Pro 专用)

    在后台线程中持续从摄像头读取帧, 并提供同步快照接口。
    自动处理摄像头断线重连。

    典型用法:
        camera = CameraNode(camera_index=0, width=1280, height=720, fps=5.0)
        camera.start()
        frame, seq = camera.get_latest_frame_snapshot()
        result = camera.capture_image("face")
        if result.ok:
            process(result.image)
        camera.stop()
    """

    def __init__(self,
                 camera_index=0,
                 width=1280,
                 height=720,
                 fps=5.0,
                 reopen_interval_sec=2.0,
                 logger=None):
        """初始化摄像头节点

        Args:
            camera_index: OpenCV 摄像头设备索引 (0=/dev/video0, 1=/dev/video1, ...)
            width: 捕获帧宽度 (像素)
            height: 捕获帧高度 (像素)
            fps: 预览帧率 (Hz, 建议 5~15)
            reopen_interval_sec: 摄像头掉线后重新打开的间隔 (秒)
            logger: 日志记录器
        """
        self._log = logger or logging.getLogger("client.camera")

        self._camera_index = int(camera_index)
        self._width = int(width)
        self._height = int(height)
        self._fps = max(float(fps), 1.0)
        self._reopen_interval_sec = max(float(reopen_interval_sec), 0.5)

        # OpenCV VideoCapture 对象
        self._capture = None

        # 最新的帧缓存 (线程安全)
        self._last_frame = None
        self._last_frame_seq = 0
        self._frame_lock = threading.Lock()

        # 用于控制背景线程的启停
        self._capture_lock = threading.Lock()

        # 线程管理
        self._stop_event = threading.Event()
        self._thread = None

        # 失败日志节流 (避免日志刷屏)
        self._last_failure_log_sec = 0.0

    # ─── 生命周期 ───

    def start(self):
        """启动摄像头捕获线程

        如果线程已在运行, 则直接返回 (幂等操作)。
        摄像头在后台线程中自动打开。
        """
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._capture_loop, name="camera-capture", daemon=True,
        )
        self._thread.start()

        self._log.info(
            "摄像头已启动: 索引=%s, 分辨率=%sx%s, 帧率=%.1f FPS",
            self._camera_index, self._width, self._height, self._fps,
        )

    def stop(self):
        """停止摄像头捕获线程并释放资源"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._release_capture()
        self._log.info("摄像头已停止")

    # ─── 帧访问接口 ───

    def get_latest_frame(self):
        """获取最新的预览帧 (便捷方法, 返回 None 或 np.ndarray)"""
        frame, _ = self.get_latest_frame_snapshot()
        return frame

    def get_latest_frame_snapshot(self):
        """获取最新的预览帧及其序号 (线程安全)

        Returns:
            (frame: np.ndarray | None, seq: int)
            frame 为帧数据的副本, 调用方可安全修改
            seq 为单调递增的帧序号, 用于检测帧是否更新
        """
        with self._frame_lock:
            if self._last_frame is None:
                return None, self._last_frame_seq
            # 返回副本, 防止帧被并发修改
            return self._last_frame.copy(), self._last_frame_seq

    def capture_image(self, reason=""):
        """捕获一帧图像 (用于人脸识别或物资检测)

        优先返回最新的缓存帧 (速度快), 若缓存为空则同步等待新帧。

        Args:
            reason: 捕获用途描述 (仅用于日志, 如 "face", "pre_material")

        Returns:
            CaptureResult 对象, ok=True 表示成功获取到图像
        """
        # 优先使用缓存帧
        frame, _ = self.get_latest_frame_snapshot()
        if frame is not None:
            return CaptureResult(
                ok=True,
                message=f"已获取最新帧 (用途: {reason})",
                image=frame,
            )

        # 缓存为空, 尝试同步捕获
        frame = self._capture_frame()
        if frame is None:
            return CaptureResult(
                ok=False,
                message="摄像头无可用帧",
                image=None,
            )

        self._store_last_frame(frame)
        return CaptureResult(
            ok=True,
            message=f"已捕获帧 (用途: {reason})",
            image=frame,
        )

    # ─── 背景捕获循环 ───

    def _capture_loop(self):
        """后台捕获循环: 按 FPS 周期采集帧并缓存

        在每个周期中:
          1. 从摄像头读取一帧
          2. 存入 _last_frame 缓存 (带序号)
          3. 按 1/FPS 间隔休眠, 休眠期间响应 _stop_event

        休眠以 50ms 为单位分段, 确保 stop() 响应延迟不超过 50ms。
        """
        period_sec = 1.0 / self._fps
        while not self._stop_event.is_set():
            start_sec = time.monotonic()

            # 抓取一帧
            frame = self._capture_frame()
            if frame is not None:
                self._store_last_frame(frame)

            # 计算剩余休眠时间, 分段休眠以快速响应 stop()
            sleep_sec = max(0.0, period_sec - (time.monotonic() - start_sec))
            if sleep_sec > 0:
                if self._stop_event.wait(sleep_sec):
                    return

    def _capture_frame(self):
        """从 OpenCV 摄像头读取一帧

        自动处理摄像头掉线重连 (在 reopen_interval_sec 后重新打开)。
        使用 _capture_lock 确保单线程访问 VideoCapture 对象。

        Returns:
            BGR 格式 np.ndarray, 读取失败返回 None
        """
        with self._capture_lock:
            cap = self._ensure_capture_open_locked()
            if cap is None:
                return None

            # 读取一帧
            success, frame = cap.read()
            if not success or frame is None:
                self._throttled_warn("摄像头读取帧失败, 将尝试重新打开")
                cap.release()
                self._capture = None
                return None

            return frame

    def _ensure_capture_open_locked(self):
        """确保 OpenCV VideoCapture 已打开 (在 _capture_lock 锁内调用)

        若 _capture 为 None, 尝试打开摄像头。
        若摄像头不可用, 等待 reopen_interval_sec 后重试 (节流日志)。

        Returns:
            cv2.VideoCapture 对象, 失败返回 None
        """
        if self._capture is not None:
            return self._capture

        # 尝试打开摄像头
        cap = cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            self._throttled_warn(
                f"无法打开摄像头 (索引 {self._camera_index}), "
                f"{self._reopen_interval_sec}秒后重试..."
            )
            cap.release()
            return None

        # 设置分辨率 (实际分辨率取决于摄像头硬件能力)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self._width))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self._height))
        cap.set(cv2.CAP_PROP_FPS, float(self._fps))

        self._capture = cap
        self._log.info(
            "已打开摄像头 索引=%s, 分辨率=%sx%s, 目标帧率=%.1f FPS",
            self._camera_index, self._width, self._height, self._fps,
        )
        return cap

    def _release_capture(self):
        """释放 OpenCV VideoCapture 资源"""
        with self._capture_lock:
            if self._capture is not None:
                self._capture.release()
                self._capture = None

    def _store_last_frame(self, frame):
        """将帧存入缓存 (线程安全, 带序号)

        Args:
            frame: BGR 格式 np.ndarray
        """
        with self._frame_lock:
            self._last_frame = frame.copy()
            self._last_frame_seq += 1

    def _throttled_warn(self, message):
        """节流日志警告 (避免同类错误刷屏)

        同一类型的警告在 reopen_interval_sec 内只输出一次。

        Args:
            message: 警告消息
        """
        now_sec = time.monotonic()
        if now_sec - self._last_failure_log_sec >= self._reopen_interval_sec:
            self._log.warning(message)
            self._last_failure_log_sec = now_sec


# ═══════════════════════════════════════════════════════════════════════════════
# 独立测试入口
# ═══════════════════════════════════════════════════════════════════════════════

def main(argv=None):
    """测试摄像头捕获: 打开摄像头, 等待首帧, 保存为文件"""
    import argparse

    parser = argparse.ArgumentParser(
        description="测试 OpenCV 摄像头捕获 (保存一帧到文件)",
    )
    parser.add_argument("--camera-index", type=int, default=0, help="摄像头设备索引")
    parser.add_argument("--width", type=int, default=1280, help="捕获宽度")
    parser.add_argument("--height", type=int, default=720, help="捕获高度")
    parser.add_argument("--fps", type=float, default=5.0, help="帧率")
    parser.add_argument("--output", default="camera_test.jpg", help="输出图片路径")
    parser.add_argument("--timeout-sec", type=float, default=10.0, help="等待首帧超时秒数")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
    )

    camera = CameraNode(
        camera_index=args.camera_index,
        width=args.width,
        height=args.height,
        fps=args.fps,
    )
    camera.start()

    deadline = time.monotonic() + max(float(args.timeout_sec), 0.1)
    try:
        frame = None
        while time.monotonic() < deadline:
            frame = camera.get_latest_frame()
            if frame is not None:
                break
            time.sleep(0.1)

        if frame is None:
            raise RuntimeError(f"在 {args.timeout_sec}s 内没有收到摄像头的首帧")

        success = cv2.imwrite(args.output, frame)
        if not success:
            raise RuntimeError(f"保存图片到 {args.output} 失败")
        print(f"已保存测试帧到: {args.output}")
    finally:
        camera.stop()


if __name__ == "__main__":
    main()
