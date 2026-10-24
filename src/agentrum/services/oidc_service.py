"""OIDC/OAuth2 SSO.

Two provider modes, selected by config:
- `generic`: standard OIDC with discovery + id_token verification via JWKS
  (works with Keycloak, Okta, Casdoor, Authelia, Logto, ...)
- `feishu`: Feishu's OAuth2 + userinfo flow (authorize → token v2 → user_info)

Users are linked by (idp_provider, idp_subject) and provisioned on first
login (JIT). Local accounts remain for bootstrap/CI.
"""

import logging
import time
import uuid as uuid_mod
from urllib.parse import urlencode

import httpx
from authlib.jose import JsonWebKey, JsonWebToken
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import audit, errors
from agentrum.auth import security
from agentrum.config import get_settings
from agentrum.db import models

logger = logging.getLogger("agentrum.oidc")

FEISHU_AUTHORIZE = "https://accounts.feishu.cn/open-ids/authenticate"
FEISHU_TOKEN = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
FEISHU_USERINFO = "https://open.feishu.cn/open-apis/authen/v1/user_info"

_discovery_cache: dict[str, tuple[float, dict]] = {}


def enabled_providers() -> list[str]:
    settings = get_settings()
    out = []
    if settings.feishu_app_id and settings.feishu_app_secret:
        out.append("feishu")
    if (
        settings.oidc_generic_issuer
        and settings.oidc_generic_client_id
        and settings.oidc_generic_client_secret
    ):
        out.append("generic")
    return out


def provider_config(provider: str) -> dict:
    settings = get_settings()
    if provider == "feishu":
        if not (settings.feishu_app_id and settings.feishu_app_secret):
            raise errors.NotFoundError("feishu SSO is not configured")
        return {
            "mode": "oauth2-userinfo",
            "authorize_url": FEISHU_AUTHORIZE,
            "token_url": FEISHU_TOKEN,
            "userinfo_url": FEISHU_USERINFO,
            "client_id": settings.feishu_app_id,
            "client_secret": settings.feishu_app_secret,
            "scopes": [],
        }
    if provider == "generic":
        if not (
            settings.oidc_generic_issuer
            and settings.oidc_generic_client_id
            and settings.oidc_generic_client_secret
        ):
            raise errors.NotFoundError("generic OIDC is not configured")
        return {
            "mode": "oidc",
            "issuer": settings.oidc_generic_issuer,
            "client_id": settings.oidc_generic_client_id,
            "client_secret": settings.oidc_generic_client_secret,
            "scopes": settings.oidc_generic_scopes.split(),
        }
    raise errors.NotFoundError(f"unknown SSO provider {provider!r}")


def redirect_uri(provider: str) -> str:
    return f"{get_settings().oidc_redirect_base.rstrip('/')}/v1/auth/oidc/{provider}/callback"


def make_state(provider: str, nonce: str) -> str:
    import jwt

    settings = get_settings()
    payload = {
        "p": provider,
        "n": nonce,
        "exp": int(time.time()) + 600,
        "typ": "state",  # distinct from session tokens sharing this key
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def read_state(state: str, provider: str) -> str:
    import jwt

    settings = get_settings()
    try:
        payload = jwt.decode(state, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise errors.PermissionDeniedError("invalid SSO state") from exc
    if payload.get("typ") != "state":
        raise errors.PermissionDeniedError("invalid SSO state")
    if payload.get("p") != provider:
        raise errors.PermissionDeniedError("SSO state provider mismatch")
    return payload["n"]


async def _discovery(issuer: str) -> dict:
    cached = _discovery_cache.get(issuer)
    now = time.time()
    if cached and now - cached[0] < 3600:
        return cached[1]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{issuer.rstrip('/')}/.well-known/openid-configuration")
        resp.raise_for_status()
        doc = resp.json()
    _discovery_cache[issuer] = (now, doc)
    return doc


async def build_authorize_url(provider: str, nonce: str) -> str:
    cfg = provider_config(provider)
    params: dict = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri(provider),
        "response_type": "code",
        "state": make_state(provider, nonce),
        "nonce": nonce,
    }
    if cfg.get("scopes"):
        params["scope"] = " ".join(cfg["scopes"])
    return f"{cfg['authorize_url']}?{urlencode(params)}"


async def exchange_code(provider: str, code: str) -> dict:
    cfg = provider_config(provider)
    if cfg["mode"] == "oidc":
        doc = await _discovery(cfg["issuer"])
        token_url = doc["token_endpoint"]
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(provider),
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
        }
    else:
        token_url = cfg["token_url"]
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(provider),
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
        }
    async with httpx.AsyncClient(timeout=15) as client:
        # RFC 6749: the token endpoint takes form-encoded bodies; strict IdPs
        # reject JSON.
        resp = await client.post(token_url, data=data)
        resp.raise_for_status()
        body = resp.json()
    if cfg["mode"] == "oauth2-userinfo" and isinstance(body.get("data"), dict):
        return body["data"]  # Feishu wraps tokens in {"code":0,"data":{...}}
    return body


