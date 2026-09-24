"""add checkins.nudged_fields; cascade user deletes to owned tables

Revision ID: 003
Revises: 002
Create Date: 2026-09-25
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables whose user_id FK should cascade when the user row is deleted
_OWNED = ("profiles", "issues", "checkins", "raw_messages")

# 001 created these FKs without names. SQLite batch mode can only drop them
# if we give reflected constraints a name via a naming convention.
_NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def _fk_name(table: str) -> str:
    if op.get_bind().dialect.name == "sqlite":
        return f"fk_{table}_user_id_users"
    return f"{table}_user_id_fkey"  # Postgres default name


def _replace_user_fk(ondelete: Union[str, None]) -> None:
    for table in _OWNED:
        name = _fk_name(table)
        with op.batch_alter_table(table, naming_convention=_NAMING) as batch:
            batch.drop_constraint(name, type_="foreignkey")
            batch.create_foreign_key(name, "users", ["user_id"], ["user_id"], ondelete=ondelete)


def upgrade() -> None:
    with op.batch_alter_table("checkins") as batch:
        batch.add_column(sa.Column("nudged_fields", sa.Text(), nullable=True))
    _replace_user_fk("CASCADE")


def downgrade() -> None:
    _replace_user_fk(None)
    with op.batch_alter_table("checkins") as batch:
        batch.drop_column("nudged_fields")
