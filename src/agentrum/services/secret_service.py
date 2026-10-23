"""Secret resources: envelope encryption at rest, values never returned.

The master key comes from ARK_SECRET_ENCRYPTION_KEY (a Fernet key). When
unset, one is derived from ARK_SECRET_KEY — fine for development, loudly
discouraged in production.
"""

import base64
import hashlib
import logging
import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import errors
from agentrum.config import get_settings
from agentrum.db import models

logger = logging.getLogger("agentrum.secrets")
_fernet = None
_warned = False


def _get_fernet():
    global _fernet, _warned
    if _fernet is not None:
        return _fernet
    from cryptography.fernet import Fernet

    settings = get_settings()
    if settings.secret_encryption_key:
        key = settings.secret_encryption_key.encode()
    else:
        if not _warned:
            logger.warning(
                "ARK_SECRET_ENCRYPTION_KEY not set: deriving the secret-encryption key "
                "from ARK_SECRET_KEY. Set a dedicated key before production use!"
            )
            _warned = True
        digest = hashlib.sha256(settings.secret_key.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    _fernet = Fernet(key)
    return _fernet


def encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


async def set_payloads(session: AsyncSession, resource_id: uuid.UUID, data: dict[str, str]) -> None:
    """Replace the encrypted payload for a Secret resource."""
    await session.execute(sa_delete(models.SecretPayload).where(models.SecretPayload.resource_id == resource_id))
    for key, value in data.items():
        session.add(
            models.SecretPayload(
                resource_id=resource_id, key=key, ciphertext=encrypt(value)
            )
        )


async def get_payloads(session: AsyncSession, resource_id: uuid.UUID) -> dict[str, str]:
    rows = (
        await session.execute(
            select(models.SecretPayload).where(models.SecretPayload.resource_id == resource_id)
        )
    ).scalars().all()
    return {row.key: decrypt(row.ciphertext) for row in rows}


async def resolve_env(
    session: AsyncSession, env_entries: list[dict], default_namespace: str
) -> dict[str, str]:
    """Resolve a spec's env list (value or valueFrom.secretRef) into plain
    key/values. Used by the deployment controller."""
    from agentrum.services.resource_service import _get_resource

    resolved: dict[str, str] = {}
    for entry in env_entries or []:
        name = entry.get("name")
        if not name:
            raise errors.ValidationError("env entry missing 'name'")
        if entry.get("value") is not None:
            resolved[name] = entry["value"]
            continue
        ref = entry.get("value_from") or {}
        namespace = ref.get("namespace") or default_namespace
        secret = await _get_resource(session, "Secret", namespace, ref.get("name", ""))
        if secret is None:
            raise errors.ValidationError(
                f"secretRef {namespace}/{ref.get('name')!r} not found"
            )
        payloads = await get_payloads(session, secret.id)
        key = ref.get("key")
        if key not in payloads:
            raise errors.ValidationError(f"secret {namespace}/{ref.get('name')} has no key {key!r}")
        resolved[name] = payloads[key]
    return resolved
