# server

`server` 是一个 ROS 2 Python 包，运行在服务端 PC 上，负责三件事：

- 接收加密出入库记录并写入 CSV（新协议，RK3399Pro 客户端）
- 兼容旧版 ROS2 客户端（物资识别 + 人脸识别，TCP 明文）
- 发布 Web 实时库存看板

## 通信协议

服务端同时支持两套通信协议：

### 新协议 (RK3399Pro 客户端, 加密)

| 端口 | 协议 | 用途 |
|------|------|------|
| `8888` | UDP 组播 | 服务器发现 (向局域网广播自身存在) |
| `8889` | TCP 短连接 | ECDH P-256 握手 (DEVICE_HELLO → DEVICE_HELLO_ACK) |
| `8890` | TCP 长连接 | AES-256-GCM 加密数据通道 (出入库记录) |

### 旧协议 (ROS2 客户端, 明文)

| 端口 | 协议 | 用途 |
|------|------|------|
| `9000` | TCP | 长度前缀明文 TCP (face_image/material_image/inventory_record) |

两套协议可同时运行，互不影响。新协议在 `tcp_bridge_node.py` 中通过 `_handle_encrypted_client()` 处理。

## 目录

```text
server/
├── server/
│   ├── tcp_bridge_node.py          # TCP桥接 + 加密协议监听 (核心)
│   ├── material_counter_node.py    # YOLO物资识别 (ROS2节点, 可选)
│   ├── face_recognize_node.py      # 人脸识别 (ROS2节点, 可选)
│   ├── inventory_web_node.py       # HTTP Web看板
│   ├── inventory_dashboard.py      # CSV数据聚合
│   ├── inventory_dashboard_page.py # 看板HTML模板
│   ├── face_database.py            # 人脸库加载/识别
│   ├── discovery_handlers.py       # UDP发现 + ECDH信令服务
│   ├── encrypted_protocol.py       # AES-GCM加解密 + ACK构造
│   ├── platform_utils.py           # 网络工具
│   ├── image_utils.py              # ROS Image ↔ BGR 转换
│   └── tcp_protocol.py             # 旧协议解析 + 数据类
├── assets/
│   ├── known_face/                 # 已知人脸库
│   └── inventory_records.csv       # 出入库记录 (示例)
├── launch/
│   ├── tcp_bridge.launch.py        # 一键启动所有核心节点
│   ├── inventory_web.launch.py     # 只启动Web看板
│   └── material_counter.launch.py  # 只启动物资识别
└── package.xml
```

## 依赖

- ROS 2 Humble
- Python 3.8+ (`alg` conda 环境)
- `ultralytics` + `face_recognition` + `opencv-python` (ROS2节点)
- `cryptography` + `netifaces` (加密协议)
- `flask` (Web 看板)

## 构建

```bash
conda activate alg
source /opt/ros/humble/setup.bash
pip install cryptography netifaces  # 加密协议依赖

colcon build --packages-select server
source install/setup.bash
export ROS_LOCALHOST_ONLY=1
```

## 启动

### 一键启动（推荐）

```bash
ros2 launch server tcp_bridge.launch.py
```

启动后所有端口自动监听：

```
UDP  8888  → 组播设备发现     (ServerDiscoveryService)
TCP  8889  → ECDH 握手        (EcdhSignalingServer)
TCP  8890  → AES-GCM加密数据  (加密accept线程)
TCP  9000  → 明文TCP桥接      (旧ROS2协议)
HTTP 8600  → Web库存看板      (inventory_web_node)
```

本机打开看板：`http://127.0.0.1:8600`

### 指定端口

```bash
ros2 launch server tcp_bridge.launch.py \
  port:=9100 \
  inventory_csv_path:=/data/inventory.csv
```

### 分开启动

```bash
# 物资识别
ros2 run server material_counter_node

# 人脸识别
ros2 run server face_recognize_node

# TCP桥接 (含加密+明文)
ros2 run server tcp_bridge_node

# Web看板
ros2 run server inventory_web_node
```

## 加密出入库记录处理流程

```
客户端连接 8890
    │
    ▼
_handle_encrypted_client()        # 单个线程处理一个客户端连接
    │
    ├─ recv_encrypted_message()    # 从AES-GCM有线格式解密
    │     └─ ServerPeerKey.get(ip) → 32字节密钥 → aes_gcm_decrypt()
    │
    ├─ _handle_encrypted_request() # 消息路由
    │     └─ "inventory_record" → _process_encrypted_inventory_record()
    │
    ├─ _process_encrypted_inventory_record()
    │     ├─ 验证 time/person/action/items
    │     ├─ 标准化 action: 入库 / 出库
    │     ├─ 写入 CSV (带 request_id, received_at 时间戳)
    │     └─ 构造 ACK 响应
    │
    └─ send_encrypted_message()    # AES-GCM加密 ACK → 发送回客户端
```

## 节点参数

### `tcp_bridge_node`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `host` | `0.0.0.0` | TCP监听地址 (仅旧协议9000端口) |
| `port` | `9000` | TCP监听端口 (旧协议) |
| `request_timeout_sec` | `15.0` | 等待ROS2识别结果超时 |
| `max_connections` | `10` | 最大并发连接数 (旧协议) |
| `material_image_topic` | `/material_counter/image` | 物资识别输入topic |
| `material_result_topic` | `/material_counter/counts` | 物资识别结果topic |
| `face_image_topic` | `/face_recognize/image` | 人脸识别输入topic |
| `face_result_topic` | `/face_recognize/result` | 人脸识别结果topic |
| `inventory_csv_path` | `auto` | CSV记录路径 (auto=server/assets/inventory_records.csv) |

新协议的端口（8888/8889/8890）为硬编码常量，定义在 `discovery_handlers.py` 和 `encrypted_protocol.py` 中。加密协议本身不接受 ROS2 参数覆盖。

## CSV 输出

文件：`server/assets/inventory_records.csv`

列结构：

| 列 | 说明 |
|----|------|
| `request_id` | 请求唯一ID (UUID hex) |
| `record_time` | 操作时间 (ISO 8601) |
| `person` | 操作人姓名 |
| `action` | `入库` 或 `出库` |
| `material_name` | 物资名称 |
| `quantity` | 数量 |
| `received_at` | 服务器接收时间 (ISO 8601) |

每条物资一行。一个出入库操作若有多个物资变化，展开为多行。

## Web 看板

启动后访问 `http://127.0.0.1:8600`。功能包括：

- 实时库存总览（总数 / 入库 / 出库）
- 物资卡片（当前库存、状态标识）
- 搜索过滤
- 最近操作记录
- 单物资详情（库存历史、最近操作人/时间）
- SSE 实时推送刷新

## 单独测试

```bash
# 物资识别
ros2 run server single_image_client --ros-args -p image_path:=/path/to/img.jpg

# 人脸识别
ros2 run server face_recognize_client --ros-args -p image_path:=/path/to/face.jpg

# 检查加密端口是否监听
ss -ltnp | grep 8890      # AES-GCM数据通道
ss -ltnp | grep 8889      # ECDH握手端口
ss -ulnp | grep 8888      # UDP发现端口
```
