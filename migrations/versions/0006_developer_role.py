"""sixth migration: add developer role

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_member_role", "team_members", type_="check")
    op.create_check_constraint(
        "ck_member_role", "team_members",
        "role IN ('admin','publisher','developer','member')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM team_members WHERE role = 'developer'")
    op.drop_constraint("ck_member_role", "team_members", type_="check")
    op.create_check_constraint(
        "ck_member_role", "team_members", "role IN ('admin','publisher','member')",
    )
