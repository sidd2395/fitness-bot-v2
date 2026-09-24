"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-09-24
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id",          sa.Integer(),  primary_key=True, autoincrement=True),
        sa.Column("telegram_chat_id", sa.String(),   unique=True, nullable=True),
        sa.Column("name",             sa.String(),   nullable=True),
        sa.Column("age",              sa.Integer(),  nullable=True),
        sa.Column("sex",              sa.String(1),  nullable=True),
        sa.Column("trainer_name",     sa.String(),   nullable=True),
        sa.Column("consent_given_at", sa.DateTime(), nullable=True),
        sa.Column("joined_at",        sa.DateTime(), nullable=False),
        sa.Column("last_active_at",   sa.DateTime(), nullable=False),
        sa.Column("onboarding_step",  sa.Integer(),  nullable=False, server_default="0"),
    )
    op.create_table(
        "profiles",
        sa.Column("profile_id",       sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id",          sa.Integer(), sa.ForeignKey("users.user_id"), unique=True, nullable=False),
        sa.Column("goal",             sa.String(),  nullable=True),
        sa.Column("start_weight",     sa.Float(),   nullable=True),
        sa.Column("calorie_target",   sa.Integer(), nullable=True),
        sa.Column("protein_target_g", sa.Integer(), nullable=True),
        sa.Column("targets_set_by",   sa.String(),  nullable=True),
        sa.Column("disciplines",      sa.String(),  nullable=True),
    )
    op.create_table(
        "issues",
        sa.Column("issue_id",        sa.Integer(),  primary_key=True, autoincrement=True),
        sa.Column("user_id",         sa.Integer(),  sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("what",            sa.Text(),     nullable=False),
        sa.Column("status",          sa.String(),   nullable=False, server_default="active"),
        sa.Column("first_mentioned", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "checkins",
        sa.Column("checkin_id",  sa.Integer(),  primary_key=True, autoincrement=True),
        sa.Column("user_id",     sa.Integer(),  sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("date",        sa.Date(),     nullable=False),
        sa.Column("entry_type",  sa.String(),   nullable=False),
        sa.Column("weight_kg",   sa.Float(),    nullable=True),
        sa.Column("sleep_hours", sa.Float(),    nullable=True),
        sa.Column("training",    sa.String(),   nullable=True),
        sa.Column("energy",      sa.Integer(),  nullable=True),
        sa.Column("calories",    sa.Integer(),  nullable=True),
        sa.Column("protein_g",   sa.Float(),    nullable=True),
        sa.Column("water_l",     sa.Float(),    nullable=True),
        sa.Column("raw_message", sa.Text(),     nullable=False),
        sa.Column("corrected_at",sa.DateTime(), nullable=True),
        sa.Column("created_at",  sa.DateTime(), nullable=False),
    )
    op.create_table(
        "raw_messages",
        sa.Column("id",         sa.Integer(),  primary_key=True, autoincrement=True),
        sa.Column("user_id",    sa.Integer(),  sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("body",       sa.Text(),     nullable=False),
        sa.Column("status",     sa.String(),   nullable=False, server_default="received"),
        sa.Column("checkin_id", sa.Integer(),  sa.ForeignKey("checkins.checkin_id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("raw_messages")
    op.drop_table("checkins")
    op.drop_table("issues")
    op.drop_table("profiles")
    op.drop_table("users")
