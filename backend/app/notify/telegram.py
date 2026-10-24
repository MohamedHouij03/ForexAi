"""Telegram phone notifications: one short message for every new BUY/SELL signal.

    SELL EUR/USD
    TP: 1.13853
    SL: 1.13945

Setup (once):
  1. In Telegram, open @BotFather, send /newbot and follow the steps. It gives you a token.
  2. Put it in the .env file:  TELEGRAM_BOT_TOKEN=<token>
  3. Open your new bot in Telegram and send it any message (e.g. "hi").
  4. From backend/:  python -m app.notify.telegram
     It finds your chat id, saves TELEGRAM_CHAT_ID in .env and sends you a test message.
Restart the app afterwards. The token is a password: never share it or commit it.
"""

from __future__ import annotations

import logging
import re
import sys

import httpx

from app.core.config import REPO_ROOT, Settings, get_settings
from app.core.instruments import get_instrument

logger = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"


def format_signal(sig: dict) -> str:
    inst = get_instrument(sig["instrument"])
    digits = inst.display_precision
    return (f"{sig['decision']} {inst.display_name}\n"
            f"TP: {sig['take_profit']:.{digits}f}\n"
            f"SL: {sig['stop_loss']:.{digits}f}")


def _call(token: str, method: str, payload: dict | None = None, timeout: float = 10.0) -> dict:
    # errors are reported without the URL: it contains the token
    try:
        r = httpx.post(API.format(token=token, method=method), json=payload or {}, timeout=timeout)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Telegram unreachable ({type(exc).__name__})") from None
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or not data.get("ok"):
        raise RuntimeError(f"Telegram error {r.status_code}: {data.get('description', 'unknown')}")
    return data


def send_message(token: str, chat_id: str, text: str) -> None:
    _call(token, "sendMessage", {"chat_id": chat_id, "text": text})


class TelegramNotifier:
    def __init__(self, settings: Settings):
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def notify_signal(self, sig: dict) -> bool:
        """Send a new BUY/SELL to the phone. Never raises: a failed message must not stop the engine."""
        if not self.enabled or sig.get("status") != "actionable" or sig.get("decision") not in ("BUY", "SELL"):
            return False
        try:
            send_message(self.token, self.chat_id, format_signal(sig))
            return True
        except Exception as exc:
            logger.warning("Telegram message failed: %s", exc)
            return False


def _save_chat_id(chat_id: str) -> None:
    env = REPO_ROOT / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    line = f"TELEGRAM_CHAT_ID={chat_id}"
    if re.search(r"^TELEGRAM_CHAT_ID=.*$", text, flags=re.M):
        text = re.sub(r"^TELEGRAM_CHAT_ID=.*$", line, text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\n{line}\n"
    env.write_text(text, encoding="utf-8")


def main() -> int:
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        print("TELEGRAM_BOT_TOKEN is empty in .env - create a bot with @BotFather first.", file=sys.stderr)
        return 1
    try:
        me = _call(token, "getMe")["result"]
        updates = _call(token, "getUpdates")["result"]
    except RuntimeError as exc:
        print(f"Could not reach your bot: {exc}. Check the token.", file=sys.stderr)
        return 1
    chats = [u["message"]["chat"] for u in updates if "message" in u]
    if not chats:
        print(f"Found your bot @{me.get('username')}. Now open it in Telegram, send it any message, "
              "and run this again.")
        return 1
    chat_id = str(chats[-1]["id"])
    _save_chat_id(chat_id)
    send_message(token, chat_id, "Forex AI connected. You will get a message here for every BUY/SELL.")
    print(f"Connected to {chats[-1].get('first_name') or chats[-1].get('title') or 'your chat'} - "
          "chat id saved to .env and a test message sent. Restart the app.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
