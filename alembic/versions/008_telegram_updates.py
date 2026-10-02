"""add telegram_updates: update ids already handled, so Telegram's retries are ignored

Revision ID: 008
Revises: 007
Create Date: 2026-10-02
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No user link and no content: just the id Telegram gave the update
    op.create_table(
        "telegram_updates",
        sa.Column("update_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("telegram_updates")
