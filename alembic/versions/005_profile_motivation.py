"""add profiles.motivation; onboarding gains a question after the goal

Revision ID: 005
Revises: 004
Create Date: 2026-09-25
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("motivation", sa.String(200), nullable=True))
    # The motivation question is step 5 now, so injuries, trainer and "complete"
    # each move up one. Anyone past the goal question keeps their place.
    op.execute("UPDATE users SET onboarding_step = onboarding_step + 1 WHERE onboarding_step >= 5")


def downgrade() -> None:
    op.execute("UPDATE users SET onboarding_step = onboarding_step - 1 WHERE onboarding_step >= 6")
    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("motivation")
