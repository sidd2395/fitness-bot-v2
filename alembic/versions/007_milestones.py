"""add milestones: each one is stored once so it is never celebrated twice

Revision ID: 007
Revises: 006
Create Date: 2026-09-25
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "milestones",
        sa.Column("milestone_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.user_id", name="fk_milestones_user_id_users", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("reached_on", sa.Date(), nullable=False),
        sa.UniqueConstraint("user_id", "kind", name="uq_milestones_user_kind"),
    )


def downgrade() -> None:
    op.drop_table("milestones")
