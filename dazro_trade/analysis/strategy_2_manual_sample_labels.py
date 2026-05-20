from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable, Literal

import pandas as pd

from dazro_trade.analysis.strategy_2_liquidity_expansion_stats import percentile
from dazro_trade.analysis.strategy_2_statistical_samples import price_to_pips, pips_to_price


SOURCE_TYPES = {"manual_trade", "missed_trade", "screenshot_only", "rejected_setup", "replay_label"}
USER_GRADES = {"A_PLUS", "A", "B", "C", "NO_TRADE", "INVALID", "UNCERTAIN"}
LABEL_CONFIDENCE = {"high", "medium", "low", ""}
DIRECTIONS = {"long", "short", ""}
REFERENCE_TYPES = {"previous_h1", "dominant_h1", "manual", ""}
RESULTS = {"TP1", "TP2", "TP3", "TP4", "BE", "SL", "manual_close", "no_trade", "unknown", ""}
SETUP_MODELS = {"immediate_expansion", "accumulation_before_expansion", "unknown", ""}
REACTION_QUALITIES = {"strong_reclaim", "clean_rejection", "aggressive_shift", "weak_reaction", "no_reaction", "unknown", ""}
CANDLE_QUALITIES = {"clean", "acceptable", "dirty", "unknown", ""}
TRI_STATE = {"true", "false", "unknown", ""}
AVOID_REASONS = {
    "opposite_x45_taken_first",
    "no_reaction",
    "dirty_setup",
    "manipulation_too_deep",
    "manipulation_too_shallow",
    "range_too_large",
    "range_too_small",
    "target_space_too_small",
    "news_or_spike",
    "late_entry",
    "already_distributed",
    "unclear",
    "none",
    "",
}

REQUIRED_MINIMUM_FIELDS = [
    "manual_sample_id",
    "symbol",
    "h1_timestamp",
    "direction",
    "user_grade",
    "manual_trade_taken",
    "notes",
    "user_reasoning",
]

MANUAL_LABEL_FIELDS = [
    "manual_sample_id",
    "source_type",
    "screenshot_ref",
    "notes",
    "symbol",
    "date",
    "h1_timestamp",
    "timezone",
    "session",
    "direction",
    "h1_reference_type",
    "h1_reference_timestamp",
    "h1_high",
    "h1_low",
    "liquidity_level",
    "h1_range",
    "m15_x45_timestamp",
    "m15_x45_high",
    "m15_x45_low",
    "m15_x45_sequence_valid",
    "opposite_x45_taken_first",
    "sequence_notes",
    "manual_trade_taken",
    "manual_entry_price",
    "manual_stop_loss",
    "manual_tp1",
    "manual_tp2",
    "manual_tp3",
    "manual_tp4",
    "manual_result",
    "manipulation_depth_pips",
    "manipulation_depth_usd",
    "max_excursion_pips",
    "max_excursion_usd",
    "conservative_sl_pips",
    "conservative_sl_usd",
    "expansion_pips",
    "expansion_usd",
    "tp1_distance_pips",
    "tp2_distance_pips",
    "tp3_distance_pips",
    "tp4_distance_pips",
    "user_grade",
    "label_confidence",
    "setup_model",
    "reaction_quality",
    "candle_anatomy_quality",
    "compression_before_sweep",
    "move_already_consumed",
    "avoid_reason",
    "user_reasoning",
    "reviewer_notes",
]

