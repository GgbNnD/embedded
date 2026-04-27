from __future__ import annotations

import shutil

VALID_CAMERA_BACKENDS = {"auto", "opencv", "rpicam"}


def resolve_camera_backend(requested_backend: str, *, rpicam_executable: str) -> str:
    backend = requested_backend.strip().lower()
    if backend not in VALID_CAMERA_BACKENDS:
        supported = ", ".join(sorted(VALID_CAMERA_BACKENDS))
        raise ValueError(f"Unsupported camera_backend '{requested_backend}', expected one of: {supported}")

    if backend != "auto":
        return backend

    return "rpicam" if shutil.which(rpicam_executable) else "opencv"


def build_rpicam_command(
    executable: str,
    *,
    width: int,
    height: int,
    timeout_ms: int,
) -> list[str]:
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be positive")

    return [
        executable,
        "-n",
        "-t",
        str(int(timeout_ms)),
        "--width",
        str(int(width)),
        "--height",
        str(int(height)),
        "--encoding",
        "jpg",
        "-o",
        "-",
    ]
