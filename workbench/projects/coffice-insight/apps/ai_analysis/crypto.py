from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ConfigurationError(RuntimeError):
    """AI服务安全配置缺失或不合法。"""


class SecretCipher:
    ENV_NAME = "AI_CONFIG_ENCRYPTION_KEY"

    def __init__(self, key: bytes | None = None):
        if key is None:
            encoded = os.environ.get(self.ENV_NAME, "").strip()
            if not encoded:
                raise ConfigurationError(
                    f"未配置{self.ENV_NAME}；请提供url-safe base64编码的32字节随机密钥"
                )
            try:
                key = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            except (ValueError, TypeError) as exc:
                raise ConfigurationError(f"{self.ENV_NAME}不是有效的base64密钥") from exc
        if len(key) != 32:
            raise ConfigurationError(f"{self.ENV_NAME}解码后必须恰好为32字节")
        self._cipher = AESGCM(key)

    def encrypt(self, secret: str, *, context: str) -> tuple[bytes, bytes]:
        if not isinstance(secret, str) or not secret:
            raise ValueError("密钥不能为空")
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(nonce, secret.encode("utf-8"), context.encode("utf-8"))
        return ciphertext, nonce

    def decrypt(self, ciphertext: bytes | memoryview, nonce: bytes | memoryview, *, context: str) -> str:
        if isinstance(ciphertext, memoryview):
            ciphertext = ciphertext.tobytes()
        if isinstance(nonce, memoryview):
            nonce = nonce.tobytes()
        return self._cipher.decrypt(bytes(nonce), bytes(ciphertext), context.encode("utf-8")).decode("utf-8")

    @staticmethod
    def mask(secret: str | None) -> str:
        if not secret:
            return "未配置"
        suffix = secret[-4:] if len(secret) >= 4 else "****"
        return f"****{suffix}"

    @staticmethod
    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii")

    @staticmethod
    def decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value.encode("ascii"))
