from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable

import pandas as pd

from dazro_trade.analysis.human_trade_management import (
    evaluate_entry_quality,
    evaluate_m5_close_quality,
    evaluate_reaction_state,
    evaluate_retest_quality,
    metric_block_from_r,
)
from dazro_trade.analytics.strategy_2_hourly_session_diagnostics import (
    sample_size_interpretation,
    sample_size_label,
)


OUTPUT_FIELDS = [
    "trade_id",
    "symbol",
    "strategy",
    "direction",
    "signal_timestamp",
    "entry_timestamp",
    "entry_price",
    "stop_loss",
    "take_profit",
    "outcome",
    "r_multiple",
    "session",
    "entry_hour",
    "setup_mode",
    "first_m5_close_quality",
    "first_m5_close_score",
    "first_m5_close_reason_codes",
    "second_m5_close_quality",
    "second_m5_close_score",
    "second_m5_close_reason_codes",
    "third_m5_close_quality",
    "third_m5_close_score",
    "third_m5_close_reason_codes",
    "reaction_state_3_m5",
    "reaction_state_5_m5",
    "reaction_reason_codes_3_m5",
    "reaction_reason_codes_5_m5",
    "mfe_3_m5_usd",
    "mae_3_m5_usd",
    "mfe_3_m5_R",
    "mae_3_m5_R",
    "mfe_5_m5_usd",
    "mae_5_m5_usd",
    "mfe_5_m5_R",
    "mae_5_m5_R",
    "favorable_follow_through_3_m5",
    "favorable_follow_through_5_m5",
    "retest_detected",
    "retest_quality",
    "retest_timestamp",
    "retest_reason_codes",
    "be_hit_then_continuation",
    "entry_quality_label",
    "price_escaped_proxy",
    "late_entry_proxy",
    "target_space_proxy",
    "no_follow_through_proxy",
    "dirty_context_proxy",
    "entry_quality_reason_codes",
    "timeout_root_cause",
    "timeout_reason_codes",
    "timeout_mfe_R",
    "timeout_mae_R",
    "timeout_reached_be_trigger",
    "timeout_reached_partial_trigger",
    "timeout_chop_proxy",
    "timeout_target_too_far_proxy",
    "winner_loser_category",
    "diagnostic_bucket",
    "primary_blocker",
    "secondary_blocker",
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

TIMEOUT_BREAKDOWN_FIELDS = [
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
    "avg_timeout_mfe_R",
    "avg_timeout_mae_R",
    "reached_be_trigger_count",
    "reached_partial_trigger_count",
]

ENTRY_LABELS = {
    "TRADE_NOW",
    "WAIT_RETEST",
    "NO_TRADE_PRICE_ESCAPED",
    "NO_TRADE_DIRTY_SETUP",
    "NO_TRADE_INSUFFICIENT_TARGET_SPACE",
    "NO_TRADE_REACTION_ALREADY_DEAD",
    "NO_TRADE_TOO_CLOSE_TO_OBSTACLE",
    "UNKNOWN_INSUFFICIENT_DATA",
}

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
}


