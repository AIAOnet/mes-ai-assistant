"""Small signed-cookie authentication layer for the learning dashboard."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass


COOKIE_NAME = "mes_session"


def secure_cookie_enabled() -> bool:
    return os.getenv("MES_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class User:
    username: str
    role: str


def configured_users() -> dict[str, tuple[str, str]]:
    users: dict[str, tuple[str, str]] = {}
    for role, prefix in (
        ("admin", "MES_ADMIN"), ("operator", "MES_OPERATOR"),
        ("maintenance", "MES_MAINTENANCE"), ("engineer", "MES_ENGINEER"),
        ("manager", "MES_MANAGER"), ("viewer", "MES_VIEWER"),
    ):
        username = os.getenv(f"{prefix}_USERNAME", "").strip()
        password = os.getenv(f"{prefix}_PASSWORD", "")
        if username and password:
            users[username] = (password, role)
    return users


def authenticate(username: str, password: str) -> User | None:
    record = configured_users().get(username)
    if record is None or not hmac.compare_digest(record[0], password):
        return None
    return User(username, record[1])


def _secret() -> bytes:
    return os.getenv("MES_DASHBOARD_SECRET", "").encode("utf-8")


def create_session(user: User, timeout_minutes: int) -> str:
    payload = {"sub": user.username, "role": user.role, "exp": int(time.time()) + timeout_minutes * 60}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
    signature = hmac.new(_secret(), encoded, hashlib.sha256).digest()
    return f"{encoded.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def read_session(token: str | None) -> User | None:
    if not token or not _secret():
        return None
    try:
        encoded_text, signature_text = token.split(".", 1)
        encoded = encoded_text.encode()
        expected = hmac.new(_secret(), encoded, hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
        if not hmac.compare_digest(expected, supplied):
            return None
        payload = json.loads(base64.urlsafe_b64decode(encoded_text + "=" * (-len(encoded_text) % 4)))
        if int(payload["exp"]) <= int(time.time()):
            return None
        return User(str(payload["sub"]), str(payload["role"]))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
