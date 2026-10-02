"""The few Telegram Bot API calls the bot makes. Plain text only, no parse_mode,
so nothing the model writes is read as markup."""
import os
from typing import Optional

import httpx

MESSAGE_LIMIT = 4096  # Telegram counts UTF-16 code units


class TelegramError(Exception):
    """Telegram answered ok=false. Carries the method and Telegram's description,
    never the URL, which contains the bot token."""

    def __init__(self, method: str, code: Optional[int], description: str):
        super().__init__(f"{method} failed ({code}): {description}")
        self.code = code


class TelegramAPI:
    def __init__(self, token: Optional[str] = None, timeout: float = 15.0):
        token = token or os.environ["TELEGRAM_BOT_TOKEN"]
        self._base = f"https://api.telegram.org/bot{token}/"
        self._http = httpx.Client(timeout=timeout)

    def call(self, method: str, timeout: Optional[float] = None, **params) -> dict:
        kwargs = {"timeout": timeout} if timeout is not None else {}
        data = self._http.post(self._base + method, json=params, **kwargs).json()
        if not data.get("ok"):
            raise TelegramError(method, data.get("error_code"), data.get("description", ""))
        return data["result"]

    def send_message(self, chat_id: str, text: str,
                     buttons: Optional[list[tuple[str, str]]] = None) -> None:
        """Sends text, split if it's over Telegram's limit. Buttons, as
        (label, callback data) pairs in one row, go on the last part."""
        parts = split_message(text)
        for i, part in enumerate(parts):
            params = {"chat_id": chat_id, "text": part}
            if buttons and i == len(parts) - 1:
                params["reply_markup"] = {"inline_keyboard": [
                    [{"text": label, "callback_data": data} for label, data in buttons]
                ]}
            self.call("sendMessage", **params)

    def send_typing(self, chat_id: str) -> None:
        self.call("sendChatAction", chat_id=chat_id, action="typing")

    def answer_callback(self, callback_id: str) -> None:
        # Stops the button's loading spinner
        self.call("answerCallbackQuery", callback_query_id=callback_id)

    def clear_buttons(self, chat_id: str, message_id: int) -> None:
        self.call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
                  reply_markup={"inline_keyboard": []})

    def get_updates(self, offset: Optional[int], wait: int = 30) -> list[dict]:
        params = {"timeout": wait, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        return self.call("getUpdates", timeout=wait + 10, **params)


def _units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def split_message(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Parts of at most `limit` UTF-16 units, cut at a paragraph break, then a
    line break, then a space, and only mid-word if there's no space at all."""
    parts = []
    while _units(text) > limit:
        # The longest prefix that fits, in characters
        fit = limit
        while _units(text[:fit]) > limit:
            fit -= 1
        cut = -1
        for sep in ("\n\n", "\n", " "):
            cut = text.rfind(sep, 0, fit)
            if cut > 0:
                break
        if cut <= 0:
            cut = fit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts
