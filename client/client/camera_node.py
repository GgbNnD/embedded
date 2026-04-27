from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

from client.camera_backend import build_rpicam_command, resolve_camera_backend
from client.config import build_argument_parser, config_from_args


@dataclass(slots=True)
class CaptureResult:
    ok: bool
    message: str
    image: np.ndarray | None = None


class CameraNode:
    def __init__(
        self,
        *,
        camera_index: int = 0,
        camera_backend: str = "auto",
        width: int = 1280,
        height: int = 720,
        fps: float = 15.0,
        rpicam_executable: str = "rpicam-still",
        rpicam_timeout_ms: int = 1,
        reopen_interval_sec: float = 2.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.logger = logger or logging.getLogger("client.camera")
        self.camera_index = int(camera_index)
        self.width = int(width)
        self.height = int(height)
        self.fps = max(float(fps), 1.0)
        self.rpicam_executable = rpicam_executable
        self.rpicam_timeout_ms = max(int(rpicam_timeout_ms), 1)
        self.reopen_interval_sec = max(float(reopen_interval_sec), 0.5)
        self.camera_backend = resolve_camera_backend(
            camera_backend,
            rpicam_executable=self.rpicam_executable,
        )

        self._capture: cv2.VideoCapture | None = None
        self._last_frame: np.ndarray | None = None
        self._last_frame_seq = 0
        self._last_failure_log_sec = 0.0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_lock = threading.Lock()
        self._capture_lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        self.logger.info(
            "Camera started with backend=%s resolution=%sx%s fps=%.1f",
            self.camera_backend,
            self.width,
            self.height,
            self.fps,
        )
        if self.camera_backend == "rpicam":
            self.logger.info("Using rpicam executable: %s", self.rpicam_executable)
        else:
            self.logger.info("Using OpenCV camera index: %s", self.camera_index)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._release_opencv_capture()

    def get_latest_frame(self) -> np.ndarray | None:
        frame, _ = self.get_latest_frame_snapshot()
        return frame

    def get_latest_frame_snapshot(self) -> tuple[np.ndarray | None, int]:
        with self._frame_lock:
            if self._last_frame is None:
                return None, self._last_frame_seq
            return self._last_frame.copy(), self._last_frame_seq

    def capture_image(self, reason: str = "") -> CaptureResult:
        del reason

        frame, _ = self.get_latest_frame_snapshot()
        if frame is not None:
            return CaptureResult(ok=True, message="Captured latest camera frame", image=frame)

        frame = self._capture_frame()
        if frame is None:
            return CaptureResult(ok=False, message="No camera frame available", image=None)

        self._store_last_frame(frame)
        return CaptureResult(ok=True, message="Captured camera frame on demand", image=frame)

    def _capture_loop(self) -> None:
        period_sec = 1.0 / self.fps
        while not self._stop_event.is_set():
            start_sec = time.monotonic()
            frame = self._capture_frame()
            if frame is not None:
                self._store_last_frame(frame)

            sleep_sec = max(0.0, period_sec - (time.monotonic() - start_sec))
            if self._stop_event.wait(sleep_sec):
                return

    def _capture_frame(self) -> np.ndarray | None:
        if self.camera_backend == "rpicam":
            return self._capture_frame_with_rpicam()
        return self._capture_frame_with_opencv()

    def _capture_frame_with_rpicam(self) -> np.ndarray | None:
        command = build_rpicam_command(
            self.rpicam_executable,
            width=self.width,
            height=self.height,
            timeout_ms=self.rpicam_timeout_ms,
        )

        try:
            with self._capture_lock:
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

        encoded = np.frombuffer(result.stdout, dtype=np.uint8)
        if encoded.size == 0:
            self._throttled_warn(f"{self.rpicam_executable} returned an empty frame")
            return None

        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if frame is None:
            self._throttled_warn(f"Failed to decode JPEG output from {self.rpicam_executable}")
            return None
        return frame

    def _capture_frame_with_opencv(self) -> np.ndarray | None:
        with self._capture_lock:
            capture = self._ensure_opencv_capture_locked()
            if capture is None:
                return None

            success, frame = capture.read()
            if not success or frame is None:
                self._throttled_warn("Failed to read frame from OpenCV camera, will retry")
                capture.release()
                self._capture = None
                return None
            return frame

    def _ensure_opencv_capture_locked(self) -> cv2.VideoCapture | None:
        if self._capture is not None:
            return self._capture

        capture = cv2.VideoCapture(self.camera_index)
        if not capture.isOpened():
            self._throttled_warn(f"Failed to open camera index {self.camera_index}")
            capture.release()
            return None

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))
        capture.set(cv2.CAP_PROP_FPS, float(self.fps))
        self._capture = capture
        self.logger.info(
            "Opened OpenCV camera index %s at %sx%s target %.1f FPS",
            self.camera_index,
            self.width,
            self.height,
            self.fps,
        )
        return capture

    def _release_opencv_capture(self) -> None:
        with self._capture_lock:
            if self._capture is not None:
                self._capture.release()
                self._capture = None

    def _store_last_frame(self, frame: np.ndarray) -> None:
        with self._frame_lock:
            self._last_frame = frame.copy()
            self._last_frame_seq += 1

    def _throttled_warn(self, message: str) -> None:
        now_sec = time.monotonic()
        if now_sec - self._last_failure_log_sec >= self.reopen_interval_sec:
            self.logger.warning(message)
            self._last_failure_log_sec = now_sec


def main(argv: list[str] | None = None) -> None:
    parser = build_argument_parser(
        "Capture a single frame to verify the local client camera setup.",
        include_camera=True,
        include_server=False,
        include_workflow=False,
    )
    parser.add_argument("--output", default="client_capture.jpg", help="Where to save the captured image")
    parser.add_argument("--timeout-sec", type=float, default=10.0, help="How long to wait for the first frame")
    args = parser.parse_args(argv)

    config = config_from_args(args)
    logging.basicConfig(level=getattr(logging, config.log_level), format="[%(levelname)s] %(name)s: %(message)s")

    camera = CameraNode(
        camera_index=config.camera_index,
        camera_backend=config.camera_backend,
        width=config.width,
        height=config.height,
        fps=config.fps,
        rpicam_executable=config.rpicam_executable,
        rpicam_timeout_ms=config.rpicam_timeout_ms,
        reopen_interval_sec=config.reopen_interval_sec,
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
            raise RuntimeError("Failed to capture a frame before timeout")

        if not cv2.imwrite(args.output, frame):
            raise RuntimeError(f"Failed to save image to {args.output}")
        print(f"Saved a test frame to {args.output}")
    finally:
        camera.stop()


if __name__ == "__main__":
    main()
