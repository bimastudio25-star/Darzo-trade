from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd


@dataclass(frozen=True)
class TimeBehaviourContext:
    timestamp_utc: datetime
    timestamp_local: datetime
    broker_time: datetime | None
    session_name: str
    minutes_from_session_open: int | None
    time_window: str
    expected_behaviours: list[str]
    manipulation_risk: str
    continuation_probability: str
    reversal_probability: str
    no_trade_risk: str
    reason_codes: list[str]

    def to_dict(self) -> dict:
        out = asdict(self)
        out["timestamp_utc"] = self.timestamp_utc.isoformat()
        out["timestamp_local"] = self.timestamp_local.isoformat()
        out["broker_time"] = self.broker_time.isoformat() if self.broker_time else None
        return out


def classify_time_behaviour(
    timestamp_utc: datetime,
    frames: dict[str, pd.DataFrame],
    session_ranges: dict | None = None,
    timezone: str = "Europe/Rome",
    broker_time_offset_hours: int = 0,
) -> TimeBehaviourContext:
    utc = _ensure_utc(timestamp_utc)
    local = utc.astimezone(ZoneInfo(timezone))
    broker_time = utc + timedelta(hours=broker_time_offset_hours) if broker_time_offset_hours else None
    clock = local.time()
    session_name, open_time, time_window, behaviours, reasons, manipulation, continuation, reversal, no_trade = _window_profile(clock)
    minutes = _minutes_from_open(local, open_time)
    return TimeBehaviourContext(
        timestamp_utc=utc,
        timestamp_local=local,
        broker_time=broker_time,
        session_name=session_name,
        minutes_from_session_open=minutes,
        time_window=time_window,
        expected_behaviours=behaviours,
        manipulation_risk=manipulation,
        continuation_probability=continuation,
        reversal_probability=reversal,
        no_trade_risk=no_trade,
        reason_codes=reasons,
    )


def _window_profile(clock: time) -> tuple[str, time | None, str, list[str], list[str], str, str, str, str]:
    if _between(clock, time(0, 0), time(2, 0)):
        return (
            "Asia",
            time(0, 0),
            "asia_early_range_building",
            ["range building", "liquidity accumulation", "false micro breakouts"],
            ["asia_range_building", "low_volatility_liquidity_accumulation", "false_micro_breakout_risk"],
            "medium",
            "low",
            "low",
            "medium",
        )
    if _between(clock, time(2, 0), time(4, 0)):
        return (
            "Asia",
            time(0, 0),
            "asia_expansion",
            ["asia range expansion", "pre-positioning", "micro liquidity sweep"],
            ["asia_expansion", "pre_london_positioning", "micro_liquidity_sweep_risk"],
            "medium",
            "medium",
            "low",
            "medium",
        )
    if _between(clock, time(7, 0), time(8, 0)):
        return (
            "Pre-London",
            time(7, 0),
            "pre_london",
            ["pre-London liquidity search", "fake move before open", "light stop hunt"],
            ["pre_london_liquidity_search", "pre_london_fake_move_risk"],
            "high",
            "medium",
            "medium",
            "medium",
        )
    if _between(clock, time(8, 0), time(10, 0)):
        return (
            "London Open",
            time(8, 0),
            "london_open",
            ["London manipulation", "Asia high/low sweep", "open drive continuation", "failed breakout", "distribution after manipulation"],
            ["london_open_window", "london_manipulation_risk", "asia_high_low_sweep_focus", "open_drive_possible", "distribution_possible_after_manipulation"],
            "high",
            "medium",
            "medium",
            "medium",
        )
    if _between(clock, time(11, 0), time(13, 0)):
        return (
            "Midday",
            time(11, 0),
            "midday",
            ["midday retrace", "VWAP/EMA retest", "liquidity rebalance", "chop/no trade risk"],
            ["midday_retrace_window", "vwap_reversion_possible", "ema_retest_possible", "no_trade_chop_risk"],
            "low",
            "low",
            "medium",
            "high",
        )
    if _between(clock, time(13, 0), time(14, 30)):
        return (
            "Pre-NY",
            time(13, 0),
            "pre_ny",
            ["pre-NY liquidity build", "London range preparation", "macro window preparation"],
            ["pre_ny_liquidity_build", "london_range_preparation"],
            "medium",
            "medium",
            "medium",
            "medium",
        )
    if _between(clock, time(14, 30), time(16, 0)):
        return (
            "NY Open",
            time(14, 30),
            "ny_open",
            ["NY manipulation", "London high/low sweep", "macro/news expansion", "London trend continuation", "HTF liquidity reversal"],
            ["ny_open_window", "ny_manipulation_risk", "london_high_low_sweep_focus", "ny_continuation_possible", "ny_news_volatility_risk"],
            "high",
            "medium",
            "medium",
            "high",
        )
    if _between(clock, time(16, 0), time(18, 0)):
        return (
            "NY PM",
            time(16, 0),
            "ny_pm",
            ["continuation runner", "profit taking", "VWAP mean reversion", "late range"],
            ["ny_pm_continuation_or_profit_taking", "late_session_vwap_reversion", "reduce_aggressiveness_after_main_move"],
            "low",
            "medium",
            "medium",
            "medium",
        )
    return (
        "Other",
        None,
        "off_peak",
        ["range building", "liquidity search", "selective trading only"],
        ["time_window_requires_extra_confirmation"],
        "medium",
        "low",
        "low",
        "medium",
    )


def _between(value: time, start: time, end: time) -> bool:
    return start <= value < end


def _minutes_from_open(local: datetime, open_time: time | None) -> int | None:
    if open_time is None:
        return None
    opened = datetime.combine(local.date(), open_time, tzinfo=local.tzinfo)
    return int((local - opened).total_seconds() // 60)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = ["TimeBehaviourContext", "classify_time_behaviour"]
