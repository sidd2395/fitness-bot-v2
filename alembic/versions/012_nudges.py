"""add nudges (tips and one-off flags shown, so they never repeat or nag) and
users.summary_used_at

Revision ID: 012
Revises: 011
Create Date: 2026-10-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nudges",
        sa.Column("nudge_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.user_id", name="fk_nudges_user_id_users", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("shown_on", sa.Date(), nullable=False),
    )
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("summary_used_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("summary_used_at")
    op.drop_table("nudges")
