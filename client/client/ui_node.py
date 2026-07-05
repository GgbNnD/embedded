"""
客户端主界面模块 (RK3399Pro 版 - tkinter)
==========================================
从原有的 client/ui_node.py 重构而来。

核心变更:
  1. 初始化新模块: CameraNode(纯OpenCV), FaceRecognizer(本地dlib),
     YoloDetector(本地NPU), EncryptedTcpClient(加密TCP)
  2. 初始化网络: ServerDiscovery(UDP组播), EcdhHandler(ECDH密钥交换)
  3. 服务器地址由组播自动发现, 不再需要手动配置 --server-host

界面布局:
  ┌──────────────────────────────────────┐
  │           摄像头实时预览              │
  │          (960x540 区域)              │
  │                                      │
  ├──────────────────────────────────────┤
  │ [Start] [Capture Materials] [Finish] │
  ├──────────────────────────────────────┤
  │ 状态信息: 当前状态/操作人/物资变化...  │
  └──────────────────────────────────────┘

运行方式:
  conda activate rknn_py38
  python -m client.ui_node
"""

import base64
import logging
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext

import cv2

from client.camera_node import CameraNode
from client.config import parse_config
from client.face_recognizer import FaceRecognizer
from client.yolo_detector import YoloDetector
from client.encrypted_tcp_client import EncryptedTcpClient
from client.ecdh_handler import EcdhHandler
from client.discovery import ServerDiscovery
from client.logic_node import LogicNode
from client.logic_utils import summarize_counts, summarize_items


# 状态显示文本映射 (中文)
STATE_LABELS = {
    "idle": "空闲",
    "recognizing_face": "正在人脸识别",
    "waiting_camera_move": "等待拍照",
    "waiting_camera_stable": "等待摄像头稳定",
    "capturing_pre_material": "正在检测操作前物资",
    "waiting_finish": "等待操作完成",
    "capturing_post_material": "正在检测操作后物资",
    "computing_diff": "正在计算出入库变化",
    "submitting_inventory": "正在上传记录",
    "success": "操作成功",
    "error": "操作失败",
}


