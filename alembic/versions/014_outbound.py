"""add notes.kind (trip | sick | event | other) and outbound_messages, the check-ins
Coach Bob sends first, one per user per local day and slot

Revision ID: 014
Revises: 013
Create Date: 2026-10-08
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("notes") as batch:
        batch.add_column(sa.Column("kind", sa.String(), nullable=True))
    op.create_table(
        "outbound_messages",
        sa.Column("outbound_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.user_id", name="fk_outbound_messages_user_id_users", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(), nullable=False),        # morning | evening
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("note_id", sa.Integer(), nullable=True),     # the trip or sick note it's about
        sa.Column("status", sa.String(), nullable=False),      # claimed | sent | dropped | failed
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "local_date", "slot", name="uq_outbound_user_day_slot"),
    )


def downgrade() -> None:
    op.drop_table("outbound_messages")
    with op.batch_alter_table("notes") as batch:
        batch.drop_column("kind")
