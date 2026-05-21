"""Research-only Adelin v3 composite candidate detector.

Adelin v3 is a strict multi-condition hypothesis. A candidate is emitted only
when C1-C5 are all satisfied with pre-anchor data. This module writes candidate
packs for later review/replay; it does not import or call live trading,
broker, order, or notification code.
"""
from __future__ import annotations

import bisect
import csv
import html
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from dazro_trade.backtest.data_loader import load_csv_timeframes
from dazro_trade.core.symbols import get_symbol_spec


DEFAULT_OUTPUT_DIR = Path("backtests/reports/adelin_v3_composite_candidate_pack")
SUPPORTED_TIMEFRAMES = ("M1", "M5", "M15", "H1", "H4", "D1")
RESEARCH_WARNING = "Research-only candidate windows. Not signals, not validation, not live trading."

LONG = "LONG"
SHORT = "SHORT"
SWING_HIGH = "SWING_HIGH"
SWING_LOW = "SWING_LOW"
DAILY_SWING = "DAILY_SWING"
H1_SWING = "H1_SWING"
FVG = "FVG"
IFVG = "IFVG"
VOLUME_CRACK = "VOLUME_CRACK"
LVN_SANDWICH = "LVN_SANDWICH"

V3_DECISION_CRITERIA_TEXT = """----- BEGIN PRE-REGISTERED V3 CRITERIA -----

When a replay is run on Adelin v3 candidates with matched controls:

VERDICT = CONTINUE_REFINEMENT
IF any of (with N >= 30 candidates):
  (a) candidate fast_reaction_rate >= control + 0.10
  (b) candidate runner_rate >= control + 0.07
  (c) candidate fast_sl20_rate <= control - 0.10

VERDICT = STOP_ARCHIVE_V3
IF for all metrics with N >= 30:
  |candidate - control| <= 0.04

VERDICT = INSUFFICIENT_SAMPLE
IF N < 30 candidates.
Default action: pause v3, no further iteration without a different hypothesis.

VERDICT = INCONCLUSIVE
Otherwise. Default action: pause.

----- END PRE-REGISTERED V3 CRITERIA -----"""


@dataclass(frozen=True)
class AdelinV3Config:
    symbol: str = "XAUUSD"
    data_dir: Path | str = Path("data")
    output_dir: Path | str = DEFAULT_OUTPUT_DIR
    from_date: datetime | None = None
    to_date: datetime | None = None
    max_candidates: int = 500
    max_examples: int = 120
    dry_run: bool = True
    sweep_lookback_minutes: int = 60
    min_sweep_anchor_delay_minutes: int = 5
    round_level_threshold_pips: float = 20.0
    reaction_zone_max_distance_pips: float = 50.0
    fvg_min_gap_pips: float = 5.0
    volume_crack_multiple: float = 2.5
    volume_crack_body_ratio: float = 0.70
    lvn_profile_hours: int = 24
    lvn_bin_pips: float = 5.0
    min_spacing_minutes: int = 60
    reaction_lookback_hours: int = 24


@dataclass(frozen=True)
class SwingLevel:
    level_id: str
    source: str
    timeframe: str
    level_type: str
    price: float
    swing_time: datetime
    formation_time: datetime
    known_at: datetime
    priority: str


@dataclass(frozen=True)
class SweepEvent:
    direction: str
    swept_level: SwingLevel
    sweep_timestamp: datetime
    sweep_price: float
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ReactionZone:
    zone_type: str
    zone_low: float
    zone_high: float
    detected_at: datetime
    source_timeframe: str
    confidence: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class V3Candidate:
    sample_id: str
    symbol: str
    anchor_timestamp: datetime
    direction: str
    c1_source: str
    c1_timeframe: str
    c1_priority: str
    c1_level_type: str
    c1_level_price: float
    c1_swing_time: datetime
    c1_known_at: datetime
    sweep_timestamp: datetime
    sweep_price: float
    reaction_zone_type: str
    reaction_zone_low: float
    reaction_zone_high: float
    reaction_zone_detected_at: datetime
    round_level: float
    round_distance_pips: float
    liquidity_confluence_config: str
    liquidity_confluence_distance_pips: float
    entry_level_price: float
    entry_level_source: str
    session: str
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...] = field(default_factory=tuple)
    chart_path: str = ""
    html_path: str = ""


def _to_path(value: Path | str) -> Path:
    return value if isinstance(value, Path) else Path(value)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _tf_delta(timeframe: str) -> timedelta:
    return {
        "M1": timedelta(minutes=1),
        "M5": timedelta(minutes=5),
        "M15": timedelta(minutes=15),
        "H1": timedelta(hours=1),
        "H4": timedelta(hours=4),
        "D1": timedelta(days=1),
    }[timeframe]


def _as_utc(value: Any) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize(timezone.utc)
    return ts.tz_convert(timezone.utc).to_pydatetime()


def _ensure_time(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], utc=True, errors="coerce")
    return out.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)


def _completed_before(df: pd.DataFrame, anchor: datetime, timeframe: str, *, delay_minutes: int = 0) -> pd.DataFrame:
    if df.empty:
        return df
    cutoff = pd.Timestamp(anchor - _tf_delta(timeframe) - timedelta(minutes=delay_minutes))
    out = _ensure_time(df)
    return out[out["time"] <= cutoff].copy().reset_index(drop=True)


