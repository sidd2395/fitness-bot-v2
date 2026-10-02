"""Print one user's full conversation from the database, oldest first, and write
it to transcript_<user_id>.txt. Holds real personal data: the files are
gitignored, and are for reading locally only.

    python3 scripts/export_transcript.py                # the most recent user
    python3 scripts/export_transcript.py --user 3
    python3 scripts/export_transcript.py --chat 123456789

Under each turn: the check-in saved from that message (linked by id), and notes
or issues created during the turn (matched by time, since they aren't linked).
Profile changes aren't recorded per turn, so the current profile is shown at the top.
"""
import argparse
import sys
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from app.db.models import Checkin, Issue, Note, RawMessage, User  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.telegram.mydata import _checkin_line  # noqa: E402

SINGAPORE = timezone(timedelta(hours=8))
_PROFILE_FIELDS = ("goal", "start_weight", "calorie_target", "protein_target_g", "targets_set_by",
                   "disciplines", "motivation")


def _sgt(dt) -> str:
    return dt.replace(tzinfo=timezone.utc).astimezone(SINGAPORE).strftime("%Y-%m-%d %H:%M:%S SGT")


def _indent(text: str, prefix: str) -> str:
    return "\n".join(prefix + line for line in (text or "").splitlines()) or prefix


def transcript(user: User, db) -> str:
    out = [f"User {user.user_id}  telegram chat {user.telegram_chat_id or '-'}",
           f"Joined {_sgt(user.joined_at)}  consent "
           f"{_sgt(user.consent_given_at) if user.consent_given_at else 'not given'}  "
           f"onboarding step {user.onboarding_step}  blocked {user.blocked}",
           f"Name {user.name!r}  age {user.age}  sex {user.sex}  trainer {user.trainer_name!r}"]
    p = user.profile
    if p:
        out.append("Profile now: " + ", ".join(f"{f}={getattr(p, f)!r}" for f in _PROFILE_FIELDS))
    out.append("(Profile changes aren't recorded per turn; this is the current profile.)")

    messages = (db.query(RawMessage).filter(RawMessage.user_id == user.user_id)
                .order_by(RawMessage.id).all())
    notes = db.query(Note).filter(Note.user_id == user.user_id).all()
    issues = db.query(Issue).filter(Issue.user_id == user.user_id).all()

    for i, m in enumerate(messages):
        until = messages[i + 1].created_at if i + 1 < len(messages) else None
        in_turn = (lambda t: t >= m.created_at and (until is None or t < until))
        out += ["", "=" * 70, f"{_sgt(m.created_at)}  message {m.id}  status {m.status}",
                ">>> user", _indent(m.body, "    "),
                "<<< bot", _indent(m.reply_text or "(no reply stored)", "    ")]
        if m.checkin_id:
            c = db.get(Checkin, m.checkin_id)
            if c:
                line = _checkin_line(c)[2:]
                if c.corrected_at:
                    line += f"  (corrected {_sgt(c.corrected_at)})"
                out.append(f"  saved check-in: {line}")
        for n in notes:
            if in_turn(n.created_at):
                follow = f", follow up {n.follow_up_on}" if n.follow_up_on else ""
                out.append(f"  note (by time): {n.text!r}{follow}{', resolved' if n.resolved else ''}")
        for iss in issues:
            if in_turn(iss.first_mentioned):
                out.append(f"  issue (by time): {iss.what!r} ({iss.status})")

    if user.milestones:
        out += ["", "Milestones: " + ", ".join(f"{m.kind} on {m.reached_on}" for m in user.milestones)]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    who = parser.add_mutually_exclusive_group()
    who.add_argument("--user", type=int, help="user id")
    who.add_argument("--chat", help="telegram chat id")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.user is not None:
            user = db.get(User, args.user)
        elif args.chat:
            user = db.query(User).filter(User.telegram_chat_id == str(args.chat)).first()
        else:
            user = db.query(User).order_by(User.last_active_at.desc(), User.user_id.desc()).first()
        if user is None:
            sys.exit("No such user.")
        text = transcript(user, db)
    finally:
        db.close()

    print(text, end="")
    path = ROOT / f"transcript_{user.user_id}.txt"
    path.write_text(text)
    print(f"\nWritten to {path.name}")


if __name__ == "__main__":
    main()
