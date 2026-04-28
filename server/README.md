# server

`server` 是一个 ROS 2 Python 包，负责三件事：

- 物资图片识别与数量统计
- 人脸图片识别
- 通过 TCP 对外提供统一接口，并把出入库记录写入 CSV
- 读取 CSV 并在本机发布实时 Web 看板

它适合部署在“服务端电脑”上运行。`client` 包通过 TCP 连接到这里，不需要和 `server` 机器做跨机器 ROS 通信。

## 1. 功能概览

包内主要节点：

- `material_counter_node`
  - 订阅 `sensor_msgs/msg/Image`
  - 调用 YOLO 模型识别物资
  - 在 `std_msgs/msg/String` 中发布 JSON 结果
- `face_recognize_node`
  - 订阅 `sensor_msgs/msg/Image`
  - 使用 `server/assets/known_face/` 中的已知人脸做人脸识别
  - 在 `std_msgs/msg/String` 中发布 JSON 结果
- `tcp_bridge_node`
  - 监听 TCP 端口
  - 接收客户端发来的 `face_image`、`material_image`、`inventory_record`
  - 将图片请求转给上面两个识别节点
  - 将 inventory 记录追加写入 CSV
- `inventory_web_node`
  - 读取 `inventory_records.csv`
  - 汇总当前库存、最后出入库人员与时间
  - 通过本机 HTTP 页面实时展示，并支持查看单个物资详情

辅助测试节点：

- `single_image_client`
  - 本地发一张物资图到 `/material_counter/image`
  - 用于单独验证物资识别
- `face_recognize_client`
  - 本地发一张人脸图到 `/face_recognize/image`
  - 用于单独验证人脸识别

## 2. 目录与依赖

关键路径：

- 部署默认权重：`weights/materials_yolo/last.pt`
- 训练评估权重：`weights/materials_yolo/best.pt`
- 已知人脸库：`server/assets/known_face/`
- 物资识别节点：`server/server/material_counter_node.py`
- 人脸识别节点：`server/server/face_recognize_node.py`
- TCP 节点：`server/server/tcp_bridge_node.py`
- Web 看板节点：`server/server/inventory_web_node.py`
- 一键启动：`server/launch/tcp_bridge.launch.py`
- 只启动看板：`server/launch/inventory_web.launch.py`

依赖环境：

- ROS 2 Humble
- `alg` conda 环境
- `ultralytics`
- `face_recognition`
- `opencv-python`

## 3. 构建

在工作区根目录执行：

```bash
conda activate alg
source /opt/ros/humble/setup.bash
colcon build --packages-select server
source install/setup.bash
```

如果只在单机或单服务器内部运行 ROS 节点，推荐再加：

```bash
export ROS_LOCALHOST_ONLY=1
```

说明：

- 即使 `ROS_LOCALHOST_ONLY=1`，`tcp_bridge_node` 仍然可以对外监听 TCP 端口。
- 因为 `client` 和 `server` 之间走的是 TCP，不走跨机器 ROS。

## 4. 快速启动

### 4.1 默认一键启动

直接启动四个核心节点：

```bash
ros2 launch server tcp_bridge.launch.py
```

这个 launch 使用的是默认参数：

- 物资识别模型：自动优先寻找 `weights/materials_yolo/last.pt`，找不到时回退到 `best.pt`
- 人脸库：自动寻找 `server/assets/known_face/`
- TCP 监听地址：`0.0.0.0`
- TCP 监听端口：`9000`
- inventory CSV：自动保存到 `server/assets/inventory_records.csv`
- Web 看板监听地址：`127.0.0.1`
- Web 看板端口：`8600`

启动后可直接在本机打开：

```text
http://127.0.0.1:8600
```

### 4.2 在 launch 中直接指定端口

例如把 TCP 端口改成 `9100`：

```bash
ros2 launch server tcp_bridge.launch.py port:=9100
```

也可以同时指定监听地址和 CSV 路径：

```bash
ros2 launch server tcp_bridge.launch.py \
  host:=0.0.0.0 \
  port:=9100 \
  inventory_csv_path:=/data/inventory_records.csv
```

如果只想看 CSV 看板，不启动识别和 TCP：

```bash
ros2 launch server inventory_web.launch.py
```

也可以自定义本地看板端口：

```bash
ros2 launch server inventory_web.launch.py port:=8700
```

### 4.3 分开启动

