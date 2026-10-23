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


@lru_cache
def get_settings() -> Settings:
    return Settings()
