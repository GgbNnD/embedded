# 嵌入式物资管理系统

基于 YOLO 物资检测 + 人脸识别的出入库管理系统。客户端运行在 RK3399Pro 开发板上，本地完成人脸识别（dlib）和 NPU 物资检测（RKNN），通过 ECDH + AES-256-GCM 加密 TCP 与服务器通信。

```
┌─────────────────────────────────┐     加密TCP        ┌──────────────────────────────┐
│  RK3399Pro 客户端                │ ◄──────────────► │  服务器 (PC)                  │
│                                 │  UDP发现+ECDH握手  │                              │
│  OpenCV 摄像头                   │                    │  Web 看板 (8600)             │
│  dlib 人脸识别 (本地)             │  仅传输出入库记录    │  CSV 记录写入                 │
│  RKNN NPU YOLO 物资检测 (本地)    │                    │  ROS2 节点 (可选,兼容旧协议)    │
│  tkinter GUI                    │                    │                              │
└─────────────────────────────────┘                    └──────────────────────────────┘
```

## 目录结构

```text
embedded/
├── README.md                     # 项目总览 (本文件)
├── client/                       # RK3399Pro 客户端 (Python 3.8)
│   ├── client/
│   │   ├── camera_node.py        # OpenCV 摄像头 (纯OpenCV,无rpicam)
│   │   ├── face_recognizer.py    # 本地人脸识别 (dlib + face_recognition)
│   │   ├── yolo_detector.py      # NPU物资检测 (rknn-toolkit-lite)
│   │   ├── yolo_postprocess.py   # YOLO后处理 (letterbox/NMS/坐标还原)
│   │   ├── logic_node.py         # 出入库工作流状态机
│   │   ├── logic_utils.py        # 纯函数工具 (差异计算/负载构造/格式化)
│   │   ├── ui_node.py            # tkinter GUI + 模块初始化编排
│   │   ├── config.py             # 26项CLI参数配置
│   │   ├── discovery.py          # UDP组播服务器发现 (端口8888)
│   │   ├── ecdh_handler.py       # ECDH握手处理器 (端口8889)
│   │   ├── encrypted_protocol.py # AES-256-GCM有线协议
│   │   ├── encrypted_tcp_client.py # 加密TCP客户端 (端口8890)
│   │   ├── crypto_utils.py       # ECDH P-256 + AES-256-GCM工具
│   │   ├── peer_key.py           # IP→AES密钥映射 (线程安全)
│   │   └── platform_utils.py     # 网络工具 (IP枚举/非阻塞切换)
│   ├── assets/known_faces/       # 已知人脸库 (需从server复制)
│   ├── models/                   # RKNN模型文件
│   ├── scripts/                  # 启动脚本
│   └── pyproject.toml
├── server/                       # ROS2 服务器 (RO S2 Humble)
│   ├── server/
│   │   ├── tcp_bridge_node.py    # TCP桥接 + 加密协议监听 (端口8888-8890+9000)
│   │   ├── material_counter_node.py  # YOLO物资识别 (可选,兼容旧client)
│   │   ├── face_recognize_node.py    # 人脸识别 (可选,兼容旧client)
│   │   ├── inventory_web_node.py     # HTTP Web看板 (端口8600)
│   │   ├── inventory_dashboard.py    # 看板数据聚合
│   │   ├── discovery_handlers.py     # 服务端UDP发现 + ECDH信令
│   │   ├── encrypted_protocol.py     # 服务端AES-GCM加解密
│   │   └── platform_utils.py
│   ├── assets/
│   │   ├── known_face/           # 已知人脸底库
│   │   └── inventory_records.csv # 出入库记录
│   └── launch/                   # ROS2 launch文件
├── weights/materials_yolo/       # 训练权重 + RKNN模型
├── scripts/                      # 训练/验证/导出/转换脚本
├── configs/                      # 类别配置
├── datasets/materials/           # YOLO训练数据集
└── rknn-toolkit/                 # RKNN Toolkit v1.7.5 + Toolkit Lite
```

