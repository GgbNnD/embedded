"""
ECDH 密钥交换处理器
==================
负责与已发现的服务器执行 ECDH P-256 密钥交换, 完成安全握手。

握手流程 (参考 net/p2p_transfer/signaling/signaling_client.py):
  1. (Client) 使用非阻塞 connect 连接到服务器的信令端口 (8889)
  2. (Client) 发送 DEVICE_HELLO 消息, 携带本机 ECDH 公钥
  3. (Server) 接收 DEVICE_HELLO, 提取客户端公钥
  4. (Server) 计算共享密钥, 存储到 PeerKey
  5. (Server) 回复 DEVICE_HELLO_ACK, 携带服务器 ECDH 公钥
  6. (Client) 接收 DEVICE_HELLO_ACK, 提取服务器公钥
  7. (Client) 计算共享密钥, 存储到 PeerKey
  8. 握手完成, 后续 TCP 通信使用 AES-256-GCM 加密

连接超时: 默认 5000ms
握手完成后: 共享密钥由 PeerKey 管理, 协议层自动查询加密
"""

import socket
import select
import threading
import time
import json
import struct
import logging

from client.crypto_utils import (
    generate_ecdh_keypair,
    compute_ecdh_shared,
    aes_gcm_encrypt,
    aes_gcm_decrypt,
)
from client.peer_key import PeerKey
from client.platform_utils import set_nonblocking, set_blocking


# 信令端口 (与服务器 ECDH 握手端口)
SIGNALING_PORT = 8889
# 握手超时 (毫秒)
HANDSHAKE_TIMEOUT_MS = 5000
# 最大消息大小 (10MB)
MAX_MSG_SIZE = 10 * 1024 * 1024

# JSON 协议消息类型常量
MSG_TYPE_DEVICE_HELLO = "DEVICE_HELLO"
MSG_TYPE_DEVICE_HELLO_ACK = "DEVICE_HELLO_ACK"


