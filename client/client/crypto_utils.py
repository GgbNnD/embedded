"""
ECDH 密钥协商 与 AES-256-GCM 加解密工具模块
==============================================
从 net/p2p_transfer/common/utils.py 提取并适配。
在 RK3399Pro 板端(client)与远端服务器(server)之间实现:
  - ECDH P-256 (secp256r1) 密钥交换
  - AES-256-GCM 认证加密/解密

ECDH 流程:
  1. 双方各自生成密钥对 (generate_ecdh_keypair)
  2. 交换公钥 (通过 TCP 信令通道)
  3. 各自计算共享密钥 (compute_ecdh_shared)
  4. 共享密钥直接作为 AES-256 密钥使用 (32字节, 无哈希)

AES-256-GCM 有线格式:
  [12字节随机IV][密文(与明文等长)][16字节GCM Tag]
"""

import os
import base64

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# ═══════════════════════════════════════════════════════════════════════════════
# ECDH 密钥协商 (secp256r1 / NIST P-256)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_ecdh_keypair():
    """生成 ECDH 密钥对 (secp256r1 曲线 / NIST P-256)

    公私钥均以 DER 格式编码后再 Base64 编码, 与 C++ 实现(OpenSSL EVP_PKEY_derive)有线兼容.

    Returns:
        (公钥Base64字符串, 私钥Base64字符串)
        公钥: DER SubjectPublicKeyInfo 格式, Base64
        私钥: DER PKCS8 格式, Base64
    """
    # 生成本地 secp256r1 私钥
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    # 公钥导出为 DER SubjectPublicKeyInfo 格式
    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    # 私钥导出为 DER PKCS8 格式 (无密码保护)
    private_der = private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    # Base64 编码后返回
    return (
        base64.b64encode(public_der).decode(),
        base64.b64encode(private_der).decode(),
    )


def compute_ecdh_shared(local_private_b64, remote_public_b64):
    """计算 ECDH 共享密钥

    使用本地私钥和远端公钥执行 ECDH 密钥交换, 输出 32 字节原始共享密钥,
    直接用作 AES-256 密钥 (不进行哈希处理).

    Args:
        local_private_b64: 本地 ECDH 私钥 (Base64 编码的 DER PKCS8 格式)
        remote_public_b64: 远端 ECDH 公钥 (Base64 编码的 DER SubjectPublicKeyInfo 格式)

    Returns:
        32 字节共享密钥 bytes, 失败返回 None
    """
    try:
        # 解码 Base64 → DER 字节
        private_der = base64.b64decode(local_private_b64)
        public_der = base64.b64decode(remote_public_b64)

        # 从 DER 加载密钥对象
        private_key = serialization.load_der_private_key(private_der, password=None)
        peer_public_key = serialization.load_der_public_key(public_der)

        # 执行 ECDH 密钥交换 (兼容 cryptography 新旧版本 API)
        try:
            shared = private_key.exchange(ec.ECDH(), peer_public_key)
        except TypeError:
            # 新版 cryptography 不再需要 ec.ECDH() 参数
            shared = private_key.exchange(peer_public_key)

        return shared  # 32 字节原始共享密钥
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# AES-256-GCM 对称认证加密
# ═══════════════════════════════════════════════════════════════════════════════

def aes_gcm_encrypt(plaintext, key):
    """使用 AES-256-GCM 对明文进行认证加密

    GCM 模式同时提供机密性和完整性保护, 每条消息使用随机 IV.
    攻击者无法篡改密文而不被检测 (GCM Tag 验证失败).

    Args:
        plaintext: 要加密的原始数据 bytes
        key: 32 字节 AES-256 密钥 (由 ECDH 协商产生)

    Returns:
        有线格式字节串: [12字节随机IV][密文][16字节GCM Tag]
    """
    iv = os.urandom(12)  # 每条消息生成随机 12 字节 nonce
    aesgcm = AESGCM(key)
    # encrypt() 返回 ciphertext || tag (密文后附加 16 字节 GCM 认证标签)
    ct_with_tag = aesgcm.encrypt(iv, plaintext, None)
    return iv + ct_with_tag


def aes_gcm_decrypt(data, key):
    """使用 AES-256-GCM 对密文进行认证解密

    Args:
        data: 有线格式字节串 [12字节IV][密文][16字节GCM Tag]
        key: 32 字节 AES-256 密钥

    Returns:
        解密后的明文 bytes, 若 GCM Tag 验证失败(数据被篡改或密钥不匹配)返回 None
    """
    # 最小有效长度 = 12(IV) + 0(空密文) + 16(Tag) = 28 字节
    if len(data) < 28:
        return None

    iv = data[:12]            # 前 12 字节为随机 IV
    ct_with_tag = data[12:]   # 剩余部分为 密文 || GCM Tag
    aesgcm = AESGCM(key)

    try:
        # decrypt() 验证 GCM Tag 并解密, 失败抛异常
        return aesgcm.decrypt(iv, ct_with_tag, None)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Base64 编解码工具
# ═══════════════════════════════════════════════════════════════════════════════

def b64_decode(s):
    """Base64 字符串解码为原始字节"""
    return base64.b64decode(s)


def b64_encode(data):
    """原始字节编码为 Base64 字符串"""
    return base64.b64encode(data).decode()
