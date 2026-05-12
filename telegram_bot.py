from __future__ import annotations

from dazro_trade.core.config import Settings
from dazro_trade.notifications.telegram_bot import TelegramBot, format_signal_message


def build_signal_message(sig: dict, ts: str, macro: dict | None = None, reverse_levels: dict | None = None) -> str:
    payload = {**sig, "timestamp_utc": ts}
    if macro:
        payload["macro_state"] = macro.get("state", macro.get("news_sentiment", "uncertain"))
    if reverse_levels:
        payload["invalidation_level"] = reverse_levels.get("invalidation_level")
        payload["liquidity_context"] = reverse_levels.get("liquidity_level")
    return format_signal_message(payload)


def build_reverse_signal_message(new_signal, old_trade, timestamp, macro):
    return "REVERSE SETUP\n" + build_signal_message(new_signal, timestamp, macro)


def build_trade_alert_message(alert_type, trade, current_price):
    return f"Trade alert {alert_type}: {trade.get('direction')} {trade.get('entry')} at {current_price}"


async def send_message(token: str, chat_id: str, text: str, retries: int = 3):
    bot = TelegramBot(Settings(telegram_token=token, telegram_chat_id=chat_id))
    return bot.send_signal({"direction": "INFO", "symbol": "", "entry": "", "sl": "", "tp": "", "notes": text}).get("ok", False)
