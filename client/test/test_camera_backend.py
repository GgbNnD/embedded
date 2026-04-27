from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))

from camera_backend import build_rpicam_command, resolve_camera_backend  # noqa: E402


class CameraBackendTests(unittest.TestCase):
    def test_resolve_camera_backend_prefers_rpicam_when_available(self) -> None:
        with patch("camera_backend.shutil.which", return_value="/usr/bin/rpicam-still"):
            self.assertEqual(resolve_camera_backend("auto", rpicam_executable="rpicam-still"), "rpicam")

    def test_resolve_camera_backend_falls_back_to_opencv_when_rpicam_missing(self) -> None:
        with patch("camera_backend.shutil.which", return_value=None):
            self.assertEqual(resolve_camera_backend("auto", rpicam_executable="rpicam-still"), "opencv")

    def test_resolve_camera_backend_rejects_unknown_value(self) -> None:
        with self.assertRaises(ValueError):
            resolve_camera_backend("foo", rpicam_executable="rpicam-still")

    def test_build_rpicam_command_writes_jpeg_to_stdout(self) -> None:
        command = build_rpicam_command("rpicam-still", width=1280, height=720, timeout_ms=1)
        self.assertEqual(
            command,
            [
                "rpicam-still",
                "-n",
                "-t",
                "1",
                "--width",
                "1280",
                "--height",
                "720",
                "--encoding",
                "jpg",
                "-o",
                "-",
            ],
        )


if __name__ == "__main__":
    unittest.main()
