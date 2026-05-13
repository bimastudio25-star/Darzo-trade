from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd

from dazro_trade.core.symbols import pips_to_price, price_to_pips

ExpansionDirection = Literal["LONG", "SHORT"]
TriggerKind = Literal["reclaim", "rejection", "aggressive_shift", "displacement"]
CandleModel = Literal["IMMEDIATE_EXPANSION", "ACCUMULATION_BEFORE_EXPANSION"]


@dataclass(frozen=True)
class SweepStatistics:
    mae_avg_pips: float
    max_excursion_pips: float
    avg_expansion_pips: float
    max_expansion_pips: float
    samples: int

    @property
    def insufficient(self) -> bool:
        return self.samples < 10


@dataclass(frozen=True)
class LiquidityReferenceLevels:
    h1_ref_high: float
    h1_ref_low: float
    m15_ref_high: float
    m15_ref_low: float
    h1_source: Literal["previous_h1", "range_dominant_h1"]
    m15_source: Literal["minute_45", "fallback_last_m15"]


@dataclass(frozen=True)
class LiquidityExpansionSignal:
    symbol: str
    direction: ExpansionDirection
    candle_model: CandleModel
    reference: LiquidityReferenceLevels
    stats: SweepStatistics
    entry: float
    stop: float
    tp1: float
    tp2: float
    tp3: float
    tp4: float
    tp1_basis: Literal["quartile_25", "avg_expansion_adaptive"]
    rr_tp1: float
    rr_tp4: float
    trigger_kind: TriggerKind
    reason_codes: list[str]
    timestamp_utc: datetime


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy().rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"})
    if not {"o", "h", "l", "c"}.issubset(out.columns):
        return pd.DataFrame()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], utc=True)
    return out


def _localize_minute(ts: pd.Timestamp, timezone_name: str) -> int | None:
    if timezone_name == "broker":
        return int(ts.minute)
    try:
        zone = ZoneInfo(timezone_name)
        return int(ts.tz_convert(zone).minute)
    except Exception:
        return None


def build_reference_levels(
    h1_df: pd.DataFrame,
    m15_df: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
    range_in_range_max_pips: float = 30.0,
    m15_reference_timezone: str = "broker",
) -> LiquidityReferenceLevels | None:
    h1 = _normalize(h1_df)
    m15 = _normalize(m15_df)
    if len(h1) < 2:
        return None

    closed_h1 = h1.iloc[:-1] if "time" in h1.columns and len(h1) >= 2 else h1
    if len(closed_h1) < 1:
        return None

    range_in_range_price = pips_to_price(symbol, range_in_range_max_pips)
    h1_source: Literal["previous_h1", "range_dominant_h1"] = "previous_h1"

    if len(closed_h1) >= 3:
        last_three = closed_h1.iloc[-3:]
        span = float(last_three["h"].max()) - float(last_three["l"].min())
        if span <= range_in_range_price:
            bodies = (last_three["c"].astype(float) - last_three["o"].astype(float)).abs()
            dominant_idx = int(bodies.idxmax())
            dominant_row = last_three.loc[dominant_idx]
            h1_ref_high = float(dominant_row["h"])
            h1_ref_low = float(dominant_row["l"])
            h1_source = "range_dominant_h1"
        else:
            prev = closed_h1.iloc[-1]
            h1_ref_high = float(prev["h"])
            h1_ref_low = float(prev["l"])
    else:
        prev = closed_h1.iloc[-1]
        h1_ref_high = float(prev["h"])
        h1_ref_low = float(prev["l"])

    if len(m15) == 0 or "time" not in m15.columns:
        return None

    latest_h1_open = pd.Timestamp(h1.iloc[-1]["time"]) if "time" in h1.columns else None
    if latest_h1_open is None:
        return None
    previous_h1_open = latest_h1_open - pd.Timedelta(hours=1)

    m15_in_prev = m15[(m15["time"] >= previous_h1_open) & (m15["time"] < latest_h1_open)]
    selected_m15: pd.Series | None = None
    m15_source: Literal["minute_45", "fallback_last_m15"] = "fallback_last_m15"

    for _, row in m15_in_prev.iterrows():
        minute = _localize_minute(pd.Timestamp(row["time"]), m15_reference_timezone)
        if minute == 45:
            selected_m15 = row
            m15_source = "minute_45"
            break

    if selected_m15 is None:
        before_h1 = m15[m15["time"] < latest_h1_open]
        if len(before_h1) == 0:
            return None
        selected_m15 = before_h1.iloc[-1]
        m15_source = "fallback_last_m15"

    return LiquidityReferenceLevels(
        h1_ref_high=h1_ref_high,
        h1_ref_low=h1_ref_low,
        m15_ref_high=float(selected_m15["h"]),
        m15_ref_low=float(selected_m15["l"]),
        h1_source=h1_source,
        m15_source=m15_source,
    )


