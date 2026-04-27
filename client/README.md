# client

`client` 是一个 ROS 2 Python 包，负责本地交互和流程控制：

- 调用摄像头采集画面
- 通过 TCP 连接远端 `server`
- 完成“开始操作 -> 人脸识别 -> 物资前后识别 -> 差异计算 -> 上传记录”的完整流程
- 提供 PyQt5 图形界面

`client` 适合部署在“操作端电脑”上运行。

## 1. 功能概览

包内主要节点：

- `camera_node`
  - 打开本地摄像头
  - 发布实时预览
  - 提供抓拍服务
- `tcp_client_node`
  - 维护到 `server` 的长连接 TCP socket
  - 对上层暴露统一 ROS service
- `logic_node`
  - 负责完整状态机
  - 串起人脸识别、稳像、物资前后对比、inventory 上传
- `ui_node`
  - PyQt5 图形界面
  - 显示预览和状态
  - 提供 `开始操作`、`完成` 两个按钮

## 2. 工作流程

当前统一流程如下：

1. 点击 `开始操作`
2. `logic_node` 每秒抓拍一次人脸图，发给 `server`
3. 当 `server` 返回“恰好 1 张脸，且不是 `unknown`”时，记录人员姓名
4. 等待 `settle_delay_sec`（默认 3.5 秒），给操作者留出移动摄像头到物资区域的时间
5. 进入稳像阶段，等待预览画面稳定
6. 抓拍操作前物资图，发给 `server` 做物资识别
7. UI 进入 `等待点击完成`
8. 用户完成实际操作后点击 `完成`
9. 抓拍操作后物资图，发给 `server`
10. 计算前后差异：
    - 增加项拆成一条 `action=入库`
    - 减少项拆成一条 `action=出库`
11. 将记录通过 TCP 上传给 `server`
12. UI 回到待机

## 3. 依赖与构建

依赖：

- ROS 2 Humble
- `alg` conda 环境
- `PyQt5`
- `opencv-python`
- 树莓派环境下可执行的 `rpicam-still`

构建命令：

```bash
conda activate alg
source /opt/ros/humble/setup.bash
colcon build --packages-select client
source install/setup.bash
```

如果你在当前 `alg` 环境里构建时看到：

```text
ModuleNotFoundError: No module named 'em'
```

先补一个 `PYTHONPATH` 再构建：

```bash
export PYTHONPATH=/usr/lib/python3/dist-packages:$PYTHONPATH
colcon build --packages-select client
```

如果 `client` 与 `server` 一起构建：

```bash
conda activate alg
source /opt/ros/humble/setup.bash
export PYTHONPATH=/usr/lib/python3/dist-packages:$PYTHONPATH
colcon build --packages-select server client
source install/setup.bash
```

如果所有 ROS 节点都只在本机内部互相通信，也可以加：

```bash
export ROS_LOCALHOST_ONLY=1
```

这不会影响 `client` 通过 TCP 连接远端 `server`。

## 4. 启动前准备

在启动 `client` 前，请先确认远端 `server` 已经启动至少这三个节点：

- `material_counter_node`
- `face_recognize_node`
- `tcp_bridge_node`

最关键的是：

- `tcp_bridge_node` 的监听 IP/端口要记清楚
- `client` 里的 `server_host` / `server_port` 必须和它一致

例如：

- server IP：`192.168.1.20`
- server port：`9100`

那么 client 就必须连：

- `server_host:=192.168.1.20`
- `server_port:=9100`

## 5. 快速启动

### 5.1 默认启动

如果 `server` 在本机默认端口 `127.0.0.1:9000`，直接：

```bash
ros2 launch client client.launch.py
```

### 5.2 指定远端 server 地址和端口

例如 server 在 `192.168.1.20:9100`：

```bash
ros2 launch client client.launch.py \
  server_host:=192.168.1.20 \
  server_port:=9100
```

### 5.3 指定摄像头设备号

默认摄像头是 `0`，如果你要用另一个摄像头：

```bash
ros2 launch client client.launch.py \
  camera_index:=1
```

### 5.4 同时指定 server 地址、端口、摄像头

```bash
ros2 launch client client.launch.py \
  server_host:=192.168.1.20 \
  server_port:=9100 \
  camera_backend:=rpicam
```

## 6. launch 参数

