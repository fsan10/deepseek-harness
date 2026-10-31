from __future__ import annotations

from apps.ai_analysis.crypto import SecretCipher


class UserPasswordCipher:
    """Encrypt user passwords reversibly for the explicitly authorized view flow.

    Login still uses the one-way bcrypt hash.  The ciphertext is only a
    server-side recovery aid and is bound to the user id through AES-GCM
    authenticated data, so it cannot be moved to another account silently.
    """

    def __init__(self, cipher: SecretCipher | None = None):
        self._cipher = cipher

    def _get_cipher(self) -> SecretCipher:
        if self._cipher is None:
            self._cipher = SecretCipher()
        return self._cipher

    @staticmethod
    def _context(user_id: int) -> str:
        return f"iam:user-password:{int(user_id)}"

    def encrypt(self, password: str, user_id: int) -> tuple[bytes, bytes]:
        return self._get_cipher().encrypt(password, context=self._context(user_id))

    def decrypt(self, ciphertext: bytes, nonce: bytes, user_id: int) -> str:
        return self._get_cipher().decrypt(ciphertext, nonce, context=self._context(user_id))
