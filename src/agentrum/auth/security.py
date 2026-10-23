"""Password hashing, JWT session tokens and API token generation."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from agentrum.config import get_settings

API_TOKEN_PREFIX = "ark_"

_password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hasher.verify(password, password_hash)


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise ValueError("invalid or expired token") from exc
    return uuid.UUID(payload["sub"])


def hash_api_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def new_api_token() -> tuple[str, str]:
    """Return (plaintext_token, stored_hash). The plaintext is shown once."""
    raw = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_api_token(raw)


def new_access_key() -> tuple[str, str, str]:
    """Return (access_key, plaintext_secret, stored_secret_hash)."""
    ak = "ark-ak-" + secrets.token_hex(8)
    sk = "ark-sk-" + secrets.token_urlsafe(24)
    return ak, sk, hash_api_token(sk)
