"""One Telegram update in, replies out. Polling (run_polling.py) and the webhook
(app/main.py) both call handle_update.

Order: private chats only, beta allowlist, duplicate update ids, button taps,
rate limit, non-text, commands, consent, daily cap, then the agent.
"""
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.loop import run
from app.db import delete_user
from app.db.models import RawMessage, TelegramUpdate, User
from app.db.session import SessionLocal
from app.telegram import replies
from app.telegram.mydata import format_mydata

logger = logging.getLogger(__name__)

DAILY_TURN_CAP = 40               # messages that reach the agent, per user per Singapore day
MESSAGE_INTERVAL_S = 2.0          # one message per this many seconds per user
UPDATE_ID_RETENTION = timedelta(days=7)
SINGAPORE = timezone(timedelta(hours=8))  # no daylight saving


class RateLimiter:
    """In memory, per chat: fine for one instance. A message inside the interval
    is turned away and doesn't restart the clock."""

    def __init__(self, interval_s: float):
        self.interval_s = interval_s
        self.clock = time.monotonic
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            last = self._last.get(key)
            if last is not None and now - last < self.interval_s:
                return False
            self._last[key] = now
            if len(self._last) > 10_000:
                self._last = {k: t for k, t in self._last.items() if now - t < self.interval_s}
            return True

    def reset(self) -> None:
        with self._lock:
            self._last.clear()


limiter = RateLimiter(MESSAGE_INTERVAL_S)


