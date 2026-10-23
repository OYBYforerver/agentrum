"""third migration: catalog/status columns, idp identity, secret payloads, trigram search

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("resources", sa.Column("catalog", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.add_column("resources", sa.Column("status", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.add_column("resource_versions", sa.Column("change_notes", sa.Text()))
    op.add_column("users", sa.Column("idp_provider", sa.String(63)))
    op.add_column("users", sa.Column("idp_subject", sa.String(255)))
    op.create_index(
        "ix_users_idp_subject", "users", ["idp_subject"], unique=True,
        postgresql_where=sa.text("idp_subject IS NOT NULL"),
    )

    op.create_table(
        "secret_payloads",
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("key", sa.String(253), primary_key=True),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Trigram acceleration for catalog search (Chinese-friendly substring match).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_resources_name_trgm", "resources", ["name"],
        postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_resources_desc_trgm", "resources", ["description"],
        postgresql_using="gin", postgresql_ops={"description": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_resources_desc_trgm", table_name="resources")
    op.drop_index("ix_resources_name_trgm", table_name="resources")
    op.drop_table("secret_payloads")
    op.drop_index("ix_users_idp_subject", table_name="users")
    op.drop_column("users", "idp_subject")
    op.drop_column("users", "idp_provider")
    op.drop_column("resource_versions", "change_notes")
    op.drop_column("resources", "status")
    op.drop_column("resources", "catalog")
