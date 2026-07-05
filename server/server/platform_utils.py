"""
服务端网络平台工具模块
=====================
与 client/platform_utils.py 功能相同, 供 server 模块使用.
提供 IP 地址枚举、主网卡选择、非阻塞切换等基础网络操作.
"""

import socket
import struct
import errno
import fcntl
import os


SOCKET_ERR = (errno.EWOULDBLOCK, errno.EAGAIN, errno.EINPROGRESS)


def get_local_ips():
    """获取本机所有非回环 IPv4 地址"""
    ips = []
    try:
        import netifaces
        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface)
            if netifaces.AF_INET in addrs:
                for addr in addrs[netifaces.AF_INET]:
                    ip = addr.get("addr", "")
                    if ip and not ip.startswith("127."):
                        ips.append(ip)
        if ips:
            return ips
    except ImportError:
        pass
    try:
        import subprocess
        import re
        output = subprocess.check_output(
            ["ip", "-4", "addr", "show"], text=True, timeout=3
        )
        for line in output.splitlines():
            m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", line)
            if m:
                ip = m.group(1)
                if not ip.startswith("127."):
                    ips.append(ip)
        if ips:
            return ips
    except Exception:
        pass
    return ["127.0.0.1"]


def select_local_ip():
    """选择本机主网卡 IPv4 地址"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 53))
        ip = s.getsockname()[0]
        s.close()
        if ip and ip != "0.0.0.0":
            return ip
    except Exception:
        pass
    ips = get_local_ips()
    return ips[0] if ips else "127.0.0.1"


def set_nonblocking(sock):
    fd = sock.fileno()
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def set_blocking(sock):
    fd = sock.fileno()
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)


def set_reuse_addr(sock):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


def is_would_block(err):
    return err in SOCKET_ERR
