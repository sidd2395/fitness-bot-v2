"""Admin: how much we hold for one Telegram user, and deleting it. Prints table
names and row counts only, never message content or profile values.

    python3 scripts/user_data.py --chat 123456789 --count
    python3 scripts/user_data.py --chat 123456789 --delete    # asks you to type the id

Uses DATABASE_URL, or DATABASE_PUBLIC_URL when that's set (Railway's private
database address only resolves inside Railway; see DEPLOY.md).
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

from sqlalchemy import func, select  # noqa: E402

from app.db import delete_user  # noqa: E402
from app.db.models import Base, User  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def counts(user_id: int, db) -> dict:
    """Rows per table that belong to this user, the users row included."""
    out = {"users": db.query(User).filter(User.user_id == user_id).count()}
    for table in Base.metadata.sorted_tables:
        if "user_id" in table.c and table.name != "users":
            out[table.name] = db.execute(
                select(func.count()).select_from(table).where(table.c.user_id == user_id)
            ).scalar()
    return out


def print_counts(label: str, rows: dict) -> None:
    print(label)
    for table, n in rows.items():
        print(f"  {table:<16} {n}")
    print(f"  {'total':<16} {sum(rows.values())}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chat", required=True, help="the user's Telegram chat id")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--count", action="store_true", help="row counts per table (read-only)")
    action.add_argument("--delete", action="store_true", help="delete everything for this user")
    args = parser.parse_args()
    chat = args.chat.strip()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_chat_id == chat).first()
        if user is None:
            print(f"No user with chat id {chat}.")
            return
        user_id = user.user_id
        print_counts(f"User {user_id} (chat {chat}):", counts(user_id, db))
        if args.count:
            return

        typed = input("\nThis deletes every row above and can't be undone. Type the chat id to confirm: ")
        if typed.strip() != chat:
            print("Didn't match. Nothing deleted.")
            return
        delete_user(user_id, db)
        print_counts("\nAfter delete:", counts(user_id, db))
    finally:
        db.close()


if __name__ == "__main__":
    main()
