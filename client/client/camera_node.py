from __future__ import annotations

import subprocess
import threading
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image

from client.camera_backend import build_rpicam_command, resolve_camera_backend
from client.image_utils import bgr_to_image_msg
from client.srv import CaptureImage


class CameraNode(Node):
    def __init__(self) -> None:
        super().__init__("camera_node")

        self.declare_parameter("camera_index", 0)
        self.declare_parameter("camera_backend", "auto")
        self.declare_parameter("width", 1280)
        self.declare_parameter("height", 720)
        self.declare_parameter("fps", 15.0)
        self.declare_parameter("rpicam_executable", "rpicam-still")
        self.declare_parameter("rpicam_timeout_ms", 1)
        self.declare_parameter("preview_topic", "/client/camera/preview")
        self.declare_parameter("capture_service", "/client/camera/capture_image")
        self.declare_parameter("reopen_interval_sec", 2.0)

        self.camera_index = int(self.get_parameter("camera_index").value)
        requested_backend = str(self.get_parameter("camera_backend").value)
        self.width = int(self.get_parameter("width").value)
        self.height = int(self.get_parameter("height").value)
        self.fps = max(float(self.get_parameter("fps").value), 1.0)
        self.rpicam_executable = str(self.get_parameter("rpicam_executable").value)
        self.rpicam_timeout_ms = max(int(self.get_parameter("rpicam_timeout_ms").value), 1)
        self.reopen_interval_sec = max(float(self.get_parameter("reopen_interval_sec").value), 0.5)
        self.camera_backend = resolve_camera_backend(
            requested_backend,
            rpicam_executable=self.rpicam_executable,
        )

        preview_topic = str(self.get_parameter("preview_topic").value)
        capture_service = str(self.get_parameter("capture_service").value)

        self.preview_publisher = self.create_publisher(Image, preview_topic, 10)
        self.capture_service = self.create_service(CaptureImage, capture_service, self._handle_capture_image)

        self._capture = None
        self._last_frame = None
        self._last_frame_seq = 0
        self._last_published_frame_seq = 0
        self._last_open_attempt_sec = 0.0
        self._last_failure_log_sec = 0.0
        self._frame_lock = threading.Lock()
        self._rpicam_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._rpicam_thread: threading.Thread | None = None

        self._timer = self.create_timer(1.0 / self.fps, self._publish_preview_frame)
        self._open_camera()

        self.get_logger().info(f"Camera backend: {self.camera_backend}")
        if self.camera_backend == "rpicam":
            self.get_logger().info(f"rpicam executable: {self.rpicam_executable}")
            self.get_logger().info("Parameter camera_index is ignored when using the rpicam backend")
        self.get_logger().info(f"Preview topic: {preview_topic}")
        self.get_logger().info(f"Capture service: {capture_service}")

    def _open_camera(self) -> None:
        now_sec = time.monotonic()
        self._last_open_attempt_sec = now_sec

        if self.camera_backend == "rpicam":
            if self._rpicam_thread is not None and self._rpicam_thread.is_alive():
                return

            self._stop_event.clear()
            self._rpicam_thread = threading.Thread(target=self._rpicam_capture_loop, daemon=True)
            self._rpicam_thread.start()
            self.get_logger().info(
                f"Started rpicam capture loop at {self.width}x{self.height} target {self.fps:.1f} FPS"
            )
            return

        if self._capture is not None:
            self._capture.release()
            self._capture = None

        capture = cv2.VideoCapture(self.camera_index)
        if not capture.isOpened():
            self._throttled_warn(f"Failed to open camera index {self.camera_index}")
            capture.release()
            return

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))
        capture.set(cv2.CAP_PROP_FPS, float(self.fps))
        self._capture = capture
        self.get_logger().info(
            f"Opened camera index {self.camera_index} at {self.width}x{self.height} target {self.fps:.1f} FPS"
        )

    def _throttled_warn(self, message: str) -> None:
        now_sec = time.monotonic()
        if now_sec - self._last_failure_log_sec >= 2.0:
            self.get_logger().warn(message)
            self._last_failure_log_sec = now_sec

    def _store_last_frame(self, frame: np.ndarray) -> None:
        with self._frame_lock:
            self._last_frame = frame.copy()
            self._last_frame_seq += 1

    def _get_last_frame_copy(self) -> tuple[np.ndarray | None, int]:
        with self._frame_lock:
            if self._last_frame is None:
                return None, self._last_frame_seq
            return self._last_frame.copy(), self._last_frame_seq

    def _publish_ros_frame(self, frame: np.ndarray, *, frame_id: str) -> None:
        msg = bgr_to_image_msg(frame, frame_id=frame_id)
        msg.header.stamp = self.get_clock().now().to_msg()
        self.preview_publisher.publish(msg)

    def _capture_frame_with_rpicam(self) -> np.ndarray | None:
        command = build_rpicam_command(
            self.rpicam_executable,
            width=self.width,
            height=self.height,
            timeout_ms=self.rpicam_timeout_ms,
        )

        try:
            with self._rpicam_lock:
                result = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=max(5.0, (self.rpicam_timeout_ms / 1000.0) + 5.0),
                )
        except FileNotFoundError:
            self._throttled_warn(f"rpicam executable not found: {self.rpicam_executable}")
            return None
        except subprocess.TimeoutExpired:
            self._throttled_warn(f"{self.rpicam_executable} timed out while capturing a frame")
            return None
        except Exception as exc:
            self._throttled_warn(f"Unexpected rpicam capture error: {exc}")
            return None

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="ignore").strip()
            if len(stderr) > 200:
                stderr = f"{stderr[:197]}..."
            self._throttled_warn(
                f"{self.rpicam_executable} exited with code {result.returncode}: {stderr or 'no stderr output'}"
            )
            return None

        if not result.stdout:
            self._throttled_warn(f"{self.rpicam_executable} returned an empty frame")
            return None

        encoded = np.frombuffer(result.stdout, dtype=np.uint8)
        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if frame is None:
            self._throttled_warn(f"Failed to decode JPEG output from {self.rpicam_executable}")
            return None
        return frame

    def _rpicam_capture_loop(self) -> None:
        period_sec = 1.0 / self.fps
        while not self._stop_event.is_set():
            start_sec = time.monotonic()
            frame = self._capture_frame_with_rpicam()
            if frame is not None:
                self._store_last_frame(frame)

            sleep_sec = max(0.0, period_sec - (time.monotonic() - start_sec))
            if self._stop_event.wait(sleep_sec):
                return

    def _publish_preview_frame(self) -> None:
        if self.camera_backend == "rpicam":
            self._publish_rpicam_preview_frame()
            return

        self._capture_opencv_preview_frame()

    def _publish_rpicam_preview_frame(self) -> None:
        frame, frame_seq = self._get_last_frame_copy()
        if frame is None:
            now_sec = time.monotonic()
            if (
                (self._rpicam_thread is None or not self._rpicam_thread.is_alive())
                and now_sec - self._last_open_attempt_sec >= self.reopen_interval_sec
            ):
                self._open_camera()
            return

        if frame_seq == self._last_published_frame_seq:
            return

        self._last_published_frame_seq = frame_seq
        self._publish_ros_frame(frame, frame_id="client_camera")

    def _capture_opencv_preview_frame(self) -> None:
        now_sec = time.monotonic()
        if self._capture is None:
            if now_sec - self._last_open_attempt_sec >= self.reopen_interval_sec:
                self._open_camera()
            return

        success, frame = self._capture.read()
        if not success or frame is None:
            self._throttled_warn("Failed to read frame from camera, will retry opening the device")
            self._capture.release()
            self._capture = None
            return

        self._store_last_frame(frame)
        self._publish_ros_frame(frame, frame_id="client_camera")

    def _handle_capture_image(self, request: CaptureImage.Request, response: CaptureImage.Response) -> CaptureImage.Response:
        del request

        frame, _ = self._get_last_frame_copy()
        if frame is None and self.camera_backend == "rpicam":
            frame = self._capture_frame_with_rpicam()
            if frame is not None:
                self._store_last_frame(frame)

        if frame is None:
            response.ok = False
            response.message = "No camera frame available"
            return response

        response.ok = True
        response.message = "Captured latest camera frame"
        response.image = bgr_to_image_msg(frame, frame_id="client_capture")
        response.image.header.stamp = self.get_clock().now().to_msg()
        return response

    def destroy_node(self) -> bool:
        self._stop_event.set()
        if self._rpicam_thread is not None:
            self._rpicam_thread.join(timeout=2.0)
            self._rpicam_thread = None
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        return super().destroy_node()


def main() -> None:
    rclpy.init()
    node = CameraNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
