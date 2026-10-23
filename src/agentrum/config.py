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


@lru_cache
def get_settings() -> Settings:
    return Settings()
