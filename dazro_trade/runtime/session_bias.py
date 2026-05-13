from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd

from dazro_trade.core.symbols import price_to_pips

SessionLabel = Literal[
    "ASIA_ACCUMULATION",
    "LONDON_OPENING_DRIVE",
    "LONDON_REVERSAL_OF_ASIA",
    "NY_CONTINUATION",
    "NY_MANIPULATION_REVERSAL",
    "NY_RANGE_INSIDE_LONDON",
    "UNCLEAR",
]

DirectionalBias = Literal["bullish", "bearish", "neutral"]
ActiveSession = Literal["asia", "london", "ny", "off_hours"]

ASIA_WINDOW_UTC = (time(0, 0), time(7, 0))
LONDON_WINDOW_UTC = (time(7, 0), time(12, 30))
NY_WINDOW_UTC = (time(12, 30), time(21, 0))


@dataclass(frozen=True)
class SessionStats:
    high: float
    low: float
    open: float
    close: float
    range_pips: float
    net_direction: DirectionalBias
    samples: int


@dataclass(frozen=True)
class SessionRelationship:
    label: SessionLabel
    active_session: ActiveSession
    previous_session: ActiveSession | None
    directional_bias: DirectionalBias
    confidence: float
    asia_range: dict
    london_range: dict
    ny_range: dict
    swept_level: str | None
    reason_codes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy().rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"})
    if not {"o", "h", "l", "c"}.issubset(out.columns):
        return pd.DataFrame()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], utc=True)
    return out


def _window_filter(df: pd.DataFrame, day: datetime, window: tuple[time, time]) -> pd.DataFrame:
    if df.empty or "time" not in df.columns:
        return df.iloc[0:0]
    start = datetime.combine(day.date(), window[0], tzinfo=timezone.utc)
    end = datetime.combine(day.date(), window[1], tzinfo=timezone.utc)
    return df[(df["time"] >= start) & (df["time"] < end)]


def _session_stats(df: pd.DataFrame, symbol: str) -> SessionStats | None:
    if df.empty:
        return None
    h = float(df["h"].max())
    l = float(df["l"].min())
    o = float(df["o"].iloc[0])
    c = float(df["c"].iloc[-1])
    range_pips = round(price_to_pips(symbol, h - l), 1)
    net_change = c - o
    threshold = (h - l) * 0.2
    if net_change > threshold:
        net = "bullish"
    elif net_change < -threshold:
        net = "bearish"
    else:
        net = "neutral"
    return SessionStats(high=h, low=l, open=o, close=c, range_pips=range_pips, net_direction=net, samples=int(len(df)))


def _empty_range() -> dict:
    return {"high": None, "low": None, "open": None, "close": None, "range_pips": 0.0, "net_direction": "neutral", "samples": 0}


def _stats_to_dict(stats: SessionStats | None) -> dict:
    if stats is None:
        return _empty_range()
    return {
        "high": round(stats.high, 2),
        "low": round(stats.low, 2),
        "open": round(stats.open, 2),
        "close": round(stats.close, 2),
        "range_pips": stats.range_pips,
        "net_direction": stats.net_direction,
        "samples": stats.samples,
    }


def _active_session(now_utc: datetime) -> ActiveSession:
    t = now_utc.astimezone(timezone.utc).time()
    if ASIA_WINDOW_UTC[0] <= t < ASIA_WINDOW_UTC[1]:
        return "asia"
    if LONDON_WINDOW_UTC[0] <= t < LONDON_WINDOW_UTC[1]:
        return "london"
    if NY_WINDOW_UTC[0] <= t < NY_WINDOW_UTC[1]:
        return "ny"
    return "off_hours"


def _previous_session(active: ActiveSession) -> ActiveSession | None:
    if active == "london":
        return "asia"
    if active == "ny":
        return "london"
    if active == "asia":
        return None
    return None


