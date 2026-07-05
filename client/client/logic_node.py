"""
出入库工作流状态机模块 (RK3399Pro 版)
====================================
从原有的 client/logic_node.py 重构而来。

核心变更:
  1. 人脸识别在本地运行 (FaceRecognizer), 不再发送 face_image 到服务器
  2. 物资检测在本地 NPU 运行 (YoloDetector), 不再发送 material_image 到服务器
  3. 与服务器的通信仅涉及出入库记录的提交 (INVENTORY_RECORD)
  4. TCP 通信使用 ECDH + AES-256-GCM 加密 (EncryptedTcpClient)
  5. 服务器发现通过 UDP 组播自动完成 (discovery + ECDH handler)

工作流状态机:
  idle
    → (用户点击 Start) recognizing_face
    → (检测到已知人脸) waiting_camera_move
    → (用户点击 Capture Materials) capturing_pre_material
    → (本地YOLO检测完成) waiting_finish
    → (用户点击 Finish) capturing_post_material
    → (本地YOLO检测完成) computing_diff
    → (计算变化) submitting_inventory
    → (加密TCP发送) success / error
"""

import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable

from client.camera_node import CameraNode
from client.face_recognizer import FaceRecognizer
from client.yolo_detector import YoloDetector
from client.encrypted_tcp_client import EncryptedTcpClient
from client.logic_utils import (
    build_inventory_payload,
    compute_inventory_changes,
)