def compute_h1_sweep_stats(
    h1_df: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
    lookback_h1: int = 60,
) -> SweepStatistics:
    h1 = _normalize(h1_df)
    if len(h1) < 4:
        return SweepStatistics(0.0, 0.0, 0.0, 0.0, 0)

    closed = h1.iloc[:-1] if "time" in h1.columns else h1
    closed = closed.tail(lookback_h1).reset_index(drop=True)
    if len(closed) < 4:
        return SweepStatistics(0.0, 0.0, 0.0, 0.0, 0)

    mae_samples: list[float] = []
    exp_samples_valid: list[float] = []
    exp_samples_all: list[float] = []

    for i in range(1, len(closed) - 2):
        prev_h = float(closed["h"].iloc[i - 1])
        prev_l = float(closed["l"].iloc[i - 1])
        cur_h = float(closed["h"].iloc[i])
        cur_l = float(closed["l"].iloc[i])
        next1_l = float(closed["l"].iloc[i + 1])
        next1_h = float(closed["h"].iloc[i + 1])
        next2_l = float(closed["l"].iloc[i + 2])
        next2_h = float(closed["h"].iloc[i + 2])
        next1_c = float(closed["c"].iloc[i + 1])
        next2_c = float(closed["c"].iloc[i + 2])

        if cur_h > prev_h:
            level = prev_h
            mae = max(0.0, cur_h - level)
            expansion = max(0.0, level - min(next1_l, next2_l))
            invalidated = next1_c > level or next2_c > level
            mae_samples.append(price_to_pips(symbol, mae))
            exp_samples_all.append(price_to_pips(symbol, expansion))
            if not invalidated:
                exp_samples_valid.append(price_to_pips(symbol, expansion))

        if cur_l < prev_l:
            level = prev_l
            mae = max(0.0, level - cur_l)
            expansion = max(0.0, max(next1_h, next2_h) - level)
            invalidated = next1_c < level or next2_c < level
            mae_samples.append(price_to_pips(symbol, mae))
            exp_samples_all.append(price_to_pips(symbol, expansion))
            if not invalidated:
                exp_samples_valid.append(price_to_pips(symbol, expansion))

    samples = len(mae_samples)
    if samples == 0:
        return SweepStatistics(0.0, 0.0, 0.0, 0.0, 0)

    mae_avg = sum(mae_samples) / samples
    max_exc = max(mae_samples)
    avg_exp = sum(exp_samples_valid) / len(exp_samples_valid) if exp_samples_valid else 0.0
    max_exp = max(exp_samples_all) if exp_samples_all else 0.0

    return SweepStatistics(
        mae_avg_pips=round(mae_avg, 2),
        max_excursion_pips=round(max_exc, 2),
        avg_expansion_pips=round(avg_exp, 2),
        max_expansion_pips=round(max_exp, 2),
        samples=samples,
    )