如果你想分别看日志，或者想单独重启某一个节点，可以分别开三个终端：

终端 1：

```bash
conda activate alg
source /opt/ros/humble/setup.bash
source /home/cells/embedded/install/setup.bash
export ROS_LOCALHOST_ONLY=1
ros2 run server material_counter_node
```

终端 2：

```bash
conda activate alg
source /opt/ros/humble/setup.bash
source /home/cells/embedded/install/setup.bash
export ROS_LOCALHOST_ONLY=1
ros2 run server face_recognize_node
```

终端 3：

```bash
conda activate alg
source /opt/ros/humble/setup.bash
source /home/cells/embedded/install/setup.bash
export ROS_LOCALHOST_ONLY=1
ros2 run server tcp_bridge_node
```

终端 4：

```bash
conda activate alg
source /opt/ros/humble/setup.bash
source /home/cells/embedded/install/setup.bash
export ROS_LOCALHOST_ONLY=1
ros2 run server inventory_web_node
```

## 5. 如何指定 TCP 通信地址和端口

推荐优先用 launch 方式传参数；如果你只想单独启动 `tcp_bridge_node`，也可以继续用 `ros2 run`。

### 5.1 指定监听地址和端口

例如把 server 改为监听 `0.0.0.0:9100`：

launch 方式：

```bash
ros2 launch server tcp_bridge.launch.py \
  host:=0.0.0.0 \
  port:=9100
```

或 `ros2 run` 方式：

```bash
ros2 run server tcp_bridge_node --ros-args \
  -p host:=0.0.0.0 \
  -p port:=9100
```

如果只想绑定某一块网卡的 IP，也可以：

launch 方式：

```bash
ros2 launch server tcp_bridge.launch.py \
  host:=192.168.1.20 \
  port:=9100
```

或 `ros2 run` 方式：

```bash
ros2 run server tcp_bridge_node --ros-args \
  -p host:=192.168.1.20 \
  -p port:=9100
```

### 5.2 指定 inventory CSV 路径

launch 方式：

```bash
ros2 launch server tcp_bridge.launch.py \
  inventory_csv_path:=/data/inventory_records.csv
```

或 `ros2 run` 方式：

```bash
ros2 run server tcp_bridge_node --ros-args \
  -p inventory_csv_path:=/data/inventory_records.csv
```

### 5.3 同时指定端口和 CSV 路径

launch 方式：

```bash
ros2 launch server tcp_bridge.launch.py \
  host:=0.0.0.0 \
  port:=9100 \
  inventory_csv_path:=/data/inventory_records.csv
```

或 `ros2 run` 方式：

```bash
ros2 run server tcp_bridge_node --ros-args \
  -p host:=0.0.0.0 \
  -p port:=9100 \
  -p inventory_csv_path:=/data/inventory_records.csv
```

### 5.4 检查端口是否真的监听成功

```bash
ss -ltnp | grep 9100
```

如果没有输出，通常说明：

- 节点没有成功启动
- 端口被别的程序占用
- 绑定地址写错了

如果你想检查 Web 看板是否真的监听成功，可以把 `9100` 换成 `8600`：

```bash
ss -ltnp | grep 8600
```

## 6. 常用节点参数

### 6.1 `material_counter_node`

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `model_path` | 自动查找 `weights/materials_yolo/best.pt` | YOLO 权重路径 |
| `device` | `""` | 推理设备；例如 `0` 表示 GPU 0，空字符串表示自动/默认 |
| `conf_threshold` | `0.25` | 检测阈值 |
| `image_topic` | `/material_counter/image` | 输入图像 topic |
| `counts_topic` | `/material_counter/counts` | 输出计数 JSON topic |
| `annotated_image_topic` | `/material_counter/annotated_image` | 标注图输出 topic |
| `publish_annotated_image` | `False` | 是否发布标注图 |

示例：

```bash
ros2 run server material_counter_node --ros-args \
  -p device:=0 \
  -p conf_threshold:=0.3 \
  -p publish_annotated_image:=true
```

### 6.4 `inventory_web_node`

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `host` | `127.0.0.1` | Web 看板监听地址，默认仅本机访问 |
| `port` | `8600` | Web 看板端口 |
| `inventory_csv_path` | `auto` | 记录 CSV 路径 |
| `refresh_interval_sec` | `1.0` | 轮询 CSV 的刷新周期 |
| `board_title` | `嵌入式物资实时看板` | 页面标题 |