## 通信协议

系统使用四端口架构：

| 端口 | 协议 | 用途 |
|------|------|------|
| `8888` | UDP 组播 | 设备自动发现 (DEVICE_BROADCAST 每3秒) |
| `8889` | TCP 短连接 | ECDH P-256 密钥交换 (DEVICE_HELLO → DEVICE_HELLO_ACK) |
| `8890` | TCP 长连接 | AES-256-GCM 加密数据传输 (出入库记录) |
| `9000` | TCP 明文 | 旧协议兼容 (接收图片+人脸识别的ROS2 client) |

### 加密传输有线格式

```
[4字节大端 加密总长][12字节随机IV][AES-GCM密文][16字节GCM Tag]
```

每条消息使用唯一随机 IV，GCM Tag 提供完整性校验，防止篡改和重放攻击。密钥通过 ECDH P-256 协商生成，不在网络中传输。

### 出入库记录 JSON

```json
{
  "type": "inventory_record",
  "time": "2026-07-06T15:30:00+08:00",
  "person": "张三",
  "action": "入库",
  "items": [
    {"name": "cboard", "quantity": 2},
    {"name": "m3508", "quantity": 1}
  ]
}
```

### ACK 响应

```json
{
  "ok": true,
  "type": "inventory_ack",
  "message": "出入库记录已保存",
  "data": {"request_id": "abc123", "rows_written": 2}
}
```

## 环境准备

### 客户端 (RK3399Pro)

RK3399Pro 开发板运行 aarch64 Linux (如 Ubuntu 18.04/20.04)，使用 Python 3.8。

```bash
# 创建 conda 环境
conda create -n rknn python=3.8

# 安装核心依赖
pip install opencv-python numpy Pillow

# 安装加密库
pip install cryptography netifaces

# 安装人脸识别 (dlib需从源码编译,约30分钟)
pip install dlib face_recognition

# 安装 RKNN Toolkit Lite (板端推理)
pip install rknn_toolkit_lite-1.7.5-cp38-cp38-linux_aarch64.whl

# 安装 GUI 支持 (可选,无显示器可跳过)
conda install tk
```

### 服务器 (PC)

服务器需要 ROS 2 Humble 和一个带 ultralytics 的 Python 环境。

```bash
# 使用现有 alg conda 环境
conda activate alg

# 安装额外依赖 (加密通信)
pip install cryptography netifaces

# ROS 2 环境
source /opt/ros/humble/setup.bash
```

## 模型准备

### 1. 训练 YOLO 模型

```bash
conda activate alg
python scripts/train.py --device 0
```

训练产物：
- `weights/materials_yolo/last.pt` — 最新训练权重（服务器部署用）
- `weights/materials_yolo/best.pt` — 验证集最优权重

### 2. 导出为 RKNN (RK3399Pro NPU 用)

使用 `rknn_py38` 环境（Python 3.8 + rknn-toolkit 1.7.5）：

```bash
conda activate rknn_py38

python scripts/convert_last_pt_to_rknn_int8.py \
  --weights weights/materials_yolo/last.pt \
  --rknn weights/materials_yolo/last_int8_rk3399pro.rknn \
  --calib-images datasets/materials/images/train \
  --imgsz 640
```

生成的 `last_int8_rk3399pro.rknn` 复制到板端的 `client/models/` 目录。

## 快速启动

### 启动服务器 (PC)

一键启动所有核心节点（包括 ROS2 识别 + Web 看板 + 加密协议监听）：

```bash
conda activate alg
source /opt/ros/humble/setup.bash
source /home/cells/embedded/install/setup.bash
export ROS_LOCALHOST_ONLY=1

ros2 launch server tcp_bridge.launch.py
```

服务器将启动：

| 服务 | 端口 | 说明 |
|------|------|------|
| UDP 发现 | 8888 | 响应客户端的组播广播 |
| ECDH 信令 | 8889 | 处理密钥交换握手 |
| AES-GCM 数据 | 8890 | 接收加密出入库记录 |
| 明文 TCP | 9000 | 兼容旧版 ROS2 client |

