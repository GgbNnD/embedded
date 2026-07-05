"""
UDP 组播设备发现模块
==================
从 net/p2p_transfer/discovery/device_discovery.py 提取并适配为 client 专用版本。

在 RK3399Pro 板端(client端)实现:
  - 定期通过 UDP 组播发送 DEVICE_BROADCAST 心跳广播, 宣告自身存在
  - 监听组播地址, 发现服务器的广播消息
  - 自动获取服务器 IP 和通信端口

组播参数:
  - 组播地址: 239.255.255.250 (本地管理范围)
  - 发现端口: 8888 (UDP)
  - 广播间隔: 3 秒

协议流程:
  1. Client 每 3 秒广播: {"type":"DEVICE_BROADCAST","device_id":"...","device_name":"...","ip":"...","port":8889,"timestamp":...}
  2. Server 也广播相同格式消息 (但 device_name 不同, 如 "inventory_server")
  3. Client 收到 Server 的广播后, 提取其 IP 和信令端口
  4. Client 用此信息发起 TCP ECDH 握手连接
"""

import socket
import struct
import json
import threading
import time
import logging

from client.platform_utils import set_reuse_addr, get_local_ips, select_local_ip

# ═══════════════════════════════════════════════════════════════════════════════
# 常量定义
# ═══════════════════════════════════════════════════════════════════════════════

# UDP 组播设备发现端口
DISCOVERY_PORT = 8888
# TCP 信令控制端口 (ECDH 握手)
SIGNALING_PORT = 8889
# TCP 加密数据通道端口 (传递出入库记录)
DATA_PORT = 8890
# 广播间隔, 每 3 秒发送一次 DEVICE_BROADCAST
BROADCAST_INTERVAL = 3
# 组播地址 (本地管理范围)
MULTICAST_ADDR = "239.255.255.250"
# 设备离线超时 (秒)
DEVICE_TIMEOUT = 10


