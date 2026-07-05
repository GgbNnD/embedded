"""
服务端 AES-GCM 加密通信协议模块
===============================
与 client/encrypted_protocol.py 对应的服务端实现。

有线格式 (与客户端一致):
  [4 字节大端 加密数据总长度][12 字节随机IV][密文][16 字节 GCM Tag]

服务端角色:
  - 接收客户端发来的加密 JSON 消息 (如 INVENTORY_RECORD)
  - AES-256-GCM 解密 → 验证 GCM Tag → 解析 JSON
  - 处理业务逻辑 (写入 CSV)
  - 构造 JSON 响应 → AES-256-GCM 加密 → 发送回客户端

消息类型:
  - 客户端 → 服务端: INVENTORY_RECORD (出入库记录)
  - 服务端 → 客户端: ACK (ok=True/False)

安全特性:
  - 每条消息使用唯一的随机 IV (12 字节, 防止重放攻击)
  - GCM Tag 提供完整性校验 (篡改或伪造的密文被自动拒绝)
  - 密钥由 ECDH 握手产生, 不在网络上传输
"""

import os
import socket
import struct
import json
import logging

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from server.discovery_handlers import ServerPeerKey


# 长度前缀格式: 大端 4 字节
LENGTH_PREFIX = struct.Struct("!I")
# 最大加密消息长度
MAX_ENCRYPTED_LEN = 10 * 1024 * 1024 + 28

# 最小 AES-GCM 数据块大小: 12(IV) + 0(空) + 16(Tag) = 28 字节
MIN_GCM_BLOCK = 28


class ConnectionClosedError(RuntimeError):
    """远端关闭连接"""
    pass


class ProtocolError(ValueError):
    """协议错误"""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# AES-256-GCM 加解密 (服务端版)
# ═══════════════════════════════════════════════════════════════════════════════

def aes_gcm_encrypt(plaintext, key):
    """AES-256-GCM 加密

    Args:
        plaintext: 明文字节
        key: 32 字节 AES 密钥

    Returns:
        [12B IV][密文][16B GCM Tag] 格式字节串
    """
    iv = os.urandom(12)
    aesgcm = AESGCM(key)
    ct_with_tag = aesgcm.encrypt(iv, plaintext, None)
    return iv + ct_with_tag


def aes_gcm_decrypt(data, key):
    """AES-256-GCM 解密

    Args:
        data: [12B IV][密文][16B GCM Tag]
        key: 32 字节 AES 密钥

    Returns:
        解密后的明文字节, 失败返回 None
    """
    if len(data) < MIN_GCM_BLOCK:
        return None
    iv = data[:12]
    ct_with_tag = data[12:]
    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(iv, ct_with_tag, None)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 底层收发
# ═══════════════════════════════════════════════════════════════════════════════

def _recv_exact(sock, n):
    """精确读取 n 字节 (循环)"""
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
    """发送全部字节 (循环)"""
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

def recv_encrypted_message(sock, client_ip):
    """接收 AES-256-GCM 加密的 JSON 消息 (服务端)

    流程:
      1. 读取 4 字节大端长度 → 获取加密数据总长度
      2. 读取加密数据块
      3. 根据 client_ip 从 ServerPeerKey 获取密钥
      4. AES-GCM 解密 → 验证 Tag
      5. 解析 JSON → 返回

    Args:
        sock: TCP 套接字
        client_ip: 客户端 IP (用于查找密钥)

    Returns:
        解密后的字典, 失败返回 None

    Raises:
        ConnectionClosedError: 连接关闭
        ProtocolError: 协议格式错误
    """
    # 1. 查找共享密钥
    key = ServerPeerKey.get(client_ip)
    if key is None:
        raise ProtocolError(f"未找到与客户端 {client_ip} 的共享密钥 (ECDH 握手尚未完成)")

    # 2. 读取长度前缀
    len_bytes = _recv_exact(sock, LENGTH_PREFIX.size)
    total_len = LENGTH_PREFIX.unpack(len_bytes)[0]
    if total_len > MAX_ENCRYPTED_LEN:
        raise ProtocolError(f"加密消息超限: {total_len} > {MAX_ENCRYPTED_LEN}")

    # 3. 读取加密数据块
    raw_data = _recv_exact(sock, total_len)

    # 4. 解密
    plaintext = aes_gcm_decrypt(raw_data, key)
    if plaintext is None:
        raise ProtocolError("AES-GCM 解密失败: 密钥不匹配或数据被篡改")

    # 5. 解析 JSON
    try:
        return json.loads(plaintext.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ProtocolError(f"JSON 解析失败: {e}")


def send_encrypted_message(sock, msg_dict, client_ip):
    """发送 AES-256-GCM 加密的 JSON 消息 (服务端 → 客户端)

    Args:
        sock: TCP 套接字
        msg_dict: 待发送的字典消息
        client_ip: 客户端 IP (用于查找密钥)

    Raises:
        RuntimeError: 未找到客户端的共享密钥
    """
    key = ServerPeerKey.get(client_ip)
    if key is None:
        raise RuntimeError(f"未找到与客户端 {client_ip} 的共享密钥")

    body = json.dumps(msg_dict, ensure_ascii=False).encode("utf-8")
    encrypted = aes_gcm_encrypt(body, key)

    length = LENGTH_PREFIX.pack(len(encrypted))
    _send_all(sock, length + encrypted)


# ═══════════════════════════════════════════════════════════════════════════════
# 应用层消息构造
# ═══════════════════════════════════════════════════════════════════════════════

def make_ack_response(ok, message="", data=None):
    """构造 ACK 响应消息

    Args:
        ok: True/False 表示操作是否成功
        message: 人类可读的消息
        data: 附加数据 (如写入的 CSV 行数)

    Returns:
        dict 格式的响应消息
    """
    response = {
        "ok": ok,
        "type": "inventory_ack",
    }
    if message:
        response["message"] = message
    if data:
        response["data"] = data
    return response


def make_error_ack(message, data=None):
    """构造错误 ACK 响应"""
    return make_ack_response(False, message, data)


def make_success_ack(message="", data=None):
    """构造成功 ACK 响应"""
    return make_ack_response(True, message, data)
