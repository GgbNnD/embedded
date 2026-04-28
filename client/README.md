# client

`client` 现在是一个独立的 Python 客户端，不再依赖 ROS2 构建，也不需要 `colcon`、`ament`、`rclpy` 才能安装运行。

它负责：

- 调用本地摄像头采集画面
- 通过 TCP 连接远端 `server`
- 完成“开始操作 -> 人脸识别 -> 物资前后识别 -> 差异计算 -> 上传记录”的完整流程
- 提供 `tkinter` 图形界面

`server` 端如果仍然保留 ROS2 没问题，`client` 和 `server` 之间只通过 TCP 协议通信。

## 1. 目录结构

```text
client/
├── client/
│   ├── camera_backend.py   # 相机后端选择与 rpicam 命令拼装
│   ├── camera_node.py      # 本地相机采集组件
│   ├── config.py           # 命令行参数与运行配置
│   ├── image_utils.py      # 图像编码与灰度统计
│   ├── logic_node.py       # 业务流程状态机
│   ├── logic_utils.py      # 纯业务逻辑辅助函数
│   ├── tcp_client_node.py  # TCP 客户端
│   ├── tcp_protocol.py     # 长度前缀 JSON 协议
│   └── ui_node.py          # tkinter 图形界面与程序入口
├── scripts/
│   └── run_client          # 仓库内直接启动入口
├── test/                   # 单元测试
├── pyproject.toml          # 标准 Python 包配置
└── README.md
```

虽然文件名里还保留了 `*_node`，但这里只是为了延续原来的分层命名，不再表示 ROS2 节点。

## 2. 依赖

- Python 3.10+
- `numpy`
- `opencv-python`
- 树莓派环境下可执行的 `rpicam-still`
- 带 `tkinter` 支持的 Python

如果你用的是 conda Python，缺少 `tkinter` 时可以先装：

```bash
conda install tk
```

如果你使用仓库里已有的 conda 环境：

```bash
conda activate alg
```

## 3. 安装

在 `client/` 目录下执行：

```bash
cd /home/cells/embedded/client
pip install -e .
```

如果只想在仓库里直接跑，也可以不安装，直接：

```bash
cd /home/cells/embedded/client
python scripts/run_client
```

## 4. 快速启动

默认启动：

```bash
embedded-client
```

指定远端 server：

```bash
embedded-client \
  --server-host 192.168.1.20 \
  --server-port 9100
```

树莓派相机启动方式：

```bash
embedded-client \
  --camera-backend rpicam \
  --fps 5 \
  --server-host 192.168.1.20 \
  --server-port 9100
```

如果你不想安装 console script，也可以直接：

```bash
python scripts/run_client \
  --camera-backend rpicam \
  --server-host 192.168.1.20 \
  --server-port 9100
```

## 5. 常用参数

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `--camera-backend` | `auto` | `auto` 优先找 `rpicam-still`，找不到再回退到 OpenCV |
| `--camera-index` | `0` | OpenCV 摄像头设备号，仅 `opencv` 后端生效 |
| `--width` | `1280` | 采集宽度 |
| `--height` | `720` | 采集高度 |
| `--fps` | `5` | Capture and preview FPS |
| `--rpicam-executable` | `rpicam-still` | `rpicam` 命令名或绝对路径 |
| `--rpicam-timeout-ms` | `1` | 单次 `rpicam` 抓图等待时间 |
| `--server-host` | `127.0.0.1` | server TCP 地址 |
| `--server-port` | `9000` | server TCP 端口 |
| `--connect-timeout-sec` | `3.0` | 建立 TCP 连接超时 |
| `--request-timeout-sec` | `15.0` | 单次 TCP 请求超时 |
| `--jpeg-quality` | `90` | 发图时 JPEG 压缩质量 |
| `--face-retry-interval-sec` | `1.0` | 人脸识别重试周期 |
| `--face-timeout-sec` | `60.0` | 人脸识别总超时 |
| `--settle-delay-sec` | `3.5` | Reserved compatibility option from the previous auto-capture flow |
| `--stable-hold-sec` | `1.0` | Reserved compatibility option from the previous auto-capture flow |
| `--stability-threshold` | `3.0` | Reserved compatibility option from the previous auto-capture flow |
| `--stable-timeout-sec` | `8.0` | Reserved compatibility option from the previous auto-capture flow |

例如，如果你想把预览和采集目标帧率改成 8 FPS：

```bash
embedded-client --fps 8
```

## 6. 调试命令

