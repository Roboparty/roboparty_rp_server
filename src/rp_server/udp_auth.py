# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""UDP 认证模块 — challenge-response + 随机Token"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("rp_server.udp.auth")


@dataclass
class TokenInfo:
    """Token 信息"""
    device_id: str
    expires_at: float  # Unix 时间戳


class UDPAuthenticator:
    """UDP 认证管理器"""

    def __init__(self, secret_key: str = "", token_ttl: int = 3600):
        """
        Args:
            secret_key: HMAC-SHA256 密钥，为空则自动生成
            token_ttl: Token 有效期（秒）
        """
        self._secret_key = secret_key or os.environ.get("RP_UDP_SECRET", "")
        if not self._secret_key:
            self._secret_key = secrets.token_hex(32)
            logger.warning("未配置 UDP secret_key，已自动生成随机密钥")

        self._token_ttl = token_ttl
        # addr_key → (challenge_code, timestamp)
        self._challenges: dict[str, tuple[str, float]] = {}
        # token → TokenInfo
        self._tokens: dict[str, TokenInfo] = {}

    def generate_challenge(self, addr: tuple[str, int], device_id: str) -> str:
        """生成挑战码

        Args:
            addr: 客户端地址 (host, port)
            device_id: 设备ID

        Returns:
            32字符随机十六进制挑战码
        """
        challenge_code = secrets.token_hex(16)  # 32字符
        addr_key = f"{addr[0]}:{addr[1]}"
        self._challenges[addr_key] = (challenge_code, time.time())
        logger.info("生成挑战码: device=%s addr=%s", device_id, addr_key)
        return challenge_code

    def verify_signature(
        self, addr: tuple[str, int], device_id: str, signature: str
    ) -> Optional[str]:
        """验证签名并生成Token

        Args:
            addr: 客户端地址
            device_id: 设备ID
            signature: HMAC-SHA256 签名（十六进制）

        Returns:
            JWT Token，验证失败返回 None
        """
        addr_key = f"{addr[0]}:{addr[1]}"

        # 获取挑战码
        challenge_data = self._challenges.get(addr_key)
        if not challenge_data:
            logger.warning("未找到挑战码: addr=%s", addr_key)
            return None

        challenge_code, timestamp = challenge_data

        # 检查挑战码是否过期（5分钟）
        if time.time() - timestamp > 300:
            logger.warning("挑战码已过期: addr=%s", addr_key)
            del self._challenges[addr_key]
            return None

        # 计算期望的签名 (格式: "deviceId:challengeCode")
        sign_input = f"{device_id}:{challenge_code}"
        expected_signature = hmac.new(
            self._secret_key.encode("utf-8"),
            sign_input.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # 调试日志：对比签名
        logger.info("签名对比: device=%s", device_id)
        logger.info("  签名输入: %s", sign_input)
        logger.info("  客户端签名: %s", signature.lower())
        logger.info("  服务端签名: %s", expected_signature.lower())
        logger.info("  密钥: %s", self._secret_key[:10] + "...")

        # 验证签名
        if not hmac.compare_digest(signature.lower(), expected_signature.lower()):
            logger.warning("签名验证失败: device=%s addr=%s", device_id, addr_key)
            return None

        # 清除已使用的挑战码
        del self._challenges[addr_key]

        # 生成 Token
        token = self._generate_token(device_id)
        logger.info("认证成功: device=%s addr=%s", device_id, addr_key)
        return token

    def _generate_token(self, device_id: str) -> str:
        """生成随机 Token

        Args:
            device_id: 设备ID

        Returns:
            64字符十六进制 Token
        """
        # 生成32字节随机数据 → 64字符十六进制
        token = secrets.token_hex(32)

        # 存储到内存
        expires_at = time.time() + self._token_ttl
        self._tokens[token] = TokenInfo(
            device_id=device_id,
            expires_at=expires_at,
        )

        logger.debug("生成 Token: device=%s expires_at=%.0f", device_id, expires_at)
        return token

    def verify_token(self, token: str) -> Optional[dict]:
        """验证 Token

        Args:
            token: Token 字符串

        Returns:
            包含 device_id 的字典，验证失败返回 None
        """
        token_info = self._tokens.get(token)
        if not token_info:
            logger.debug("Token 不存在")
            return None

        if time.time() > token_info.expires_at:
            logger.debug("Token 已过期")
            del self._tokens[token]
            return None

        return {"sub": token_info.device_id}

    def revoke_token(self, token: str) -> None:
        """撤销 Token"""
        self._tokens.pop(token, None)

    def cleanup_expired_tokens(self) -> int:
        """清理过期的 Token"""
        now = time.time()
        expired = [t for t, info in self._tokens.items() if now > info.expires_at]
        for t in expired:
            del self._tokens[t]
        if expired:
            logger.debug("清理过期 Token: %d 个", len(expired))
        return len(expired)

    def cleanup_expired(self, max_age: float = 300.0) -> int:
        """清理过期的挑战码和 Token

        Args:
            max_age: 挑战码最大存活时间（秒）

        Returns:
            清理数量
        """
        # 清理过期挑战码
        now = time.time()
        expired_challenges = [
            addr_key
            for addr_key, (_, timestamp) in self._challenges.items()
            if now - timestamp > max_age
        ]
        for addr_key in expired_challenges:
            del self._challenges[addr_key]

        # 清理过期 Token
        expired_tokens = self.cleanup_expired_tokens()

        total = len(expired_challenges) + expired_tokens
        if total:
            logger.debug("清理过期数据: 挑战码 %d 个, Token %d 个",
                        len(expired_challenges), expired_tokens)
        return total
