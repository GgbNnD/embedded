"""
ECDH 共享密钥存储模块
===================
从 net/p2p_transfer/common/peer_key.py 适配。
全局、线程安全的 IP 地址 → AES-256 共享密钥映射表。

在 ECDH 握手完成后, 将服务器的 IP 地址与计算出的 32 字节 AES-256 密钥关联存储。
后续 TCP 通信时自动查询此表决定是否加密。

使用场景:
  - ecdh_handler.py:  ECDH 握手成功后调用 store() 存储密钥
  - encrypted_protocol.py: 发送/接收消息时调用 get() 查询密钥以决定是否加密
  - discovery.py:  服务器离线时调用 remove() 清理密钥
"""

import threading


class PeerKey:
    """线程安全的对端 ECDH 共享密钥存储

    使用类级别静态字典 + Lock 实现线程安全.
    密钥是 ECDH 输出的原始 32 字节, 直接用作 AES-256-GCM 密钥.

    典型用法:
        PeerKey.store("192.168.1.50", shared_secret_bytes)
        key = PeerKey.get("192.168.1.50")
        if key:
            encrypted = aes_gcm_encrypt(data, key)
    """

    # 类级别线程锁 (保护 _secrets 字典的并发访问)
    _lock = threading.Lock()
    # IP 地址字符串 → 32 字节 AES 密钥 的映射表
    _secrets = {}

    @classmethod
    def store(cls, ip, shared_secret):
        """存储某个 IP 地址的共享密钥

        若该 IP 已有旧密钥, 将被新密钥覆盖 (密钥更新).

        Args:
            ip: 远端服务器 IP 地址字符串, 如 "192.168.1.50"
            shared_secret: 32 字节 ECDH 共享密钥 bytes
        """
        with cls._lock:
            cls._secrets[ip] = shared_secret

    @classmethod
    def get(cls, ip):
        """获取某个 IP 地址的共享密钥

        Args:
            ip: 远端服务器 IP 地址字符串

        Returns:
            32 字节 AES 密钥 bytes, 若无密钥则返回 None
        """
        with cls._lock:
            return cls._secrets.get(ip)

    @classmethod
    def has(cls, ip):
        """检查是否已持有某个 IP 地址的共享密钥

        Args:
            ip: 远端服务器 IP 地址字符串

        Returns:
            True 表示已与该 IP 完成 ECDH 握手
        """
        with cls._lock:
            return ip in cls._secrets

    @classmethod
    def remove(cls, ip):
        """删除某个 IP 地址的密钥记录

        当服务器离线或需要重新握手时调用.

        Args:
            ip: 远端服务器 IP 地址字符串
        """
        with cls._lock:
            cls._secrets.pop(ip, None)

    @classmethod
    def clear(cls):
        """清空所有密钥记录 (用于服务关闭时清理)"""
        with cls._lock:
            cls._secrets.clear()