class ServerDiscovery:
    """UDP 组播服务器发现客户端

    启动后创建两个后台守护线程:
      - _send_loop: 每 3 秒发送 DEVICE_BROADCAST 宣告自身存在
      - _recv_loop: 持续监听组播消息, 发现服务器并触发回调

    发现的服务器信息通过 on_server_found 回调通知上层:
      callback(server_ip, server_port_of_signaling)

    典型用法:
        discovery = ServerDiscovery("client_001", "rk3399pro_001")
        discovery.set_on_server_found(my_handler)
        discovery.start()
        # ... 程序运行 ...
        discovery.stop()
    """

    def __init__(self, device_id, device_name, port=DISCOVERY_PORT):
        """初始化服务器发现服务

        Args:
            device_id: 本机唯一标识 (如 UUID 字符串)
            device_name: 本机显示名称 (如 "rk3399pro_inventory_001")
            port: UDP 监听端口, 默认 8888
        """
        self._log = logging.getLogger("client.discovery")

        self._device_id = device_id
        self._device_name = device_name
        self._port = int(port)
        self._running = False

        # 套接字与线程
        self._sock = None
        self._send_thread = None
        self._recv_thread = None

        # 自动选择主网卡 IP
        self._local_ip = select_local_ip()

        # 服务器信息缓存: {(ip, port): last_seen_timestamp}
        self._servers = {}
        self._servers_lock = threading.Lock()

        # 发现服务器的回调
        self._on_server_found = None
        self._on_server_lost = None

    # ─── 回调设置 ───

    def set_on_server_found(self, callback):
        """设置发现服务器的回调函数 callback(server_ip, signaling_port, data_port)

        Args:
            callback: 回调函数, 接收 (ip:str, signaling_port:int, data_port:int) 三个参数
        """
        self._on_server_found = callback

    def set_on_server_lost(self, callback):
        """设置服务器离线的回调函数 callback(server_ip)

        Args:
            callback: 回调函数, 接收 (ip:str) 一个参数
        """
        self._on_server_lost = callback

    # ─── 属性 ───

    @property
    def local_ip(self):
        """本机局域网 IP 地址"""
        return self._local_ip

    @property
    def local_port(self):
        """本机信令端口"""
        return SIGNALING_PORT

    # ─── 生命周期 ───

    def start(self):
        """启动发现服务: 创建 UDP 套接字并启动发送/接收线程"""
        if self._running:
            return

        self._sock = self._create_socket()
        self._running = True
        self._send_thread = threading.Thread(target=self._send_loop, name="discovery-send", daemon=True)
        self._recv_thread = threading.Thread(target=self._recv_loop, name="discovery-recv", daemon=True)
        self._send_thread.start()
        self._recv_thread.start()
        self._log.info("UDP 设备发现服务已启动, 本机 IP=%s, 组播=%s:%s",
                       self._local_ip, MULTICAST_ADDR, self._port)

    def stop(self):
        """停止发现服务: 发送离线通知, 关闭套接字, 等待线程退出"""
        if not self._running:
            return
        self._running = False

        # 尽力发送 3 次 DEVICE_OFFLINE 通知 (UDP 不可靠)
        offline_msg = json.dumps({
            "type": "DEVICE_OFFLINE",
            "device_id": self._device_id,
        }).encode("utf-8")
        for _ in range(3):
            try:
                if self._sock:
                    self._sock.sendto(offline_msg, (MULTICAST_ADDR, self._port))
            except Exception:
                pass

        # 关闭套接字以唤醒阻塞在 recvfrom 的接收线程
        sock = self._sock
        self._sock = None
        if sock:
            try:
                sock.close()
            except Exception:
                pass

        # 等待线程退出
        for t in (self._send_thread, self._recv_thread):
            if t and t.is_alive():
                t.join(timeout=2)
        self._log.info("UDP 设备发现服务已停止")

    def get_servers(self):
        """获取当前在线的服务器列表

        Returns:
            list of (ip, signaling_port, data_port) 元组
        """
        cutoff = time.time() - DEVICE_TIMEOUT
        with self._servers_lock:
            return [
                (ip, sp, dp) for (ip, sp, dp), ts in self._servers.items()
                if ts >= cutoff
            ]

    # ─── 内部实现 ───

    def _create_socket(self):
        """创建并配置 UDP 组播套接字

        配置流程:
          1. UDP 套接字 + SO_REUSEADDR (允许多个进程共享端口)
          2. 绑定到 0.0.0.0:port (接收所有接口的数据包)
          3. 加入组播组 (IP_ADD_MEMBERSHIP)
          4. 为每个非回环网卡独立加入组播组 (多网卡兼容)
          5. 组播 TTL = 64 (限制在局域网内)
          6. 指定组播出口接口为主网卡 IP
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        set_reuse_addr(sock)
        sock.bind(("0.0.0.0", self._port))

        # 加入组播组: IP_ADD_MEMBERSHIP 参数 = (组播地址, 本地接口IP)
        # 0.0.0.0 表示内核自动选择默认接口
        mreq = struct.pack(
            "!4s4s",
            socket.inet_aton(MULTICAST_ADDR),
            socket.inet_aton("0.0.0.0"),
        )
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        # 为所有非回环网卡单独加入组播组 (多网卡兼容, 如 eth0 + wifi)
        for ip in get_local_ips():
            if ip != self._local_ip and not ip.startswith("127."):
                try:
                    mreq2 = struct.pack(
                        "!4s4s",
                        socket.inet_aton(MULTICAST_ADDR),
                        socket.inet_aton(ip),
                    )
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq2)
                except Exception:
                    pass

        # 组播 TTL = 64, 限制在同一局域网内 (不跨路由器)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack("B", 64))

        # 指定组播出口接口 (关键: 确保数据包从主网卡发出)
        try:
            sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_MULTICAST_IF,
                socket.inet_aton(self._local_ip),
            )
        except Exception:
            pass

        return sock

    def _send_loop(self):
        """发送线程: 定期向组播组广播 DEVICE_BROADCAST

        每条广播包含本机信息: device_id, device_name, IP, 信令端口(8889).
        休眠以 100ms 为单位分段执行, 确保 stop() 信号响应延迟不超过 100ms.
        """
        while self._running:
            # 构造 DEVICE_BROADCAST 消息
            msg = json.dumps({
                "type": "DEVICE_BROADCAST",
                "device_id": self._device_id,
                "device_name": self._device_name,
                "ip": self._local_ip,
                "port": SIGNALING_PORT,      # 告知服务器: 用信令端口 8889 连接我
                "data_port": DATA_PORT,        # 告知服务器: 数据在端口 8890
                "timestamp": time.time(),
            }).encode("utf-8")

            try:
                if self._sock:
                    self._sock.sendto(msg, (MULTICAST_ADDR, self._port))
            except Exception:
                pass

            # 分段休眠以响应停止信号 (每 100ms 检查一次 _running)
            for _ in range(int(BROADCAST_INTERVAL * 10)):
                if not self._running:
                    break
                time.sleep(0.1)

    def _recv_loop(self):
        """接收线程: 持续监听组播消息, 发现服务器

        对每一条收到的 DEVICE_BROADCAST 消息:
          1. 用数据包的源 IP 覆盖 JSON 中的 ip 字段 (更可靠, 避免 NAT/误配置)
          2. 忽略本机发出的消息 (通过 device_id 比对)
          3. 检查是否为 server 类型的设备
          4. 触发 on_server_found 回调
        """
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

            # 解析 JSON 消息
            try:
                msg = json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            msg_type = msg.get("type", "")

            if msg_type == "DEVICE_OFFLINE":
                # 设备离线通知
                sender_id = msg.get("device_id", "")
                sender_ip = addr[0]
                if sender_id != self._device_id:
                    with self._servers_lock:
                        to_remove = [(k, sender_ip) for k in list(self._servers.keys()) if k[0] == sender_ip]
                        for k, _ in to_remove:
                            self._servers.pop(k, None)
                    if self._on_server_lost:
                        self._on_server_lost(sender_ip)
                continue

            if msg_type != "DEVICE_BROADCAST":
                continue

            # 提取发送方信息
            sender_id = msg.get("device_id", "")
            sender_name = msg.get("device_name", "")
            # 使用数据包的源 IP (比 JSON 中的 ip 字段更可靠)
            sender_ip = addr[0]
            sender_port = msg.get("port", SIGNALING_PORT)
            sender_data_port = msg.get("data_port", DATA_PORT)
            timestamp = msg.get("timestamp", time.time())

            # 忽略本机发出的广播 (通过 device_id 比对)
            if sender_id == self._device_id:
                continue

            # 更新服务器信息缓存
            server_key = (sender_ip, sender_port, sender_data_port)
            with self._servers_lock:
                is_new_server = server_key not in self._servers
                self._servers[server_key] = timestamp

            # 发现新服务器时触发回调
            if is_new_server and self._on_server_found:
                self._log.info("发现服务器: %s (%s) @ %s, 信令端口=%s, 数据端口=%s",
                               sender_name, sender_id, sender_ip, sender_port, sender_data_port)
                self._on_server_found(sender_ip, sender_port, sender_data_port)