class ClientWindow:
    """客户端主窗口 (tkinter GUI)

    负责:
      - 显示摄像头实时预览
      - 提供三个操作按钮: Start / Capture Materials / Finish
      - 显示状态信息窗口 (操作人, 物资变化等)
      - 定期轮询 LogicNode 的状态快照更新 UI
    """

    def __init__(self, camera, logic, ui_fps=5.0):
        """初始化 GUI

        Args:
            camera: CameraNode 实例
            logic: LogicNode 实例
            ui_fps: UI 刷新帧率 (Hz)
        """
        self._camera = camera
        self._logic = logic

        # UI 刷新参数
        self._refresh_interval_ms = max(1, int(1000 / max(float(ui_fps), 1.0)))

        # 帧追踪 (避免渲染重复帧)
        self._last_frame_seq = -1

        # 状态缓存
        self._status_payload = self._logic.get_status_snapshot()
        self._local_notice = ""  # 本地通知 (非状态机消息)
        self._connection_status = "等待服务器..."

        # 预览图片 (tkinter PhotoImage 需要保持引用, 否则会被 GC)
        self._preview_photo = None

        # ─── 构建 tkinter 窗口 ───
        self._root = tk.Tk()
        self._root.title("RK3399Pro 出入库管理客户端")
        self._root.geometry("1100x800")
        self._root.minsize(960, 700)
        self._root.protocol("WM_DELETE_WINDOW", self._handle_close)

        self._build_ui()

        # 启动 UI 刷新循环
        self._schedule_refresh()

        # 首次更新状态和按钮
        self._update_status_text()
        self._update_buttons()

    # ─── UI 构建 ───

    def _build_ui(self):
        """构建 UI 组件"""
        # 主容器
        container = tk.Frame(self._root, padx=12, pady=12)
        container.pack(fill=tk.BOTH, expand=True)

        # ─── 连接状态栏 (顶部) ───
        conn_frame = tk.Frame(container)
        conn_frame.pack(fill=tk.X, pady=(0, 6))
        self._conn_label = tk.Label(
            conn_frame,
            text="服务器: 正在搜索...",
            fg="#888888",
            font=("TkDefaultFont", 10),
        )
        self._conn_label.pack(side=tk.LEFT)

        # ─── 摄像头预览区域 ───
        self._preview_label = tk.Label(
            container,
            text="等待摄像头预览...",
            bg="#111111",
            fg="#dddddd",
            relief=tk.SOLID,
            borderwidth=1,
            anchor=tk.CENTER,
        )
        self._preview_label.pack(fill=tk.BOTH, expand=True)
        self._preview_label.configure(width=960, height=540)

        # ─── 按钮行 ───
        button_row = tk.Frame(container, pady=10)
        button_row.pack(fill=tk.X)

        self._start_button = tk.Button(
            button_row, text="🟢 Start (开始操作)",
            command=self._handle_start_clicked,
            font=("TkDefaultFont", 11, "bold"),
        )
        self._capture_button = tk.Button(
            button_row, text="📷 Capture Materials (拍照)",
            command=self._handle_capture_clicked,
            font=("TkDefaultFont", 11, "bold"),
        )
        self._finish_button = tk.Button(
            button_row, text="✅ Finish (完成)",
            command=self._handle_finish_clicked,
            font=("TkDefaultFont", 11, "bold"),
        )

        self._start_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self._capture_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self._finish_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        # ─── 状态文本区域 ───
        self._status_view = scrolledtext.ScrolledText(
            container, wrap=tk.WORD, height=10,
            font=("TkFixedFont", 10),
        )
        self._status_view.pack(fill=tk.BOTH, expand=False)
        self._status_view.configure(state=tk.DISABLED)

    # ─── UI 刷新 ───

    def _refresh_view(self):
        """刷新 UI: 预览帧 + 状态文本 + 按钮启用/禁用"""
        self._refresh_preview()
        self._status_payload = self._logic.get_status_snapshot()
        self._update_status_text()
        self._update_buttons()
        self._schedule_refresh()

    def _schedule_refresh(self):
        """调度下一次 UI 刷新"""
        self._root.after(self._refresh_interval_ms, self._refresh_view)

    def _refresh_preview(self):
        """刷新摄像头预览帧 (从 CameraNode 获取最新帧)

        将 BGR 帧转换为 base64 PNG, 然后设置为 tk.PhotoImage。
        只在帧序号变化时更新 (避免重复渲染).
        """
        frame, frame_seq = self._camera.get_latest_frame_snapshot()
        if frame is None or frame_seq == self._last_frame_seq:
            return

        self._last_frame_seq = frame_seq

        # 缩小帧以适配预览区域
        display_frame = self._resize_for_preview(frame)

        # BGR → PNG bytes → base64 → tk.PhotoImage
        success, encoded = cv2.imencode(".png", display_frame)
        if not success:
            return

        png_base64 = base64.b64encode(encoded.tobytes()).decode("ascii")
        self._preview_photo = tk.PhotoImage(data=png_base64)
        self._preview_label.configure(image=self._preview_photo, text="")

    def _resize_for_preview(self, frame):
        """将帧缩放到预览区域大小 (保持宽高比)

        Args:
            frame: BGR 图像

        Returns:
            RGB 格式 (tkinter 需要 RGB)
        """
        label_width = max(self._preview_label.winfo_width(), 960)
        label_height = max(self._preview_label.winfo_height(), 540)
        frame_height, frame_width = frame.shape[:2]

        scale = min(label_width / frame_width, label_height / frame_height)
        scale = max(scale, 0.1)
        target_width = max(1, int(frame_width * scale))
        target_height = max(1, int(frame_height * scale))

        if target_width == frame_width and target_height == frame_height:
            # 无需缩放, BGR → RGB
            return frame[:, :, ::-1].copy()

        resized = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)
        # BGR → RGB
        return resized[:, :, ::-1].copy()

    # ─── 状态文本更新 ───

    def _update_status_text(self):
        """更新状态文本区域"""
        payload = self._status_payload
        state = str(payload.get("state", "idle"))

        lines = [
            f"状态: {STATE_LABELS.get(state, state)}",
            f"消息: {payload.get('message', '')}",
        ]

        # 连接状态
        lines.append(f"服务器: {self._connection_status}")

        # 本地通知
        if self._local_notice:
            lines.append(f"通知: {self._local_notice}")

        # 操作人
        person = str(payload.get("person", ""))
        if person:
            lines.append(f"操作人: {person}")

        # 物资统计
        pre_counts = payload.get("pre_counts", {})
        post_counts = payload.get("post_counts", {})
        added_items = payload.get("added_items", [])
        removed_items = payload.get("removed_items", [])

        lines.append("")
        lines.append(f"操作前物资: {summarize_counts(pre_counts if isinstance(pre_counts, dict) else {})}")
        lines.append(f"操作后物资: {summarize_counts(post_counts if isinstance(post_counts, dict) else {})}")
        lines.append(f"入库 (新增): {summarize_items(added_items if isinstance(added_items, list) else [])}")
        lines.append(f"出库 (移除): {summarize_items(removed_items if isinstance(removed_items, list) else [])}")

        self._status_view.configure(state=tk.NORMAL)
        self._status_view.delete("1.0", tk.END)
        self._status_view.insert("1.0", "\n".join(lines))
        self._status_view.configure(state=tk.DISABLED)

    # ─── 按钮状态更新 ───

    def _update_buttons(self):
        """根据当前状态启用/禁用按钮"""
        state = str(self._status_payload.get("state", "idle"))

        start_state = tk.DISABLED
        capture_state = tk.DISABLED
        finish_state = tk.DISABLED

        if state in {"idle", "success", "error"}:
            start_state = tk.NORMAL
        elif state == "waiting_camera_move":
            capture_state = tk.NORMAL
        elif state == "waiting_finish":
            finish_state = tk.NORMAL

        self._start_button.configure(state=start_state)
        self._capture_button.configure(state=capture_state)
        self._finish_button.configure(state=finish_state)

    # ─── 按钮事件处理 ───

    def _handle_start_clicked(self):
        """Start 按钮: 开始新的出入库操作"""
        success, message = self._logic.start_operation()
        if not success:
            self._local_notice = message
            self._update_status_text()
            messagebox.showwarning("启动失败", message)
            return

        self._local_notice = ""
        self._status_payload = self._logic.get_status_snapshot()
        self._update_status_text()
        self._update_buttons()

    def _handle_capture_clicked(self):
        """Capture Materials 按钮: 拍摄操作前物资照片"""
        success, message = self._logic.capture_material_now()
        if not success:
            self._local_notice = message
            self._update_status_text()
            messagebox.showwarning("捕获失败", message)
            return

        self._local_notice = ""
        self._status_payload = self._logic.get_status_snapshot()
        self._update_status_text()
        self._update_buttons()

    def _handle_finish_clicked(self):
        """Finish 按钮: 拍摄操作后物资照片并提交"""
        success, message = self._logic.finish_operation()
        if not success:
            self._local_notice = message
            self._update_status_text()
            messagebox.showwarning("完成失败", message)
            return

        self._local_notice = ""
        self._status_payload = self._logic.get_status_snapshot()
        self._update_status_text()
        self._update_buttons()

    # ─── 连接状态更新 (由外部线程调用) ───

    def set_connection_status(self, status):
        """设置连接状态文本 (由 discovery/ecdh 回调线程调用)

        使用 tkinter 的 after() 确保在主线程中更新 UI。

        Args:
            status: 连接状态描述字符串
        """
        self._connection_status = status
        # 在主线程中更新连接标签
        self._root.after(0, self._update_connection_label)

    def _update_connection_label(self):
        """更新连接状态标签 (在主线程中调用)"""
        if "已连接" in self._connection_status or "加密" in self._connection_status:
            color = "#00aa00"  # 绿色 = 已连接
        elif "搜索" in self._connection_status or "发现" in self._connection_status:
            color = "#cc8800"  # 橙色 = 搜索中
        else:
            color = "#cc0000"  # 红色 = 错误

        self._conn_label.configure(text=f"服务器: {self._connection_status}", fg=color)

    # ─── 关闭 ───

    def _handle_close(self):
        """窗口关闭按钮处理"""
        self._root.quit()

    def mainloop(self):
        """进入 tkinter 主事件循环"""
        self._root.mainloop()


