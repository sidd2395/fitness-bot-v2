"""Logging setup. JSON lines in prod, plain text locally.

What may be logged: user_id, event, model, token counts, cost, latency, ids.
Never message text, replies, names or keys. Events pass their fields through
`extra`, so the JSON line carries them as keys.
"""
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone

# Fields that may appear in a JSON line, from a record's `extra`
FIELDS = ("event", "user_id", "detail", "model", "input_tokens", "output_tokens",
          "cache_read_tokens", "cache_write_tokens", "cost_usd", "latency_ms",
          "update_id", "status")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
        }
        for f in FIELDS:
            if hasattr(record, f):
                line[f] = getattr(record, f)
        if "event" not in line:
            # Only our own loggers are kept at INFO; this is a library warning
            line["msg"] = record.getMessage()
        if record.exc_info:
            line["error"] = safe_error(record.exc_info)
        return json.dumps(line, default=str)


def safe_error(exc_info) -> str:
    """Exception type and stack, without the exception's message: SQL errors
    echo their parameters, which can include a user's message."""
    exc_type, _, tb = exc_info
    return exc_type.__name__ + "\n" + "".join(traceback.format_tb(tb))


class TextFormatter(logging.Formatter):
    def formatException(self, ei) -> str:
        return safe_error(ei)


def setup_logging() -> None:
    json_logs = os.environ.get("LOG_FORMAT", "json" if os.environ.get("RAILWAY_ENVIRONMENT") else "text")
    handler = logging.StreamHandler(sys.stdout)
    if json_logs == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.WARNING)
    logging.getLogger("app").setLevel(logging.INFO)
    # httpx logs every request URL at INFO, and Telegram's URLs contain the bot token
    for name in ("httpx", "httpcore", "anthropic"):
        logging.getLogger(name).setLevel(logging.WARNING)