`client.launch.py` 当前支持这些参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `camera_index` | `0` | 摄像头设备号 |
| `camera_backend` | `auto` | 相机后端，`auto` 会优先使用 `rpicam-still`，否则回退到 OpenCV |
| `width` | `1280` | 采集宽度 |
| `height` | `720` | 采集高度 |
| `fps` | `15` | 预览帧率 |
| `rpicam_executable` | `rpicam-still` | `rpicam` 抓图命令 |
| `rpicam_timeout_ms` | `1` | 单次 `rpicam` 抓图等待时间（毫秒） |
| `server_host` | `127.0.0.1` | server TCP 地址 |
| `server_port` | `9000` | server TCP 端口 |
| `connect_timeout_sec` | `3.0` | 建立 TCP 连接超时 |
| `request_timeout_sec` | `15.0` | 单次 TCP 请求超时 |
| `jpeg_quality` | `90` | 发图时 JPEG 压缩质量 |
| `face_retry_interval_sec` | `1.0` | 人脸识别重试周期 |
| `face_timeout_sec` | `60.0` | 人脸识别总超时 |
| `settle_delay_sec` | `3.5` | 人脸识别后等待移动摄像头的时间 |
| `stable_hold_sec` | `1.0` | 需要持续稳定多长时间才算稳像成功 |
| `stability_threshold` | `3.0` | 预览帧灰度均值变化阈值 |
| `stable_timeout_sec` | `8.0` | 稳像阶段最长等待时间 |

说明：

- `camera_index` 只在 `camera_backend:=opencv` 时生效
- `camera_backend:=auto` 时，如果系统能找到 `rpicam-still`，会默认优先使用它

常见示例：

```bash
ros2 launch client client.launch.py \
  server_host:=192.168.1.20 \
  server_port:=9100 \
  camera_backend:=rpicam \
  settle_delay_sec:=4.0 \
  stable_timeout_sec:=10.0
```

## 7. 单独启动各节点

如果你要分开调试，每个节点都可以单独跑。

### 7.1 `camera_node`

```bash
ros2 run client camera_node --ros-args \
  -p camera_backend:=rpicam \
  -p width:=1280 \
  -p height:=720 \
  -p fps:=15 \
  -p rpicam_timeout_ms:=1
```

### 7.2 `tcp_client_node`

```bash
ros2 run client tcp_client_node --ros-args \
  -p server_host:=192.168.1.20 \
  -p server_port:=9100 \
  -p connect_timeout_sec:=3.0 \
  -p request_timeout_sec:=15.0
```

### 7.3 `logic_node`

```bash
ros2 run client logic_node --ros-args \
  -p face_timeout_sec:=60.0 \
  -p settle_delay_sec:=3.5 \
  -p stable_timeout_sec:=8.0
```

### 7.4 `ui_node`

```bash
ros2 run client ui_node
```

如果当前环境没有显示器、只想做无头调试：

```bash
export QT_QPA_PLATFORM=offscreen
ros2 run client ui_node
```

## 8. 内部 ROS 接口

### 8.1 Topics

| 名称 | 类型 | 说明 |
|---|---|---|
| `/client/camera/preview` | `sensor_msgs/msg/Image` | 摄像头实时预览 |
| `/client/logic/status` | `std_msgs/msg/String` | 当前流程状态 JSON |

### 8.2 Services

| 名称 | 类型 | 说明 |
|---|---|---|
| `/client/camera/capture_image` | `client/srv/CaptureImage` | 抓拍当前帧 |
| `/client/tcp/send_server_request` | `client/srv/SendServerRequest` | 发 TCP 请求到 server |
| `/client/logic/start_operation` | `std_srvs/srv/Trigger` | 开始流程 |
| `/client/logic/finish_operation` | `std_srvs/srv/Trigger` | 完成流程 |

### 8.3 `CaptureImage.srv`

请求：

```text
string reason
```

响应：

```text
bool ok
string message
sensor_msgs/Image image
```

### 8.4 `SendServerRequest.srv`

请求：

```text
string request_type
sensor_msgs/Image image
string payload_json
```

响应：

```text
bool ok
string code
string message
string response_json
```

### 8.5 `status` JSON 字段

`/client/logic/status` 当前包含这些字段：

- `state`
- `message`
- `person`
- `pre_counts`
- `post_counts`
- `added_items`
- `removed_items`

