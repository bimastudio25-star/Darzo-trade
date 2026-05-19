from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable, Literal

import pandas as pd

from dazro_trade.analysis.strategy_2_liquidity_expansion_stats import (
    LiquidityExpansionStatsProfile,
    adaptive_tp1_distance,
    expansion_quartiles,
    find_h1_reference_for_time,
    find_m15_0045_for_h1,
    max_excursion_plus_25,
    normalize_ohlc,
    validate_liquidity_sequence,
)


SPEC_AUDIT_FIELDS = [
    "trade_id",
    "direction",
    "entry_timestamp",
    "entry_price",
    "stop_loss",
    "take_profit",
    "outcome",
    "r_multiple",
    "h1_reference_timestamp",
    "h1_reference_type",
    "h1_high",
    "h1_low",
    "h1_liquidity_level",
    "h1_liquidity_side",
    "h1_liquidity_taken",
    "h1_liquidity_taken_timestamp",
    "m15_0045_timestamp",
    "m15_0045_high",
    "m15_0045_low",
    "m15_opposite_level_taken_before_h1",
    "liquidity_sequence_valid",
    "liquidity_sequence_reason_codes",
    "entry_distance_from_h1_level_usd",
    "historical_average_mae_used",
    "historical_max_excursion_used",
    "entry_near_average_mae",
    "mae_alignment_label",
    "sl_distance_from_entry_usd",
    "sl_distance_from_h1_level_usd",
    "expected_sl_distance_from_h1_level_usd",
    "expected_sl_price",
    "sl_matches_max_excursion_plus_25",
    "sl_exceeds_12_usd",
    "sl_sanity_label",
    "current_tp_distance_from_entry_usd",
    "current_tp_distance_from_h1_level_usd",
    "expected_tp1_price",
    "expected_tp2_price",
    "expected_tp3_price",
    "expected_tp4_price",
    "current_tp_anchored_to_h1_level",
    "current_tp_appears_entry_anchored",
    "tp_alignment_label",
    "current_planned_rr",
    "expected_rr_to_tp1",
    "expected_rr_to_tp2",
    "expected_rr_to_tp3",
    "expected_rr_to_tp4",
    "spec_alignment_score",
    "spec_alignment_label",
    "spec_deviation_reason_codes",
]

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


def _direction(value: Any) -> Literal["LONG", "SHORT"] | None:
    text = str(value or "").strip().upper()
    if text in {"BUY", "LONG"}:
        return "LONG"
    if text in {"SELL", "SHORT"}:
        return "SHORT"
    return None


def _trade_id(row: dict[str, Any], index: int) -> str:
    return str(row.get("trade_id") or row.get("id") or f"strategy2_trade_{index + 1:03d}")


