"""Credential encryption using Fernet."""
from __future__ import annotations
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _derive_key(secret: str) -> bytes:
    if not secret:
        secret = "ai-seo-autopilot-default-key-change-me"
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet() -> Fernet:
    secret = ""
    try:
        secret = current_app.config.get("CREDENTIAL_ENCRYPTION_KEY", "")
    except RuntimeError:
        pass
    if not secret:
        import os
        secret = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "")
    return Fernet(_derive_key(secret))


def encrypt(plaintext: str) -> str:
    if plaintext is None:
        return ""
    return get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def mask(value: str, visible: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return value[:visible] + "*" * (len(value) - visible)