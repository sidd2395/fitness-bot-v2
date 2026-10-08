"""add users.reminders (both | morning | off) and users.paused_until for check-ins
Coach Bob sends first

Revision ID: 013
Revises: 012
Create Date: 2026-10-08
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        # Off until they pick a button: nobody gets a message they didn't ask for
        batch.add_column(sa.Column("reminders", sa.String(), nullable=False, server_default="off"))
        batch.add_column(sa.Column("paused_until", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("paused_until")
        batch.drop_column("reminders")
