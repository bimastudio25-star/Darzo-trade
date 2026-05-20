from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable, Literal

import pandas as pd

from dazro_trade.analysis.strategy_2_liquidity_expansion_stats import normalize_ohlc, percentile
from dazro_trade.analytics.strategy_2_hourly_session_diagnostics import derived_session_from_hour


Direction = Literal["LONG", "SHORT"]
ReferenceMode = Literal["previous", "dominant", "both"]
ReferenceType = Literal["previous_h1", "dominant_h1"]

VALID_STATUSES = {"VALID_SAMPLE_TRADE_TRIGGERED", "VALID_SAMPLE_NO_ENTRY_MANIPULATED_LESS"}

SAMPLE_FIELDS = [
    "sample_id",
    "symbol",
    "direction",
    "h1_context_timestamp",
    "h1_reference_type",
    "h1_reference_timestamp",
    "h1_reference_high",
    "h1_reference_low",
    "h1_reference_range",
    "h1_reference_range_bucket",
    "h1_liquidity_level",
    "h1_liquidity_side",
    "m15_x45_timestamp",
    "m15_x45_high",
    "m15_x45_low",
    "m15_x45_sequence_valid",
    "m15_x45_sequence_reason",
    "opposite_m15_x45_taken_timestamp",
    "h1_sweep_timestamp",
    "opposite_h1_side_taken_before_sweep",
    "distribution_timestamp",
    "reaction_confirmed",
    "reaction_type",
    "reaction_timestamp",
    "reaction_latency_candles",
    "distribution_confirmed",
    "distribution_distance_price",
    "distribution_distance_usd",
    "distribution_distance_pips",
    "manipulation_depth_price",
    "manipulation_depth_usd",
    "manipulation_depth_pips",
    "conversion_factor_used",
    "sample_status",
    "sample_reason_codes",
    "would_trigger_current_mae_entry",
    "current_mae_entry_threshold_price",
    "valid_for_mae_dataset",
    "candle_development_model",
    "session",
    "hour",
]


SAFETY = {
    "research_only": True,
    "dry_run": True,
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "broker_called": False,
    "order_sent": False,
    "order_send_called": False,
    "data_files_written": False,
}


@dataclass(frozen=True)
class StatisticalRecorderConfig:
    symbol: str = "XAUUSD"
    pip_factor: float = 10.0
    h1_reference_mode: ReferenceMode = "both"
    dominant_contained_count: int = 2
    reaction_window_m5: int = 5
    min_context_sample: int = 20
    min_manipulation_price: float = 0.1
    min_distribution_price: float = 1.0
    risk_guardrail_usd: float = 12.0


def _timestamp(value: Any) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _timestamp_text(value: Any) -> str | None:
    ts = _timestamp(value)
    return ts.isoformat() if ts is not None else None


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(float(value), digits) if value is not None else None