def read_executed_trades(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


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


def _entry_time(row: dict[str, Any]) -> pd.Timestamp | None:
    for field in ("entry_timestamp", "signal_timestamp", "timestamp", "time"):
        ts = _timestamp(row.get(field))
        if ts is not None:
            return ts
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


def slice_m5_after_entry(m5: pd.DataFrame | None, entry_time: Any, *, count: int = 5) -> pd.DataFrame:
    frame = _prepare_frame(m5)
    ts = _timestamp(entry_time)
    if frame.empty or ts is None or "time" not in frame.columns:
        return pd.DataFrame()
    return frame[frame["time"] >= ts].head(count).copy()


def slice_m1_after_entry(m1: pd.DataFrame | None, entry_time: Any, *, minutes: int = 25) -> pd.DataFrame:
    frame = _prepare_frame(m1)
    ts = _timestamp(entry_time)
    if frame.empty or ts is None or "time" not in frame.columns:
        return pd.DataFrame()
    end = ts + pd.Timedelta(minutes=minutes)
    return frame[(frame["time"] >= ts) & (frame["time"] <= end)].copy()


def _previous_m5_candle(m5: pd.DataFrame | None, entry_time: Any) -> dict[str, Any] | None:
    frame = _prepare_frame(m5)
    ts = _timestamp(entry_time)
    if frame.empty or ts is None or "time" not in frame.columns:
        return None
    prev = frame[frame["time"] < ts].tail(1)
    if prev.empty:
        return None
    return prev.iloc[0].to_dict()


def _trade_prices(row: dict[str, Any]) -> dict[str, float | None]:
    entry = _to_float(row.get("entry_price") or row.get("entry"))
    stop = _to_float(row.get("stop_loss") or row.get("stop"))
    take_profit = (
        _to_float(row.get("take_profit"))
        or _to_float(row.get("tp2"))
        or _to_float(row.get("tp1"))
        or _to_float(row.get("original_take_profit"))
    )
    return {"entry": entry, "stop": stop, "take_profit": take_profit}


def _risk(entry: float | None, stop: float | None) -> float | None:
    if entry is None or stop is None:
        return None
    risk = abs(float(entry) - float(stop))
    return risk if risk > 0 else None


def _price_escape_proxy(direction: str, entry: float | None, first_m5: pd.DataFrame, risk: float | None) -> dict[str, Any]:
    if entry is None or first_m5.empty:
        return {"price_escaped_proxy": None, "late_entry_proxy": None, "price_escape_usd": None, "price_escape_R": None}
    open_price = _to_float(first_m5.iloc[0].get("open"))
    if open_price is None:
        return {"price_escaped_proxy": None, "late_entry_proxy": None, "price_escape_usd": None, "price_escape_R": None}
    if direction == "LONG":
        escape_usd = max(0.0, float(entry) - float(open_price))
    else:
        escape_usd = max(0.0, float(open_price) - float(entry))
    escape_r = escape_usd / risk if risk else None
    late = escape_usd >= 10.0 or (escape_r is not None and escape_r >= 0.25)
    return {
        "price_escaped_proxy": late,
        "late_entry_proxy": late,
        "price_escape_usd": round(escape_usd, 4),
        "price_escape_R": round(escape_r, 4) if escape_r is not None else None,
    }


def _target_space_proxy(direction: str, entry: float | None, target: float | None, risk: float | None) -> float | None:
    if entry is None or target is None or risk is None:
        return None
    distance = (float(target) - float(entry)) if direction == "LONG" else (float(entry) - float(target))
    return round(distance / risk, 4)


def _quality_for_index(
    m5_window: pd.DataFrame,
    idx: int,
    direction: str,
    *,
    previous_candle: dict[str, Any] | None,
    entry: float | None,
    stop: float | None,
) -> dict[str, Any]:
    if len(m5_window) <= idx or entry is None:
        return {"quality": None, "score": None, "reason_codes": ["missing_m5_close"]}
    row = m5_window.iloc[idx].to_dict()
    prev = previous_candle if idx == 0 else m5_window.iloc[idx - 1].to_dict()
    return evaluate_m5_close_quality(
        row,
        direction,
        previous_candle=prev,
        entry_price=entry,
        invalidation_level=stop,
    )


def _outcome_group(row: dict[str, Any]) -> str:
    outcome = str(row.get("outcome") or "").upper()
    r = _to_float(row.get("r_multiple"))
    if outcome == "TIMEOUT_CLOSE":
        return "TIMEOUT_CLOSE"
    if outcome == "BE" or r == 0:
        return "BE"
    if r is not None and r > 0:
        return "WINNER"
    if r is not None and r < 0:
        return "LOSER"
    return "UNKNOWN"


def _timeout_cause(row: dict[str, Any], record: dict[str, Any], risk: float | None) -> dict[str, Any]:
    if str(row.get("outcome") or "").upper() != "TIMEOUT_CLOSE":
        return {
            "timeout_root_cause": None,
            "timeout_reason_codes": None,
            "timeout_mfe_R": None,
            "timeout_mae_R": None,
            "timeout_reached_be_trigger": None,
            "timeout_reached_partial_trigger": None,
            "timeout_chop_proxy": None,
            "timeout_target_too_far_proxy": None,
        }
    mfe = _to_float(row.get("mfe"))
    mae = _to_float(row.get("mae"))
    mfe_r = mfe / risk if risk and mfe is not None else None
    mae_r = mae / risk if risk and mae is not None else None
    reached_be = bool(mfe is not None and mfe >= 10.0)
    reached_partial = bool(mfe is not None and mfe >= 15.0)
    reason_codes: list[str] = []
    no_follow = record.get("reaction_state_5_m5") != "REACTION_ALIVE" or bool(record.get("no_follow_through_proxy"))
    chop = bool(
        mfe_r is not None
        and mae_r is not None
        and mfe_r < 1.0
        and mae_r < 1.0
        and record.get("reaction_state_5_m5") == "REACTION_WEAK"
    )
    target_too_far = bool(mfe_r is not None and mfe_r >= 1.0 and record.get("target_space_proxy") and mfe_r < float(record["target_space_proxy"]))
    if no_follow:
        reason_codes.append("no_follow_through")
        root = "TIMEOUT_NO_FOLLOW_THROUGH"
    elif chop:
        reason_codes.append("two_sided_chop_without_target")
        root = "TIMEOUT_CHOP"
    elif target_too_far:
        reason_codes.append("mfe_available_but_target_farther")
        root = "TIMEOUT_TARGET_TOO_FAR"
    else:
        reason_codes.append("timeout_unknown")
        root = "TIMEOUT_UNKNOWN"
    if reached_be:
        reason_codes.append("be_trigger_reached")
    if reached_partial:
        reason_codes.append("partial_trigger_reached")
    return {
        "timeout_root_cause": root,
        "timeout_reason_codes": ";".join(reason_codes),
        "timeout_mfe_R": round(mfe_r, 4) if mfe_r is not None else None,
        "timeout_mae_R": round(mae_r, 4) if mae_r is not None else None,
        "timeout_reached_be_trigger": reached_be,
        "timeout_reached_partial_trigger": reached_partial,
        "timeout_chop_proxy": chop,
        "timeout_target_too_far_proxy": target_too_far,
    }


def classify_entry_quality_label(
    *,
    first_quality: str | None,
    reaction_state_3: str | None,
    target_space_R: float | None,
    price_escaped: bool | None,
    retest_quality: str | None,
    m5_missing: bool = False,
) -> tuple[str, list[str], str, str | None]:
    if m5_missing:
        return "UNKNOWN_INSUFFICIENT_DATA", ["missing_m5_path"], "missing_m5_path", None
    reasons: list[str] = []
    secondary: str | None = None
    if reaction_state_3 == "REACTION_DEAD":
        reasons.append("reaction_dead_within_3_m5")
        if first_quality in {"BAD_CLOSE", "INVALIDATING_CLOSE"}:
            secondary = "bad_first_m5_close"
        return "NO_TRADE_REACTION_ALREADY_DEAD", reasons, "reaction_dead", secondary
    if price_escaped:
        reasons.append("late_entry_price_escaped_proxy")
        return "NO_TRADE_PRICE_ESCAPED", reasons, "price_chased", secondary
    if first_quality in {"BAD_CLOSE", "INVALIDATING_CLOSE"}:
        reasons.append("bad_or_invalidating_first_m5_close")
        return "NO_TRADE_DIRTY_SETUP", reasons, "dirty_m5_context", secondary
    if target_space_R is not None and target_space_R < 1.0:
        reasons.append("target_space_lt_1R")
        return "NO_TRADE_INSUFFICIENT_TARGET_SPACE", reasons, "insufficient_target_space", secondary
    if retest_quality == "RETEST_PENDING":
        reasons.append("retest_pending_wait_for_confirmation")
        return "WAIT_RETEST", reasons, "retest_pending", secondary
    reasons.append("entry_quality_no_blocker_detected")
    return "TRADE_NOW", reasons, "no_primary_blocker", secondary


def _taxonomy(row: dict[str, Any], record: dict[str, Any]) -> str:
    group = record["winner_loser_category"]
    first = record.get("first_m5_close_quality")
    reaction3 = record.get("reaction_state_3_m5")
    reaction5 = record.get("reaction_state_5_m5")
    retest = record.get("retest_quality")
    if group == "WINNER":
        if retest == "HEALTHY_RETEST":
            return "WINNER_AFTER_HEALTHY_RETEST"
        if first in {"GOOD_CLOSE", "ACCEPTABLE_CLOSE"} and reaction3 == "REACTION_ALIVE":
            return "WINNER_CLEAN_FOLLOW_THROUGH"
        if reaction5 in {"REACTION_ALIVE", "REACTION_WEAK"}:
            return "WINNER_SLOW_GRIND"
        return "WINNER_UNKNOWN"
    if group == "LOSER":
        if first == "INVALIDATING_CLOSE" or reaction3 == "REACTION_DEAD":
            return "LOSER_IMMEDIATE_INVALIDATION"
        if record.get("price_escaped_proxy"):
            return "LOSER_PRICE_CHASED"
        if first == "BAD_CLOSE":
            return "LOSER_BAD_M5_CLOSE_IGNORED"
        if retest == "FAILED_RETEST":
            return "LOSER_FAILED_RETEST"
        if record.get("no_follow_through_proxy"):
            return "LOSER_NO_FOLLOW_THROUGH"
        return "LOSER_UNKNOWN"
    if group == "BE":
        if retest == "HEALTHY_RETEST":
            return "BE_AFTER_HEALTHY_RETEST"
        if reaction5 in {"REACTION_WEAK", "REACTION_DEAD"}:
            return "BE_AFTER_WEAK_REACTION"
        return "BE_AFTER_WEAK_REACTION"
    if group == "TIMEOUT_CLOSE":
        return str(record.get("timeout_root_cause") or "TIMEOUT_UNKNOWN")
    return "UNKNOWN"


def enrich_trade_entry_quality(
    row: dict[str, Any],
    *,
    m5: pd.DataFrame | None,
    m1: pd.DataFrame | None = None,
    reaction_window_m5: int = 5,
    row_index: int = 0,
) -> dict[str, Any]:
    prices = _trade_prices(row)
    entry = prices["entry"]
    stop = prices["stop"]
    take_profit = prices["take_profit"]
    risk = _risk(entry, stop)
    direction = _direction(row.get("direction"))
    entry_ts = _entry_time(row)
    m5_window = slice_m5_after_entry(m5, entry_ts, count=max(reaction_window_m5, 5))
    _ = slice_m1_after_entry(m1, entry_ts, minutes=5 * max(reaction_window_m5, 5))
    previous = _previous_m5_candle(m5, entry_ts)

    qualities = [
        _quality_for_index(m5_window, idx, direction, previous_candle=previous, entry=entry, stop=stop)
        for idx in range(3)
    ]
    reaction3 = evaluate_reaction_state(m5_window.head(3), direction, entry or 0.0, stop_loss=stop, lookahead_candles=3)
    reaction5 = evaluate_reaction_state(m5_window.head(5), direction, entry or 0.0, stop_loss=stop, lookahead_candles=5)
    retest = evaluate_retest_quality(m5_window, direction, entry or 0.0, stop_loss=stop, be_trigger_usd=10.0)
    escape = _price_escape_proxy(direction, entry, m5_window.head(1), risk)
    target_space = _target_space_proxy(direction, entry, take_profit, risk)
    no_follow = bool(reaction3.get("reaction_state") != "REACTION_ALIVE" and (reaction3.get("mfe_R") is None or float(reaction3.get("mfe_R") or 0.0) < 0.35))
    dirty = bool(qualities[0].get("quality") in {"BAD_CLOSE", "INVALIDATING_CLOSE"} or reaction3.get("reaction_state") == "REACTION_DEAD")
    entry_label, entry_reasons, primary, secondary = classify_entry_quality_label(
        first_quality=qualities[0].get("quality"),
        reaction_state_3=reaction3.get("reaction_state"),
        target_space_R=target_space,
        price_escaped=escape.get("price_escaped_proxy"),
        retest_quality=retest.get("retest_quality"),
        m5_missing=m5_window.empty,
    )
    base = {
        "trade_id": str(row.get("trade_id") or row.get("id") or row_index),
        "symbol": row.get("symbol"),
        "strategy": row.get("strategy") or row.get("strategy_name"),
        "direction": direction,
        "signal_timestamp": _timestamp_text(row.get("signal_timestamp") or row.get("timestamp")),
        "entry_timestamp": _timestamp_text(row.get("entry_timestamp") or row.get("timestamp")),
        "entry_price": entry,
        "stop_loss": stop,
        "take_profit": take_profit,
        "outcome": row.get("outcome"),
        "r_multiple": _to_float(row.get("r_multiple")),
        "session": row.get("session"),
        "entry_hour": entry_ts.hour if entry_ts is not None else None,
        "setup_mode": row.get("setup_mode"),
        "reaction_state_3_m5": reaction3.get("reaction_state"),
        "reaction_state_5_m5": reaction5.get("reaction_state"),
        "reaction_reason_codes_3_m5": ";".join(str(code) for code in reaction3.get("reason_codes", [])),
        "reaction_reason_codes_5_m5": ";".join(str(code) for code in reaction5.get("reason_codes", [])),
        "mfe_3_m5_usd": reaction3.get("mfe_usd"),
        "mae_3_m5_usd": reaction3.get("mae_usd"),
        "mfe_3_m5_R": reaction3.get("mfe_R"),
        "mae_3_m5_R": reaction3.get("mae_R"),
        "mfe_5_m5_usd": reaction5.get("mfe_usd"),
        "mae_5_m5_usd": reaction5.get("mae_usd"),
        "mfe_5_m5_R": reaction5.get("mfe_R"),
        "mae_5_m5_R": reaction5.get("mae_R"),
        "favorable_follow_through_3_m5": reaction3.get("reaction_state") == "REACTION_ALIVE",
        "favorable_follow_through_5_m5": reaction5.get("reaction_state") == "REACTION_ALIVE",
        "retest_detected": bool(retest.get("retest_detected", False)),
        "retest_quality": retest.get("retest_quality"),
        "retest_timestamp": retest.get("retest_timestamp"),
        "retest_reason_codes": ";".join(str(code) for code in retest.get("reason_codes", [])),
        "be_hit_then_continuation": "be_hit_then_continuation" in set(retest.get("reason_codes", [])),
        "entry_quality_label": entry_label,
        "price_escaped_proxy": escape.get("price_escaped_proxy"),
        "late_entry_proxy": escape.get("late_entry_proxy"),
        "target_space_proxy": target_space,
        "no_follow_through_proxy": no_follow,
        "dirty_context_proxy": dirty,
        "entry_quality_reason_codes": ";".join(entry_reasons),
        "winner_loser_category": _outcome_group(row),
        "primary_blocker": primary,
        "secondary_blocker": secondary,
    }
    for idx, prefix in enumerate(("first", "second", "third")):
        base[f"{prefix}_m5_close_quality"] = qualities[idx].get("quality")
        base[f"{prefix}_m5_close_score"] = qualities[idx].get("score")
        base[f"{prefix}_m5_close_reason_codes"] = ";".join(str(code) for code in qualities[idx].get("reason_codes", []))
    base.update(_timeout_cause(row, base, risk))
    base["diagnostic_bucket"] = "|".join(
        str(part)
        for part in (
            base.get("entry_quality_label"),
            base.get("reaction_state_3_m5"),
            base.get("first_m5_close_quality"),
        )
        if part
    )
    taxonomy = _taxonomy(row, base)
    base["diagnostic_bucket"] = taxonomy
    if base["winner_loser_category"] in {"WINNER", "LOSER", "BE", "TIMEOUT_CLOSE"}:
        base["primary_blocker"] = base["primary_blocker"] if base["winner_loser_category"] == "WINNER" else _primary_from_taxonomy(taxonomy, base)
    base["winner_loser_category"] = taxonomy
    return {field: base.get(field) for field in OUTPUT_FIELDS}


def _primary_from_taxonomy(taxonomy: str, record: dict[str, Any]) -> str:
    if "PRICE_CHASED" in taxonomy:
        return "price_chased"
    if "BAD_M5" in taxonomy or "INVALIDATION" in taxonomy:
        return "bad_m5_or_invalidation"
    if "NO_FOLLOW" in taxonomy:
        return "no_follow_through"
    if "FAILED_RETEST" in taxonomy:
        return "failed_retest"
    if "CHOP" in taxonomy:
        return "timeout_chop"
    if "TARGET_TOO_FAR" in taxonomy:
        return "target_too_far"
    if "TIMEOUT" in taxonomy:
        return "timeout_unknown"
    return str(record.get("primary_blocker") or "none")


def _metric_rows(rows: list[dict[str, Any]], dimension: str, field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(field) or "UNKNOWN")].append(row)
    out: list[dict[str, Any]] = []
    for category, group in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        values = [float(row["r_multiple"]) for row in group if row.get("r_multiple") is not None]
        metrics = metric_block_from_r(values)
        out.append(
            {
                "dimension": dimension,
                "category": category,
                "trades": metrics["trades"],
                "sample_label": sample_size_label(metrics["trades"]),
                "interpretation": sample_size_interpretation_for_report(metrics["trades"]),
                "PF": metrics["PF"],
                "WR": metrics["WR"],
                "AvgR": metrics["AvgR"],
                "MedianR": metrics["MedianR"],
                "total_R": metrics["total_R"],
                "MaxDD": metrics["MaxDD"],
            }
        )
    return out


