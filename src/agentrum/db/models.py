"""SQLAlchemy models: tenancy (users/teams/namespaces), resources, subscriptions, audit."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# --- Domain constants --------------------------------------------------------

KINDS = ("Agent", "MCPServer", "Skill", "Prompt", "Secret", "Deployment")

ROLE_ADMIN = "admin"
ROLE_PUBLISHER = "publisher"
ROLE_MEMBER = "member"
ROLES = (ROLE_ADMIN, ROLE_PUBLISHER, ROLE_MEMBER)

VISIBILITY_INTERNAL = "internal"
VISIBILITY_RESTRICTED = "restricted"
VISIBILITY_PRIVATE = "private"  # project-only (Prompts)

SUB_ACTIVE = "active"
SUB_PENDING = "pending_approval"
SUB_REVOKED = "revoked"


class Base(DeclarativeBase):
    pass


# --- Identity ----------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(63), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Identity-provider link (OIDC / OAuth2 SSO). NULL for local accounts.
    idp_provider: Mapped[str | None] = mapped_column(String(63))
    idp_subject: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ApiToken(Base):
    """Long-lived credentials for CLI/CI. Only the SHA-256 hash is stored."""

    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Tenancy -----------------------------------------------------------------


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(63), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    # Explicit ownership: the admin member responsible for the project.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (CheckConstraint("role IN ('admin','publisher','member')", name="ck_member_role"),)

    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(15), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Namespace(Base):
    """Isolation unit. Every team owns at least one namespace (its own name)."""

    __tablename__ = "namespaces"

    name: Mapped[str] = mapped_column(String(63), primary_key=True)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# --- Resources ---------------------------------------------------------------


class Resource(Base):
    """A registry asset (agent / MCP server / skill / prompt). Soft-deleted."""

    __tablename__ = "resources"
    __table_args__ = (
        UniqueConstraint("kind", "namespace", "name", name="uq_resource_identity"),
        Index("ix_resources_kind_namespace", "kind", "namespace"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(31), nullable=False)
    namespace: Mapped[str] = mapped_column(ForeignKey("namespaces.name"), nullable=False)
    name: Mapped[str] = mapped_column(String(253), nullable=False)
    visibility: Mapped[str] = mapped_column(String(15), nullable=False, server_default="internal")
    labels: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    description: Mapped[str | None] = mapped_column(Text)
    # Mutable catalog metadata (icon/keywords/authors/license/links/...);
    # changes do NOT create new versions.
    catalog: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Runtime observations (conditions written by probes / controllers).
    status: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResourceVersion(Base):
    """Immutable snapshot of a resource. Tags never move once published."""

    __tablename__ = "resource_versions"
    __table_args__ = (
        UniqueConstraint("resource_id", "version", name="uq_resource_version"),
        UniqueConstraint("resource_id", "tag", name="uq_resource_tag"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    tag: Mapped[str | None] = mapped_column(String(63))
    spec: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    change_notes: Mapped[str | None] = mapped_column(Text)
    published_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# --- Subscriptions -----------------------------------------------------------


class Subscription(Base):
    """Team B follows Team A's content.

    `name` may be "*" to subscribe to a whole namespace. For restricted
    resources the subscription starts as `pending_approval` until an admin of
    the owning team approves it.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("subscriber_team_id", "kind", "namespace", "name", name="uq_subscription"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscriber_team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(31), nullable=False)
    namespace: Mapped[str] = mapped_column(String(63), nullable=False)
    name: Mapped[str] = mapped_column(String(253), nullable=False)
    events: Mapped[list] = mapped_column(JSONB, nullable=False, server_default='["new_version"]')
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# --- Audit -------------------------------------------------------------------


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_occurred_at", "occurred_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(63), nullable=False)
    kind: Mapped[str | None] = mapped_column(String(31))
    namespace: Mapped[str | None] = mapped_column(String(63))
    name: Mapped[str | None] = mapped_column(String(253))
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    source_ip: Mapped[str | None] = mapped_column(String(64))


# --- Notifications ------------------------------------------------------------


class NotificationOutbox(Base):
    """Transactional outbox: events are committed with the state that caused
    them, then delivered by a background dispatcher."""

    __tablename__ = "notification_outbox"
    __table_args__ = (Index("ix_outbox_status_next", "status", "next_attempt_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    event_type: Mapped[str] = mapped_column(String(63), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_error: Mapped[str | None] = mapped_column(Text)


class SecretPayload(Base):
    """Encrypted-at-rest values for Secret resources. One row per key;
    plaintext never touches the database."""

    __tablename__ = "secret_payloads"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(253), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AccessKey(Base):
    """Project-scoped machine credential (AK/SK). SK is verified via SHA-256
    hash and shown exactly once at creation; scopes: read/publish/deploy."""

    __tablename__ = "access_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    access_key: Mapped[str] = mapped_column(String(63), unique=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default='["read","publish","deploy"]')
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
