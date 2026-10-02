"""Point Telegram at the deployed webhook, with the secret it must send back.

    python3 scripts/set_webhook.py https://<your-app>.up.railway.app
    python3 scripts/set_webhook.py --info      # show what Telegram has now
    python3 scripts/set_webhook.py --delete    # back to no webhook (polling)

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET from the environment or .env.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.telegram.api import TelegramAPI  # noqa: E402

WEBHOOK_PATH = "/telegram/webhook"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base_url", nargs="?", help="the app's public https URL, without the path")
    parser.add_argument("--info", action="store_true", help="show the current webhook")
    parser.add_argument("--delete", action="store_true", help="remove the webhook")
    parser.add_argument("--drop-pending", action="store_true",
                        help="discard updates Telegram queued while nothing was listening")
    args = parser.parse_args()
    api = TelegramAPI()

    if args.info:
        info = api.call("getWebhookInfo")
        for key in ("url", "pending_update_count", "last_error_date", "last_error_message"):
            if key in info:
                print(f"{key}: {info[key]}")
        return
    if args.delete:
        api.call("deleteWebhook", drop_pending_updates=args.drop_pending)
        print("Webhook removed.")
        return

    if not args.base_url or not args.base_url.startswith("https://"):
        parser.error("give the app's https URL, e.g. https://coach-bob.up.railway.app")
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    if not secret:
        sys.exit("TELEGRAM_WEBHOOK_SECRET is empty. Set it here and on Railway (same value).")
    url = args.base_url.rstrip("/") + WEBHOOK_PATH
    api.call("setWebhook", url=url, secret_token=secret,
             allowed_updates=["message", "callback_query"],
             drop_pending_updates=args.drop_pending)
    print(f"Webhook set: {url}")


if __name__ == "__main__":
    main()
