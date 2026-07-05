"""
客户端配置模块 (RK3399Pro 版)
=============================
从原有的 client/config.py 扩展而来。

新增配置项:
  - 网络发现相关 (device_id, discovery_port, ...)
  - ECDH 密钥交换相关
  - 本地人脸识别相关 (known_face_dir, face_tolerance, ...)
  - RKNN YOLO 检测相关 (rknn_model_path, conf_threshold, ...)

移除配置项:
  - rpicam 相关 (rpicam_executable, rpicam_timeout_ms)
  - camera_backend 选择 (固定 opencv)
  - image_format/image_quality (不再发送图像)
"""

import argparse
from dataclasses import asdict, dataclass


@dataclass
class ClientConfig:
    """RK3399Pro 客户端全局配置"""

    # ─── 本机标识 ───
    device_id: str = ""   # 本机 UUID (空字符串表示自动生成)
    device_name: str = "rk3399pro_inventory_001"  # 本机显示名称 (用于组播广播)

    # ─── 摄像头 (仅 OpenCV) ───
    camera_index: int = 0       # OpenCV 摄像头设备索引 (/dev/videoN)
    width: int = 1280           # 捕获帧宽度
    height: int = 720           # 捕获帧高度
    fps: float = 5.0            # 预览帧率 (Hz)
    reopen_interval_sec: float = 2.0  # 摄像头掉线重连间隔

    # ─── 网络发现 (UDP 组播) ───
    discovery_port: int = 8888  # UDP 组播发现端口

    # ─── 加密通信 (ECDH + AES-GCM) ───
    signaling_port: int = 8889  # TCP 信令端口 (ECDH 握手)
    data_port: int = 8890       # TCP 数据端口 (加密数据通道)
    connect_timeout_sec: float = 3.0   # TCP 连接超时
    request_timeout_sec: float = 15.0  # TCP 请求超时

    # ─── 本地人脸识别 (dlib) ───
    known_face_dir: str = "assets/known_faces"  # 已知人脸图片目录
    face_tolerance: float = 0.45                # 人脸匹配容差 (0~1, 越小越严格)
    face_detection_model: str = "hog"           # 人脸检测模型 ("hog" CPU 快速 / "cnn" GPU 精确)

    # ─── RKNN YOLO 物资检测 ───
    rknn_model_path: str = "models/last_int8_rk3399pro.rknn"  # RKNN 模型文件路径
    conf_threshold: float = 0.25   # YOLO 置信度阈值
    iou_threshold: float = 0.45    # NMS IoU 阈值
    yolo_image_size: int = 640     # 模型输入尺寸

    # ─── 工作流 ───
    face_retry_interval_sec: float = 1.0   # 人脸识别重试间隔
    face_timeout_sec: float = 60.0         # 人脸识别超时

    # ─── 日志 ───
    log_level: str = "INFO"  # DEBUG / INFO / WARNING / ERROR