def _window(df: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    if df.empty:
        return df
    out = _ensure_time(df)
    return out[(out["time"] >= pd.Timestamp(start)) & (out["time"] < pd.Timestamp(end))].copy().reset_index(drop=True)


def _fast_window(clean_df: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    if clean_df.empty:
        return clean_df
    times = clean_df["time"]
    left = times.searchsorted(pd.Timestamp(start), side="left")
    right = times.searchsorted(pd.Timestamp(end), side="left")
    return clean_df.iloc[left:right].copy().reset_index(drop=True)


def _price_distance_pips(price_a: float, price_b: float, pip_size: float) -> float:
    return round(abs(float(price_a) - float(price_b)) / pip_size, 4)


def nearest_v3_round_level(price: float) -> float:
    return round(math.floor(float(price) / 10.0 + 0.5) * 10.0, 2)


def round_confluence(price: float, pip_size: float, threshold_pips: float = 20.0) -> tuple[bool, float, float]:
    level = nearest_v3_round_level(price)
    distance = _price_distance_pips(price, level, pip_size)
    return distance <= threshold_pips, level, distance


def classify_v3_session(ts: datetime) -> str:
    minutes = ts.astimezone(timezone.utc).hour * 60 + ts.astimezone(timezone.utc).minute
    if 90 <= minutes < 180:
        return "ASIA_OPEN"
    if 510 <= minutes < 600:
        return "LONDON_OPEN"
    if 870 <= minutes < 960:
        return "NEW_YORK_OPEN"
    if 0 <= minutes < 420:
        return "ASIA"
    if 420 <= minutes < 780:
        return "LONDON"
    if 780 <= minutes < 1080:
        return "NEW_YORK"
    return "OTHER"


def detect_swing_levels(frames: Mapping[str, pd.DataFrame]) -> list[SwingLevel]:
    levels: list[SwingLevel] = []
    specs = (
        ("D1", DAILY_SWING, "HIGH", 1, timedelta(hours=24)),
        ("H1", H1_SWING, "MEDIUM", 2, timedelta(hours=6)),
    )
    for timeframe, source, priority, radius, _age in specs:
        df = _ensure_time(frames.get(timeframe, pd.DataFrame()))
        if len(df) < radius * 2 + 1:
            continue
        delta = _tf_delta(timeframe)
        for idx in range(radius, len(df) - radius):
            before = df.iloc[idx - radius:idx]
            after = df.iloc[idx + 1:idx + radius + 1]
            row = df.iloc[idx]
            swing_time = _as_utc(row["time"])
            formation_time = swing_time + delta
            known_at = _as_utc(df.iloc[idx + radius]["time"]) + delta
            high = float(row["high"])
            low = float(row["low"])
            if high > float(before["high"].max()) and high > float(after["high"].max()):
                levels.append(
                    SwingLevel(
                        f"{source}_{idx}_HIGH",
                        source,
                        timeframe,
                        SWING_HIGH,
                        round(high, 2),
                        swing_time,
                        formation_time,
                        known_at,
                        priority,
                    )
                )
            if low < float(before["low"].min()) and low < float(after["low"].min()):
                levels.append(
                    SwingLevel(
                        f"{source}_{idx}_LOW",
                        source,
                        timeframe,
                        SWING_LOW,
                        round(low, 2),
                        swing_time,
                        formation_time,
                        known_at,
                        priority,
                    )
                )
    return sorted(levels, key=lambda item: (item.known_at, item.source, item.price))


def _level_age_ok(level: SwingLevel, anchor: datetime) -> bool:
    min_age = timedelta(hours=24) if level.source == DAILY_SWING else timedelta(hours=6)
    return level.known_at < anchor and level.formation_time + min_age < anchor


def _eligible_levels(levels: Sequence[SwingLevel], anchor: datetime, pip_size: float, threshold_pips: float) -> list[SwingLevel]:
    out = []
    for level in levels:
        if not _level_age_ok(level, anchor):
            continue
        ok, _round, _distance = round_confluence(level.price, pip_size, threshold_pips)
        if ok:
            out.append(level)
    return out


def detect_sweep_event(
    frames: Mapping[str, pd.DataFrame],
    levels: Sequence[SwingLevel],
    anchor: datetime,
    *,
    pip_size: float,
    sweep_lookback_minutes: int = 60,
    min_anchor_delay_minutes: int = 5,
) -> SweepEvent | None:
    m5 = _completed_before(frames.get("M5", pd.DataFrame()), anchor, "M5", delay_minutes=min_anchor_delay_minutes)
    recent = _window(m5, anchor - timedelta(minutes=sweep_lookback_minutes + min_anchor_delay_minutes), anchor)
    return _detect_sweep_event_from_recent(recent, levels)


def _detect_sweep_event_from_recent(recent: pd.DataFrame, levels: Sequence[SwingLevel]) -> SweepEvent | None:
    if recent.empty:
        return None
    events: list[SweepEvent] = []
    recent_min = float(recent["low"].min())
    recent_max = float(recent["high"].max())
    for level in levels:
        if level.level_type == SWING_LOW and recent_min < level.price:
            hit = recent[recent["low"].astype(float) < level.price].iloc[0]
            events.append(
                SweepEvent(
                    LONG,
                    level,
                    _as_utc(hit["time"]),
                    round(float(hit["low"]), 2),
                    ("C1_SWING_LOW_SWEPT", "C5_LONG_FROM_LOW_SWEEP"),
                )
            )
        elif level.level_type == SWING_HIGH and recent_max > level.price:
            hit = recent[recent["high"].astype(float) > level.price].iloc[0]
            events.append(
                SweepEvent(
                    SHORT,
                    level,
                    _as_utc(hit["time"]),
                    round(float(hit["high"]), 2),
                    ("C1_SWING_HIGH_SWEPT", "C5_SHORT_FROM_HIGH_SWEEP"),
                )
            )
    if not events:
        return None
    return sorted(events, key=lambda item: (item.sweep_timestamp, 0 if item.swept_level.source == DAILY_SWING else 1))[0]


def _zone_beyond_level(zone_low: float, zone_high: float, event: SweepEvent, max_distance_pips: float, pip_size: float) -> bool:
    max_distance = max_distance_pips * pip_size
    level = event.swept_level.price
    if event.direction == LONG:
        return zone_high <= level and level - zone_high <= max_distance
    return zone_low >= level and zone_low - level <= max_distance


def _range_intersects_zone(row: pd.Series, zone_low: float, zone_high: float) -> bool:
    return float(row["low"]) <= zone_high and float(row["high"]) >= zone_low


def _last_usable_m5(frames: Mapping[str, pd.DataFrame], anchor: datetime, min_anchor_delay_minutes: int) -> pd.Series | None:
    m5 = _completed_before(frames.get("M5", pd.DataFrame()), anchor, "M5", delay_minutes=min_anchor_delay_minutes)
    if m5.empty:
        return None
    return m5.iloc[-1]


def _fvg_zones(
    frames: Mapping[str, pd.DataFrame],
    event: SweepEvent,
    anchor: datetime,
    *,
    pip_size: float,
    min_gap_pips: float,
    max_distance_pips: float,
    min_anchor_delay_minutes: int,
    reaction_lookback_hours: int,
    m5_context: pd.DataFrame | None = None,
) -> list[ReactionZone]:
    m5 = _ensure_time(m5_context) if m5_context is not None else _completed_before(frames.get("M5", pd.DataFrame()), anchor, "M5", delay_minutes=min_anchor_delay_minutes)
    m5 = _window(m5, anchor - timedelta(hours=reaction_lookback_hours), anchor)
    if len(m5) < 4:
        return []
    highs = m5["high"].astype(float).to_numpy()
    lows = m5["low"].astype(float).to_numpy()
    times = list(m5["time"])
    last_low = float(lows[-1])
    last_high = float(highs[-1])
    zones: list[ReactionZone] = []
    for idx in range(2, len(m5)):
        created_at = _as_utc(times[idx]) + _tf_delta("M5")
        if created_at >= anchor:
            continue
        bullish_gap = lows[idx] - highs[idx - 2]
        bearish_gap = lows[idx - 2] - highs[idx]
        if event.direction == LONG and bullish_gap >= min_gap_pips * pip_size:
            zone_low, zone_high = round(float(highs[idx - 2]), 2), round(float(lows[idx]), 2)
        elif event.direction == SHORT and bearish_gap >= min_gap_pips * pip_size:
            zone_low, zone_high = round(float(highs[idx]), 2), round(float(lows[idx - 2]), 2)
        else:
            continue
        if not _zone_beyond_level(zone_low, zone_high, event, max_distance_pips, pip_size):
            continue
        if not (last_low <= zone_high and last_high >= zone_low):
            continue
        later_lows = lows[idx + 1:-1]
        later_highs = highs[idx + 1:-1]
        touched_before_last = bool(((later_lows <= zone_high) & (later_highs >= zone_low)).any()) if len(later_lows) else False
        zone_type = IFVG if touched_before_last else FVG
        reason = (
            "C2_IFVG_LAST_COMPLETED_PRE_ANCHOR_RETEST"
            if zone_type == IFVG
            else "C2_FVG_FIRST_PRE_ANCHOR_TOUCH_UNMITIGATED_BEFORE_TOUCH"
        )
        zones.append(
            ReactionZone(
                zone_type,
                zone_low,
                zone_high,
                created_at,
                "M5",
                "MEDIUM" if zone_type == FVG else "LOW",
                (reason, "ANCHOR_CANDLE_EXCLUDED"),
            )
        )
    return zones


def _volume_crack_zones(
    frames: Mapping[str, pd.DataFrame],
    event: SweepEvent,
    anchor: datetime,
    *,
    pip_size: float,
    max_distance_pips: float,
    volume_multiple: float,
    body_ratio_min: float,
    min_anchor_delay_minutes: int,
    reaction_lookback_hours: int,
    m5_context: pd.DataFrame | None = None,
) -> list[ReactionZone]:
    m5 = _ensure_time(m5_context) if m5_context is not None else _completed_before(frames.get("M5", pd.DataFrame()), anchor, "M5", delay_minutes=min_anchor_delay_minutes)
    m5 = _window(m5, anchor - timedelta(hours=reaction_lookback_hours), anchor)
    if len(m5) < 21:
        return []
    highs = m5["high"].astype(float).to_numpy()
    lows = m5["low"].astype(float).to_numpy()
    opens = m5["open"].astype(float).to_numpy()
    closes = m5["close"].astype(float).to_numpy()
    times = list(m5["time"])
    last_low = float(lows[-1])
    last_high = float(highs[-1])
    zones: list[ReactionZone] = []
    volume_col = "tick_volume" if "tick_volume" in m5.columns else None
    if volume_col is None:
        return []
    volumes = m5[volume_col].astype(float).to_numpy()
    for idx in range(20, len(m5)):
        avg_volume = float(volumes[idx - 20:idx].mean())
        if avg_volume <= 0 or volumes[idx] < avg_volume * volume_multiple:
            continue
        high, low, open_, close = highs[idx], lows[idx], opens[idx], closes[idx]
        total_range = high - low
        if total_range <= 0:
            continue
        body_low, body_high = min(open_, close), max(open_, close)
        if (body_high - body_low) / total_range < body_ratio_min:
            continue
        if event.direction == LONG and close < open_ and low < event.swept_level.price:
            midpoint = body_low + (body_high - body_low) / 2.0
            zone_low, zone_high = round(body_low, 2), round(midpoint, 2)
        elif event.direction == SHORT and close > open_ and high > event.swept_level.price:
            midpoint = body_low + (body_high - body_low) / 2.0
            zone_low, zone_high = round(midpoint, 2), round(body_high, 2)
        else:
            continue
        if _zone_beyond_level(zone_low, zone_high, event, max_distance_pips, pip_size) and last_low <= zone_high and last_high >= zone_low:
            zones.append(
                ReactionZone(
                    VOLUME_CRACK,
                    zone_low,
                    zone_high,
                    _as_utc(times[idx]) + _tf_delta("M5"),
                    "M5",
                    "LOW",
                    ("C2_VOLUME_CRACK", "PRE_ANCHOR_VOLUME_AND_BODY_FILTERS"),
                )
            )
    return zones


def _lvn_sandwich_zones(
    frames: Mapping[str, pd.DataFrame],
    event: SweepEvent,
    anchor: datetime,
    *,
    pip_size: float,
    max_distance_pips: float,
    bin_pips: float,
    profile_hours: int,
    min_anchor_delay_minutes: int,
    m5_context: pd.DataFrame | None = None,
) -> list[ReactionZone]:
    m5 = _ensure_time(m5_context) if m5_context is not None else _completed_before(frames.get("M5", pd.DataFrame()), anchor, "M5", delay_minutes=min_anchor_delay_minutes)
    profile = _window(m5, anchor - timedelta(hours=profile_hours), anchor)
    if len(profile) < 50 or "tick_volume" not in profile.columns:
        return []
    bin_size = bin_pips * pip_size
    if bin_size <= 0:
        return []
    rows: Counter[int] = Counter()
    for row in profile.itertuples(index=False):
        mid = (float(row.high) + float(row.low) + float(row.close)) / 3.0
        rows[int(math.floor(mid / bin_size))] += int(getattr(row, "tick_volume", 0) or 0)
    if len(rows) < 5:
        return []
    volumes = sorted(rows.values())
    low_cut = volumes[max(0, int(len(volumes) * 0.20) - 1)]
    high_cut = volumes[min(len(volumes) - 1, int(math.ceil(len(volumes) * 0.80)) - 1)]
    bins = sorted(rows)
    zones: list[ReactionZone] = []
    idx = 0
    while idx < len(bins):
        if rows[bins[idx]] > low_cut:
            idx += 1
            continue
        start = idx
        while idx + 1 < len(bins) and bins[idx + 1] == bins[idx] + 1 and rows[bins[idx + 1]] <= low_cut:
            idx += 1
        end = idx
        if end - start + 1 >= 2:
            left_hvn = start > 0 and rows[bins[start - 1]] >= high_cut
            right_hvn = end + 1 < len(bins) and rows[bins[end + 1]] >= high_cut
            if left_hvn and right_hvn:
                zone_low = round(bins[start] * bin_size, 2)
                zone_high = round((bins[end] + 1) * bin_size, 2)
                if _zone_beyond_level(zone_low, zone_high, event, max_distance_pips, pip_size):
                    zones.append(
                        ReactionZone(
                            LVN_SANDWICH,
                            zone_low,
                            zone_high,
                            anchor - timedelta(minutes=min_anchor_delay_minutes),
                            "M5",
                            "LOW",
                            ("C2_LVN_SANDWICH_24H_PROFILE", "PROFILE_WINDOW_EXCLUDES_ANCHOR"),
                        )
                    )
        idx += 1
    return zones


def detect_reaction_zone(
    frames: Mapping[str, pd.DataFrame],
    event: SweepEvent,
    anchor: datetime,
    cfg: AdelinV3Config,
    pip_size: float,
    m5_context: pd.DataFrame | None = None,
) -> ReactionZone | None:
    zones: list[ReactionZone] = []
    zones.extend(
        _fvg_zones(
            frames,
            event,
            anchor,
            pip_size=pip_size,
            min_gap_pips=cfg.fvg_min_gap_pips,
            max_distance_pips=cfg.reaction_zone_max_distance_pips,
            min_anchor_delay_minutes=cfg.min_sweep_anchor_delay_minutes,
            reaction_lookback_hours=cfg.reaction_lookback_hours,
            m5_context=m5_context,
        )
    )
    zones.extend(
        _volume_crack_zones(
            frames,
            event,
            anchor,
            pip_size=pip_size,
            max_distance_pips=cfg.reaction_zone_max_distance_pips,
            volume_multiple=cfg.volume_crack_multiple,
            body_ratio_min=cfg.volume_crack_body_ratio,
            min_anchor_delay_minutes=cfg.min_sweep_anchor_delay_minutes,
            reaction_lookback_hours=cfg.reaction_lookback_hours,
            m5_context=m5_context,
        )
    )
    zones.extend(
        _lvn_sandwich_zones(
            frames,
            event,
            anchor,
            pip_size=pip_size,
            max_distance_pips=cfg.reaction_zone_max_distance_pips,
            bin_pips=cfg.lvn_bin_pips,
            profile_hours=cfg.lvn_profile_hours,
            min_anchor_delay_minutes=cfg.min_sweep_anchor_delay_minutes,
            m5_context=m5_context,
        )
    )
    if not zones:
        return None
    priority = {FVG: 0, IFVG: 1, VOLUME_CRACK: 2, LVN_SANDWICH: 3}
    return sorted(zones, key=lambda zone: (priority.get(zone.zone_type, 99), zone.detected_at))[0]


def _recent_external_liquidity(
    df: pd.DataFrame,
    anchor: datetime,
    timeframe: str,
    direction: str,
    pip_size: float,
    level_price: float,
    context: pd.DataFrame | None = None,
) -> float | None:
    complete = _ensure_time(context) if context is not None else _completed_before(df, anchor, timeframe, delay_minutes=5)
    if len(complete) < 8:
        return None
    recent = complete.tail(7)
    ref = recent.iloc[:-1]
    last = recent.iloc[-1]
    if direction == LONG:
        value = float(last["low"])
        if value < float(ref["low"].min()) and _price_distance_pips(value, level_price, pip_size) <= 10:
            return value
    else:
        value = float(last["high"])
        if value > float(ref["high"].max()) and _price_distance_pips(value, level_price, pip_size) <= 10:
            return value
    return None


def _h4_internal_near(h4_levels: Sequence[SwingLevel], anchor: datetime, direction: str, level_price: float, pip_size: float) -> float | None:
    for level in h4_levels:
        if level.known_at >= anchor:
            continue
        if direction == LONG and level.level_type != SWING_LOW:
            continue
        if direction == SHORT and level.level_type != SWING_HIGH:
            continue
        if _price_distance_pips(level.price, level_price, pip_size) <= 10:
            return level.price
    return None


def detect_h4_swing_levels(h4: pd.DataFrame) -> list[SwingLevel]:
    df = _ensure_time(h4)
    if len(df) < 5:
        return []
    out: list[SwingLevel] = []
    delta = _tf_delta("H4")
    for idx in range(2, len(df) - 2):
        row = df.iloc[idx]
        before = df.iloc[idx - 2:idx]
        after = df.iloc[idx + 1:idx + 3]
        swing_time = _as_utc(row["time"])
        known_at = _as_utc(df.iloc[idx + 2]["time"]) + delta
        if float(row["high"]) > float(before["high"].max()) and float(row["high"]) > float(after["high"].max()):
            out.append(SwingLevel(f"H4_{idx}_HIGH", "H4_INTERNAL", "H4", SWING_HIGH, round(float(row["high"]), 2), swing_time, swing_time + delta, known_at, "MEDIUM"))
        if float(row["low"]) < float(before["low"].min()) and float(row["low"]) < float(after["low"].min()):
            out.append(SwingLevel(f"H4_{idx}_LOW", "H4_INTERNAL", "H4", SWING_LOW, round(float(row["low"]), 2), swing_time, swing_time + delta, known_at, "MEDIUM"))
    return out


def _m15_sweep_level_near(
    frames: Mapping[str, pd.DataFrame],
    event: SweepEvent,
    anchor: datetime,
    pip_size: float,
    m15_context: pd.DataFrame | None = None,
) -> float | None:
    recent = _ensure_time(m15_context) if m15_context is not None else _window(
        _completed_before(frames.get("M15", pd.DataFrame()), anchor, "M15", delay_minutes=5),
        anchor - timedelta(hours=6),
        anchor,
    )
    if len(recent) < 5:
        return None
    for idx in range(2, len(recent)):
        prior = recent.iloc[:idx]
        row = recent.iloc[idx]
        if event.direction == LONG:
            prior_low = float(prior["low"].min())
            if float(row["low"]) < prior_low and _price_distance_pips(prior_low, event.swept_level.price, pip_size) <= 15:
                return prior_low
        else:
            prior_high = float(prior["high"].max())
            if float(row["high"]) > prior_high and _price_distance_pips(prior_high, event.swept_level.price, pip_size) <= 15:
                return prior_high
    return None


def detect_liquidity_confluence(
    frames: Mapping[str, pd.DataFrame],
    event: SweepEvent,
    anchor: datetime,
    pip_size: float,
    h4_levels: Sequence[SwingLevel] | None = None,
    m1_context: pd.DataFrame | None = None,
    m5_context: pd.DataFrame | None = None,
    m15_context: pd.DataFrame | None = None,
) -> tuple[bool, str, float, tuple[str, ...]]:
    if event.swept_level.source == DAILY_SWING:
        m15_level = _m15_sweep_level_near(frames, event, anchor, pip_size, m15_context=m15_context)
        if m15_level is not None:
            distance = _price_distance_pips(m15_level, event.swept_level.price, pip_size)
            return True, "CONFIG_B_DAILY_M15_SWEEP", distance, ("C4_CONFIG_B_DAILY_SWING_M15_SWEEP",)
    h4_level = _h4_internal_near(
        h4_levels if h4_levels is not None else detect_h4_swing_levels(frames.get("H4", pd.DataFrame())),
        anchor,
        event.direction,
        event.swept_level.price,
        pip_size,
    )
    if h4_level is not None:
        for tf, context in (("M5", m5_context), ("M1", m1_context)):
            ltf_level = _recent_external_liquidity(frames.get(tf, pd.DataFrame()), anchor, tf, event.direction, pip_size, h4_level, context=context)
            if ltf_level is not None:
                distance = _price_distance_pips(h4_level, ltf_level, pip_size)
                return True, f"CONFIG_A_H4_INTERNAL_{tf}_EXTERNAL", distance, ("C4_CONFIG_A_H4_INTERNAL_LTF_EXTERNAL",)
    return False, "NONE", 0.0, ("C4_MULTI_TF_LIQUIDITY_CONFLUENCE_MISSING",)


def _direction_consistent(event: SweepEvent, reaction_zone: ReactionZone) -> bool:
    if event.direction == LONG:
        return event.swept_level.level_type == SWING_LOW and reaction_zone.zone_high <= event.swept_level.price
    return event.swept_level.level_type == SWING_HIGH and reaction_zone.zone_low >= event.swept_level.price


def _candidate_row(candidate: V3Candidate) -> dict[str, Any]:
    return {
        "sample_id": candidate.sample_id,
        "symbol": candidate.symbol,
        "anchor_timestamp": candidate.anchor_timestamp.isoformat(),
        "direction": candidate.direction,
        "c1_source": candidate.c1_source,
        "c1_timeframe": candidate.c1_timeframe,
        "c1_priority": candidate.c1_priority,
        "c1_level_type": candidate.c1_level_type,
        "c1_level_price": candidate.c1_level_price,
        "c1_swing_time": candidate.c1_swing_time.isoformat(),
        "c1_known_at": candidate.c1_known_at.isoformat(),
        "sweep_timestamp": candidate.sweep_timestamp.isoformat(),
        "sweep_price": candidate.sweep_price,
        "reaction_zone_type": candidate.reaction_zone_type,
        "reaction_zone_low": candidate.reaction_zone_low,
        "reaction_zone_high": candidate.reaction_zone_high,
        "reaction_zone_detected_at": candidate.reaction_zone_detected_at.isoformat(),
        "round_level": candidate.round_level,
        "round_distance_pips": candidate.round_distance_pips,
        "liquidity_confluence_config": candidate.liquidity_confluence_config,
        "liquidity_confluence_distance_pips": candidate.liquidity_confluence_distance_pips,
        "entry_level_price": candidate.entry_level_price,
        "entry_level_source": candidate.entry_level_source,
        "session": candidate.session,
        "chart_path": candidate.chart_path,
        "html_path": candidate.html_path,
        "reason_codes": "|".join(candidate.reason_codes),
        "limitations": "|".join(candidate.limitations),
    }


CSV_FIELDS = list(_candidate_row(
    V3Candidate(
        "sample_000",
        "XAUUSD",
        datetime(2000, 1, 1, tzinfo=timezone.utc),
        LONG,
        DAILY_SWING,
        "D1",
        "HIGH",
        SWING_LOW,
        0.0,
        datetime(2000, 1, 1, tzinfo=timezone.utc),
        datetime(2000, 1, 1, tzinfo=timezone.utc),
        datetime(2000, 1, 1, tzinfo=timezone.utc),
        0.0,
        FVG,
        0.0,
        0.0,
        datetime(2000, 1, 1, tzinfo=timezone.utc),
        0.0,
        0.0,
        "CONFIG_B",
        0.0,
        0.0,
        FVG,
        "OTHER",
        (),
    )
).keys())


def _svg_chart(candidate: V3Candidate, frames: Mapping[str, pd.DataFrame], output_dir: Path) -> str:
    charts = output_dir / "charts"
    charts.mkdir(parents=True, exist_ok=True)
    rel = f"charts/{candidate.sample_id}.svg"
    path = output_dir / rel
    m5 = _window(frames.get("M5", pd.DataFrame()), candidate.anchor_timestamp - timedelta(hours=2), candidate.anchor_timestamp + timedelta(hours=2))
    width, height = 900, 320
    if m5.empty:
        path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"><text x="20" y="40">No M5 candles available.</text></svg>', encoding="utf-8")
        return rel
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    min_p, max_p = float(lows.min()), float(highs.max())
    pad = max((max_p - min_p) * 0.08, 1.0)
    min_p -= pad
    max_p += pad

    def x_for(i: int) -> float:
        return 40 + i * (width - 80) / max(len(m5) - 1, 1)

    def y_for(price: float) -> float:
        return 20 + (max_p - price) * (height - 60) / max(max_p - min_p, 1e-9)

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fbfbf8"/>',
        f'<text x="40" y="18" font-family="Arial" font-size="13">{html.escape(candidate.sample_id)} {candidate.direction} {candidate.reaction_zone_type}</text>',
    ]
    candle_w = max(3, (width - 90) / max(len(m5), 1) * 0.55)
    for i, row in enumerate(m5.itertuples(index=False)):
        open_, high, low, close = float(row.open), float(row.high), float(row.low), float(row.close)
        x = x_for(i)
        color = "#176c4c" if close >= open_ else "#a23a3a"
        elements.append(f'<line x1="{x:.2f}" x2="{x:.2f}" y1="{y_for(high):.2f}" y2="{y_for(low):.2f}" stroke="{color}" stroke-width="1"/>')
        y = min(y_for(open_), y_for(close))
        h = max(abs(y_for(open_) - y_for(close)), 1.5)
        elements.append(f'<rect x="{x - candle_w/2:.2f}" y="{y:.2f}" width="{candle_w:.2f}" height="{h:.2f}" fill="{color}" opacity="0.82"/>')
    level_y = y_for(candidate.c1_level_price)
    zone_y1 = y_for(candidate.reaction_zone_high)
    zone_y2 = y_for(candidate.reaction_zone_low)
    elements.append(f'<line x1="40" x2="{width-40}" y1="{level_y:.2f}" y2="{level_y:.2f}" stroke="#111827" stroke-dasharray="5 4"/>')
    elements.append(f'<rect x="40" y="{min(zone_y1, zone_y2):.2f}" width="{width-80}" height="{max(abs(zone_y2-zone_y1), 2):.2f}" fill="#d97706" opacity="0.20"/>')
    elements.append(f'<text x="45" y="{max(35, level_y-6):.2f}" font-family="Arial" font-size="11">C1 {candidate.c1_level_price}</text>')
    elements.append(f'<text x="45" y="{max(50, min(zone_y1, zone_y2)-6):.2f}" font-family="Arial" font-size="11">{candidate.reaction_zone_type}</text>')
    elements.append("</svg>")
    path.write_text("\n".join(elements), encoding="utf-8")
    return rel


def _sample_html(candidate: V3Candidate, output_dir: Path) -> str:
    examples = output_dir / "examples"
    examples.mkdir(parents=True, exist_ok=True)
    rel = f"examples/{candidate.sample_id}.html"
    rows = _candidate_row(candidate)
    meta = "\n".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in rows.items()
    )
    text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(candidate.sample_id)} - Adelin v3 Composite Candidate</title>
  <style>
    body {{ font-family: Arial, Helvetica, sans-serif; margin: 24px; color: #172033; }}
    .warning {{ border-left: 5px solid #b91c1c; background: #fff1f2; padding: 12px; font-weight: 700; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border: 1px solid #d6d3ca; padding: 7px; text-align: left; font-size: 13px; }}
    th {{ width: 260px; background: #eceee8; }}
  </style>
</head>
<body>
  <h1>Adelin v3 Composite Candidate</h1>
  <p class="warning">{html.escape(RESEARCH_WARNING)}</p>
  <img src="../{html.escape(candidate.chart_path)}" alt="M5 chart for {html.escape(candidate.sample_id)}" style="max-width:100%;height:auto;">
  <table>{meta}</table>
</body>
</html>
"""
    (output_dir / rel).write_text(text, encoding="utf-8")
    return rel


def _write_index(candidates: Sequence[V3Candidate], summary: Mapping[str, Any], output_dir: Path) -> None:
    rows = []
    for candidate in candidates:
        rows.append(
            "<tr>"
            f"<td>{html.escape(candidate.sample_id)}</td>"
            f"<td>{html.escape(candidate.anchor_timestamp.isoformat())}</td>"
            f"<td>{html.escape(candidate.direction)}</td>"
            f"<td>{html.escape(candidate.c1_source)}</td>"
            f"<td>{html.escape(candidate.reaction_zone_type)}</td>"
            f"<td>{html.escape(candidate.liquidity_confluence_config)}</td>"
            f"<td>{html.escape(candidate.session)}</td>"
            f'<td><a href="{html.escape(candidate.html_path)}">html</a></td>'
            f'<td><a href="{html.escape(candidate.chart_path)}">svg</a></td>'
            "</tr>"
        )
    text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Adelin v3 Composite Candidate Pack</title>
  <style>
    body {{ font-family: Arial, Helvetica, sans-serif; margin: 24px; color: #172033; }}
    .warning {{ border-left: 5px solid #b91c1c; background: #fff1f2; padding: 12px; font-weight: 700; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border: 1px solid #d6d3ca; padding: 7px; text-align: left; font-size: 13px; }}
    th {{ background: #eceee8; }}
  </style>
</head>
<body>
  <h1>Adelin v3 Composite Candidate Pack</h1>
  <p class="warning">{html.escape(RESEARCH_WARNING)}</p>
  <p>Composite detector: C1 sweepable D1/H1 swing, C2 reaction zone beyond sweep, C3 number confluence, C4 multi-timeframe liquidity confluence, C5 unambiguous reversal direction. No replay and no matched controls in this branch.</p>
  <h2>Summary</h2>
  <pre>{html.escape(json.dumps(summary, indent=2, sort_keys=True, default=str))}</pre>
  <h2>Candidates</h2>
  <table>
    <tr><th>sample</th><th>anchor</th><th>direction</th><th>C1</th><th>reaction</th><th>C4</th><th>session</th><th>html</th><th>svg</th></tr>
    {''.join(rows)}
  </table>
</body>
</html>
"""
    (output_dir / "index.html").write_text(text, encoding="utf-8")


def _write_readme(output_dir: Path, summary: Mapping[str, Any]) -> None:
    text = [
        "# Adelin v3 Composite Candidate Pack",
        "",
        "Research-only. Candidate windows are not signals and this pack is not validation.",
        "",
        "This pack requires all hard C1-C5 conditions simultaneously. It does not run matched-control replay.",
        "",
        f"- candidates: `{summary['candidate_count']}`",
        f"- generation verdict: `{summary['candidate_pack_verdict']}`",
        "",
        "If candidates are fewer than 30, the registered next action is `INSUFFICIENT_SAMPLE` and replay should not be run.",
    ]
    (output_dir / "README.md").write_text("\n".join(text) + "\n", encoding="utf-8")


def _summary(candidates: Sequence[V3Candidate], rejections: Counter[str], cfg: AdelinV3Config, started: datetime, frames: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
    candidate_count = len(candidates)
    if candidate_count < 30:
        verdict = "INSUFFICIENT_SAMPLE"
        next_step = "Pause v3; do not run matched-control replay."
    else:
        verdict = "READY_FOR_MATCHED_CONTROL_REPLAY"
        next_step = "Create feat/adelin-v3-candidate-pack-matched-control-replay and apply locked v3 criteria."
    time_ranges: dict[str, dict[str, str]] = {}
    for tf, df in frames.items():
        clean = _ensure_time(df)
        if clean.empty:
            continue
        time_ranges[tf] = {
            "start": _as_utc(clean.iloc[0]["time"]).isoformat(),
            "end": _as_utc(clean.iloc[-1]["time"]).isoformat(),
            "rows": str(len(clean)),
        }
    return {
        "run_started_at": started.isoformat(),
        "run_finished_at": _utc_now().isoformat(),
        "symbol": cfg.symbol,
        "output_dir": str(cfg.output_dir),
        "dry_run": bool(cfg.dry_run),
        "candidate_count": candidate_count,
        "candidate_pack_verdict": verdict,
        "recommended_next_step": next_step,
        "source_counts": dict(Counter(candidate.c1_source for candidate in candidates)),
        "direction_counts": dict(Counter(candidate.direction for candidate in candidates)),
        "reaction_zone_counts": dict(Counter(candidate.reaction_zone_type for candidate in candidates)),
        "liquidity_confluence_counts": dict(Counter(candidate.liquidity_confluence_config for candidate in candidates)),
        "session_counts": dict(Counter(candidate.session for candidate in candidates)),
        "rejection_counts": dict(sorted(rejections.items())),
        "time_ranges": time_ranges,
        "pre_registered_decision_criteria": V3_DECISION_CRITERIA_TEXT,
        "anti_lookahead_guarantees": [
            "C1 D1/H1 swings require known_at < anchor and configured age before anchor.",
            "Sweep candles must close at least 5 minutes before anchor.",
            "FVG/IFVG/volume crack/LVN sandwich use pre-anchor M5 candles only.",
            "IFVG retest requires the last completed pre-anchor M5 candle; anchor candle retests are rejected.",
            "24h volume profile uses [anchor - 24h, anchor) with completed pre-anchor candles.",
        ],
        "limitations": [
            "Deterministic proxies approximate discretionary Adelin v3 judgment.",
            "Matched-control replay is intentionally deferred.",
            "No thresholds are optimized in this branch.",
            *([] if candidate_count >= 30 else ["CANDIDATE_COUNT_BELOW_30_REPLAY_GATE"]),
        ],
        "safety": {
            "live_trading_enabled": False,
            "telegram_enabled": False,
            "broker_execution_enabled": False,
            "order_execution_enabled": False,
            "strategy_2_touched": False,
            "strategy_3_touched": False,
            "data_modified": False,
        },
    }


def generate_v3_candidate_pack(cfg: AdelinV3Config) -> dict[str, Any]:
    started = _utc_now()
    output_dir = _to_path(cfg.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = load_csv_timeframes(
        cfg.symbol,
        list(SUPPORTED_TIMEFRAMES),
        data_dir=str(cfg.data_dir),
        date_from=cfg.from_date,
        date_to=cfg.to_date,
    )
    pip_size = get_symbol_spec(cfg.symbol).pip_size
    c1_levels = detect_swing_levels(frames)
    h4_levels = detect_h4_swing_levels(frames.get("H4", pd.DataFrame()))
    m1_clean = _ensure_time(frames.get("M1", pd.DataFrame()))
    m15_clean = _ensure_time(frames.get("M15", pd.DataFrame()))
    c1_round_levels = [
        level
        for level in c1_levels
        if round_confluence(level.price, pip_size, cfg.round_level_threshold_pips)[0]
    ]
    price_sorted_levels = sorted((level.price, idx, level) for idx, level in enumerate(c1_round_levels))
    sorted_prices = [item[0] for item in price_sorted_levels]
    m5 = _ensure_time(frames.get("M5", pd.DataFrame()))
    candidates: list[V3Candidate] = []
    rejections: Counter[str] = Counter()
    used_keys: set[tuple[str, str, str]] = set()
    last_anchor: datetime | None = None
    if m5.empty:
        rejections["MISSING_M5_DATA"] += 1
    lookback_candles = max(3, int(math.ceil((cfg.sweep_lookback_minutes + cfg.min_sweep_anchor_delay_minutes) / 5.0)) + 2)
    for idx, row in enumerate(m5.itertuples(index=False)):
        anchor = _as_utc(row.time) + timedelta(minutes=10)
        if cfg.from_date and anchor < cfg.from_date:
            continue
        if cfg.to_date and anchor > cfg.to_date:
            continue
        if last_anchor and anchor - last_anchor < timedelta(minutes=cfg.min_spacing_minutes):
            rejections["MIN_SPACING_FILTER"] += 1
            continue
        recent = m5.iloc[max(0, idx - lookback_candles + 1):idx + 1].copy()
        if recent.empty:
            rejections["C1_NO_RECENT_PRE_ANCHOR_SWEEP"] += 1
            continue
        recent_low = float(recent["low"].min())
        recent_high = float(recent["high"].max())
        left = bisect.bisect_left(sorted_prices, recent_low)
        right = bisect.bisect_right(sorted_prices, recent_high)
        price_window_levels = [item[2] for item in price_sorted_levels[left:right]]
        eligible = [level for level in price_window_levels if _level_age_ok(level, anchor)]
        if not eligible:
            rejections["C1_OR_C3_NO_ELIGIBLE_AGED_ROUND_SWING"] += 1
            continue
        event = _detect_sweep_event_from_recent(recent, eligible)
        if event is None:
            rejections["C1_NO_RECENT_PRE_ANCHOR_SWEEP"] += 1
            continue
        m5_context = m5.iloc[max(0, idx - int(math.ceil(cfg.reaction_lookback_hours * 60 / 5)) - 2):idx + 1].copy()
        reaction = detect_reaction_zone(frames, event, anchor, cfg, pip_size, m5_context=m5_context)
        if reaction is None:
            rejections["C2_REACTION_ZONE_MISSING"] += 1
            continue
        if not _direction_consistent(event, reaction):
            rejections["C5_DIRECTION_REACTION_BOUNDS_CONFLICT"] += 1
            continue
        m1_context = _fast_window(m1_clean, anchor - timedelta(minutes=30), anchor - timedelta(minutes=cfg.min_sweep_anchor_delay_minutes))
        m15_context = _fast_window(m15_clean, anchor - timedelta(hours=6), anchor - timedelta(minutes=cfg.min_sweep_anchor_delay_minutes))
        ok_c4, c4_config, c4_distance, c4_reasons = detect_liquidity_confluence(
            frames,
            event,
            anchor,
            pip_size,
            h4_levels,
            m1_context=m1_context,
            m5_context=m5_context,
            m15_context=m15_context,
        )
        if not ok_c4:
            rejections["C4_MULTI_TF_CONFLUENCE_MISSING"] += 1
            continue
        _ok_round, round_level, round_distance = round_confluence(event.swept_level.price, pip_size, cfg.round_level_threshold_pips)
        key = (event.swept_level.level_id, reaction.zone_type, anchor.date().isoformat())
        if key in used_keys:
            rejections["DUPLICATE_LEVEL_REACTION_DAY"] += 1
            continue
        sample_id = f"v3_sample_{len(candidates) + 1:03d}"
        candidate = V3Candidate(
            sample_id=sample_id,
            symbol=cfg.symbol,
            anchor_timestamp=anchor,
            direction=event.direction,
            c1_source=event.swept_level.source,
            c1_timeframe=event.swept_level.timeframe,
            c1_priority=event.swept_level.priority,
            c1_level_type=event.swept_level.level_type,
            c1_level_price=event.swept_level.price,
            c1_swing_time=event.swept_level.swing_time,
            c1_known_at=event.swept_level.known_at,
            sweep_timestamp=event.sweep_timestamp,
            sweep_price=event.sweep_price,
            reaction_zone_type=reaction.zone_type,
            reaction_zone_low=reaction.zone_low,
            reaction_zone_high=reaction.zone_high,
            reaction_zone_detected_at=reaction.detected_at,
            round_level=round_level,
            round_distance_pips=round_distance,
            liquidity_confluence_config=c4_config,
            liquidity_confluence_distance_pips=c4_distance,
            entry_level_price=round((reaction.zone_low + reaction.zone_high) / 2.0, 2),
            entry_level_source=reaction.zone_type,
            session=classify_v3_session(anchor),
            reason_codes=(
                "C1_AGED_D1_OR_H1_SWING",
                *event.reason_codes,
                *reaction.reason_codes,
                "C3_NUMBER_THEORY_CONFLUENCE",
                *c4_reasons,
                "C5_DIRECTION_INFERENCE_UNAMBIGUOUS_BEYOND_SWEEP",
            ),
        )
        candidate = V3Candidate(**{**candidate.__dict__, "chart_path": _svg_chart(candidate, frames, output_dir)})
        candidate = V3Candidate(**{**candidate.__dict__, "html_path": _sample_html(candidate, output_dir)})
        candidates.append(candidate)
        used_keys.add(key)
        last_anchor = anchor
        if len(candidates) >= cfg.max_candidates:
            rejections["MAX_CANDIDATES_REACHED"] += 1
            break

    with (output_dir / "candidate_pack.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(_candidate_row(candidate))

    with (output_dir / "rejection_breakdown.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["reason", "count"])
        writer.writeheader()
        for reason, count in sorted(rejections.items()):
            writer.writerow({"reason": reason, "count": count})

    summary = _summary(candidates, rejections, cfg, started, frames)
    (output_dir / "generation_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    (output_dir / "decision_criteria.md").write_text(V3_DECISION_CRITERIA_TEXT + "\n", encoding="utf-8")
    _write_index(candidates, summary, output_dir)
    _write_readme(output_dir, summary)
    return summary


__all__ = [
    "AdelinV3Config",
    "DAILY_SWING",
    "FVG",
    "H1_SWING",
    "IFVG",
    "LONG",
    "LVN_SANDWICH",
    "SHORT",
    "V3_DECISION_CRITERIA_TEXT",
    "VOLUME_CRACK",
    "detect_reaction_zone",
    "detect_sweep_event",
    "detect_swing_levels",
    "generate_v3_candidate_pack",
    "nearest_v3_round_level",
    "round_confluence",
]