def sample_size_interpretation_for_report(n: int) -> str:
    if n < 10:
        return "no conclusion"
    if n < 30:
        return "observation only"
    if n < 100:
        return "interpretable but not validated"
    return "stronger but still not live validation"


def _distribution(rows: list[dict[str, Any]], by: str, value: str) -> dict[str, dict[str, int]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        grouped[str(row.get(by) or "UNKNOWN")][str(row.get(value) or "UNKNOWN")] += 1
    return {key: dict(counter) for key, counter in sorted(grouped.items())}


def _timeout_breakdown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timeout_rows = [row for row in rows if row.get("outcome") == "TIMEOUT_CLOSE"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in timeout_rows:
        grouped[str(row.get("timeout_root_cause") or "TIMEOUT_UNKNOWN")].append(row)
    out: list[dict[str, Any]] = []
    for root, group in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        values = [float(row["r_multiple"]) for row in group if row.get("r_multiple") is not None]
        metrics = metric_block_from_r(values)
        mfe_vals = [float(row["timeout_mfe_R"]) for row in group if row.get("timeout_mfe_R") is not None]
        mae_vals = [float(row["timeout_mae_R"]) for row in group if row.get("timeout_mae_R") is not None]
        out.append(
            {
                "timeout_root_cause": root,
                "trades": len(group),
                "sample_label": sample_size_label(len(group)),
                "interpretation": sample_size_interpretation_for_report(len(group)),
                "PF": metrics["PF"],
                "WR": metrics["WR"],
                "AvgR": metrics["AvgR"],
                "MedianR": metrics["MedianR"],
                "total_R": metrics["total_R"],
                "MaxDD": metrics["MaxDD"],
                "avg_timeout_mfe_R": round(fmean(mfe_vals), 4) if mfe_vals else None,
                "avg_timeout_mae_R": round(fmean(mae_vals), 4) if mae_vals else None,
                "reached_be_trigger_count": sum(1 for row in group if row.get("timeout_reached_be_trigger")),
                "reached_partial_trigger_count": sum(1 for row in group if row.get("timeout_reached_partial_trigger")),
            }
        )
    return out


def _best_worst_buckets(breakdown_rows: list[dict[str, Any]], dimension: str = "diagnostic_bucket") -> dict[str, Any]:
    candidates = [row for row in breakdown_rows if row["dimension"] == dimension and row["trades"]]
    ranked = sorted(candidates, key=lambda row: ((row["AvgR"] if row["AvgR"] is not None else -999.0), _pf_sort(row["PF"])), reverse=True)
    return {
        "best_by_avgR": ranked[:5],
        "worst_by_avgR": list(reversed(ranked[-5:])),
    }


def _pf_sort(value: Any) -> float:
    if value == "inf":
        return 999.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return -999.0


def _decision(rows: list[dict[str, Any]], breakdown_rows: list[dict[str, Any]], path: dict[str, Any]) -> dict[str, Any]:
    verdict_flags = ["STRATEGY_2_REMAINS_RESEARCH_ONLY", "NO_LIVE_DEPLOYMENT_DECISION"]
    if not rows:
        return {
            "decision": "INSUFFICIENT_DATA_FOR_DECISION",
            "next_step": "data/report repair before more Strategy 2 research",
            "verdict_flags": ["INSUFFICIENT_DATA_FOR_DECISION", *verdict_flags],
            "reason_codes": ["no_rows"],
        }
    if path.get("missing_m5_rows", 0) > len(rows) * 0.2:
        return {
            "decision": "INSUFFICIENT_DATA_FOR_DECISION",
            "next_step": "data/report repair before more Strategy 2 research",
            "verdict_flags": ["INSUFFICIENT_DATA_FOR_DECISION", *verdict_flags],
            "reason_codes": ["m5_path_missing_for_many_trades"],
        }
    baseline = metric_block_from_r(float(row["r_multiple"]) for row in rows if row.get("r_multiple") is not None)
    candidate_dimensions = {
        "first_m5_close_quality",
        "reaction_state_3_m5",
        "reaction_state_5_m5",
        "retest_quality",
        "entry_quality_label",
        "diagnostic_bucket",
    }
    bucket_rows = [row for row in breakdown_rows if row["dimension"] in candidate_dimensions]
    good_candidates = [
        row
        for row in bucket_rows
        if row["trades"] >= 10
        and row["AvgR"] is not None
        and float(row["AvgR"]) > float(baseline["AvgR"] or 0.0) + 0.10
        and _pf_sort(row["PF"]) > _pf_sort(baseline["PF"]) + 0.20
        and _is_logical_good_subset(row)
    ]
    if good_candidates:
        best = sorted(good_candidates, key=lambda row: (float(row["AvgR"]), _pf_sort(row["PF"])), reverse=True)[0]
        return {
            "decision": "CLEAR_GOOD_ENTRY_SUBSET_FOUND",
            "next_step": "feat/strategy-2-entry-filter-research",
            "verdict_flags": ["CLEAR_GOOD_ENTRY_SUBSET_FOUND", *verdict_flags],
            "reason_codes": [f"best_bucket={best['category']}", f"sample_label={best['sample_label']}"],
            "best_candidate": best,
        }
    unknown_rate = sum(1 for row in rows if row.get("entry_quality_label") == "UNKNOWN_INSUFFICIENT_DATA") / len(rows)
    if unknown_rate > 0.30:
        return {
            "decision": "MANAGEMENT_CONTEXT_REQUIRED",
            "next_step": "feat/strategy-2-enrich-management-context",
            "verdict_flags": ["MANAGEMENT_CONTEXT_REQUIRED", *verdict_flags],
            "reason_codes": ["entry_context_unknown_rate_gt_30pct"],
        }
    return {
        "decision": "ENTRY_LOGIC_UNIFORMLY_WEAK",
        "next_step": "pause/archive Strategy 2 and focus on Strategy 3 paper validation",
        "verdict_flags": ["ENTRY_LOGIC_UNIFORMLY_WEAK", *verdict_flags],
        "reason_codes": ["no_materially_better_logical_bucket_with_n_ge_10"],
    }


def _is_logical_good_subset(row: dict[str, Any]) -> bool:
    dimension = row.get("dimension")
    category = row.get("category")
    if dimension in {"reaction_state_3_m5", "reaction_state_5_m5"}:
        return category == "REACTION_ALIVE"
    if dimension == "first_m5_close_quality":
        return category in {"GOOD_CLOSE", "ACCEPTABLE_CLOSE"}
    if dimension == "retest_quality":
        return category == "HEALTHY_RETEST"
    if dimension == "entry_quality_label":
        return category == "TRADE_NOW"
    if dimension == "diagnostic_bucket":
        return str(category).startswith("WINNER_")
    return False


def build_entry_quality_diagnostic(
    trade_rows: Iterable[dict[str, Any]],
    *,
    market_data: dict[str, pd.DataFrame],
    source_path: str,
    symbol: str = "XAUUSD",
    reaction_window_m5: int = 5,
) -> dict[str, Any]:
    trade_rows = list(trade_rows)
    m5 = market_data.get("M5")
    m1 = market_data.get("M1")
    enriched = [
        enrich_trade_entry_quality(row, m5=m5, m1=m1, reaction_window_m5=reaction_window_m5, row_index=idx)
        for idx, row in enumerate(trade_rows)
    ]
    breakdown_rows: list[dict[str, Any]] = []
    for dimension, field in (
        ("outcome_group", "winner_loser_category"),
        ("first_m5_close_quality", "first_m5_close_quality"),
        ("reaction_state_3_m5", "reaction_state_3_m5"),
        ("reaction_state_5_m5", "reaction_state_5_m5"),
        ("retest_quality", "retest_quality"),
        ("entry_quality_label", "entry_quality_label"),
        ("diagnostic_bucket", "diagnostic_bucket"),
        ("primary_blocker", "primary_blocker"),
    ):
        breakdown_rows.extend(_metric_rows(enriched, dimension, field))
    timeout_rows = _timeout_breakdown(enriched)
    path_availability = {
        "m1_loaded": bool(m1 is not None and not m1.empty),
        "m5_loaded": bool(m5 is not None and not m5.empty),
        "missing_m5_rows": sum(1 for row in enriched if row.get("first_m5_close_quality") is None),
        "missing_m1_rows": 0 if m1 is not None and not m1.empty else len(enriched),
    }
    summary = {
        "research_only": True,
        "safety": SAFETY,
        "source": {
            "symbol": symbol,
            "trades_path": source_path,
            "trades_analyzed": len(enriched),
            "reaction_window_m5": reaction_window_m5,
            "path_availability": path_availability,
        },
        "baseline": metric_block_from_r(float(row["r_multiple"]) for row in enriched if row.get("r_multiple") is not None),
        "m5_close_quality_by_outcome": {
            "first": _distribution(enriched, "outcome", "first_m5_close_quality"),
            "second": _distribution(enriched, "outcome", "second_m5_close_quality"),
            "third": _distribution(enriched, "outcome", "third_m5_close_quality"),
        },
        "reaction_state_by_outcome": {
            "reaction_3_m5": _distribution(enriched, "outcome", "reaction_state_3_m5"),
            "reaction_5_m5": _distribution(enriched, "outcome", "reaction_state_5_m5"),
        },
        "retest_quality_by_outcome": _distribution(enriched, "outcome", "retest_quality"),
        "entry_quality_label_counts": dict(Counter(str(row.get("entry_quality_label") or "UNKNOWN") for row in enriched)),
        "winner_loser_category_counts": dict(Counter(str(row.get("winner_loser_category") or "UNKNOWN") for row in enriched)),
        "timeout_root_cause_counts": dict(Counter(str(row.get("timeout_root_cause") or "NOT_TIMEOUT") for row in enriched if row.get("outcome") == "TIMEOUT_CLOSE")),
        "best_worst_diagnostic_buckets": _best_worst_buckets(breakdown_rows),
    }
    decision = _decision(enriched, breakdown_rows, path_availability)
    summary["decision_matrix"] = decision
    report = render_markdown_report(summary, breakdown_rows, timeout_rows)
    return {
        "trade_rows": enriched,
        "summary": summary,
        "breakdown_rows": breakdown_rows,
        "timeout_breakdown_rows": timeout_rows,
        "report_markdown": report,
    }


def _table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "_No rows._"
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return "\n".join(lines)


def _distribution_table(title: str, data: dict[str, dict[str, int]]) -> list[str]:
    rows = []
    for outcome, counts in data.items():
        rows.append({"outcome": outcome, "distribution": json.dumps(counts, sort_keys=True)})
    return [f"### {title}", "", _table(rows, ["outcome", "distribution"]), ""]


def render_markdown_report(summary: dict[str, Any], breakdown_rows: list[dict[str, Any]], timeout_rows: list[dict[str, Any]]) -> str:
    decision = summary["decision_matrix"]
    baseline = summary["baseline"]
    path = summary["source"]["path_availability"]
    bucket_rank = summary["best_worst_diagnostic_buckets"]
    lines = [
        "# Strategy 2 Entry Quality Diagnostics",
        "",
        "Status: research-only diagnostic. No live trading, no Telegram alerts, no broker execution, no strategy-entry changes.",
        "",
        "## Executive Summary",
        "",
        f"- trades analyzed: `{summary['source']['trades_analyzed']}`",
        f"- baseline PF / AvgR / total_R: `{baseline['PF']}` / `{baseline['AvgR']}` / `{baseline['total_R']}`",
        f"- decision matrix result: `{decision['decision']}`",
        f"- next step: `{decision['next_step']}`",
        f"- verdict flags: `{', '.join(decision['verdict_flags'])}`",
        f"- best candidate subset: `{_format_best_candidate(decision.get('best_candidate'))}`",
        "",
        "## Input Data And Safety",
        "",
        f"- trades path: `{summary['source']['trades_path']}`",
        f"- M1 loaded: `{str(path['m1_loaded']).lower()}`",
        f"- M5 loaded: `{str(path['m5_loaded']).lower()}`",
        f"- missing M5 rows: `{path['missing_m5_rows']}`",
        f"- live/order/Telegram enabled: `false`",
        "",
        "## Baseline Recap",
        "",
        _table(
            [
                {
                    "trades": baseline["trades"],
                    "sample_label": sample_size_label(baseline["trades"]),
                    "PF": baseline["PF"],
                    "WR": baseline["WR"],
                    "AvgR": baseline["AvgR"],
                    "MedianR": baseline["MedianR"],
                    "total_R": baseline["total_R"],
                    "MaxDD": baseline["MaxDD"],
                }
            ],
            ["trades", "sample_label", "PF", "WR", "AvgR", "MedianR", "total_R", "MaxDD"],
        ),
        "",
        "## M5 Close Quality Distribution",
        "",
    ]
    lines.extend(_distribution_table("First M5 Close By Outcome", summary["m5_close_quality_by_outcome"]["first"]))
    lines.extend(_distribution_table("Second M5 Close By Outcome", summary["m5_close_quality_by_outcome"]["second"]))
    lines.extend(_distribution_table("Third M5 Close By Outcome", summary["m5_close_quality_by_outcome"]["third"]))
    lines.extend(["## Reaction State Distribution", ""])
    lines.extend(_distribution_table("Reaction After 3 M5 Candles", summary["reaction_state_by_outcome"]["reaction_3_m5"]))
    lines.extend(_distribution_table("Reaction After 5 M5 Candles", summary["reaction_state_by_outcome"]["reaction_5_m5"]))
    lines.extend(["## Retest Distribution", ""])
    lines.extend(_distribution_table("Retest Quality By Outcome", summary["retest_quality_by_outcome"]))
    lines.extend(
        [
            "## Entry-Quality Labels",
            "",
            "```json",
            json.dumps(summary["entry_quality_label_counts"], indent=2, sort_keys=True),
            "```",
            "",
            "## Timeout Root-Cause Diagnostics",
            "",
            _table(timeout_rows, TIMEOUT_BREAKDOWN_FIELDS),
            "",
            "## Winner / Loser Taxonomy",
            "",
            "```json",
            json.dumps(summary["winner_loser_category_counts"], indent=2, sort_keys=True),
            "```",
            "",
            "## Diagnostic Buckets Ranked By AvgR",
            "",
            "Best buckets:",
            "",
            _table(bucket_rank["best_by_avgR"], BREAKDOWN_FIELDS),
            "",
            "Worst buckets:",
            "",
            _table(bucket_rank["worst_by_avgR"], BREAKDOWN_FIELDS),
            "",
            "## Statistical Caveats",
            "",
            "- Buckets with `n < 10` are insufficient and must not be interpreted.",
            "- Buckets with `10 <= n < 30` are weak observations only.",
            "- Buckets with `n >= 30` are interpretable but not validated.",
            "- Nothing in this report is live-ready or validated.",
            "",
            "## Decision Matrix Result",
            "",
            f"- result: `{decision['decision']}`",
            f"- reason codes: `{', '.join(decision.get('reason_codes', []))}`",
            f"- recommended next step: `{decision['next_step']}`",
            "",
            "## Recommended Next Step",
            "",
            decision["next_step"],
        ]
    )
    return "\n".join(lines) + "\n"


def _format_best_candidate(candidate: Any) -> str:
    if not isinstance(candidate, dict):
        return "none"
    return (
        f"{candidate.get('dimension')}={candidate.get('category')} "
        f"n={candidate.get('trades')} label={candidate.get('sample_label')} "
        f"PF={candidate.get('PF')} AvgR={candidate.get('AvgR')}"
    )


def write_outputs(report: dict[str, Any], output_dir: Path, docs_path: Path | None = None) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "trades_csv": str(output_dir / "strategy_2_entry_quality_trades.csv"),
        "trades_jsonl": str(output_dir / "strategy_2_entry_quality_trades.jsonl"),
        "summary_json": str(output_dir / "strategy_2_entry_quality_summary.json"),
        "report_md": str(output_dir / "strategy_2_entry_quality_report.md"),
        "breakdown_csv": str(output_dir / "strategy_2_entry_quality_breakdown.csv"),
        "timeout_breakdown_csv": str(output_dir / "strategy_2_timeout_quality_breakdown.csv"),
    }
    _write_csv(Path(paths["trades_csv"]), report["trade_rows"], OUTPUT_FIELDS)
    _write_jsonl(Path(paths["trades_jsonl"]), report["trade_rows"])
    Path(paths["summary_json"]).write_text(json.dumps(report["summary"], indent=2, sort_keys=True, default=str), encoding="utf-8")
    Path(paths["report_md"]).write_text(report["report_markdown"], encoding="utf-8")
    _write_csv(Path(paths["breakdown_csv"]), report["breakdown_rows"], BREAKDOWN_FIELDS)
    _write_csv(Path(paths["timeout_breakdown_csv"]), report["timeout_breakdown_rows"], TIMEOUT_BREAKDOWN_FIELDS)
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
    "ENTRY_LABELS",
    "OUTPUT_FIELDS",
    "SAFETY",
    "TIMEOUT_BREAKDOWN_FIELDS",
    "build_entry_quality_diagnostic",
    "classify_entry_quality_label",
    "enrich_trade_entry_quality",
    "read_executed_trades",
    "render_markdown_report",
    "sample_size_interpretation_for_report",
    "slice_m1_after_entry",
    "slice_m5_after_entry",
    "write_outputs",
]
