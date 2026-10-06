"""Write PROMPTS_REVIEW.md: everything the model and the user are shown, in one
file to read through. Regenerated on every run, gitignored.

    python3 scripts/dump_prompts.py

The context block is built for a made-up user in a throwaway in-memory
database, so no real data is read and nothing is written anywhere else.
"""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.agent import context, loop  # noqa: E402
from app.agent.tools import ONBOARDING_STEPS, TOOL_SCHEMAS  # noqa: E402
from app.db.models import Base, Checkin, Issue, Note, Profile, RawMessage, User  # noqa: E402
from app.telegram import replies  # noqa: E402

OUT = ROOT / "PROMPTS_REVIEW.md"


def section(n: int, title: str, source: str, body: str, fence: str = "text") -> str:
    return f"## {n}. {title}\n\nFrom `{source}`\n\n````{fence}\n{body.rstrip()}\n````\n"


def made_up_user(db) -> User:
    """Alex: three weeks of check-ins, a knee issue, a coach, targets, a trip coming up."""
    today = date.today()
    joined = datetime.utcnow() - timedelta(days=24)
    user = User(telegram_chat_id="0", name="Alex", age=34, sex="M", trainer_name="Dan",
                onboarding_step=ONBOARDING_STEPS, joined_at=joined, last_active_at=datetime.utcnow(),
                consent_given_at=joined)
    db.add(user)
    db.commit()
    db.add(Profile(user_id=user.user_id, goal="lose_fat", start_weight=86.0, calorie_target=2200,
                   protein_target_g=160, targets_set_by="coach", disciplines="Gym,Muay Thai",
                   motivation="keep up with my kids"))
    db.add(Issue(user_id=user.user_id, what="sore left knee from running",
                 first_mentioned=joined + timedelta(days=3)))
    weights = [85.6, 85.4, 85.5, 85.1, 85.3, 84.9, 85.0, 84.8, 84.9, 84.6, 84.7, 84.4, 84.6, 84.3,
               84.5, 84.2, 84.4, 84.0, 84.3, 84.1, 84.4]
    for i, kg in enumerate(weights):
        day = today - timedelta(days=len(weights) - 1 - i)
        db.add(Checkin(user_id=user.user_id, date=day, entry_type="morning", weight_kg=kg,
                       sleep_hours=[7.5, 6.5, 7, 5.5, 5.5][i % 5], training=["gym", "Muay Thai", None,
                       "easy run", "rest"][i % 5], energy=[4, 3, 4, 2, 3][i % 5],
                       food_note="big dinner out" if i == len(weights) - 2 else None,
                       raw_message="(made up)", created_at=datetime.utcnow()))
    db.add(Note(user_id=user.user_id, text="Work trip to Bangkok, hotel gym only",
                starts_on=today + timedelta(days=5), ends_on=today + timedelta(days=9),
                follow_up_on=today + timedelta(days=10)))
    db.add(RawMessage(user_id=user.user_id, body="84.4 slept 5.5h, rest day",
                      reply_text="Logged. 5.5 hours is short, so keep today easy.",
                      created_at=datetime.utcnow() - timedelta(hours=2)))
    db.commit()
    db.refresh(user)
    return user


def onboarding_user(db) -> User:
    user = User(telegram_chat_id="1", name="Sam", age=29, onboarding_step=2,
                joined_at=datetime.utcnow(), last_active_at=datetime.utcnow())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def main() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    onboarding = context.build_system_prompt(onboarding_user(db), db)
    coaching = context.build_system_prompt(made_up_user(db), db)

    tools = "\n\n".join(
        f"### {t['name']}\n\n{t['description']}\n\n```json\n"
        f"{json.dumps(t['input_schema'], indent=2, ensure_ascii=False)}\n```"
        for t in TOOL_SCHEMAS)

    fixed = {
        "Welcome (no consent step, e.g. tests)": loop.WELCOME_REPLY,
        "Consent notice (Telegram welcome)": replies.CONSENT_NOTICE,
        "After tapping I agree": replies.AFTER_CONSENT,
        "All set (end of onboarding)": loop.ONBOARDED_REPLY,
        "/help": replies.HELP,
        "Under 18, blocked": loop.BLOCKED_REPLY,
        "Not on the beta allowlist": replies.NOT_ALLOWED,
        "Not text": replies.TEXT_ONLY,
        "Rate limit": replies.SLOW_DOWN,
        "Daily cap": replies.DAILY_CAP,
        "Something went wrong": replies.ERROR_REPLY,
        "Unknown command": replies.UNKNOWN_COMMAND,
        "/summary with a bad number": replies.SUMMARY_USAGE,
        "/delete confirm": replies.DELETE_CONFIRM,
        "/delete buttons": " | ".join(label for label, _ in replies.DELETE_BUTTONS),
        "/delete done": replies.DELETED,
        "/delete cancelled": replies.DELETE_CANCELLED,
        "Nothing held": replies.NOTHING_HELD,
        "Fallback, something was saved": loop.EMPTY_REPLY_SAVED,
        "Fallback, nothing saved": loop.EMPTY_REPLY_NOTHING_SAVED,
        "Sent to the model with tool results when it drafted text": loop.DRAFT_NOT_SENT_NOTE,
    }
    fixed_text = "\n\n".join(f"### {name}\n\n```text\n{text}\n```" for name, text in fixed.items())

    parts = [
        "# Prompt review\n\nGenerated by `scripts/dump_prompts.py` on "
        f"{datetime.now():%Y-%m-%d %H:%M}. Don't edit: change the source files and run it again.\n",
        section(1, "coach.md in full", "app/agent/prompts/coach.md", context.COACH_PROMPT, "markdown"),
        section(2, "Onboarding system prompt (cached static part, then the per-turn block)",
                "app/agent/context.py build_system_prompt, for a user on question 3",
                onboarding[0]["text"] + "\n\n----- per-turn block -----\n\n" + onboarding[1]["text"],
                "markdown"),
        section(3, "Tool rules", "app/agent/context.py _TOOL_RULES", context._TOOL_RULES, "markdown"),
        f"## 4. Tools, exactly as sent to the model\n\nFrom `app/agent/tools.py` TOOL_SCHEMAS. "
        f"Onboarding is offered save_profile only.\n\n{tools}\n",
        section(5, "Context block for a made-up user (Alex)",
                "app/agent/context.py _context_block, filled in from a throwaway database",
                coaching[1]["text"]),
        f"## 6. Fixed messages\n\nFrom `app/agent/loop.py`, `app/telegram/replies.py` and "
        f"`app/capabilities.py`.\n\n{fixed_text}\n",
    ]
    OUT.write_text("\n".join(parts))
    print(f"Written to {OUT.name}")


if __name__ == "__main__":
    main()
