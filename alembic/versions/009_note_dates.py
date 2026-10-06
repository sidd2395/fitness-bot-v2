"""add starts_on and ends_on to notes, so code works out whether a trip or event
is coming up, happening now or over

Revision ID: 009
Revises: 008
Create Date: 2026-10-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("notes") as batch:
        batch.add_column(sa.Column("starts_on", sa.Date(), nullable=True))
        batch.add_column(sa.Column("ends_on", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("notes") as batch:
        batch.drop_column("ends_on")
        batch.drop_column("starts_on")
