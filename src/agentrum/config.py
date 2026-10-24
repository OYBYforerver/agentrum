from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration (prefix: ARK_)."""

    model_config = SettingsConfigDict(env_prefix="ARK_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://agentrum:agentrum@localhost:5433/agentrum"
    secret_key: str = "dev-insecure-change-me"
    access_token_expire_minutes: int = 480
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin123"

    # Security hardening
    allowed_origins: str = "*"  # comma-separated list; "*" allows all (dev only)
    max_body_bytes: int = 2 * 1024 * 1024  # 2 MiB cap for request bodies
    log_format: str = "console"  # "console" or "json"

    # Login throttling (per-process; Redis-backed global limiting comes in Phase B)
    login_max_per_window: int = 10
    login_window_seconds: int = 60
    lockout_threshold: int = 5
    lockout_seconds: int = 600

    # Notifications (transactional outbox + background dispatcher)
    feishu_webhook_url: str | None = None  # Feishu custom bot webhook
    feishu_webhook_secret: str | None = None  # optional signing key
    notification_webhook_url: str | None = None  # generic webhook, HMAC-signed
    notification_webhook_secret: str | None = None
    notification_interval_seconds: int = 10

    # Secrets at rest: 32-byte url-safe base64 key (Fernet). Falls back to a
    # key derived from secret_key with a loud warning when unset.
    secret_encryption_key: str | None = None

    # OIDC SSO. Generic provider uses discovery (issuer URL); Feishu is a
    # built-in preset using its OAuth2 + userinfo endpoints.
    oidc_generic_issuer: str | None = None
    oidc_generic_client_id: str | None = None
    oidc_generic_client_secret: str | None = None
    oidc_generic_scopes: str = "openid profile email"
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    oidc_redirect_base: str = "http://localhost:12122"

    # Deployment controller (Phase B)
    deploy_interval_seconds: int = 10
    # Comma-separated image registry prefixes allowed for deployment, e.g.
    # "registry.internal/,ghcr.io/acme/". Empty means allow-all (dev only).
    image_allowlist: str = ""
    ui_origin: str | None = None  # where OIDC callbacks redirect with the token

    # Probes & maintenance
    probe_interval_seconds: int = 60
    audit_retention_days: int = 180
    notification_retention_days: int = 30
    skill_drift_interval_seconds: int = 300  # git-sourced skill upstream check (0 disables)

    # Bundled handbook (built mkdocs site); mounted at /handbook when set
    docs_dir: str | None = None

    # OpenTelemetry tracing (OTLP HTTP exporter), disabled by default
    otel_enabled: bool = False
    otel_endpoint: str = "http://localhost:4318/v1/traces"


@lru_cache
def get_settings() -> Settings:
    return Settings()
