"""
加密 TCP 客户端模块
==================
替代原有的 client/tcp_client_node.py, 实现与服务器的 AES-GCM 加密 TCP 通信。

与旧版 (tcp_client_node.py) 的主要区别:
  1. 不再发送图像数据 (人脸识别和物资检测在板端本地完成)
  2. 只发送出入库记录 (INVENTORY_RECORD)
  3. 所有通信使用 AES-256-GCM 加密
  4. 自动从 PeerKey 获取加密密钥 (密钥由 ecdh_handler.py 在握手后存入)

通信协议:
  - 数据通道端口: 8890 (与信令端口 8889 和发现端口 8888 相互独立)
  - 消息格式: [4B加密总长][12B IV][密文][16B GCM Tag]
  - 消息类型: inventory_record (出入库记录)
  - 响应类型: inventory_ack (操作确认)

连接管理:
  - 自动重连 (最多 2 次尝试)
  - 非阻塞连接
  - 线程安全 (使用锁保护套接字)
"""

import socket
import threading
import time
import json
import logging
import uuid

from client.encrypted_protocol import (
    send_encrypted_message,
    recv_encrypted_message,
    build_inventory_request,
    ConnectionClosedError,
    ProtocolError,
)


class EncryptedTcpClient:
    """AES-256-GCM 加密 TCP 客户端

    负责与服务器建立加密 TCP 连接, 发送出入库记录并接收响应.

    典型用法:
        client = EncryptedTcpClient()
        client.connect_to_server("192.168.1.100", 8890)
        result = client.send_inventory_record(
            record_time="2026-07-05T10:30:00+08:00",
            person="张三",
            action="入库",
            items=[{"name": "cboard", "quantity": 2}],
        )
        if result["ok"]:
            print("出入库记录已提交")
        client.close()
    """

    def __init__(self,
                 connect_timeout_sec=3.0,
                 request_timeout_sec=15.0,
                 logger=None):
        """初始化加密 TCP 客户端

        Args:
            connect_timeout_sec: TCP 连接超时 (秒)
            request_timeout_sec: 请求超时 (秒)
            logger: 日志记录器
        """
        self._log = logger or logging.getLogger("client.encrypted_tcp")

        self._connect_timeout_sec = max(float(connect_timeout_sec), 0.5)
        self._request_timeout_sec = max(float(request_timeout_sec), 1.0)

        # 服务器连接信息
        self._server_ip = None
        self._server_port = None

        # 套接字与线程安全
        self._socket_lock = threading.Lock()
        self._socket = None

    # ─── 连接管理 ───

    def connect_to_server(self, server_ip, server_port):
        """设置目标服务器地址 (不立即连接, 延迟到首次请求时)

        Args:
            server_ip: 服务器 IP 地址
            server_port: 服务器数据通道端口 (默认 8890)
        """
        self._server_ip = server_ip
        self._server_port = int(server_port)
        self._log.info("设置目标服务器: %s:%s", server_ip, server_port)

    def close(self):
        """关闭 TCP 连接"""
        with self._socket_lock:
            self._close_socket_locked()

    def is_connected(self):
        """检查是否已连接"""
        with self._socket_lock:
            return self._socket is not None

    # ─── 核心方法: 发送出入库记录 ───

    def send_inventory_record(self, record_time, person, action, items):
        """发送一条出入库记录到服务器

        Args:
            record_time: 操作时间字符串 (ISO 8601 格式)
            person: 操作人姓名
            action: 操作类型 "入库" 或 "出库"
            items: 物资列表 [{"name": "cboard", "quantity": 2}, ...]

        Returns:
            dict: {"ok": True/False, "message": "...", "response": {...}}
                  ok=True 表示服务器已成功记录
        """
        # 构造 INVENTORY_RECORD 请求消息
        request = build_inventory_request(record_time, person, action, items)

        try:
            response = self._send_request(request)
            if response is None:
                return {"ok": False, "message": "服务器无响应", "response": None}

            if response.get("ok") is True:
                return {
                    "ok": True,
                    "message": "出入库记录已提交",
                    "response": response,
                }

            error = response.get("error", {})
            return {
                "ok": False,
                "message": error.get("message", "服务器返回错误"),
                "response": response,
            }

        except RuntimeError as e:
            # 可能原因: ECDH 未完成, 服务器离线
            return {"ok": False, "message": str(e), "response": None}
        except (ConnectionClosedError, ProtocolError, ConnectionError) as e:
            return {"ok": False, "message": f"网络错误: {e}", "response": None}
        except Exception as e:
            self._log.error("发送出入库记录时发生未预期错误: %s", e)
            return {"ok": False, "message": f"内部错误: {e}", "response": None}

    def check_connection(self):
        """检查与服务器的连接状态

        Returns:
            (ok: bool, message: str)
        """
        try:
            with self._socket_lock:
                self._ensure_connection_locked()
            return True, f"已连接到 {self._server_ip}:{self._server_port}"
        except Exception as e:
            return False, str(e)

    # ─── 内部实现 ───

    def _send_request(self, request_dict):
        """发送加密请求并接收加密响应

        支持自动重连 (最多 2 次尝试).
        线程安全: 整个 send/recv 在锁内完成, 防止多线程交错写入.

        Args:
            request_dict: 要发送的请求字典消息

        Returns:
            解密后的响应字典, 失败返回 None
        """
        if self._server_ip is None:
            raise RuntimeError("未设置服务器地址, 请先调用 connect_to_server()")

        with self._socket_lock:
            last_error = None
            # 最多重试 2 次 (首次 + 1 次重连)
            for attempt in range(2):
                try:
                    sock = self._ensure_connection_locked()
                    send_encrypted_message(sock, request_dict, self._server_ip)
                    response = recv_encrypted_message(sock, self._server_ip)
                    if isinstance(response, dict):
                        return response
                    raise ProtocolError("服务器返回非字典类型消息")
                except (OSError, ConnectionClosedError, ProtocolError, ConnectionError) as e:
                    last_error = e
                    self._close_socket_locked()
                    self._log.debug("请求失败 (第%s次), 正在重连: %s", attempt + 1, e)

        if last_error:
            raise last_error
        return None

    def _ensure_connection_locked(self):
        """确保套接字已连接 (在锁内调用)

        Returns:
            已连接的套接字

        Raises:
            RuntimeError: 未设置服务器地址
            ConnectionError: 连接失败
        """
        if self._socket is not None:
            return self._socket

        if self._server_ip is None:
            raise RuntimeError("未设置服务器地址")

        # 创建 TCP 连接
        sock = socket.create_connection(
            (self._server_ip, self._server_port),
            timeout=self._connect_timeout_sec,
        )
        sock.settimeout(self._request_timeout_sec)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._socket = sock
        self._log.info("已连接到服务器 %s:%s", self._server_ip, self._server_port)
        return sock

    def _close_socket_locked(self):
        """关闭套接字 (在锁内调用)"""
        if self._socket is None:
            return
        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._socket.close()
        except OSError:
            pass
        self._socket = None
        self._log.debug("TCP 连接已关闭")