def _mean(values: Iterable[float]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(fmean(vals), 4) if vals else None


def _median(values: Iterable[float]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(median(vals), 4) if vals else None


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def price_to_pips(distance: float | None, pip_factor: float) -> float | None:
    if distance is None:
        return None
    return round(float(distance) * float(pip_factor), 4)


def pips_to_price(pips: float | None, pip_factor: float) -> float | None:
    if pips is None or pip_factor == 0:
        return None
    return round(float(pips) / float(pip_factor), 4)


def select_m15_x45(m15: pd.DataFrame, h1_open_time: Any) -> dict[str, Any] | None:
    frame = normalize_ohlc(m15)
    h1_ts = _timestamp(h1_open_time)
    if frame.empty or h1_ts is None:
        return None
    hour_end = h1_ts + pd.Timedelta(hours=1)
    candidates = frame[(frame["time"] >= h1_ts) & (frame["time"] < hour_end) & (frame["time"].dt.minute == 45)]
    if candidates.empty:
        return None
    row = candidates.iloc[0]
    return {
        "m15_x45_timestamp": _timestamp_text(row["time"]),
        "m15_x45_high": round(float(row["high"]), 4),
        "m15_x45_low": round(float(row["low"]), 4),
    }


def first_touch_time(
    frame: pd.DataFrame,
    *,
    level: float,
    side: Literal["high", "low"],
    start: Any | None = None,
    end: Any | None = None,
) -> pd.Timestamp | None:
    data = normalize_ohlc(frame)
    if data.empty:
        return None
    start_ts = _timestamp(start)
    end_ts = _timestamp(end)
    if start_ts is not None:
        data = data[data["time"] >= start_ts]
    if end_ts is not None:
        data = data[data["time"] <= end_ts]
    hits = data[data["high"] >= float(level)] if side == "high" else data[data["low"] <= float(level)]
    if hits.empty:
        return None
    return pd.Timestamp(hits.iloc[0]["time"])


def _row_to_reference(row: pd.Series, ref_type: ReferenceType) -> dict[str, Any]:
    high = float(row["high"])
    low = float(row["low"])
    return {
        "h1_reference_type": ref_type,
        "h1_reference_timestamp": _timestamp_text(row["time"]),
        "h1_reference_high": round(high, 4),
        "h1_reference_low": round(low, 4),
        "h1_reference_range": round(high - low, 4),
        "h1_reference_range_bucket": _range_bucket(high - low),
    }


def previous_h1_reference(h1: pd.DataFrame, current_index: int) -> dict[str, Any] | None:
    if current_index <= 0:
        return None
    return _row_to_reference(h1.iloc[current_index - 1], "previous_h1")


def dominant_h1_reference(
    h1: pd.DataFrame,
    current_index: int,
    *,
    contained_count: int = 2,
    lookback: int = 12,
) -> dict[str, Any] | None:
    if current_index <= 0 or contained_count <= 0:
        return None
    start = max(0, current_index - lookback)
    for idx in range(current_index - 1, start - 1, -1):
        candidate = h1.iloc[idx]
        following = h1.iloc[idx + 1 : min(idx + 1 + contained_count, len(h1))]
        if len(following) < contained_count:
            continue
        high = float(candidate["high"])
        low = float(candidate["low"])
        contained = (following["high"].astype(float) <= high).all() and (following["low"].astype(float) >= low).all()
        if contained:
            return _row_to_reference(candidate, "dominant_h1")
    return None


def references_for_context(
    h1: pd.DataFrame,
    current_index: int,
    *,
    mode: ReferenceMode,
    dominant_contained_count: int = 2,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if mode in {"previous", "both"}:
        prev = previous_h1_reference(h1, current_index)
        if prev:
            refs.append(prev)
    if mode in {"dominant", "both"}:
        dom = dominant_h1_reference(h1, current_index, contained_count=dominant_contained_count)
        if dom and not any(
            r["h1_reference_timestamp"] == dom["h1_reference_timestamp"] and r["h1_reference_type"] == dom["h1_reference_type"]
            for r in refs
        ):
            refs.append(dom)
    return refs


def _range_bucket(range_value: float) -> str:
    value = float(range_value)
    if value < 5:
        return "RANGE_LT_5"
    if value < 10:
        return "RANGE_5_10"
    if value < 20:
        return "RANGE_10_20"
    if value < 40:
        return "RANGE_20_40"
    return "RANGE_GE_40"


def _liquidity_level(direction: Direction, reference: dict[str, Any]) -> tuple[float, str]:
    if direction == "LONG":
        return float(reference["h1_reference_low"]), "LOW"
    return float(reference["h1_reference_high"]), "HIGH"


def _opposite_h1_level(direction: Direction, reference: dict[str, Any]) -> tuple[float, Literal["high", "low"]]:
    if direction == "LONG":
        return float(reference["h1_reference_high"]), "high"
    return float(reference["h1_reference_low"]), "low"


def _sequence_side(direction: Direction) -> tuple[Literal["high", "low"], Literal["high", "low"]]:
    return ("low", "high") if direction == "LONG" else ("high", "low")


def _window_between(frame: pd.DataFrame, start: Any, end: Any) -> pd.DataFrame:
    data = normalize_ohlc(frame)
    start_ts = _timestamp(start)
    end_ts = _timestamp(end)
    if data.empty or start_ts is None:
        return pd.DataFrame()
    if end_ts is None:
        return data[data["time"] >= start_ts]
    return data[(data["time"] >= start_ts) & (data["time"] <= end_ts)]


def _distribution_time(
    window: pd.DataFrame,
    *,
    direction: Direction,
    h1_level: float,
    sweep_time: Any,
    min_distribution_price: float,
) -> pd.Timestamp | None:
    after = _window_between(window, sweep_time, None)
    if after.empty:
        return None
    if direction == "LONG":
        hits = after[after["high"] >= h1_level + min_distribution_price]
    else:
        hits = after[after["low"] <= h1_level - min_distribution_price]
    if hits.empty:
        return None
    return pd.Timestamp(hits.iloc[0]["time"])


def _manipulation_depth(
    window: pd.DataFrame,
    *,
    direction: Direction,
    h1_level: float,
    sweep_time: Any,
    distribution_time: Any,
) -> float:
    segment = _window_between(window, sweep_time, distribution_time)
    if segment.empty:
        return 0.0
    if direction == "LONG":
        return round(max(0.0, h1_level - float(segment["low"].min())), 4)
    return round(max(0.0, float(segment["high"].max()) - h1_level), 4)


def _expansion_distance(window: pd.DataFrame, *, direction: Direction, h1_level: float, sweep_time: Any) -> float:
    after = _window_between(window, sweep_time, None)
    if after.empty:
        return 0.0
    if direction == "LONG":
        return round(max(0.0, float(after["high"].max()) - h1_level), 4)
    return round(max(0.0, h1_level - float(after["low"].min())), 4)


def _reaction_proxy(
    m5_window: pd.DataFrame,
    *,
    direction: Direction,
    h1_level: float,
    sweep_time: Any,
    reaction_window_m5: int,
    min_distribution_price: float,
) -> dict[str, Any]:
    frame = normalize_ohlc(m5_window)
    sweep_ts = _timestamp(sweep_time)
    if frame.empty or sweep_ts is None:
        return {
            "reaction_confirmed": False,
            "reaction_type": "REACTION_CONFIRMATION_NOT_FULLY_MODELED",
            "reaction_timestamp": None,
            "reaction_latency_candles": None,
        }
    after = frame[frame["time"] >= sweep_ts].head(max(1, int(reaction_window_m5)))
    for idx, (_, candle) in enumerate(after.iterrows(), start=1):
        close = float(candle["close"])
        high = float(candle["high"])
        low = float(candle["low"])
        if direction == "LONG":
            if close > h1_level:
                return {
                    "reaction_confirmed": True,
                    "reaction_type": "M5_RECLAIM",
                    "reaction_timestamp": _timestamp_text(candle["time"]),
                    "reaction_latency_candles": idx,
                }
            if high >= h1_level + min_distribution_price:
                return {
                    "reaction_confirmed": True,
                    "reaction_type": "M5_EXPANSION_PROXY",
                    "reaction_timestamp": _timestamp_text(candle["time"]),
                    "reaction_latency_candles": idx,
                }
        else:
            if close < h1_level:
                return {
                    "reaction_confirmed": True,
                    "reaction_type": "M5_RECLAIM",
                    "reaction_timestamp": _timestamp_text(candle["time"]),
                    "reaction_latency_candles": idx,
                }
            if low <= h1_level - min_distribution_price:
                return {
                    "reaction_confirmed": True,
                    "reaction_type": "M5_EXPANSION_PROXY",
                    "reaction_timestamp": _timestamp_text(candle["time"]),
                    "reaction_latency_candles": idx,
                }
    return {
        "reaction_confirmed": False,
        "reaction_type": "REACTION_CONFIRMATION_NOT_FULLY_MODELED",
        "reaction_timestamp": None,
        "reaction_latency_candles": None,
    }


def _candle_development_model(window: pd.DataFrame, sweep_time: Any) -> str:
    frame = normalize_ohlc(window)
    sweep_ts = _timestamp(sweep_time)
    if frame.empty or sweep_ts is None:
        return "UNKNOWN"
    pre = frame[frame["time"] < sweep_ts].tail(15)
    if len(pre) < 4:
        return "UNKNOWN"
    ranges = (pre["high"] - pre["low"]).astype(float)
    avg_range = float(ranges.mean())
    span = float(pre["high"].max() - pre["low"].min())
    if avg_range > 0 and span <= avg_range * 3:
        return "ACCUMULATION_BEFORE_EXPANSION"
    return "IMMEDIATE_EXPANSION"


def evaluate_h1_sample(
    *,
    symbol: str,
    h1_context: pd.Series,
    reference: dict[str, Any],
    direction: Direction,
    m1_window: pd.DataFrame,
    m5_window: pd.DataFrame,
    m15: pd.DataFrame,
    config: StatisticalRecorderConfig,
) -> dict[str, Any]:
    h1_start = pd.Timestamp(h1_context["time"])
    h1_end = h1_start + pd.Timedelta(hours=1)
    h1_level, h1_side = _liquidity_level(direction, reference)
    sweep_side, opposite_m15_side = _sequence_side(direction)
    sample_id = f"{symbol}_{h1_start.strftime('%Y%m%d%H%M')}_{reference['h1_reference_type']}_{direction}"
    base = {
        "sample_id": sample_id,
        "symbol": symbol,
        "direction": direction,
        "h1_context_timestamp": _timestamp_text(h1_start),
        **reference,
        "h1_liquidity_level": round(h1_level, 4),
        "h1_liquidity_side": h1_side,
        "session": derived_session_from_hour(h1_start.hour),
        "hour": h1_start.hour,
        "conversion_factor_used": config.pip_factor,
        "current_mae_entry_threshold_price": None,
        "valid_for_mae_dataset": False,
    }
    m15_x45 = select_m15_x45(m15, h1_start)
    if not m15_x45:
        return {
            **base,
            "sample_status": "INVALID_INSUFFICIENT_DATA",
            "sample_reason_codes": "M15_X45_MISSING",
            "m15_x45_sequence_valid": False,
        }
    base.update(m15_x45)
    opposite_m15_level = float(m15_x45["m15_x45_high"] if direction == "LONG" else m15_x45["m15_x45_low"])
    sweep_time = first_touch_time(m1_window, level=h1_level, side=sweep_side, start=h1_start, end=h1_end)
    opposite_m15_time = first_touch_time(m1_window, level=opposite_m15_level, side=opposite_m15_side, start=h1_start, end=sweep_time or h1_end)
    opposite_h1_level, opposite_h1_side = _opposite_h1_level(direction, reference)
    opposite_h1_time = first_touch_time(m1_window, level=opposite_h1_level, side=opposite_h1_side, start=h1_start, end=sweep_time or h1_end)
    if opposite_m15_time is not None and (sweep_time is None or opposite_m15_time < sweep_time):
        return {
            **base,
            "m15_x45_sequence_valid": False,
            "m15_x45_sequence_reason": "INVALID_OPPOSITE_M15_X45_TAKEN_FIRST",
            "opposite_m15_x45_taken_timestamp": _timestamp_text(opposite_m15_time),
            "h1_sweep_timestamp": _timestamp_text(sweep_time),
            "opposite_h1_side_taken_before_sweep": opposite_h1_time is not None and (sweep_time is None or opposite_h1_time < sweep_time),
            "sample_status": "INVALID_OPPOSITE_M15_X45_TAKEN_FIRST",
            "sample_reason_codes": "INVALID_OPPOSITE_M15_X45_TAKEN_FIRST",
        }
    if opposite_h1_time is not None and (sweep_time is None or opposite_h1_time < sweep_time):
        return {
            **base,
            "m15_x45_sequence_valid": True,
            "m15_x45_sequence_reason": "M15_X45_SEQUENCE_VALID",
            "opposite_m15_x45_taken_timestamp": _timestamp_text(opposite_m15_time),
            "h1_sweep_timestamp": _timestamp_text(sweep_time),
            "opposite_h1_side_taken_before_sweep": True,
            "sample_status": "INVALID_MOVE_ALREADY_CONSUMED",
            "sample_reason_codes": "INVALID_MOVE_ALREADY_CONSUMED",
        }
    if sweep_time is None:
        return {
            **base,
            "m15_x45_sequence_valid": True,
            "m15_x45_sequence_reason": "M15_X45_SEQUENCE_VALID",
            "opposite_m15_x45_taken_timestamp": _timestamp_text(opposite_m15_time),
            "h1_sweep_timestamp": None,
            "sample_status": "INVALID_NO_CLEAR_MANIPULATION",
            "sample_reason_codes": "INVALID_NO_CLEAR_MANIPULATION",
        }
    distribution_time = _distribution_time(
        m1_window,
        direction=direction,
        h1_level=h1_level,
        sweep_time=sweep_time,
        min_distribution_price=config.min_distribution_price,
    )
    manipulation = _manipulation_depth(
        m1_window,
        direction=direction,
        h1_level=h1_level,
        sweep_time=sweep_time,
        distribution_time=distribution_time or h1_end,
    )
    if manipulation < config.min_manipulation_price:
        return {
            **base,
            "m15_x45_sequence_valid": True,
            "m15_x45_sequence_reason": "M15_X45_SEQUENCE_VALID",
            "opposite_m15_x45_taken_timestamp": _timestamp_text(opposite_m15_time),
            "h1_sweep_timestamp": _timestamp_text(sweep_time),
            "manipulation_depth_price": manipulation,
            "manipulation_depth_usd": manipulation,
            "manipulation_depth_pips": price_to_pips(manipulation, config.pip_factor),
            "sample_status": "INVALID_NO_CLEAR_MANIPULATION",
            "sample_reason_codes": "INVALID_NO_CLEAR_MANIPULATION",
        }
    if distribution_time is None:
        return {
            **base,
            "m15_x45_sequence_valid": True,
            "m15_x45_sequence_reason": "M15_X45_SEQUENCE_VALID",
            "opposite_m15_x45_taken_timestamp": _timestamp_text(opposite_m15_time),
            "h1_sweep_timestamp": _timestamp_text(sweep_time),
            "manipulation_depth_price": manipulation,
            "manipulation_depth_usd": manipulation,
            "manipulation_depth_pips": price_to_pips(manipulation, config.pip_factor),
            "sample_status": "INVALID_NO_DISTRIBUTION",
            "sample_reason_codes": "INVALID_NO_DISTRIBUTION",
        }
    expansion = _expansion_distance(m1_window, direction=direction, h1_level=h1_level, sweep_time=sweep_time)
    reaction = _reaction_proxy(
        m5_window,
        direction=direction,
        h1_level=h1_level,
        sweep_time=sweep_time,
        reaction_window_m5=config.reaction_window_m5,
        min_distribution_price=config.min_distribution_price,
    )
    return {
        **base,
        "m15_x45_sequence_valid": True,
        "m15_x45_sequence_reason": "M15_X45_SEQUENCE_VALID",
        "opposite_m15_x45_taken_timestamp": _timestamp_text(opposite_m15_time),
        "h1_sweep_timestamp": _timestamp_text(sweep_time),
        "opposite_h1_side_taken_before_sweep": False,
        "distribution_timestamp": _timestamp_text(distribution_time),
        **reaction,
        "distribution_confirmed": True,
        "distribution_distance_price": expansion,
        "distribution_distance_usd": expansion,
        "distribution_distance_pips": price_to_pips(expansion, config.pip_factor),
        "manipulation_depth_price": manipulation,
        "manipulation_depth_usd": manipulation,
        "manipulation_depth_pips": price_to_pips(manipulation, config.pip_factor),
        "sample_status": "VALID_SAMPLE_UNCLASSIFIED",
        "sample_reason_codes": "VALID_MANIPULATION_AND_DISTRIBUTION",
        "valid_for_mae_dataset": True,
        "candle_development_model": _candle_development_model(m1_window, sweep_time),
    }


def collect_statistical_samples(
    *,
    symbol: str,
    market_data: dict[str, pd.DataFrame],
    date_from: Any,
    date_to: Any,
    config: StatisticalRecorderConfig | None = None,
) -> list[dict[str, Any]]:
    cfg = config or StatisticalRecorderConfig(symbol=symbol)
    m1 = normalize_ohlc(market_data.get("M1"))
    m5 = normalize_ohlc(market_data.get("M5"))
    m15 = normalize_ohlc(market_data.get("M15"))
    h1 = normalize_ohlc(market_data.get("H1"))
    start = _timestamp(date_from)
    end = _timestamp(date_to)
    if m1.empty or h1.empty or start is None or end is None:
        return []
    rows: list[dict[str, Any]] = []
    h1_contexts = h1[(h1["time"] >= start) & (h1["time"] <= end)].reset_index()
    for _, context in h1_contexts.iterrows():
        idx = int(context["index"])
        h1_start = pd.Timestamp(context["time"])
        h1_end = h1_start + pd.Timedelta(hours=1)
        m1_window = m1[(m1["time"] >= h1_start) & (m1["time"] < h1_end)]
        m5_window = m5[(m5["time"] >= h1_start) & (m5["time"] < h1_end)] if not m5.empty else pd.DataFrame()
        refs = references_for_context(h1, idx, mode=cfg.h1_reference_mode, dominant_contained_count=cfg.dominant_contained_count)
        if cfg.h1_reference_mode in {"dominant", "both"} and not any(ref["h1_reference_type"] == "dominant_h1" for ref in refs):
            rows.append(
                {
                    "sample_id": f"{symbol}_{h1_start.strftime('%Y%m%d%H%M')}_dominant_UNKNOWN",
                    "symbol": symbol,
                    "h1_context_timestamp": _timestamp_text(h1_start),
                    "h1_reference_type": "dominant_h1",
                    "sample_status": "INVALID_INSUFFICIENT_DATA",
                    "sample_reason_codes": "H1_DOMINANT_UNCLEAR",
                    "session": derived_session_from_hour(h1_start.hour),
                    "hour": h1_start.hour,
                    "conversion_factor_used": cfg.pip_factor,
                }
            )
        for ref in refs:
            for direction in ("LONG", "SHORT"):
                rows.append(
                    evaluate_h1_sample(
                        symbol=symbol,
                        h1_context=context,
                        reference=ref,
                        direction=direction,  # type: ignore[arg-type]
                        m1_window=m1_window,
                        m5_window=m5_window,
                        m15=m15,
                        config=cfg,
                    )
                )
    return _classify_valid_samples_with_mae(rows)


def _classify_valid_samples_with_mae(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid_depths = [
        float(row["manipulation_depth_price"])
        for row in rows
        if row.get("sample_status") == "VALID_SAMPLE_UNCLASSIFIED" and row.get("manipulation_depth_price") not in (None, "")
    ]
    mae = _mean(valid_depths)
    for row in rows:
        if mae is not None:
            row["current_mae_entry_threshold_price"] = mae
        if row.get("sample_status") != "VALID_SAMPLE_UNCLASSIFIED":
            row.setdefault("would_trigger_current_mae_entry", False)
            row.setdefault("valid_for_mae_dataset", False)
            continue
        depth = float(row.get("manipulation_depth_price") or 0.0)
        triggered = mae is not None and depth >= mae
        row["would_trigger_current_mae_entry"] = triggered
        row["valid_for_mae_dataset"] = True
        row["sample_status"] = "VALID_SAMPLE_TRADE_TRIGGERED" if triggered else "VALID_SAMPLE_NO_ENTRY_MANIPULATED_LESS"
        row["sample_reason_codes"] = (
            "VALID_SAMPLE_TRADE_TRIGGERED"
            if triggered
            else "VALID_NO_ENTRY_SAMPLE_INCLUDED_IN_MAE|MANIPULATED_LESS_THAN_CURRENT_MAE"
        )
    return rows


def profile_distances(values: Iterable[float], *, pip_factor: float) -> dict[str, Any]:
    vals = [float(v) for v in values if v is not None]
    return {
        "count": len(vals),
        "average_price": _mean(vals),
        "average_usd": _mean(vals),
        "average_pips": price_to_pips(_mean(vals), pip_factor) if vals else None,
        "median_price": _median(vals),
        "median_usd": _median(vals),
        "median_pips": price_to_pips(_median(vals), pip_factor) if vals else None,
        "p25_price": percentile(vals, 0.25) or 0.0 if vals else None,
        "p50_price": percentile(vals, 0.50) or 0.0 if vals else None,
        "p75_price": percentile(vals, 0.75) or 0.0 if vals else None,
        "p80_price": percentile(vals, 0.80) or 0.0 if vals else None,
        "p85_price": percentile(vals, 0.85) or 0.0 if vals else None,
        "p90_price": percentile(vals, 0.90) or 0.0 if vals else None,
        "p95_price": percentile(vals, 0.95) or 0.0 if vals else None,
        "max_price": round(max(vals), 4) if vals else None,
        "max_usd": round(max(vals), 4) if vals else None,
        "max_pips": price_to_pips(max(vals), pip_factor) if vals else None,
    }


def build_statistical_profile(rows: list[dict[str, Any]], *, config: StatisticalRecorderConfig) -> dict[str, Any]:
    valid = [row for row in rows if row.get("sample_status") in VALID_STATUSES]
    manipulations = [float(row["manipulation_depth_price"]) for row in valid if row.get("manipulation_depth_price") not in (None, "")]
    expansions = [float(row["distribution_distance_price"]) for row in valid if row.get("distribution_distance_price") not in (None, "")]
    mae_profile = profile_distances(manipulations, pip_factor=config.pip_factor)
    expansion_profile = profile_distances(expansions, pip_factor=config.pip_factor)
    risky_stop = mae_profile["max_price"] or 0.0
    conservative_stop = round(risky_stop * 1.25, 4)
    p95 = mae_profile["p95_price"] or 0.0
    p90 = mae_profile["p90_price"] or 0.0
    p85 = mae_profile["p85_price"] or 0.0
    p75 = mae_profile["p75_price"] or 0.0
    max_expansion = expansion_profile["max_price"] or 0.0
    avg_expansion = expansion_profile["average_price"] or 0.0
    tp1 = round(max_expansion * 0.25, 4)
    tp2 = round(max_expansion * 0.50, 4)
    tp3 = round(max_expansion * 0.75, 4)
    tp4 = round(max_expansion, 4)
    adaptive_tp1_used = bool(avg_expansion > 0 and avg_expansion < tp1)
    adaptive_tp1 = round(avg_expansion if adaptive_tp1_used else tp1, 4)
    risk_stats = _risk_threshold_stats(manipulations, config=config)
    rr = rr_diagnostic(
        mae_entry_distance=mae_profile["average_price"] or 0.0,
        risky_stop_distance=risky_stop,
        conservative_stop_distance=conservative_stop,
        tp_distances=[tp1, tp2, tp3, tp4],
        adaptive_tp1_distance=adaptive_tp1,
    )
    return {
        "mae_profile": mae_profile,
        "max_excursion_profile": {
            "risky_stop_distance_price": risky_stop,
            "risky_stop_distance_usd": risky_stop,
            "risky_stop_distance_pips": price_to_pips(risky_stop, config.pip_factor),
            "conservative_stop_distance_price": conservative_stop,
            "conservative_stop_distance_usd": conservative_stop,
            "conservative_stop_distance_pips": price_to_pips(conservative_stop, config.pip_factor),
            "p95_conservative_stop_price": round(p95 * 1.25, 4),
            "p90_conservative_stop_price": round(p90 * 1.25, 4),
            "p85_conservative_stop_price": round(p85 * 1.25, 4),
            "p75_conservative_stop_price": round(p75 * 1.25, 4),
            "global_xauusd_max_excursion_used": False,
            **risk_stats,
        },
        "expansion_profile": expansion_profile,
        "tp_profile": {
            "tp_anchor_level": "H1_LIQUIDITY_LEVEL",
            "tp_anchor_is_entry": False,
            "tp1_distance_price": tp1,
            "tp2_distance_price": tp2,
            "tp3_distance_price": tp3,
            "tp4_distance_price": tp4,
            "tp1_distance_pips": price_to_pips(tp1, config.pip_factor),
            "tp2_distance_pips": price_to_pips(tp2, config.pip_factor),
            "tp3_distance_pips": price_to_pips(tp3, config.pip_factor),
            "tp4_distance_pips": price_to_pips(tp4, config.pip_factor),
            "adaptive_tp1_used": adaptive_tp1_used,
            "adaptive_tp1_distance_price": adaptive_tp1,
            "adaptive_tp1_distance_pips": price_to_pips(adaptive_tp1, config.pip_factor),
            "p95_quartiles_price": _quartiles_from(expansion_profile["p95_price"] or 0.0),
            "p90_quartiles_price": _quartiles_from(expansion_profile["p90_price"] or 0.0),
        },
        "rr_diagnostic": rr,
    }


def _risk_threshold_stats(values: list[float], *, config: StatisticalRecorderConfig) -> dict[str, Any]:
    total = len(values)
    def pct(predicate: Any) -> float:
        return _rate(sum(1 for value in values if predicate(value)), total)
    return {
        "pct_manipulation_le_8_usd": pct(lambda v: v <= 8.0),
        "pct_manipulation_le_10_usd": pct(lambda v: v <= 10.0),
        "pct_manipulation_le_12_usd": pct(lambda v: v <= 12.0),
        "pct_manipulation_gt_12_usd": pct(lambda v: v > 12.0),
        "pct_manipulation_gt_15_usd": pct(lambda v: v > 15.0),
        "pct_manipulation_gt_20_usd": pct(lambda v: v > 20.0),
        "profile_risk_too_large": bool(values and max(values) * 1.25 > config.risk_guardrail_usd),
    }


def _quartiles_from(max_value: float) -> dict[str, float]:
    value = max(0.0, float(max_value))
    return {
        "tp1": round(value * 0.25, 4),
        "tp2": round(value * 0.50, 4),
        "tp3": round(value * 0.75, 4),
        "tp4": round(value, 4),
    }


def rr_diagnostic(
    *,
    mae_entry_distance: float,
    risky_stop_distance: float,
    conservative_stop_distance: float,
    tp_distances: list[float],
    adaptive_tp1_distance: float,
) -> dict[str, Any]:
    def rr(tp_distance: float, stop_distance: float) -> float | None:
        if stop_distance <= 0:
            return None
        return round((mae_entry_distance + tp_distance) / stop_distance, 4)

    risky = {f"tp{idx}_R": rr(distance, risky_stop_distance) for idx, distance in enumerate(tp_distances, start=1)}
    conservative = {f"tp{idx}_R": rr(distance, conservative_stop_distance) for idx, distance in enumerate(tp_distances, start=1)}
    adaptive_risky = rr(adaptive_tp1_distance, risky_stop_distance)
    adaptive_conservative = rr(adaptive_tp1_distance, conservative_stop_distance)
    flags: list[str] = []
    if conservative.get("tp1_R") is not None and conservative["tp1_R"] < 0.5:
        flags.append("TP1_R_TOO_SMALL")
    if conservative.get("tp2_R") is not None and conservative["tp2_R"] < 1.0:
        flags.append("TP2_R_BELOW_1")
    if flags:
        flags.append("RR_STRUCTURALLY_UNFAVORABLE")
    return {
        "mae_entry_distance_price": round(mae_entry_distance, 4),
        "risky_stop_distance_price": round(risky_stop_distance, 4),
        "conservative_stop_distance_price": round(conservative_stop_distance, 4),
        "risky_stop_rr": risky,
        "conservative_stop_rr": conservative,
        "adaptive_TP1_R_risky_stop": adaptive_risky,
        "adaptive_TP1_R_conservative_stop": adaptive_conservative,
        "rr_structurally_valid": not bool(flags),
        "rr_flags": flags,
    }


def build_context_breakdowns(rows: list[dict[str, Any]], *, min_context_sample: int) -> list[dict[str, Any]]:
    valid = [row for row in rows if row.get("sample_status") in VALID_STATUSES]
    scopes = {
        "direction": "direction",
        "h1_reference_type": "h1_reference_type",
        "session": "session",
        "h1_reference_range_bucket": "h1_reference_range_bucket",
        "candle_development_model": "candle_development_model",
        "m15_x45_sequence_valid": "m15_x45_sequence_valid",
    }
    output: list[dict[str, Any]] = []
    for scope, field in scopes.items():
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in valid:
            grouped[str(row.get(field) if row.get(field) not in (None, "") else "UNKNOWN")].append(row)
        for bucket, group in sorted(grouped.items()):
            manipulations = [float(row["manipulation_depth_price"]) for row in group if row.get("manipulation_depth_price") not in (None, "")]
            expansions = [float(row["distribution_distance_price"]) for row in group if row.get("distribution_distance_price") not in (None, "")]
            output.append(
                {
                    "scope": scope,
                    "bucket": bucket,
                    "samples": len(group),
                    "sample_flag": "LOW_SAMPLE_CONTEXT" if len(group) < min_context_sample else "CONTEXT_SAMPLE_OK",
                    "avg_manipulation": _mean(manipulations),
                    "max_manipulation": round(max(manipulations), 4) if manipulations else None,
                    "avg_expansion": _mean(expansions),
                    "max_expansion": round(max(expansions), 4) if expansions else None,
                }
            )
    return output


def build_statistical_sample_report(
    *,
    symbol: str,
    market_data: dict[str, pd.DataFrame],
    date_from: Any,
    date_to: Any,
    config: StatisticalRecorderConfig,
) -> dict[str, Any]:
    rows = collect_statistical_samples(symbol=symbol, market_data=market_data, date_from=date_from, date_to=date_to, config=config)
    profile = build_statistical_profile(rows, config=config)
    status_counts = Counter(str(row.get("sample_status") or "UNKNOWN") for row in rows)
    invalid_counts = {key: value for key, value in status_counts.items() if not key.startswith("VALID_")}
    valid_count = sum(status_counts.get(status, 0) for status in VALID_STATUSES)
    triggered = status_counts.get("VALID_SAMPLE_TRADE_TRIGGERED", 0)
    no_entry = status_counts.get("VALID_SAMPLE_NO_ENTRY_MANIPULATED_LESS", 0)
    m15_valid = sum(1 for row in rows if row.get("m15_x45_sequence_valid") is True)
    m15_invalid = sum(1 for row in rows if row.get("sample_status") == "INVALID_OPPOSITE_M15_X45_TAKEN_FIRST")
    context_breakdown = build_context_breakdowns(rows, min_context_sample=config.min_context_sample)
    flags = _verdict_flags(profile, context_breakdown)
    summary = {
        "research_only": True,
        "safety": SAFETY,
        "symbol": symbol,
        "date_from": _timestamp_text(date_from),
        "date_to": _timestamp_text(date_to),
        "h1_reference_mode": config.h1_reference_mode,
        "pip_factor": config.pip_factor,
        "h1_contexts_analyzed": len(rows),
        "valid_samples": valid_count,
        "invalid_samples_by_reason": invalid_counts,
        "valid_triggered_samples": triggered,
        "valid_no_entry_samples": no_entry,
        "m15_x45_valid_count": m15_valid,
        "m15_x45_invalid_count": m15_invalid,
        "status_counts": dict(status_counts),
        "profile": profile,
        "context_breakdown": context_breakdown,
        "verdict_flags": flags,
    }
    return {
        "sample_rows": rows,
        "summary": summary,
        "context_breakdown": context_breakdown,
    }


def _verdict_flags(profile: dict[str, Any], context_breakdown: list[dict[str, Any]]) -> list[str]:
    flags = [
        "STATISTICAL_SAMPLE_RECORDER_BUILT",
        "M15_X45_FILTER_CORRECTED",
        "GLOBAL_MAX_EXCURSION_REJECTED",
        "MAE_FROM_VALID_MANIPULATION_SAMPLES",
        "VALID_NO_ENTRY_SAMPLES_INCLUDED",
        "MAX_EXCURSION_FROM_VALID_SAMPLE_SET",
        "CONSERVATIVE_SL_MAX_EXCURSION_PLUS_25",
        "TP_ANCHORED_TO_H1_CONFIRMED",
        "REACTION_CONFIRMATION_NOT_FULLY_MODELED",
    ]
    if profile["max_excursion_profile"]["profile_risk_too_large"]:
        flags.append("PROFILE_RISK_TOO_LARGE")
    else:
        flags.append("PROFILE_RISK_PLAUSIBLE")
    if any(row.get("sample_flag") == "LOW_SAMPLE_CONTEXT" for row in context_breakdown):
        flags.append("LOW_SAMPLE_CONTEXT")
    flags.extend(["STRATEGY_2_REMAINS_RESEARCH_ONLY", "NO_LIVE_DEPLOYMENT_DECISION"])
    return flags


def write_statistical_sample_outputs(report: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "samples_csv": str(output_dir / "h1_liquidity_samples.csv"),
        "samples_jsonl": str(output_dir / "h1_liquidity_samples.jsonl"),
        "summary_json": str(output_dir / "statistical_profile_summary.json"),
        "mae_profile_csv": str(output_dir / "mae_profile.csv"),
        "max_excursion_profile_csv": str(output_dir / "max_excursion_profile.csv"),
        "expansion_profile_csv": str(output_dir / "expansion_profile.csv"),
        "tp_profile_csv": str(output_dir / "tp_profile.csv"),
        "context_breakdown_csv": str(output_dir / "context_breakdown.csv"),
        "summary_md": str(output_dir / "recorder_summary.md"),
    }
    with Path(paths["samples_csv"]).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SAMPLE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["sample_rows"])
    with Path(paths["samples_jsonl"]).open("w", encoding="utf-8") as f:
        for row in report["sample_rows"]:
            f.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    summary = report["summary"]
    Path(paths["summary_json"]).write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    _write_single_row_csv(Path(paths["mae_profile_csv"]), summary["profile"]["mae_profile"])
    _write_single_row_csv(Path(paths["max_excursion_profile_csv"]), summary["profile"]["max_excursion_profile"])
    _write_single_row_csv(Path(paths["expansion_profile_csv"]), summary["profile"]["expansion_profile"])
    _write_single_row_csv(Path(paths["tp_profile_csv"]), summary["profile"]["tp_profile"])
    if report["context_breakdown"]:
        with Path(paths["context_breakdown_csv"]).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(report["context_breakdown"][0].keys()), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(report["context_breakdown"])
    else:
        Path(paths["context_breakdown_csv"]).write_text("", encoding="utf-8")
    Path(paths["summary_md"]).write_text(render_statistical_sample_markdown(summary), encoding="utf-8")
    return paths


def _write_single_row_csv(path: Path, row: dict[str, Any]) -> None:
    flat = {key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value for key, value in row.items()}
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(flat.keys()))
        writer.writeheader()
        writer.writerow(flat)


def render_statistical_sample_markdown(summary: dict[str, Any]) -> str:
    profile = summary["profile"]
    max_profile = profile["max_excursion_profile"]
    lines = [
        "# Strategy 2 Statistical Sample Recorder",
        "",
        "Research-only statistical sample recorder. No live trading, no orders, no Telegram, no Strategy 2 runtime registration.",
        "",
        "## Run Context",
        "",
        f"- symbol: `{summary['symbol']}`",
        f"- window: `{summary['date_from']}` -> `{summary['date_to']}`",
        f"- H1 reference mode: `{summary['h1_reference_mode']}`",
        f"- pip factor: `{summary['pip_factor']}`",
        "",
        "## Results",
        "",
        f"- H1 contexts analyzed: `{summary['h1_contexts_analyzed']}`",
        f"- valid samples: `{summary['valid_samples']}`",
        f"- valid triggered samples: `{summary['valid_triggered_samples']}`",
        f"- valid no-entry samples: `{summary['valid_no_entry_samples']}`",
        f"- M15 x:45 valid/invalid: `{summary['m15_x45_valid_count']}` / `{summary['m15_x45_invalid_count']}`",
        "",
        "## Invalid Samples",
        "",
        "```json",
        json.dumps(summary["invalid_samples_by_reason"], indent=2, sort_keys=True),
        "```",
        "",
        "## MAE Profile",
        "",
        "```json",
        json.dumps(profile["mae_profile"], indent=2, sort_keys=True),
        "```",
        "",
        "## Max Excursion / SL Profile",
        "",
        "```json",
        json.dumps(max_profile, indent=2, sort_keys=True),
        "```",
        "",
        "## Expansion / TP Profile",
        "",
        "```json",
        json.dumps({"expansion_profile": profile["expansion_profile"], "tp_profile": profile["tp_profile"]}, indent=2, sort_keys=True),
        "```",
        "",
        "## R:R Diagnostic",
        "",
        "```json",
        json.dumps(profile["rr_diagnostic"], indent=2, sort_keys=True),
        "```",
        "",
        "## Verdict Flags",
        "",
        "\n".join(f"- `{flag}`" for flag in summary["verdict_flags"]),
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "Direction",
    "ReferenceMode",
    "SAMPLE_FIELDS",
    "SAFETY",
    "StatisticalRecorderConfig",
    "VALID_STATUSES",
    "build_statistical_profile",
    "build_statistical_sample_report",
    "collect_statistical_samples",
    "conservative_stop_distance",
    "evaluate_h1_sample",
    "first_touch_time",
    "price_to_pips",
    "render_statistical_sample_markdown",
    "rr_diagnostic",
    "select_m15_x45",
    "write_statistical_sample_outputs",
]


def conservative_stop_distance(max_manipulation: float) -> float:
    return round(max(0.0, float(max_manipulation)) * 1.25, 4)
