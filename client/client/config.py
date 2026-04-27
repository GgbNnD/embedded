from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass


@dataclass(slots=True)
class ClientConfig:
    camera_index: int = 0
    camera_backend: str = "auto"
    width: int = 1280
    height: int = 720
    fps: float = 5.0
    rpicam_executable: str = "rpicam-still"
    rpicam_timeout_ms: int = 1
    reopen_interval_sec: float = 2.0
    server_host: str = "127.0.0.1"
    server_port: int = 9000
    connect_timeout_sec: float = 3.0
    request_timeout_sec: float = 15.0
    jpeg_quality: int = 90
    face_retry_interval_sec: float = 1.0
    face_timeout_sec: float = 60.0
    settle_delay_sec: float = 3.5
    stable_hold_sec: float = 1.0
    stability_threshold: float = 3.0
    stable_timeout_sec: float = 8.0
    log_level: str = "INFO"


def build_argument_parser(
    description: str,
    *,
    include_camera: bool = True,
    include_server: bool = True,
    include_workflow: bool = True,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)

    if include_camera:
        parser.add_argument("--camera-index", type=int, default=0, help="OpenCV camera device index")
        parser.add_argument(
            "--camera-backend",
            default="auto",
            choices=["auto", "opencv", "rpicam"],
            help="Camera backend. auto prefers rpicam-still when available.",
        )
        parser.add_argument("--width", type=int, default=1280, help="Capture width")
        parser.add_argument("--height", type=int, default=720, help="Capture height")
        parser.add_argument("--fps", type=float, default=5.0, help="Preview and capture FPS")
        parser.add_argument("--rpicam-executable", default="rpicam-still", help="rpicam executable name or path")
        parser.add_argument("--rpicam-timeout-ms", type=int, default=1, help="Single rpicam capture timeout in ms")
        parser.add_argument("--reopen-interval-sec", type=float, default=2.0, help="Retry interval after camera failure")

    if include_server:
        parser.add_argument("--server-host", default="127.0.0.1", help="Remote server host")
        parser.add_argument("--server-port", type=int, default=9000, help="Remote server TCP port")
        parser.add_argument("--connect-timeout-sec", type=float, default=3.0, help="TCP connect timeout")
        parser.add_argument("--request-timeout-sec", type=float, default=15.0, help="TCP request timeout")
        parser.add_argument("--jpeg-quality", type=int, default=90, help="JPEG quality when sending images")

    if include_workflow:
        parser.add_argument("--face-retry-interval-sec", type=float, default=1.0, help="Face retry interval")
        parser.add_argument("--face-timeout-sec", type=float, default=60.0, help="Face recognition timeout")
        parser.add_argument("--settle-delay-sec", type=float, default=3.5, help="Delay before stability check")
        parser.add_argument("--stable-hold-sec", type=float, default=1.0, help="Required stable duration")
        parser.add_argument("--stability-threshold", type=float, default=3.0, help="Gray mean stability threshold")
        parser.add_argument("--stable-timeout-sec", type=float, default=8.0, help="Max wait for stable preview")

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> ClientConfig:
    data = asdict(ClientConfig())
    for key in data:
        if hasattr(args, key):
            data[key] = getattr(args, key)

    return ClientConfig(
        camera_index=int(data["camera_index"]),
        camera_backend=str(data["camera_backend"]),
        width=int(data["width"]),
        height=int(data["height"]),
        fps=max(float(data["fps"]), 1.0),
        rpicam_executable=str(data["rpicam_executable"]),
        rpicam_timeout_ms=max(int(data["rpicam_timeout_ms"]), 1),
        reopen_interval_sec=max(float(data["reopen_interval_sec"]), 0.5),
        server_host=str(data["server_host"]),
        server_port=int(data["server_port"]),
        connect_timeout_sec=max(float(data["connect_timeout_sec"]), 0.1),
        request_timeout_sec=max(float(data["request_timeout_sec"]), 0.1),
        jpeg_quality=max(1, min(int(data["jpeg_quality"]), 100)),
        face_retry_interval_sec=max(float(data["face_retry_interval_sec"]), 0.1),
        face_timeout_sec=max(float(data["face_timeout_sec"]), 1.0),
        settle_delay_sec=max(float(data["settle_delay_sec"]), 0.0),
        stable_hold_sec=max(float(data["stable_hold_sec"]), 0.1),
        stability_threshold=max(float(data["stability_threshold"]), 0.0),
        stable_timeout_sec=max(float(data["stable_timeout_sec"]), 0.1),
        log_level=str(data["log_level"]),
    )


def parse_config(
    argv: list[str] | None = None,
    *,
    description: str,
    include_camera: bool = True,
    include_server: bool = True,
    include_workflow: bool = True,
) -> ClientConfig:
    parser = build_argument_parser(
        description,
        include_camera=include_camera,
        include_server=include_server,
        include_workflow=include_workflow,
    )
    args = parser.parse_args(argv)
    return config_from_args(args)
