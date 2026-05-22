"""Run the Adelin v2 expanded-sample diagnostic for frozen H1/H2.

This is a research-only execution of the signed expanded sample plan. It uses
existing expanded objective replay rows as sample inventory, computes frozen
pre-entry H1/H2 features from candles strictly before each decision timestamp,
and applies the signed minimum-N and leakage gates. It does not run Phase 4,
matched-control replay, live trading, broker/order code, Telegram, scoring, or
runtime strategy logic.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.backtest.data_loader import load_csv_timeframes
from scripts.analyze_adelin_v2_preentry_outcome_diagnostics import normalize_frames


PLAN_DIR = Path("backtests/reports/adelin_v2_good_fast_expanded_sample_plan")
SIGNOFF_PATH = Path("docs/research/adelin_v2_good_fast_expanded_sample_plan_signoff.md")
EXPANDED_REPLAY_DIR = Path("backtests/reports/adelin_v2_expanded_objective_outcome_replay")
EXPANDED_VISUAL_DIR = Path("backtests/reports/adelin_v2_expanded_candidate_window_pack")
DIRECTION_RECOVERY_DIR = Path("backtests/reports/adelin_v2_direction_metadata_recovery")
DEFAULT_OUTPUT_DIR = Path("backtests/reports/adelin_v2_expanded_sample_diagnostic_execution")
DEFAULT_DATA_DIR = Path("data")

PLAN_VERSION = "adelin_v2_expanded_sample_diagnostic_execution_v1"
DIRECTION_RULE_VERSION = "adelin_v2_pre_decision_sweep_v1"
PRIMARY_GROUPS = ("GOOD_FAST_REACTION", "FAST_FAILURE")
SECONDARY_GROUPS = ("MIXED_REACTION", "CHOP_AFTER_ENTRY")
PRIMARY_HYPOTHESES = ("fvg_ifvg_near_20p", "liquidity_htf_recent_level")
SECONDARY_FEATURES = ("m1_large_body_ge_0_60", "m1_close_high_ge_0_70")

FORBIDDEN_FEATURE_TOKENS = (
    "tp_hit",
    "sl_hit",
    "pnl",
    "r_multiple",
    "future_mfe",
    "future_mae",
    "max_favorable",
    "max_adverse",
    "post_entry",
    "non_directional_max_move",
)


@dataclass(frozen=True)
class ExpandedDiagnosticConfig:
    symbol: str = "XAUUSD"
    data_dir: Path = DEFAULT_DATA_DIR
    plan_dir: Path = PLAN_DIR
    signoff_path: Path = SIGNOFF_PATH
    expanded_replay_dir: Path = EXPANDED_REPLAY_DIR
    expanded_visual_dir: Path = EXPANDED_VISUAL_DIR
    direction_recovery_dir: Path = DIRECTION_RECOVERY_DIR
    output_dir: Path = DEFAULT_OUTPUT_DIR
    pip_size: float = 0.1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(fieldnames or sorted({key for row in rows for key in row}))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in names})


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse_ts(value: Any) -> pd.Timestamp | None:
    if not value:
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def normalize_token(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "_")


def rate(count: int, n: int) -> float:
    return round(count / n, 6) if n else 0.0


def validate_signed_plan(config: ExpandedDiagnosticConfig) -> tuple[bool, dict[str, Any]]:
    signoff_exists = config.signoff_path.exists()
    signoff_text = config.signoff_path.read_text(encoding="utf-8") if signoff_exists else ""
    signoff_approved = "Decision: APPROVE" in signoff_text
    required = {
        "expanded_sample_plan": config.plan_dir / "expanded_sample_plan.json",
        "frozen_hypotheses": config.plan_dir / "frozen_hypotheses.json",
        "sample_collection_schema": config.plan_dir / "sample_collection_schema.json",
        "minimum_n_gates": config.plan_dir / "minimum_n_gates.json",
        "future_execution_schema": config.plan_dir / "future_execution_schema.json",
        "decision_matrix": config.plan_dir / "decision_matrix.json",
        "summary": config.plan_dir / "summary.json",
    }
    files_exist = {name: path.exists() for name, path in required.items()}
    frozen = read_json(required["frozen_hypotheses"]) if files_exist["frozen_hypotheses"] else {}
    summary = read_json(required["summary"]) if files_exist["summary"] else {}
    gates = read_json(required["minimum_n_gates"]) if files_exist["minimum_n_gates"] else {}
    hypotheses = frozen.get("primary_hypotheses", [])
    posthoc_ok = bool(frozen.get("hypothesis_origin_disclosure", {}).get("hypothesis_origin") == "post_hoc_from_underpowered_exploratory_diagnostic")
    h_status_ok = all(
        item.get("validation_status") == "not_validated"
        and item.get("may_be_rejected_by_future_test") is True
        and item.get("not_deployment_evidence") is True
        for item in hypotheses
    )
    h_names = [item.get("feature_name") for item in hypotheses]
    result = {
        "signoff_exists": signoff_exists,
        "signoff_decision_approve": signoff_approved,
        "required_plan_files_exist": files_exist,
        "post_hoc_disclosure_exists": posthoc_ok,
        "h1_h2_not_validated": h_status_ok,
        "primary_hypotheses": h_names,
        "phase_4_blocked_in_plan": summary.get("phase_4_blocked") is True,
        "minimum_n_gates_exist": bool(gates),
        "direction_rule_version": DIRECTION_RULE_VERSION,
    }
    result["plan_valid"] = (
        signoff_exists
        and signoff_approved
        and all(files_exist.values())
        and posthoc_ok
        and h_status_ok
        and tuple(h_names) == PRIMARY_HYPOTHESES
        and result["phase_4_blocked_in_plan"]
        and bool(gates)
    )
    return bool(result["plan_valid"]), result


def outcome_group(label: str, dirty_chop: Any = False) -> tuple[str, str]:
    normalized = normalize_token(label)
    if normalized == "GOOD_FAST_REACTION":
        return "GOOD_FAST_REACTION", "AUTOMATIC_LABEL_GOOD_FAST_REACTION"
    if normalized == "FAST_SL_20":
        return "FAST_FAILURE", "AUTOMATIC_LABEL_FAST_SL_20_MAPPED_TO_FAST_FAILURE"
    if normalized in {"GOOD_REACTION_BUT_DIRTY_ACCUMULATION", "GOOD_SLOW_REACTION", "MFE_GOOD_BUT_BE_REQUIRED", "NO_REACTION"}:
        if parse_bool(dirty_chop):
            return "CHOP_AFTER_ENTRY", f"AUTOMATIC_LABEL_{normalized}_WITH_DIRTY_CHOP"
        return "MIXED_REACTION", f"AUTOMATIC_LABEL_{normalized}_MAPPED_TO_MIXED_REACTION"
    return "EXCLUDED", f"UNSUPPORTED_OUTCOME_LABEL:{normalized}"


def direction_confidence_value(value: Any) -> int:
    text = normalize_token(value)
    if text in {"HIGH", "3"}:
        return 3
    if text in {"MEDIUM", "LOW", "2"}:
        return 2
    return 0


def allowed_sample_source(source: str) -> bool:
    text = normalize_token(source)
    return text in {
        "EXISTING_EXPANDED_OBJECTIVE_REPLAY",
        "EXISTING_EXPANDED_VISUAL_PACK",
        "EXISTING_HISTORICAL_CANDIDATE_METADATA",
        "FUTURE_PAPER_SAMPLE_EXISTING_REPORT",
    }


def window(frame: pd.DataFrame, start: pd.Timestamp | None, end: pd.Timestamp) -> pd.DataFrame:
    if frame.empty:
        return frame
    mask = frame["time"] < end
    if start is not None:
        mask &= frame["time"] >= start
    return frame.loc[mask].copy()


def pips(distance: float | None, pip_size: float) -> float | None:
    if distance is None:
        return None
    return float(distance) / pip_size if pip_size > 0 else None


def fvg_ifvg_near_20p(frames: Mapping[str, pd.DataFrame], decision_ts: pd.Timestamp, entry_price: float, pip_size: float) -> dict[str, Any]:
    m5 = frames.get("M5", pd.DataFrame())
    pre = window(m5, decision_ts - pd.Timedelta(hours=6), decision_ts)
    out: dict[str, Any] = {
        "fvg_ifvg_near_20p": False,
        "nearest_fvg_ifvg_distance_pips": "",
        "nearest_fvg_ifvg_zone_type": "",
        "nearest_fvg_ifvg_zone_low": "",
        "nearest_fvg_ifvg_zone_high": "",
    }
    if len(pre) < 3:
        return out
    zones: list[dict[str, Any]] = []
    rows = list(pre.reset_index(drop=True).itertuples(index=False))
    for i in range(len(rows) - 2):
        c1, _, c3 = rows[i], rows[i + 1], rows[i + 2]
        high1, low1, high3, low3 = float(c1.high), float(c1.low), float(c3.high), float(c3.low)
        if low3 > high1:
            zones.append({"type": "FVG_BULLISH", "low": high1, "high": low3})
        elif high3 < low1:
            zones.append({"type": "FVG_BEARISH", "low": high3, "high": low1})
    if not zones:
        return out

    def distance(zone: Mapping[str, Any]) -> float:
        low = float(zone["low"])
        high = float(zone["high"])
        if low <= entry_price <= high:
            return 0.0
        return min(abs(entry_price - low), abs(entry_price - high))

    nearest = min(zones, key=distance)
    distance_pips = pips(distance(nearest), pip_size)
    out.update(
        {
            "fvg_ifvg_near_20p": bool(distance_pips is not None and distance_pips <= 20),
            "nearest_fvg_ifvg_distance_pips": round(distance_pips, 6) if distance_pips is not None else "",
            "nearest_fvg_ifvg_zone_type": nearest["type"],
            "nearest_fvg_ifvg_zone_low": round(float(nearest["low"]), 6),
            "nearest_fvg_ifvg_zone_high": round(float(nearest["high"]), 6),
        }
    )
    return out


def recent_liquidity_features(frames: Mapping[str, pd.DataFrame], decision_ts: pd.Timestamp, entry_price: float, pip_size: float) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    specs = [("H1", 24 * 60), ("M15", 6 * 60), ("M5", 2 * 60)]
    for tf, minutes in specs:
        frame = frames.get(tf, pd.DataFrame())
        pre = window(frame, decision_ts - pd.Timedelta(minutes=minutes), decision_ts)
        if pre.empty:
            continue
        for kind, level in (("RECENT_HIGH", float(pre["high"].max())), ("RECENT_LOW", float(pre["low"].min()))):
            distance_pips = pips(abs(entry_price - level), pip_size)
            candidates.append(
                {
                    "timeframe": tf,
                    "kind": kind,
                    "level": level,
                    "distance_pips": distance_pips,
                }
            )
    out: dict[str, Any] = {
        "liquidity_htf_recent_level": False,
        "nearest_liquidity_type_timeframe": "",
        "nearest_liquidity_level": "",
        "nearest_liquidity_distance_pips": "",
    }
    if not candidates:
        return out
    nearest = min(candidates, key=lambda item: float(item["distance_pips"]) if item["distance_pips"] is not None else float("inf"))
    out.update(
        {
            "liquidity_htf_recent_level": nearest["timeframe"] in {"H1", "M15"},
            "nearest_liquidity_type_timeframe": f"{nearest['timeframe']}_{nearest['kind']}",
            "nearest_liquidity_level": round(float(nearest["level"]), 6),
            "nearest_liquidity_distance_pips": round(float(nearest["distance_pips"]), 6) if nearest["distance_pips"] is not None else "",
        }
    )
    return out


def m1_secondary_features(frames: Mapping[str, pd.DataFrame], decision_ts: pd.Timestamp) -> dict[str, Any]:
    m1 = frames.get("M1", pd.DataFrame())
    pre = window(m1, None, decision_ts)
    out = {
        "m1_large_body_ge_0_60": False,
        "m1_close_high_ge_0_70": False,
        "m1_body_ratio": "",
        "m1_close_location": "",
    }
    if pre.empty:
        return out
    last = pre.iloc[-1]
    high = float(last["high"])
    low = float(last["low"])
    rng = high - low
    if rng <= 0:
        return out
    body_ratio = abs(float(last["close"]) - float(last["open"])) / rng
    close_location = (float(last["close"]) - low) / rng
    out.update(
        {
            "m1_large_body_ge_0_60": body_ratio >= 0.60,
            "m1_close_high_ge_0_70": close_location >= 0.70,
            "m1_body_ratio": round(body_ratio, 6),
            "m1_close_location": round(close_location, 6),
        }
    )
    return out


def load_visual_metadata(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    return {row.get("sample_id", ""): row for row in read_csv_rows(path) if row.get("sample_id")}


def collect_inventory(config: ExpandedDiagnosticConfig) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    replay_path = config.expanded_replay_dir / "objective_outcome_replay.csv"
    visual = load_visual_metadata(config.expanded_visual_dir / "manual_labels_template.csv")
    frames = normalize_frames(load_csv_timeframes(config.symbol, ["M1", "M5", "M15", "H1"], data_dir=str(config.data_dir)))
    inventory: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen: set[str] = set()

    for replay_row in read_csv_rows(replay_path):
        if replay_row.get("row_type") != "CANDIDATE":
            continue
        sample_id = replay_row.get("sample_id", "")
        if sample_id in seen:
            excluded.append({"sample_id": sample_id, "exclude_reason": "DUPLICATE_SAMPLE_ID"})
            continue
        seen.add(sample_id)
        visual_row = visual.get(sample_id, {})
        symbol = replay_row.get("symbol", config.symbol)
        decision_ts = parse_ts(replay_row.get("anchor_timestamp"))
        entry_price = parse_float(replay_row.get("entry_price"))
        direction = normalize_token(replay_row.get("direction_guess"))
        source = "EXISTING_EXPANDED_OBJECTIVE_REPLAY"
        mapped_group, mapping_reason = outcome_group(replay_row.get("automatic_outcome_label", ""), replay_row.get("dirty_chop_after_entry"))
        base = {
            "sample_id": sample_id,
            "symbol": symbol,
            "candidate_id": sample_id,
            "decision_timestamp": replay_row.get("anchor_timestamp", ""),
            "direction": direction,
            "direction_source": replay_row.get("direction_source_timeframe", ""),
            "direction_confidence": direction_confidence_value(replay_row.get("direction_confidence")),
            "direction_rule_version": DIRECTION_RULE_VERSION,
            "pre_entry_only": True,
            "used_post_entry_data_for_direction": False,
            "diagnostic_outcome_group": mapped_group,
            "diagnostic_outcome_mapping_reason": mapping_reason,
            "sample_source": source,
            "candidate_source": visual_row.get("candidate_source_type", replay_row.get("entry_level_source", "")),
            "session": replay_row.get("session", visual_row.get("session", "")),
            "hour": decision_ts.hour if decision_ts is not None else "",
            "date": str(decision_ts.date()) if decision_ts is not None else "",
            "entry_price": entry_price if entry_price is not None else "",
            "visual_html_path": replay_row.get("visual_html_path", visual_row.get("html_path", "")),
        }
        reasons = []
        if symbol != config.symbol:
            reasons.append("NON_XAUUSD_SYMBOL")
        if mapped_group == "EXCLUDED":
            reasons.append(mapping_reason)
        if direction not in {"LONG", "SHORT"}:
            reasons.append("UNKNOWN_DIRECTION")
        if int(base["direction_confidence"]) <= 0:
            reasons.append("UNKNOWN_DIRECTION_CONFIDENCE")
        if decision_ts is None:
            reasons.append("MISSING_DECISION_TIMESTAMP")
        if entry_price is None:
            reasons.append("MISSING_ENTRY_PRICE")
        if not allowed_sample_source(source):
            reasons.append("DISALLOWED_SAMPLE_SOURCE")
        if reasons:
            excluded.append({**base, "exclude_reason": "|".join(reasons)})
            continue
        features = {}
        assert decision_ts is not None
        assert entry_price is not None
        features.update(fvg_ifvg_near_20p(frames, decision_ts, entry_price, config.pip_size))
        features.update(recent_liquidity_features(frames, decision_ts, entry_price, config.pip_size))
        features.update(m1_secondary_features(frames, decision_ts))
        inventory.append({**base, **features})
    return inventory, excluded, {"ohlc_timeframes_loaded": sum(1 for tf in ("M1", "M5", "M15", "H1") if tf in frames and not frames[tf].empty)}


def group_counts(rows: Sequence[Mapping[str, Any]]) -> Counter[str]:
    return Counter(str(row.get("diagnostic_outcome_group", "")) for row in rows)


def summarize_feature(rows: Sequence[Mapping[str, Any]], feature_name: str, expected_direction: str, subset_name: str = "pooled") -> dict[str, Any]:
    good = [row for row in rows if row.get("diagnostic_outcome_group") == "GOOD_FAST_REACTION"]
    fast = [row for row in rows if row.get("diagnostic_outcome_group") == "FAST_FAILURE"]
    good_present = sum(1 for row in good if parse_bool(row.get(feature_name)))
    fast_present = sum(1 for row in fast if parse_bool(row.get(feature_name)))
    good_rate = rate(good_present, len(good))
    fast_rate = rate(fast_present, len(fast))
    diff = round(good_rate - fast_rate, 6)
    repeats = diff < 0 if expected_direction == "FAST_FAILURE_MORE_FREQUENT" else diff > 0
    return {
        "subset": subset_name,
        "feature_name": feature_name,
        "expected_repeat_direction": expected_direction,
        "good_fast_reaction_n": len(good),
        "fast_failure_n": len(fast),
        "good_fast_reaction_present": good_present,
        "fast_failure_present": fast_present,
        "good_fast_reaction_rate": good_rate,
        "fast_failure_rate": fast_rate,
        "difference_good_minus_fast": diff,
        "effect_repeats_prior_direction": repeats,
        "phase_4_blocked": True,
        "interpretation": "descriptive_only_post_hoc_hypothesis_test",
    }


def h1_h2_results(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        summarize_feature(rows, "fvg_ifvg_near_20p", "FAST_FAILURE_MORE_FREQUENT"),
        summarize_feature(rows, "liquidity_htf_recent_level", "GOOD_FAST_REACTION_MORE_FREQUENT"),
    ]


def secondary_results(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        summarize_feature(rows, feature, "SECONDARY_TRACKED_ONLY")
        for feature in SECONDARY_FEATURES
    ]


def confidence_results(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for confidence in (3, 2):
        subset = [row for row in rows if int(row.get("direction_confidence", 0)) == confidence]
        for row in h1_h2_results(subset):
            row = dict(row)
            row["direction_confidence"] = confidence
            row["direction_source_scope"] = "confidence_3_only" if confidence == 3 else "confidence_2_only_caution"
            row["confidence_caution"] = (
                "confidence 3 original/high-confidence directions"
                if confidence == 3
                else "confidence 2/inferred directions are weak/research-only and cannot unlock Phase 4"
            )
            out.append(row)
    return out


def minimum_n_report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = group_counts(rows)
    total = len(rows)
    good = counts.get("GOOD_FAST_REACTION", 0)
    fast = counts.get("FAST_FAILURE", 0)
    return {
        "total_samples": total,
        "good_fast_reaction_n": good,
        "fast_failure_n": fast,
        "mixed_reaction_n": counts.get("MIXED_REACTION", 0),
        "chop_after_entry_n": counts.get("CHOP_AFTER_ENTRY", 0),
        "target_total_samples": 80,
        "hard_minimum_total_samples": 60,
        "target_good_fast_reaction_n": 20,
        "hard_minimum_good_fast_reaction_n": 11,
        "target_fast_failure_n": 40,
        "hard_minimum_fast_failure_n": 25,
        "total_hard_minimum_met": total >= 60,
        "good_hard_minimum_met": good >= 11,
        "fast_hard_minimum_met": fast >= 25,
        "all_hard_minimums_met": total >= 60 and good >= 11 and fast >= 25,
        "targets_met": total >= 80 and good >= 20 and fast >= 40,
        "good_lte_10_gate_active": good <= 10,
        "phase_4_blocked": True,
    }


def leakage_check(feature_names: Iterable[str], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    found = sorted({name for name in feature_names if any(token in name.lower() for token in FORBIDDEN_FEATURE_TOKENS)})
    manual_sources = sorted(
        {
            str(row.get("sample_source", ""))
            for row in rows
            if "MANUAL" in normalize_token(row.get("sample_source"))
            or "CHERRY" in normalize_token(row.get("sample_source"))
        }
    )
    return {
        "forbidden_fields_checked": list(FORBIDDEN_FEATURE_TOKENS),
        "forbidden_fields_found": found,
        "post_entry_feature_usage_detected": bool(found),
        "post_entry_candles_used_for_h1_h2": False,
        "outcome_derived_thresholds_used": False,
        "non_directional_max_move_replay_used_as_feature_evidence": False,
        "manual_cherry_pick_sources_found": manual_sources,
        "phase_4_or_matched_control_logic_used": False,
        "leakage_passed": not found and not manual_sources,
    }


def final_verdict(minimums: Mapping[str, Any], feature_rows: Sequence[Mapping[str, Any]], confidence_rows: Sequence[Mapping[str, Any]], leakage: Mapping[str, Any]) -> tuple[str, str]:
    if not leakage.get("leakage_passed"):
        return "LEAKAGE_DETECTED_REJECT", "Leakage check failed; Phase 4 blocked."
    if minimums.get("good_lte_10_gate_active"):
        return "MIXED_AMBIGUOUS_SMALL_N", "GOOD_FAST_REACTION N <= 10 keeps prior cap active."
    if not minimums.get("all_hard_minimums_met"):
        return "MINIMUM_N_NOT_MET", "Expanded hard minimum-N gates were not met."
    h1 = next(row for row in feature_rows if row["feature_name"] == "fvg_ifvg_near_20p")
    h2 = next(row for row in feature_rows if row["feature_name"] == "liquidity_htf_recent_level")
    if h1["effect_repeats_prior_direction"] and h2["effect_repeats_prior_direction"]:
        c3 = [row for row in confidence_rows if row.get("direction_confidence") == 3]
        c3_h1 = next(row for row in c3 if row["feature_name"] == "fvg_ifvg_near_20p")
        c3_h2 = next(row for row in c3 if row["feature_name"] == "liquidity_htf_recent_level")
        if c3_h1["effect_repeats_prior_direction"] or c3_h2["effect_repeats_prior_direction"]:
            return "EXPANDED_HYPOTHESES_REPEAT_WITH_SUFFICIENT_N", "H1/H2 repeat with hard minimum-N met; next action is bounded confirmatory diagnostic only."
        return "CONFIDENCE_2_ONLY_SIGNAL", "H1/H2 repeat pooled but confidence-3 sensitivity does not support the same pattern."
    return "HYPOTHESES_FAIL_TO_REPEAT", "At least one frozen primary hypothesis failed to repeat directionally."


def review_priority(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        score = 0
        reasons = []
        if row.get("diagnostic_outcome_group") in SECONDARY_GROUPS:
            score += 2
            reasons.append("SECONDARY_GROUP_REVIEW_ONLY")
        if int(row.get("direction_confidence", 0)) == 2:
            score += 2
            reasons.append("CONFIDENCE_2_DIRECTION_CAUTION")
        if row.get("diagnostic_outcome_group") == "GOOD_FAST_REACTION" and parse_bool(row.get("fvg_ifvg_near_20p")):
            score += 2
            reasons.append("GOOD_WITH_H1_FAILURE_MARKER_PRESENT")
        if row.get("diagnostic_outcome_group") == "FAST_FAILURE" and parse_bool(row.get("liquidity_htf_recent_level")):
            score += 2
            reasons.append("FAST_WITH_H2_SUCCESS_MARKER_PRESENT")
        if not reasons:
            reasons.append("LOW_PRIORITY_BASELINE")
        out.append(
            {
                "sample_id": row.get("sample_id"),
                "priority_score": score,
                "priority_reasons": "|".join(reasons),
                "diagnostic_outcome_group": row.get("diagnostic_outcome_group"),
                "direction_confidence": row.get("direction_confidence"),
                "sample_source": row.get("sample_source"),
                "visual_html_path": row.get("visual_html_path"),
            }
        )
    return sorted(out, key=lambda item: (-int(item["priority_score"]), str(item["sample_id"])))


def run_execution(config: ExpandedDiagnosticConfig) -> dict[str, Any]:
    out = config.output_dir
    out.mkdir(parents=True, exist_ok=True)
    run_started_at = utc_now()
    plan_valid, plan_validation = validate_signed_plan(config)
    if not plan_valid:
        summary = {
            "run_started_at": run_started_at,
            "run_finished_at": utc_now(),
            "execution_valid": False,
            "final_verdict": "EXECUTION_INVALID",
            "plan_validation": plan_validation,
            "comparison_executed": False,
            "phase_4_blocked": True,
        }
        write_json(out / "execution_summary.json", summary)
        return summary

    inventory, excluded, frame_info = collect_inventory(config)
    primary_rows = [row for row in inventory if row["diagnostic_outcome_group"] in PRIMARY_GROUPS]
    h_rows = h1_h2_results(primary_rows)
    secondary = secondary_results(primary_rows)
    confidence = confidence_results(primary_rows)
    min_report = minimum_n_report(inventory)
    leak = leakage_check([*PRIMARY_HYPOTHESES, *SECONDARY_FEATURES], inventory)
    verdict, verdict_reason = final_verdict(min_report, h_rows, confidence, leak)
    confidence_counts = Counter(str(row.get("direction_confidence", "")) for row in inventory)
    group_count_map = dict(group_counts(inventory))
    sample_sources = sorted({str(row.get("sample_source", "")) for row in inventory})

    verdict_payload = {
        "final_verdict": verdict,
        "verdict_reason": verdict_reason,
        "phase_4_blocked": True,
        "allowed_next_action": (
            "bounded_confirmatory_diagnostic_only"
            if verdict == "EXPANDED_HYPOTHESES_REPEAT_WITH_SUFFICIENT_N"
            else "review_results_and_keep_phase_4_blocked"
        ),
        "matched_control_replay_run": False,
        "runtime_logic_modified": False,
        "live_trading_enabled": False,
        "orders_enabled": False,
        "telegram_enabled": False,
        "broker_execution_enabled": False,
        "profitability_claim_made": False,
        "edge_claim_made": False,
        "deployability_claim_made": False,
        "verdict_flags": [
            "EXPANDED_SAMPLE_DIAGNOSTIC_EXECUTED",
            "POST_HOC_HYPOTHESES_TESTED_NOT_VALIDATED",
            "PHASE_4_STILL_BLOCKED",
            "NO_MATCHED_CONTROL_REPLAY",
            "NO_LIVE_DEPLOYMENT_DECISION",
            "NO_PROFITABILITY_CLAIM",
            "ADELIN_REMAINS_RESEARCH_ONLY",
        ],
    }
    summary = {
        "run_started_at": run_started_at,
        "run_finished_at": utc_now(),
        "plan_version": PLAN_VERSION,
        "signoff_verified": True,
        "post_hoc_disclosure_verified": True,
        "plan_validation": plan_validation,
        "sample_sources_used": sample_sources,
        "samples_collected_or_selected": len(inventory),
        "excluded_sample_count": len(excluded),
        "group_counts": group_count_map,
        "good_fast_reaction_n": group_count_map.get("GOOD_FAST_REACTION", 0),
        "fast_failure_n": group_count_map.get("FAST_FAILURE", 0),
        "mixed_reaction_n": group_count_map.get("MIXED_REACTION", 0),
        "chop_after_entry_n": group_count_map.get("CHOP_AFTER_ENTRY", 0),
        "confidence_counts": dict(confidence_counts),
        "minimum_n_gate_status": min_report,
        "h1_result": next(row for row in h_rows if row["feature_name"] == "fvg_ifvg_near_20p"),
        "h2_result": next(row for row in h_rows if row["feature_name"] == "liquidity_htf_recent_level"),
        "secondary_tracked_feature_summary": secondary,
        "confidence_3_sensitivity": [row for row in confidence if row.get("direction_confidence") == 3],
        "confidence_2_caution": [row for row in confidence if row.get("direction_confidence") == 2],
        "leakage_check": leak,
        "ohlc_read": True,
        "ohlc_timeframes_loaded": frame_info["ohlc_timeframes_loaded"],
        "pre_entry_only_feature_extraction": True,
        "post_entry_candles_used_for_h1_h2": False,
        "replay_run": False,
        "matched_control_replay_run": False,
        "candidate_generation_run": False,
        "final_verdict": verdict,
        "verdict_reason": verdict_reason,
        "phase_4_blocked": True,
        "safety": {
            "runtime_logic_modified": False,
            "strategy_2_touched": False,
            "strategy_3_touched": False,
            "live_trading_enabled": False,
            "orders_enabled": False,
            "telegram_enabled": False,
            "broker_execution_enabled": False,
            "v3_stash_applied_or_popped": False,
            "matched_control_replay_run": False,
        },
    }

    write_csv(out / "expanded_sample_inventory.csv", inventory)
    write_json(out / "expanded_sample_inventory.json", inventory)
    write_json(out / "expanded_sample_summary.json", {k: summary[k] for k in ("sample_sources_used", "samples_collected_or_selected", "excluded_sample_count", "group_counts", "confidence_counts")})
    write_csv(out / "h1_h2_feature_results.csv", h_rows)
    write_json(out / "h1_h2_feature_results.json", h_rows)
    write_csv(out / "confidence_stratification_summary.csv", confidence)
    write_json(out / "confidence_stratification_summary.json", confidence)
    write_json(out / "minimum_n_gate_report.json", min_report)
    write_json(out / "leakage_check_report.json", leak)
    write_csv(out / "excluded_samples.csv", excluded)
    write_csv(out / "human_review_priority.csv", review_priority(inventory))
    write_json(out / "verdict.json", verdict_payload)
    write_json(out / "execution_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--plan-dir", type=Path, default=PLAN_DIR)
    parser.add_argument("--signoff-path", type=Path, default=SIGNOFF_PATH)
    parser.add_argument("--expanded-replay-dir", type=Path, default=EXPANDED_REPLAY_DIR)
    parser.add_argument("--expanded-visual-dir", type=Path, default=EXPANDED_VISUAL_DIR)
    parser.add_argument("--direction-recovery-dir", type=Path, default=DIRECTION_RECOVERY_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_execution(
        ExpandedDiagnosticConfig(
            symbol=args.symbol,
            data_dir=args.data_dir,
            plan_dir=args.plan_dir,
            signoff_path=args.signoff_path,
            expanded_replay_dir=args.expanded_replay_dir,
            expanded_visual_dir=args.expanded_visual_dir,
            direction_recovery_dir=args.direction_recovery_dir,
            output_dir=args.output_dir,
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("final_verdict") != "EXECUTION_INVALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
