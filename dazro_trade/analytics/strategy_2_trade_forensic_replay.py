from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable

import pandas as pd

from dazro_trade.analysis.human_trade_management import metric_block_from_r
from dazro_trade.analytics.strategy_2_entry_quality_diagnostics import read_executed_trades
from dazro_trade.analytics.strategy_2_hourly_session_diagnostics import (
    sample_size_interpretation,
    sample_size_label,
)


SAFETY = {
    "research_only": True,
    "dry_run": True,
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "order_execution_enabled": False,
    "broker_called": False,
    "telegram_sent": False,
    "order_sent": False,
    "order_send_called": False,
    "strategy_2_entry_logic_changed": False,
    "strategy_3_logic_changed": False,
    "adelin_logic_changed": False,
    "machine_learning_used": False,
    "optimization_run": False,
}

FORENSIC_FIELDS = [
    "trade_id",
    "symbol",
    "strategy",
    "direction",
    "signal_timestamp",
    "entry_timestamp",
    "exit_timestamp",
    "outcome",
    "r_multiple",
    "entry_price",
    "stop_loss",
    "take_profit",
    "close_price",
    "sl_distance_usd",
    "tp_distance_usd",
    "planned_rr",
    "actual_exit_distance_usd",
    "actual_exit_R",
    "tp_sl_ratio_label",
    "stop_size_bucket",
    "target_size_bucket",
    "rr_bucket",
    "mfe_usd",
    "mae_usd",
    "mfe_R",
    "mae_R",
    "max_favorable_price",
    "max_adverse_price",
    "timestamp_mfe",
    "timestamp_mae",
    "reached_be_plus_10",
    "reached_partial_plus_15",
    "reached_partial_plus_20",
    "reached_0_5R",
    "reached_1R",
    "reached_2R",
    "closest_distance_to_tp_usd",
    "closest_distance_to_sl_usd",
    "closest_distance_to_tp_R",
    "closest_distance_to_sl_R",
    "almost_hit_tp",
    "almost_hit_sl",
    "bars_to_mfe",
    "bars_to_mae",
    "bars_to_exit",
    "minutes_to_mfe",
    "minutes_to_mae",
    "minutes_to_exit",
    "time_in_profit_minutes",
    "time_in_loss_minutes",
    "time_near_entry_minutes",
    "first_m5_close_quality",
    "reaction_state_3_m5",
    "reaction_state_5_m5",
    "retest_quality",
    "entry_quality_label",
    "primary_blocker",
    "secondary_blocker",
    "tp_realism_label",
    "sl_realism_label",
    "timeout_root_cause",
    "trade_failure_mode",
    "pre_entry_obstacle_distance_R",
    "target_blocked_by_obstacle_proxy",
    "human_review_required",
    "human_review_priority",
    "human_would_take",
    "human_would_skip",
    "human_would_wait_retest",
    "human_would_enter_earlier",
    "human_would_exit_early",
    "human_would_partial",
    "human_would_let_run",
    "human_correct_entry_zone",
    "human_correct_sl_zone",
    "human_correct_tp_zone",
    "human_reason",
    "screenshot_before_entry_path",
    "screenshot_after_entry_path",
    "screenshot_exit_path",
    "forensic_reason_codes",
]

HUMAN_LABEL_PACK_FIELDS = [
    "trade_id",
    "symbol",
    "direction",
    "entry_timestamp",
    "outcome",
    "r_multiple",
    "entry_price",
    "stop_loss",
    "take_profit",
    "sl_distance_usd",
    "tp_distance_usd",
    "planned_rr",
    "mfe_R",
    "mae_R",
    "entry_quality_label",
    "trade_failure_mode",
    "human_review_required",
    "human_review_priority",
    "human_would_take",
    "human_would_skip",
    "human_would_wait_retest",
    "human_would_enter_earlier",
    "human_would_exit_early",
    "human_would_partial",
    "human_would_let_run",
    "human_correct_entry_zone",
    "human_correct_sl_zone",
    "human_correct_tp_zone",
    "human_reason",
    "screenshot_before_entry_path",
    "screenshot_after_entry_path",
    "screenshot_exit_path",
]

BREAKDOWN_FIELDS = [
    "dimension",
    "category",
    "trades",
    "sample_label",
    "interpretation",
    "PF",
    "WR",
    "AvgR",
    "MedianR",
    "total_R",
    "MaxDD",
]

TIMEOUT_FIELDS = [
    "timeout_root_cause",
    "trades",
    "sample_label",
    "interpretation",
    "PF",
    "WR",
    "AvgR",
    "MedianR",
    "total_R",
    "MaxDD",
    "avg_mfe_R",
    "avg_mae_R",
    "reached_plus_10",
    "reached_plus_15",
    "reached_plus_20",
    "almost_hit_tp",
]


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _direction(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"BUY", "BULL", "BULLISH", "LONG"}:
        return "LONG"
    if text in {"SELL", "BEAR", "BEARISH", "SHORT"}:
        return "SHORT"
    return text or "UNKNOWN"


def _r_value(row: dict[str, Any]) -> float | None:
    for field in ("r_multiple", "result_baseline_R"):
        value = _to_float(row.get(field))
        if value is not None:
            return value
    return None


def _prepare_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], utc=True, errors="coerce")
        out = out.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    return out


def _entry_timestamp(row: dict[str, Any]) -> pd.Timestamp | None:
    for field in ("entry_timestamp", "signal_timestamp", "timestamp", "time"):
        ts = _timestamp(row.get(field))
        if ts is not None:
            return ts
    return None


def _exit_timestamp(row: dict[str, Any]) -> pd.Timestamp | None:
    for field in ("exit_timestamp", "exit_time"):
        ts = _timestamp(row.get(field))
        if ts is not None:
            return ts
    entry_ts = _entry_timestamp(row)
    bars_held = _to_float(row.get("bars_held"))
    if entry_ts is not None and bars_held is not None:
        return entry_ts + pd.Timedelta(minutes=float(bars_held))
    return None


