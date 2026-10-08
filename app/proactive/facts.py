"""Reads what the planner needs from the database. Times are Singapore local,
naive, like clock.now_local()."""
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.agent.stats import note_end_of, _TRIP_WORDS
from app.db.models import Checkin, Note, OutboundMessage, RawMessage, User
from app.proactive.planner import Facts, NoteFact

UTC_TO_LOCAL = timedelta(hours=8)   # Singapore, no daylight saving
SICK_CLOSE_DAYS = 7


def _local(utc: Optional[datetime]) -> Optional[datetime]:
    return utc + UTC_TO_LOCAL if utc else None


def note_kind(note: Note) -> str:
    """The note's kind; older notes saved before kinds existed are read from their text."""
    if note.kind:
        return note.kind
    return "trip" if _TRIP_WORDS.search(note.text or "") else "other"


def close_old_sick_notes(user_id: int, db: Session, today: date) -> int:
    """Safety net: a sick note closes itself 7 days after it started, in case
    resolve_note never came. Returns how many were closed."""
    stale = [n for n in db.query(Note).filter(Note.user_id == user_id, Note.resolved.is_(False),
                                             Note.kind == "sick").all()
             if (n.starts_on or n.created_at.date()) <= today - timedelta(days=SICK_CLOSE_DAYS)]
    for note in stale:
        note.resolved = True
    if stale:
        db.commit()
    return len(stale)


def build_facts(user: User, db: Session, now: datetime) -> Facts:
    today = now.date()
    last = (db.query(RawMessage.created_at).filter(RawMessage.user_id == user.user_id)
            .order_by(RawMessage.created_at.desc()).first())
    notes = []
    for n in db.query(Note).filter(Note.user_id == user.user_id, Note.resolved.is_(False)).all():
        kind = note_kind(n)
        start = n.starts_on or (n.created_at.date() if kind == "sick" else None)
        notes.append(NoteFact(n.note_id, kind, start, note_end_of(n) if n.starts_on or n.ends_on else start))

    sent = (db.query(OutboundMessage).filter(OutboundMessage.user_id == user.user_id,
                                             OutboundMessage.status == "sent")
            .order_by(OutboundMessage.sent_at).all())
    sick_sent = {o.note_id for o in sent if o.reason == "sick" and o.note_id}
    return Facts(
        reminders=user.reminders or "off",
        paused_until=user.paused_until,
        last_message_at=_local(last[0]) if last else None,
        since=_local(user.consent_given_at or user.joined_at),
        logged_today=db.query(Checkin.checkin_id).filter(Checkin.user_id == user.user_id,
                                                         Checkin.date == today).first() is not None,
        open_notes=notes,
        sick_checkins_sent=sick_sent,
        last_two_unanswered=len(sent) >= 2 and all(not _answered(user.user_id, o, sent, db)
                                                  for o in sent[-2:]),
    )


def _answered(user_id: int, outbound: OutboundMessage, sent: list, db: Session) -> bool:
    """A message from them after this one went out, before the next one did."""
    later = [o.sent_at for o in sent if o.sent_at and o.sent_at > outbound.sent_at]
    q = db.query(RawMessage.id).filter(RawMessage.user_id == user_id,
                                       RawMessage.created_at > outbound.sent_at)
    if later:
        q = q.filter(RawMessage.created_at < min(later))
    return q.first() is not None
