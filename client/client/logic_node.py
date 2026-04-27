from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable

from client.camera_node import CameraNode
from client.logic_utils import (
    FrameStabilityTracker,
    build_inventory_payload,
    compute_inventory_changes,
    extract_material_counts,
    extract_single_known_person,
    parse_server_response,
)
from client.image_utils import compute_gray_mean
from client.tcp_client_node import TcpClientNode


class LogicNode:
    def __init__(
        self,
        *,
        camera: CameraNode,
        tcp_client: TcpClientNode,
        face_retry_interval_sec: float = 1.0,
        face_timeout_sec: float = 60.0,
        settle_delay_sec: float = 3.5,
        stable_hold_sec: float = 1.0,
        stability_threshold: float = 3.0,
        stable_timeout_sec: float = 8.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.logger = logger or logging.getLogger("client.logic")
        self.camera = camera
        self.tcp_client = tcp_client

        self.face_retry_interval_sec = float(face_retry_interval_sec)
        self.face_timeout_sec = float(face_timeout_sec)
        self.settle_delay_sec = float(settle_delay_sec)
        self.stable_hold_sec = float(stable_hold_sec)
        self.stability_threshold = float(stability_threshold)
        self.stable_timeout_sec = float(stable_timeout_sec)

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._timer_thread: threading.Thread | None = None
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
        self._finish_record_time = ""
        self._pending_inventory_payloads: list[dict[str, Any]] = []

        self._state = "idle"
        self._message = "Ready to start"
        self._person = ""
        self._pre_counts: dict[str, int] = {}
        self._post_counts: dict[str, int] = {}
        self._added_items: list[dict[str, int | str]] = []
        self._removed_items: list[dict[str, int | str]] = []

        self.logger.info("Logic initialized")

    def start(self) -> None:
        if self._timer_thread is not None and self._timer_thread.is_alive():
            return

        self._stop_event.clear()
        self._timer_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._timer_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._timer_thread is not None:
            self._timer_thread.join(timeout=2.0)
            self._timer_thread = None

    def start_operation(self) -> tuple[bool, str]:
        with self._lock:
            if self._state not in {"idle", "success", "error"}:
                return False, "A workflow is already in progress"

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
            self._state = "recognizing_face"
            self._message = "Recognizing face"

        return True, "Workflow started"

    def finish_operation(self) -> tuple[bool, str]:
        with self._lock:
            if self._state != "waiting_finish":
                return False, "The workflow is not waiting for completion"
            if self._request_in_flight:
                return False, "A request is still in progress"

            token = self._workflow_token
            self._finish_record_time = datetime.now().astimezone().isoformat(timespec="seconds")

        self._capture_material_snapshot(token, phase="post")
        return True, "Capturing the post-operation material snapshot"

    def get_status_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "message": self._message,
                "person": self._person,
                "pre_counts": dict(self._pre_counts),
                "post_counts": dict(self._post_counts),
                "added_items": list(self._added_items),
                "removed_items": list(self._removed_items),
            }

    def _tick_loop(self) -> None:
        while not self._stop_event.wait(0.1):
            self._tick()

    def _tick(self) -> None:
        now_sec = time.monotonic()
        with self._lock:
            state = self._state
            request_in_flight = self._request_in_flight
            face_deadline_sec = self._face_deadline_sec
            next_face_attempt_sec = self._next_face_attempt_sec
            move_until_sec = self._move_until_sec
            stable_deadline_sec = self._stable_deadline_sec
            token = self._workflow_token

        if state == "recognizing_face":
            if face_deadline_sec is not None and now_sec >= face_deadline_sec and not request_in_flight:
                self._finish_with_terminal_state("error", "Failed to recognize a valid face within 60 seconds", token=token)
                return

            if not request_in_flight and next_face_attempt_sec is not None and now_sec >= next_face_attempt_sec:
                with self._lock:
                    if token == self._workflow_token:
                        self._next_face_attempt_sec = now_sec + self.face_retry_interval_sec
                self._capture_face_attempt(token)
                return

        if state == "waiting_camera_move" and move_until_sec is not None and now_sec >= move_until_sec:
            with self._lock:
                if token != self._workflow_token:
                    return
                self._stability_tracker.reset()
                self._stable_deadline_sec = now_sec + self.stable_timeout_sec
                self._state = "waiting_camera_stable"
                self._message = "Keep the material view stable while waiting to capture"
            return

        if state == "waiting_camera_stable":
            if stable_deadline_sec is not None and now_sec >= stable_deadline_sec and not request_in_flight:
                self._finish_with_terminal_state("error", "The preview stayed unstable for too long, please restart", token=token)
                return

            if not request_in_flight:
                frame = self.camera.get_latest_frame()
                if frame is None:
                    return

                try:
                    mean_value = compute_gray_mean(frame)
                except Exception:
                    return

                with self._lock:
                    if (
                        token == self._workflow_token
                        and self._state == "waiting_camera_stable"
                        and not self._request_in_flight
                        and self._stability_tracker.update(mean_value, now_sec)
                    ):
                        pass
                    else:
                        return

                self._capture_material_snapshot(token, phase="pre")

    def _capture_face_attempt(self, token: int) -> None:
        self._start_image_request(
            token=token,
            reason="face",
            request_type="face_image",
            on_success=self._handle_face_server_response,
        )

    def _capture_material_snapshot(self, token: int, *, phase: str) -> None:
        state = "capturing_pre_material" if phase == "pre" else "capturing_post_material"
        message = "Capturing the pre-operation material snapshot" if phase == "pre" else "Capturing the post-operation material snapshot"
        self._set_state(state, message, token=token)
        self._start_image_request(
            token=token,
            reason=f"{phase}_material",
            request_type="material_image",
            on_success=lambda response_json: self._handle_material_server_response(response_json, phase=phase),
        )

    def _start_image_request(
        self,
        *,
        token: int,
        reason: str,
        request_type: str,
        on_success: Callable[[str], None],
    ) -> None:
        if not self._begin_request(token):
            return

        worker = threading.Thread(
            target=self._do_image_request,
            args=(token, reason, request_type, on_success),
            daemon=True,
        )
        worker.start()

    def _do_image_request(
        self,
        token: int,
        reason: str,
        request_type: str,
        on_success: Callable[[str], None],
    ) -> None:
        try:
            capture = self.camera.capture_image(reason)
            if not capture.ok or capture.image is None:
                raise RuntimeError(f"Capture failed: {capture.message}")

            response = self.tcp_client.send_server_request(
                request_type=request_type,
                image=capture.image,
            )
            if not response.ok:
                raise RuntimeError(f"Server {request_type} request failed: {response.code} {response.message}".strip())
        except Exception as exc:
            self._end_request(token)
            self._finish_with_terminal_state("error", str(exc), token=token)
            return

        self._end_request(token)
        if self._token_is_active(token):
            on_success(response.response_json)

    def _handle_face_server_response(self, response_json: str) -> None:
        try:
            payload = parse_server_response(response_json)
            person = extract_single_known_person(payload)
        except Exception as exc:
            self._finish_with_terminal_state("error", f"Failed to parse the face-recognition result: {exc}")
            return

        if person is None:
            with self._lock:
                remaining_sec = 0
                if self._face_deadline_sec is not None:
                    remaining_sec = max(0, int(self._face_deadline_sec - time.monotonic()))
                self._state = "recognizing_face"
                self._message = f"No single known face detected, retrying ({remaining_sec}s left)"
            return

        with self._lock:
            self._person = person
            self._move_until_sec = time.monotonic() + self.settle_delay_sec
            self._state = "waiting_camera_move"
            self._message = f"Recognized {person}. Move the camera to the materials and wait"

    def _handle_material_server_response(self, response_json: str, *, phase: str) -> None:
        try:
            payload = parse_server_response(response_json)
            counts = extract_material_counts(payload)
        except Exception as exc:
            self._finish_with_terminal_state("error", f"Failed to parse the material-recognition result: {exc}")
            return

        if phase == "pre":
            with self._lock:
                self._pre_counts = counts
                self._state = "waiting_finish"
                self._message = "Pre-operation materials recorded. Click Finish after the operation"
            return

        with self._lock:
            self._post_counts = counts
            self._state = "computing_diff"
            self._message = "Computing inventory changes"
        self._finalize_inventory_changes()

    def _finalize_inventory_changes(self) -> None:
        with self._lock:
            self._added_items, self._removed_items = compute_inventory_changes(self._pre_counts, self._post_counts)
            if not self._finish_record_time:
                self._finish_record_time = datetime.now().astimezone().isoformat(timespec="seconds")

            if not self._added_items and not self._removed_items:
                self._state = "success"
                self._message = "No changes detected"
                self._request_in_flight = False
                self._pending_inventory_payloads = []
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

            self._state = "submitting_inventory"
            self._message = "Uploading inventory records"
            token = self._workflow_token

        self._submit_next_inventory_record(token)

    def _submit_next_inventory_record(self, token: int) -> None:
        with self._lock:
            if token != self._workflow_token:
                return
            if not self._pending_inventory_payloads:
                self._state = "success"
                self._message = "Inventory records uploaded"
                self._request_in_flight = False
                return
            payload = self._pending_inventory_payloads.pop(0)

        if not self._begin_request(token):
            return

        worker = threading.Thread(
            target=self._do_inventory_request,
            args=(token, payload),
            daemon=True,
        )
        worker.start()

    def _do_inventory_request(self, token: int, payload: dict[str, Any]) -> None:
        try:
            response = self.tcp_client.send_server_request(
                request_type="inventory_record",
                payload=payload,
            )
            if not response.ok:
                raise RuntimeError(f"Server inventory_record request failed: {response.code} {response.message}".strip())
        except Exception as exc:
            self._end_request(token)
            self._finish_with_terminal_state("error", str(exc), token=token)
            return

        self._end_request(token)
        if self._token_is_active(token):
            self._handle_inventory_server_response(token, response.response_json)

    def _handle_inventory_server_response(self, token: int, response_json: str) -> None:
        try:
            parse_server_response(response_json)
        except Exception as exc:
            self._finish_with_terminal_state("error", f"Failed to parse the inventory response: {exc}", token=token)
            return

        self._submit_next_inventory_record(token)

    def _begin_request(self, token: int) -> bool:
        with self._lock:
            if token != self._workflow_token or self._request_in_flight:
                return False
            self._request_in_flight = True
            return True

    def _end_request(self, token: int) -> None:
        with self._lock:
            if token == self._workflow_token:
                self._request_in_flight = False

    def _token_is_active(self, token: int) -> bool:
        with self._lock:
            return token == self._workflow_token

    def _set_state(self, state: str, message: str, *, token: int | None = None) -> None:
        with self._lock:
            if token is not None and token != self._workflow_token:
                return
            self._state = state
            self._message = message

    def _finish_with_terminal_state(self, terminal_state: str, message: str, *, token: int | None = None) -> None:
        with self._lock:
            if token is not None and token != self._workflow_token:
                return

            self._state = terminal_state
            self._message = message
            self._request_in_flight = False
            self._face_deadline_sec = None
            self._next_face_attempt_sec = None
            self._move_until_sec = None
            self._stable_deadline_sec = None
            self._finish_record_time = ""
            self._pending_inventory_payloads = []
            self._stability_tracker.reset()