启动后在本机打开 Web 看板：`http://127.0.0.1:8600`

### 启动客户端 (RK3399Pro)

```bash
cd /home/cells/embedded/client

# 确保准备好人脸库（从server复制或自行创建）
ls assets/known_faces/

# 确保准备好RKNN模型
ls models/last_int8_rk3399pro.rknn

# 启动 GUI
python -m client.ui_node
```

客户端会自动通过 UDP 组播发现服务器，完成 ECDH 握手后即可使用。

如果服务器 IP 已知，也可以跳过发现，直接在代码中指定：

```bash
# 通过参数指定服务器（如果组播发现不可用）
python -m client.ui_node \
  --known-face-dir assets/known_faces \
  --rknn-model-path models/last_int8_rk3399pro.rknn \
  --fps 5
```

## 命令行参数 (客户端)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--device-id` | `""` | 设备唯一ID（空则自动生成UUID） |
| `--device-name` | `rk3399pro_inventory_001` | 设备显示名称 |
| `--camera-index` | `0` | OpenCV摄像头设备索引 |
| `--width` | `1280` | 捕获宽度 |
| `--height` | `720` | 捕获高度 |
| `--fps` | `5.0` | 预览帧率 |
| `--known-face-dir` | `assets/known_faces` | 已知人脸库目录 |
| `--face-tolerance` | `0.45` | 人脸匹配容差（0~1，越小越严格） |
| `--face-detection-model` | `hog` | 人脸检测模型（hog/cnn） |
| `--rknn-model-path` | `models/last_int8_rk3399pro.rknn` | RKNN模型路径 |
| `--conf-threshold` | `0.25` | YOLO置信度阈值 |
| `--iou-threshold` | `0.45` | NMS IoU阈值 |
| `--discovery-port` | `8888` | UDP组播发现端口 |
| `--signaling-port` | `8889` | TCP信令端口（ECDH握手） |
| `--data-port` | `8890` | TCP数据端口（加密通道） |
| `--face-retry-interval-sec` | `1.0` | 人脸识别重试间隔 |
| `--face-timeout-sec` | `60.0` | 人脸识别超时 |
| `--log-level` | `INFO` | 日志级别（DEBUG/INFO/WARNING/ERROR） |

## 工作流程

```
  用户点击 Start
       │
       ▼
┌─────────────────┐
│  recognizing_face │  每1秒从摄像头抓帧 → dlib 本地人脸识别
│                   │  超时60s未检测到已知人脸 → error
└───────┬───────────┘
        │ 检测到唯一已知人脸
        ▼
┌──────────────────┐
│ waiting_camera_   │  显示操作人姓名,
│     move          │  提示将摄像头对准物资
└───────┬───────────┘
        │ 用户点击 Capture Materials
        ▼
┌──────────────────┐
│ capturing_pre_    │  抓帧 → RKNN NPU YOLO推理 → 物资计数
│   material        │  (letterbox→NPU→NMS→counts)
└───────┬───────────┘
        │ YOLO检测完成
        ▼
┌──────────────────┐
│  waiting_finish   │  操作前物资已记录,
│                   │  提示用户完成实际出入库操作
└───────┬───────────┘
        │ 用户点击 Finish
        ▼
┌──────────────────┐
│ capturing_post_   │  再次抓帧 → RKNN NPU YOLO推理 → 物资计数
│   material        │
└───────┬───────────┘
        │ YOLO检测完成
        ▼
┌──────────────────┐
│  computing_diff   │  比较前后计数差异 → 生成 inbound/outbound 列表
└───────┬───────────┘
        │ 无变化 → success (跳过上传)
        │ 有变化 → 进入下一阶段
        ▼
┌──────────────────┐
│   submitting_     │  AES-256-GCM加密 → TCP 8890 → 服务器
│   inventory       │  服务器验证 → 写入CSV → ACK
└───────┬───────────┘
        │
        ▼
     success / error
```

## 添加新的人脸

