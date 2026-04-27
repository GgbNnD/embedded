from __future__ import annotations

import logging
import sys
from typing import Any

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

from client.camera_node import CameraNode
from client.config import parse_config
from client.logic_node import LogicNode
from client.logic_utils import summarize_counts, summarize_items
from client.tcp_client_node import TcpClientNode


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


class ClientWindow(QMainWindow):
    def __init__(self, *, camera: CameraNode, logic: LogicNode) -> None:
        super().__init__()
        self.camera = camera
        self.logic = logic
        self._last_frame_seq = -1
        self._status_payload: dict[str, Any] = self.logic.get_status_snapshot()
        self._local_notice = ""

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

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_view)
        self._refresh_timer.start(100)

        self._update_status_text()
        self._update_buttons()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._refresh_timer.stop()
        super().closeEvent(event)

    def _refresh_view(self) -> None:
        self._refresh_preview()
        self._status_payload = self.logic.get_status_snapshot()
        self._update_status_text()
        self._update_buttons()

    def _refresh_preview(self) -> None:
        frame, frame_seq = self.camera.get_latest_frame_snapshot()
        if frame is None or frame_seq == self._last_frame_seq:
            return

        self._last_frame_seq = frame_seq
        rgb = frame[:, :, ::-1].copy()
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

    def _handle_start_clicked(self) -> None:
        success, message = self.logic.start_operation()
        if not success:
            self._local_notice = message
            self._update_status_text()
            QMessageBox.warning(self, "开始失败", message)
            return

        self._local_notice = ""
        self._status_payload = self.logic.get_status_snapshot()
        self._update_status_text()
        self._update_buttons()

    def _handle_finish_clicked(self) -> None:
        success, message = self.logic.finish_operation()
        if not success:
            self._local_notice = message
            self._update_status_text()
            QMessageBox.warning(self, "完成失败", message)
            return

        self._local_notice = ""
        self._status_payload = self.logic.get_status_snapshot()
        self._update_status_text()
        self._update_buttons()

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
        if state in {"idle", "success", "error"}:
            self.start_button.setEnabled(True)
            self.finish_button.setEnabled(False)
        elif state == "waiting_finish":
            self.start_button.setEnabled(False)
            self.finish_button.setEnabled(True)
        else:
            self.start_button.setEnabled(False)
            self.finish_button.setEnabled(False)


def main(argv: list[str] | None = None) -> None:
    config = parse_config(
        argv,
        description="Standalone client application for face recognition and inventory flow.",
        include_camera=True,
        include_server=True,
        include_workflow=True,
    )
    logging.basicConfig(level=getattr(logging, config.log_level), format="[%(levelname)s] %(name)s: %(message)s")

    camera = CameraNode(
        camera_index=config.camera_index,
        camera_backend=config.camera_backend,
        width=config.width,
        height=config.height,
        fps=config.fps,
        rpicam_executable=config.rpicam_executable,
        rpicam_timeout_ms=config.rpicam_timeout_ms,
        reopen_interval_sec=config.reopen_interval_sec,
    )
    tcp_client = TcpClientNode(
        server_host=config.server_host,
        server_port=config.server_port,
        connect_timeout_sec=config.connect_timeout_sec,
        request_timeout_sec=config.request_timeout_sec,
        jpeg_quality=config.jpeg_quality,
    )
    logic = LogicNode(
        camera=camera,
        tcp_client=tcp_client,
        face_retry_interval_sec=config.face_retry_interval_sec,
        face_timeout_sec=config.face_timeout_sec,
        settle_delay_sec=config.settle_delay_sec,
        stable_hold_sec=config.stable_hold_sec,
        stability_threshold=config.stability_threshold,
        stable_timeout_sec=config.stable_timeout_sec,
    )

    camera.start()
    logic.start()

    app = QApplication(sys.argv if argv is None else ["client-app", *argv])
    window = ClientWindow(camera=camera, logic=logic)
    window.show()

    def _shutdown() -> None:
        logic.stop()
        tcp_client.close()
        camera.stop()

    app.aboutToQuit.connect(_shutdown)

    exit_code = 0
    try:
        exit_code = app.exec_()
    finally:
        _shutdown()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