def _get_price(row: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = _to_float(row.get(name))
        if value is not None:
            return value
    return None


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(float(value), digits) if value is not None else None


def _mean(values: Iterable[float | None]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(fmean(vals), 4) if vals else None


def _median(values: Iterable[float | None]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(median(vals), 4) if vals else None


def _min(values: Iterable[float | None]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(min(vals), 4) if vals else None


def _max(values: Iterable[float | None]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(max(vals), 4) if vals else None


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def _h1_level_for_direction(direction: Literal["LONG", "SHORT"], h1_ref: dict[str, Any]) -> tuple[float | None, str | None]:
    if direction == "LONG":
        return _to_float(h1_ref.get("h1_low")), "LOW"
    return _to_float(h1_ref.get("h1_high")), "HIGH"


def _entry_deviation(direction: Literal["LONG", "SHORT"], entry: float, h1_level: float) -> float:
    if direction == "LONG":
        return round(max(0.0, h1_level - entry), 4)
    return round(max(0.0, entry - h1_level), 4)


def _distance_from_level(direction: Literal["LONG", "SHORT"], price: float, h1_level: float) -> float:
    if direction == "LONG":
        return round(price - h1_level, 4)
    return round(h1_level - price, 4)


def _expected_price_from_level(direction: Literal["LONG", "SHORT"], h1_level: float, distance: float) -> float:
    if direction == "LONG":
        return round(h1_level + distance, 4)
    return round(h1_level - distance, 4)


def _expected_stop(direction: Literal["LONG", "SHORT"], h1_level: float, distance: float) -> float:
    if direction == "LONG":
        return round(h1_level - distance, 4)
    return round(h1_level + distance, 4)


def _matches_any_distance(actual_distance: float | None, expected_distances: Iterable[float], tolerance: float) -> bool:
    if actual_distance is None:
        return False
    return any(abs(float(actual_distance) - float(expected)) <= tolerance for expected in expected_distances)


def _safe_rr(target_price: float | None, entry: float | None, stop: float | None) -> float | None:
    if target_price is None or entry is None or stop is None:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    return round(abs(target_price - entry) / risk, 4)


def _profile_from_summary(summary: dict[str, Any]) -> LiquidityExpansionStatsProfile:
    profile = summary.get("profile", summary)
    return LiquidityExpansionStatsProfile(
        average_mae=float(profile.get("average_mae", 0.0) or 0.0),
        median_mae=float(profile.get("median_mae", 0.0) or 0.0),
        p75_mae=float(profile.get("p75_mae", 0.0) or 0.0),
        p90_mae=float(profile.get("p90_mae", 0.0) or 0.0),
        max_excursion=float(profile.get("max_excursion", 0.0) or 0.0),
        average_expansion=float(profile.get("average_expansion", 0.0) or 0.0),
        median_expansion=float(profile.get("median_expansion", 0.0) or 0.0),
        max_expansion=float(profile.get("max_expansion", 0.0) or 0.0),
        tp_quartile_distance=float(profile.get("tp_quartile_distance", 0.0) or 0.0),
        suggested_sl_distance=float(profile.get("suggested_sl_distance", 0.0) or 0.0),
        effective_risk_from_mae_entry=float(profile.get("effective_risk_from_mae_entry", 0.0) or 0.0),
        effective_risk_gt_12=bool(profile.get("effective_risk_gt_12", False)),
        samples=int(profile.get("samples", 0) or 0),
        calibration_from=profile.get("calibration_from"),
        calibration_to=profile.get("calibration_to"),
    )


def load_stats_profile(path: Path | None) -> LiquidityExpansionStatsProfile | None:
    if path is None or not path.exists():
        return None
    return _profile_from_summary(json.loads(path.read_text(encoding="utf-8")))


def audit_trade_against_spec(
    row: dict[str, Any],
    *,
    index: int,
    m1: pd.DataFrame,
    m15: pd.DataFrame,
    h1: pd.DataFrame,
    profile: LiquidityExpansionStatsProfile | None,
) -> dict[str, Any]:
    direction = _direction(row.get("direction"))
    entry_ts = _timestamp(row.get("timestamp") or row.get("entry_timestamp") or row.get("signal_timestamp"))
    exit_ts = _timestamp(row.get("exit_time") or row.get("exit_timestamp"))
    entry = _get_price(row, "entry", "entry_price")
    stop = _get_price(row, "stop", "stop_loss")
    take_profit = _get_price(row, "take_profit", "tp2", "tp1", "tp")
    r_multiple = _to_float(row.get("r_multiple"))
    reasons: list[str] = []

    out: dict[str, Any] = {
        "trade_id": _trade_id(row, index),
        "direction": direction,
        "entry_timestamp": _timestamp_text(entry_ts),
        "entry_price": entry,
        "stop_loss": stop,
        "take_profit": take_profit,
        "outcome": row.get("outcome"),
        "r_multiple": r_multiple,
    }
    if direction is None or entry_ts is None or entry is None or stop is None or take_profit is None:
        reasons.append("required_trade_fields_missing")
        out.update(_unknown_alignment(reasons))
        return out

    h1_ref = find_h1_reference_for_time(h1, entry_ts)
    if not h1_ref:
        reasons.append("h1_reference_missing")
        out.update(_unknown_alignment(reasons))
        return out

    h1_level, side = _h1_level_for_direction(direction, h1_ref)
    if h1_level is None or side is None:
        reasons.append("h1_liquidity_level_missing")
        out.update(_unknown_alignment(reasons))
        return out

    h1_start = h1_ref.get("current_h1_timestamp")
    m15_ref = find_m15_0045_for_h1(m15, h1_ref.get("h1_reference_timestamp")) or {}
    if not m15_ref:
        reasons.append("m15_0045_missing")
    m15_opposite = _to_float(m15_ref.get("m15_0045_high" if direction == "LONG" else "m15_0045_low"))
    sequence = {
        "h1_liquidity_taken": False,
        "h1_liquidity_taken_timestamp": None,
        "m15_opposite_level_taken_before_h1": None,
        "liquidity_sequence_valid": False,
        "liquidity_sequence_reason_codes": ["m15_0045_missing"],
    }
    if m15_opposite is not None and h1_start is not None:
        sequence = validate_liquidity_sequence(
            m1,
            direction=direction,
            h1_start=h1_start,
            h1_level=h1_level,
            m15_opposite_level=m15_opposite,
            end=exit_ts or entry_ts + pd.Timedelta(hours=1),
        )
        if not sequence.get("liquidity_sequence_valid"):
            reasons.extend(str(v) for v in sequence.get("liquidity_sequence_reason_codes") or [])

    avg_mae = profile.average_mae if profile is not None else 0.0
    max_exc = profile.max_excursion if profile is not None else 0.0
    max_expansion = profile.max_expansion if profile is not None else 0.0
    avg_expansion = profile.average_expansion if profile is not None else 0.0
    if profile is None or profile.samples <= 0:
        reasons.append("historical_stats_profile_missing")

    entry_deviation = _entry_deviation(direction, entry, h1_level)
    mae_tolerance = max(0.25, avg_mae * 0.25) if avg_mae > 0 else 0.0
    entry_near_mae = bool(avg_mae > 0 and abs(entry_deviation - avg_mae) <= mae_tolerance)
    if avg_mae <= 0:
        mae_label = "UNKNOWN_INSUFFICIENT_DATA"
    elif entry_near_mae:
        mae_label = "MAE_ALIGNED"
    elif entry_deviation <= max(0.25, avg_mae * 0.25):
        mae_label = "ENTRY_TOO_CLOSE_TO_H1_LEVEL"
        reasons.append("entry_not_at_average_mae_deviation")
    else:
        mae_label = "ENTRY_NOT_NEAR_AVERAGE_MAE"
        reasons.append("entry_not_near_average_mae")

    expected_sl_distance = max_excursion_plus_25(max_exc) if max_exc > 0 else None
    expected_sl_price = _expected_stop(direction, h1_level, expected_sl_distance) if expected_sl_distance is not None else None
    sl_distance_from_entry = abs(entry - stop)
    sl_distance_from_h1 = abs(stop - h1_level)
    sl_tolerance = max(0.25, (expected_sl_distance or 0) * 0.05)
    sl_matches = bool(expected_sl_distance is not None and abs(sl_distance_from_h1 - expected_sl_distance) <= sl_tolerance)
    sl_exceeds_12 = sl_distance_from_entry > 12.0
    sl_label = "SL_ALIGNED" if sl_matches else "SL_NOT_MAX_EXCURSION_PLUS_25"
    if sl_exceeds_12:
        reasons.append("sl_exceeds_12_usd")
    if not sl_matches:
        reasons.append("sl_not_max_excursion_plus_25")

    tp1_distance = adaptive_tp1_distance(average_expansion=avg_expansion, max_expansion=max_expansion)
    quartiles = expansion_quartiles(max_expansion)
    tp_distances = [
        tp1_distance,
        quartiles["tp2_quartile_distance"],
        quartiles["tp3_quartile_distance"],
        quartiles["tp4_quartile_distance"],
    ]
    expected_tps = [_expected_price_from_level(direction, h1_level, d) for d in tp_distances]
    current_tp_from_entry = abs(take_profit - entry)
    current_tp_from_h1 = abs(take_profit - h1_level)
    tp_tolerance = max(0.25, max(tp_distances or [0]) * 0.05)
    anchored_to_h1 = _matches_any_distance(current_tp_from_h1, tp_distances, tp_tolerance)
    reward_distance = _to_float(row.get("reward_distance"))
    entry_anchored = reward_distance is not None and abs(current_tp_from_entry - reward_distance) <= 0.25
    if anchored_to_h1:
        tp_label = "TP_H1_ANCHORED"
    elif entry_anchored:
        tp_label = "TP_APPEARS_ENTRY_ANCHORED"
        reasons.append("tp_appears_entry_anchored")
    else:
        tp_label = "TP_NOT_SPEC_ALIGNED"
        reasons.append("tp_not_h1_quartile_aligned")

    current_rr = _safe_rr(take_profit, entry, stop)
    expected_rrs = [_safe_rr(tp, entry, expected_sl_price) for tp in expected_tps]
    if current_rr is not None and current_rr < 1.0:
        reasons.append("current_planned_rr_below_1")

    score_parts = [
        sequence.get("h1_liquidity_taken") is True,
        sequence.get("liquidity_sequence_valid") is True,
        entry_near_mae,
        sl_matches,
        not sl_exceeds_12,
        anchored_to_h1,
        current_rr is not None and current_rr >= 1.0,
    ]
    score = round(100 * sum(1 for ok in score_parts if ok) / len(score_parts), 2)
    if profile is None or not h1_ref:
        label = "UNKNOWN_INSUFFICIENT_DATA"
    elif score >= 80:
        label = "SPEC_ALIGNED"
    elif score >= 40:
        label = "PARTIALLY_ALIGNED"
    else:
        label = "NOT_ALIGNED"

    out.update(
        {
            "h1_reference_timestamp": h1_ref.get("h1_reference_timestamp"),
            "h1_reference_type": h1_ref.get("h1_reference_type"),
            "h1_high": h1_ref.get("h1_high"),
            "h1_low": h1_ref.get("h1_low"),
            "h1_liquidity_level": h1_level,
            "h1_liquidity_side": side,
            "h1_liquidity_taken": sequence.get("h1_liquidity_taken"),
            "h1_liquidity_taken_timestamp": sequence.get("h1_liquidity_taken_timestamp"),
            "m15_0045_timestamp": m15_ref.get("m15_0045_timestamp"),
            "m15_0045_high": m15_ref.get("m15_0045_high"),
            "m15_0045_low": m15_ref.get("m15_0045_low"),
            "m15_opposite_level_taken_before_h1": sequence.get("m15_opposite_level_taken_before_h1"),
            "liquidity_sequence_valid": sequence.get("liquidity_sequence_valid"),
            "liquidity_sequence_reason_codes": "|".join(str(v) for v in sequence.get("liquidity_sequence_reason_codes") or []),
            "entry_distance_from_h1_level_usd": _round(entry_deviation),
            "historical_average_mae_used": _round(avg_mae),
            "historical_max_excursion_used": _round(max_exc),
            "entry_near_average_mae": entry_near_mae,
            "mae_alignment_label": mae_label,
            "sl_distance_from_entry_usd": _round(sl_distance_from_entry),
            "sl_distance_from_h1_level_usd": _round(sl_distance_from_h1),
            "expected_sl_distance_from_h1_level_usd": _round(expected_sl_distance),
            "expected_sl_price": _round(expected_sl_price),
            "sl_matches_max_excursion_plus_25": sl_matches,
            "sl_exceeds_12_usd": sl_exceeds_12,
            "sl_sanity_label": sl_label,
            "current_tp_distance_from_entry_usd": _round(current_tp_from_entry),
            "current_tp_distance_from_h1_level_usd": _round(current_tp_from_h1),
            "expected_tp1_price": expected_tps[0],
            "expected_tp2_price": expected_tps[1],
            "expected_tp3_price": expected_tps[2],
            "expected_tp4_price": expected_tps[3],
            "current_tp_anchored_to_h1_level": anchored_to_h1,
            "current_tp_appears_entry_anchored": entry_anchored,
            "tp_alignment_label": tp_label,
            "current_planned_rr": current_rr,
            "expected_rr_to_tp1": expected_rrs[0],
            "expected_rr_to_tp2": expected_rrs[1],
            "expected_rr_to_tp3": expected_rrs[2],
            "expected_rr_to_tp4": expected_rrs[3],
            "spec_alignment_score": score,
            "spec_alignment_label": label,
            "spec_deviation_reason_codes": "|".join(sorted(set(reasons))),
        }
    )
    return out


def _unknown_alignment(reasons: list[str]) -> dict[str, Any]:
    return {
        "spec_alignment_score": 0.0,
        "spec_alignment_label": "UNKNOWN_INSUFFICIENT_DATA",
        "spec_deviation_reason_codes": "|".join(sorted(set(reasons))),
    }


def build_spec_alignment_audit(
    trades: list[dict[str, Any]],
    *,
    market_data: dict[str, pd.DataFrame],
    profile: LiquidityExpansionStatsProfile | None,
    source_path: str,
    symbol: str,
    source_pdf_found: bool = False,
) -> dict[str, Any]:
    m1 = normalize_ohlc(market_data.get("M1"))
    m15 = normalize_ohlc(market_data.get("M15"))
    h1 = normalize_ohlc(market_data.get("H1"))
    rows = [
        audit_trade_against_spec(row, index=index, m1=m1, m15=m15, h1=h1, profile=profile)
        for index, row in enumerate(trades)
    ]
    total = len(rows)
    label_counts = Counter(str(row.get("spec_alignment_label") or "UNKNOWN") for row in rows)
    deviation_counts: Counter[str] = Counter()
    for row in rows:
        for code in str(row.get("spec_deviation_reason_codes") or "").split("|"):
            if code:
                deviation_counts[code] += 1
    h1_identified = sum(1 for row in rows if row.get("h1_liquidity_level") not in (None, ""))
    m15_computable = sum(1 for row in rows if row.get("m15_0045_timestamp"))
    sequence_valid = sum(1 for row in rows if row.get("liquidity_sequence_valid") is True)
    entry_near_mae = sum(1 for row in rows if row.get("entry_near_average_mae") is True)
    sl_aligned = sum(1 for row in rows if row.get("sl_matches_max_excursion_plus_25") is True)
    sl_gt_12 = sum(1 for row in rows if row.get("sl_exceeds_12_usd") is True)
    tp_h1 = sum(1 for row in rows if row.get("current_tp_anchored_to_h1_level") is True)
    tp_entry = sum(1 for row in rows if row.get("current_tp_appears_entry_anchored") is True)
    spec_aligned = sum(1 for row in rows if row.get("spec_alignment_label") == "SPEC_ALIGNED")
    current_sl_values = [_to_float(row.get("sl_distance_from_entry_usd")) for row in rows]
    expected_sl_values = [_to_float(row.get("expected_sl_distance_from_h1_level_usd")) for row in rows]
    summary = {
        "research_only": True,
        "safety": SAFETY,
        "symbol": symbol,
        "source_path": source_path,
        "source_pdf_found": source_pdf_found,
        "source_spec_flag": None if source_pdf_found else "SOURCE_PDF_NOT_AVAILABLE_USED_EMBEDDED_SPEC",
        "total_trades_audited": total,
        "h1_level_identified_count": h1_identified,
        "h1_level_identified_rate": _rate(h1_identified, total),
        "m15_0045_filter_computable_count": m15_computable,
        "m15_0045_filter_computable_rate": _rate(m15_computable, total),
        "liquidity_sequence_valid_count": sequence_valid,
        "liquidity_sequence_valid_rate": _rate(sequence_valid, total),
        "entry_near_mae_count": entry_near_mae,
        "entry_near_mae_rate": _rate(entry_near_mae, total),
        "sl_aligned_count": sl_aligned,
        "sl_aligned_rate": _rate(sl_aligned, total),
        "sl_gt_12_count": sl_gt_12,
        "sl_gt_12_rate": _rate(sl_gt_12, total),
        "tp_anchored_to_h1_count": tp_h1,
        "tp_anchored_to_h1_rate": _rate(tp_h1, total),
        "tp_entry_anchored_count": tp_entry,
        "tp_entry_anchored_rate": _rate(tp_entry, total),
        "average_current_sl": _mean(current_sl_values),
        "median_current_sl": _median(current_sl_values),
        "min_current_sl": _min(current_sl_values),
        "max_current_sl": _max(current_sl_values),
        "average_expected_sl": _mean(expected_sl_values),
        "median_expected_sl": _median(expected_sl_values),
        "min_expected_sl": _min(expected_sl_values),
        "max_expected_sl": _max(expected_sl_values),
        "average_current_planned_rr": _mean(_to_float(row.get("current_planned_rr")) for row in rows),
        "average_expected_rr_to_tp1": _mean(_to_float(row.get("expected_rr_to_tp1")) for row in rows),
        "average_expected_rr_to_tp2": _mean(_to_float(row.get("expected_rr_to_tp2")) for row in rows),
        "average_expected_rr_to_tp3": _mean(_to_float(row.get("expected_rr_to_tp3")) for row in rows),
        "average_expected_rr_to_tp4": _mean(_to_float(row.get("expected_rr_to_tp4")) for row in rows),
        "spec_aligned_count": spec_aligned,
        "spec_aligned_rate": _rate(spec_aligned, total),
        "spec_alignment_label_counts": dict(label_counts),
        "spec_deviation_reason_counts": dict(deviation_counts),
        "spec_audit_insufficient_data": h1_identified == 0 or m15_computable == 0 or profile is None or profile.samples <= 0,
    }
    verdict_flags = []
    if not source_pdf_found:
        verdict_flags.append("SOURCE_PDF_NOT_AVAILABLE_USED_EMBEDDED_SPEC")
    if summary["spec_audit_insufficient_data"]:
        verdict_flags.append("SPEC_AUDIT_INSUFFICIENT_DATA")
    if total and summary["spec_aligned_rate"] < 0.5:
        verdict_flags.append("STRATEGY_2_0_SPEC_MISMATCH_CONFIRMED")
    if summary["tp_entry_anchored_rate"] > summary["tp_anchored_to_h1_rate"] or summary["tp_anchored_to_h1_rate"] < 0.5:
        verdict_flags.append("CURRENT_TP_SL_ANCHORING_WRONG")
    if summary["sl_gt_12_rate"] >= 0.5:
        verdict_flags.append("CURRENT_SL_TOO_LARGE_FOR_SCALPING_MODEL")
    if (summary["average_current_planned_rr"] or 0) < 1.0:
        verdict_flags.append("CURRENT_RR_STRUCTURALLY_UNFAVORABLE")
    if summary["liquidity_sequence_valid_rate"] < 0.5:
        verdict_flags.append("M15_SEQUENCE_FILTER_MISSING_OR_FAILED")
    if summary["entry_near_mae_rate"] < 0.5:
        verdict_flags.append("MAE_ENTRY_MODEL_MISSING_OR_FAILED")
    verdict_flags.extend(["STRATEGY_2_REMAINS_RESEARCH_ONLY", "NO_LIVE_DEPLOYMENT_DECISION"])
    summary["verdict_flags"] = verdict_flags
    return {
        "trade_rows": rows,
        "summary": summary,
        "report_markdown": render_audit_markdown(summary),
    }


def render_audit_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Strategy 2 Spec Alignment Audit",
        "",
        "Research-only audit. No live trading, no orders, no Telegram, no Strategy 2.0 in-place changes.",
        "",
        "## Inputs",
        "",
        f"- symbol: `{summary['symbol']}`",
        f"- executed trades: `{summary['source_path']}`",
        f"- PDF found: `{summary['source_pdf_found']}`",
        f"- source spec flag: `{summary.get('source_spec_flag')}`",
        "",
        "## Summary",
        "",
        f"- trades audited: `{summary['total_trades_audited']}`",
        f"- H1 level identified: `{summary['h1_level_identified_count']}` / `{summary['total_trades_audited']}`",
        f"- M15 00:45 computable: `{summary['m15_0045_filter_computable_count']}` / `{summary['total_trades_audited']}`",
        f"- liquidity sequence valid rate: `{summary['liquidity_sequence_valid_rate']}`",
        f"- entry near MAE rate: `{summary['entry_near_mae_rate']}`",
        f"- SL aligned rate: `{summary['sl_aligned_rate']}`",
        f"- SL > 12 USD rate: `{summary['sl_gt_12_rate']}`",
        f"- TP anchored to H1 rate: `{summary['tp_anchored_to_h1_rate']}`",
        f"- TP appears entry anchored rate: `{summary['tp_entry_anchored_rate']}`",
        f"- average current SL: `{summary['average_current_sl']}`",
        f"- median current SL: `{summary['median_current_sl']}`",
        f"- min/max current SL: `{summary['min_current_sl']}` / `{summary['max_current_sl']}`",
        f"- average expected SL: `{summary['average_expected_sl']}`",
        f"- median expected SL: `{summary['median_expected_sl']}`",
        f"- min/max expected SL: `{summary['min_expected_sl']}` / `{summary['max_expected_sl']}`",
        f"- average current planned R:R: `{summary['average_current_planned_rr']}`",
        f"- average expected R:R to TP1/TP2/TP3/TP4: `{summary['average_expected_rr_to_tp1']}`, `{summary['average_expected_rr_to_tp2']}`, `{summary['average_expected_rr_to_tp3']}`, `{summary['average_expected_rr_to_tp4']}`",
        f"- spec aligned rate: `{summary['spec_aligned_rate']}`",
        "",
        "## Alignment Labels",
        "",
        "```json",
        json.dumps(summary["spec_alignment_label_counts"], indent=2, sort_keys=True),
        "```",
        "",
        "## Deviation Reasons",
        "",
        "```json",
        json.dumps(summary["spec_deviation_reason_counts"], indent=2, sort_keys=True),
        "```",
        "",
        "## Verdict Flags",
        "",
        "\n".join(f"- `{flag}`" for flag in summary["verdict_flags"]),
    ]
    return "\n".join(lines) + "\n"


def write_audit_outputs(report: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "trades_csv": str(output_dir / "strategy_2_spec_alignment_trades.csv"),
        "trades_jsonl": str(output_dir / "strategy_2_spec_alignment_trades.jsonl"),
        "summary_json": str(output_dir / "strategy_2_spec_alignment_summary.json"),
        "report_md": str(output_dir / "strategy_2_spec_alignment_report.md"),
    }
    with Path(paths["trades_csv"]).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SPEC_AUDIT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["trade_rows"])
    with Path(paths["trades_jsonl"]).open("w", encoding="utf-8") as f:
        for row in report["trade_rows"]:
            f.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    Path(paths["summary_json"]).write_text(json.dumps(report["summary"], indent=2, sort_keys=True, default=str), encoding="utf-8")
    Path(paths["report_md"]).write_text(report["report_markdown"], encoding="utf-8")
    return paths


__all__ = [
    "SAFETY",
    "SPEC_AUDIT_FIELDS",
    "audit_trade_against_spec",
    "build_spec_alignment_audit",
    "load_stats_profile",
    "render_audit_markdown",
    "write_audit_outputs",
]