def build_argument_parser(description,
                          include_camera=True,
                          include_network=True,
                          include_workflow=True):
    """构建命令行参数解析器

    Args:
        description: 程序描述
        include_camera: 是否包含摄像头参数组
        include_network: 是否包含网络/加密参数组
        include_workflow: 是否包含工作流参数组

    Returns:
        argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(description=description)

    # ─── 本机标识 ───
    parser.add_argument("--device-id", default="",
                        help="本机唯一标识 (留空自动生成 UUID)")
    parser.add_argument("--device-name", default="rk3399pro_inventory_001",
                        help="本机显示名称 (用于组播广播)")

    # ─── 摄像头 ───
    if include_camera:
        parser.add_argument("--camera-index", type=int, default=0,
                            help="OpenCV 摄像头设备索引 (默认: 0)")
        parser.add_argument("--width", type=int, default=1280,
                            help="捕获帧宽度 (默认: 1280)")
        parser.add_argument("--height", type=int, default=720,
                            help="捕获帧高度 (默认: 720)")
        parser.add_argument("--fps", type=float, default=5.0,
                            help="预览帧率 (默认: 5.0)")
        parser.add_argument("--reopen-interval-sec", type=float, default=2.0,
                            help="摄像头掉线重连间隔 (默认: 2.0)")

    # ─── 网络/加密 ───
    if include_network:
        parser.add_argument("--discovery-port", type=int, default=8888,
                            help="UDP 组播发现端口 (默认: 8888)")
        parser.add_argument("--signaling-port", type=int, default=8889,
                            help="TCP 信令端口 (ECDH 握手, 默认: 8889)")
        parser.add_argument("--data-port", type=int, default=8890,
                            help="TCP 数据端口 (加密数据通道, 默认: 8890)")
        parser.add_argument("--connect-timeout-sec", type=float, default=3.0,
                            help="TCP 连接超时秒数 (默认: 3.0)")
        parser.add_argument("--request-timeout-sec", type=float, default=15.0,
                            help="TCP 请求超时秒数 (默认: 15.0)")

    # ─── 人脸识别 ───
        parser.add_argument("--known-face-dir", default="assets/known_faces",
                            help="已知人脸图片目录 (默认: assets/known_faces)")
        parser.add_argument("--face-tolerance", type=float, default=0.45,
                            help="人脸匹配容差 0~1, 越小越严格 (默认: 0.45)")
        parser.add_argument("--face-detection-model", default="hog",
                            choices=["hog", "cnn"],
                            help="人脸检测模型 (默认: hog, CPU 快速)")

    # ─── RKNN YOLO ───
        parser.add_argument("--rknn-model-path", default="models/last_int8_rk3399pro.rknn",
                            help="RKNN 模型文件路径 (默认: models/last_int8_rk3399pro.rknn)")
        parser.add_argument("--conf-threshold", type=float, default=0.25,
                            help="YOLO 置信度阈值 0~1 (默认: 0.25)")
        parser.add_argument("--iou-threshold", type=float, default=0.45,
                            help="NMS IoU 阈值 0~1 (默认: 0.45)")
        parser.add_argument("--yolo-image-size", type=int, default=640,
                            help="模型输入尺寸 (默认: 640)")

    # ─── 工作流 ───
    if include_workflow:
        parser.add_argument("--face-retry-interval-sec", type=float, default=1.0,
                            help="人脸识别重试间隔 (默认: 1.0)")
        parser.add_argument("--face-timeout-sec", type=float, default=60.0,
                            help="人脸识别超时秒数 (默认: 60.0)")

    # ─── 日志 ───
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="日志级别 (默认: INFO)")

    return parser


def config_from_args(args):
    """从 argparse.Namespace 构造 ClientConfig

    Args:
        args: parse_args() 返回的命名空间

    Returns:
        ClientConfig 对象 (带有默认值回退)
    """
    data = asdict(ClientConfig())
    for key in data:
        if hasattr(args, key):
            data[key] = getattr(args, key)

    return ClientConfig(
        # 本机标识
        device_id=str(data["device_id"]),
        device_name=str(data["device_name"]),

        # 摄像头
        camera_index=int(data["camera_index"]),
        width=int(data["width"]),
        height=int(data["height"]),
        fps=max(float(data["fps"]), 1.0),
        reopen_interval_sec=max(float(data["reopen_interval_sec"]), 0.5),

        # 网络/加密
        discovery_port=int(data["discovery_port"]),
        signaling_port=int(data["signaling_port"]),
        data_port=int(data["data_port"]),
        connect_timeout_sec=max(float(data["connect_timeout_sec"]), 0.1),
        request_timeout_sec=max(float(data["request_timeout_sec"]), 0.1),

        # 人脸识别
        known_face_dir=str(data["known_face_dir"]),
        face_tolerance=max(0.0, min(1.0, float(data["face_tolerance"]))),
        face_detection_model=str(data["face_detection_model"]),

        # RKNN YOLO
        rknn_model_path=str(data["rknn_model_path"]),
        conf_threshold=max(0.0, min(1.0, float(data["conf_threshold"]))),
        iou_threshold=max(0.0, min(1.0, float(data["iou_threshold"]))),
        yolo_image_size=int(data["yolo_image_size"]),

        # 工作流
        face_retry_interval_sec=max(float(data["face_retry_interval_sec"]), 0.1),
        face_timeout_sec=max(float(data["face_timeout_sec"]), 1.0),

        # 日志
        log_level=str(data["log_level"]),
    )


def parse_config(argv=None, description="RK3399Pro 客户端",
                 include_camera=True, include_network=True, include_workflow=True):
    """解析命令行参数并返回 ClientConfig

    一步完成: 构建 parser → 解析 → 构造配置对象

    Args:
        argv: 命令行参数列表 (None 表示使用 sys.argv)
        description: 程序描述
        include_camera: 包含摄像头参数
        include_network: 包含网络参数
        include_workflow: 包含工作流参数

    Returns:
        ClientConfig 对象
    """
    parser = build_argument_parser(
        description,
        include_camera=include_camera,
        include_network=include_network,
        include_workflow=include_workflow,
    )
    args = parser.parse_args(argv)
    return config_from_args(args)