def allowed_ids() -> set[str]:
    raw = os.environ.get("ALLOWED_TELEGRAM_IDS", "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def handle_update(update: dict, api, db: Optional[Session] = None) -> None:
    own_session = db is None
    db = db or SessionLocal()
    try:
        _handle(update, api, db)
    except Exception:
        db.rollback()
        logger.error("event=update_failed", exc_info=True,
                     extra={"event": "update_failed", "update_id": update.get("update_id")})
        chat_id = _chat_id(update)
        if chat_id and chat_id in allowed_ids():
            try:
                api.send_message(chat_id, replies.ERROR_REPLY)
            except Exception:
                _log("error_reply_failed", update_id=update.get("update_id"))
    finally:
        if own_session:
            db.close()


def _chat_id(update: dict) -> Optional[str]:
    if "callback_query" in update:
        chat = update["callback_query"].get("message", {}).get("chat", {})
    else:
        chat = update.get("message", {}).get("chat", {})
    if chat.get("type") != "private" or "id" not in chat:
        return None
    return str(chat["id"])


def _handle(update: dict, api, db: Session) -> None:
    # Edited messages, channel posts, group chats and the like are ignored
    chat_id = _chat_id(update)
    if chat_id is None:
        return
    callback = update.get("callback_query")

    # Beta allowlist: strangers get one fixed line and nothing about them is stored
    if chat_id not in allowed_ids():
        if callback:
            api.answer_callback(callback["id"])
        else:
            api.send_message(chat_id, replies.NOT_ALLOWED)
        _log("not_allowed")
        return

    # Telegram retries a delivery it thinks failed: handle each update id once
    if not _first_time(update.get("update_id"), db):
        _log("duplicate_update", update_id=update.get("update_id"))
        return

    user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
    if callback:
        _on_button(callback, chat_id, user, api, db)
        return

    if not limiter.allow(chat_id):
        api.send_message(chat_id, replies.SLOW_DOWN)
        _log("rate_limited", user)
        return

    text = (update["message"].get("text") or "").strip()
    if not update["message"].get("text"):
        # Photos, stickers, voice notes, files
        api.send_message(chat_id, replies.TEXT_ONLY)
        _log("not_text", user)
        return
    if not text:
        return

    if text.startswith("/"):
        _on_command(text, chat_id, user, api, db)
        return

    # Under 18: run() sends the fixed blocked reply and stores nothing
    if user is not None and user.blocked:
        api.send_message(chat_id, run(user.user_id, text, db))
        return

    # Nothing is stored until they tap "I agree"
    if user is None or user.consent_given_at is None:
        api.send_message(chat_id, replies.CONSENT_NOTICE, buttons=[replies.AGREE_BUTTON])
        _log("consent_asked", user)
        return

    if turns_today(user.user_id, db) >= DAILY_TURN_CAP:
        api.send_message(chat_id, replies.DAILY_CAP)
        _log("daily_cap", user)
        return

    try:
        api.send_typing(chat_id)
    except Exception:
        pass  # cosmetic
    started = time.monotonic()
    reply = run(user.user_id, text, db)
    api.send_message(chat_id, reply)
    _log("replied", user, latency_ms=round((time.monotonic() - started) * 1000))


def _on_command(text: str, chat_id: str, user: Optional[User], api, db: Session) -> None:
    command = text.split()[0].split("@")[0].lower()
    _log(f"command{command.replace('/', '_')}" if command in
         ("/start", "/help", "/mydata", "/delete") else "command_unknown", user)
    if command == "/start":
        # Telegram sends /start when someone first opens the bot
        if user is None or (user.consent_given_at is None and not user.blocked):
            api.send_message(chat_id, replies.CONSENT_NOTICE, buttons=[replies.AGREE_BUTTON])
        else:
            api.send_message(chat_id, replies.HELP)
    elif command == "/help":
        api.send_message(chat_id, replies.HELP)
    elif command == "/mydata":
        api.send_message(chat_id, format_mydata(user, db))
    elif command == "/delete":
        if user is None:
            api.send_message(chat_id, replies.NOTHING_HELD)
        else:
            api.send_message(chat_id, replies.DELETE_CONFIRM, buttons=replies.DELETE_BUTTONS)
    else:
        api.send_message(chat_id, replies.UNKNOWN_COMMAND)


def _on_button(callback: dict, chat_id: str, user: Optional[User], api, db: Session) -> None:
    api.answer_callback(callback["id"])
    data = callback.get("data")
    message_id = callback.get("message", {}).get("message_id")

    if data == "consent":
        if user is not None and (user.blocked or user.consent_given_at is not None):
            return  # an old button tapped again
        if user is None:
            user = User(telegram_chat_id=chat_id)
            db.add(user)
        user.consent_given_at = datetime.utcnow()
        db.commit()
        _clear(api, chat_id, message_id)
        api.send_message(chat_id, replies.AFTER_CONSENT)
        _log("consent_given", user)
    elif data == "delete_yes":
        _clear(api, chat_id, message_id)
        if user is None:
            api.send_message(chat_id, replies.NOTHING_HELD)
            return
        user_id = user.user_id
        delete_user(user_id, db)
        api.send_message(chat_id, replies.DELETED)
        _log("deleted", user_id=user_id)
    elif data == "delete_no":
        _clear(api, chat_id, message_id)
        api.send_message(chat_id, replies.DELETE_CANCELLED)


def _clear(api, chat_id: str, message_id: Optional[int]) -> None:
    """Takes the buttons off a message once one is tapped."""
    if message_id is None:
        return
    try:
        api.clear_buttons(chat_id, message_id)
    except Exception:
        pass  # already cleared, or too old to edit


def _first_time(update_id: Optional[int], db: Session) -> bool:
    if update_id is None:
        return True
    db.add(TelegramUpdate(update_id=update_id, received_at=datetime.utcnow()))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    if update_id % 500 == 0:
        cutoff = datetime.utcnow() - UPDATE_ID_RETENTION
        db.query(TelegramUpdate).filter(TelegramUpdate.received_at < cutoff).delete()
        db.commit()
    return True


def day_start_utc(now: Optional[datetime] = None) -> datetime:
    """Midnight Singapore time today, as naive UTC like the created_at columns."""
    now = now or datetime.now(timezone.utc)
    midnight = now.astimezone(SINGAPORE).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).replace(tzinfo=None)


def turns_today(user_id: int, db: Session) -> int:
    """Messages that reached the agent since midnight Singapore time. Every turn
    stores one raw message, so this survives restarts."""
    return (db.query(RawMessage)
            .filter(RawMessage.user_id == user_id, RawMessage.created_at >= day_start_utc())
            .count())


def _log(event: str, user: Optional[User] = None, *, user_id: Optional[int] = None,
         **fields) -> None:
    # Ids, events and numbers only: never message text, replies, names or chat ids
    if user_id is None and user is not None:
        user_id = user.user_id
    logger.info("event=%s user_id=%s", event, user_id,
                extra={"event": event, "user_id": user_id, **fields})
