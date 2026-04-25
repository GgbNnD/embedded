from __future__ import annotations

import time

import cv2
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image

from client.image_utils import bgr_to_image_msg
from client.srv import CaptureImage


class CameraNode(Node):
    def __init__(self) -> None:
        super().__init__("camera_node")

        self.declare_parameter("camera_index", 0)
        self.declare_parameter("width", 1280)
        self.declare_parameter("height", 720)
        self.declare_parameter("fps", 15.0)
        self.declare_parameter("preview_topic", "/client/camera/preview")
        self.declare_parameter("capture_service", "/client/camera/capture_image")
        self.declare_parameter("reopen_interval_sec", 2.0)

        self.camera_index = int(self.get_parameter("camera_index").value)
        self.width = int(self.get_parameter("width").value)
        self.height = int(self.get_parameter("height").value)
        self.fps = max(float(self.get_parameter("fps").value), 1.0)
        self.reopen_interval_sec = max(float(self.get_parameter("reopen_interval_sec").value), 0.5)

        preview_topic = str(self.get_parameter("preview_topic").value)
        capture_service = str(self.get_parameter("capture_service").value)

        self.preview_publisher = self.create_publisher(Image, preview_topic, 10)
        self.capture_service = self.create_service(CaptureImage, capture_service, self._handle_capture_image)

        self._capture = None
        self._last_frame = None
        self._last_open_attempt_sec = 0.0
        self._last_failure_log_sec = 0.0

        self._timer = self.create_timer(1.0 / self.fps, self._capture_preview_frame)
        self._open_camera()

        self.get_logger().info(f"Preview topic: {preview_topic}")
        self.get_logger().info(f"Capture service: {capture_service}")

    def _open_camera(self) -> None:
        now_sec = time.monotonic()
        self._last_open_attempt_sec = now_sec

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

    def _capture_preview_frame(self) -> None:
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

        self._last_frame = frame.copy()
        msg = bgr_to_image_msg(frame, frame_id="client_camera")
        msg.header.stamp = self.get_clock().now().to_msg()
        self.preview_publisher.publish(msg)

    def _handle_capture_image(self, request: CaptureImage.Request, response: CaptureImage.Response) -> CaptureImage.Response:
        del request

        if self._last_frame is None:
            response.ok = False
            response.message = "No camera frame available"
            return response

        response.ok = True
        response.message = "Captured latest camera frame"
        response.image = bgr_to_image_msg(self._last_frame.copy(), frame_id="client_capture")
        response.image.header.stamp = self.get_clock().now().to_msg()
        return response

    def destroy_node(self) -> bool:
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
