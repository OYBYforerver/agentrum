"""seventh migration: credential lifecycle + identity index correctness

- users.password_changed_at: JWTs issued before this instant are rejected,
  so a password change/reset revokes every existing session.
- idp identity: the unique index moves from (idp_subject) to
  (idp_provider, idp_subject) — subjects are per-IdP namespaces, so two
  different providers may legitimately reuse the same subject value.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True)))
    op.drop_index("ix_users_idp_subject", table_name="users")
    op.create_index(
        "ix_users_idp_provider_subject", "users", ["idp_provider", "idp_subject"], unique=True,
        postgresql_where=sa.text("idp_subject IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_idp_provider_subject", table_name="users")
    op.create_index(
        "ix_users_idp_subject", "users", ["idp_subject"], unique=True,
        postgresql_where=sa.text("idp_subject IS NOT NULL"),
    )
    op.drop_column("users", "password_changed_at")