在 `assets/known_faces/` 目录下放置人脸图片：

```text
assets/known_faces/
├── 张三.jpg          # 文件名自动作为人名
├── 李四.png
└── 王五/             # 子目录名作为人名
    ├── photo1.jpg    # 支持每个人员多张图片
    └── photo2.jpg
```

支持格式：`jpg`、`jpeg`、`png`、`bmp`。每张图片只需包含一个人脸，程序取第一个检测到的人脸编码。

## 线程架构

客户端使用以下线程模型：

```
main() [主线程 = tkinter UI loop]
│
├── CameraNode._capture_loop       [daemon]    持续抓帧 → _last_frame缓存
├── LogicNode._tick_loop           [daemon]    每100ms检查人脸识别时机
├── ServerDiscovery._send_loop     [daemon]    每3s UDP组播DEVICE_BROADCAST
├── ServerDiscovery._recv_loop     [daemon]    监听组播 → on_server_found回调
├── EcdhHandler._handshake_loop    [daemon]    主动连接服务器8889 → ECDH握手 → 存密钥
│
└── [临时工作线程, 任务完成后退出]
    ├── 人脸识别线程    抓帧 → FaceRecognizer.recognize() → 推进状态
    ├── 物资检测线程    抓帧 → YoloDetector.detect() → 推进状态
    └── 记录发送线程    加密TCP send → recv ACK → 推进状态
```

## 常见问题

### RKNN 模型加载失败

确认板端已安装 rknn-toolkit-lite：

```bash
python -c "from rknnlite.api import RKNNLite; print('OK')"
```

确认模型文件存在并且是 int8 格式（不是 ONNX 或 .pt）：

```bash
ls -la models/last_int8_rk3399pro.rknn
```

### 人脸识别总是失败

- 确认 `assets/known_faces/` 中有图片
- 确认图片中能检测到人脸（光照充足、正面朝向）
- 尝试调小 `--face-tolerance`（如 `0.35`）
- 查看日志：`--log-level DEBUG`

### 无法发现服务器

- 确认客户端和服务器在同一局域网
- 检查 UDP 端口 8888 是否被防火墙阻挡
- 尝试在服务器上检查：`ss -ulnp | grep 8888`
- 在客户端检查：`python -c "from client.platform_utils import select_local_ip; print(select_local_ip())"`

### 出入库记录未写入

- 确认 ECDH 握手已完成（查看日志中的 "ECDH 握手成功" 消息）
- 检查服务器 CSV 路径：`server/assets/inventory_records.csv`
- 查看服务器日志中的 "加密通道: 收到出入库记录" 消息

### 无显示器环境测试

如需无头测试摄像头和模型加载：

```bash
# 测试摄像头
python -m client.camera_node --output test.jpg --timeout-sec 10

# 测试人脸识别
python -c "
from client.face_recognizer import FaceRecognizer
import cv2
r = FaceRecognizer('assets/known_faces')
r.load()
img = cv2.imread('test.jpg')
print(r.get_single_known_person(img))
"
```

### dlib 编译失败 (aarch64)

RK3399Pro 上 dlib 需从源码编译。如失败，尝试：

```bash
# 安装编译工具链
sudo apt-get install build-essential cmake

# 安装BLAS库（加速dlib）
sudo apt-get install libopenblas-dev liblapack-dev

# 使用单线程编译 (内存受限时)
pip install dlib --no-cache-dir -v
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.8 |
| 推理框架 | RKNN Toolkit Lite 1.7.5 |
| 人脸识别 | dlib + face_recognition |
| 加密 | ECDH P-256 + AES-256-GCM (Python cryptography) |
| 网络 | UDP 组播发现 + TCP 短连接(信令) + TCP长连接(数据) |
| GUI | tkinter |
| 摄像头 | OpenCV VideoCapture |
| 服务端 | ROS 2 Humble + ultralytics + Flask |
| Web 看板 | 内嵌HTML/CSS/JS + SSE推送 |
| 模型 | YOLO11n (训练) → ONNX → RKNN int8 (部署) |
