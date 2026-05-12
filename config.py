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
    "send_approaching_alerts": True,
    "send_armed_reaction_alerts": True,
    "send_sweep_intrabar_alerts": True,
    "approaching_alert_distance_pips": 150,
    "armed_alert_distance_pips": 80,
    "imminent_reaction_distance_pips": 50,
    "allow_far_prep_alerts": True,
    "far_prep_alert_distance_pips": 250,
    "max_far_prep_alerts_per_session": 1,
    "reaction_alert_cooldown_minutes": 20,
    "max_alerts_per_zone_per_session": 3,
    "max_reaction_alerts_per_session": 5,
    "send_triggered_only": False,
    "min_normal_reaction_target_pips": 50,
    "preferred_reaction_target_pips": 100,
    "allow_vwap_1r_target": True,
    "min_vwap_target_pips": 30,
    "min_rr_normal": 1.5,
    "min_rr_vwap_scalp": 1.0,
    "enable_reentry_analysis": True,
    "reentry_max_wait_minutes": 30,
    "reentry_require_new_entry": True,
    "reentry_require_choch": True,
    "reentry_require_fvg_or_ifvg": True,
    "reentry_max_volatility_state": "elevated",
    "reentry_no_chase_max_distance_pips": 80,
}

TIMEFRAMES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def validate_env() -> list[str]:
    return load_settings().validate()


__all__ = ["CONFIG", "TIMEFRAMES", "Settings", "load_settings", "now_utc", "validate_env"]
