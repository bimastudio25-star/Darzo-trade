"""Create the Adelin v2 GOOD_FAST_REACTION vs FAST_FAILURE diagnostic plan.

This script is intentionally plan-only. It writes pre-registered comparison
schemas and governance artifacts, but it does not read OHLC data, inspect
candles, execute replay, or compute feature-vs-outcome statistics.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PLAN_VERSION = "adelin_v2_good_vs_fast_failure_diagnostic_plan_v1"
DEFAULT_OUTPUT_DIR = Path("backtests/reports/adelin_v2_good_vs_fast_failure_diagnostic_plan")

PRIMARY_GROUPS = ["GOOD_FAST_REACTION", "FAST_FAILURE"]
SECONDARY_REVIEW_GROUPS = ["MIXED_REACTION", "CHOP_AFTER_ENTRY"]

PRIOR_VALIDATED_BASELINE_CONTEXT = {
    "total_samples": 40,
    "direction_coverage": "40/40",
    "existing_metadata_direction_count": 21,
    "pre_decision_sweep_inferred_direction_count": 19,
    "post_entry_data_used_for_direction_recovery": 0,
    "direction_inference_rule_version": "adelin_v2_pre_decision_sweep_v1",
    "prior_outcome_counts_context_only": {
        "FAST_FAILURE": 27,
        "GOOD_FAST_REACTION": 10,
        "MIXED_REACTION": 2,
        "CHOP_AFTER_ENTRY": 1,
    },
    "note": (
        "These are prior validated diagnostic context values only. This branch "
        "does not recompute outcomes or produce feature-vs-outcome statistics."
    ),
}

ALLOWED_FEATURES = [
    {
        "feature_family": "numeric_level_confluence",
        "pre_entry_only": True,
        "planned_use": "descriptive candidate-group comparison",
        "allowed_inputs": ["decision timestamp", "entry/reference level available before decision"],
        "leakage_guard": "Do not use whether price later reacted from the level.",
    },
    {
        "feature_family": "round_level_proximity",
        "pre_entry_only": True,
        "planned_use": "distance/proximity stratum only",
        "allowed_inputs": ["price level available before decision", "frozen numeric grid"],
        "leakage_guard": "Do not select grid bands after seeing GOOD vs FAST separation.",
    },
    {
        "feature_family": "pre_decision_sweep_type",
        "pre_entry_only": True,
        "planned_use": "sweep source and side stratum",
        "allowed_inputs": ["pre-decision M1/M5 sweep evidence", "direction inference source"],
        "leakage_guard": "Use only candles strictly before decision timestamp.",
    },
    {
        "feature_family": "m1_candle_anatomy_before_decision",
        "pre_entry_only": True,
        "planned_use": "wick/body/range anatomy before decision",
        "allowed_inputs": ["last completed pre-decision M1 candles"],
        "leakage_guard": "Exclude decision candle if not closed and all post-entry candles.",
    },
    {
        "feature_family": "m5_candle_anatomy_before_decision",
        "pre_entry_only": True,
        "planned_use": "M5 wick/body/range anatomy before decision",
        "allowed_inputs": ["last completed pre-decision M5 candles"],
        "leakage_guard": "Exclude incomplete/current M5 candle unless already closed before decision.",
    },
    {
        "feature_family": "m15_context_before_decision",
        "pre_entry_only": True,
        "planned_use": "coarse context annotation",
        "allowed_inputs": ["closed M15 candles before decision"],
        "leakage_guard": "No HTF candle may be used before it is closed.",
    },
    {
        "feature_family": "wick_body_proxy_before_decision",
        "pre_entry_only": True,
        "planned_use": "proxy stratum only",
        "allowed_inputs": ["pre-decision candle open/high/low/close"],
        "leakage_guard": "Thresholds must be pre-declared in execution branch, not selected from outcomes.",
    },
    {
        "feature_family": "compression_overlap_proxy_before_decision",
        "pre_entry_only": True,
        "planned_use": "range/overlap proxy before decision",
        "allowed_inputs": ["pre-decision candle ranges and overlap"],
        "leakage_guard": "Do not include post-entry accumulation/chop.",
    },
    {
        "feature_family": "fvg_ifvg_proximity_pre_entry",
        "pre_entry_only": True,
        "planned_use": "reaction-zone proximity if already available before decision",
        "allowed_inputs": ["pre-decision FVG/IFVG metadata or pre-decision candles"],
        "leakage_guard": "Do not mark a zone because post-entry price respected it.",
    },
    {
        "feature_family": "session_hour",
        "pre_entry_only": True,
        "planned_use": "session/time stratum",
        "allowed_inputs": ["decision timestamp"],
        "leakage_guard": "Session cannot be optimized after outcome review.",
    },
    {
        "feature_family": "volatility_range_context_before_decision",
        "pre_entry_only": True,
        "planned_use": "range/volatility stratum",
        "allowed_inputs": ["pre-decision range or volatility proxy"],
        "leakage_guard": "Do not use future ATR/range after decision.",
    },
    {
        "feature_family": "target_space_proxy_at_decision",
        "pre_entry_only": True,
        "planned_use": "available target-space context at decision",
        "allowed_inputs": ["known pre-decision liquidity/levels"],
        "leakage_guard": "Do not use actual later target hit or later liquidity behavior.",
    },
    {
        "feature_family": "direction_confidence_stratum",
        "pre_entry_only": True,
        "planned_use": "mandatory sensitivity stratum",
        "allowed_inputs": ["direction recovery confidence"],
        "leakage_guard": "Confidence 2 is weaker than original metadata and must be separated.",
    },
    {
        "feature_family": "direction_source_stratum",
        "pre_entry_only": True,
        "planned_use": "mandatory provenance stratum",
        "allowed_inputs": ["direction recovery source"],
        "leakage_guard": "Do not collapse inferred direction and existing metadata without reporting.",
    },
]

FORBIDDEN_FEATURES = [
    {"name": "TP hit", "forbidden_reason": "post-entry outcome"},
    {"name": "SL hit", "forbidden_reason": "post-entry outcome"},
    {"name": "pnl", "forbidden_reason": "performance outcome"},
    {"name": "r_multiple", "forbidden_reason": "performance outcome"},
    {"name": "future MFE", "forbidden_reason": "post-entry excursion"},
    {"name": "future MAE", "forbidden_reason": "post-entry excursion"},
    {"name": "post-entry candles", "forbidden_reason": "future price data"},
    {"name": "future liquidity behavior", "forbidden_reason": "future market state"},
    {"name": "outcome-derived thresholds", "forbidden_reason": "threshold leakage"},
    {
        "name": "feature thresholds selected after GOOD vs FAST separation",
        "forbidden_reason": "post-hoc optimization",
    },
    {
        "name": "any field created after seeing whether setup was GOOD_FAST_REACTION or FAST_FAILURE",
        "forbidden_reason": "label leakage",
    },
    {
        "name": "non-directional max move replay as primary evidence",
        "forbidden_reason": "optimistic semantic shift",
    },
]

CONFIDENCE_HANDLING = {
    "primary_planned_analysis": "Include confidence 3 and confidence 2 samples.",
    "mandatory_stratification": ["direction_confidence", "direction_source"],
    "mandatory_sensitivity_analysis": "confidence_3_only",
    "confidence_2_guardrail": (
        "Confidence 2 samples must not be treated as identical to original metadata direction. "
        "If separation exists only in confidence 2 samples, treat it as weak and research-only."
    ),
    "phase_4_guardrail": (
        "If confidence 3 sensitivity does not support the same direction, do not proceed to Phase 4."
    ),
}

COMPARISON_SCHEMA = {
    "plan_version": PLAN_VERSION,
    "comparison_executed": False,
    "primary_groups": PRIMARY_GROUPS,
    "secondary_review_groups": SECONDARY_REVIEW_GROUPS,
    "primary_group_inclusion_rule": (
        "Only rows whose final diagnostic outcome is GOOD_FAST_REACTION or FAST_FAILURE "
        "belong in the primary comparison."
    ),
    "secondary_group_rule": (
        "MIXED_REACTION and CHOP_AFTER_ENTRY may be reviewed separately, but must not be "
        "included in primary GOOD vs FAST separation."
    ),
    "planned_descriptive_outputs_for_future_execution_branch": [
        "descriptive feature frequency table",
        "difference in proportions",
        "confidence-3-only sensitivity",
        "confidence-2-only caution table",
        "human review priority list",
        "leakage check report",
    ],
    "prohibited_outputs": [
        "statistical significance claims",
        "ML classifier",
        "optimized thresholds",
        "score generation",
        "live-entry filter",
        "profitability claim",
    ],
    "small_n_warning": (
        "N=10 GOOD_FAST_REACTION is too small for strong conclusions. Future outputs "
        "must be diagnostic only."
    ),
    "future_row_fields": [
        "sample_id",
        "final_diagnostic_outcome",
        "direction",
        "direction_confidence",
        "direction_source",
        "pre_entry_feature_family",
        "pre_entry_feature_value",
        "feature_present",
        "leakage_check_passed",
        "notes",
    ],
    "real_feature_vs_outcome_statistics_generated": False,
}

DECISION_MATRIX = {
    "plan_version": PLAN_VERSION,
    "phase_4_blocked": True,
    "outcomes": [
        {
            "decision_code": "STRONG_DESCRIPTIVE_SEPARATION",
            "condition": (
                "One or two pre-entry features show strong descriptive separation and "
                "the same pattern appears in confidence-3-only sensitivity."
            ),
            "allowed_next_step": "allow a small confirmatory diagnostic branch",
            "phase_4_status": "still blocked until reviewed",
        },
        {
            "decision_code": "CONFIDENCE_2_ONLY_SEPARATION",
            "condition": "Separation exists mainly or only in confidence-2 inferred-direction samples.",
            "allowed_next_step": "mark weak, require more data or manual review",
            "phase_4_status": "blocked",
        },
        {
            "decision_code": "NO_STABLE_SEPARATION",
            "condition": "No stable pre-entry separation exists.",
            "allowed_next_step": "pause Adelin v2 as a strategy candidate; optionally keep as research lab",
            "phase_4_status": "blocked",
        },
        {
            "decision_code": "LEAKAGE_DEPENDENT_SEPARATION",
            "condition": "Separation requires post-entry interpretation or forbidden inputs.",
            "allowed_next_step": "reject the feature and mark leakage risk",
            "phase_4_status": "blocked",
        },
        {
            "decision_code": "MIXED_AMBIGUOUS_SMALL_N",
            "condition": "Separation is ambiguous due small N.",
            "allowed_next_step": "require additional samples or stricter sample collection",
            "phase_4_status": "blocked",
        },
    ],
}


def diagnostic_plan() -> dict[str, Any]:
    return {
        "plan_version": PLAN_VERSION,
        "plan_only": True,
        "comparison_executed": False,
        "ohlc_read": False,
        "replay_run": False,
        "matched_control_replay_run": False,
        "phase_4_blocked": True,
        "purpose": (
            "Pre-register how to compare GOOD_FAST_REACTION samples against FAST_FAILURE "
            "samples before any new analysis is executed."
        ),
        "prior_validated_baseline_context": PRIOR_VALIDATED_BASELINE_CONTEXT,
        "sample_groups": {
            "primary": PRIMARY_GROUPS,
            "secondary_excluded_from_primary": SECONDARY_REVIEW_GROUPS,
        },
        "direction_confidence_handling": CONFIDENCE_HANDLING,
        "allowed_feature_family_count": len(ALLOWED_FEATURES),
        "forbidden_feature_count": len(FORBIDDEN_FEATURES),
        "comparison_schema_file": "comparison_schema.json",
        "decision_matrix_file": "decision_matrix.json",
    }


def summary() -> dict[str, Any]:
    return {
        "plan_version": PLAN_VERSION,
        "plan_only": True,
        "ohlc_read": False,
        "candles_inspected": False,
        "comparison_executed": False,
        "new_outcome_statistics_generated": False,
        "feature_vs_outcome_statistics_generated": False,
        "replay_run": False,
        "matched_control_replay_run": False,
        "phase_4_blocked": True,
        "primary_groups": PRIMARY_GROUPS,
        "secondary_review_groups": SECONDARY_REVIEW_GROUPS,
        "allowed_feature_families": [item["feature_family"] for item in ALLOWED_FEATURES],
        "forbidden_leakage_fields": [item["name"] for item in FORBIDDEN_FEATURES],
        "confidence_2_guardrail": CONFIDENCE_HANDLING["confidence_2_guardrail"],
        "confidence_3_sensitivity_required": True,
        "small_n_warning": COMPARISON_SCHEMA["small_n_warning"],
        "safety": {
            "runtime_logic_modified": False,
            "strategy_2_touched": False,
            "strategy_3_touched": False,
            "live_trading_enabled": False,
            "orders_enabled": False,
            "telegram_alerts_enabled": False,
            "broker_execution_enabled": False,
            "v3_stash_applied_or_popped": False,
        },
        "verdict_flags": [
            "GOOD_VS_FAST_FAILURE_PLAN_REGISTERED",
            "PLAN_ONLY_NO_COMPARISON_EXECUTED",
            "NO_OHLC_READ",
            "PRE_ENTRY_FEATURES_ONLY_DEFINED",
            "FORBIDDEN_LEAKAGE_FEATURES_REGISTERED",
            "CONFIDENCE_3_SENSITIVITY_REQUIRED",
            "CONFIDENCE_2_GUARDRAIL_REGISTERED",
            "PHASE_4_STILL_BLOCKED",
            "ADELIN_REMAINS_RESEARCH_ONLY",
            "NO_LIVE_DEPLOYMENT_DECISION",
        ],
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_plan(output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "diagnostic_plan": output_dir / "diagnostic_plan.json",
        "allowed_features": output_dir / "allowed_features.json",
        "excluded_features": output_dir / "excluded_features.json",
        "comparison_schema": output_dir / "comparison_schema.json",
        "decision_matrix": output_dir / "decision_matrix.json",
        "summary": output_dir / "summary.json",
    }
    write_json(outputs["diagnostic_plan"], diagnostic_plan())
    write_json(outputs["allowed_features"], {"plan_version": PLAN_VERSION, "allowed_features": ALLOWED_FEATURES})
    write_json(
        outputs["excluded_features"],
        {"plan_version": PLAN_VERSION, "excluded_features": FORBIDDEN_FEATURES},
    )
    write_json(outputs["comparison_schema"], COMPARISON_SCHEMA)
    write_json(outputs["decision_matrix"], DECISION_MATRIX)
    write_json(outputs["summary"], summary())
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    outputs = write_plan(args.output_dir)
    print(json.dumps({key: str(path) for key, path in outputs.items()}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
