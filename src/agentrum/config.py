from functools import lru_cache
from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration (prefix: ARK_)."""

    model_config = SettingsConfigDict(env_prefix="ARK_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://agentrum:agentrum@localhost:5433/agentrum"
    secret_key: str = "dev-insecure-change-me"
    access_token_expire_minutes: int = 480
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin123"
    # Escape hatch for local dev / CI: permits the default secret_key and the
    # admin123 bootstrap password. Never set in production.
    allow_insecure: bool = False

    # Security hardening
    allowed_origins: str = "*"  # comma-separated list; "*" allows all (dev only)
    max_body_bytes: int = 2 * 1024 * 1024  # 2 MiB cap for request bodies
    log_format: str = "console"  # "console" or "json"
    # Serve the built console (Next.js static export) from this directory.
    ui_dir: str | None = None
    metrics_enabled: bool = True

    # Credentials lifecycle. API tokens default to a one-year expiry and can
    # never outlive api_token_max_expire_days.
    api_token_default_expire_days: int = 365
    api_token_max_expire_days: int = 3650
    access_key_max_expire_days: int = 3650
    # Trust this reverse-proxy header for client IPs (e.g. "X-Forwarded-For");
    # only enable when the proxy chain actually overwrites it.
    client_ip_header: str | None = None

    # Login throttling. Counters live per-process unless a shared backend is
    # configured below — multi-replica deployments should set
    # ratelimit_backend=redis so windows and lockouts are global.
    login_max_per_window: int = 10
    login_window_seconds: int = 60
    lockout_threshold: int = 5
    lockout_seconds: int = 600
    # Failures per username across all source IPs — raises the bar for
    # lockout-DoS against a victim behind a shared egress IP.
    lockout_username_threshold: int = 20
    # Shared rate-limit counters: "memory" (default, per-process) or "redis"
    # (global across replicas; requires the `agentrum[redis]` extra). If Redis
    # is unreachable the limiters fail open (allow + loud warning) so a
    # backend outage cannot take down logins entirely.
    ratelimit_backend: str = "memory"
    ratelimit_redis_url: str | None = None

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
    # Skill publishing: remote git resolution gets this many seconds before
    # the request fails, so a hanging remote cannot pin a DB transaction.
    git_timeout_seconds: int = 30
    # Content delivery: tarballs larger than this are refused (protects the
    # pod from a maliciously huge "skill" repository).
    skill_content_max_bytes: int = 50 * 1024 * 1024
    # Disk cache TTL for built tarballs keyed by (git url, pinned sha) — the
    # content of a version is immutable, so repeat downloads skip the clone.
    # 0 disables the cache.
    skill_content_cache_seconds: int = 600

    # Probes & maintenance
    probe_interval_seconds: int = 60
    probe_tls_verify: bool = True  # disable only for self-signed test endpoints
    audit_retention_days: int = 180
    notification_retention_days: int = 30
    # Soft-deleted resources live in the recycle bin for this long; the
    # retention prune then removes them for good (versions and secret
    # payloads cascade at the database level).
    resource_retention_days: int = 30
    skill_drift_interval_seconds: int = 300  # git-sourced skill upstream check (0 disables)

    # Egress guard for server-initiated requests (git clone/ls-remote, health
    # probes, skill content delivery). Publishers control these destinations,
    # so the registry must not be aimable at itself, in-cluster services or
    # cloud metadata. Private ranges stay reachable by default (internal git
    # registries are the norm); loopback/link-local are blocked unless
    # explicitly allowed. file:// git sources work only when explicitly
    # enabled (local development / test fixtures).
    egress_allow_private_addresses: bool = True
    egress_allow_loopback: bool = False
    egress_allow_file_sources: bool = False

    # Bundled handbook (built mkdocs site); mounted at /handbook when set
    docs_dir: str | None = None

    # OpenTelemetry tracing (OTLP HTTP exporter), disabled by default
    otel_enabled: bool = False
    otel_endpoint: str = "http://localhost:4318/v1/traces"


    DEFAULT_SECRET_KEY: ClassVar[str] = "dev-insecure-change-me"
    DEFAULT_BOOTSTRAP_PASSWORD: ClassVar[str] = "admin123"

    def assert_safe_secrets(self) -> None:
        """Refuse to run with publicly-known signing material unless the
        operator explicitly opts in with ARK_ALLOW_INSECURE=true."""
        if self.allow_insecure:
            return
        if self.secret_key == self.DEFAULT_SECRET_KEY or len(self.secret_key) < 32:
            raise RuntimeError(
                "ARK_SECRET_KEY is unset, the built-in default, or shorter than 32 "
                "characters — JWTs would be forgeable. Generate one with "
                "`openssl rand -hex 32`, or set ARK_ALLOW_INSECURE=true to "
                "explicitly keep the insecure development setup."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
