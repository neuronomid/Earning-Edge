from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class EncryptionKeyMissingError(RuntimeError):
    pass


class DecryptionError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = get_settings().app_encryption_key
    if not key:
        raise EncryptionKeyMissingError(
            "APP_ENCRYPTION_KEY is not set. Generate one with `Fernet.generate_key()`."
        )
    return Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    if plaintext is None:
        raise ValueError("plaintext must not be None")
    token = _fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError("ciphertext could not be decrypted with the configured key") from exc


def generate_key() -> str:
    return Fernet.generate_key().decode("utf-8")


def reset_cache() -> None:
    _fernet.cache_clear()