def _detect_trigger(
    m1: pd.DataFrame,
    m5: pd.DataFrame,
    direction: ExpansionDirection,
    h1_ref_low: float,
    h1_ref_high: float,
) -> TriggerKind | None:
    if len(m1) < 4:
        return None
    closed_m1 = m1.iloc[:-1] if "time" in m1.columns and len(m1) > 3 else m1
    if len(closed_m1) < 3:
        return None

    last3 = closed_m1.iloc[-3:]
    last = closed_m1.iloc[-1]
    prev = closed_m1.iloc[-2]

    o = float(last["o"])
    c = float(last["c"])
    h = float(last["h"])
    l = float(last["l"])
    body = abs(c - o)

    if direction == "LONG":
        if bool((last3["c"].astype(float) >= h1_ref_low).any()):
            return "reclaim"
        lower_wick = min(o, c) - l
        if body > 0 and lower_wick > body * 1.5 and c > o:
            return "rejection"
        if c > float(prev["h"]):
            return "aggressive_shift"
    else:
        if bool((last3["c"].astype(float) <= h1_ref_high).any()):
            return "reclaim"
        upper_wick = h - max(o, c)
        if body > 0 and upper_wick > body * 1.5 and c < o:
            return "rejection"
        if c < float(prev["l"]):
            return "aggressive_shift"

    closed_m5 = m5.iloc[:-1] if "time" in m5.columns and len(m5) > 6 else m5
    if len(closed_m5) >= 6:
        bodies_m5 = (closed_m5["c"].astype(float) - closed_m5["o"].astype(float)).abs()
        last_m5 = closed_m5.iloc[-1]
        avg_body = float(bodies_m5.iloc[-6:-1].mean() or 0.0)
        last_body = abs(float(last_m5["c"]) - float(last_m5["o"]))
        if avg_body > 0 and last_body >= avg_body * 1.2:
            bullish = float(last_m5["c"]) > float(last_m5["o"])
            if direction == "LONG" and bullish:
                return "displacement"
            if direction == "SHORT" and not bullish:
                return "displacement"

    return None


def _classify_candle_model(h1_df: pd.DataFrame) -> CandleModel:
    closed = h1_df.iloc[:-1] if "time" in h1_df.columns and len(h1_df) > 2 else h1_df
    if len(closed) < 2:
        return "IMMEDIATE_EXPANSION"
    a = closed.iloc[-2]
    b = closed.iloc[-1]
    a_h, a_l = float(a["h"]), float(a["l"])
    b_h, b_l = float(b["h"]), float(b["l"])
    overlap = min(a_h, b_h) >= max(a_l, b_l)
    if not overlap:
        return "IMMEDIATE_EXPANSION"
    body_a = abs(float(a["c"]) - float(a["o"]))
    body_b = abs(float(b["c"]) - float(b["o"]))
    range_a = max(a_h - a_l, 1e-9)
    range_b = max(b_h - b_l, 1e-9)
    ratio = max(body_a / range_a, body_b / range_b)
    if ratio < 0.6:
        return "ACCUMULATION_BEFORE_EXPANSION"
    return "IMMEDIATE_EXPANSION"


