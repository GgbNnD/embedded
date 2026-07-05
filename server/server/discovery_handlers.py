"""
服务端 UDP 组播发现 + ECDH 握手处理模块
========================================
为 server/tcp_bridge_node.py 提供网络发现和密钥交换功能。

与客户端(client/discovery.py, client/ecdh_handler.py)对应的服务端实现。

核心功能:
  1. ServerDiscoveryService: UDP 组播广播服务器存在, 通知局域网内的客户端
  2. EcdhSignalingServer: TCP 信令服务器 (端口 8889), 处理 DEVICE_HELLO 请求,
     与客户端完成 ECDH P-256 密钥交换

发现协议:
  - Server 每隔 3 秒广播 DEVICE_BROADCAST (device_name 中包含 "server" 标识)
  - Client 收到广播后得知服务器 IP 和端口
  - Client 向服务器的信令端口发起 TCP 连接 → ECDH 握手

ECDH 握手协议:
  1. Client → Server: DEVICE_HELLO (携带客户端 ECDH 公钥)
  2. Server → Client: DEVICE_HELLO_ACK (携带服务器 ECDH 公钥)
  3. 双方各自计算 ECDH 共享密钥 (32 字节 AES-256 密钥)
  4. Server 将客户端 IP→密钥 存入 PeerKey 存储
  5. 后续数据通信使用 AES-256-GCM 加密
"""

import socket
import struct
import json
import threading
import time
import base64
import logging

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

from server.platform_utils import set_reuse_addr, get_local_ips, select_local_ip


# ═══════════════════════════════════════════════════════════════════════════════
# 常量定义 (与客户端保持一致)
# ═══════════════════════════════════════════════════════════════════════════════

DISCOVERY_PORT = 8888     # UDP 组播发现端口
SIGNALING_PORT = 8889     # TCP 信令端口 (ECDH 握手)
DATA_PORT = 8890          # TCP 加密数据通道端口
BROADCAST_INTERVAL = 3    # 广播间隔 (秒)
MULTICAST_ADDR = "239.255.255.250"  # 组播地址
DEVICE_TIMEOUT = 10       # 设备离线超时 (秒)
MAX_MSG_SIZE = 10 * 1024 * 1024  # 最大消息大小

# 协议消息类型
MSG_DEVICE_BROADCAST = "DEVICE_BROADCAST"
MSG_DEVICE_OFFLINE = "DEVICE_OFFLINE"
MSG_DEVICE_HELLO = "DEVICE_HELLO"
MSG_DEVICE_HELLO_ACK = "DEVICE_HELLO_ACK"


# ═══════════════════════════════════════════════════════════════════════════════
# ECDH 工具函数 (服务端版)
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_ecdh_keypair():
    """生成 ECDH P-256 密钥对 (secp256r1 曲线)

    Returns:
        (public_key_b64: str, private_key_b64: str)
    """
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_der = private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    return (
        base64.b64encode(public_der).decode(),
        base64.b64encode(private_der).decode(),
    )


def _compute_ecdh_shared(local_private_b64, remote_public_b64):
    """计算 ECDH 共享密钥 (32 字节 AES-256 密钥)

    Args:
        local_private_b64: 本地 ECDH 私钥 (Base64 DER PKCS8)
        remote_public_b64: 远端 ECDH 公钥 (Base64 DER SubjectPublicKeyInfo)

    Returns:
        32 字节共享密钥 bytes, 失败返回 None
    """
    try:
        private_der = base64.b64decode(local_private_b64)
        public_der = base64.b64decode(remote_public_b64)

        private_key = serialization.load_der_private_key(private_der, password=None)
        peer_public_key = serialization.load_der_public_key(public_der)

        try:
            shared = private_key.exchange(ec.ECDH(), peer_public_key)
        except TypeError:
            shared = private_key.exchange(peer_public_key)

        return shared
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 对端密钥存储 (服务端版, 线程安全)
# ═══════════════════════════════════════════════════════════════════════════════

