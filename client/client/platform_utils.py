"""
平台相关网络工具模块
===================
从 net/p2p_transfer/common/platform.py 提取并适配。
提供 RK3399Pro 板端(arm64 Linux)所需的基础网络操作:

功能:
  - 枚举本机所有非回环 IPv4 地址
  - 自动选择主网卡 IP (UDP connect 技巧)
  - 非阻塞/阻塞模式切换
  - SO_REUSEADDR 设置
  - 可恢复网络错误判断
"""

import socket
import struct
import errno
import fcntl
import os


# 可恢复的网络错误码:
#   EWOULDBLOCK - 非阻塞套接字无数据可读/写
#   EAGAIN      - 与 EWOULDBLOCK 等值(Linux下), 资源暂时不可用
#   EINPROGRESS - 非阻塞 connect() 正在连接中(必须纳入判断)
SOCKET_ERR = (errno.EWOULDBLOCK, errno.EAGAIN, errno.EINPROGRESS)


def get_local_ips():
    """获取本机所有非回环 IPv4 地址列表

    优先使用 netifaces 库, 若未安装则调用 ip 命令解析输出,
    最终回退到 127.0.0.1.
    在 RK3399Pro (aarch64 Linux) 上 netifaces 可用, ip 命令也可用.

    Returns:
        IP 地址字符串列表, 至少包含 "127.0.0.1"
    """
    ips = []

    # 方案 1: 使用 netifaces 库 (最可靠的跨平台方案)
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

    # 方案 2: 调用 ip 命令解析输出 (Linux 通用回退方案, 3秒超时防止卡死)
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

    # 方案 3: 所有方案都失败, 返回回环地址
    return ["127.0.0.1"]


def select_local_ip():
    """选择本机主网卡 IPv4 地址

    使用 UDP connect 技巧: 创建一个临时 UDP 套接字, 尝试连接到
    1.1.1.1:53 (Cloudflare DNS, 不会实际发送数据), 通过 getsockname()
    获取内核路由选择出的源 IP 地址, 即为主网卡 IP.

    连接失败时回退到 get_local_ips() 的第一个结果.

    Returns:
        本机局域网 IP 地址字符串, 如 "192.168.1.100"
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 连接到外部地址, 触发内核路由选择, 不发送实际数据
        s.connect(("1.1.1.1", 53))
        ip = s.getsockname()[0]
        s.close()
        if ip and ip != "0.0.0.0":
            return ip
    except Exception:
        pass

    # 回退: 取第一个枚举到的非回环 IP
    ips = get_local_ips()
    return ips[0] if ips else "127.0.0.1"


def set_nonblocking(sock):
    """将套接字设置为非阻塞模式 (设置 O_NONBLOCK 标志)"""
    fd = sock.fileno()
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def set_blocking(sock):
    """将套接字恢复为阻塞模式 (清除 O_NONBLOCK 标志)"""
    fd = sock.fileno()
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)


def set_reuse_addr(sock):
    """设置 SO_REUSEADDR 选项, 允许端口复用和快速重启"""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


def is_would_block(err):
    """判断 errno 值是否为可恢复的"会阻塞"错误

    包括 EWOULDBLOCK, EAGAIN (资源暂时不可用), EINPROGRESS (连接进行中).
    用于非阻塞 socket 操作后的错误处理.

    Returns:
        True 表示可恢复, 稍后重试; False 表示真正的错误
    """
    return err in SOCKET_ERR