def _price_fields(row: dict[str, Any]) -> tuple[float | None, float | None, float | None, float | None]:
    entry = _to_float(row.get("entry_price") or row.get("entry"))
    stop = _to_float(row.get("stop_loss") or row.get("stop"))
    target = (
        _to_float(row.get("take_profit"))
        or _to_float(row.get("tp2"))
        or _to_float(row.get("tp1"))
        or _to_float(row.get("original_take_profit"))
    )
    close = _to_float(row.get("close_price") or row.get("exit_price"))
    return entry, stop, target, close


def calculate_tp_sl(entry: float, stop: float, target: float, direction: str) -> dict[str, Any]:
    sl_distance = abs(entry - stop)
    tp_distance = target - entry if direction == "LONG" else entry - target
    planned_rr = tp_distance / sl_distance if sl_distance > 0 else None
    return {
        "sl_distance_usd": round(sl_distance, 4),
        "tp_distance_usd": round(tp_distance, 4),
        "planned_rr": round(planned_rr, 4) if planned_rr is not None else None,
        "tp_sl_ratio_label": _rr_label(planned_rr),
        "stop_size_bucket": _distance_bucket(sl_distance, kind="stop"),
        "target_size_bucket": _distance_bucket(tp_distance, kind="target"),
        "rr_bucket": _rr_bucket(planned_rr),
    }


def _rr_label(planned_rr: float | None) -> str:
    if planned_rr is None:
        return "RR_UNKNOWN"
    if planned_rr < 1.0:
        return "RR_LT_1"
    if planned_rr < 1.5:
        return "RR_1_TO_1_5"
    if planned_rr < 2.0:
        return "RR_1_5_TO_2"
    return "RR_GE_2"


def _rr_bucket(planned_rr: float | None) -> str:
    if planned_rr is None:
        return "rr_unknown"
    if planned_rr < 0.75:
        return "rr_below_0_75"
    if planned_rr < 1.0:
        return "rr_0_75_to_1"
    if planned_rr < 1.5:
        return "rr_1_to_1_5"
    return "rr_above_1_5"


def _distance_bucket(distance: float | None, *, kind: str) -> str:
    if distance is None:
        return f"{kind}_unknown"
    if distance < 15:
        return f"{kind}_lt_15"
    if distance < 30:
        return f"{kind}_15_to_30"
    if distance < 45:
        return f"{kind}_30_to_45"
    return f"{kind}_ge_45"


def _path_after_entry(frame: pd.DataFrame | None, entry_ts: Any, exit_ts: Any) -> pd.DataFrame:
    data = _prepare_frame(frame)
    entry = _timestamp(entry_ts)
    exit_ = _timestamp(exit_ts)
    if data.empty or entry is None or "time" not in data.columns:
        return pd.DataFrame()
    if exit_ is None or exit_ < entry:
        exit_ = entry + pd.Timedelta(minutes=480)
    return data[(data["time"] >= entry) & (data["time"] <= exit_)].copy().reset_index(drop=True)


def _minutes_between(start: Any, end: Any) -> float | None:
    s = _timestamp(start)
    e = _timestamp(end)
    if s is None or e is None:
        return None
    return round((e - s).total_seconds() / 60.0, 4)


def calculate_path_metrics(
    *,
    path: pd.DataFrame,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    exit_ts: Any,
    fallback_mfe: float | None = None,
    fallback_mae: float | None = None,
) -> dict[str, Any]:
    risk = abs(entry - stop)
    if path.empty:
        mfe = fallback_mfe or 0.0
        mae = fallback_mae or 0.0
        return _empty_path_metrics(mfe=mfe, mae=mae, risk=risk, entry=entry, stop=stop, target=target, direction=direction)

    highs = path["high"].astype(float)
    lows = path["low"].astype(float)
    closes = path["close"].astype(float)
    if direction == "LONG":
        favorable_values = highs - entry
        adverse_values = entry - lows
        max_fav_idx = int(favorable_values.idxmax())
        max_adv_idx = int(adverse_values.idxmax())
        max_fav_price = float(highs.iloc[max_fav_idx])
        max_adv_price = float(lows.iloc[max_adv_idx])
        distance_to_tp = (target - highs).clip(lower=0)
        distance_to_sl = (lows - stop).clip(lower=0)
        profit_mask = closes > entry
        loss_mask = closes < entry
    else:
        favorable_values = entry - lows
        adverse_values = highs - entry
        max_fav_idx = int(favorable_values.idxmax())
        max_adv_idx = int(adverse_values.idxmax())
        max_fav_price = float(lows.iloc[max_fav_idx])
        max_adv_price = float(highs.iloc[max_adv_idx])
        distance_to_tp = (lows - target).clip(lower=0)
        distance_to_sl = (stop - highs).clip(lower=0)
        profit_mask = closes < entry
        loss_mask = closes > entry

    mfe = max(0.0, float(favorable_values.iloc[max_fav_idx]))
    mae = max(0.0, float(adverse_values.iloc[max_adv_idx]))
    closest_tp = float(distance_to_tp.min()) if len(distance_to_tp) else None
    closest_sl = float(distance_to_sl.min()) if len(distance_to_sl) else None
    near_entry = (abs(closes - entry) <= max(0.25, risk * 0.10)) if risk else closes == entry
    entry_ts = path.iloc[0]["time"]
    mfe_ts = path.iloc[max_fav_idx]["time"]
    mae_ts = path.iloc[max_adv_idx]["time"]
    exit_time = _timestamp(exit_ts) or path.iloc[-1]["time"]
    return {
        "mfe_usd": round(mfe, 4),
        "mae_usd": round(mae, 4),
        "mfe_R": round(mfe / risk, 4) if risk else None,
        "mae_R": round(mae / risk, 4) if risk else None,
        "max_favorable_price": round(max_fav_price, 4),
        "max_adverse_price": round(max_adv_price, 4),
        "timestamp_mfe": _timestamp_text(mfe_ts),
        "timestamp_mae": _timestamp_text(mae_ts),
        "reached_be_plus_10": mfe >= 10.0,
        "reached_partial_plus_15": mfe >= 15.0,
        "reached_partial_plus_20": mfe >= 20.0,
        "reached_0_5R": bool(risk and mfe >= 0.5 * risk),
        "reached_1R": bool(risk and mfe >= risk),
        "reached_2R": bool(risk and mfe >= 2 * risk),
        "closest_distance_to_tp_usd": round(closest_tp, 4) if closest_tp is not None else None,
        "closest_distance_to_sl_usd": round(closest_sl, 4) if closest_sl is not None else None,
        "closest_distance_to_tp_R": round(closest_tp / risk, 4) if risk and closest_tp is not None else None,
        "closest_distance_to_sl_R": round(closest_sl / risk, 4) if risk and closest_sl is not None else None,
        "almost_hit_tp": bool(risk and closest_tp is not None and 0 < closest_tp <= 0.15 * risk),
        "almost_hit_sl": bool(risk and closest_sl is not None and 0 < closest_sl <= 0.15 * risk),
        "bars_to_mfe": max_fav_idx + 1,
        "bars_to_mae": max_adv_idx + 1,
        "bars_to_exit": len(path),
        "minutes_to_mfe": _minutes_between(entry_ts, mfe_ts),
        "minutes_to_mae": _minutes_between(entry_ts, mae_ts),
        "minutes_to_exit": _minutes_between(entry_ts, exit_time),
        "time_in_profit_minutes": int(profit_mask.sum()),
        "time_in_loss_minutes": int(loss_mask.sum()),
        "time_near_entry_minutes": int(near_entry.sum()),
    }


