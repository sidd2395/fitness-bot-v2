"""Preview a message Coach Bob would send first: builds the real prompt, calls the
model, prints the message and its word count. Sends nothing to Telegram and
writes nothing to the database (the session is rolled back and never committed).

    python3 scripts/preview_outreach.py --user 3 --reason morning
    python3 scripts/preview_outreach.py --user 3 --reason trip_return

For trip_return and sick it uses the user's most recent trip or sick note.
The model call is paid: it counts against the daily test budget, and its cost
is logged to eval_runs.csv like a test run. --force overrides the budget.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
if os.environ.get("DATABASE_PUBLIC_URL"):
    os.environ["DATABASE_URL"] = os.environ["DATABASE_PUBLIC_URL"]

import eval_log  # noqa: E402
from app.agent import loop as agent_loop  # noqa: E402
from app.db.models import Note, User  # noqa: E402
from app.pricing import cost_usd, usage_counts  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.proactive.facts import note_kind  # noqa: E402
from app.proactive.sender import compose, problems  # noqa: E402

REASONS = ["morning", "evening", "quiet", "quiet_last", "sick", "trip_return"]
PREVIEW_ESTIMATE_USD = 0.012   # one Sonnet call with the cached static prompt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", type=int, required=True)
    parser.add_argument("--reason", choices=REASONS, required=True)
    parser.add_argument("--force", action="store_true", help="run even if over today's test budget")
    args = parser.parse_args()
    if not eval_log.budget_ok(PREVIEW_ESTIMATE_USD, args.force):
        sys.exit(2)

    # Add up what this preview's model call costs, for eval_runs.csv
    spent = [0.0]
    real_record = agent_loop._record_usage

    def record(user_id, model, usage, latency_ms=None):
        real_record(user_id, model, usage, latency_ms)
        spent[0] += cost_usd(model, usage_counts(usage)) or 0.0
    agent_loop._record_usage = record

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
    eval_log.append({
        "models": f"coach={agent_loop.MODEL_COACH}",
        "only": f"preview:{args.reason}",
        "passed": 0 if issues else 1,
        "total": 1,
        "cost_usd": f"{spent[0]:.4f}",
        "checks": json.dumps({f"preview/{args.reason}": "fail" if issues else "pass"}),
    })
    print(f"[{args.reason}] {len(text.split())} words, {text.count('?')} question mark(s)"
          + (f", would be DROPPED: {', '.join(issues)}" if issues else ", would be sent"))
    print(text)


if __name__ == "__main__":
    main()
