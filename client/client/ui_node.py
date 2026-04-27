from __future__ import annotations

import base64
import logging
import sys
import tkinter as tk
from typing import Any
from tkinter import messagebox, scrolledtext

import cv2

from client.camera_node import CameraNode
from client.config import parse_config
from client.logic_node import LogicNode
from client.logic_utils import summarize_counts, summarize_items
from client.tcp_client_node import TcpClientNode


STATE_LABELS = {
    "idle": "Idle",
    "recognizing_face": "Recognizing Face",
    "waiting_camera_move": "Waiting For Camera Move",
    "waiting_camera_stable": "Waiting For Stable Preview",
    "capturing_pre_material": "Capturing Pre-Operation Materials",
    "waiting_finish": "Waiting For Finish",
    "capturing_post_material": "Capturing Post-Operation Materials",
    "computing_diff": "Computing Changes",
    "submitting_inventory": "Uploading Records",
    "success": "Success",
    "error": "Error",
}


class ClientWindow:
    def __init__(self, *, camera: CameraNode, logic: LogicNode, ui_fps: float) -> None:
        self.camera = camera
        self.logic = logic
        self.refresh_interval_ms = max(1, int(1000 / max(ui_fps, 1.0)))
        self._last_frame_seq = -1
        self._status_payload: dict[str, Any] = self.logic.get_status_snapshot()
        self._local_notice = ""
        self._preview_photo: tk.PhotoImage | None = None

        self.root = tk.Tk()
        self.root.title("Embedded Inventory Client")
        self.root.geometry("1100x800")
        self.root.minsize(960, 700)
        self.root.protocol("WM_DELETE_WINDOW", self._handle_close)

        container = tk.Frame(self.root, padx=12, pady=12)
        container.pack(fill=tk.BOTH, expand=True)

        self.preview_label = tk.Label(
            container,
            text="Waiting for camera preview",
            bg="#111111",
            fg="#dddddd",
            relief=tk.SOLID,
            borderwidth=1,
            anchor=tk.CENTER,
        )
        self.preview_label.pack(fill=tk.BOTH, expand=True)
        self.preview_label.configure(width=960, height=540)

        button_row = tk.Frame(container, pady=10)
        button_row.pack(fill=tk.X)

        self.start_button = tk.Button(button_row, text="Start", command=self._handle_start_clicked)
        self.finish_button = tk.Button(button_row, text="Finish", command=self._handle_finish_clicked)
        self.start_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.finish_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

        self.status_view = scrolledtext.ScrolledText(container, wrap=tk.WORD, height=12)
        self.status_view.pack(fill=tk.BOTH, expand=False)
        self.status_view.configure(state=tk.DISABLED)

        self._schedule_refresh()
        self._update_status_text()
        self._update_buttons()

    def _refresh_view(self) -> None:
        self._refresh_preview()
        self._status_payload = self.logic.get_status_snapshot()
        self._update_status_text()
        self._update_buttons()
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        self.root.after(self.refresh_interval_ms, self._refresh_view)

    def _refresh_preview(self) -> None:
        frame, frame_seq = self.camera.get_latest_frame_snapshot()
        if frame is None or frame_seq == self._last_frame_seq:
            return

        self._last_frame_seq = frame_seq
        display_frame = self._resize_for_preview(frame)
        success, encoded = cv2.imencode(".png", display_frame)
        if not success:
            return

        png_base64 = base64.b64encode(encoded.tobytes()).decode("ascii")
        self._preview_photo = tk.PhotoImage(data=png_base64)
        self.preview_label.configure(image=self._preview_photo, text="")

    def _resize_for_preview(self, frame):
        label_width = max(self.preview_label.winfo_width(), 960)
        label_height = max(self.preview_label.winfo_height(), 540)
        frame_height, frame_width = frame.shape[:2]

        scale = min(label_width / frame_width, label_height / frame_height)
        scale = max(scale, 0.1)
        target_width = max(1, int(frame_width * scale))
        target_height = max(1, int(frame_height * scale))
        if target_width == frame_width and target_height == frame_height:
            return frame[:, :, ::-1].copy()

        resized = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)
        return resized[:, :, ::-1].copy()

    def _handle_start_clicked(self) -> None:
        success, message = self.logic.start_operation()
        if not success:
            self._local_notice = message
            self._update_status_text()
            messagebox.showwarning("Start Failed", message)
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
            messagebox.showwarning("Finish Failed", message)
            return

        self._local_notice = ""
        self._status_payload = self.logic.get_status_snapshot()
        self._update_status_text()
        self._update_buttons()

    def _update_status_text(self) -> None:
        payload = self._status_payload
        state = str(payload.get("state", "idle"))
        lines = [
            f"State: {STATE_LABELS.get(state, state)}",
            f"Message: {payload.get('message', '')}",
        ]
        if self._local_notice:
            lines.append(f"Local Notice: {self._local_notice}")

        person = str(payload.get("person", ""))
        if person:
            lines.append(f"Person: {person}")

        pre_counts = payload.get("pre_counts", {})
        post_counts = payload.get("post_counts", {})
        added_items = payload.get("added_items", [])
        removed_items = payload.get("removed_items", [])

        lines.append(f"Pre-Operation Materials: {summarize_counts(pre_counts if isinstance(pre_counts, dict) else {})}")
        lines.append(f"Post-Operation Materials: {summarize_counts(post_counts if isinstance(post_counts, dict) else {})}")
        lines.append(f"Added Items: {summarize_items(added_items if isinstance(added_items, list) else [])}")
        lines.append(f"Removed Items: {summarize_items(removed_items if isinstance(removed_items, list) else [])}")

        self.status_view.configure(state=tk.NORMAL)
        self.status_view.delete("1.0", tk.END)
        self.status_view.insert("1.0", "\n".join(lines))
        self.status_view.configure(state=tk.DISABLED)

    def _update_buttons(self) -> None:
        state = str(self._status_payload.get("state", "idle"))
        start_state = tk.DISABLED
        finish_state = tk.DISABLED
        if state in {"idle", "success", "error"}:
            start_state = tk.NORMAL
        elif state == "waiting_finish":
            finish_state = tk.NORMAL

        self.start_button.configure(state=start_state)
        self.finish_button.configure(state=finish_state)

    def _handle_close(self) -> None:
        self.root.quit()

    def mainloop(self) -> None:
        self.root.mainloop()


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

    def _shutdown() -> None:
        logic.stop()
        tcp_client.close()
        camera.stop()
    try:
        window = ClientWindow(camera=camera, logic=logic, ui_fps=config.fps)
        window.mainloop()
    except tk.TclError as exc:
        raise RuntimeError(
            f"Failed to start tkinter UI: {exc}. If this is a headless environment, use embedded-client-camera "
            "and embedded-client-server for no-GUI checks first."
        ) from exc
    finally:
        _shutdown()
    sys.exit(0)


if __name__ == "__main__":
    main()