def _empty_path_metrics(*, mfe: float, mae: float, risk: float, entry: float, stop: float, target: float, direction: str) -> dict[str, Any]:
    max_fav_price = entry + mfe if direction == "LONG" else entry - mfe
    max_adv_price = entry - mae if direction == "LONG" else entry + mae
    closest_tp = max(0.0, abs(target - entry) - mfe)
    closest_sl = max(0.0, abs(entry - stop) - mae)
    return {
        "mfe_usd": round(mfe, 4),
        "mae_usd": round(mae, 4),
        "mfe_R": round(mfe / risk, 4) if risk else None,
        "mae_R": round(mae / risk, 4) if risk else None,
        "max_favorable_price": round(max_fav_price, 4),
        "max_adverse_price": round(max_adv_price, 4),
        "timestamp_mfe": None,
        "timestamp_mae": None,
        "reached_be_plus_10": mfe >= 10.0,
        "reached_partial_plus_15": mfe >= 15.0,
        "reached_partial_plus_20": mfe >= 20.0,
        "reached_0_5R": bool(risk and mfe >= 0.5 * risk),
        "reached_1R": bool(risk and mfe >= risk),
        "reached_2R": bool(risk and mfe >= 2 * risk),
        "closest_distance_to_tp_usd": round(closest_tp, 4),
        "closest_distance_to_sl_usd": round(closest_sl, 4),
        "closest_distance_to_tp_R": round(closest_tp / risk, 4) if risk else None,
        "closest_distance_to_sl_R": round(closest_sl / risk, 4) if risk else None,
        "almost_hit_tp": bool(risk and 0 < closest_tp <= 0.15 * risk),
        "almost_hit_sl": bool(risk and 0 < closest_sl <= 0.15 * risk),
        "bars_to_mfe": None,
        "bars_to_mae": None,
        "bars_to_exit": None,
        "minutes_to_mfe": None,
        "minutes_to_mae": None,
        "minutes_to_exit": None,
        "time_in_profit_minutes": None,
        "time_in_loss_minutes": None,
        "time_near_entry_minutes": None,
    }


def _pre_entry_m15(frame: pd.DataFrame | None, entry_ts: Any, count: int = 20) -> pd.DataFrame:
    data = _prepare_frame(frame)
    ts = _timestamp(entry_ts)
    if data.empty or ts is None or "time" not in data.columns:
        return pd.DataFrame()
    return data[data["time"] < ts].tail(count).copy()


def _pre_entry_obstacle_distance_R(m15: pd.DataFrame, direction: str, entry: float, target: float, risk: float) -> float | None:
    if m15.empty or risk <= 0:
        return None
    if direction == "LONG":
        distances = [float(high) - entry for high in m15["high"].dropna().tolist() if float(high) > entry]
    else:
        distances = [entry - float(low) for low in m15["low"].dropna().tolist() if float(low) < entry]
    distances = [distance for distance in distances if distance > 0]
    if not distances:
        return None
    return round(min(distances) / risk, 4)


def classify_tp_realism(record: dict[str, Any]) -> str:
    outcome = str(record.get("outcome") or "").upper()
    planned_rr = _to_float(record.get("planned_rr"))
    mfe_r = _to_float(record.get("mfe_R"))
    blocked = bool(record.get("target_blocked_by_obstacle_proxy"))
    if outcome.startswith("TP") or (planned_rr is not None and mfe_r is not None and mfe_r >= planned_rr):
        return "TP_REALISTIC"
    if planned_rr is None or mfe_r is None:
        return "TP_UNKNOWN"
    if outcome == "TIMEOUT_CLOSE" and mfe_r < max(0.50, planned_rr * 0.65):
        return "TP_TOO_FAR"
    if planned_rr > 1.25 and mfe_r < planned_rr * 0.75:
        return "TP_TOO_FAR"
    if blocked:
        return "TP_BLOCKED_BY_OBSTACLE"
    return "TP_UNKNOWN"


