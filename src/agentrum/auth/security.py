"""Password hashing, JWT session tokens and API token generation."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from agentrum.config import get_settings

API_TOKEN_PREFIX = "ark_"

# Token-type claims separate session JWTs from OIDC state JWTs (both are
# signed with secret_key); decode refuses anything that is not a session.
_TOKEN_TYPE_SESSION = "session"

_password_hasher = PasswordHash.recommended()

# Argon2 hash of an unguessable random value: verifying against it keeps the
# timing of "unknown username" logins close to "known username, wrong
# password", closing the enumeration side channel.
_DUMMY_HASH = _password_hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hasher.verify(password, password_hash)


def dummy_verify(password: str) -> None:
    """Burn roughly the same CPU as a real password check (user enumeration
    timing defense; the result is always False)."""
    _password_hasher.verify(password, _DUMMY_HASH)


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "typ": _TOKEN_TYPE_SESSION,
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> tuple[uuid.UUID, datetime | None]:
    """Return (user_id, issued_at). Raises ValueError for anything that is
    not a valid, non-expired *session* token (including OIDC state JWTs)."""
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        if payload.get("typ") != _TOKEN_TYPE_SESSION:
            raise ValueError("invalid or expired token")
        return uuid.UUID(payload["sub"]), _parse_iat(payload.get("iat"))
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid or expired token") from exc


def _parse_iat(value: object) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    return None


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