SAFETY = {
    "research_only": True,
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "broker_called": False,
    "order_sent": False,
    "order_send_called": False,
    "data_files_written": False,
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


def _mean(values: Iterable[float]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(fmean(vals), 4) if vals else None


def _median(values: Iterable[float]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(median(vals), 4) if vals else None


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _clean(value).upper()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _boolish(value: Any) -> str:
    text = _lower(value)
    if text in {"1", "true", "yes", "y"}:
        return "true"
    if text in {"0", "false", "no", "n"}:
        return "false"
    if text in {"unknown", "unclear", ""}:
        return "unknown" if text else ""
    return text


def is_example_row(row: dict[str, Any]) -> bool:
    sample_id = _upper(row.get("manual_sample_id"))
    return sample_id.startswith("EXAMPLE_") or "EXAMPLE_ONLY" in _upper(row.get("notes"))


def template_rows() -> list[dict[str, Any]]:
    base = {field: "" for field in MANUAL_LABEL_FIELDS}
    examples = [
        {
            "manual_sample_id": "EXAMPLE_A_PLUS_001",
            "source_type": "manual_trade",
            "notes": "EXAMPLE_ONLY replace this row before real analysis",
            "symbol": "XAUUSD",
            "date": "2026-05-11",
            "h1_timestamp": "2026-05-11T14:00:00+00:00",
            "timezone": "UTC",
            "session": "NewYork",
            "direction": "long",
            "h1_reference_type": "previous_h1",
            "liquidity_level": "2400.00",
            "m15_x45_sequence_valid": "true",
            "manual_trade_taken": "true",
            "manual_entry_price": "2395.40",
            "manual_stop_loss": "2386.00",
            "manual_tp1": "2410.00",
            "manual_result": "TP2",
            "manipulation_depth_pips": "45.9",
            "manipulation_depth_usd": "4.59",
            "expansion_pips": "193.6",
            "expansion_usd": "19.36",
            "user_grade": "A_PLUS",
            "label_confidence": "high",
            "setup_model": "immediate_expansion",
            "reaction_quality": "strong_reclaim",
            "candle_anatomy_quality": "clean",
            "compression_before_sweep": "false",
            "move_already_consumed": "false",
            "avoid_reason": "none",
            "user_reasoning": "Example clean reclaim and distribution. Replace with real user label.",
        },
        {
            "manual_sample_id": "EXAMPLE_NO_TRADE_002",
            "source_type": "rejected_setup",
            "notes": "EXAMPLE_ONLY replace this row before real analysis",
            "symbol": "XAUUSD",
            "date": "2026-05-12",
            "h1_timestamp": "2026-05-12T09:00:00+00:00",
            "timezone": "UTC",
            "session": "London",
            "direction": "short",
            "h1_reference_type": "dominant_h1",
            "m15_x45_sequence_valid": "false",
            "opposite_x45_taken_first": "true",
            "manual_trade_taken": "false",
            "manual_result": "no_trade",
            "manipulation_depth_pips": "160.0",
            "manipulation_depth_usd": "16.0",
            "expansion_pips": "60.0",
            "expansion_usd": "6.0",
            "user_grade": "NO_TRADE",
            "label_confidence": "medium",
            "setup_model": "unknown",
            "reaction_quality": "weak_reaction",
            "candle_anatomy_quality": "dirty",
            "compression_before_sweep": "unknown",
            "move_already_consumed": "true",
            "avoid_reason": "opposite_x45_taken_first",
            "user_reasoning": "Example rejected setup. Replace with real user label.",
        },
        {
            "manual_sample_id": "EXAMPLE_B_003",
            "source_type": "missed_trade",
            "notes": "EXAMPLE_ONLY replace this row before real analysis",
            "symbol": "XAUUSD",
            "date": "2026-05-13",
            "h1_timestamp": "2026-05-13T15:00:00+00:00",
            "timezone": "UTC",
            "session": "NewYork",
            "direction": "long",
            "manual_trade_taken": "false",
            "manual_result": "unknown",
            "manipulation_depth_pips": "72.0",
            "manipulation_depth_usd": "7.2",
            "expansion_pips": "120.0",
            "expansion_usd": "12.0",
            "user_grade": "B",
            "label_confidence": "low",
            "reaction_quality": "clean_rejection",
            "candle_anatomy_quality": "acceptable",
            "avoid_reason": "unclear",
            "user_reasoning": "Example partial label with many optional fields blank.",
        },
    ]
    return [{**base, **row} for row in examples]


def write_template(output_dir: Path, *, output_format: Literal["csv", "jsonl", "both"] = "both") -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = template_rows()
    paths: dict[str, str] = {}
    if output_format in {"csv", "both"}:
        csv_path = output_dir / "manual_sample_template.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=MANUAL_LABEL_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        paths["csv"] = str(csv_path)
    if output_format in {"jsonl", "both"}:
        jsonl_path = output_dir / "manual_sample_template.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, sort_keys=True) + "\n")
        paths["jsonl"] = str(jsonl_path)
    readme_path = output_dir / "README_manual_sample_labels.md"
    readme_path.write_text(render_template_readme(), encoding="utf-8")
    paths["readme"] = str(readme_path)
    return paths


def render_template_readme() -> str:
    return (
        "# Strategy 2 Manual Sample Labels\n\n"
        "This is a research-only label template. Replace the EXAMPLE_ONLY rows with real user labels before drawing conclusions.\n\n"
        "Minimum required fields: manual_sample_id, symbol, h1_timestamp, direction, user_grade, manual_trade_taken, notes/user_reasoning.\n\n"
        "Use 10-30 labels minimum and prefer 30+. Include winners, losers, BE, no-entry valid samples, rejected setups, and invalid examples.\n"
    )


def read_manual_labels(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".jsonl":
        rows: list[dict[str, str]] = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append({str(k): "" if v is None else str(v) for k, v in json.loads(line).items()})
        return rows
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [{str(k): "" if v is None else str(v) for k, v in row.items()} for row in reader]


def normalize_manual_row(row: dict[str, Any], *, pip_factor: float = 10.0) -> dict[str, Any]:
    out = {field: _clean(row.get(field)) for field in MANUAL_LABEL_FIELDS}
    out["source_type"] = _lower(out.get("source_type"))
    out["direction"] = _lower(out.get("direction"))
    out["h1_reference_type"] = _lower(out.get("h1_reference_type"))
    out["user_grade"] = _upper(out.get("user_grade"))
    out["label_confidence"] = _lower(out.get("label_confidence"))
    out["setup_model"] = _lower(out.get("setup_model"))
    out["reaction_quality"] = _lower(out.get("reaction_quality"))
    out["candle_anatomy_quality"] = _lower(out.get("candle_anatomy_quality"))
    out["compression_before_sweep"] = _boolish(out.get("compression_before_sweep"))
    out["move_already_consumed"] = _boolish(out.get("move_already_consumed"))
    out["m15_x45_sequence_valid"] = _boolish(out.get("m15_x45_sequence_valid"))
    out["opposite_x45_taken_first"] = _boolish(out.get("opposite_x45_taken_first"))
    out["manual_trade_taken"] = _boolish(out.get("manual_trade_taken"))
    out["avoid_reason"] = _lower(out.get("avoid_reason"))
    _fill_distance_pair(out, "manipulation_depth", pip_factor)
    _fill_distance_pair(out, "max_excursion", pip_factor)
    _fill_distance_pair(out, "conservative_sl", pip_factor)
    _fill_distance_pair(out, "expansion", pip_factor)
    for tp in ("tp1_distance", "tp2_distance", "tp3_distance", "tp4_distance"):
        _fill_distance_pair(out, tp, pip_factor)
    out["pip_factor_used"] = pip_factor
    out["is_example"] = is_example_row(out)
    return out


def _fill_distance_pair(row: dict[str, Any], prefix: str, pip_factor: float) -> None:
    pips_key = f"{prefix}_pips"
    usd_key = f"{prefix}_usd"
    pips = _to_float(row.get(pips_key))
    usd = _to_float(row.get(usd_key))
    if usd is None and pips is not None:
        usd = pips_to_price(pips, pip_factor)
        row[usd_key] = str(usd)
    if pips is None and usd is not None:
        pips = price_to_pips(usd, pip_factor)
        row[pips_key] = str(pips)


def validate_manual_labels(rows: list[dict[str, Any]], *, pip_factor: float = 10.0) -> dict[str, Any]:
    normalized = [normalize_manual_row(row, pip_factor=pip_factor) for row in rows]
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, row in enumerate(normalized, start=1):
        sample_id = row.get("manual_sample_id")
        if not sample_id:
            errors.append({"row": idx, "field": "manual_sample_id", "message": "required"})
        elif sample_id in seen_ids:
            errors.append({"row": idx, "field": "manual_sample_id", "message": "duplicate"})
        else:
            seen_ids.add(sample_id)
        for field in REQUIRED_MINIMUM_FIELDS:
            if field in {"notes", "user_reasoning"}:
                continue
            if not row.get(field):
                errors.append({"row": idx, "field": field, "message": "required_minimum_field_missing"})
        if not row.get("notes") and not row.get("user_reasoning"):
            errors.append({"row": idx, "field": "notes/user_reasoning", "message": "one_of_notes_or_user_reasoning_required"})
        _enum_check(errors, idx, row, "source_type", SOURCE_TYPES, allow_blank=True)
        _enum_check(errors, idx, row, "direction", DIRECTIONS, allow_blank=False)
        _enum_check(errors, idx, row, "h1_reference_type", REFERENCE_TYPES, allow_blank=True)
        _enum_check(errors, idx, row, "manual_result", RESULTS, allow_blank=True)
        _enum_check(errors, idx, row, "user_grade", USER_GRADES, allow_blank=False)
        _enum_check(errors, idx, row, "label_confidence", LABEL_CONFIDENCE, allow_blank=True)
        _enum_check(errors, idx, row, "setup_model", SETUP_MODELS, allow_blank=True)
        _enum_check(errors, idx, row, "reaction_quality", REACTION_QUALITIES, allow_blank=True)
        _enum_check(errors, idx, row, "candle_anatomy_quality", CANDLE_QUALITIES, allow_blank=True)
        _enum_check(errors, idx, row, "compression_before_sweep", TRI_STATE, allow_blank=True)
        _enum_check(errors, idx, row, "move_already_consumed", TRI_STATE, allow_blank=True)
        _enum_check(errors, idx, row, "avoid_reason", AVOID_REASONS, allow_blank=True)
        if row.get("h1_timestamp") and _timestamp(row.get("h1_timestamp")) is None:
            errors.append({"row": idx, "field": "h1_timestamp", "message": "invalid_timestamp"})
        if row["is_example"]:
            warnings.append({"row": idx, "field": "manual_sample_id", "message": "example_row_not_real_label"})
    real_rows = [row for row in normalized if not row["is_example"]]
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "rows_loaded": len(rows),
        "real_label_rows": len(real_rows),
        "example_rows": len(normalized) - len(real_rows),
        "manual_labels_not_provided_yet": len(real_rows) == 0,
        "normalized_rows": normalized,
        "required_minimum_fields": REQUIRED_MINIMUM_FIELDS,
        "schema_fields": MANUAL_LABEL_FIELDS,
        "pip_factor_used": pip_factor,
    }


def _enum_check(
    errors: list[dict[str, Any]],
    idx: int,
    row: dict[str, Any],
    field: str,
    allowed: set[str],
    *,
    allow_blank: bool,
) -> None:
    value = row.get(field, "")
    if value == "" and allow_blank:
        return
    if value not in allowed:
        errors.append({"row": idx, "field": field, "message": f"invalid_value:{value}"})


def read_auto_samples(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [{str(k): "" if v is None else str(v) for k, v in row.items()} for row in reader]


def match_manual_to_auto_samples(
    manual_rows: list[dict[str, Any]],
    auto_rows: list[dict[str, Any]],
    *,
    time_tolerance_minutes: int = 90,
    level_tolerance_usd: float = 2.0,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    auto_prepared = [_prepare_auto_row(row) for row in auto_rows]
    for row in manual_rows:
        manual_ts = _timestamp(row.get("h1_timestamp"))
        direction = _lower(row.get("direction"))
        liquidity = _to_float(row.get("liquidity_level"))
        candidates = []
        if manual_ts is not None:
            for auto in auto_prepared:
                if direction and _lower(auto.get("direction")) != direction:
                    continue
                auto_ts = _timestamp(auto.get("h1_context_timestamp"))
                if auto_ts is None:
                    continue
                minutes = abs((auto_ts - manual_ts).total_seconds()) / 60
                if minutes > time_tolerance_minutes:
                    continue
                level_delta = None
                if liquidity is not None and auto.get("h1_liquidity_level") not in (None, ""):
                    level_delta = abs(float(auto["h1_liquidity_level"]) - liquidity)
                    if level_delta > level_tolerance_usd:
                        continue
                candidates.append((minutes, level_delta if level_delta is not None else 9999.0, auto))
        candidates.sort(key=lambda item: (item[0], item[1]))
        if not candidates:
            status = "unmatched"
            match_id = ""
        elif len(candidates) == 1:
            status = "matched"
            match_id = candidates[0][2].get("sample_id", "")
        else:
            first = candidates[0]
            second = candidates[1]
            status = "ambiguous_match" if abs(first[0] - second[0]) <= 15 and abs(first[1] - second[1]) <= 1.0 else "matched"
            match_id = first[2].get("sample_id", "")
        matches.append(
            {
                "manual_sample_id": row.get("manual_sample_id"),
                "match_status": status,
                "matched_auto_sample_id": match_id,
                "candidate_count": len(candidates),
            }
        )
    return matches


def _prepare_auto_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items()}


def profile_label_subset(rows: list[dict[str, Any]], *, subset_name: str, pip_factor: float = 10.0) -> dict[str, Any]:
    manipulations = [_to_float(row.get("manipulation_depth_usd")) for row in rows]
    manipulations = [v for v in manipulations if v is not None]
    expansions = [_to_float(row.get("expansion_usd")) for row in rows]
    expansions = [v for v in expansions if v is not None]
    max_manip = round(max(manipulations), 4) if manipulations else 0.0
    conservative = round(max_manip * 1.25, 4)
    max_exp = round(max(expansions), 4) if expansions else 0.0
    avg_exp = _mean(expansions) or 0.0
    tp1 = round(max_exp * 0.25, 4)
    tp2 = round(max_exp * 0.50, 4)
    tp3 = round(max_exp * 0.75, 4)
    tp4 = round(max_exp, 4)
    adaptive_tp1 = round(avg_exp if avg_exp > 0 and avg_exp < tp1 else tp1, 4)
    avg_mae = _mean(manipulations) or 0.0
    profile = {
        "subset_name": subset_name,
        "count": len(rows),
        "direction_counts": dict(Counter(_lower(row.get("direction")) or "unknown" for row in rows)),
        "session_counts": dict(Counter(_clean(row.get("session")) or "unknown" for row in rows)),
        "h1_reference_counts": dict(Counter(_lower(row.get("h1_reference_type")) or "unknown" for row in rows)),
        "avg_manipulation_usd": avg_mae,
        "avg_manipulation_pips": price_to_pips(avg_mae, pip_factor),
        "median_manipulation_usd": _median(manipulations),
        "p75_manipulation_usd": percentile(manipulations, 0.75) if manipulations else None,
        "p90_manipulation_usd": percentile(manipulations, 0.90) if manipulations else None,
        "p95_manipulation_usd": percentile(manipulations, 0.95) if manipulations else None,
        "max_manipulation_usd": max_manip,
        "max_manipulation_pips": price_to_pips(max_manip, pip_factor),
        "risky_sl_usd": max_manip,
        "risky_sl_pips": price_to_pips(max_manip, pip_factor),
        "conservative_sl_usd": conservative,
        "conservative_sl_pips": price_to_pips(conservative, pip_factor),
        "p95_diagnostic_sl_usd": round((percentile(manipulations, 0.95) or 0.0) * 1.25, 4) if manipulations else None,
        "p90_diagnostic_sl_usd": round((percentile(manipulations, 0.90) or 0.0) * 1.25, 4) if manipulations else None,
        "pct_le_8_usd": _pct(manipulations, lambda v: v <= 8),
        "pct_le_10_usd": _pct(manipulations, lambda v: v <= 10),
        "pct_le_12_usd": _pct(manipulations, lambda v: v <= 12),
        "pct_gt_12_usd": _pct(manipulations, lambda v: v > 12),
        "pct_gt_15_usd": _pct(manipulations, lambda v: v > 15),
        "pct_gt_20_usd": _pct(manipulations, lambda v: v > 20),
        "avg_expansion_usd": avg_exp,
        "median_expansion_usd": _median(expansions),
        "max_expansion_usd": max_exp,
        "tp1_distance_usd": tp1,
        "tp2_distance_usd": tp2,
        "tp3_distance_usd": tp3,
        "tp4_distance_usd": tp4,
        "adaptive_tp1_distance_usd": adaptive_tp1,
        "adaptive_tp1_used": bool(avg_exp > 0 and avg_exp < tp1),
        "rr_diagnostic": rr_diagnostic(avg_mae=avg_mae, risky_sl=max_manip, conservative_sl=conservative, tps=[tp1, tp2, tp3, tp4], adaptive_tp1=adaptive_tp1),
        "profile_risk_too_large": bool(max_manip * 1.25 > 12),
        "pip_factor_used": pip_factor,
    }
    return profile


def _pct(values: list[float], predicate: Any) -> float:
    return _rate(sum(1 for value in values if predicate(value)), len(values))


def rr_diagnostic(*, avg_mae: float, risky_sl: float, conservative_sl: float, tps: list[float], adaptive_tp1: float) -> dict[str, Any]:
    def rr(tp: float, stop: float) -> float | None:
        if stop <= 0:
            return None
        return round((avg_mae + tp) / stop, 4)
    risky = {f"tp{idx}_R": rr(tp, risky_sl) for idx, tp in enumerate(tps, start=1)}
    conservative = {f"tp{idx}_R": rr(tp, conservative_sl) for idx, tp in enumerate(tps, start=1)}
    flags = []
    if conservative.get("tp1_R") is not None and conservative["tp1_R"] < 0.5:
        flags.append("TP1_R_TOO_SMALL")
    if conservative.get("tp2_R") is not None and conservative["tp2_R"] < 1.0:
        flags.append("TP2_R_BELOW_1")
    if flags:
        flags.append("RR_STRUCTURALLY_UNFAVORABLE")
    return {
        "risky_stop_rr": risky,
        "conservative_stop_rr": conservative,
        "adaptive_TP1_R_risky_stop": rr(adaptive_tp1, risky_sl),
        "adaptive_TP1_R_conservative_stop": rr(adaptive_tp1, conservative_sl),
        "rr_structurally_valid": not flags,
        "rr_flags": flags,
    }


def build_manual_subset_profiles(rows: list[dict[str, Any]], *, pip_factor: float = 10.0) -> dict[str, Any]:
    real = [row for row in rows if not row.get("is_example")]
    subsets = {
        "all_manual_labels": real,
        "A_PLUS_only": [row for row in real if row.get("user_grade") == "A_PLUS"],
        "A_PLUS_A": [row for row in real if row.get("user_grade") in {"A_PLUS", "A"}],
        "A_PLUS_A_B": [row for row in real if row.get("user_grade") in {"A_PLUS", "A", "B"}],
        "NO_TRADE": [row for row in real if row.get("user_grade") == "NO_TRADE"],
        "INVALID": [row for row in real if row.get("user_grade") == "INVALID"],
    }
    return {name: profile_label_subset(group, subset_name=name, pip_factor=pip_factor) for name, group in subsets.items()}


def auto_rows_to_label_rows(auto_rows: list[dict[str, Any]], *, pip_factor: float = 10.0) -> list[dict[str, Any]]:
    converted = []
    for row in auto_rows:
        if str(row.get("sample_status") or "").startswith("VALID_"):
            converted.append(
                {
                    "manual_sample_id": row.get("sample_id"),
                    "symbol": row.get("symbol"),
                    "h1_timestamp": row.get("h1_context_timestamp"),
                    "direction": _lower(row.get("direction")),
                    "session": row.get("session"),
                    "h1_reference_type": row.get("h1_reference_type"),
                    "manipulation_depth_usd": row.get("manipulation_depth_usd") or row.get("manipulation_depth_price"),
                    "manipulation_depth_pips": row.get("manipulation_depth_pips"),
                    "expansion_usd": row.get("distribution_distance_usd") or row.get("distribution_distance_price"),
                    "expansion_pips": row.get("distribution_distance_pips"),
                    "user_grade": "UNCERTAIN",
                    "manual_trade_taken": "unknown",
                    "notes": "automatic sample converted for descriptive comparison",
                    "pip_factor_used": pip_factor,
                }
            )
    return [normalize_manual_row(row, pip_factor=pip_factor) for row in converted]


def deep_tail_analysis(auto_rows: list[dict[str, Any]], *, pip_factor: float = 10.0) -> list[dict[str, Any]]:
    converted = auto_rows_to_label_rows(auto_rows, pip_factor=pip_factor)
    subsets = {
        "body_le_8_usd": [row for row in converted if (_to_float(row.get("manipulation_depth_usd")) or 0.0) <= 8],
        "body_le_10_usd": [row for row in converted if (_to_float(row.get("manipulation_depth_usd")) or 0.0) <= 10],
        "body_le_12_usd": [row for row in converted if (_to_float(row.get("manipulation_depth_usd")) or 0.0) <= 12],
        "tail_gt_12_usd": [row for row in converted if (_to_float(row.get("manipulation_depth_usd")) or 0.0) > 12],
        "extreme_tail_gt_20_usd": [row for row in converted if (_to_float(row.get("manipulation_depth_usd")) or 0.0) > 20],
    }
    rows = []
    for name, group in subsets.items():
        profile = profile_label_subset(group, subset_name=name, pip_factor=pip_factor)
        rows.append(
            {
                "subset": name,
                "count": profile["count"],
                "avg_manipulation_usd": profile["avg_manipulation_usd"],
                "max_manipulation_usd": profile["max_manipulation_usd"],
                "avg_expansion_usd": profile["avg_expansion_usd"],
                "max_expansion_usd": profile["max_expansion_usd"],
                "direction_counts": json.dumps(profile["direction_counts"], sort_keys=True),
                "session_counts": json.dumps(profile["session_counts"], sort_keys=True),
                "h1_reference_counts": json.dumps(profile["h1_reference_counts"], sort_keys=True),
                "profile_risk_too_large": profile["profile_risk_too_large"],
            }
        )
    return rows


def compare_manual_to_global(manual_profiles: dict[str, Any], global_profile: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    global_avg = global_profile.get("avg_manipulation_usd")
    global_max = global_profile.get("max_manipulation_usd")
    global_p95 = global_profile.get("p95_manipulation_usd")
    global_exp = global_profile.get("avg_expansion_usd")
    for name, profile in manual_profiles.items():
        rows.append(
            {
                "subset": name,
                "count": profile["count"],
                "avg_manipulation_usd": profile["avg_manipulation_usd"],
                "delta_avg_manipulation_vs_global": _delta(profile.get("avg_manipulation_usd"), global_avg),
                "max_manipulation_usd": profile["max_manipulation_usd"],
                "delta_max_manipulation_vs_global": _delta(profile.get("max_manipulation_usd"), global_max),
                "p95_manipulation_usd": profile["p95_manipulation_usd"],
                "delta_p95_manipulation_vs_global": _delta(profile.get("p95_manipulation_usd"), global_p95),
                "avg_expansion_usd": profile["avg_expansion_usd"],
                "delta_avg_expansion_vs_global": _delta(profile.get("avg_expansion_usd"), global_exp),
                "rr_structurally_valid": profile["rr_diagnostic"]["rr_structurally_valid"],
                "profile_risk_too_large": profile["profile_risk_too_large"],
            }
        )
    return rows


def _delta(value: Any, baseline: Any) -> float | None:
    left = _to_float(value)
    right = _to_float(baseline)
    if left is None or right is None:
        return None
    return round(left - right, 4)


def feature_difference_rows(manual_rows: list[dict[str, Any]], auto_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aplus = [row for row in manual_rows if not row.get("is_example") and row.get("user_grade") in {"A_PLUS", "A"}]
    global_rows = auto_rows_to_label_rows(auto_rows)
    deep_tail = [row for row in global_rows if (_to_float(row.get("manipulation_depth_usd")) or 0.0) > 12]
    fields = [
        "session",
        "direction",
        "h1_reference_type",
        "reaction_quality",
        "candle_anatomy_quality",
        "compression_before_sweep",
        "move_already_consumed",
        "avoid_reason",
    ]
    rows = []
    for field in fields:
        rows.append(
            {
                "feature": field,
                "manual_A_A_PLUS_counts": json.dumps(dict(Counter(_clean(row.get(field)) or "unknown" for row in aplus)), sort_keys=True),
                "global_counts": json.dumps(dict(Counter(_clean(row.get(field)) or "unknown" for row in global_rows)), sort_keys=True),
                "deep_tail_counts": json.dumps(dict(Counter(_clean(row.get(field)) or "unknown" for row in deep_tail)), sort_keys=True),
            }
        )
    return rows


def build_manual_label_analysis(
    *,
    labels_path: Path,
    auto_samples_path: Path,
    pip_factor: float = 10.0,
) -> dict[str, Any]:
    manual_raw = read_manual_labels(labels_path)
    validation = validate_manual_labels(manual_raw, pip_factor=pip_factor)
    manual_rows = validation["normalized_rows"]
    auto_rows = read_auto_samples(auto_samples_path)
    matches = match_manual_to_auto_samples([row for row in manual_rows if not row.get("is_example")], auto_rows)
    manual_profiles = build_manual_subset_profiles(manual_rows, pip_factor=pip_factor)
    global_rows = auto_rows_to_label_rows(auto_rows, pip_factor=pip_factor)
    global_profile = profile_label_subset(global_rows, subset_name="automatic_valid_global", pip_factor=pip_factor)
    comparison = compare_manual_to_global(manual_profiles, global_profile)
    tail = deep_tail_analysis(auto_rows, pip_factor=pip_factor)
    feature_rows = feature_difference_rows(manual_rows, auto_rows)
    flags = [
        "MANUAL_SAMPLE_LABEL_PACK_BUILT",
        "MANUAL_LABEL_SCHEMA_CREATED",
        "GLOBAL_VALID_SAMPLE_POOL_TOO_BROAD",
        "DEEP_TAIL_DRIVES_RAW_MAX_EXCURSION",
        "BODY_OF_DISTRIBUTION_PLAUSIBLE",
        "USER_A_PLUS_FILTER_REQUIRED",
        "UNIT_CONVERSION_GUARDED",
        "STRATEGY_2_REMAINS_RESEARCH_ONLY",
        "NO_LIVE_DEPLOYMENT_DECISION",
    ]
    if validation["manual_labels_not_provided_yet"]:
        flags.append("MANUAL_LABELS_NOT_PROVIDED_YET")
    return {
        "validation": validation,
        "manual_profiles": manual_profiles,
        "global_profile": global_profile,
        "manual_vs_global_comparison": comparison,
        "deep_tail_analysis": tail,
        "feature_differences": feature_rows,
        "matches": matches,
        "verdict_flags": flags,
        "safety": SAFETY,
    }


__all__ = [
    "AVOID_REASONS",
    "MANUAL_LABEL_FIELDS",
    "REQUIRED_MINIMUM_FIELDS",
    "SAFETY",
    "USER_GRADES",
    "build_manual_label_analysis",
    "build_manual_subset_profiles",
    "compare_manual_to_global",
    "deep_tail_analysis",
    "is_example_row",
    "match_manual_to_auto_samples",
    "normalize_manual_row",
    "profile_label_subset",
    "read_auto_samples",
    "read_manual_labels",
    "template_rows",
    "validate_manual_labels",
    "write_template",
]