示例：

```bash
ros2 run server inventory_web_node --ros-args \
  -p host:=127.0.0.1 \
  -p port:=8700 \
  -p inventory_csv_path:=/data/inventory_records.csv
```

## 7. 示例 CSV

仓库里已经放了一份可直接演示的示例数据：

```text
server/assets/inventory_records.csv
```

特点：

- 人员更多，便于看最后操作人变化
- 物资种类更多，便于看汇总效果
- 字段格式与 `tcp_bridge_node` 当前实际写入的 CSV 一致

### 6.2 `face_recognize_node`

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `known_face_dir` | 自动查找 `server/assets/known_face` | 已知人脸目录 |
| `tolerance` | `0.45` | 人脸匹配阈值 |
| `detection_model` | `hog` | `hog` 或 `cnn` |
| `unknown_label` | `unknown` | 未识别命中的标签 |
| `image_topic` | `/face_recognize/image` | 输入图像 topic |
| `result_topic` | `/face_recognize/result` | 识别结果 JSON topic |
| `annotated_image_topic` | `/face_recognize/annotated_image` | 标注图 topic |
| `publish_annotated_image` | `False` | 是否发布标注图 |

示例：

```bash
ros2 run server face_recognize_node --ros-args \
  -p tolerance:=0.4 \
  -p detection_model:=hog
```

### 6.3 `tcp_bridge_node`

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `host` | `0.0.0.0` | TCP 监听地址 |
| `port` | `9000` | TCP 监听端口 |
| `request_timeout_sec` | `15.0` | 等待识别结果超时 |
| `material_image_topic` | `/material_counter/image` | 转发物资图的 topic |
| `material_result_topic` | `/material_counter/counts` | 读取物资结果的 topic |
| `face_image_topic` | `/face_recognize/image` | 转发人脸图的 topic |
| `face_result_topic` | `/face_recognize/result` | 读取人脸结果的 topic |
| `inventory_csv_path` | `auto` | 默认自动解析到 `server/assets/inventory_records.csv`；也可手动指定绝对路径 |

## 7. ROS 内部接口

默认 topic：

- `/material_counter/image`
- `/material_counter/counts`
- `/material_counter/annotated_image`
- `/face_recognize/image`
- `/face_recognize/result`
- `/face_recognize/annotated_image`

结果消息类型都是 `std_msgs/msg/String`，内容为 JSON。

### 7.1 物资识别结果示例

```json
{
  "frame_id": "camera",
  "stamp_sec": 1777119153,
  "stamp_nanosec": 0,
  "counts": {
    "cboard": 2,
    "m3508": 1
  },
  "total_detections": 3
}
```

### 7.2 人脸识别结果示例

```json
{
  "frame_id": "camera",
  "stamp_sec": 1777123000,
  "stamp_nanosec": 0,
  "results": [
    {
      "name": "huanghexiang",
      "distance": 0.37,
      "box": {
        "top": 120,
        "right": 280,
        "bottom": 280,
        "left": 110
      }
    }
  ],
  "counts": {
    "huanghexiang": 1
  },
  "total_faces": 1
}
```

## 8. TCP 协议

`tcp_bridge_node` 使用长度前缀协议：

- 一条 TCP 连接可以连续发送多条请求
- 每条消息格式为：`4 字节大端长度 + UTF-8 JSON`

支持的 `type`：

- `material_image`
- `face_image`
- `inventory_record`

### 8.1 图片请求

```json
{
  "type": "material_image",
  "request_id": "req-001",
  "payload": {
    "image_base64": "<base64>",
    "image_format": "jpg"
  }
}
```

`face_image` 的 `payload` 完全相同，只是 `type` 不同。

### 8.2 inventory 请求

```json
{
  "type": "inventory_record",
  "request_id": "req-002",
  "payload": {
    "time": "2026-04-25T21:30:00+08:00",
    "person": "huanghexiang",
    "action": "出库",
    "items": [
      {"name": "cboard", "quantity": 2},
      {"name": "m3508", "quantity": 1}
    ]
  }
}
```

注意：

- `action` 只接受 `入库`、`出库`、`in`、`out`
- `items` 必须是非空数组
- 每个 item 至少要有 `name` 和 `quantity`

### 8.3 成功响应

