from __future__ import annotations

from datetime import datetime, timezone

from dazro_trade.core.config import Settings, load_settings


CONFIG = {
    "symbol_candidates": ["XAUUSD", "XAUUSD.", "XAUUSDm", "GOLD"],
    "scan_interval": 120,
    "scan_interval_seconds": 120,
    "idle_interval": 300,
    "pip": 0.1,
    "sessions": ["Sydney", "Tokyo", "London", "New York"],
    "auto_signals_enabled": True,
    "send_auto_analysis_reports": False,
    "send_auto_watch_reports": False,
    "send_auto_zone_events": False,
    "send_auto_no_trade_messages": False,
    "max_alerts_per_scan": 1,
    "send_watch_alerts": False,
    "send_armed_reaction_alerts": True,
    "min_reaction_distance_pips": 80,
    "reaction_alert_cooldown_minutes": 15,
    "max_reaction_alerts_per_session": 5,
    "send_triggered_only": False,
}

TIMEFRAMES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def validate_env() -> list[str]:
    return load_settings().validate()


__all__ = ["CONFIG", "TIMEFRAMES", "Settings", "load_settings", "now_utc", "validate_env"]
