"""The deployed bot: Telegram webhook plus a health check.

    uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""
import hmac
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

load_dotenv()

from app.db.migrate import upgrade_head  # noqa: E402
from app.logs import setup_logging  # noqa: E402
from app.telegram.handler import handle_update  # noqa: E402

_api = None


def telegram_api():
    """Built on first use, so importing the app doesn't need the bot token."""
    global _api
    if _api is None:
        from app.telegram.api import TelegramAPI
        _api = TelegramAPI()
    return _api


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    upgrade_head()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request, background: BackgroundTasks):
    expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    given = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    # No secret configured means nothing gets in
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        return JSONResponse({"ok": False}, status_code=401)
    try:
        update = await request.json()
    except ValueError:
        return JSONResponse({"ok": False}, status_code=400)
    if not isinstance(update, dict):
        return JSONResponse({"ok": False}, status_code=400)
    # Answer Telegram at once; the agent can take several seconds. A sync
    # background function runs in the thread pool, off the event loop.
    background.add_task(handle_update, update, telegram_api())
    return {"ok": True}