def evaluate_liquidity_expansion(
    m1_df: pd.DataFrame,
    m5_df: pd.DataFrame,
    m15_df: pd.DataFrame,
    h1_df: pd.DataFrame,
    *,
    current_price: float,
    symbol: str = "XAUUSD",
    lookback_h1: int = 60,
    range_in_range_max_pips: float = 30.0,
    m15_reference_timezone: str = "broker",
    now_utc: datetime | None = None,
) -> LiquidityExpansionSignal | None:
    m1 = _normalize(m1_df)
    m5 = _normalize(m5_df)
    m15 = _normalize(m15_df)
    h1 = _normalize(h1_df)
    if len(m1) == 0 or len(m5) == 0 or len(m15) == 0 or len(h1) < 2:
        return None
    if "time" not in m1.columns or "time" not in h1.columns:
        return None

    reference = build_reference_levels(
        h1, m15,
        symbol=symbol,
        range_in_range_max_pips=range_in_range_max_pips,
        m15_reference_timezone=m15_reference_timezone,
    )
    if reference is None:
        return None

    stats = compute_h1_sweep_stats(h1, symbol=symbol, lookback_h1=lookback_h1)
    if stats.insufficient:
        return None

    latest_h1_open = pd.Timestamp(h1.iloc[-1]["time"])
    current_window = m1[m1["time"] >= latest_h1_open]
    if len(current_window) == 0:
        return None

    high_m15_hits = current_window[current_window["h"].astype(float) >= reference.m15_ref_high]
    low_m15_hits = current_window[current_window["l"].astype(float) <= reference.m15_ref_low]
    high_h1_hits = current_window[current_window["h"].astype(float) >= reference.h1_ref_high]
    low_h1_hits = current_window[current_window["l"].astype(float) <= reference.h1_ref_low]

    t_high_m15 = pd.Timestamp(high_m15_hits.iloc[0]["time"]) if len(high_m15_hits) else None
    t_low_m15 = pd.Timestamp(low_m15_hits.iloc[0]["time"]) if len(low_m15_hits) else None
    t_high_h1 = pd.Timestamp(high_h1_hits.iloc[0]["time"]) if len(high_h1_hits) else None
    t_low_h1 = pd.Timestamp(low_h1_hits.iloc[0]["time"]) if len(low_h1_hits) else None

    long_valid = t_low_h1 is not None and (t_high_m15 is None or t_low_h1 <= t_high_m15)
    short_valid = t_high_h1 is not None and (t_low_m15 is None or t_high_h1 <= t_low_m15)

    direction: ExpansionDirection | None = None
    if long_valid and current_price <= reference.h1_ref_low - pips_to_price(symbol, stats.mae_avg_pips):
        direction = "LONG"
    elif short_valid and current_price >= reference.h1_ref_high + pips_to_price(symbol, stats.mae_avg_pips):
        direction = "SHORT"

    if direction is None:
        return None

    trigger = _detect_trigger(m1, m5, direction, reference.h1_ref_low, reference.h1_ref_high)
    if trigger is None:
        return None

    if direction == "LONG":
        level = reference.h1_ref_low
        stop = level - pips_to_price(symbol, stats.max_excursion_pips * 1.25)
        sign = 1.0
    else:
        level = reference.h1_ref_high
        stop = level + pips_to_price(symbol, stats.max_excursion_pips * 1.25)
        sign = -1.0

    quartile_25 = stats.max_expansion_pips * 0.25
    adaptive = stats.avg_expansion_pips < quartile_25
    tp1_pips = stats.avg_expansion_pips if adaptive else quartile_25
    tp1_basis: Literal["quartile_25", "avg_expansion_adaptive"] = (
        "avg_expansion_adaptive" if adaptive else "quartile_25"
    )

    tp1 = level + sign * pips_to_price(symbol, tp1_pips)
    tp2 = level + sign * pips_to_price(symbol, stats.max_expansion_pips * 0.50)
    tp3 = level + sign * pips_to_price(symbol, stats.max_expansion_pips * 0.75)
    tp4 = level + sign * pips_to_price(symbol, stats.max_expansion_pips * 1.00)

    entry = float(current_price)
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    rr_tp1 = abs(tp1 - entry) / risk
    rr_tp4 = abs(tp4 - entry) / risk

    candle_model = _classify_candle_model(h1)

    reason_codes = [
        "liquidity_expansion_model_2_0",
        f"trigger_{trigger}",
        f"h1_source_{reference.h1_source}",
        f"m15_source_{reference.m15_source}",
        f"candle_model_{candle_model.lower()}",
    ]
    if adaptive:
        reason_codes.append("adaptive_tp1_avg_expansion")

    return LiquidityExpansionSignal(
        symbol=symbol,
        direction=direction,
        candle_model=candle_model,
        reference=reference,
        stats=stats,
        entry=round(entry, 2),
        stop=round(stop, 2),
        tp1=round(tp1, 2),
        tp2=round(tp2, 2),
        tp3=round(tp3, 2),
        tp4=round(tp4, 2),
        tp1_basis=tp1_basis,
        rr_tp1=round(rr_tp1, 2),
        rr_tp4=round(rr_tp4, 2),
        trigger_kind=trigger,
        reason_codes=reason_codes,
        timestamp_utc=now_utc or datetime.now(timezone.utc),
    )


__all__ = [
    "SweepStatistics",
    "LiquidityReferenceLevels",
    "LiquidityExpansionSignal",
    "build_reference_levels",
    "compute_h1_sweep_stats",
    "evaluate_liquidity_expansion",
]
