from __future__ import annotations

import csv
import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median
from typing import Any, Literal

import pandas as pd

from dazro_trade.analysis.strategy_2_liquidity_expansion_stats import normalize_ohlc, percentile
from dazro_trade.analytics.strategy_2_hourly_session_diagnostics import derived_session_from_hour


Direction = Literal["LONG", "SHORT"]
M15FilterModel = Literal["containing", "preceding", "approach_window", "all"]
ReferenceMode = Literal["previous", "dominant", "both"]
ReferenceType = Literal["previous_h1", "dominant_h1"]

M15_MODELS: tuple[str, ...] = ("containing", "preceding", "approach_window")
VALID_STATUSES = {"VALID_SAMPLE_TRADE_TRIGGERED", "VALID_SAMPLE_NO_ENTRY_MAE_NOT_REACHED", "VALID_SAMPLE_NO_ENTRY_NO_RANGE_REENTRY"}

SAFETY = {
    "research_only": True,
    "dry_run": True,
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "broker_called": False,
    "order_sent": False,
    "order_send_called": False,
    "signals_generated": False,
    "runtime_registration": False,
    "parameters_optimized": False,
    "machine_learning_used": False,
    "market_data_written": False,
}

CORRECTED_SAMPLE_FIELDS = [
    "sample_id",
    "symbol",
    "m15_filter_model",
    "direction",
    "h1_context_timestamp",
    "h1_context_end",
    "h1_reference_type",
    "h1_reference_timestamp",
    "h1_reference_high",
    "h1_reference_low",
    "h1_reference_range",
    "h1_liquidity_level",
    "h1_liquidity_side",
    "dominant_contains_internal_count",
    "dominant_high_taken",
    "dominant_low_taken",
    "opposite_h1_side_taken_first",
    "h1_level_take_timestamp",
    "level_take_threshold_pips",
    "level_take_threshold_usd",
    "relevant_m15_open_time",
    "relevant_m15_count",
    "relevant_m15_high",
    "relevant_m15_low",
    "m15_sequence_valid",
    "m15_invalid_reason",
    "old_x45_sequence_valid",
    "old_x45_timestamp",
    "old_x45_high",
    "old_x45_low",
    "mae_avg_used_usd",
    "mae_reached",
    "mae_reached_timestamp",
    "range_reentry_required_pips",
    "range_reentry_required_usd",
    "range_reentry_reached",
    "range_reentry_timestamp",
    "entry_valid",
    "entry_timestamp",
    "entry_status",
    "reaction_confirmation_used_as_gate",
    "reaction_confirmed_ex_post",
    "distribution_confirmed",
    "distribution_timestamp",
    "manipulation_depth_usd",
    "manipulation_depth_pips",
    "expansion_usd",
    "expansion_pips",
    "sample_status",
    "sample_reason_codes",
    "valid_for_mae_dataset",
    "session",
    "hour",
]


@dataclass(frozen=True)
class MechanicalSpecConfig:
    symbol: str = "XAUUSD"
    pip_factor: float = 10.0
    h1_reference_mode: ReferenceMode = "both"
    m15_filter_model: M15FilterModel = "all"
    dominant_contained_count: int = 2
    dominant_lookback: int = 12
    mae_avg_usd: float = 4.6471
    min_distribution_usd: float = 1.0
    level_take_pips: float = 1.0
    reentry_pips: float = 1.0
    old_samples_path: str = "backtests/reports/strategy_2_statistical_sample_recorder/h1_liquidity_samples.csv"


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
    if value is None:
        return None
    return round(float(value), digits)