# ═══════════════════════════════════════════════════════════════════════════════
# 程序入口
# ═══════════════════════════════════════════════════════════════════════════════

def main(argv=None):
    """RK3399Pro 客户端主入口

    启动流程:
      1. 解析命令行参数 → ClientConfig
      2. 初始化各模块: 摄像头, 人脸识别, YOLO检测, 加密TCP, 发现服务, ECDH
      3. 启动模块
      4. 进入 tkinter UI 主循环
      5. 退出时清理资源
    """
    # ─── 解析配置 ───
    config = parse_config(
        argv,
        description="RK3399Pro 出入库管理客户端 — 本地人脸+本地NPU检测+加密通信",
        include_camera=True,
        include_network=True,
        include_workflow=True,
    )

    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="[%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger("client.main")

    # ─── 解决路径 (相对于项目根目录或脚本目录) ───
    project_root = Path(__file__).resolve().parents[1]

    known_face_dir = Path(config.known_face_dir)
    if not known_face_dir.is_absolute():
        known_face_dir = project_root / known_face_dir

    rknn_model_path = Path(config.rknn_model_path)
    if not rknn_model_path.is_absolute():
        rknn_model_path = project_root / rknn_model_path

    # ─── 初始化各模块 ───

    # 1. 摄像头 (纯 OpenCV)
    log.info("初始化摄像头...")
    camera = CameraNode(
        camera_index=config.camera_index,
        width=config.width,
        height=config.height,
        fps=config.fps,
        reopen_interval_sec=config.reopen_interval_sec,
    )

    # 2. 本地人脸识别 (dlib + face_recognition)
    log.info("初始化本地人脸识别...")
    face_recognizer = FaceRecognizer(
        known_face_dir=str(known_face_dir),
        tolerance=config.face_tolerance,
        detection_model=config.face_detection_model,
    )
    # 预加载人脸编码 (避免首次调用时的阻塞)
    try:
        face_recognizer.load()
        log.info("人脸库已加载: %s", known_face_dir)
    except Exception as e:
        log.error("人脸库加载失败: %s", e)

    # 3. 本地 YOLO 物资检测 (RKNN NPU)
    log.info("初始化 RKNN NPU YOLO 检测...")
    yolo_detector = YoloDetector(
        model_path=str(rknn_model_path),
        conf_threshold=config.conf_threshold,
        iou_threshold=config.iou_threshold,
        image_size=config.yolo_image_size,
    )
    try:
        yolo_detector.load()
        log.info("RKNN YOLO 模型已加载: %s", rknn_model_path)
    except Exception as e:
        log.error("RKNN YOLO 模型加载失败 (板端需 rknn-toolkit-lite): %s", e)

    # 4. 加密 TCP 客户端
    log.info("初始化加密 TCP 客户端...")
    tcp_client = EncryptedTcpClient(
        connect_timeout_sec=config.connect_timeout_sec,
        request_timeout_sec=config.request_timeout_sec,
    )

    # 5. 工作流状态机
    log.info("初始化工作流状态机...")
    logic = LogicNode(
        camera=camera,
        face_recognizer=face_recognizer,
        yolo_detector=yolo_detector,
        tcp_client=tcp_client,
        face_retry_interval_sec=config.face_retry_interval_sec,
        face_timeout_sec=config.face_timeout_sec,
    )

    # 6. 本地标识
    import uuid
    device_id = config.device_id or uuid.uuid4().hex
    device_name = config.device_name

    # 7. UDP 组播发现服务
    log.info("初始化 UDP 组播发现服务...")
    discovery = ServerDiscovery(device_id, device_name, port=config.discovery_port)

    # 8. ECDH 密钥交换处理器
    log.info("初始化 ECDH 密钥交换...")
    ecdh = EcdhHandler(device_id, device_name, local_ip=discovery.local_ip)

    # ─── 连接回调 ───
    # 当发现服务器时:
    #   1. 设置 EncryptedTcpClient 的目标地址
    #   2. 启动 ECDH 密钥交换

    def _on_server_found(server_ip, signaling_port, data_port):
        """发现服务器后的回调 (在发现线程中调用)"""
        log.info("发现服务器: %s (信令=%s, 数据=%s)", server_ip, signaling_port, data_port)

        # 设置 TCP 客户端的目标地址 (数据通道)
        tcp_client.connect_to_server(server_ip, data_port)

        # 触发 ECDH 握手 (信令通道)
        ecdh.set_server(server_ip, signaling_port)

        # 更新 UI 连接状态
        window.set_connection_status(f"发现服务器 {server_ip}, 正在密钥交换...")

    def _on_server_lost(server_ip):
        """服务器离线回调"""
        log.warning("服务器离线: %s", server_ip)
        window.set_connection_status("服务器离线, 正在搜索...")

    def _on_ecdh_done():
        """ECDH 握手完成回调 (在握手线程中调用)"""
        log.info("ECDH 密钥交换完成, TCP 通信已加密")
        window.set_connection_status(
            f"已加密连接到 {ecdh.server_ip} (AES-256-GCM)"
        )

    # 设置回调
    discovery.set_on_server_found(_on_server_found)
    discovery.set_on_server_lost(_on_server_lost)

    # ─── 启动所有模块 ───
    log.info("正在启动所有模块...")
    camera.start()
    logic.start()
    discovery.start()
    ecdh.start()

    # ─── ECDH 状态监控 (后台线程) ───
    def _ecdh_monitor():
        """监控 ECDH 握手状态, 完成后通知 UI"""
        while True:
            if ecdh.is_handshake_done:
                _on_ecdh_done()
                break
            time.sleep(0.5)

    import time
    ecdh_monitor_thread = threading.Thread(
        target=_ecdh_monitor, name="ecdh-monitor", daemon=True,
    )
    ecdh_monitor_thread.start()

    # ─── 创建并运行 UI ───
    log.info("启动 GUI 界面...")
    window = ClientWindow(camera=camera, logic=logic, ui_fps=config.fps)

    # 设置初始连接状态
    window.set_connection_status("正在搜索服务器...")

    # ─── 关闭清理 ───
    def _shutdown():
        log.info("正在关闭所有模块...")
        logic.stop()
        ecdh.stop()
        discovery.stop()
        tcp_client.close()
        yolo_detector.release()
        camera.stop()
        log.info("所有模块已关闭")

    try:
        window.mainloop()
    except tk.TclError as e:
        raise RuntimeError(
            f"无法启动 tkinter GUI: {e}. "
            f"如果是无桌面环境, 请确保已安装 Tk 库并设置了 DISPLAY 环境变量."
        ) from e
    finally:
        _shutdown()

    sys.exit(0)


if __name__ == "__main__":
    main()