可能出现的 `state`：

- `idle`
- `recognizing_face`
- `waiting_camera_move`
- `waiting_camera_stable`
- `capturing_pre_material`
- `waiting_finish`
- `capturing_post_material`
- `computing_diff`
- `submitting_inventory`
- `success`
- `error`

## 9. 使用方法

### 9.1 图形界面使用

启动后，界面上有两个按钮：

- `开始操作`
- `完成`

使用步骤：

1. 确认 `server` 已经启动
2. 确认客户端摄像头画面正常显示
3. 点击 `开始操作`
4. 把人脸对准摄像头，等待识别成功
5. 根据提示将摄像头移到物资区域
6. 等待系统自动完成稳像和“操作前物资”抓拍
7. 实际进行物资操作
8. 点击 `完成`
9. 等待系统抓拍“操作后物资”、计算差异并上传记录

### 9.2 不开 UI，纯命令行触发

先启动：

- `camera_node`
- `tcp_client_node`
- `logic_node`

然后手动调用服务。

开始流程：

```bash
ros2 service call /client/logic/start_operation std_srvs/srv/Trigger "{}"
```

查看状态：

```bash
ros2 topic echo /client/logic/status
```

完成流程：

```bash
ros2 service call /client/logic/finish_operation std_srvs/srv/Trigger "{}"
```

## 10. 两机联调示例

假设：

- server 电脑 IP：`192.168.1.20`
- server TCP 端口：`9100`
- client 电脑上接着 USB 摄像头

### 10.1 server 电脑

参照 [server/README.md](/home/cells/embedded/server/README.md) 启动：

```bash
ros2 run server tcp_bridge_node --ros-args \
  -p host:=0.0.0.0 \
  -p port:=9100
```

### 10.2 client 电脑

```bash
conda activate alg
source /opt/ros/humble/setup.bash
source /home/cells/embedded/install/setup.bash
export ROS_LOCALHOST_ONLY=1
ros2 launch client client.launch.py \
  server_host:=192.168.1.20 \
  server_port:=9100 \
  camera_index:=0
```

## 11. 常见排查

### 11.1 指定了端口但连不上

先检查两边配置是否一致：

- server：
  - `host`
  - `port`
- client：
  - `server_host`
  - `server_port`

例如 server 监听：

```bash
ros2 run server tcp_bridge_node --ros-args -p host:=0.0.0.0 -p port:=9100
```

那么 client 必须连：

```bash
ros2 launch client client.launch.py server_host:=<server_ip> server_port:=9100
```

### 11.2 client 显示 `TCP_ERROR`

通常检查：

- server 端 `tcp_bridge_node` 是否已启动
- server 端端口是否被防火墙拦截
- `server_host` 是否写成了错误 IP
- `server_port` 是否和 server 端一致

### 11.3 人脸阶段一直过不去

看 `/client/logic/status`：

```bash
ros2 topic echo /client/logic/status
```

如果一直卡在 `recognizing_face`，通常是：

- 人脸没有进入画面
- 画面里不止一张脸
- 识别结果是 `unknown`
- server 的已知人脸库不对

### 11.4 稳像阶段过不去

如果一直停在 `waiting_camera_stable`，可以尝试：

- 降低手抖和相机晃动
- 稍微延长 `settle_delay_sec`
- 适当放宽 `stability_threshold`
- 适当增大 `stable_timeout_sec`

例如：

```bash
ros2 launch client client.launch.py \
  settle_delay_sec:=4.0 \
  stability_threshold:=4.0 \
  stable_timeout_sec:=12.0
```

### 11.5 摄像头打不开

先试：

```bash
ros2 run client camera_node --ros-args -p camera_backend:=rpicam
```

如果失败：

- 先直接测试 `rpicam-still -n -t 1 -o test.jpg`
- 如果你接的是 USB 摄像头，再改成 `camera_backend:=opencv` 后测试 `camera_index:=0` / `1`
- 确认没有被别的程序占用

### 11.6 UI 无法显示

如果是远程终端或无桌面环境，可以先做无头测试：

```bash
export QT_QPA_PLATFORM=offscreen
ros2 run client ui_node
```

或者先不启 `ui_node`，只跑：

- `camera_node`
- `tcp_client_node`
- `logic_node`

然后通过 service 和 topic 调试。