def _mean(values: list[float]) -> float | None:
    return round(fmean(values), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(median(values), 4) if values else None


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


def conservative_sl_distance(max_excursion: float | None) -> float | None:
    if max_excursion is None:
        return None
    return round(float(max_excursion) * 1.25, 4)


def tp_quartiles_from_h1(max_expansion: float | None) -> dict[str, float | None]:
    if max_expansion is None:
        return {"tp1": None, "tp2": None, "tp3": None, "tp4": None, "tp_anchor": "H1_LEVEL"}
    value = float(max_expansion)
    return {
        "tp1": round(value * 0.25, 4),
        "tp2": round(value * 0.50, 4),
        "tp3": round(value * 0.75, 4),
        "tp4": round(value, 4),
        "tp_anchor": "H1_LEVEL",
    }


def _first_touch_time(
    frame: pd.DataFrame,
    *,
    level: float,
    side: Literal["high", "low"],
    start: Any | None = None,
    end: Any | None = None,
    include_end: bool = True,
) -> pd.Timestamp | None:
    data = normalize_ohlc(frame)
    if data.empty:
        return None
    start_ts = _timestamp(start)
    end_ts = _timestamp(end)
    if start_ts is not None:
        data = data[data["time"] >= start_ts]
    if end_ts is not None:
        data = data[data["time"] <= end_ts] if include_end else data[data["time"] < end_ts]
    hits = data[data["high"] >= float(level)] if side == "high" else data[data["low"] <= float(level)]
    if hits.empty:
        return None
    return pd.Timestamp(hits.iloc[0]["time"])


def _first_touch_after(
    frame: pd.DataFrame,
    *,
    level: float,
    side: Literal["high", "low"],
    start: Any,
    end: Any,
) -> pd.Timestamp | None:
    return _first_touch_time(frame, level=level, side=side, start=start, end=end, include_end=False)


def previous_h1_reference(h1: pd.DataFrame, current_index: int) -> dict[str, Any] | None:
    if current_index <= 0:
        return None
    row = h1.iloc[current_index - 1]
    return _reference_from_row(row, "previous_h1", dominant_count=0, high_taken=False, low_taken=False)


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
        high = float(candidate["high"])
        low = float(candidate["low"])
        internal = h1.iloc[idx + 1 : current_index]
        if internal.empty:
            continue
        contained_mask = (internal["high"].astype(float) < high) & (internal["low"].astype(float) > low)
        contained_total = int(contained_mask.sum())
        breached_high = bool((internal["high"].astype(float) >= high).any())
        breached_low = bool((internal["low"].astype(float) <= low).any())
        if contained_total >= contained_count and not breached_high and not breached_low:
            return _reference_from_row(
                candidate,
                "dominant_h1",
                dominant_count=contained_total,
                high_taken=breached_high,
                low_taken=breached_low,
            )
    return None


def references_for_context(
    h1: pd.DataFrame,
    current_index: int,
    *,
    mode: ReferenceMode = "both",
    dominant_contained_count: int = 2,
    dominant_lookback: int = 12,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if mode in {"previous", "both"}:
        prev = previous_h1_reference(h1, current_index)
        if prev:
            refs.append(prev)
    if mode in {"dominant", "both"}:
        dom = dominant_h1_reference(h1, current_index, contained_count=dominant_contained_count, lookback=dominant_lookback)
        if dom and not any(
            ref["h1_reference_type"] == dom["h1_reference_type"] and ref["h1_reference_timestamp"] == dom["h1_reference_timestamp"]
            for ref in refs
        ):
            refs.append(dom)
    return refs


def _reference_from_row(
    row: pd.Series,
    ref_type: ReferenceType,
    *,
    dominant_count: int,
    high_taken: bool,
    low_taken: bool,
) -> dict[str, Any]:
    high = float(row["high"])
    low = float(row["low"])
    return {
        "h1_reference_type": ref_type,
        "h1_reference_timestamp": _timestamp_text(row["time"]),
        "h1_reference_high": round(high, 4),
        "h1_reference_low": round(low, 4),
        "h1_reference_range": round(high - low, 4),
        "dominant_contains_internal_count": dominant_count,
        "dominant_high_taken": high_taken,
        "dominant_low_taken": low_taken,
    }


def _window(frame: pd.DataFrame, start: Any, end: Any, *, include_end: bool = False) -> pd.DataFrame:
    data = normalize_ohlc(frame)
    start_ts = _timestamp(start)
    end_ts = _timestamp(end)
    if data.empty or start_ts is None or end_ts is None:
        return pd.DataFrame()
    if include_end:
        return data[(data["time"] >= start_ts) & (data["time"] <= end_ts)].copy()
    return data[(data["time"] >= start_ts) & (data["time"] < end_ts)].copy()


def first_h1_level_take(
    m1_window: pd.DataFrame,
    *,
    reference: dict[str, Any],
    threshold_price: float,
) -> dict[str, Any]:
    low = float(reference["h1_reference_low"])
    high = float(reference["h1_reference_high"])
    long_take = _first_touch_time(m1_window, level=low - threshold_price, side="low")
    short_take = _first_touch_time(m1_window, level=high + threshold_price, side="high")
    if long_take is None and short_take is None:
        return {"direction": None, "take_timestamp": None, "opposite_h1_side_taken_first": False, "ambiguous_same_bar": False}
    if long_take is not None and short_take is not None:
        if long_take == short_take:
            return {"direction": None, "take_timestamp": long_take, "opposite_h1_side_taken_first": True, "ambiguous_same_bar": True}
        if long_take < short_take:
            return {"direction": "LONG", "take_timestamp": long_take, "opposite_h1_side_taken_first": False, "ambiguous_same_bar": False}
        return {"direction": "SHORT", "take_timestamp": short_take, "opposite_h1_side_taken_first": False, "ambiguous_same_bar": False}
    if long_take is not None:
        return {"direction": "LONG", "take_timestamp": long_take, "opposite_h1_side_taken_first": False, "ambiguous_same_bar": False}
    return {"direction": "SHORT", "take_timestamp": short_take, "opposite_h1_side_taken_first": False, "ambiguous_same_bar": False}


def select_relevant_m15(
    m15: pd.DataFrame,
    *,
    h1_context_open: Any,
    take_timestamp: Any,
    model: Literal["containing", "preceding", "approach_window"],
) -> pd.DataFrame:
    frame = normalize_ohlc(m15)
    context_open = _timestamp(h1_context_open)
    take_ts = _timestamp(take_timestamp)
    if frame.empty or context_open is None or take_ts is None:
        return pd.DataFrame()
    if model == "containing":
        selected = frame[(frame["time"] <= take_ts) & (frame["time"] + pd.Timedelta(minutes=15) > take_ts)].tail(1)
        return selected.copy()
    if model == "preceding":
        selected = frame[frame["time"] + pd.Timedelta(minutes=15) <= take_ts].tail(1)
        return selected.copy()
    return frame[(frame["time"] >= context_open) & (frame["time"] <= take_ts)].copy()


def evaluate_m15_sequence(
    m1_window: pd.DataFrame,
    m15: pd.DataFrame,
    *,
    direction: Direction,
    h1_context_open: Any,
    take_timestamp: Any,
    model: Literal["containing", "preceding", "approach_window"],
) -> dict[str, Any]:
    relevant = select_relevant_m15(m15, h1_context_open=h1_context_open, take_timestamp=take_timestamp, model=model)
    if relevant.empty:
        return {
            "m15_sequence_valid": False,
            "m15_invalid_reason": "INVALID_M15_REFERENCE_MISSING",
            "relevant_m15_open_time": None,
            "relevant_m15_count": 0,
            "relevant_m15_high": None,
            "relevant_m15_low": None,
        }

    highs = relevant["high"].astype(float)
    lows = relevant["low"].astype(float)
    invalid_reason = None
    if direction == "LONG":
        for _, candle in relevant.iterrows():
            touched = _first_touch_time(
                m1_window,
                level=float(candle["high"]),
                side="high",
                start=h1_context_open,
                end=take_timestamp,
                include_end=False,
            )
            if touched is not None:
                invalid_reason = "INVALID_CURRENT_M15_HIGH_TAKEN_FIRST_FOR_LONG"
                break
    else:
        for _, candle in relevant.iterrows():
            touched = _first_touch_time(
                m1_window,
                level=float(candle["low"]),
                side="low",
                start=h1_context_open,
                end=take_timestamp,
                include_end=False,
            )
            if touched is not None:
                invalid_reason = "INVALID_CURRENT_M15_LOW_TAKEN_FIRST_FOR_SHORT"
                break

    first_row = relevant.iloc[0]
    return {
        "m15_sequence_valid": invalid_reason is None,
        "m15_invalid_reason": invalid_reason,
        "relevant_m15_open_time": _timestamp_text(first_row["time"]) if model != "approach_window" else None,
        "relevant_m15_count": int(len(relevant)),
        "relevant_m15_high": round(float(highs.max()), 4),
        "relevant_m15_low": round(float(lows.min()), 4),
    }


def select_old_x45(m15: pd.DataFrame, h1_context_open: Any) -> dict[str, Any]:
    frame = normalize_ohlc(m15)
    h1_open = _timestamp(h1_context_open)
    if frame.empty or h1_open is None:
        return {"old_x45_timestamp": None, "old_x45_high": None, "old_x45_low": None}
    hour_end = h1_open + pd.Timedelta(hours=1)
    selected = frame[(frame["time"] >= h1_open) & (frame["time"] < hour_end) & (frame["time"].dt.minute == 45)]
    if selected.empty:
        return {"old_x45_timestamp": None, "old_x45_high": None, "old_x45_low": None}
    row = selected.iloc[0]
    return {"old_x45_timestamp": _timestamp_text(row["time"]), "old_x45_high": round(float(row["high"]), 4), "old_x45_low": round(float(row["low"]), 4)}


def evaluate_old_x45_sequence(
    m1_window: pd.DataFrame,
    m15: pd.DataFrame,
    *,
    direction: Direction,
    h1_context_open: Any,
    take_timestamp: Any,
) -> dict[str, Any]:
    old = select_old_x45(m15, h1_context_open)
    if old["old_x45_timestamp"] is None:
        return {**old, "old_x45_sequence_valid": False}
    if direction == "LONG":
        touched = _first_touch_time(m1_window, level=float(old["old_x45_high"]), side="high", start=h1_context_open, end=take_timestamp, include_end=False)
    else:
        touched = _first_touch_time(m1_window, level=float(old["old_x45_low"]), side="low", start=h1_context_open, end=take_timestamp, include_end=False)
    return {**old, "old_x45_sequence_valid": touched is None}


def evaluate_mechanical_entry(
    m1_window: pd.DataFrame,
    *,
    direction: Direction,
    h1_level: float,
    take_timestamp: Any,
    h1_context_end: Any,
    mae_avg_usd: float,
    reentry_threshold_price: float,
) -> dict[str, Any]:
    take_ts = _timestamp(take_timestamp)
    end_ts = _timestamp(h1_context_end)
    if take_ts is None or end_ts is None:
        return {
            "mae_reached": False,
            "mae_reached_timestamp": None,
            "range_reentry_reached": False,
            "range_reentry_timestamp": None,
            "entry_valid": False,
            "entry_timestamp": None,
            "entry_status": "NO_ENTRY_INSUFFICIENT_DATA",
        }
    if direction == "LONG":
        mae_level = h1_level - float(mae_avg_usd)
        mae_time = _first_touch_time(m1_window, level=mae_level, side="low", start=take_ts, end=end_ts, include_end=False)
        reentry_level = h1_level + reentry_threshold_price
        reentry_side: Literal["high", "low"] = "high"
    else:
        mae_level = h1_level + float(mae_avg_usd)
        mae_time = _first_touch_time(m1_window, level=mae_level, side="high", start=take_ts, end=end_ts, include_end=False)
        reentry_level = h1_level - reentry_threshold_price
        reentry_side = "low"

    if mae_time is None:
        return {
            "mae_reached": False,
            "mae_reached_timestamp": None,
            "range_reentry_reached": False,
            "range_reentry_timestamp": None,
            "entry_valid": False,
            "entry_timestamp": None,
            "entry_status": "NO_ENTRY_MAE_NOT_REACHED",
        }

    reentry_time = _first_touch_time(m1_window, level=reentry_level, side=reentry_side, start=mae_time, end=end_ts, include_end=False)
    if reentry_time is None:
        return {
            "mae_reached": True,
            "mae_reached_timestamp": _timestamp_text(mae_time),
            "range_reentry_reached": False,
            "range_reentry_timestamp": None,
            "entry_valid": False,
            "entry_timestamp": None,
            "entry_status": "NO_ENTRY_NO_RANGE_REENTRY",
        }
    return {
        "mae_reached": True,
        "mae_reached_timestamp": _timestamp_text(mae_time),
        "range_reentry_reached": True,
        "range_reentry_timestamp": _timestamp_text(reentry_time),
        "entry_valid": True,
        "entry_timestamp": _timestamp_text(reentry_time),
        "entry_status": "ENTRY_TRIGGERED_MAE_AND_RANGE_REENTRY",
    }


def _expansion_and_distribution(
    m1_window: pd.DataFrame,
    *,
    direction: Direction,
    h1_level: float,
    take_timestamp: Any,
    min_distribution_usd: float,
) -> dict[str, Any]:
    take_ts = _timestamp(take_timestamp)
    if take_ts is None:
        return {
            "distribution_confirmed": False,
            "distribution_timestamp": None,
            "manipulation_depth_usd": None,
            "manipulation_depth_pips": None,
            "expansion_usd": None,
            "expansion_pips": None,
        }
    after = normalize_ohlc(m1_window)
    after = after[after["time"] >= take_ts]
    if after.empty:
        return {
            "distribution_confirmed": False,
            "distribution_timestamp": None,
            "manipulation_depth_usd": None,
            "manipulation_depth_pips": None,
            "expansion_usd": None,
            "expansion_pips": None,
        }
    if direction == "LONG":
        manipulation = max(0.0, h1_level - float(after["low"].min()))
        expansion = max(0.0, float(after["high"].max()) - h1_level)
        dist_hits = after[after["high"] >= h1_level + min_distribution_usd]
    else:
        manipulation = max(0.0, float(after["high"].max()) - h1_level)
        expansion = max(0.0, h1_level - float(after["low"].min()))
        dist_hits = after[after["low"] <= h1_level - min_distribution_usd]
    return {
        "distribution_confirmed": not dist_hits.empty,
        "distribution_timestamp": _timestamp_text(dist_hits.iloc[0]["time"]) if not dist_hits.empty else None,
        "manipulation_depth_usd": round(manipulation, 4),
        "manipulation_depth_pips": None,
        "expansion_usd": round(expansion, 4),
        "expansion_pips": None,
    }


def evaluate_context_model(
    *,
    symbol: str,
    h1_context: pd.Series,
    reference: dict[str, Any],
    m1_window: pd.DataFrame,
    m15: pd.DataFrame,
    model: Literal["containing", "preceding", "approach_window"],
    config: MechanicalSpecConfig,
) -> dict[str, Any]:
    h1_open = _timestamp(h1_context["time"])
    h1_end = h1_open + pd.Timedelta(hours=1) if h1_open is not None else None
    take_threshold = pips_to_price(config.level_take_pips, config.pip_factor) or 0.0
    reentry_threshold = pips_to_price(config.reentry_pips, config.pip_factor) or 0.0
    take = first_h1_level_take(m1_window, reference=reference, threshold_price=take_threshold)

    base = {
        "symbol": symbol,
        "m15_filter_model": model,
        "h1_context_timestamp": _timestamp_text(h1_open),
        "h1_context_end": _timestamp_text(h1_end),
        "h1_reference_type": reference["h1_reference_type"],
        "h1_reference_timestamp": reference["h1_reference_timestamp"],
        "h1_reference_high": reference["h1_reference_high"],
        "h1_reference_low": reference["h1_reference_low"],
        "h1_reference_range": reference["h1_reference_range"],
        "dominant_contains_internal_count": reference.get("dominant_contains_internal_count", 0),
        "dominant_high_taken": reference.get("dominant_high_taken", False),
        "dominant_low_taken": reference.get("dominant_low_taken", False),
        "level_take_threshold_pips": config.level_take_pips,
        "level_take_threshold_usd": take_threshold,
        "range_reentry_required_pips": config.reentry_pips,
        "range_reentry_required_usd": reentry_threshold,
        "mae_avg_used_usd": config.mae_avg_usd,
        "reaction_confirmation_used_as_gate": False,
        "reaction_confirmed_ex_post": None,
        "session": derived_session_from_hour(int(h1_open.hour)) if h1_open is not None else None,
        "hour": int(h1_open.hour) if h1_open is not None else None,
    }

    if take["take_timestamp"] is None or take.get("ambiguous_same_bar"):
        reason = "NO_H1_LEVEL_TAKEN" if not take.get("ambiguous_same_bar") else "BOTH_H1_LEVELS_TAKEN_SAME_BAR_AMBIGUOUS"
        direction = None
        h1_level = None
        h1_side = None
        sample_id = f"{symbol}_{_timestamp_text(h1_open)}_{reference['h1_reference_type']}_{model}_NO_LEVEL"
        return _complete_row(
            {
                **base,
                "sample_id": sample_id,
                "direction": direction,
                "h1_liquidity_level": h1_level,
                "h1_liquidity_side": h1_side,
                "opposite_h1_side_taken_first": bool(take.get("opposite_h1_side_taken_first")),
                "h1_level_take_timestamp": _timestamp_text(take["take_timestamp"]),
                "sample_status": "INVALID_NO_H1_LEVEL_TAKEN" if not take.get("ambiguous_same_bar") else "INVALID_AMBIGUOUS_BOTH_H1_LEVELS_SAME_BAR",
                "sample_reason_codes": reason,
                "valid_for_mae_dataset": False,
            }
        )

    direction = take["direction"]
    assert direction in {"LONG", "SHORT"}
    h1_level = float(reference["h1_reference_low"] if direction == "LONG" else reference["h1_reference_high"])
    h1_side = "LOW" if direction == "LONG" else "HIGH"
    model_seq = evaluate_m15_sequence(m1_window, m15, direction=direction, h1_context_open=h1_open, take_timestamp=take["take_timestamp"], model=model)
    old_seq = evaluate_old_x45_sequence(m1_window, m15, direction=direction, h1_context_open=h1_open, take_timestamp=take["take_timestamp"])
    entry = evaluate_mechanical_entry(
        m1_window,
        direction=direction,
        h1_level=h1_level,
        take_timestamp=take["take_timestamp"],
        h1_context_end=h1_end,
        mae_avg_usd=config.mae_avg_usd,
        reentry_threshold_price=reentry_threshold,
    )
    movement = _expansion_and_distribution(
        m1_window,
        direction=direction,
        h1_level=h1_level,
        take_timestamp=take["take_timestamp"],
        min_distribution_usd=config.min_distribution_usd,
    )
    movement["manipulation_depth_pips"] = price_to_pips(movement["manipulation_depth_usd"], config.pip_factor)
    movement["expansion_pips"] = price_to_pips(movement["expansion_usd"], config.pip_factor)

    if not model_seq["m15_sequence_valid"]:
        sample_status = "INVALID_CURRENT_M15_SEQUENCE"
        reasons = model_seq["m15_invalid_reason"]
        valid_for_mae = False
    elif not movement["distribution_confirmed"]:
        sample_status = "INVALID_NO_DISTRIBUTION"
        reasons = "INVALID_NO_DISTRIBUTION"
        valid_for_mae = False
    elif entry["entry_valid"]:
        sample_status = "VALID_SAMPLE_TRADE_TRIGGERED"
        reasons = "ENTRY_TRIGGERED_MAE_AND_RANGE_REENTRY"
        valid_for_mae = True
    elif entry["entry_status"] == "NO_ENTRY_MAE_NOT_REACHED":
        sample_status = "VALID_SAMPLE_NO_ENTRY_MAE_NOT_REACHED"
        reasons = "VALID_NO_ENTRY_SAMPLE_INCLUDED_IN_MAE|NO_ENTRY_MAE_NOT_REACHED"
        valid_for_mae = True
    else:
        sample_status = "VALID_SAMPLE_NO_ENTRY_NO_RANGE_REENTRY"
        reasons = "VALID_NO_ENTRY_SAMPLE_INCLUDED_IN_MAE|NO_ENTRY_NO_RANGE_REENTRY"
        valid_for_mae = True

    clean_time = str(_timestamp_text(h1_open) or "").replace("-", "").replace(":", "").replace("+00:00", "").replace("T", "")
    sample_id = f"{symbol}_{clean_time}_{reference['h1_reference_type']}_{model}_{direction}"
    return _complete_row(
        {
            **base,
            **model_seq,
            **old_seq,
            **entry,
            **movement,
            "sample_id": sample_id,
            "direction": direction,
            "h1_liquidity_level": h1_level,
            "h1_liquidity_side": h1_side,
            "opposite_h1_side_taken_first": bool(take.get("opposite_h1_side_taken_first")),
            "h1_level_take_timestamp": _timestamp_text(take["take_timestamp"]),
            "sample_status": sample_status,
            "sample_reason_codes": reasons,
            "valid_for_mae_dataset": valid_for_mae,
        }
    )


def _complete_row(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in CORRECTED_SAMPLE_FIELDS}


def build_corrected_mechanical_samples(
    *,
    symbol: str,
    market_data: dict[str, pd.DataFrame],
    date_from: Any,
    date_to: Any,
    config: MechanicalSpecConfig,
) -> list[dict[str, Any]]:
    h1 = normalize_ohlc(market_data.get("H1"))
    m1 = normalize_ohlc(market_data.get("M1"))
    m15 = normalize_ohlc(market_data.get("M15"))
    if h1.empty or m1.empty or m15.empty:
        return []

    start = _timestamp(date_from)
    end = _timestamp(date_to)
    if start is None or end is None:
        return []
    models = M15_MODELS if config.m15_filter_model == "all" else (config.m15_filter_model,)
    rows: list[dict[str, Any]] = []

    for idx, h1_context in h1.iterrows():
        h1_open = _timestamp(h1_context["time"])
        if h1_open is None or h1_open < start or h1_open > end:
            continue
        h1_end = h1_open + pd.Timedelta(hours=1)
        m1_window = _window(m1, h1_open, h1_end)
        if m1_window.empty:
            continue
        refs = references_for_context(
            h1,
            int(idx),
            mode=config.h1_reference_mode,
            dominant_contained_count=config.dominant_contained_count,
            dominant_lookback=config.dominant_lookback,
        )
        for reference in refs:
            for model in models:
                rows.append(
                    evaluate_context_model(
                        symbol=symbol,
                        h1_context=h1_context,
                        reference=reference,
                        m1_window=m1_window,
                        m15=m15,
                        model=model,  # type: ignore[arg-type]
                        config=config,
                    )
                )
    return rows


def _sample_key(row: dict[str, Any] | pd.Series) -> str:
    return "|".join(
        [
            str(row.get("h1_context_timestamp", "")),
            str(row.get("h1_reference_type", "")),
            str(row.get("direction", "")),
        ]
    )


def load_old_valid_keys(old_samples_path: str | Path) -> tuple[set[str], int]:
    path = Path(old_samples_path)
    if not path.exists():
        return set(), 0
    frame = pd.read_csv(path)
    if frame.empty:
        return set(), 0
    status = frame.get("sample_status", pd.Series("", index=frame.index)).astype(str)
    valid_for_mae = frame.get("valid_for_mae_dataset", pd.Series(False, index=frame.index)).astype(str).str.lower().isin({"true", "1", "yes"})
    valid = frame[valid_for_mae | status.isin({"VALID_SAMPLE_TRADE_TRIGGERED", "VALID_SAMPLE_NO_ENTRY_MANIPULATED_LESS"})].copy()
    keys = set(_sample_key(row) for _, row in valid.iterrows() if str(row.get("direction", "")).strip())
    return keys, len(keys)


def _valid_rows(rows: list[dict[str, Any]], model: str | None = None) -> list[dict[str, Any]]:
    out = [row for row in rows if row.get("sample_status") in VALID_STATUSES and bool(row.get("valid_for_mae_dataset"))]
    if model:
        out = [row for row in out if row.get("m15_filter_model") == model]
    return out


def _numeric_values(rows: list[dict[str, Any]], field: str) -> list[float]:
    values = []
    for row in rows:
        value = row.get(field)
        try:
            if value is not None and not pd.isna(value):
                values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


def profile_for_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    manip = _numeric_values(rows, "manipulation_depth_usd")
    expansion = _numeric_values(rows, "expansion_usd")
    max_excursion = max(manip) if manip else None
    return {
        "samples": len(rows),
        "mae_avg": _mean(manip),
        "mae_median": _median(manip),
        "mae_p90": percentile(manip, 0.90),
        "mae_p95": percentile(manip, 0.95),
        "mae_max": _round(max_excursion),
        "conservative_sl": conservative_sl_distance(max_excursion),
        "expansion_avg": _mean(expansion),
        "expansion_median": _median(expansion),
        "expansion_max": _round(max(expansion)) if expansion else None,
        "tp_quartiles": tp_quartiles_from_h1(max(expansion) if expansion else None),
        "le_8": sum(1 for value in manip if value <= 8),
        "le_10": sum(1 for value in manip if value <= 10),
        "le_12": sum(1 for value in manip if value <= 12),
        "gt_12": sum(1 for value in manip if value > 12),
        "gt_20": sum(1 for value in manip if value > 20),
    }


def model_comparison(rows: list[dict[str, Any]], *, old_valid_keys: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for model in M15_MODELS:
        model_rows = [row for row in rows if row.get("m15_filter_model") == model]
        valid = _valid_rows(model_rows)
        valid_keys = set(_sample_key(row) for row in valid if row.get("direction"))
        status_counts = Counter(str(row.get("sample_status")) for row in model_rows)
        reason_counts = Counter(str(row.get("m15_invalid_reason") or row.get("sample_reason_codes") or "") for row in model_rows)
        entry_triggered = sum(1 for row in valid if row.get("entry_valid") is True)
        no_entry = sum(1 for row in valid if row.get("entry_valid") is not True)
        profile = profile_for_rows(valid)
        out.append(
            {
                "m15_filter_model": model,
                "rows": len(model_rows),
                "corrected_samples": len(valid),
                "current_m15_valid_count": sum(1 for row in model_rows if row.get("m15_sequence_valid") is True),
                "entry_triggered_count": entry_triggered,
                "no_entry_count": no_entry,
                "status_counts": json.dumps(dict(status_counts), sort_keys=True),
                "invalid_reason_counts": json.dumps(dict(reason_counts), sort_keys=True),
                "old_x45_valid_count": len(old_valid_keys),
                "overlap_with_old_x45": len(valid_keys & old_valid_keys),
                "old_valid_new_invalid": len(old_valid_keys - valid_keys),
                "old_invalid_new_valid": len(valid_keys - old_valid_keys),
                "mae_avg": profile["mae_avg"],
                "mae_median": profile["mae_median"],
                "mae_p90": profile["mae_p90"],
                "mae_p95": profile["mae_p95"],
                "mae_max": profile["mae_max"],
                "max_excursion": profile["mae_max"],
                "conservative_sl": profile["conservative_sl"],
                "tail_le_8": profile["le_8"],
                "tail_le_10": profile["le_10"],
                "tail_le_12": profile["le_12"],
                "tail_gt_12": profile["gt_12"],
                "tail_gt_20": profile["gt_20"],
            }
        )
    return out


def old_vs_corrected_comparison(rows: list[dict[str, Any]], old_valid_keys: set[str]) -> list[dict[str, Any]]:
    return [
        {
            "m15_filter_model": row["m15_filter_model"],
            "old_x45_valid_count": row["old_x45_valid_count"],
            "corrected_model_valid_count": row["corrected_samples"],
            "overlap": row["overlap_with_old_x45"],
            "old_valid_new_invalid": row["old_valid_new_invalid"],
            "old_invalid_new_valid": row["old_invalid_new_valid"],
        }
        for row in model_comparison(rows, old_valid_keys=old_valid_keys)
    ]


def build_summary(rows: list[dict[str, Any]], *, old_valid_keys: set[str], runtime_seconds: float) -> dict[str, Any]:
    comparison = model_comparison(rows, old_valid_keys=old_valid_keys)
    contexts = {str(row.get("h1_context_timestamp")) for row in rows if row.get("h1_context_timestamp")}
    per_model_profiles = {row["m15_filter_model"]: row for row in comparison}
    return {
        "runtime_seconds": round(runtime_seconds, 4),
        "h1_contexts_analyzed": len(contexts),
        "rows": len(rows),
        "old_x45_valid_count": len(old_valid_keys),
        "per_model": per_model_profiles,
        "safety": SAFETY,
        "verdict_flags": [
            "MECHANICAL_SPEC_CORRECTION_COMPLETE",
            "FIXED_X45_M15_SUPERSEDED",
            "CURRENT_M15_MODELS_IMPLEMENTED",
            "M15_MODEL_COMPARISON_COMPLETE",
            "OLD_NEW_M15_COMPARISON_COMPLETE",
            "ENTRY_REQUIRES_MAE_AND_RANGE_REENTRY",
            "SAME_H1_ENTRY_WINDOW_DEFINED",
            "REACTION_CONFIRMATION_REMOVED_AS_GATE",
            "H1_DOMINANT_RULE_DOCUMENTED",
            "STANDARD_TP1_FALLBACK_DEFERRED",
            "STRATEGY_2_REMAINS_RESEARCH_ONLY",
            "NO_LIVE_DEPLOYMENT_DECISION",
        ],
    }


def build_mechanical_spec_report(
    *,
    symbol: str,
    market_data: dict[str, pd.DataFrame],
    date_from: Any,
    date_to: Any,
    config: MechanicalSpecConfig,
) -> dict[str, Any]:
    started = time.perf_counter()
    rows = build_corrected_mechanical_samples(symbol=symbol, market_data=market_data, date_from=date_from, date_to=date_to, config=config)
    old_valid_keys, _ = load_old_valid_keys(config.old_samples_path)
    runtime_seconds = time.perf_counter() - started
    comparison = model_comparison(rows, old_valid_keys=old_valid_keys)
    return {
        "rows": rows,
        "model_comparison": comparison,
        "old_vs_corrected": old_vs_corrected_comparison(rows, old_valid_keys),
        "entry_diagnostics": [
            {
                "sample_id": row["sample_id"],
                "m15_filter_model": row["m15_filter_model"],
                "entry_status": row["entry_status"],
                "entry_valid": row["entry_valid"],
                "mae_reached": row["mae_reached"],
                "range_reentry_reached": row["range_reentry_reached"],
                "mae_reached_timestamp": row["mae_reached_timestamp"],
                "range_reentry_timestamp": row["range_reentry_timestamp"],
                "entry_timestamp": row["entry_timestamp"],
                "sample_status": row["sample_status"],
            }
            for row in rows
        ],
        "summary": build_summary(rows, old_valid_keys=old_valid_keys, runtime_seconds=runtime_seconds),
    }


def write_mechanical_spec_outputs(report: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows = report["rows"]
    corrected_csv = output / "corrected_mechanical_samples.csv"
    corrected_jsonl = output / "corrected_mechanical_samples.jsonl"
    comparison_csv = output / "m15_model_comparison.csv"
    old_new_csv = output / "old_vs_corrected_m15_comparison.csv"
    entry_csv = output / "mechanical_entry_diagnostics.csv"
    summary_json = output / "mechanical_spec_summary.json"
    report_md = output / "mechanical_spec_report.md"

    _write_csv(corrected_csv, rows, CORRECTED_SAMPLE_FIELDS)
    with corrected_jsonl.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    _write_csv(comparison_csv, report["model_comparison"], list(report["model_comparison"][0].keys()) if report["model_comparison"] else [])
    _write_csv(old_new_csv, report["old_vs_corrected"], list(report["old_vs_corrected"][0].keys()) if report["old_vs_corrected"] else [])
    _write_csv(entry_csv, report["entry_diagnostics"], list(report["entry_diagnostics"][0].keys()) if report["entry_diagnostics"] else [])
    summary_json.write_text(json.dumps(report["summary"], indent=2, sort_keys=True), encoding="utf-8")
    report_md.write_text(mechanical_report_markdown(report["summary"]), encoding="utf-8")
    return {
        "corrected_mechanical_samples_csv": str(corrected_csv),
        "corrected_mechanical_samples_jsonl": str(corrected_jsonl),
        "m15_model_comparison_csv": str(comparison_csv),
        "old_vs_corrected_m15_comparison_csv": str(old_new_csv),
        "mechanical_entry_diagnostics_csv": str(entry_csv),
        "mechanical_spec_summary_json": str(summary_json),
        "mechanical_spec_report_md": str(report_md),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def mechanical_report_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Strategy 2 Mechanical Spec Correction",
        "",
        "Research-only diagnostic report. Fixed HH:45/x:45 M15 logic is superseded by three deterministic current-M15 models.",
        "",
        "## Context",
        "",
        "Previous Strategy 2 statistical recorder outputs used a fixed HH:45/x:45 M15 sequence filter. The user clarified that the relevant M15 is dynamic while price moves toward the H1 liquidity level, and that reaction/candle confirmation is not a mandatory entry gate. This report corrects that mechanical interpretation and compares the old x:45 result against three deterministic current-M15 approximations.",
        "",
        "## Safety",
        "",
        "- Strategy 3 untouched.",
        "- data/XAUUSD/*.csv untouched.",
        "- No live trading, Telegram, broker execution, orders, or runtime registration.",
        "",
        "## Corrected Rules",
        "",
        "- H1 context uses previous H1 and/or first-pass dominant H1 range detection.",
        "- Dominant H1 requires full containment: internal high < outer high and internal low > outer low.",
        "- A level take by 1 pip is enough.",
        "- If both H1 high and low are taken in the same context, only the first side is considered; same-bar ambiguity is rejected.",
        "- M15 models: containing, preceding, approach_window.",
        "- Long is invalid when the relevant/current M15 high is taken before the H1 low.",
        "- Short is invalid when the relevant/current M15 low is taken before the H1 high.",
        "- Entry requires average MAE reached inside the same H1 candle as the level take, then range re-entry by 1 pip.",
        "- Re-entry is a price touch, not a candle close.",
        "- Reaction confirmation is ex-post metadata only and is not an entry gate.",
        "- Conservative SL remains Max Excursion * 1.25.",
        "- TP remains anchored to H1 liquidity level; standard TP1 fallback is deferred.",
        "",
        "## M15 Model Definitions",
        "",
        "- containing: M15 candle whose open time contains the H1 level-take timestamp.",
        "- preceding: last M15 candle fully closed before the H1 level-take timestamp.",
        "- approach_window: all M15 candles from H1 context open through the H1 level-take timestamp.",
        "",
        "## Method",
        "",
        "For each H1 context and selected H1 reference, the audit detects the first H1 high/low take using a 1-pip threshold, applies each M15 model, evaluates same-H1 MAE reach and same-H1 range re-entry, and records manipulation/expansion distributions. The old x:45 recorder output is loaded only for overlap comparison.",
        "",
        "## Results",
        "",
        f"- H1 contexts analyzed: {summary.get('h1_contexts_analyzed')}",
        f"- Old x45 valid count: {summary.get('old_x45_valid_count')}",
        "",
        "| M15 model | corrected samples | current-M15 valid | entry triggered | no-entry | overlap old | old valid/new invalid | old invalid/new valid | MAE avg | max excursion | conservative SL | <=8 | <=10 | <=12 | >12 | >20 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, row in summary.get("per_model", {}).items():
        lines.append(
            "| "
            + " | ".join(
                [
                    str(model),
                    str(row.get("corrected_samples")),
                    str(row.get("current_m15_valid_count")),
                    str(row.get("entry_triggered_count")),
                    str(row.get("no_entry_count")),
                    str(row.get("overlap_with_old_x45")),
                    str(row.get("old_valid_new_invalid")),
                    str(row.get("old_invalid_new_valid")),
                    str(row.get("mae_avg")),
                    str(row.get("max_excursion")),
                    str(row.get("conservative_sl")),
                    str(row.get("tail_le_8")),
                    str(row.get("tail_le_10")),
                    str(row.get("tail_le_12")),
                    str(row.get("tail_gt_12")),
                    str(row.get("tail_gt_20")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Verdict Flags",
            "",
            *[f"- {flag}" for flag in summary.get("verdict_flags", [])],
            "",
            "## Limitations",
            "",
            "- The user must still choose which current-M15 interpretation best matches the intended mechanical idea.",
            "- No manual labels are used.",
            "- No profitability, deployment, or live-readiness conclusion is made.",
            "- Dominant H1 handling is a deterministic first pass using full containment.",
            "- The large Max Excursion / conservative SL values are reported honestly and are not clamped.",
            "",
            "## Next Strategy 2-Only Step",
            "",
            "- feat/strategy-2-m15-model-selection-review",
        ]
    )
    return "\n".join(lines) + "\n"
