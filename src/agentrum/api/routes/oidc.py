"""OIDC/OAuth2 login endpoints."""

import secrets as pysecrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import errors
from agentrum.auth import security
from agentrum.auth.deps import client_ip
from agentrum.config import get_settings
from agentrum.db.engine import get_session
from agentrum.services import oidc_service

router = APIRouter(prefix="/v1/auth/oidc", tags=["auth"])

_STATE_COOKIE = "ark_oidc_state"


@router.get("/providers", response_model=list[str])
async def list_providers() -> list[str]:
    return oidc_service.enabled_providers()


@router.get("/{provider}/login")
async def sso_login(provider: str, request: Request) -> RedirectResponse:
    if provider not in oidc_service.enabled_providers():
        raise errors.NotFoundError(f"SSO provider {provider!r} is not configured")
    nonce = pysecrets.token_urlsafe(24)
    state = oidc_service.make_state(provider, nonce)
    url = await oidc_service.build_authorize_url(provider, nonce)
    response = RedirectResponse(url, status_code=307)
    response.set_cookie(
        _STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return response


@router.get("/{provider}/callback")
async def sso_callback(
    provider: str,
    code: str = "",
    state: str = "",
    request: Request = None,  # type: ignore[assignment]
    session: AsyncSession = Depends(get_session),
):
    if provider not in oidc_service.enabled_providers():
        raise errors.NotFoundError(f"SSO provider {provider!r} is not configured")
    cookie_state = request.cookies.get(_STATE_COOKIE)  # type: ignore[union-attr]
    if not cookie_state or cookie_state != state:
        raise errors.PermissionDeniedError("SSO state mismatch")
    nonce = oidc_service.read_state(state, provider)

    tokens = await oidc_service.exchange_code(provider, code)
    identity = await oidc_service.fetch_identity(provider, tokens, nonce=nonce)
    user, created = await oidc_service.login_or_signup(
        session, provider, identity,
        source_ip=client_ip(request),
    )
    if user.disabled_at is not None:
        raise errors.PermissionDeniedError("account is disabled")

    token = security.create_access_token(user.id)
    if get_settings().ui_origin:
        # Fragment, not query: the token must not land in browser history,
        # access logs or Referer headers.
        response = RedirectResponse(
            f"{get_settings().ui_origin.rstrip('/')}/"
            f"#token={token}&login={'new' if created else 'ok'}",
            status_code=302,
        )
        response.delete_cookie(_STATE_COOKIE, path="/")
        return response
    return JSONResponse(
        {
            "access_token": token,
            "token_type": "bearer",
            "created": created,
            "user": {
                "id": str(user.id),
                "username": user.username,
                "display_name": user.display_name,
                "is_platform_admin": user.is_platform_admin,
            },
        }
    )
