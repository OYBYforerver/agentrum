"""ninth migration: subscription version pin (pinned_tag)

Consumers can lock their subscription to one immutable tag; publishes of
other tags notify them with an explicit "pinned, new version available"
hint instead of implying an upgrade.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("pinned_tag", sa.String(63), nullable=True))


def downgrade() -> None:
    op.drop_column("subscriptions", "pinned_tag")
