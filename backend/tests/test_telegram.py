import app.notify.telegram as tg
from app.core.config import Settings

SIG = {"instrument": "EUR_USD", "decision": "SELL", "status": "actionable",
       "take_profit": 1.138530001, "stop_loss": 1.13945, "entry": 1.13899}


def test_message_is_short():
    assert tg.format_signal(SIG) == "SELL EUR/USD\nTP: 1.13853\nSL: 1.13945"
    gold = {**SIG, "instrument": "XAU_USD", "decision": "BUY", "take_profit": 2410.456, "stop_loss": 2398.1}
    assert tg.format_signal(gold) == "BUY GOLD\nTP: 2410.456\nSL: 2398.100"


def test_notifier_sends_only_new_buy_sell(monkeypatch):
    sent = []
    monkeypatch.setattr(tg, "send_message", lambda token, chat, text: sent.append((chat, text)))
    off = tg.TelegramNotifier(Settings(telegram_bot_token="", telegram_chat_id=""))
    assert not off.enabled and off.notify_signal(SIG) is False
    on = tg.TelegramNotifier(Settings(telegram_bot_token="123:abc", telegram_chat_id="42"))
    assert on.notify_signal(SIG) is True
    assert on.notify_signal({**SIG, "decision": "WAIT"}) is False
    assert on.notify_signal({**SIG, "status": "expired"}) is False
    assert sent == [("42", "SELL EUR/USD\nTP: 1.13853\nSL: 1.13945")]


def test_a_failed_message_never_breaks_the_engine(monkeypatch):
    def boom(*a):
        raise RuntimeError("Telegram unreachable")
    monkeypatch.setattr(tg, "send_message", boom)
    assert tg.TelegramNotifier(Settings(telegram_bot_token="1:a", telegram_chat_id="2")).notify_signal(SIG) is False
