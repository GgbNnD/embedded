# client — RK3399Pro 客户端

运行在 RK3399Pro 开发板上的独立 Python 客户端。不需要 ROS2，不需要 `colcon`。

## 核心功能

| 功能 | 实现 | 位置 |
|------|------|------|
| 摄像头采集 | OpenCV `cv2.VideoCapture` | `camera_node.py` |
| 人脸识别 | dlib + face_recognition（本地） | `face_recognizer.py` |
| 物资检测 | RKNN NPU YOLO（本地） | `yolo_detector.py` + `yolo_postprocess.py` |
| 服务器发现 | UDP 组播（端口 8888） | `discovery.py` |
| 密钥交换 | ECDH P-256（端口 8889） | `ecdh_handler.py` |
| 加密通信 | AES-256-GCM（端口 8890） | `encrypted_protocol.py` + `encrypted_tcp_client.py` |
| 业务流程 | 状态机：人脸→拍照→检测→差异→加密上报 | `logic_node.py` |
| 用户界面 | tkinter | `ui_node.py` |

## 依赖

```
Python >= 3.8
numpy, opencv-python, Pillow
cryptography, netifaces
dlib, face_recognition
rknn-toolkit-lite >= 1.7.5
```

## 环境安装 (RK3399Pro 板端)

```bash
# 1. 创建环境
conda create -n rknn python=3.8
conda activate rknn

# 2. 基础库
pip install numpy opencv-python Pillow

# 3. 加密通信
pip install cryptography netifaces

# 4. 人脸识别 (dlib 需从源码编译, ~30分钟)
pip install dlib face_recognition

# 5. RKNN NPU 推理
pip install rknn_toolkit_lite-1.7.5-cp38-cp38-linux_aarch64.whl

# 6. GUI (可选)
conda install tk
```

## 准备数据

将服务器上的文件复制到板端：

```bash
# 已知人脸库
scp user@server:/home/cells/embedded/server/assets/known_face/* \
    /home/cells/embedded/client/assets/known_faces/

# RKNN 模型
scp user@server:/home/cells/embedded/weights/materials_yolo/last_int8_rk3399pro.rknn \
    /home/cells/embedded/client/models/
```

## 启动

```bash
cd /home/cells/embedded/client

# 默认启动 (自动发现服务器)
python -m client.ui_node

# 显式指定参数
python -m client.ui_node \
  --camera-index 0 \
  --fps 5 \
  --known-face-dir assets/known_faces \
  --rknn-model-path models/last_int8_rk3399pro.rknn \
  --face-tolerance 0.45 \
  --conf-threshold 0.25 \
  --log-level INFO
```

## 常用参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--camera-index` | `0` | 摄像头索引 (`/dev/video0`) |
| `--width` | `1280` | 捕获宽度 |
| `--height` | `720` | 捕获高度 |
| `--fps` | `5.0` | 预览帧率 |
| `--known-face-dir` | `assets/known_faces` | 已知人脸库路径 |
| `--face-tolerance` | `0.45` | 人脸匹配容差 |
| `--face-detection-model` | `hog` | `hog`(CPU快) 或 `cnn`(GPU准) |
| `--rknn-model-path` | `models/last_int8_rk3399pro.rknn` | RKNN 模型文件 |
| `--conf-threshold` | `0.25` | YOLO 置信度阈值 |
| `--iou-threshold` | `0.45` | NMS IoU 阈值 |
| `--face-timeout-sec` | `60.0` | 人脸识别超时 |
| `--log-level` | `INFO` | DEBUG / INFO / WARNING / ERROR |

## 调试命令

测试摄像头：

```bash
python -m client.camera_node --output test.jpg --timeout-sec 10
```

测试人脸识别：

```bash
python -c "
from client.face_recognizer import FaceRecognizer
import cv2
r = FaceRecognizer('assets/known_faces')
r.load()
img = cv2.imread('test.jpg')
print(r.get_single_known_person(img))
"
```

## 目录结构

```text
client/
├── client/
│   ├── ui_node.py           # tkinter GUI + main()入口
│   ├── logic_node.py        # 工作流状态机 (idle→face→yolo→submit)
│   ├── logic_utils.py       # 纯函数 (差异计算/负载构造/格式化)
│   ├── config.py            # CLI参数配置
│   ├── camera_node.py       # OpenCV摄像头
│   ├── face_recognizer.py   # 本地dlib人脸识别
│   ├── yolo_detector.py     # RKNN NPU YOLO检测
│   ├── yolo_postprocess.py  # YOLO后处理 (letterbox/NMS)
│   ├── encrypted_tcp_client.py  # 加密TCP客户端
│   ├── encrypted_protocol.py    # AES-GCM有线协议
│   ├── ecdh_handler.py      # ECDH握手处理器
│   ├── discovery.py         # UDP组播发现
│   ├── crypto_utils.py      # ECDH+AES工具
│   ├── peer_key.py          # IP→密钥映射
│   └── platform_utils.py    # 网络工具
├── assets/known_faces/      # 已知人脸库
├── models/                  # RKNN模型
├── scripts/                 # 启动脚本
└── pyproject.toml           # 包配置
```

## 线程模型

```
main() [主线程 = tkinter UI loop]
│
├── CameraNode._capture_loop       [daemon]  每200ms抓帧存入缓存
├── LogicNode._tick_loop           [daemon]  每100ms检查人脸识别时机
├── ServerDiscovery._send_loop     [daemon]  每3s发送UDP组播广播
├── ServerDiscovery._recv_loop     [daemon]  接收组播→触发发现回调
├── EcdhHandler._handshake_loop    [daemon]  连接8889→交换公钥→存密钥
│
└── [临时线程, 任务完成即退出]
    ├── 人脸识别: 抓帧→dlib检测→匹配→推进状态
    ├── 物资检测: 抓帧→letterbox→NPU推理→NMS→推进状态
    └── 记录发送: AES加密→TCP发送→收ACK→推进状态
```

## 常见问题

### dlib 编译失败

```bash
sudo apt-get install build-essential cmake libopenblas-dev
pip install dlib --no-cache-dir -v
```

### cmake 版本太低

dlib 需要 cmake >= 3.1。若系统 cmake 版本过低：

```bash
pip install cmake --upgrade
# 或
sudo apt-get install cmake  # Ubuntu 20.04+已默认3.16
```

### 摄像头打不开

```bash
# 检查设备
ls /dev/video*
v4l2-ctl --list-devices

# 测试
python -c "import cv2; cap=cv2.VideoCapture(0); print(cap.isOpened())"
```

### 板端内存不足

YOLO 模型在 NPU 上运行，NPU 有自己的 DDR。如果系统内存紧张：

```bash
# 关闭不必要的 X11 服务
sudo systemctl stop lightdm

# 增大 swap
sudo fallocate -l 2G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
```