```json
{
  "ok": true,
  "type": "material_image_result",
  "request_id": "req-001",
  "data": {
    "frame_id": "req-001",
    "stamp_sec": 1777119153,
    "stamp_nanosec": 0,
    "counts": {
      "cboard": 2
    },
    "total_detections": 2
  }
}
```

### 8.4 失败响应

```json
{
  "ok": false,
  "type": "error",
  "request_id": "req-001",
  "error": {
    "code": "TIMEOUT",
    "message": "Timed out waiting for material_image_result"
  }
}
```

常见错误码：

- `INVALID_JSON`
- `INVALID_REQUEST`
- `INVALID_PAYLOAD`
- `INVALID_IMAGE`
- `INVALID_IMAGE_FORMAT`
- `INVALID_INVENTORY`
- `UNKNOWN_TYPE`
- `DUPLICATE_REQUEST_ID`
- `TIMEOUT`

## 9. CSV 输出

默认 CSV 路径：

```text
server/assets/inventory_records.csv
```

列结构：

- `request_id`
- `record_time`
- `person`
- `action`
- `material_name`
- `quantity`
- `received_at`

写入规则：

- 一条物资一行
- 一个 inventory 请求里如果有多个物资，会展开成多行
- 如果 CSV 不存在，会自动创建并写表头

## 10. 单独测试识别节点

### 10.1 测试物资识别

先启动：

```bash
ros2 run server material_counter_node
```

再发一张图：

```bash
ros2 run server single_image_client --ros-args \
  -p image_path:=/absolute/path/to/image.jpg
```

### 10.2 测试人脸识别

先启动：

```bash
ros2 run server face_recognize_node
```

再发一张图：

```bash
ros2 run server face_recognize_client --ros-args \
  -p image_path:=/absolute/path/to/face.jpg
```

## 11. 两机联调示例

假设：

- server 电脑 IP：`192.168.1.20`
- server 监听端口：`9100`
- client 电脑稍后会连到 `192.168.1.20:9100`

### 11.1 在 server 电脑上启动

终端 1：

```bash
conda activate alg
source /opt/ros/humble/setup.bash
source /home/cells/embedded/install/setup.bash
export ROS_LOCALHOST_ONLY=1
ros2 run server material_counter_node
```

终端 2：

```bash
conda activate alg
source /opt/ros/humble/setup.bash
source /home/cells/embedded/install/setup.bash
export ROS_LOCALHOST_ONLY=1
ros2 run server face_recognize_node
```

终端 3：

```bash
conda activate alg
source /opt/ros/humble/setup.bash
source /home/cells/embedded/install/setup.bash
export ROS_LOCALHOST_ONLY=1
ros2 run server tcp_bridge_node --ros-args \
  -p host:=0.0.0.0 \
  -p port:=9100 \
  -p inventory_csv_path:=/data/inventory_records.csv
```

### 11.2 在 client 电脑上连接

见 [client/README.md](/home/cells/embedded/client/README.md) 中的 `server_host` / `server_port` 配置方法。

## 12. 最小 Python TCP 示例

```python
import json
import socket
import struct

body = {
    "type": "inventory_record",
    "request_id": "demo-001",
    "payload": {
        "time": "2026-04-25T21:30:00+08:00",
        "person": "huanghexiang",
        "action": "入库",
        "items": [
            {"name": "cboard", "quantity": 2},
        ],
    },
}

encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")

with socket.create_connection(("127.0.0.1", 9000)) as sock:
    sock.sendall(struct.pack("!I", len(encoded)) + encoded)
    header = sock.recv(4)
    length = struct.unpack("!I", header)[0]
    response = sock.recv(length)
    print(json.loads(response.decode("utf-8")))
```

## 13. 常见问题

### 13.1 client 连不上 server

先检查：

- `tcp_bridge_node` 是否真的启动
- `host` 和 `port` 是否与 client 配置一致
- server 机器防火墙是否放通该端口

常用检查命令：

```bash
ss -ltnp | grep 9000
```

### 13.2 人脸识别总是 `unknown`

检查：

- `server/assets/known_face/` 里是否放了正确的人脸底库
- 底库图片是否能正确提取到人脸
- 识别图角度、光照、清晰度是否足够
- 是否需要调小 `tolerance`

### 13.3 物资识别结果不理想

可以尝试：

- 调整 `conf_threshold`
- 更换拍摄角度
- 检查模型路径是否真的是当前想用的权重
- 重新采集/训练数据
