from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Callable

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String
from std_srvs.srv import Trigger

from client.image_utils import compute_gray_mean, image_msg_to_bgr
from client.logic_utils import (
    FrameStabilityTracker,
    build_inventory_payload,
    compute_inventory_changes,
    extract_material_counts,
    extract_single_known_person,
    parse_server_response,
)
from client.srv import CaptureImage, SendServerRequest


class LogicNode(Node):
    def __init__(self) -> None:
        super().__init__("logic_node")

        self.declare_parameter("preview_topic", "/client/camera/preview")
        self.declare_parameter("status_topic", "/client/logic/status")
        self.declare_parameter("capture_service", "/client/camera/capture_image")
        self.declare_parameter("send_server_service", "/client/tcp/send_server_request")
        self.declare_parameter("start_service", "/client/logic/start_operation")
        self.declare_parameter("finish_service", "/client/logic/finish_operation")
        self.declare_parameter("face_retry_interval_sec", 1.0)
        self.declare_parameter("face_timeout_sec", 60.0)
        self.declare_parameter("settle_delay_sec", 3.5)
        self.declare_parameter("stable_hold_sec", 1.0)
        self.declare_parameter("stability_threshold", 3.0)
        self.declare_parameter("stable_timeout_sec", 8.0)

        preview_topic = str(self.get_parameter("preview_topic").value)
        status_topic = str(self.get_parameter("status_topic").value)
        capture_service = str(self.get_parameter("capture_service").value)
        send_server_service = str(self.get_parameter("send_server_service").value)
        start_service = str(self.get_parameter("start_service").value)
        finish_service = str(self.get_parameter("finish_service").value)

        self.face_retry_interval_sec = float(self.get_parameter("face_retry_interval_sec").value)
        self.face_timeout_sec = float(self.get_parameter("face_timeout_sec").value)
        self.settle_delay_sec = float(self.get_parameter("settle_delay_sec").value)
        self.stable_hold_sec = float(self.get_parameter("stable_hold_sec").value)
        self.stability_threshold = float(self.get_parameter("stability_threshold").value)
        self.stable_timeout_sec = float(self.get_parameter("stable_timeout_sec").value)

        self.status_publisher = self.create_publisher(String, status_topic, 10)
        self.preview_subscription = self.create_subscription(Image, preview_topic, self._preview_callback, 10)
        self.capture_client = self.create_client(CaptureImage, capture_service)
        self.server_client = self.create_client(SendServerRequest, send_server_service)
        self.start_service = self.create_service(Trigger, start_service, self._handle_start_operation)
        self.finish_service = self.create_service(Trigger, finish_service, self._handle_finish_operation)
        self.timer = self.create_timer(0.1, self._tick)

        self._stability_tracker = FrameStabilityTracker(
            threshold=self.stability_threshold,
            hold_duration_sec=self.stable_hold_sec,
        )

        self._workflow_token = 0
        self._request_in_flight = False
        self._face_deadline_sec: float | None = None
        self._next_face_attempt_sec: float | None = None
        self._move_until_sec: float | None = None
        self._stable_deadline_sec: float | None = None
        self._finish_record_time: str = ""
        self._pending_inventory_payloads: list[dict[str, Any]] = []

        self._state = "idle"
        self._message = "等待开始操作"
        self._person = ""
        self._pre_counts: dict[str, int] = {}
        self._post_counts: dict[str, int] = {}
        self._added_items: list[dict[str, int | str]] = []
        self._removed_items: list[dict[str, int | str]] = []

        self._publish_status()

        self.get_logger().info(f"Preview topic: {preview_topic}")
        self.get_logger().info(f"Status topic: {status_topic}")
        self.get_logger().info(f"Capture service client: {capture_service}")
        self.get_logger().info(f"Server service client: {send_server_service}")

    def _handle_start_operation(self, request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        del request

        if self._state != "idle":
            response.success = False
            response.message = "当前流程正在进行中"
            return response

        if not self.capture_client.wait_for_service(timeout_sec=0.0):
            response.success = False
            response.message = "摄像头抓拍服务未就绪"
            return response

        if not self.server_client.wait_for_service(timeout_sec=0.0):
            response.success = False
            response.message = "TCP 通信服务未就绪"
            return response

        self._workflow_token += 1
        self._request_in_flight = False
        self._face_deadline_sec = time.monotonic() + self.face_timeout_sec
        self._next_face_attempt_sec = time.monotonic()
        self._move_until_sec = None
        self._stable_deadline_sec = None
        self._finish_record_time = ""
        self._pending_inventory_payloads = []
        self._stability_tracker.reset()

        self._person = ""
        self._pre_counts = {}
        self._post_counts = {}
        self._added_items = []
        self._removed_items = []

        self._set_state("recognizing_face", "正在识别人脸")
        response.success = True
        response.message = "已开始操作流程"
        return response

    def _handle_finish_operation(self, request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        del request

        if self._state != "waiting_finish":
            response.success = False
            response.message = "当前不在等待完成状态"
            return response

        if self._request_in_flight:
            response.success = False
            response.message = "当前仍有请求进行中，请稍候"
            return response

        self._finish_record_time = datetime.now().astimezone().isoformat(timespec="seconds")
        self._capture_material_snapshot(self._workflow_token, phase="post")
        response.success = True
        response.message = "正在抓拍操作后物资"
        return response

    def _tick(self) -> None:
        now_sec = time.monotonic()

        if self._state == "recognizing_face":
            if self._face_deadline_sec is not None and now_sec >= self._face_deadline_sec and not self._request_in_flight:
                self._finish_with_terminal_state("error", "60 秒内未识别到有效人脸")
                return

            if (
                not self._request_in_flight
                and self._next_face_attempt_sec is not None
                and now_sec >= self._next_face_attempt_sec
            ):
                self._next_face_attempt_sec = now_sec + self.face_retry_interval_sec
                self._capture_face_attempt(self._workflow_token)
                return

        if self._state == "waiting_camera_move" and self._move_until_sec is not None and now_sec >= self._move_until_sec:
            self._stability_tracker.reset()
            self._stable_deadline_sec = now_sec + self.stable_timeout_sec
            self._set_state("waiting_camera_stable", "请保持物资画面稳定，正在等待稳定后抓拍")
            return

        if (
            self._state == "waiting_camera_stable"
            and self._stable_deadline_sec is not None
            and now_sec >= self._stable_deadline_sec
            and not self._request_in_flight
        ):
            self._finish_with_terminal_state("error", "画面长时间不稳定，请重新开始操作")

    def _preview_callback(self, msg: Image) -> None:
        if self._state != "waiting_camera_stable" or self._request_in_flight:
            return

        try:
            image = image_msg_to_bgr(msg)
            mean_value = compute_gray_mean(image)
        except Exception:
            return

        if self._stability_tracker.update(mean_value, time.monotonic()):
            self._capture_material_snapshot(self._workflow_token, phase="pre")

    def _capture_face_attempt(self, token: int) -> None:
        self._request_capture(
            token,
            reason="face",
            on_success=lambda image: self._request_server(
                token=token,
                request_type="face_image",
                image=image,
                payload_json="",
                on_success=self._handle_face_server_response,
            ),
        )

    def _capture_material_snapshot(self, token: int, *, phase: str) -> None:
        state = "capturing_pre_material" if phase == "pre" else "capturing_post_material"
        message = "正在抓拍操作前物资" if phase == "pre" else "正在抓拍操作后物资"
        self._set_state(state, message)
        self._request_capture(
            token,
            reason=f"{phase}_material",
            on_success=lambda image: self._request_server(
                token=token,
                request_type="material_image",
                image=image,
                payload_json="",
                on_success=lambda response_json: self._handle_material_server_response(response_json, phase=phase),
            ),
        )

    def _request_capture(
        self,
        token: int,
        *,
        reason: str,
        on_success: Callable[[Image], None],
    ) -> None:
        if not self.capture_client.wait_for_service(timeout_sec=0.0):
            self._finish_with_terminal_state("error", "摄像头抓拍服务不可用")
            return

        request = CaptureImage.Request()
        request.reason = reason
        self._request_in_flight = True
        future = self.capture_client.call_async(request)

        def _done_callback(done_future) -> None:
            self._request_in_flight = False
            if token != self._workflow_token:
                return

            try:
                response = done_future.result()
            except Exception as exc:
                self._finish_with_terminal_state("error", f"抓拍失败: {exc}")
                return

            if not response.ok:
                self._finish_with_terminal_state("error", f"抓拍失败: {response.message}")
                return

            on_success(response.image)

        future.add_done_callback(_done_callback)

    def _request_server(
        self,
        *,
        token: int,
        request_type: str,
        image: Image | None,
        payload_json: str,
        on_success: Callable[[str], None],
    ) -> None:
        if not self.server_client.wait_for_service(timeout_sec=0.0):
            self._finish_with_terminal_state("error", "TCP 通信服务不可用")
            return

        request = SendServerRequest.Request()
        request.request_type = request_type
        if image is not None:
            request.image = image
        request.payload_json = payload_json

        self._request_in_flight = True
        future = self.server_client.call_async(request)

        def _done_callback(done_future) -> None:
            self._request_in_flight = False
            if token != self._workflow_token:
                return

            try:
                response = done_future.result()
            except Exception as exc:
                self._finish_with_terminal_state("error", f"请求 server 失败: {exc}")
                return

            if not response.ok:
                self._finish_with_terminal_state(
                    "error",
                    f"server {request_type} 请求失败: {response.code} {response.message}".strip(),
                )
                return

            on_success(response.response_json)

        future.add_done_callback(_done_callback)

    def _handle_face_server_response(self, response_json: str) -> None:
        try:
            payload = parse_server_response(response_json)
            person = extract_single_known_person(payload)
        except Exception as exc:
            self._finish_with_terminal_state("error", f"解析人脸识别结果失败: {exc}")
            return

        if person is None:
            remaining_sec = 0
            if self._face_deadline_sec is not None:
                remaining_sec = max(0, int(self._face_deadline_sec - time.monotonic()))
            self._set_state("recognizing_face", f"未识别到唯一已知人脸，继续尝试（剩余 {remaining_sec} 秒）")
            return

        self._person = person
        self._move_until_sec = time.monotonic() + self.settle_delay_sec
        self._set_state("waiting_camera_move", f"识别到 {person}，请将摄像头移动到物资并稍候")

    def _handle_material_server_response(self, response_json: str, *, phase: str) -> None:
        try:
            payload = parse_server_response(response_json)
            counts = extract_material_counts(payload)
        except Exception as exc:
            self._finish_with_terminal_state("error", f"解析物资识别结果失败: {exc}")
            return

        if phase == "pre":
            self._pre_counts = counts
            self._set_state("waiting_finish", "已记录操作前物资，请完成操作后点击完成")
            return

        self._post_counts = counts
        self._set_state("computing_diff", "正在计算物资变化")
        self._finalize_inventory_changes()

    def _finalize_inventory_changes(self) -> None:
        self._added_items, self._removed_items = compute_inventory_changes(self._pre_counts, self._post_counts)
        if not self._finish_record_time:
            self._finish_record_time = datetime.now().astimezone().isoformat(timespec="seconds")

        if not self._added_items and not self._removed_items:
            self._finish_with_terminal_state("success", "未检测到变化")
            return

        self._pending_inventory_payloads = []
        if self._added_items:
            self._pending_inventory_payloads.append(
                build_inventory_payload(self._finish_record_time, self._person, "入库", self._added_items)
            )
        if self._removed_items:
            self._pending_inventory_payloads.append(
                build_inventory_payload(self._finish_record_time, self._person, "出库", self._removed_items)
            )

        self._set_state("submitting_inventory", "正在上传操作记录")
        self._submit_next_inventory_record(self._workflow_token)

    def _submit_next_inventory_record(self, token: int) -> None:
        if token != self._workflow_token:
            return

        if not self._pending_inventory_payloads:
            self._finish_with_terminal_state("success", "操作记录已上传")
            return

        payload = self._pending_inventory_payloads.pop(0)
        self._request_server(
            token=token,
            request_type="inventory_record",
            image=None,
            payload_json=json.dumps(payload, ensure_ascii=False),
            on_success=lambda response_json: self._handle_inventory_server_response(token, response_json),
        )

    def _handle_inventory_server_response(self, token: int, response_json: str) -> None:
        try:
            parse_server_response(response_json)
        except Exception as exc:
            self._finish_with_terminal_state("error", f"解析出入库响应失败: {exc}")
            return

        self._submit_next_inventory_record(token)

    def _set_state(self, state: str, message: str) -> None:
        self._state = state
        self._message = message
        self._publish_status()

    def _publish_status(self, *, override_state: str | None = None, override_message: str | None = None) -> None:
        payload = {
            "state": override_state or self._state,
            "message": override_message or self._message,
            "person": self._person,
            "pre_counts": self._pre_counts,
            "post_counts": self._post_counts,
            "added_items": self._added_items,
            "removed_items": self._removed_items,
        }
        self.status_publisher.publish(String(data=json.dumps(payload, ensure_ascii=False)))

    def _finish_with_terminal_state(self, terminal_state: str, message: str) -> None:
        self._publish_status(override_state=terminal_state, override_message=message)

        self._state = "idle"
        self._message = message
        self._request_in_flight = False
        self._face_deadline_sec = None
        self._next_face_attempt_sec = None
        self._move_until_sec = None
        self._stable_deadline_sec = None
        self._pending_inventory_payloads = []
        self._stability_tracker.reset()

        self._publish_status()


def main() -> None:
    rclpy.init()
    node = LogicNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
