from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    DateTime, Date, Text, ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    user_id          = Column(Integer, primary_key=True, autoincrement=True)
    telegram_chat_id = Column(String, unique=True, nullable=True)
    name             = Column(String, nullable=True)
    age              = Column(Integer, nullable=True)
    sex              = Column(String(1), nullable=True)          # M or F
    trainer_name     = Column(String, nullable=True)
    consent_given_at = Column(DateTime, nullable=True)
    joined_at        = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_active_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    onboarding_step  = Column(Integer, default=0, nullable=False)  # 0–7; 7 = complete
    # Under 18. Personal data is cleared; every message gets a fixed reply, no model call
    blocked          = Column(Boolean, default=False, nullable=False)

    # Deleting a user deletes everything they own (PDPA delete command)
    profile      = relationship("Profile",    uselist=False, back_populates="user",
                                cascade="all, delete-orphan")
    issues       = relationship("Issue",      back_populates="user",
                                cascade="all, delete-orphan")
    checkins     = relationship("Checkin",    back_populates="user",
                                cascade="all, delete-orphan")
    raw_messages = relationship("RawMessage", back_populates="user",
                                foreign_keys="RawMessage.user_id",
                                cascade="all, delete-orphan")


class Profile(Base):
    __tablename__ = "profiles"

    profile_id       = Column(Integer, primary_key=True, autoincrement=True)
    user_id          = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), unique=True, nullable=False)
    goal             = Column(String, nullable=True)   # lose_fat | build_muscle | perform | feel_better
    start_weight     = Column(Float,  nullable=True)
    calorie_target   = Column(Integer, nullable=True)
    protein_target_g = Column(Integer, nullable=True)
    targets_set_by   = Column(String, nullable=True)   # user | coach
    disciplines      = Column(String, nullable=True)   # comma-separated

    user = relationship("User", back_populates="profile")


class Issue(Base):
    __tablename__ = "issues"

    issue_id        = Column(Integer, primary_key=True, autoincrement=True)
    user_id         = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    what            = Column(Text, nullable=False)
    status          = Column(String, default="active", nullable=False)  # active | resolved
    first_mentioned = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="issues")


class Checkin(Base):
    __tablename__ = "checkins"

    checkin_id   = Column(Integer, primary_key=True, autoincrement=True)
    user_id      = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    date         = Column(Date,    nullable=False)
    entry_type   = Column(String,  nullable=False)      # morning | evening
    weight_kg    = Column(Float,   nullable=True)
    sleep_hours  = Column(Float,   nullable=True)
    training     = Column(String,  nullable=True)
    energy       = Column(Integer, nullable=True)        # 1–5
    calories     = Column(Integer, nullable=True)
    protein_g    = Column(Float,   nullable=True)
    water_l      = Column(Float,   nullable=True)
    raw_message  = Column(Text,    nullable=False)
    corrected_at = Column(DateTime, nullable=True)
    nudged_fields = Column(Text,   nullable=True)        # comma-separated fields the bot reminded them about
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="checkins")


class RawMessage(Base):
    """Every inbound message, saved before the agent runs.
    status=failed means the agent errored; use these rows to find mishandled messages."""
    __tablename__ = "raw_messages"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    body       = Column(Text,    nullable=False)
    status     = Column(String,  default="received", nullable=False)  # received | processed | failed
    checkin_id = Column(Integer, ForeignKey("checkins.checkin_id"), nullable=True)
    reply_text = Column(Text,    nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user    = relationship("User",    back_populates="raw_messages", foreign_keys=[user_id])
    checkin = relationship("Checkin", foreign_keys=[checkin_id])
