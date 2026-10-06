"""add checkins.food_note: what they ate in their own words, never turned into numbers

Revision ID: 011
Revises: 010
Create Date: 2026-10-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("checkins") as batch:
        batch.add_column(sa.Column("food_note", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("checkins") as batch:
        batch.drop_column("food_note")