def classify_session_relationship(
    market_data: dict[str, pd.DataFrame],
    now_utc: datetime,
    *,
    symbol: str = "XAUUSD",
    timezone_name: str = "Europe/Rome",
    broker_time_offset_hours: int = 0,
    asia_range_max_pips: float = 35.0,
) -> SessionRelationship:
    m15 = _normalize(market_data.get("M15"))
    m5 = _normalize(market_data.get("M5"))
    intraday = m15 if not m15.empty else m5
    active = _active_session(now_utc)
    prev = _previous_session(active)

    asia = _session_stats(_window_filter(intraday, now_utc, ASIA_WINDOW_UTC), symbol)
    london = _session_stats(_window_filter(intraday, now_utc, LONDON_WINDOW_UTC), symbol)
    ny = _session_stats(_window_filter(intraday, now_utc, NY_WINDOW_UTC), symbol)

    reason: list[str] = []
    notes: list[str] = []
    label: SessionLabel = "UNCLEAR"
    bias: DirectionalBias = "neutral"
    confidence: float = 0.0
    swept_level: str | None = None

    if active == "asia":
        if asia is not None and asia.range_pips <= asia_range_max_pips:
            label = "ASIA_ACCUMULATION"
            bias = "neutral"
            confidence = 0.6
            reason.append(f"asia_range_pips={asia.range_pips}")
        else:
            label = "UNCLEAR"
            reason.append("asia_range_too_wide_or_no_data")
    elif active == "london" and asia is not None and london is not None:
        broke_asia_high = london.high > asia.high
        broke_asia_low = london.low < asia.low
        close_inside_asia = asia.low <= london.close <= asia.high
        if (broke_asia_high or broke_asia_low) and close_inside_asia:
            label = "LONDON_REVERSAL_OF_ASIA"
            bias = "bearish" if broke_asia_high else "bullish"
            confidence = 0.7
            swept_level = "asia_high" if broke_asia_high else "asia_low"
            reason.append(f"london_swept_{swept_level}_and_closed_back_inside_asia")
        elif (broke_asia_high or broke_asia_low) and not close_inside_asia:
            label = "LONDON_OPENING_DRIVE"
            bias = london.net_direction
            confidence = 0.75
            swept_level = "asia_high" if broke_asia_high else "asia_low"
            reason.append(f"london_broke_{swept_level}_no_reentry")
        else:
            label = "UNCLEAR"
            reason.append("london_inside_asia_no_breakout")
    elif active == "ny" and london is not None and ny is not None:
        broke_london_high = ny.high > london.high
        broke_london_low = ny.low < london.low
        close_inside_london = london.low <= ny.close <= london.high
        london_bias = london.net_direction
        if (broke_london_high or broke_london_low) and close_inside_london and ny.net_direction != london_bias and ny.net_direction != "neutral":
            label = "NY_MANIPULATION_REVERSAL"
            bias = ny.net_direction
            confidence = 0.75
            swept_level = "london_high" if broke_london_high else "london_low"
            reason.extend([f"ny_swept_{swept_level}", "ny_closed_back_inside_london", f"ny_direction_opposite_to_london_{london_bias}"])
        elif (broke_london_high or broke_london_low) and ny.net_direction == london_bias and london_bias != "neutral":
            label = "NY_CONTINUATION"
            bias = london_bias
            confidence = 0.8
            swept_level = "london_high" if broke_london_high else "london_low"
            reason.extend([f"ny_extended_past_{swept_level}", f"ny_direction_matches_london_{london_bias}"])
        elif not broke_london_high and not broke_london_low:
            label = "NY_RANGE_INSIDE_LONDON"
            bias = "neutral"
            confidence = 0.5
            reason.append("ny_inside_london_range")
        else:
            label = "UNCLEAR"
            reason.append("ny_breakout_without_clear_classification")
    else:
        reason.append(f"active_session_{active}_no_data")

    return SessionRelationship(
        label=label,
        active_session=active,
        previous_session=prev,
        directional_bias=bias,
        confidence=round(confidence, 2),
        asia_range=_stats_to_dict(asia),
        london_range=_stats_to_dict(london),
        ny_range=_stats_to_dict(ny),
        swept_level=swept_level,
        reason_codes=reason,
        notes=notes,
    )


def apply_session_bias_to_strategy(
    strategy_direction: str,
    relationship: SessionRelationship,
) -> dict:
    """Return a dict with 'effect' in {'boost', 'demote', 'warning', 'neutral'} and reason codes."""
    if relationship.label == "UNCLEAR":
        return {"effect": "neutral", "reason_codes": ["session_bias_unclear"]}
    if relationship.directional_bias == "neutral":
        return {"effect": "neutral", "reason_codes": [f"session_bias_neutral_label_{relationship.label}"]}

    desired = "bullish" if strategy_direction == "LONG" else "bearish"
    aligned = relationship.directional_bias == desired

    if relationship.label == "NY_MANIPULATION_REVERSAL" and not aligned:
        return {
            "effect": "demote",
            "reason_codes": ["ny_manipulation_against_strategy_direction", f"session_bias={relationship.label}"],
        }
    if relationship.label == "NY_CONTINUATION" and aligned:
        return {
            "effect": "boost",
            "reason_codes": ["ny_continuation_aligned_with_strategy", f"session_bias={relationship.label}"],
        }
    if aligned:
        return {
            "effect": "boost",
            "reason_codes": [f"session_bias_aligned_{relationship.label}"],
        }
    return {
        "effect": "warning",
        "reason_codes": [f"session_bias_opposes_strategy_{relationship.label}"],
    }


__all__ = [
    "SessionLabel",
    "SessionRelationship",
    "SessionStats",
    "classify_session_relationship",
    "apply_session_bias_to_strategy",
]
