"""eighth migration: resource deprecation

Deprecation keeps a resource visible and consumable while warning
subscribers — the registry-native alternative to soft-delete for
end-of-life assets.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("resources", sa.Column("deprecation", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("resources", "deprecation")
