from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet
from hypothesis import given
from hypothesis import strategies as st

from app.core import crypto
from app.core.config import get_settings


def test_roundtrip_simple() -> None:
    crypto.reset_cache()
    token = crypto.encrypt("hello-secret")
    assert token != "hello-secret"
    assert crypto.decrypt(token) == "hello-secret"


def test_decrypt_with_wrong_key_fails() -> None:
    crypto.reset_cache()
    token = crypto.encrypt("payload")

    other_key = Fernet.generate_key().decode("utf-8")
    original_key = os.environ["APP_ENCRYPTION_KEY"]
    os.environ["APP_ENCRYPTION_KEY"] = other_key
    get_settings.cache_clear()
    crypto.reset_cache()
    try:
        with pytest.raises(crypto.DecryptionError):
            crypto.decrypt(token)
    finally:
        os.environ["APP_ENCRYPTION_KEY"] = original_key
        get_settings.cache_clear()
        crypto.reset_cache()


def test_missing_key_raises() -> None:
    original_key = os.environ.pop("APP_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    crypto.reset_cache()
    try:
        with pytest.raises(crypto.EncryptionKeyMissingError):
            crypto.encrypt("anything")
    finally:
        if original_key:
            os.environ["APP_ENCRYPTION_KEY"] = original_key
        get_settings.cache_clear()
        crypto.reset_cache()


@given(st.text(min_size=0, max_size=512))
def test_roundtrip_property(plaintext: str) -> None:
    crypto.reset_cache()
    assert crypto.decrypt(crypto.encrypt(plaintext)) == plaintext
