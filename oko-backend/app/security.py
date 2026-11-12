"""Пароли и JWT-токены. Только стандартная библиотека + PyJWT."""
import hashlib
import hmac
import os
from datetime import timedelta
from typing import Optional

import jwt

from . import config
from .logic import utcnow

ALGO = "HS256"
PBKDF2_ITERATIONS = 120_000


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2$%d$%s$%s" % (PBKDF2_ITERATIONS, salt.hex(), digest.hex())


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


def make_token(user_id: int, username: str, role: str, display_name: str) -> str:
    now = utcnow()
    payload = {
        "sub": str(user_id), "username": username, "role": role, "name": display_name,
        "iat": int(now.timestamp()), "exp": int((now + timedelta(hours=config.TOKEN_TTL_HOURS)).timestamp()),
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm=ALGO)


def read_token(token: str) -> Optional[dict]:
    """None, если токен недействителен или просрочен."""
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=[ALGO])
    except jwt.PyJWTError:
        return None
