from pydantic import BaseModel


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ApiTokenCreateIn(BaseModel):
    name: str
    # None → server default (config: api_token_default_expire_days).
    expires_in_days: int | None = None


class ApiTokenOut(BaseModel):
    id: str
    name: str
    created_at: str
    last_used_at: str | None = None
    expires_at: str | None = None
    revoked_at: str | None = None


class ApiTokenCreatedOut(ApiTokenOut):
    token: str  # plaintext, returned exactly once


class TeamRoleOut(BaseModel):
    name: str
    role: str


class MeOut(BaseModel):
    id: str
    username: str
    display_name: str | None
    is_platform_admin: bool
    teams: list[TeamRoleOut]
