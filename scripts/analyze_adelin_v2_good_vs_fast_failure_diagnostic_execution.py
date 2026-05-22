"""Run the bounded Adelin v2 GOOD_FAST_REACTION vs FAST_FAILURE diagnostic.

This execution is descriptive only. It validates the signed pre-registered plan,
uses already generated pre-entry diagnostic rows, compares allowed pre-entry
feature frequencies by group, and applies the strict minimum-N gate. It does not
run matched-control replay, modify runtime logic, create scoring, or read OHLC.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


PLAN_DIR = Path("backtests/reports/adelin_v2_good_vs_fast_failure_diagnostic_plan")
SIGNOFF_PATH = Path("docs/research/adelin_v2_good_vs_fast_failure_diagnostic_plan_signoff.md")
DIRECTION_RECOVERY_DIR = Path("backtests/reports/adelin_v2_direction_metadata_recovery")
DIAGNOSTICS_DIR = Path("backtests/reports/adelin_v2_preentry_outcome_diagnostics_direction_recovered")
DEFAULT_OUTPUT_DIR = Path("backtests/reports/adelin_v2_good_vs_fast_failure_diagnostic_execution")

PRIMARY_GROUPS = ("GOOD_FAST_REACTION", "FAST_FAILURE")
SECONDARY_GROUPS = ("MIXED_REACTION", "CHOP_AFTER_ENTRY")
FINAL_VERDICT = "MIXED_AMBIGUOUS_SMALL_N"
PLAN_VERSION = "adelin_v2_good_vs_fast_failure_diagnostic_execution_v1"

FORBIDDEN_FEATURE_TOKENS = (
    "tp hit",
    "sl hit",
    "pnl",
    "r_multiple",
    "future mfe",
    "future mae",
    "post-entry candles",
    "future liquidity behavior",
    "outcome-derived thresholds",
    "feature thresholds selected after looking at good vs fast separation",
    "non-directional max move replay as primary evidence",
)


@dataclass(frozen=True)
class ExecutionConfig:
    plan_dir: Path = PLAN_DIR
    signoff_path: Path = SIGNOFF_PATH
    diagnostics_dir: Path = DIAGNOSTICS_DIR
    direction_recovery_dir: Path = DIRECTION_RECOVERY_DIR
    output_dir: Path = DEFAULT_OUTPUT_DIR


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
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


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"true", "1", "yes", "y"}


def parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_token(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "_")


def rate(count: int, n: int) -> float:
    return round(count / n, 6) if n else 0.0


def direction_confidence(row: Mapping[str, Any]) -> int:
    try:
        return int(float(row.get("direction_recovery_confidence") or 0))
    except (TypeError, ValueError):
        return 0


def sweep_type(row: Mapping[str, Any]) -> str:
    reason = str(row.get("direction_recovery_reason", "")).upper()
    source = normalize_token(row.get("direction_recovery_source"))
    if source != "PRE_DECISION_SWEEP_INFERENCE":
        return source or "UNKNOWN"
    for marker in (
        "M1_DOWNWARD_SWEEP",
        "M1_UPWARD_SWEEP",
        "M5_DOWNWARD_SWEEP",
        "M5_UPWARD_SWEEP",
    ):
        if marker in reason:
            return marker
    return "PRE_DECISION_SWEEP_INFERENCE_UNKNOWN_TF"


def ge(value: Any, threshold: float) -> bool:
    parsed = parse_float(value)
    return parsed is not None and parsed >= threshold


def le(value: Any, threshold: float) -> bool:
    parsed = parse_float(value)
    return parsed is not None and parsed <= threshold


def pre_entry_feature_flags(row: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    session = normalize_token(row.get("session"))
    vol = normalize_token(row.get("volatility_range_context"))
    band = normalize_token(row.get("tight_numeric_level_touch_band"))
    source = normalize_token(row.get("direction_recovery_source"))
    confidence = direction_confidence(row)
    sweep = sweep_type(row)
    fvg_distance = parse_float(row.get("nearest_fvg_ifvg_distance_pips"))
    target_space = parse_float(row.get("target_space_proxy_pips"))
    liquidity_type = normalize_token(row.get("liquidity_type_timeframe"))

    features: dict[str, tuple[str, bool]] = {
        "numeric_level_confluence_20p": ("numeric_level_confluence", parse_bool(row.get("numeric_level_confluence_20p"))),
        "round_band_0_10p": ("round_level_proximity", band == "0-10_PIPS"),
        "round_band_10_20p": ("round_level_proximity", band == "10-20_PIPS"),
        "round_band_gt_20p": ("round_level_proximity", band == "GT_20_PIPS"),
        "pre_decision_sweep_inferred": ("pre_decision_sweep_type", source == "PRE_DECISION_SWEEP_INFERENCE"),
        "pre_decision_m1_downward_sweep": ("pre_decision_sweep_type", sweep == "M1_DOWNWARD_SWEEP"),
        "pre_decision_m1_upward_sweep": ("pre_decision_sweep_type", sweep == "M1_UPWARD_SWEEP"),
        "m1_large_body_ge_0_60": ("m1_candle_anatomy_before_decision", ge(row.get("m1_body_ratio"), 0.60)),
        "m1_upper_wick_ge_0_50": ("m1_candle_anatomy_before_decision", ge(row.get("m1_upper_wick_ratio"), 0.50)),
        "m1_lower_wick_ge_0_50": ("m1_candle_anatomy_before_decision", ge(row.get("m1_lower_wick_ratio"), 0.50)),
        "m1_close_high_ge_0_70": ("m1_candle_anatomy_before_decision", ge(row.get("m1_close_location"), 0.70)),
        "m1_close_low_le_0_30": ("m1_candle_anatomy_before_decision", le(row.get("m1_close_location"), 0.30)),
        "m5_large_body_ge_0_60": ("m5_candle_anatomy_before_decision", ge(row.get("m5_body_ratio"), 0.60)),
        "m5_upper_wick_ge_0_50": ("m5_candle_anatomy_before_decision", ge(row.get("m5_upper_wick_ratio"), 0.50)),
        "m5_lower_wick_ge_0_50": ("m5_candle_anatomy_before_decision", ge(row.get("m5_lower_wick_ratio"), 0.50)),
        "m5_close_high_ge_0_70": ("m5_candle_anatomy_before_decision", ge(row.get("m5_close_location"), 0.70)),
        "m5_close_low_le_0_30": ("m5_candle_anatomy_before_decision", le(row.get("m5_close_location"), 0.30)),
        "m15_large_body_ge_0_50": ("m15_context_before_decision", ge(row.get("m15_body_ratio"), 0.50)),
        "m15_close_high_ge_0_70": ("m15_context_before_decision", ge(row.get("m15_close_location"), 0.70)),
        "m15_close_low_le_0_30": ("m15_context_before_decision", le(row.get("m15_close_location"), 0.30)),
        "wick_body_m1_wick_dominant": (
            "wick_body_proxy_before_decision",
            ge(row.get("m1_upper_wick_ratio"), 0.50) or ge(row.get("m1_lower_wick_ratio"), 0.50),
        ),
        "wick_body_m5_wick_dominant": (
            "wick_body_proxy_before_decision",
            ge(row.get("m5_upper_wick_ratio"), 0.50) or ge(row.get("m5_lower_wick_ratio"), 0.50),
        ),
        "compression_overlap_proxy": ("compression_overlap_proxy_before_decision", parse_bool(row.get("compression_overlap_proxy"))),
        "expansion_before_decision_proxy": (
            "compression_overlap_proxy_before_decision",
            parse_bool(row.get("expansion_before_decision_proxy")),
        ),
        "fvg_ifvg_available": ("fvg_ifvg_proximity_pre_entry", parse_bool(row.get("fvg_ifvg_proximity_available"))),
        "fvg_ifvg_near_20p": ("fvg_ifvg_proximity_pre_entry", fvg_distance is not None and fvg_distance <= 20),
        "premium_session_open": ("session_hour", session in {"ASIA_OPEN", "LONDON_OPEN", "NEW_YORK_OPEN"}),
        "session_new_york": ("session_hour", session in {"NEW_YORK", "NEW_YORK_OPEN"}),
        "session_london": ("session_hour", session in {"LONDON", "LONDON_OPEN"}),
        "high_volatility_context": ("volatility_range_context_before_decision", vol == "HIGH"),
        "mid_volatility_context": ("volatility_range_context_before_decision", vol == "MID"),
        "clean_target_space_proxy": ("target_space_proxy_at_decision", target_space is not None and target_space >= 100),
        "liquidity_htf_recent_level": ("target_space_proxy_at_decision", liquidity_type.startswith(("H1_", "M15_"))),
        "direction_confidence_3": ("direction_confidence_stratum", confidence == 3),
        "direction_confidence_2": ("direction_confidence_stratum", confidence == 2),
        "direction_source_existing_metadata": ("direction_source_stratum", source == "EXISTING_METADATA"),
        "direction_source_pre_decision_sweep": ("direction_source_stratum", source == "PRE_DECISION_SWEEP_INFERENCE"),
    }
    return {
        name: {"feature_family": family, "present": present}
        for name, (family, present) in features.items()
    }


def load_rows(path: Path) -> list[dict[str, Any]]:
    return list(load_json(path))


def validate_plan(config: ExecutionConfig) -> tuple[bool, dict[str, Any]]:
    signoff_exists = config.signoff_path.exists()
    signoff_text = config.signoff_path.read_text(encoding="utf-8") if signoff_exists else ""
    signoff_approved = "Decision: APPROVE" in signoff_text

    required_plan_files = {
        "diagnostic_plan": config.plan_dir / "diagnostic_plan.json",
        "allowed_features": config.plan_dir / "allowed_features.json",
        "excluded_features": config.plan_dir / "excluded_features.json",
        "comparison_schema": config.plan_dir / "comparison_schema.json",
        "decision_matrix": config.plan_dir / "decision_matrix.json",
        "summary": config.plan_dir / "summary.json",
    }
    files_exist = {name: path.exists() for name, path in required_plan_files.items()}
    decision_matrix = load_json(required_plan_files["decision_matrix"]) if files_exist["decision_matrix"] else {}
    gate = decision_matrix.get("minimum_n_thresholds", {})

    result = {
        "signoff_exists": signoff_exists,
        "signoff_decision_approve": signoff_approved,
        "required_plan_files_exist": files_exist,
        "minimum_n_gate_exists": bool(gate),
        "gate_tripped": gate.get("gate_tripped") is True,
        "strong_descriptive_separation_forbidden": gate.get("strong_descriptive_separation_forbidden") is True,
        "strongest_allowed_verdict": gate.get("strongest_allowed_verdict", ""),
        "phase_4_blocked": decision_matrix.get("phase_4_blocked") is True and gate.get("phase_4_blocked") is True,
    }
    result["plan_valid"] = (
        result["signoff_exists"]
        and result["signoff_decision_approve"]
        and all(files_exist.values())
        and result["minimum_n_gate_exists"]
        and result["gate_tripped"]
        and result["strong_descriptive_separation_forbidden"]
        and result["strongest_allowed_verdict"] == FINAL_VERDICT
        and result["phase_4_blocked"]
    )
    result["decision_matrix"] = decision_matrix
    return bool(result["plan_valid"]), result


def leakage_check(feature_names: Iterable[str], excluded_features: Mapping[str, Any]) -> dict[str, Any]:
    forbidden_from_plan = [str(item.get("name", "")) for item in excluded_features.get("excluded_features", [])]
    tokens = tuple(token.lower() for token in FORBIDDEN_FEATURE_TOKENS)
    found = []
    for feature in feature_names:
        lower = feature.lower()
        if any(token in lower for token in tokens):
            found.append(feature)
    return {
        "forbidden_fields_checked": forbidden_from_plan,
        "forbidden_feature_tokens_checked": list(tokens),
        "forbidden_fields_found": sorted(set(found)),
        "post_entry_feature_usage_detected": bool(found),
        "post_entry_candles_used": False,
        "non_directional_max_move_replay_used_as_primary": False,
        "leakage_passed": not found,
    }


def group_counts(rows: Sequence[Mapping[str, Any]]) -> Counter[str]:
    return Counter(str(row.get("final_diagnostic_outcome", "")) for row in rows)


def summarize_frequency(rows: Sequence[Mapping[str, Any]], feature_names: Sequence[str]) -> list[dict[str, Any]]:
    grouped = {group: [row for row in rows if row.get("final_diagnostic_outcome") == group] for group in PRIMARY_GROUPS}
    out: list[dict[str, Any]] = []
    for feature in feature_names:
        family = next(iter(pre_entry_feature_flags(row)[feature]["feature_family"] for row in rows), "")
        for group, group_rows in grouped.items():
            present = sum(1 for row in group_rows if pre_entry_feature_flags(row)[feature]["present"])
            n = len(group_rows)
            out.append(
                {
                    "feature_name": feature,
                    "feature_family": family,
                    "group": group,
                    "group_n": n,
                    "present_count": present,
                    "absent_count": n - present,
                    "present_rate": rate(present, n),
                    "note": "descriptive_only_minimum_n_gate_caps_verdict",
                }
            )
    return out


def differences(rows: Sequence[Mapping[str, Any]], feature_names: Sequence[str]) -> list[dict[str, Any]]:
    good = [row for row in rows if row.get("final_diagnostic_outcome") == "GOOD_FAST_REACTION"]
    fast = [row for row in rows if row.get("final_diagnostic_outcome") == "FAST_FAILURE"]
    out = []
    for feature in feature_names:
        family = next(iter(pre_entry_feature_flags(row)[feature]["feature_family"] for row in rows), "")
        good_present = sum(1 for row in good if pre_entry_feature_flags(row)[feature]["present"])
        fast_present = sum(1 for row in fast if pre_entry_feature_flags(row)[feature]["present"])
        good_rate = rate(good_present, len(good))
        fast_rate = rate(fast_present, len(fast))
        out.append(
            {
                "feature_name": feature,
                "feature_family": family,
                "good_fast_reaction_n": len(good),
                "fast_failure_n": len(fast),
                "good_fast_reaction_present": good_present,
                "fast_failure_present": fast_present,
                "good_fast_reaction_rate": good_rate,
                "fast_failure_rate": fast_rate,
                "difference_good_minus_fast": round(good_rate - fast_rate, 6),
                "interpretation": "directional_descriptive_only_phase_4_blocked",
            }
        )
    return sorted(out, key=lambda item: abs(float(item["difference_good_minus_fast"])), reverse=True)


def confidence_sensitivity(rows: Sequence[Mapping[str, Any]], feature_names: Sequence[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for confidence in (3, 2):
        subset = [row for row in rows if direction_confidence(row) == confidence]
        diff_rows = differences(subset, feature_names) if subset else []
        for row in diff_rows:
            row = dict(row)
            row["direction_confidence"] = confidence
            row["sensitivity_type"] = "confidence_3_only" if confidence == 3 else "confidence_2_only_caution"
            row["caution"] = (
                "mandatory sensitivity; can support only descriptive next step"
                if confidence == 3
                else "confidence 2 inferred directions are weaker; confidence-2-only separation cannot unlock Phase 4"
            )
            out.append(row)
    return out


def comparison_rows(rows: Sequence[Mapping[str, Any]], feature_names: Sequence[str]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        outcome = str(row.get("final_diagnostic_outcome", ""))
        if outcome not in PRIMARY_GROUPS:
            continue
        flags = pre_entry_feature_flags(row)
        present = [feature for feature in feature_names if flags[feature]["present"]]
        out.append(
            {
                "sample_id": row.get("sample_id", ""),
                "final_diagnostic_outcome": outcome,
                "direction": row.get("direction", ""),
                "direction_confidence": direction_confidence(row),
                "direction_source": row.get("direction_recovery_source", ""),
                "feature_count": len(present),
                "present_pre_entry_features": "|".join(present),
                "chart_path": row.get("chart_path", ""),
                "html_path": row.get("html_path", ""),
                "note": "pre_entry_features_only; diagnostic_group_label_used_for_comparison",
            }
        )
    return out


def confidence_2_caution_rows(sensitivity_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in sensitivity_rows:
        if int(row.get("direction_confidence", 0)) != 2:
            continue
        diff = float(row.get("difference_good_minus_fast", 0.0))
        out.append(
            {
                "feature_name": row.get("feature_name", ""),
                "feature_family": row.get("feature_family", ""),
                "confidence_2_good_n": row.get("good_fast_reaction_n", 0),
                "confidence_2_fast_n": row.get("fast_failure_n", 0),
                "difference_good_minus_fast": diff,
                "caution": (
                    "WEAK_RESEARCH_ONLY_CONFIDENCE_2_INFERRED_DIRECTION; "
                    "do_not_use_as_phase_4_gate"
                ),
            }
        )
    return sorted(out, key=lambda item: abs(float(item["difference_good_minus_fast"])), reverse=True)


def priority_rows(rows: Sequence[Mapping[str, Any]], feature_names: Sequence[str]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        flags = pre_entry_feature_flags(row)
        present = [feature for feature in feature_names if flags[feature]["present"]]
        outcome = str(row.get("final_diagnostic_outcome", ""))
        confidence = direction_confidence(row)
        score = 0
        reasons: list[str] = []
        if outcome == "GOOD_FAST_REACTION" and len(present) <= 3:
            score += 3
            reasons.append("GOOD_WITH_FEW_PRE_ENTRY_FEATURES")
        if outcome == "FAST_FAILURE" and len(present) >= 8:
            score += 3
            reasons.append("FAST_FAILURE_LOOKS_FEATURE_RICH")
        if confidence == 2:
            score += 2
            reasons.append("CONFIDENCE_2_DIRECTION_INFERENCE_AFFECTS_INTERPRETATION")
        if outcome in SECONDARY_GROUPS:
            score += 2
            reasons.append("SECONDARY_GROUP_REVIEW_ONLY")
        if not reasons:
            reasons.append("LOW_PRIORITY_BASELINE")
        out.append(
            {
                "sample_id": row.get("sample_id", ""),
                "priority_score": score,
                "priority_reasons": "|".join(reasons),
                "final_diagnostic_outcome": outcome,
                "direction_confidence": confidence,
                "direction_source": row.get("direction_recovery_source", ""),
                "feature_count": len(present),
                "chart_path": row.get("chart_path", ""),
                "html_path": row.get("html_path", ""),
                "review_scope": "human_review_only_not_phase_4",
            }
        )
    return sorted(out, key=lambda item: (-int(item["priority_score"]), str(item["sample_id"])))


def apply_decision_matrix(rows: Sequence[Mapping[str, Any]], plan_validation: Mapping[str, Any]) -> dict[str, Any]:
    counts = group_counts(rows)
    good_n = counts.get("GOOD_FAST_REACTION", 0)
    fast_n = counts.get("FAST_FAILURE", 0)
    gate_active = bool(good_n <= 10 or fast_n <= 10)
    return {
        "final_verdict": FINAL_VERDICT,
        "minimum_n_gate_active": gate_active,
        "good_fast_reaction_n": good_n,
        "fast_failure_n": fast_n,
        "secondary_groups_excluded": list(SECONDARY_GROUPS),
        "secondary_group_counts": {group: counts.get(group, 0) for group in SECONDARY_GROUPS},
        "strongest_allowed_verdict": FINAL_VERDICT if gate_active else plan_validation.get("strongest_allowed_verdict", ""),
        "strong_descriptive_separation_forbidden": gate_active,
        "phase_4_blocked": True,
        "no_confidence_stratum_exception": True,
        "rule_applied": (
            "GOOD_FAST_REACTION N <= 10 triggers the strict minimum-N gate; "
            "the verdict is capped at MIXED_AMBIGUOUS_SMALL_N regardless of observed feature differences."
        ),
        "allowed_next_actions": [
            "more sample collection",
            "bounded confirmatory diagnostic",
            "human review of priority samples",
        ],
        "forbidden_next_actions": [
            "Phase 4 matched-control replay",
            "live trading",
            "scoring or live-entry filtering",
            "profitability claims",
        ],
    }


def run_execution(config: ExecutionConfig) -> dict[str, Any]:
    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    plan_valid, plan_validation = validate_plan(config)
    if not plan_valid:
        failure = {
            "run_started_at": utc_now(),
            "run_finished_at": utc_now(),
            "plan_valid": False,
            "comparison_executed": False,
            "failure_reason": "SIGNED_PLAN_VALIDATION_FAILED",
            "plan_validation": plan_validation,
            "phase_4_blocked": True,
        }
        write_json(output_dir / "execution_summary.json", failure)
        return failure

    excluded = load_json(config.plan_dir / "excluded_features.json")
    rows = load_rows(config.diagnostics_dir / "sample_diagnostics.json")
    primary_rows = [row for row in rows if row.get("final_diagnostic_outcome") in PRIMARY_GROUPS]
    feature_names = sorted(pre_entry_feature_flags(primary_rows[0]).keys()) if primary_rows else []
    leak = leakage_check(feature_names, excluded)

    comparison = comparison_rows(rows, feature_names)
    frequency = summarize_frequency(primary_rows, feature_names)
    diff = differences(primary_rows, feature_names)
    sensitivity = confidence_sensitivity(primary_rows, feature_names)
    confidence2 = confidence_2_caution_rows(sensitivity)
    priority = priority_rows(rows, feature_names)
    decision = apply_decision_matrix(rows, plan_validation)

    top_diffs = diff[:8]
    confidence3_top = [row for row in sensitivity if int(row.get("direction_confidence", 0)) == 3][:8]
    confidence2_top = confidence2[:8]
    counts = group_counts(rows)

    verdict = {
        **decision,
        "comparison_executed": True,
        "matched_control_replay_run": False,
        "runtime_logic_modified": False,
        "live_trading_enabled": False,
        "telegram_enabled": False,
        "broker_execution_enabled": False,
        "profitability_claim_made": False,
        "verdict_flags": [
            "GOOD_VS_FAST_DIAGNOSTIC_EXECUTED",
            "MINIMUM_N_GATE_ACTIVE",
            "VERDICT_CAPPED_AT_MIXED_AMBIGUOUS_SMALL_N",
            "STRONG_DESCRIPTIVE_SEPARATION_FORBIDDEN",
            "PHASE_4_STILL_BLOCKED",
            "DESCRIPTIVE_ONLY",
            "NO_PROFITABILITY_CLAIM",
            "NO_LIVE_DEPLOYMENT_DECISION",
            "NO_MATCHED_CONTROL_REPLAY",
            "ADELIN_REMAINS_RESEARCH_ONLY",
        ],
    }

    summary = {
        "run_started_at": utc_now(),
        "run_finished_at": utc_now(),
        "plan_version": PLAN_VERSION,
        "plan_loaded": True,
        "signoff_verified": True,
        "plan_validation": {key: value for key, value in plan_validation.items() if key != "decision_matrix"},
        "output_dir": str(output_dir),
        "diagnostics_input": str(config.diagnostics_dir / "sample_diagnostics.json"),
        "direction_recovery_input": str(config.direction_recovery_dir),
        "comparison_executed": True,
        "comparison_scope": "bounded_pre_registered_good_vs_fast_failure_only",
        "ohlc_read": False,
        "pre_entry_only": True,
        "post_entry_candles_used": False,
        "matched_control_replay_run": False,
        "candidate_pack_generated": False,
        "phase_4_started": False,
        "total_samples_loaded": len(rows),
        "primary_samples_compared": len(primary_rows),
        "group_counts": dict(counts),
        "good_fast_reaction_n": counts.get("GOOD_FAST_REACTION", 0),
        "fast_failure_n": counts.get("FAST_FAILURE", 0),
        "secondary_groups_excluded": list(SECONDARY_GROUPS),
        "secondary_group_counts": {group: counts.get(group, 0) for group in SECONDARY_GROUPS},
        "feature_count": len(feature_names),
        "top_descriptive_differences": top_diffs,
        "confidence_3_only_sensitivity_top": confidence3_top,
        "confidence_2_caution_top": confidence2_top,
        "leakage_check": leak,
        "final_verdict": FINAL_VERDICT,
        "minimum_n_gate_active": decision["minimum_n_gate_active"],
        "strongest_allowed_verdict": FINAL_VERDICT,
        "strong_descriptive_separation_forbidden": True,
        "phase_4_blocked": True,
        "runtime_logic_modified": False,
        "live_trading_enabled": False,
        "telegram_enabled": False,
        "broker_execution_enabled": False,
        "profitability_claim_made": False,
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
        "verdict_flags": verdict["verdict_flags"],
    }

    write_csv(output_dir / "comparison_results.csv", comparison)
    write_csv(output_dir / "feature_frequency_summary.csv", frequency)
    write_csv(output_dir / "difference_in_proportions.csv", diff)
    write_csv(output_dir / "confidence_sensitivity_summary.csv", sensitivity)
    write_csv(output_dir / "confidence_2_caution_table.csv", confidence2)
    write_csv(output_dir / "human_review_priority.csv", priority)
    write_json(output_dir / "leakage_check_report.json", leak)
    write_json(output_dir / "decision_matrix_applied.json", decision)
    write_json(output_dir / "verdict.json", verdict)
    write_json(output_dir / "execution_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-dir", type=Path, default=PLAN_DIR)
    parser.add_argument("--signoff-path", type=Path, default=SIGNOFF_PATH)
    parser.add_argument("--diagnostics-dir", type=Path, default=DIAGNOSTICS_DIR)
    parser.add_argument("--direction-recovery-dir", type=Path, default=DIRECTION_RECOVERY_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_execution(
        ExecutionConfig(
            plan_dir=args.plan_dir,
            signoff_path=args.signoff_path,
            diagnostics_dir=args.diagnostics_dir,
            direction_recovery_dir=args.direction_recovery_dir,
            output_dir=args.output_dir,
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("comparison_executed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
