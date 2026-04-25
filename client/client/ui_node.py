from __future__ import annotations

import json
import sys
from typing import Any

import rclpy
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
)
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String
from std_srvs.srv import Trigger

from client.image_utils import image_msg_to_bgr
from client.logic_utils import summarize_counts, summarize_items


STATE_LABELS = {
    "idle": "待机",
    "recognizing_face": "识别人脸",
    "waiting_camera_move": "等待移动摄像头",
    "waiting_camera_stable": "等待画面稳定",
    "capturing_pre_material": "抓拍操作前物资",
    "waiting_finish": "等待点击完成",
    "capturing_post_material": "抓拍操作后物资",
    "computing_diff": "计算差异",
    "submitting_inventory": "上传记录",
    "success": "成功",
    "error": "错误",
}


class UiNode(Node):
    def __init__(self) -> None:
        super().__init__("ui_node")

        self.declare_parameter("preview_topic", "/client/camera/preview")
        self.declare_parameter("status_topic", "/client/logic/status")
        self.declare_parameter("start_service", "/client/logic/start_operation")
        self.declare_parameter("finish_service", "/client/logic/finish_operation")

        preview_topic = str(self.get_parameter("preview_topic").value)
        status_topic = str(self.get_parameter("status_topic").value)
        start_service = str(self.get_parameter("start_service").value)
        finish_service = str(self.get_parameter("finish_service").value)

        self.preview_subscription = self.create_subscription(Image, preview_topic, self._preview_callback, 10)
        self.status_subscription = self.create_subscription(String, status_topic, self._status_callback, 10)
        self.start_client = self.create_client(Trigger, start_service)
        self.finish_client = self.create_client(Trigger, finish_service)

        self.window: ClientWindow | None = None

    def _preview_callback(self, msg: Image) -> None:
        if self.window is not None:
            self.window.update_preview(msg)

    def _status_callback(self, msg: String) -> None:
        if self.window is None:
            return

        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            payload = {
                "state": "error",
                "message": "状态消息解析失败",
                "person": "",
                "pre_counts": {},
                "post_counts": {},
                "added_items": [],
                "removed_items": [],
            }
        self.window.update_status(payload)

    def call_trigger(self, client, action_name: str) -> tuple[bool, str]:
        if not client.wait_for_service(timeout_sec=0.0):
            return False, f"{action_name}服务未就绪"

        future = client.call_async(Trigger.Request())
        rclpy.spin_until_future_complete(self, future, timeout_sec=2.0)
        if not future.done():
            return False, f"{action_name}请求超时"

        try:
            response = future.result()
        except Exception as exc:
            return False, f"{action_name}失败: {exc}"

        return bool(response.success), response.message


class ClientWindow(QMainWindow):
    def __init__(self, node: UiNode) -> None:
        super().__init__()
        self.node = node
        self.node.window = self

        self.setWindowTitle("统一操作客户端")
        self.resize(1100, 800)

        self.preview_label = QLabel("等待摄像头画面")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(960, 540)
        self.preview_label.setStyleSheet("background:#111;color:#ddd;border:1px solid #444;")

        self.status_view = QPlainTextEdit()
        self.status_view.setReadOnly(True)

        self.start_button = QPushButton("开始操作")
        self.finish_button = QPushButton("完成")
        self.start_button.clicked.connect(self._handle_start_clicked)
        self.finish_button.clicked.connect(self._handle_finish_clicked)

        button_row = QHBoxLayout()
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.finish_button)

        layout = QVBoxLayout()
        layout.addWidget(self.preview_label)
        layout.addLayout(button_row)
        layout.addWidget(self.status_view)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self._status_payload: dict[str, Any] = {
            "state": "idle",
            "message": "等待开始操作",
            "person": "",
            "pre_counts": {},
            "post_counts": {},
            "added_items": [],
            "removed_items": [],
        }
        self._local_notice = ""
        self._update_status_text()
        self._update_buttons()

    def update_preview(self, msg: Image) -> None:
        try:
            image = image_msg_to_bgr(msg)
        except Exception:
            return

        rgb = image[:, :, ::-1].copy()
        qimage = QImage(
            rgb.tobytes(),
            rgb.shape[1],
            rgb.shape[0],
            rgb.strides[0],
            QImage.Format_RGB888,
        ).copy()
        pixmap = QPixmap.fromImage(qimage)
        scaled = pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview_label.setPixmap(scaled)

    def update_status(self, payload: dict[str, Any]) -> None:
        self._status_payload = payload
        self._local_notice = ""
        self._update_status_text()
        self._update_buttons()

    def _handle_start_clicked(self) -> None:
        success, message = self.node.call_trigger(self.node.start_client, "开始操作")
        if not success:
            self._local_notice = message
            self._update_status_text()
            QMessageBox.warning(self, "开始失败", message)

    def _handle_finish_clicked(self) -> None:
        success, message = self.node.call_trigger(self.node.finish_client, "完成")
        if not success:
            self._local_notice = message
            self._update_status_text()
            QMessageBox.warning(self, "完成失败", message)

    def _update_status_text(self) -> None:
        payload = self._status_payload
        state = str(payload.get("state", "idle"))
        lines = [
            f"状态: {STATE_LABELS.get(state, state)}",
            f"提示: {payload.get('message', '')}",
        ]
        if self._local_notice:
            lines.append(f"本地提示: {self._local_notice}")

        person = str(payload.get("person", ""))
        if person:
            lines.append(f"人员: {person}")

        pre_counts = payload.get("pre_counts", {})
        post_counts = payload.get("post_counts", {})
        added_items = payload.get("added_items", [])
        removed_items = payload.get("removed_items", [])

        lines.append(f"操作前物资: {summarize_counts(pre_counts if isinstance(pre_counts, dict) else {})}")
        lines.append(f"操作后物资: {summarize_counts(post_counts if isinstance(post_counts, dict) else {})}")
        lines.append(f"增加项: {summarize_items(added_items if isinstance(added_items, list) else [])}")
        lines.append(f"减少项: {summarize_items(removed_items if isinstance(removed_items, list) else [])}")

        self.status_view.setPlainText("\n".join(lines))

    def _update_buttons(self) -> None:
        state = str(self._status_payload.get("state", "idle"))
        if state == "idle":
            self.start_button.setEnabled(True)
            self.finish_button.setEnabled(False)
        elif state == "waiting_finish":
            self.start_button.setEnabled(False)
            self.finish_button.setEnabled(True)
        else:
            self.start_button.setEnabled(False)
            self.finish_button.setEnabled(False)


def main() -> None:
    app = QApplication(sys.argv)
    rclpy.init()
    node = UiNode()
    window = ClientWindow(node)
    window.show()

    spin_timer = QTimer()
    spin_timer.timeout.connect(lambda: rclpy.spin_once(node, timeout_sec=0.0) if rclpy.ok() else None)
    spin_timer.start(30)

    exit_code = 0
    try:
        exit_code = app.exec_()
    finally:
        spin_timer.stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