def classify_sl_realism(record: dict[str, Any], *, pre_entry_m15: pd.DataFrame) -> str:
    direction = str(record.get("direction") or "")
    entry = _to_float(record.get("entry_price"))
    stop = _to_float(record.get("stop_loss"))
    sl_distance = _to_float(record.get("sl_distance_usd"))
    if entry is None or stop is None or sl_distance is None:
        return "SL_UNKNOWN"
    if sl_distance < 15.0:
        return "SL_TOO_TIGHT"
    if sl_distance >= 45.0:
        return "SL_TOO_WIDE"
    if not pre_entry_m15.empty:
        if direction == "LONG":
            prior_low = float(pre_entry_m15["low"].min())
            if stop <= prior_low:
                return "SL_STRUCTURALLY_PROTECTED"
            return "SL_TOO_TIGHT"
        if direction == "SHORT":
            prior_high = float(pre_entry_m15["high"].max())
            if stop >= prior_high:
                return "SL_STRUCTURALLY_PROTECTED"
            return "SL_TOO_TIGHT"
    return "SL_UNKNOWN"


def classify_timeout_root_cause(record: dict[str, Any]) -> str | None:
    if str(record.get("outcome") or "").upper() != "TIMEOUT_CLOSE":
        return None
    entry_label = str(record.get("entry_quality_label") or "")
    reaction5 = str(record.get("reaction_state_5_m5") or "")
    mfe_r = _to_float(record.get("mfe_R")) or 0.0
    mae_r = _to_float(record.get("mae_R")) or 0.0
    if entry_label == "NO_TRADE_PRICE_ESCAPED":
        return "TIMEOUT_ENTRY_TOO_LATE"
    if reaction5 != "REACTION_ALIVE" and mfe_r < 0.35:
        return "TIMEOUT_NO_FOLLOW_THROUGH"
    if record.get("tp_realism_label") == "TP_TOO_FAR" or (mfe_r >= 0.50 and not record.get("almost_hit_tp")):
        return "TIMEOUT_TARGET_TOO_FAR"
    if mfe_r < 1.0 and mae_r < 1.0 and (record.get("time_near_entry_minutes") or 0) >= 30:
        return "TIMEOUT_PRICE_CHOP"
    if record.get("target_blocked_by_obstacle_proxy"):
        return "TIMEOUT_TARGET_BLOCKED"
    return "TIMEOUT_UNKNOWN"


def classify_failure_mode(record: dict[str, Any]) -> str:
    entry_label = str(record.get("entry_quality_label") or "")
    first_m5 = str(record.get("first_m5_close_quality") or "")
    reaction3 = str(record.get("reaction_state_3_m5") or "")
    outcome = str(record.get("outcome") or "").upper()
    timeout = str(record.get("timeout_root_cause") or "")
    if entry_label == "NO_TRADE_PRICE_ESCAPED":
        return "ENTRY_TOO_LATE"
    if entry_label == "NO_TRADE_REACTION_ALREADY_DEAD" or reaction3 == "REACTION_DEAD":
        return "REACTION_DEAD"
    if timeout == "TIMEOUT_TARGET_TOO_FAR":
        return "TARGET_TOO_AMBITIOUS"
    if timeout == "TIMEOUT_PRICE_CHOP":
        return "CHOP_TIMEOUT"
    if timeout == "TIMEOUT_NO_FOLLOW_THROUGH":
        return "NO_FOLLOW_THROUGH"
    if entry_label == "NO_TRADE_DIRTY_SETUP":
        return "DIRTY_SETUP"
    if first_m5 in {"BAD_CLOSE", "INVALIDATING_CLOSE"} and outcome in {"SL", "TIMEOUT_CLOSE"}:
        return "BAD_M5_CLOSE_IGNORED"
    if str(record.get("sl_realism_label")) == "SL_TOO_TIGHT":
        return "STOP_TOO_TIGHT"
    if str(record.get("sl_realism_label")) == "SL_TOO_WIDE":
        return "STOP_TOO_WIDE"
    if record.get("almost_hit_tp") and outcome != "TP2":
        return "GOOD_TRADE_BAD_MANAGEMENT"
    return "UNKNOWN"


def _review_decision(record: dict[str, Any]) -> tuple[bool, str]:
    high = {
        "GOOD_TRADE_BAD_MANAGEMENT",
        "TARGET_TOO_AMBITIOUS",
        "STOP_TOO_TIGHT",
        "STOP_TOO_WIDE",
    }
    medium = {
        "ENTRY_TOO_LATE",
        "DIRTY_SETUP",
        "NO_FOLLOW_THROUGH",
        "BAD_M5_CLOSE_IGNORED",
        "CHOP_TIMEOUT",
    }
    mode = str(record.get("trade_failure_mode") or "")
    if record.get("almost_hit_tp") or (record.get("reached_partial_plus_20") and record.get("outcome") in {"SL", "TIMEOUT_CLOSE"}):
        return True, "HIGH"
    if mode in high:
        return True, "HIGH"
    if mode in medium or record.get("outcome") == "TIMEOUT_CLOSE":
        return True, "MEDIUM"
    return False, "LOW"


def _actual_exit(entry: float, close: float | None, direction: str, risk: float) -> tuple[float | None, float | None]:
    if close is None:
        return None, None
    distance = close - entry if direction == "LONG" else entry - close
    return round(distance, 4), round(distance / risk, 4) if risk else None


def _merge_diagnostics(rows: list[dict[str, Any]], entry_quality_dir: Path | None) -> dict[str, dict[str, Any]]:
    if entry_quality_dir is None:
        return {}
    path = entry_quality_dir / "strategy_2_entry_quality_trades.csv"
    if not path.exists():
        return {}
    diagnostic_rows, _ = read_executed_trades(path)
    return {str(row.get("trade_id") or idx): row for idx, row in enumerate(diagnostic_rows)}