检查相机是否能抓到图：

```bash
embedded-client-camera \
  --camera-backend rpicam \
  --output test.jpg
```

只检查 TCP 服务端是否能连通：

```bash
embedded-client-server \
  --server-host 192.168.1.20 \
  --server-port 9100
```

如果没安装 console script，也可以直接：

```bash
python -m client.camera_node --camera-backend rpicam --output test.jpg
python -m client.tcp_client_node --server-host 192.168.1.20 --server-port 9100
```

## 7. 工作流程

当前统一流程如下：

1. 点击 `开始操作`
2. 客户端定时抓拍人脸图并发给 `server`
3. 当 `server` 返回“恰好 1 张脸，且不是 `unknown`”时，记录人员姓名
4. 将摄像头移动到物资区域
5. 点击 `Capture Materials`
6. 抓拍操作前物资图并发给 `server`
7. UI 进入 `等待点击完成`
8. 用户完成实际操作后点击 `完成`
9. 抓拍操作后物资图并发给 `server`
10. 计算前后差异并上传 inventory 记录

## 8. 常见问题

### 8.1 树莓派相机打不开

先直接在终端测试：

```bash
rpicam-still -n -t 1 -o test.jpg
```

如果这里都失败，先解决系统层的相机权限或驱动问题。

### 8.2 USB 摄像头能用，树莓派相机不能用

强制改用树莓派后端：

```bash
embedded-client --camera-backend rpicam
```

如果你接的是 USB 摄像头，则改成：

```bash
embedded-client --camera-backend opencv --camera-index 0
```

### 8.3 一直停在识别人脸

通常是：

- 人脸没有进入画面
- 画面里不止一张脸
- 识别结果是 `unknown`
- `server` 端的人脸库不对

### 8.4 操作前物资没有被正确抓拍

现在操作前物资抓拍改成了手动触发：

- 先等人脸识别成功
- 把摄像头移到物资区域
- 点击 `Capture Materials`
- 如果取景不对，就调整镜头后再点

## 9. 树莓派开机自启

如果你的 `client` 运行的是当前这个 `tkinter` 图形界面，推荐使用“桌面自动启动”而不是普通后台 `systemd` 服务。

原因：

- `embedded-client` 需要图形桌面环境
- 如果机器还没进入桌面会话，直接后台启动通常会因为没有 `DISPLAY` 而失败

### 9.1 先确认手动运行没问题

在树莓派上先确认下面命令能正常打开客户端：

```bash
cd /home/cells/embedded/client
python3 scripts/run_client \
  --camera-backend rpicam \
  --server-host 192.168.1.20 \
  --server-port 9000
```

### 9.2 给仓库里的启动脚本加执行权限

仓库里已经提供了一个自动启动脚本：

```text
client/scripts/start_client_autostart.sh
```

执行：

```bash
chmod +x /home/cells/embedded/client/scripts/start_client_autostart.sh
```

这个脚本会启动：

```bash
python3 scripts/run_client \
  --camera-backend rpicam \
  --server-host 192.168.1.20 \
  --server-port 9000
```

并把日志写到：

```text
/home/cells/embedded/client/client_autostart.log
```

### 9.3 创建桌面自动启动项

在树莓派上执行：

```bash
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/embedded-client.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Embedded Client
Exec=/home/cells/embedded/client/scripts/start_client_autostart.sh
Path=/home/cells/embedded/client
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
```

### 9.4 打开树莓派自动登录桌面

如果你希望“上电后不手动登录也自动弹出 client 界面”，还需要让 Raspberry Pi OS 自动登录到图形桌面。

可以执行：

```bash
sudo raspi-config
```

然后进入：

```text
System Options -> Boot / Auto Login -> Desktop Autologin
```

### 9.5 重启验证

执行：

```bash
sudo reboot
```

重启后检查：

- 是否自动进入桌面
- 是否自动弹出 client 窗口
- 如果没起来，查看日志 `client/client_autostart.log`

### 9.6 如果你改了 server 地址或端口

直接编辑这个脚本即可：

- [start_client_autostart.sh](/home/cells/embedded/client/scripts/start_client_autostart.sh)

### 8.5 无显示器环境

如果是远程终端或无桌面环境，可以先做无头验证：

```bash
embedded-client-camera --camera-backend rpicam --output test.jpg
embedded-client-server --server-host 192.168.1.20 --server-port 9100
```

也就是先分别确认“本地能拍图”和“远端能连通”，再回到图形界面联调。