async def fetch_identity(provider: str, tokens: dict, nonce: str | None = None) -> dict:
    """Return {subject, username, display_name, email}."""
    cfg = provider_config(provider)
    if cfg["mode"] == "oidc":
        doc = await _discovery(cfg["issuer"])
        id_token = tokens.get("id_token")
        if not id_token:
            raise errors.PermissionDeniedError("IdP returned no id_token")
        async with httpx.AsyncClient(timeout=10) as client:
            jwks_resp = await client.get(doc["jwks_uri"])
            jwks_resp.raise_for_status()
        key_set = JsonWebKey().import_key_set(jwks_resp.json())
        claims = JsonWebToken(["RS256", "ES256"]).decode(
            id_token, key_set,
            claims_options={
                # Pin the issuer to the configured value, not just presence.
                "iss": {"essential": True, "value": cfg["issuer"]},
                "aud": {"essential": True, "value": cfg["client_id"]},
            },
        )
        claims.validate(now=time.time(), leeway=60)
        # The id_token must be bound to the authorization request that asked
        # for it (nonce round-trip).
        if nonce is not None and claims.get("nonce") != nonce:
            raise errors.PermissionDeniedError("id_token nonce mismatch")
        return {
            "subject": claims["sub"],
            "username": claims.get("preferred_username") or claims.get("email", "").split("@")[0],
            "display_name": claims.get("name"),
            "email": claims.get("email"),
        }
    # Feishu: opaque access_token → userinfo API
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            cfg["userinfo_url"],
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        resp.raise_for_status()
        body = resp.json()
    data = body.get("data", body)
    subject = data.get("union_id") or data.get("open_id")
    if not subject:
        raise errors.PermissionDeniedError("Feishu userinfo returned no subject")
    return {
        "subject": subject,
        "username": data.get("en_name") or data.get("name"),
        "display_name": data.get("name"),
        "email": None,
    }


def _sanitize_username(raw: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in (raw or "").lower())
    return cleaned.strip("-")[:48] or "user"


async def login_or_signup(
    session: AsyncSession, provider: str, identity: dict, source_ip: str | None = None
) -> tuple[models.User, bool]:
    user = (
        await session.execute(
            select(models.User).where(
                models.User.idp_provider == provider,
                models.User.idp_subject == identity["subject"],
            )
        )
    ).scalar_one_or_none()
    if user is not None:
        return user, False

    base = _sanitize_username(identity.get("username") or f"{provider}-{identity['subject'][:8]}")
    username = base
    for i in range(1, 50):
        taken = (
            await session.execute(select(models.User).where(models.User.username == username))
        ).scalar_one_or_none()
        if taken is None:
            break
        username = f"{base}-{i}"
    user = models.User(
        username=username,
        # random unusable password; identity comes from the IdP
        password_hash=security.hash_password(uuid_mod.uuid4().hex + uuid_mod.uuid4().hex),
        display_name=identity.get("display_name"),
        idp_provider=provider,
        idp_subject=identity["subject"],
    )
    session.add(user)
    await audit.record(
        session, actor=None, action="user.oidc_create",
        detail={"provider": provider, "username": username}, source_ip=source_ip,
    )
    try:
        await session.commit()
    except IntegrityError:
        # Concurrent JIT signup for the same identity: whoever lost the race
        # re-reads the winner instead of 500ing.
        await session.rollback()
        user = (
            await session.execute(
                select(models.User).where(
                    models.User.idp_provider == provider,
                    models.User.idp_subject == identity["subject"],
                )
            )
        ).scalar_one_or_none()
        if user is None:
            raise errors.ConflictError(
                "SSO identity registration raced; please retry"
            ) from None
        return user, False
    await session.refresh(user)
    logger.info("provisioned SSO user %r from %s", username, provider)
    return user, True