def enrich_trade_forensics(
    row: dict[str, Any],
    *,
    row_index: int,
    m1: pd.DataFrame | None,
    m15: pd.DataFrame | None,
    diagnostics: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    trade_id = str(row.get("trade_id") or row.get("id") or row_index)
    diagnostic = (diagnostics or {}).get(trade_id, {})
    merged = {**row, **diagnostic}
    direction = _direction(merged.get("direction"))
    entry_ts = _entry_timestamp(merged)
    exit_ts = _exit_timestamp(merged)
    entry, stop, target, close = _price_fields(merged)
    if entry is None or stop is None or target is None:
        return {field: None for field in FORENSIC_FIELDS} | {"trade_id": trade_id, "forensic_reason_codes": "missing_entry_stop_or_target"}
    risk = abs(entry - stop)
    tp_sl = calculate_tp_sl(entry, stop, target, direction)
    actual_exit_distance, actual_exit_r = _actual_exit(entry, close, direction, risk)
    path = _path_after_entry(m1, entry_ts, exit_ts)
    path_metrics = calculate_path_metrics(
        path=path,
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        exit_ts=exit_ts,
        fallback_mfe=_to_float(merged.get("mfe")),
        fallback_mae=_to_float(merged.get("mae")),
    )
    prior_m15 = _pre_entry_m15(m15, entry_ts)
    obstacle_r = _pre_entry_obstacle_distance_R(prior_m15, direction, entry, target, risk)
    planned_rr = tp_sl["planned_rr"]
    target_blocked = bool(obstacle_r is not None and planned_rr is not None and obstacle_r < planned_rr)
    base = {
        "trade_id": trade_id,
        "symbol": merged.get("symbol"),
        "strategy": merged.get("strategy") or merged.get("strategy_name"),
        "direction": direction,
        "signal_timestamp": _timestamp_text(merged.get("signal_timestamp") or merged.get("timestamp")),
        "entry_timestamp": _timestamp_text(entry_ts),
        "exit_timestamp": _timestamp_text(exit_ts),
        "outcome": merged.get("outcome"),
        "r_multiple": _r_value(merged),
        "entry_price": round(entry, 4),
        "stop_loss": round(stop, 4),
        "take_profit": round(target, 4),
        "close_price": close,
        "actual_exit_distance_usd": actual_exit_distance,
        "actual_exit_R": actual_exit_r,
        **tp_sl,
        **path_metrics,
        "first_m5_close_quality": diagnostic.get("first_m5_close_quality"),
        "reaction_state_3_m5": diagnostic.get("reaction_state_3_m5"),
        "reaction_state_5_m5": diagnostic.get("reaction_state_5_m5"),
        "retest_quality": diagnostic.get("retest_quality"),
        "entry_quality_label": diagnostic.get("entry_quality_label"),
        "primary_blocker": diagnostic.get("primary_blocker"),
        "secondary_blocker": diagnostic.get("secondary_blocker"),
        "pre_entry_obstacle_distance_R": obstacle_r,
        "target_blocked_by_obstacle_proxy": target_blocked,
    }
    base["tp_realism_label"] = classify_tp_realism(base)
    base["sl_realism_label"] = classify_sl_realism(base, pre_entry_m15=prior_m15)
    base["timeout_root_cause"] = classify_timeout_root_cause(base)
    base["trade_failure_mode"] = classify_failure_mode(base)
    review_required, review_priority = _review_decision(base)
    reason_codes = _reason_codes(base, path_available=not path.empty)
    base.update(
        {
            "human_review_required": review_required,
            "human_review_priority": review_priority,
            "human_would_take": None,
            "human_would_skip": None,
            "human_would_wait_retest": None,
            "human_would_enter_earlier": None,
            "human_would_exit_early": None,
            "human_would_partial": None,
            "human_would_let_run": None,
            "human_correct_entry_zone": None,
            "human_correct_sl_zone": None,
            "human_correct_tp_zone": None,
            "human_reason": None,
            "screenshot_before_entry_path": None,
            "screenshot_after_entry_path": None,
            "screenshot_exit_path": None,
            "forensic_reason_codes": ";".join(reason_codes),
        }
    )
    return {field: base.get(field) for field in FORENSIC_FIELDS}


def _reason_codes(record: dict[str, Any], *, path_available: bool) -> list[str]:
    codes: list[str] = []
    if not path_available:
        codes.append("m1_path_missing_used_exported_mfe_mae")
    if record.get("reached_be_plus_10"):
        codes.append("reached_plus_10")
    if record.get("reached_partial_plus_15"):
        codes.append("reached_plus_15")
    if record.get("reached_partial_plus_20"):
        codes.append("reached_plus_20")
    if record.get("almost_hit_tp"):
        codes.append("almost_hit_tp")
    if record.get("almost_hit_sl"):
        codes.append("almost_hit_sl")
    if record.get("target_blocked_by_obstacle_proxy"):
        codes.append("pre_entry_obstacle_before_target")
    if record.get("timeout_root_cause"):
        codes.append(str(record["timeout_root_cause"]).lower())
    if record.get("trade_failure_mode"):
        codes.append(str(record["trade_failure_mode"]).lower())
    return codes or ["no_special_forensic_marker"]


def build_trade_forensics(
    trade_rows: Iterable[dict[str, Any]],
    *,
    market_data: dict[str, pd.DataFrame],
    source_path: str,
    entry_quality_dir: Path | None = None,
    entry_filter_dir: Path | None = None,
    symbol: str = "XAUUSD",
) -> dict[str, Any]:
    trade_rows = list(trade_rows)
    diagnostics = _merge_diagnostics(trade_rows, entry_quality_dir)
    m1 = market_data.get("M1")
    m15 = market_data.get("M15")
    enriched = [
        enrich_trade_forensics(row, row_index=idx, m1=m1, m15=m15, diagnostics=diagnostics)
        for idx, row in enumerate(trade_rows)
    ]
    breakdown_rows = _breakdown_rows(enriched)
    timeout_rows = _timeout_breakdown(enriched)
    tp_sl_rows = [row for row in breakdown_rows if row["dimension"] in {"stop_size_bucket", "target_size_bucket", "rr_bucket", "tp_realism_label", "sl_realism_label"}]
    summary = {
        "research_only": True,
        "safety": SAFETY,
        "source": {
            "symbol": symbol,
            "trades_path": source_path,
            "entry_quality_dir": str(entry_quality_dir) if entry_quality_dir else None,
            "entry_filter_dir": str(entry_filter_dir) if entry_filter_dir else None,
            "trades_analyzed": len(enriched),
            "m1_loaded": bool(m1 is not None and not m1.empty),
            "m15_loaded": bool(m15 is not None and not m15.empty),
            "missing_path_rows": sum(1 for row in enriched if not row.get("bars_to_exit")),
        },
        "baseline": metric_block_from_r(row["r_multiple"] for row in enriched if row.get("r_multiple") is not None),
        "tp_sl_distribution": _tp_sl_summary(enriched),
        "mfe_mae_summary": _mfe_mae_summary(enriched),
        "reach_counts": _reach_counts(enriched),
        "timeout_root_cause_counts": dict(Counter(str(row.get("timeout_root_cause") or "NOT_TIMEOUT") for row in enriched if row.get("outcome") == "TIMEOUT_CLOSE")),
        "tp_realism_counts": dict(Counter(str(row.get("tp_realism_label") or "TP_UNKNOWN") for row in enriched)),
        "sl_realism_counts": dict(Counter(str(row.get("sl_realism_label") or "SL_UNKNOWN") for row in enriched)),
        "failure_mode_counts": dict(Counter(str(row.get("trade_failure_mode") or "UNKNOWN") for row in enriched)),
        "human_review_priority_counts": dict(Counter(str(row.get("human_review_priority") or "LOW") for row in enriched if row.get("human_review_required"))),
        "human_review_required_count": sum(1 for row in enriched if row.get("human_review_required")),
        "key_answers": _key_answers(enriched),
    }
    return {
        "trade_rows": enriched,
        "human_label_rows": [{field: row.get(field) for field in HUMAN_LABEL_PACK_FIELDS} for row in enriched],
        "summary": summary,
        "breakdown_rows": breakdown_rows,
        "timeout_rows": timeout_rows,
        "tp_sl_rows": tp_sl_rows,
        "report_markdown": render_markdown_report(summary, breakdown_rows, timeout_rows),
    }


def _numbers(rows: list[dict[str, Any]], field: str) -> list[float]:
    return [float(value) for row in rows if (value := _to_float(row.get(field))) is not None]


def _avg(values: list[float]) -> float | None:
    return round(fmean(values), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(median(values), 4) if values else None


def _tp_sl_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sl = _numbers(rows, "sl_distance_usd")
    tp = _numbers(rows, "tp_distance_usd")
    rr = _numbers(rows, "planned_rr")
    return {
        "average_sl_distance": _avg(sl),
        "median_sl_distance": _median(sl),
        "min_sl_distance": round(min(sl), 4) if sl else None,
        "max_sl_distance": round(max(sl), 4) if sl else None,
        "average_tp_distance": _avg(tp),
        "median_tp_distance": _median(tp),
        "min_tp_distance": round(min(tp), 4) if tp else None,
        "max_tp_distance": round(max(tp), 4) if tp else None,
        "average_planned_rr": _avg(rr),
        "median_planned_rr": _median(rr),
        "min_planned_rr": round(min(rr), 4) if rr else None,
        "max_planned_rr": round(max(rr), 4) if rr else None,
    }


def _mfe_mae_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    mfe = _numbers(rows, "mfe_usd")
    mae = _numbers(rows, "mae_usd")
    mfe_r = _numbers(rows, "mfe_R")
    mae_r = _numbers(rows, "mae_R")
    return {
        "average_mfe_usd": _avg(mfe),
        "median_mfe_usd": _median(mfe),
        "average_mae_usd": _avg(mae),
        "median_mae_usd": _median(mae),
        "average_mfe_R": _avg(mfe_r),
        "median_mfe_R": _median(mfe_r),
        "average_mae_R": _avg(mae_r),
        "median_mae_R": _median(mae_r),
    }


def _reach_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "reached_plus_10": sum(1 for row in rows if row.get("reached_be_plus_10")),
        "reached_plus_15": sum(1 for row in rows if row.get("reached_partial_plus_15")),
        "reached_plus_20": sum(1 for row in rows if row.get("reached_partial_plus_20")),
        "reached_0_5R": sum(1 for row in rows if row.get("reached_0_5R")),
        "reached_1R": sum(1 for row in rows if row.get("reached_1R")),
        "reached_2R": sum(1 for row in rows if row.get("reached_2R")),
        "almost_hit_tp": sum(1 for row in rows if row.get("almost_hit_tp")),
        "almost_hit_sl": sum(1 for row in rows if row.get("almost_hit_sl")),
    }


def _metric_row(rows: list[dict[str, Any]], dimension: str, category: str) -> dict[str, Any]:
    metrics = metric_block_from_r(row["r_multiple"] for row in rows if row.get("r_multiple") is not None)
    return {
        "dimension": dimension,
        "category": category,
        "trades": metrics["trades"],
        "sample_label": sample_size_label(metrics["trades"]),
        "interpretation": sample_size_interpretation(metrics["trades"]),
        "PF": metrics["PF"],
        "WR": metrics["WR"],
        "AvgR": metrics["AvgR"],
        "MedianR": metrics["MedianR"],
        "total_R": metrics["total_R"],
        "MaxDD": metrics["MaxDD"],
    }


def _breakdown_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for field in (
        "outcome",
        "stop_size_bucket",
        "target_size_bucket",
        "rr_bucket",
        "tp_realism_label",
        "sl_realism_label",
        "timeout_root_cause",
        "trade_failure_mode",
        "human_review_priority",
    ):
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get(field) or "NONE")].append(row)
        for category, group in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
            out.append(_metric_row(group, field, category))
    return out


