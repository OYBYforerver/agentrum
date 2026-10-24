"""fifth migration: explicit team ownership

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")))
    # backfill: first admin member becomes the owner
    op.execute(
        "UPDATE teams SET owner_user_id = ("
        " SELECT user_id FROM team_members"
        " WHERE team_members.team_id = teams.id AND role = 'admin'"
        " ORDER BY created_at LIMIT 1)"
    )

def downgrade() -> None:
    op.drop_column("teams", "owner_user_id")
