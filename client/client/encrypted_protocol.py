"""
AES-GCM 加密通信协议模块
=======================
实现客户端与服务器之间的 AES-256-GCM 加密 TCP 数据流协议。

有线格式规范 (与 net/p2p_transfer/common/protocol.py 兼容):
═══════════════════════════════════════════════════════════════════════
  加密 JSON 消息格式:
    [4 字节大端 加密数据总长度][12 字节随机IV][密文][16 字节 GCM Tag]

  其中:
    加密数据总长度 = 12 + len(明文) + 16
    IV 为每消息随机生成的 12 字节 nonce
    GCM Tag 为 16 字节认证标签, 提供完整性校验

  注意: 数据通道使用 1 字节类型标记区分消息类型, 但本协议简化:
    只用作加密 JSON 传输, 故使用无标记的信令通道格式.
═══════════════════════════════════════════════════════════════════════

加密流程:
  1. 构建 JSON 消息 (如出入库记录)
  2. 从 PeerKey 获取与服务器 IP 对应的共享密钥 (无密钥则拒绝发送)
  3. AES-256-GCM 加密 JSON 字节串
  4. 组装有线格式: [4B总长][12B IV][密文][16B GCM Tag]
  5. 通过 TCP 发送

解密流程:
  1. 读取 4 字节大端长度前缀, 获取加密数据总长度
  2. 读取完整的加密数据块
  3. 从 PeerKey 获取密钥, AES-256-GCM 解密
  4. 解析 JSON
"""

import socket
import struct
import json
import logging

from client.crypto_utils import aes_gcm_encrypt, aes_gcm_decrypt
from client.peer_key import PeerKey


# 消息长度前缀格式: 大端 4 字节无符号整数 "!I"
LENGTH_PREFIX_FMT = struct.Struct("!I")
# 最大加密消息总长度 (10MB 明文 + 28 字节加密开销)
MAX_ENCRYPTED_LENGTH = 10 * 1024 * 1024 + 28


class ConnectionClosedError(RuntimeError):
    """远端关闭连接异常"""
    pass


class ProtocolError(ValueError):
    """协议格式错误异常"""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# 底层可靠收发
# ═══════════════════════════════════════════════════════════════════════════════

def _recv_exact(sock, n):
    """从套接字精确读取 n 字节 (循环直到凑满或对端关闭)

    Args:
        sock: TCP 套接字
        n: 需要读取的字节数

    Returns:
        读取到的 bytes

    Raises:
        ConnectionClosedError: 对端关闭连接
    """
    data = b""
    while len(data) < n:
        try:
            chunk = sock.recv(n - len(data))
        except InterruptedError:
            continue
        except socket.timeout:
            raise ConnectionClosedError("接收超时")
        except BlockingIOError:
            raise ConnectionClosedError("recv would block")
        if not chunk:
            raise ConnectionClosedError("连接已关闭")
        data += chunk
    return data


def _send_all(sock, data):
    """将全部数据写入套接字 (循环 send 直到全部发出)

    Args:
        sock: TCP 套接字
        data: 要发送的 bytes

    Raises:
        ConnectionError: 发送失败
    """
    sent = 0
    while sent < len(data):
        try:
            n = sock.send(data[sent:])
        except (BlockingIOError, InterruptedError):
            continue
        if n < 0:
            raise ConnectionError("发送失败")
        sent += n


# ═══════════════════════════════════════════════════════════════════════════════
# 加密消息收发
# ═══════════════════════════════════════════════════════════════════════════════

def send_encrypted_message(sock, msg_dict, server_ip):
    """发送 AES-256-GCM 加密的 JSON 消息

    消息必须先序列化为 JSON 再加密发送。
    需要先完成 ECDH 握手 (PeerKey 中存在 server_ip 的密钥)。

    有线格式:
      [4字节大端 加密总长][12字节IV][AES-GCM密文][16字节GCM Tag]

    Args:
        sock: 已连接的 TCP 套接字
        msg_dict: 要发送的字典消息 (将 json.dumps 后加密)
        server_ip: 服务器 IP 地址 (用于查找 AES 密钥)

    Returns:
        True 发送成功

    Raises:
        RuntimeError: 未找到服务器密钥 (ECDH 未完成)
        ConnectionError: 网络发送失败
    """
    # 1. 查找共享密钥
    key = PeerKey.get(server_ip)
    if key is None:
        raise RuntimeError(f"未找到与服务器 {server_ip} 的共享密钥, 请先完成 ECDH 握手")

    # 2. 序列化 JSON → bytes
    body = json.dumps(msg_dict, ensure_ascii=False).encode("utf-8")

    # 3. AES-256-GCM 加密
    encrypted = aes_gcm_encrypt(body, key)

    # 4. 组装有线格式: [4B长度][加密数据块]
    length_prefix = LENGTH_PREFIX_FMT.pack(len(encrypted))
    _send_all(sock, length_prefix + encrypted)
    return True


def recv_encrypted_message(sock, server_ip):
    """接收 AES-256-GCM 加密的 JSON 消息

    先读取 4 字节长度前缀获取加密数据总长度, 读取加密块后解密并解析 JSON。
    GCM Tag 自动验证, 篡改/伪造的密文将被拒绝。

    有线格式输入:
      [4字节大端 加密总长][12字节IV][AES-GCM密文][16字节GCM Tag]

    Args:
        sock: 已连接的 TCP 套接字
        server_ip: 服务器 IP 地址 (用于查找 AES 密钥)

    Returns:
        解析后的字典消息

    Raises:
        ConnectionClosedError: 连接已关闭
        ProtocolError: 解密失败或 JSON 解析失败
        RuntimeError: 未找到服务器密钥
    """
    key = PeerKey.get(server_ip)
    if key is None:
        raise RuntimeError(f"未找到与服务器 {server_ip} 的共享密钥, 请先完成 ECDH 握手")

    # 1. 读取长度前缀
    try:
        len_bytes = _recv_exact(sock, LENGTH_PREFIX_FMT.size)
    except ConnectionClosedError:
        raise

    total_len = LENGTH_PREFIX_FMT.unpack(len_bytes)[0]
    if total_len > MAX_ENCRYPTED_LENGTH:
        raise ProtocolError(f"加密消息长度超限: {total_len} > {MAX_ENCRYPTED_LENGTH}")

    # 2. 读取加密数据块
    raw_data = _recv_exact(sock, total_len)

    # 3. AES-256-GCM 解密
    plaintext = aes_gcm_decrypt(raw_data, key)
    if plaintext is None:
        raise ProtocolError("AES-GCM 解密失败, 密钥不匹配或数据被篡改")

    # 4. 解析 JSON
    try:
        return json.loads(plaintext.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ProtocolError(f"JSON 解析失败: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# 应用层消息构造
# ═══════════════════════════════════════════════════════════════════════════════

def build_inventory_request(record_time, person, action, items):
    """构造出入库记录请求消息 INVENTORY_RECORD

    与旧协议 (server/server/tcp_protocol.py validate_inventory_payload) 兼容.

    Args:
        record_time: 操作时间字符串 (ISO 8601 格式)
        person: 操作人姓名
        action: 操作类型 "入库" 或 "出库"
        items: 物资列表 [{"name": "cboard", "quantity": 2}, ...]

    Returns:
        字典格式的 INVENTORY_RECORD 请求消息
    """
    return {
        "type": "inventory_record",
        "time": record_time,
        "person": person,
        "action": action,
        "items": items,
    }