class ServerPeerKey:
    """服务端的 ECDH 共享密钥存储

    客户端 IP 地址 → 32 字节 AES-256 密钥的映射。
    数据通道收到加密消息时, 通过客户端 IP 查找对应的密钥。
    """
    _lock = threading.Lock()
    _secrets = {}

    @classmethod
    def store(cls, ip, shared_secret):
        with cls._lock:
            cls._secrets[ip] = shared_secret

    @classmethod
    def get(cls, ip):
        with cls._lock:
            return cls._secrets.get(ip)

    @classmethod
    def remove(cls, ip):
        with cls._lock:
            cls._secrets.pop(ip, None)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 服务端 UDP 组播发现服务
# ═══════════════════════════════════════════════════════════════════════════════

class ServerDiscoveryService:
    """服务端 UDP 组播发现服务

    启动后:
      - 每 3 秒向组播组广播 DEVICE_BROADCAST
      - 监听组播组, 接收客户端的在线/离线通知

    客户端收到广播后即可获知服务器的 IP 和端口信息。
    """

    def __init__(self, device_id, device_name, port=DISCOVERY_PORT,
                 logger=None):
        """初始化服务端发现服务

        Args:
            device_id: 服务器唯一标识 (如 UUID)
            device_name: 服务器显示名称 (如 "inventory_server")
            port: UDP 监听端口 (默认 8888)
            logger: 日志记录器
        """
        self._log = logger or logging.getLogger("server.discovery")

        self._device_id = device_id
        self._device_name = device_name
        self._port = int(port)
        self._running = False

        self._sock = None
        self._send_thread = None
        self._recv_thread = None

        self._local_ip = select_local_ip()

        # 已知客户端列表 (用于跟踪在线设备)
        self._clients = {}       # {(ip, port): last_seen_timestamp}
        self._clients_lock = threading.Lock()

    @property
    def local_ip(self):
        return self._local_ip

    def start(self):
        """启动发现服务"""
        if self._running:
            return
        self._sock = self._create_socket()
        self._running = True
        self._send_thread = threading.Thread(
            target=self._send_loop, name="server-discovery-send", daemon=True,
        )
        self._recv_thread = threading.Thread(
            target=self._recv_loop, name="server-discovery-recv", daemon=True,
        )
        self._send_thread.start()
        self._recv_thread.start()
        self._log.info("服务器 UDP 发现服务已启动: %s @ %s:%s",
                       self._device_name, self._local_ip, self._port)

    def stop(self):
        """停止发现服务"""
        if not self._running:
            return
        self._running = False

        # 发送离线通知
        offline_msg = json.dumps({
            "type": MSG_DEVICE_OFFLINE,
            "device_id": self._device_id,
        }).encode("utf-8")
        for _ in range(3):
            try:
                if self._sock:
                    self._sock.sendto(offline_msg, (MULTICAST_ADDR, self._port))
            except Exception:
                pass

        sock = self._sock
        self._sock = None
        if sock:
            try:
                sock.close()
            except Exception:
                pass

        for t in (self._send_thread, self._recv_thread):
            if t and t.is_alive():
                t.join(timeout=2)
        self._log.info("服务器 UDP 发现服务已停止")

    def _create_socket(self):
        """创建 UDP 组播套接字"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        set_reuse_addr(sock)
        sock.bind(("0.0.0.0", self._port))

        # 加入组播组
        mreq = struct.pack("!4s4s",
                           socket.inet_aton(MULTICAST_ADDR),
                           socket.inet_aton("0.0.0.0"))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        # 多网卡兼容
        for ip in get_local_ips():
            if ip != self._local_ip and not ip.startswith("127."):
                try:
                    mreq2 = struct.pack("!4s4s",
                                        socket.inet_aton(MULTICAST_ADDR),
                                        socket.inet_aton(ip))
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq2)
                except Exception:
                    pass

        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack("B", 64))
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                            socket.inet_aton(self._local_ip))
        except Exception:
            pass

        return sock

    def _send_loop(self):
        """发送线程: 定期广播 DEVICE_BROADCAST"""
        while self._running:
            msg = json.dumps({
                "type": MSG_DEVICE_BROADCAST,
                "device_id": self._device_id,
                "device_name": self._device_name,
                "ip": self._local_ip,
                "port": SIGNALING_PORT,    # 信令端口
                "data_port": DATA_PORT,     # 数据端口
                "timestamp": time.time(),
            }).encode("utf-8")

            try:
                if self._sock:
                    self._sock.sendto(msg, (MULTICAST_ADDR, self._port))
            except Exception:
                pass

            for _ in range(int(BROADCAST_INTERVAL * 10)):
                if not self._running:
                    break
                time.sleep(0.1)

    def _recv_loop(self):
        """接收线程: 监听客户端广播"""
        while self._running:
            if self._sock is None:
                break
            try:
                self._sock.settimeout(0.5)
                data, addr = self._sock.recvfrom(2048)
            except socket.timeout:
                continue
            except Exception:
                if self._running:
                    continue
                break

            try:
                msg = json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            msg_type = msg.get("type", "")
            sender_id = msg.get("device_id", "")
            sender_ip = addr[0]  # 使用数据包源 IP

            if sender_id == self._device_id:
                continue

            if msg_type == MSG_DEVICE_OFFLINE:
                self._log.info("客户端离线: %s (%s)", sender_id, sender_ip)
                ServerPeerKey.remove(sender_ip)
                continue

            if msg_type != MSG_DEVICE_BROADCAST:
                continue

            # 更新客户端在线记录
            sender_port = msg.get("port", SIGNALING_PORT)
            key = (sender_ip, sender_port)
            with self._clients_lock:
                is_new = key not in self._clients
                self._clients[key] = time.time()

            if is_new:
                self._log.info("发现客户端: %s (%s) @ %s:%s",
                               msg.get("device_name", ""), sender_id,
                               sender_ip, sender_port)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 服务端 ECDH 信令服务器
# ═══════════════════════════════════════════════════════════════════════════════

class EcdhSignalingServer:
    """服务端 ECDH 信令服务器

    在端口 8889 上监听 TCP 短连接, 处理客户端发来的 DEVICE_HELLO 请求。
    每个连接只处理一条消息, 回复 DEVICE_HELLO_ACK 后立即关闭。

    握手流程:
      1. 客户端 TCP 连接到 8889
      2. 客户端发送 DEVICE_HELLO (携带客户端公钥)
      3. 服务端接收, 提取客户端公钥, 计算共享密钥, 存储到 ServerPeerKey
      4. 服务端回复 DEVICE_HELLO_ACK (携带服务端公钥)
      5. 连接关闭, 握手完成
    """

    def __init__(self, port=SIGNALING_PORT, logger=None):
        """初始化 ECDH 信令服务器

        Args:
            port: 监听端口 (默认 8889)
            logger: 日志记录器
        """
        self._log = logger or logging.getLogger("server.ecdh")

        self._port = int(port)
        self._running = False

        # 服务端 ECDH 密钥对 (注意: 不每个客户端换, 所有客户端使用同一个)
        self._public_key, self._private_key = _generate_ecdh_keypair()
        self._log.info("服务端 ECDH 密钥对已生成 (P-256)")

        self._sock = None
        self._accept_thread = None
        self._handler_threads = []
        self._handler_lock = threading.Lock()

    @property
    def public_key(self):
        """服务端 ECDH 公钥 (Base64)"""
        return self._public_key

    def start(self):
        """启动信令服务器"""
        if self._running:
            return

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        set_reuse_addr(self._sock)
        self._sock.bind(("0.0.0.0", self._port))
        self._sock.listen(32)
        self._sock.settimeout(0.2)  # 非阻塞 accept

        self._running = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="server-ecdh-accept", daemon=True,
        )
        self._accept_thread.start()
        self._log.info("ECDH 信令服务器已启动: 0.0.0.0:%s", self._port)

    def stop(self):
        """停止信令服务器"""
        self._running = False
        if self._accept_thread and self._accept_thread.is_alive():
            self._accept_thread.join(timeout=2)
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass

        with self._handler_lock:
            for t in self._handler_threads:
                if t.is_alive():
                    t.join(timeout=2)
        self._log.info("ECDH 信令服务器已停止")

    def _accept_loop(self):
        """接受连接循环"""
        while self._running:
            if self._sock is None:
                break
            try:
                client_sock, addr = self._sock.accept()
            except (socket.timeout, BlockingIOError):
                continue
            except Exception:
                if self._running:
                    continue
                break

            client_ip = addr[0]
            t = threading.Thread(
                target=self._handle_handshake,
                args=(client_sock, client_ip),
                name=f"ecdh-handler-{client_ip}",
                daemon=True,
            )
            t.start()
            with self._handler_lock:
                self._handler_threads.append(t)
                self._handler_threads = [h for h in self._handler_threads if h.is_alive()]

    def _handle_handshake(self, sock, client_ip):
        """处理单个客户端的 ECDH 握手请求

        流程:
          1. 接收 DEVICE_HELLO
          2. 提取客户端公钥
          3. 计算 ECDH 共享密钥, 存入 ServerPeerKey
          4. 回复 DEVICE_HELLO_ACK

        Args:
            sock: 已连接的 TCP 套接字
            client_ip: 客户端 IP 地址
        """
        try:
            sock.settimeout(5)  # 5 秒超时

            # 1. 接收 DEVICE_HELLO
            msg = self._recv_json(sock)
            if msg is None:
                return

            if msg.get("type") != MSG_DEVICE_HELLO:
                self._log.debug("收到非握手消息: %s", msg.get("type"))
                return

            # 2. 提取客户端公钥
            remote_public = msg.get("public_key", "")
            if not remote_public:
                self._log.warning("DEVICE_HELLO 未包含客户端公钥")
                return

            # 3. 计算 ECDH 共享密钥
            shared = _compute_ecdh_shared(self._private_key, remote_public)
            if shared is None or len(shared) != 32:
                self._log.error("ECDH 共享密钥计算失败: %s", client_ip)
                return

            # 存储密钥 (用于后续加密数据通信)
            ServerPeerKey.store(client_ip, shared)
            self._log.info("ECDH 握手成功: %s", client_ip)

            # 4. 回复 DEVICE_HELLO_ACK (携带服务端公钥)
            ack = {
                "type": MSG_DEVICE_HELLO_ACK,
                "public_key": self._public_key,
            }
            self._send_json(sock, ack)

        except socket.timeout:
            self._log.debug("ECDH 握手超时: %s", client_ip)
        except Exception as e:
            self._log.debug("ECDH 握手异常: %s - %s", client_ip, e)
        finally:
            try:
                sock.close()
            except Exception:
                pass

    # ─── 底层收发 ───

    @staticmethod
    def _send_json(sock, msg_dict):
        """发送 JSON 消息: [4B 大端长度][JSON UTF-8]"""
        body = json.dumps(msg_dict, ensure_ascii=False).encode("utf-8")
        length = struct.pack("!I", len(body))
        sock.sendall(length + body)

    @staticmethod
    def _recv_json(sock):
        """接收 JSON 消息"""
        try:
            len_bytes = EcdhSignalingServer._recv_exact(sock, 4)
        except Exception:
            return None

        body_len = struct.unpack("!I", len_bytes)[0]
        if body_len > MAX_MSG_SIZE:
            return None

        try:
            body = EcdhSignalingServer._recv_exact(sock, body_len)
        except Exception:
            return None

        try:
            return json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    @staticmethod
    def _recv_exact(sock, n):
        """精确读取 n 字节"""
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("连接已关闭")
            data += chunk
        return data