class LogicNode:
    """出入库工作流状态机

    管理整个出入库操作的生命周期: 人脸认证 → 拍照前 → 拍照后 → 计算差异 → 提交记录.

    典型用法:
        camera = CameraNode(...)
        face_recognizer = FaceRecognizer(...)
        yolo_detector = YoloDetector(...)
        tcp_client = EncryptedTcpClient(...)

        logic = LogicNode(
            camera=camera,
            face_recognizer=face_recognizer,
            yolo_detector=yolo_detector,
            tcp_client=tcp_client,
        )
        logic.start()
        # 通过 #1 UI 按钮触发 start_operation / capture_material_now / finish_operation
        # 通过 #2 get_status_snapshot() 获取当前状态用于 UI 更新
        logic.stop()
    """

    def __init__(self,
                 camera,
                 face_recognizer,
                 yolo_detector,
                 tcp_client,
                 face_retry_interval_sec=1.0,
                 face_timeout_sec=60.0,
                 logger=None):
        """初始化工作流状态机

        Args:
            camera: CameraNode 实例 (OpenCV 摄像头)
            face_recognizer: FaceRecognizer 实例 (dlib 本地人脸识别)
            yolo_detector: YoloDetector 实例 (RKNN NPU 本地物资检测)
            tcp_client: EncryptedTcpClient 实例 (加密 TCP 到服务器)
            face_retry_interval_sec: 人脸识别重试间隔 (秒)
            face_timeout_sec: 人脸识别总超时 (秒)
            logger: 日志记录器
        """
        self._log = logger or logging.getLogger("client.logic")

        # 外部依赖模块
        self._camera = camera
        self._face_recognizer = face_recognizer
        self._yolo_detector = yolo_detector
        self._tcp_client = tcp_client

        # 工作流参数
        self._face_retry_interval_sec = float(face_retry_interval_sec)
        self._face_timeout_sec = float(face_timeout_sec)

        # ─── 线程安全 ───
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._timer_thread = None

        # ─── 工作流状态 ───
        # workflow_token: 每次新操作递增, 用于识别过期的异步回调
        # (例如: 操作A启动人脸识别, 操作B也启动人脸识别, 操作A的回调返回时被忽略)
        self._workflow_token = 0

        # request_in_flight: 是否有网络请求/本地检测正在进行
        self._request_in_flight = False

        # 人脸识别时间控制
        self._face_deadline_sec = None       # 人脸识别总超时时间点
        self._next_face_attempt_sec = None   # 下一次人脸识别尝试的时间点

        # 操作记录
        self._finish_record_time = ""  # 操作完成时间 (ISO 8601)

        # 待发送的出入库记录队列
        self._pending_inventory_payloads = []

        # ─── 当前状态 (对外可见) ───
        self._state = "idle"       # 状态机当前状态
        self._message = "准备就绪"  # 当前状态的人类可读描述
        self._person = ""          # 识别到的操作人姓名
        self._pre_counts = {}      # 操作前物资计数 {"cboard": 2, ...}
        self._post_counts = {}     # 操作后物资计数
        self._added_items = []     # 新增物资列表
        self._removed_items = []   # 移除物资列表

        self._log.info("工作流逻辑已初始化 (本地人脸+本地YOLO+加密上报)")

    # ═══════════════════════════════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════════════════════════════

    def start(self):
        """启动工作流 (开启状态机定时器线程)"""
        if self._timer_thread is not None and self._timer_thread.is_alive():
            return

        self._stop_event.clear()
        self._timer_thread = threading.Thread(
            target=self._tick_loop, name="logic-tick", daemon=True,
        )
        self._timer_thread.start()
        self._log.info("工作流状态机已启动")

    def stop(self):
        """停止工作流 (停止定时器线程)"""
        self._stop_event.set()
        if self._timer_thread is not None:
            self._timer_thread.join(timeout=2.0)
            self._timer_thread = None
        self._log.info("工作流状态机已停止")

    # ═══════════════════════════════════════════════════════════════════════════
    # UI 按钮操作 (由 ui_node.py 调用)
    # ═══════════════════════════════════════════════════════════════════════════

    def start_operation(self):
        """开始新的出入库操作 (对应 UI 的 Start 按钮)

        流程:
          1. 重置所有状态
          2. 进入 "recognizing_face" 状态
          3. 定时器线程自动执行人脸检测循环

        Returns:
            (ok: bool, message: str)
        """
        with self._lock:
            if self._state not in {"idle", "success", "error"}:
                return False, "当前有操作正在进行, 不能启动新操作"

            # 递增 token, 使之前的异步操作结果被忽略
            self._workflow_token += 1

            # 重置所有状态
            self._request_in_flight = False
            self._face_deadline_sec = time.monotonic() + self._face_timeout_sec
            self._next_face_attempt_sec = time.monotonic()  # 立即开始第一次尝试
            self._finish_record_time = ""
            self._pending_inventory_payloads = []

            self._person = ""
            self._pre_counts = {}
            self._post_counts = {}
            self._added_items = []
            self._removed_items = []

            self._state = "recognizing_face"
            self._message = "正在识别人脸..."

        return True, "操作已启动"

    def capture_material_now(self):
        """拍照捕获操作前物资 (对应 UI 的 Capture Materials 按钮)

        仅在 "waiting_camera_move" 状态时有效。

        Returns:
            (ok: bool, message: str)
        """
        with self._lock:
            if self._state != "waiting_camera_move":
                return False, "当前状态不允许捕获物资"
            if self._request_in_flight:
                return False, "前一个检测请求尚未完成"
            token = self._workflow_token

        # 异步执行本地 YOLO 检测 (不阻塞 UI)
        self._capture_material_snapshot(token, phase="pre")
        return True, "正在捕获操作前物资..."

    def finish_operation(self):
        """完成操作-拍照捕获操作后物资 (对应 UI 的 Finish 按钮)

        仅在 "waiting_finish" 状态时有效。

        Returns:
            (ok: bool, message: str)
        """
        with self._lock:
            if self._state != "waiting_finish":
                return False, "当前状态不允许完成操作"
            if self._request_in_flight:
                return False, "前一个检测请求尚未完成"
            token = self._workflow_token

            # 记录操作时间
            self._finish_record_time = datetime.now().astimezone().isoformat(
                timespec="seconds"
            )

        # 异步执行本地 YOLO 检测 (不阻塞 UI)
        self._capture_material_snapshot(token, phase="post")
        return True, "正在捕获操作后物资..."

    # ═══════════════════════════════════════════════════════════════════════════
    # 状态查询 (由 ui_node.py 周期调用)
    # ═══════════════════════════════════════════════════════════════════════════

    def get_status_snapshot(self):
        """获取当前状态的快照 (线程安全)

        Returns:
            dict: {
                "state": str,         # 状态机状态名
                "message": str,       # 人类可读描述
                "person": str,        # 操作人
                "pre_counts": dict,   # 操作前物资计数
                "post_counts": dict,  # 操作后物资计数
                "added_items": list,  # 新增物资
                "removed_items": list,# 移除物资
            }
        """
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

    # ═══════════════════════════════════════════════════════════════════════════
    # 定时器循环 (后台线程)
    # ═══════════════════════════════════════════════════════════════════════════

    def _tick_loop(self):
        """定时器主循环: 每 100ms 检查一次是否需要执行人脸识别"""
        while not self._stop_event.wait(0.1):
            self._tick()

    def _tick(self):
        """单次时钟滴答: 根据当前状态执行对应的动作"""
        now_sec = time.monotonic()
        with self._lock:
            state = self._state
            request_in_flight = self._request_in_flight
            face_deadline_sec = self._face_deadline_sec
            next_face_attempt_sec = self._next_face_attempt_sec
            token = self._workflow_token

        # 人脸识别状态下的周期检查
        if state == "recognizing_face":
            # 超时检查
            if (face_deadline_sec is not None and
                now_sec >= face_deadline_sec and
                not request_in_flight):
                self._finish_terminal_state(
                    "error", f"人脸识别超时 ({self._face_timeout_sec}s 内未检测到已知人脸)",
                    token=token,
                )
                return

            # 重试检查
            if (not request_in_flight and
                next_face_attempt_sec is not None and
                now_sec >= next_face_attempt_sec):
                # 更新下一次尝试时间
                with self._lock:
                    if token == self._workflow_token:
                        self._next_face_attempt_sec = now_sec + self._face_retry_interval_sec

                # 执行本地人脸识别
                self._do_local_face_recognition(token)

    # ═══════════════════════════════════════════════════════════════════════════
    # 本地人脸识别 (替代旧的 _capture_face_attempt → 发送 face_image 到服务器)
    # ═══════════════════════════════════════════════════════════════════════════

    def _do_local_face_recognition(self, token):
        """执行一次本地人脸识别

        在后台线程中进行: 抓取摄像头帧 → 调用 FaceRecognizer → 判断结果.
        如果识别到单张已知人脸 → 切换到等待拍照状态.
        如果未识别到 → 保持 recognizing_face 状态, 等待下一次 tick 重试.

        Args:
            token: 当前工作流 token (用于验证回调时状态是否过期)
        """
        if not self._begin_request(token):
            return

        worker = threading.Thread(
            target=self._local_face_recognition_worker,
            args=(token,),
            name="face-recognition",
            daemon=True,
        )
        worker.start()

    def _local_face_recognition_worker(self, token):
        """人脸识别工作线程

        流程:
          1. 从摄像头获取最新帧
          2. 调用 FaceRecognizer.get_single_known_person()
          3. 若识别成功 → 记录人名, 切换到 waiting_camera_move
          4. 若识别失败 → 回到 recognizing_face 状态 (在下次 tick 重试)
        """
        try:
            # 步骤1: 获取摄像头帧
            result = self._camera.capture_image("face")
            if not result.ok or result.image is None:
                raise RuntimeError(f"获取摄像头帧失败: {result.message}")

            # 步骤2: 本地人脸识别 (dlib + face_recognition)
            person = self._face_recognizer.get_single_known_person(result.image)

        except Exception as e:
            self._end_request(token)
            self._finish_terminal_state("error", f"人脸识别出错: {e}", token=token)
            return

        self._end_request(token)

        # 如果 token 已过期 (用户又点了 Start), 丢弃结果
        if not self._token_is_active(token):
            return

        # 步骤3: 判断结果
        if person is None:
            # 未识别到已知人脸, 等待下次 tick 重试
            with self._lock:
                if self._face_deadline_sec is not None:
                    remaining_sec = max(0, int(self._face_deadline_sec - time.monotonic()))
                self._state = "recognizing_face"
                self._message = f"未检测到已知人脸, 正在重试... (剩余 {remaining_sec}s)"
            return

        # 识别成功: 记录人名, 切换到等待拍照
        with self._lock:
            self._person = person
            self._state = "waiting_camera_move"
            self._message = (
                f"已识别: {person}. "
                f"请将摄像头对准物资, 然后点击 Capture Materials"
            )

        self._log.info("人脸识别成功: %s", person)

    # ═══════════════════════════════════════════════════════════════════════════
    # 本地物资检测 (替代旧的 _capture_material_snapshot → 发送 material_image 到服务器)
    # ═══════════════════════════════════════════════════════════════════════════

    def _capture_material_snapshot(self, token, phase="pre"):
        """捕获物资快照并执行本地 YOLO 检测

        Args:
            token: 当前工作流 token
            phase: "pre" (操作前) 或 "post" (操作后)
        """
        # 更新状态显示
        if phase == "pre":
            self._set_state(
                "capturing_pre_material", "正在检测操作前物资...", token=token,
            )
        else:
            self._set_state(
                "capturing_post_material", "正在检测操作后物资...", token=token,
            )

        if not self._begin_request(token):
            return

        worker = threading.Thread(
            target=self._local_material_detection_worker,
            args=(token, phase),
            name=f"material-detection-{phase}",
            daemon=True,
        )
        worker.start()

    def _local_material_detection_worker(self, token, phase):
        """物资检测工作线程

        流程:
          1. 从摄像头获取最新帧
          2. 调用 YoloDetector.detect() 在 NPU 上推理
          3. 存储检测结果
          4. phase="pre" → 切换到 waiting_finish
          5. phase="post" → 切换到 computing_diff → 计算变化 → 提交记录
        """
        try:
            # 步骤1: 获取摄像头帧
            result = self._camera.capture_image(f"{phase}_material")
            if not result.ok or result.image is None:
                raise RuntimeError(f"获取摄像头帧失败: {result.message}")

            # 步骤2: NPU 本地 YOLO 物资检测
            counts = self._yolo_detector.detect(result.image)

        except Exception as e:
            self._end_request(token)
            self._finish_terminal_state("error", f"物资检测出错: {e}", token=token)
            return

        self._end_request(token)

        if not self._token_is_active(token):
            return

        # 步骤3: 存储检测结果并推进状态
        if phase == "pre":
            # 操作前检测完成 → 等待用户操作完成
            with self._lock:
                self._pre_counts = counts
                self._state = "waiting_finish"
                self._message = "操作前物资已记录. 请完成操作后点击 Finish"
            self._log.info("操作前物资检测完成: %s", counts)

        else:
            # 操作后检测完成 → 计算差异 → 提交记录
            with self._lock:
                self._post_counts = counts
                self._state = "computing_diff"
                self._message = "正在计算出入库变化..."
            self._log.info("操作后物资检测完成: %s", counts)
            self._finalize_inventory_changes(token)

    # ═══════════════════════════════════════════════════════════════════════════
    # 出入库记录计算与提交
    # ═══════════════════════════════════════════════════════════════════════════

    def _finalize_inventory_changes(self, token):
        """计算操作前后的物资变化, 生成出入库记录

        流程:
          1. 比较 pre_counts 和 post_counts
          2. 生成 added_items (入库) 和 removed_items (出库) 列表
          3. 若无变化 → 直接 success
          4. 若有变化 → 构造 encrypted inventory record → 加密 TCP 发送
        """
        with self._lock:
            # 计算物资变化
            self._added_items, self._removed_items = compute_inventory_changes(
                self._pre_counts, self._post_counts,
            )

            # 确保有操作时间
            if not self._finish_record_time:
                self._finish_record_time = datetime.now().astimezone().isoformat(
                    timespec="seconds"
                )

            # 无变化: 直接成功
            if not self._added_items and not self._removed_items:
                self._state = "success"
                self._message = "未检测到物资变化"
                self._request_in_flight = False
                self._pending_inventory_payloads = []
                self._log.info("无物资变化, 跳过上传")
                return

            # 有变化: 构造出入库记录
            self._pending_inventory_payloads = []

            if self._added_items:
                # 新增物资 → 入库记录
                self._pending_inventory_payloads.append(
                    build_inventory_payload(
                        self._finish_record_time, self._person, "入库",
                        self._added_items,
                    )
                )

            if self._removed_items:
                # 减少物资 → 出库记录
                self._pending_inventory_payloads.append(
                    build_inventory_payload(
                        self._finish_record_time, self._person, "出库",
                        self._removed_items,
                    )
                )

            self._state = "submitting_inventory"
            self._message = "正在上传出入库记录..."

        # 提交第一个记录 (可能触发级联)
        self._submit_next_inventory_record(token)

    def _submit_next_inventory_record(self, token):
        """提交队列中的下一个出入库记录 (加密 TCP 发送)

        从 _pending_inventory_payloads 队列弹出一条记录,
        通过 EncryptedTcpClient 发送到服务器.
        成功后继续提交队列中的下一条.

        Args:
            token: 当前工作流 token
        """
        with self._lock:
            if token != self._workflow_token:
                return

            if not self._pending_inventory_payloads:
                # 队列为空: 所有记录已发送完毕
                self._state = "success"
                self._message = "出入库记录已上传完毕"
                self._request_in_flight = False
                return

            # 弹出队首记录
            payload = self._pending_inventory_payloads.pop(0)

        if not self._begin_request(token):
            return

        worker = threading.Thread(
            target=self._inventory_send_worker,
            args=(token, payload),
            name="inventory-send",
            daemon=True,
        )
        worker.start()

    def _inventory_send_worker(self, token, payload):
        """出入库记录发送工作线程

        通过加密 TCP 将记录发送到服务器。
        因为是本地线程, 无需等待物理操作, 速度很快.

        Args:
            token: 当前工作流 token
            payload: 出入库记录字典 (来自 build_inventory_payload)
        """
        try:
            # 加密 TCP 发送出入库记录
            result = self._tcp_client.send_inventory_record(
                record_time=payload["time"],
                person=payload["person"],
                action=payload["action"],
                items=payload["items"],
            )

            if not result["ok"]:
                raise RuntimeError(result["message"])

        except Exception as e:
            self._end_request(token)
            self._finish_terminal_state(
                "error", f"出入库记录上传失败: {e}", token=token,
            )
            return

        self._end_request(token)

        if not self._token_is_active(token):
            return

        # 继续提交下一条记录 (如果有)
        self._submit_next_inventory_record(token)

    # ═══════════════════════════════════════════════════════════════════════════
    # 内部辅助方法
    # ═══════════════════════════════════════════════════════════════════════════

    def _begin_request(self, token):
        """尝试开始一个请求 (标记 request_in_flight = True)

        防止并发请求: 如果 token 过期或已有请求在进行中, 返回 False.

        Args:
            token: 当前工作流 token

        Returns:
            True 表示可以开始; False 表示请求被拒绝
        """
        with self._lock:
            if token != self._workflow_token or self._request_in_flight:
                return False
            self._request_in_flight = True
            return True

    def _end_request(self, token):
        """标记请求结束 (request_in_flight = False)"""
        with self._lock:
            if token == self._workflow_token:
                self._request_in_flight = False

    def _token_is_active(self, token):
        """检查 token 是否仍有效 (未被新操作替换)"""
        with self._lock:
            return token == self._workflow_token

    def _set_state(self, state, message, token=None):
        """设置当前状态和消息 (线程安全)"""
        with self._lock:
            if token is not None and token != self._workflow_token:
                return
            self._state = state
            self._message = message

    def _finish_terminal_state(self, terminal_state, message, token=None):
        """将状态机置为终态 (error 或 success) 并清理所有中间状态"""
        with self._lock:
            if token is not None and token != self._workflow_token:
                return

            self._state = terminal_state
            self._message = message
            self._request_in_flight = False
            self._face_deadline_sec = None
            self._next_face_attempt_sec = None
            self._finish_record_time = ""
            self._pending_inventory_payloads = []

        self._log.warning("工作流终止 [%s]: %s", terminal_state, message)