def _timeout_breakdown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timeout_rows = [row for row in rows if row.get("outcome") == "TIMEOUT_CLOSE"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in timeout_rows:
        grouped[str(row.get("timeout_root_cause") or "TIMEOUT_UNKNOWN")].append(row)
    out: list[dict[str, Any]] = []
    for root, group in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        metrics = metric_block_from_r(row["r_multiple"] for row in group if row.get("r_multiple") is not None)
        out.append(
            {
                "timeout_root_cause": root,
                "trades": len(group),
                "sample_label": sample_size_label(len(group)),
                "interpretation": sample_size_interpretation(len(group)),
                "PF": metrics["PF"],
                "WR": metrics["WR"],
                "AvgR": metrics["AvgR"],
                "MedianR": metrics["MedianR"],
                "total_R": metrics["total_R"],
                "MaxDD": metrics["MaxDD"],
                "avg_mfe_R": _avg(_numbers(group, "mfe_R")),
                "avg_mae_R": _avg(_numbers(group, "mae_R")),
                "reached_plus_10": sum(1 for row in group if row.get("reached_be_plus_10")),
                "reached_plus_15": sum(1 for row in group if row.get("reached_partial_plus_15")),
                "reached_plus_20": sum(1 for row in group if row.get("reached_partial_plus_20")),
                "almost_hit_tp": sum(1 for row in group if row.get("almost_hit_tp")),
            }
        )
    return out


def _key_answers(rows: list[dict[str, Any]]) -> dict[str, Any]:
    timeout = [row for row in rows if row.get("outcome") == "TIMEOUT_CLOSE"]
    losers = [row for row in rows if (row.get("r_multiple") is not None and float(row["r_multiple"]) < 0)]
    immediate_losers = [row for row in losers if row.get("reaction_state_3_m5") == "REACTION_DEAD" or row.get("first_m5_close_quality") in {"BAD_CLOSE", "INVALIDATING_CLOSE"}]
    return {
        "losers_immediate_invalidation_count": len(immediate_losers),
        "losers_slow_failure_count": max(0, len(losers) - len(immediate_losers)),
        "timeout_almost_hit_tp_count": sum(1 for row in timeout if row.get("almost_hit_tp")),
        "timeout_never_reached_0_5R_count": sum(1 for row in timeout if not row.get("reached_0_5R")),
        "trades_reached_plus_10_before_failing": sum(1 for row in rows if row.get("reached_be_plus_10") and row.get("outcome") in {"SL", "TIMEOUT_CLOSE"}),
        "trades_reached_plus_15_before_failing": sum(1 for row in rows if row.get("reached_partial_plus_15") and row.get("outcome") in {"SL", "TIMEOUT_CLOSE"}),
        "trades_reached_plus_20_before_failing": sum(1 for row in rows if row.get("reached_partial_plus_20") and row.get("outcome") in {"SL", "TIMEOUT_CLOSE"}),
        "be_partial_supported_by_mfe": sum(1 for row in rows if row.get("reached_be_plus_10")) >= 10,
        "targets_too_ambitious_count": sum(1 for row in rows if row.get("tp_realism_label") == "TP_TOO_FAR"),
        "stops_too_tight_count": sum(1 for row in rows if row.get("sl_realism_label") == "SL_TOO_TIGHT"),
        "human_review_required_count": sum(1 for row in rows if row.get("human_review_required")),
    }


def _table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "_No rows._"
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return "\n".join(lines)


def render_markdown_report(summary: dict[str, Any], breakdown_rows: list[dict[str, Any]], timeout_rows: list[dict[str, Any]]) -> str:
    tp_sl = summary["tp_sl_distribution"]
    reach = summary["reach_counts"]
    mfe_mae = summary["mfe_mae_summary"]
    answers = summary["key_answers"]
    lines = [
        "# Strategy 2 Trade Forensic Replay",
        "",
        "Status: research-only autopsy. No live trading, no Telegram alerts, no broker execution, no strategy changes.",
        "",
        "## Executive Summary",
        "",
        f"- trades analyzed: `{summary['source']['trades_analyzed']}`",
        f"- average / median SL distance: `{tp_sl['average_sl_distance']}` / `{tp_sl['median_sl_distance']}` USD",
        f"- average / median TP distance: `{tp_sl['average_tp_distance']}` / `{tp_sl['median_tp_distance']}` USD",
        f"- average planned R:R: `{tp_sl['average_planned_rr']}`",
        f"- trades reaching +10/+15/+20: `{reach['reached_plus_10']}` / `{reach['reached_plus_15']}` / `{reach['reached_plus_20']}`",
        f"- human review required: `{summary['human_review_required_count']}`",
        "",
        "## Safety Confirmation",
        "",
        "- no live trading",
        "- no Telegram",
        "- no orders",
        "- no broker execution",
        "- no order_send",
        "- no Strategy 2, Strategy 3, or Adelin logic changes",
        "- no optimization and no ML",
        "",
        "## Input Files And Data Availability",
        "",
        "```json",
        json.dumps(summary["source"], indent=2, sort_keys=True, default=str),
        "```",
        "",
        "## TP/SL Distribution",
        "",
        "```json",
        json.dumps(tp_sl, indent=2, sort_keys=True),
        "```",
        "",
        "## Outcome By TP/SL Bucket",
        "",
        _table([row for row in breakdown_rows if row["dimension"] in {"stop_size_bucket", "target_size_bucket", "rr_bucket"}], BREAKDOWN_FIELDS),
        "",
        "## MFE/MAE Distribution",
        "",
        "```json",
        json.dumps(mfe_mae, indent=2, sort_keys=True),
        "```",
        "",
        "## Threshold Reach Counts",
        "",
        "```json",
        json.dumps(reach, indent=2, sort_keys=True),
        "```",
        "",
        "## TIMEOUT_CLOSE Forensic Breakdown",
        "",
        _table(timeout_rows, TIMEOUT_FIELDS),
        "",
        "## TP Realism And SL Realism",
        "",
        "TP realism:",
        "",
        "```json",
        json.dumps(summary["tp_realism_counts"], indent=2, sort_keys=True),
        "```",
        "",
        "SL realism:",
        "",
        "```json",
        json.dumps(summary["sl_realism_counts"], indent=2, sort_keys=True),
        "```",
        "",
        "## Failure-Mode Taxonomy",
        "",
        "```json",
        json.dumps(summary["failure_mode_counts"], indent=2, sort_keys=True),
        "```",
        "",
        "## Trades Requiring Human Review",
        "",
        f"- review required count: `{summary['human_review_required_count']}`",
        "```json",
        json.dumps(summary["human_review_priority_counts"], indent=2, sort_keys=True),
        "```",
        "",
        "## Human Labeling Pack Instructions",
        "",
        "Use `strategy_2_human_label_pack.csv` for manual screenshot review. Fill only the human columns after inspecting before-entry, after-entry, and exit screenshots. Leave blank when unsure.",
        "",
        "## Key Questions Answered",
        "",
        f"1. Average and median SL size: `{tp_sl['average_sl_distance']}` / `{tp_sl['median_sl_distance']}` USD.",
        f"2. Average and median TP size: `{tp_sl['average_tp_distance']}` / `{tp_sl['median_tp_distance']}` USD.",
        f"3. Average planned R:R: `{tp_sl['average_planned_rr']}`.",
        f"4. Losing trades immediate invalidation vs slow failure: `{answers['losers_immediate_invalidation_count']}` / `{answers['losers_slow_failure_count']}`.",
        f"5. TIMEOUT_CLOSE almost-hit TP vs never reached 0.5R: `{answers['timeout_almost_hit_tp_count']}` / `{answers['timeout_never_reached_0_5R_count']}`.",
        f"6. Trades reaching +10/+15/+20 before failing: `{answers['trades_reached_plus_10_before_failing']}` / `{answers['trades_reached_plus_15_before_failing']}` / `{answers['trades_reached_plus_20_before_failing']}`.",
        f"7. BE/partial support from MFE: `{answers['be_partial_supported_by_mfe']}`.",
        f"8. TP targets too ambitious count: `{answers['targets_too_ambitious_count']}`.",
        f"9. Stops too tight count: `{answers['stops_too_tight_count']}`.",
        f"10. Manual review first: high priority rows in `strategy_2_human_label_pack.csv`.",
        "11. Missing data for human-vs-bot: screenshots, human-marked entry/SL/TP zones, protected structure/liquidity levels, and manual rationale.",
        "",
        "## What This Proves",
        "",
        "This report proves only what happened inside this 57-trade historical Strategy 2 sample: planned distances, path movement, timeout behavior, and forensic labels.",
        "",
        "## What This Does Not Prove",
        "",
        "It does not validate Strategy 2, create an edge, optimize parameters, or justify live deployment.",
        "",
        "## Recommended Next Step",
        "",
        "Use the human label pack to manually inspect the highest-priority trades. If the manual review does not reveal a repeatable human-vs-bot execution gap, keep Strategy 2 paused and focus on Strategy 3 paper validation.",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any], output_dir: Path, docs_path: Path | None = None) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "forensics_csv": str(output_dir / "strategy_2_trade_forensics.csv"),
        "forensics_jsonl": str(output_dir / "strategy_2_trade_forensics.jsonl"),
        "summary_json": str(output_dir / "strategy_2_trade_forensics_summary.json"),
        "report_md": str(output_dir / "strategy_2_trade_forensics_report.md"),
        "human_label_pack_csv": str(output_dir / "strategy_2_human_label_pack.csv"),
        "timeout_forensics_csv": str(output_dir / "strategy_2_timeout_forensics.csv"),
        "tp_sl_distribution_csv": str(output_dir / "strategy_2_tp_sl_distribution.csv"),
    }
    _write_csv(Path(paths["forensics_csv"]), report["trade_rows"], FORENSIC_FIELDS)
    _write_jsonl(Path(paths["forensics_jsonl"]), report["trade_rows"])
    Path(paths["summary_json"]).write_text(json.dumps(report["summary"], indent=2, sort_keys=True, default=str), encoding="utf-8")
    Path(paths["report_md"]).write_text(report["report_markdown"], encoding="utf-8")
    _write_csv(Path(paths["human_label_pack_csv"]), report["human_label_rows"], HUMAN_LABEL_PACK_FIELDS)
    _write_csv(Path(paths["timeout_forensics_csv"]), report["timeout_rows"], TIMEOUT_FIELDS)
    _write_csv(Path(paths["tp_sl_distribution_csv"]), report["tp_sl_rows"], BREAKDOWN_FIELDS)
    if docs_path is not None:
        docs_path.parent.mkdir(parents=True, exist_ok=True)
        docs_path.write_text(report["report_markdown"], encoding="utf-8")
        paths["docs_markdown"] = str(docs_path)
    return paths


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True, default=str) + "\n")


__all__ = [
    "BREAKDOWN_FIELDS",
    "FORENSIC_FIELDS",
    "HUMAN_LABEL_PACK_FIELDS",
    "SAFETY",
    "TIMEOUT_FIELDS",
    "build_trade_forensics",
    "calculate_path_metrics",
    "calculate_tp_sl",
    "classify_failure_mode",
    "classify_timeout_root_cause",
    "classify_tp_realism",
    "enrich_trade_forensics",
    "render_markdown_report",
    "write_outputs",
]
