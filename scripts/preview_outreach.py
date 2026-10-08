"""Preview a message Coach Bob would send first: builds the real prompt, calls the
model, prints the message and its word count. Sends nothing to Telegram and
writes nothing to the database (the session is rolled back and never committed).

    python3 scripts/preview_outreach.py --user 3 --reason morning
    python3 scripts/preview_outreach.py --user 3 --reason trip_return

For trip_return and sick it uses the user's most recent trip or sick note.
The model call is paid and its usage is logged like any other.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
if os.environ.get("DATABASE_PUBLIC_URL"):
    os.environ["DATABASE_URL"] = os.environ["DATABASE_PUBLIC_URL"]

from app.db.models import Note, User  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.proactive.facts import note_kind  # noqa: E402
from app.proactive.sender import compose, problems  # noqa: E402

REASONS = ["morning", "evening", "quiet", "quiet_last", "sick", "trip_return"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", type=int, required=True)
    parser.add_argument("--reason", choices=REASONS, required=True)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        # Nothing here is meant to write; flushing is off and the session is
        # rolled back, so even an accidental change never lands
        db.autoflush = False
        db.commit = db.flush = lambda *a, **k: None
        user = db.get(User, args.user)
        if user is None:
            sys.exit("No such user.")
        note = None
        if args.reason in ("trip_return", "sick"):
            want = "trip" if args.reason == "trip_return" else "sick"
            notes = [n for n in db.query(Note).filter(Note.user_id == user.user_id)
                     .order_by(Note.created_at.desc()).all() if note_kind(n) == want]
            note = notes[0] if notes else None
            if note is None:
                print(f"(no {want} note for this user; previewing without one)")
        text = compose(user, args.reason, note, db)
    finally:
        db.rollback()
        db.close()

    issues = problems(text)
    print(f"[{args.reason}] {len(text.split())} words, {text.count('?')} question mark(s)"
          + (f", would be DROPPED: {', '.join(issues)}" if issues else ", would be sent"))
    print(text)


if __name__ == "__main__":
    main()