class EcdhHandler:
    """ECDH 密钥交换处理器

    负责:
      - 生成本地 ECDH 密钥对
      - 与服务器完成 ECDH 握手
      - 将共享密钥存储到全局 PeerKey 存储

    典型用法:
        handler = EcdhHandler(device_id, device_name)
        handler.start()
        # 当 discovery 发现服务器时:
        handler.handshake_with_server(server_ip, server_port)
        # handler 会自动重试, 直到成功或手动停止
    """

    def __init__(self, device_id, device_name, local_ip):
        """初始化 ECDH 处理器

        Args:
            device_id: 本机唯一标识字符串
            device_name: 本机显示名称
            local_ip: 本机局域网 IP 地址
        """
        self._log = logging.getLogger("client.ecdh")

        self._device_id = device_id
        self._device_name = device_name
        self._local_ip = local_ip

        # 生成本地 ECDH P-256 密钥对 (公钥 + 私钥)
        self._public_key, self._private_key = generate_ecdh_keypair()
        self._log.info("ECDH 密钥对已生成")

        # 目标服务器信息 (由 discovery 回调设置)
        self._server_ip = None
        self._server_port = SIGNALING_PORT
        self._server_lock = threading.Lock()

        # 握手状态
        self._handshake_done = threading.Event()
        self._running = False
        self._handshake_thread = None

        # 握手重试控制
        self._retry_interval_sec = 3.0  # 重试间隔 (秒)

    # ─── 属性 ───

    @property
    def public_key(self):
        """本机 ECDH 公钥 (Base64 编码)"""
        return self._public_key

    @property
    def is_handshake_done(self):
        """是否已完成 ECDH 握手"""
        return self._handshake_done.is_set()

    @property
    def server_ip(self):
        """当前握手的服务器 IP (可能为 None)"""
        with self._server_lock:
            return self._server_ip

    # ─── 生命周期 ───

    def start(self):
        """启动 ECDH 处理器, 开始监听发现回调"""
        self._running = True
        self._log.info("ECDH 握手处理器已启动")

    def stop(self):
        """停止 ECDH 处理器"""
        self._running = False
        self._handshake_done.set()  # 唤醒等待线程
        if self._handshake_thread and self._handshake_thread.is_alive():
            self._handshake_thread.join(timeout=3)
        PeerKey.clear()
        self._log.info("ECDH 握手处理器已停止")

    def set_server(self, server_ip, server_port=SIGNALING_PORT):
        """设置目标服务器地址 (由 discovery 模块回调调用)

        Args:
            server_ip: 服务器 IP 地址
            server_port: 服务器信令端口 (默认 8889)
        """
        with self._server_lock:
            if self._server_ip == server_ip:
                return  # 已经设置过了
            self._server_ip = server_ip
            self._server_port = int(server_port)

        # 如果已有密钥, 先清除旧的
        PeerKey.remove(server_ip)
        self._handshake_done.clear()

        self._log.info("设置目标服务器: %s:%s", server_ip, server_port)

        # 启动握手线程 (非阻塞)
        if self._running:
            self._handshake_thread = threading.Thread(
                target=self._handshake_loop,
                name="ecdh-handshake",
                daemon=True,
            )
            self._handshake_thread.start()

    def wait_for_handshake(self, timeout_sec=None):
        """阻塞等待握手完成

        Args:
            timeout_sec: 超时秒数, None 表示无限等待

        Returns:
            True 表示握手成功, False 超时
        """
        return self._handshake_done.wait(timeout_sec)

    # ─── 握手线程 ───

    def _handshake_loop(self):
        """握手循环: 不断重试直到成功或停止"""
        while self._running and not self._handshake_done.is_set():
            with self._server_lock:
                server_ip = self._server_ip
                server_port = self._server_port
            if not server_ip:
                time.sleep(0.5)
                continue

            success = self._do_ecdh_handshake(server_ip, server_port)
            if success:
                self._log.info("ECDH 握手成功: %s:%s", server_ip, server_port)
                self._handshake_done.set()
                return

            # 握手失败, 等待后重试
            self._log.debug("ECDH 握手失败, %s 秒后重试", self._retry_interval_sec)
            for _ in range(int(self._retry_interval_sec * 10)):
                if not self._running or self._handshake_done.is_set():
                    return
                time.sleep(0.1)

    def _do_ecdh_handshake(self, server_ip, server_port):
        """执行一次完整的 ECDH 握手流程

        Args:
            server_ip: 服务器 IP
            server_port: 服务器信令端口

        Returns:
            True 握手成功, False 失败
        """
        # 步骤1: 非阻塞 TCP 连接到服务器信令端口
        sock = self._connect_nonblocking(server_ip, server_port)
        if sock is None:
            return False

        try:
            sock.settimeout(HANDSHAKE_TIMEOUT_MS / 1000.0)

            # 步骤2: 发送 DEVICE_HELLO (携带本机 ECDH 公钥)
            hello_msg = {
                "type": MSG_TYPE_DEVICE_HELLO,
                "device_id": self._device_id,
                "device_name": self._device_name,
                "ip": self._local_ip,
                "port": SIGNALING_PORT,
                "public_key": self._public_key,
            }
            self._send_raw_json(sock, hello_msg)

            # 步骤3: 接收 DEVICE_HELLO_ACK
            response = self._recv_raw_json(sock)
            if response is None:
                return False

            msg_type = response.get("type", "")
            if msg_type != MSG_TYPE_DEVICE_HELLO_ACK:
                self._log.warning("收到非预期的握手响应类型: %s", msg_type)
                return False

            # 步骤4: 提取服务器 ECDH 公钥
            remote_public = response.get("public_key", "")
            if not remote_public:
                self._log.warning("DEVICE_HELLO_ACK 中未包含服务器公钥")
                return False

            # 步骤5: 计算 ECDH 共享密钥
            shared = compute_ecdh_shared(self._private_key, remote_public)
            if shared is None or len(shared) != 32:
                self._log.error("ECDH 共享密钥计算失败")
                return False

            # 步骤6: 将 32 字节共享密钥存入 PeerKey
            PeerKey.store(server_ip, shared)
            self._log.debug("已存储 AES-256 密钥: %s (32字节)", server_ip)
            return True

        except socket.timeout:
            self._log.debug("ECDH 握手超时: %s:%s", server_ip, server_port)
            return False
        except Exception as e:
            self._log.debug("ECDH 握手异常: %s", e)
            return False
        finally:
            try:
                sock.close()
            except Exception:
                pass

    # ─── 网络连接辅助函数 ───

    @staticmethod
    def _connect_nonblocking(target_ip, target_port, timeout_ms=HANDSHAKE_TIMEOUT_MS):
        """非阻塞 TCP 连接到目标

        使用 non-blocking connect + select 超时模式:
          1. 创建 TCP 套接字, 设为非阻塞
          2. connect() (预期返回 BlockingIOError)
          3. select() 等待可写
          4. 检查 SO_ERROR 确认连接成功
          5. 恢复阻塞模式

        Args:
            target_ip: 目标 IP
            target_port: 目标端口
            timeout_ms: 超时毫秒

        Returns:
            已连接的阻塞套接字, 失败返回 None
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        set_nonblocking(sock)

        # 非阻塞 connect: 正常现象是抛出 BlockingIOError (EINPROGRESS)
        try:
            sock.connect((target_ip, target_port))
        except BlockingIOError:
            pass
        except OSError:
            sock.close()
            return None

        # select 等待连接完成
        _, writable, _ = select.select([], [sock], [], timeout_ms / 1000.0)
        if not writable:
            sock.close()
            return None

        # 检查 SO_ERROR 确认连接成功
        err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if err != 0:
            sock.close()
            return None

        # 连接成功, 恢复阻塞模式
        set_blocking(sock)
        sock.settimeout(timeout_ms / 1000.0)
        return sock

    # ─── 信令通道底层收发 ───

    @staticmethod
    def _send_raw_json(sock, msg):
        """发送明文 JSON 消息 (信令通道, 无加密)

        有线格式: [4字节大端长度][JSON UTF-8字节串]
        信令通道为短连接模式, 握手阶段还未完成密钥交换, 故使用明文发送.

        Args:
            sock: 已连接的 TCP 套接字
            msg: 要发送的字典消息 (将被 json.dumps 序列化)
        """
        body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        length_prefix = struct.pack("!I", len(body))
        EcdhHandler._send_all(sock, length_prefix + body)

    @staticmethod
    def _recv_raw_json(sock):
        """接收明文 JSON 消息 (信令通道, 无加密)

        先读取 4 字节大端长度前缀, 再按长度读取 JSON 正文并解析.

        Args:
            sock: 已连接的 TCP 套接字

        Returns:
            解析后的字典, 失败返回 None
        """
        try:
            len_bytes = EcdhHandler._recv_exact(sock, 4)
        except ConnectionError:
            return None

        body_len = struct.unpack("!I", len_bytes)[0]
        if body_len > MAX_MSG_SIZE:
            return None

        try:
            body = EcdhHandler._recv_exact(sock, body_len)
        except ConnectionError:
            return None

        try:
            return json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    @staticmethod
    def _send_all(sock, data):
        """将全部数据写入套接字 (循环 send 直到全部发出)"""
        sent = 0
        while sent < len(data):
            try:
                n = sock.send(data[sent:])
            except (BlockingIOError, InterruptedError):
                continue
            if n < 0:
                raise ConnectionError("发送失败")
            sent += n

    @staticmethod
    def _recv_exact(sock, n):
        """从套接字精确读取 n 字节 (循环 recv 直到凑满)"""
        data = b""
        while len(data) < n:
            try:
                chunk = sock.recv(n - len(data))
            except InterruptedError:
                continue
            except socket.timeout:
                raise ConnectionError("接收超时")
            except BlockingIOError:
                raise ConnectionError("recv would block")
            if not chunk:
                raise ConnectionError("连接已关闭")
            data += chunk
        return data
