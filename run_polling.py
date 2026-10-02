"""Run the bot locally with long polling: no public URL needed.

    python3 run_polling.py

Uses DATABASE_URL (the local fitness.db by default) and the same handler as the
webhook. Polling and a webhook can't both be active, so this removes any webhook
first; run scripts/set_webhook.py again before going back to the deployed bot.
"""
import logging
import time

from dotenv import load_dotenv

load_dotenv()

from app.db.migrate import upgrade_head  # noqa: E402
from app.logs import setup_logging  # noqa: E402
from app.telegram.api import TelegramAPI, safe_message  # noqa: E402
from app.telegram.handler import allowed_ids, handle_update  # noqa: E402

logger = logging.getLogger("app.polling")


def main() -> None:
    setup_logging()
    if not allowed_ids():
        raise SystemExit("ALLOWED_TELEGRAM_IDS is empty, so the bot would answer nobody. "
                         "Add your Telegram user id to .env.")

    upgrade_head()
    api = TelegramAPI()
    api.call("deleteWebhook")
    me = api.call("getMe")
    print(f"Polling as @{me['username']}. Ctrl+C to stop.")

    offset = None
    while True:
        try:
            updates = api.get_updates(offset)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            # Type and message (token masked) plus the stack. A failed poll carries
            # no update, so there's no message content to leak.
            detail = safe_message(e)
            logger.warning("event=poll_failed detail=%s", detail, exc_info=True,
                           extra={"event": "poll_failed", "detail": detail})
            time.sleep(5)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            handle_update(update, api)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
