"""add profiles.water_target_l: a daily water target they or their coach set

Revision ID: 010
Revises: 009
Create Date: 2026-10-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("water_target_l", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("water_target_l")
