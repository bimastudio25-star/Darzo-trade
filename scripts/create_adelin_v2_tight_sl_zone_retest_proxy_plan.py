"""Create the Adelin v2 tight-SL and zone-retest OHLC proxy plan.

This is plan-only tooling. It pre-registers deterministic proxy definitions
without reading OHLC, collecting samples, running replay/backtests, modifying
runtime logic, or unlocking Phase 4.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_DIR = Path("backtests/reports/adelin_v2_tight_sl_zone_retest_proxy_plan")
PLAN_VERSION = "adelin_v2_tight_sl_zone_retest_proxy_plan_v1"
PRIMARY_PROXY_CONCEPTS = ["TIGHT_SL_BEHIND_SPIKE_OR_SWING", "ZONE_RETEST_OR_RECLAIM"]

FORBIDDEN_INPUTS = [
    "post_entry_candles",
    "tp_hit",
    "sl_hit",
    "pnl",
    "r_multiple",
    "future_mfe",
    "future_mae",
    "outcome_derived_thresholds",
    "later_swing_levels_created_after_decision",
    "future_liquidity_behavior",
    "manual_cherry_picking",
    "non_directional_max_move_replay",
    "good_fast_outcome_group_for_threshold_selection",
    "fast_failure_outcome_group_for_threshold_selection",
]

ALLOWED_INPUTS = {
    "global_rules": [
        "Use only candles and metadata with timestamp strictly before decision_timestamp.",
        "Use completed candles only.",
        "Use candidate reference price from existing candidate metadata or a separately pre-registered reference-price rule.",
        "Use existing OHLC timeframes only in the future execution branch.",
        "Do not use result labels, TP/SL hit, future excursion, or future swing formation.",
    ],
    "timeframes": ["M1", "M5", "M15", "H1"],
    "fields": [
        "open",
        "high",
        "low",
        "close",
        "timestamp",
        "candidate_reference_price",
        "decision_timestamp",
        "direction",
        "source/session metadata for stratification",
    ],
}

H3_SPEC: dict[str, Any] = {
    "proxy_id": "H3",
    "concept_id": "TIGHT_SL_BEHIND_SPIKE_OR_SWING",
    "proxy_name": "tight_sl_local_invalidation_proxy",
    "human_concept_description": "A discretionary entry is more attractive when invalidation sits close behind a local spike, sweep extreme, or completed swing structure.",
    "deterministic_formula_description": (
        "For the candidate direction, inspect completed pre-decision M1 and M5 candles in fixed lookback windows. "
        "For LONG, the invalidation extreme is the nearest qualifying local low/sweep low below the candidate reference price. "
        "For SHORT, the invalidation extreme is the nearest qualifying local high/sweep high above the candidate reference price. "
        "Compute invalidation_distance_usd, invalidation_distance_pips, and invalidation_distance_to_recent_range_ratio."
    ),
    "allowed_timeframes": ["M1", "M5"],
    "required_inputs": [
        "decision_timestamp",
        "candidate_reference_price",
        "direction",
        "completed pre-decision M1 OHLC",
        "completed pre-decision M5 OHLC",
    ],
    "allowed_inputs": [
        "local swing highs/lows formed before decision_timestamp",
        "sweep extremes formed before decision_timestamp",
        "recent pre-decision range proxy",
        "candidate/source metadata",
    ],
    "forbidden_inputs": FORBIDDEN_INPUTS,
    "pre_decision_only_rule": "All swing/spike candidates and range proxies must use candles with timestamp < decision_timestamp.",
    "candidate_reference_price_definition": "Use the existing candidate entry/reference price when present; otherwise the future execution branch must stop or use a separately pre-registered fallback, not infer from outcome.",
    "normalization_method": {
        "recent_range_proxy": "Median high-low range over completed pre-decision M1 candles in a fixed 30-minute window plus M5 range cross-check.",
        "normalized_distance": "invalidation_distance_usd / max(recent_range_proxy_usd, small_positive_floor)",
        "pips_conversion": "For XAUUSD, 1 pip = 0.1 USD unless a future instrument-specific metadata file pre-registers otherwise.",
    },
    "threshold_policy": {
        "type": "multi_band_descriptive_pre_registered",
        "bands": {
            "TIGHT": "normalized_distance <= 1.0",
            "MEDIUM": "1.0 < normalized_distance <= 2.0",
            "WIDE": "normalized_distance > 2.0",
        },
        "fixed_usd_reference_band": "Record <=2.0 USD / <=20 pips as a descriptive reference only, not as an optimized pass threshold.",
        "forbidden": [
            "Do not choose thresholds after observing GOOD/FAST separation.",
            "Do not change bands during execution.",
            "Do not select the best-performing band as a final rule.",
        ],
    },
    "leakage_risks": [
        "Using whether the stop was later hit.",
        "Using swing highs/lows formed after decision_timestamp.",
        "Using future MAE/MFE to choose invalidation point.",
    ],
    "validation_requirements": [
        "Report computability rate.",
        "Report missing-reference-price rows.",
        "Report pre_entry_only=true and post_entry_data_used=false.",
        "Stratify by direction confidence/source if available.",
        "Treat all outputs as descriptive diagnostics only.",
    ],
    "future_execution_outputs": [
        "tight_sl_band",
        "invalidation_distance_usd",
        "invalidation_distance_pips",
        "invalidation_distance_to_recent_range_ratio",
        "invalidation_source_timeframe",
        "invalidation_source_type",
        "proxy_computable",
        "proxy_limitations",
    ],
}

H4_SPEC: dict[str, Any] = {
    "proxy_id": "H4",
    "concept_id": "ZONE_RETEST_OR_RECLAIM",
    "proxy_name": "pre_decision_zone_retest_reclaim_proxy",
    "human_concept_description": "A discretionary entry may improve when price reclaims, retests, or holds a pre-defined zone/level before the decision.",
    "deterministic_formula_description": (
        "Freeze zone boundaries before decision_timestamp. Candidate zones may come from numeric levels, completed swing zones, or completed FVG/iFVG zones. "
        "A retest occurs when a completed pre-decision M1/M5 candle touches the zone after the first interaction and closes without invalidating the side implied by direction. "
        "A reclaim occurs when price moves through a zone boundary and a completed pre-decision candle closes back on the trade side of that boundary."
    ),
    "allowed_timeframes": ["M1", "M5", "M15", "H1"],
    "required_inputs": [
        "decision_timestamp",
        "candidate_reference_price",
        "direction",
        "pre-defined zone boundaries",
        "completed pre-decision M1/M5 OHLC",
    ],
    "allowed_inputs": [
        "numeric level zones from locked grid",
        "completed swing high/low zones",
        "completed FVG/iFVG zone boundaries",
        "completed pre-decision closes and wicks",
        "touch count before decision_timestamp",
    ],
    "forbidden_inputs": FORBIDDEN_INPUTS,
    "pre_decision_only_rule": "All zone definitions, touches, closes, retests, and reclaims must occur before decision_timestamp.",
    "candidate_reference_price_definition": "Use the existing candidate entry/reference price when present; do not infer zone membership from future outcome.",
    "normalization_method": {
        "zone_width": "Record zone width in USD/pips and as a ratio to recent pre-decision M1/M5 range.",
        "distance_to_zone": "Distance from candidate reference price to nearest zone boundary, signed by whether price is inside or outside the zone.",
        "touch_count": "Count completed pre-decision touches only.",
    },
    "threshold_policy": {
        "type": "categorical_descriptive_pre_registered",
        "categories": [
            "NO_ZONE_AVAILABLE",
            "INSIDE_ZONE",
            "RETEST_HELD",
            "RECLAIM_CONFIRMED",
            "RETEST_FAILED_PRE_DECISION",
        ],
        "forbidden": [
            "Do not tune zone width after seeing outcomes.",
            "Do not promote the best category to a rule after execution.",
            "Do not redefine zones mid-run.",
        ],
    },
    "leakage_risks": [
        "Using post-entry retest/reclaim candles.",
        "Creating zone boundaries from future swings.",
        "Using later target or SL behavior to decide whether a retest held.",
    ],
    "validation_requirements": [
        "Report zone-source distribution.",
        "Report category distribution.",
        "Report pre_entry_only=true and post_entry_data_used=false.",
        "Report rows rejected due unclear zone definitions.",
        "Treat all outputs as descriptive diagnostics only.",
    ],
    "future_execution_outputs": [
        "zone_retest_reclaim_category",
        "zone_source",
        "zone_low",
        "zone_high",
        "zone_width_pips",
        "distance_to_zone_pips",
        "pre_decision_touch_count",
        "last_pre_decision_close_relation",
        "proxy_computable",
        "proxy_limitations",
    ],
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def plan_payload() -> dict[str, Any]:
    return {
        "plan_version": PLAN_VERSION,
        "plan_only": True,
        "context_source": "manual screenshot concept audit b866011",
        "primary_proxy_concepts": PRIMARY_PROXY_CONCEPTS,
        "volume_profile_deferred": True,
        "proxy_execution_required_future_branch": True,
        "proxy_specs": [H3_SPEC, H4_SPEC],
        "current_feature_relationship": {
            "H3": "Related to local invalidation and tight SL human discretion; currently missing in feature coverage.",
            "H4": "Related to zone membership/retest/reclaim and reaction-zone logic; currently missing or partial in feature coverage.",
        },
        "not_live_filters": True,
        "not_validated_features": True,
    }


def leakage_guards_payload() -> dict[str, Any]:
    return {
        "pre_entry_only_required": True,
        "future_execution_must_record": {
            "pre_entry_only": True,
            "post_entry_data_used": False,
            "leakage_check_passed": True,
        },
        "forbidden_inputs": FORBIDDEN_INPUTS,
        "threshold_tuning_from_results_forbidden": True,
        "manual_cherry_picking_forbidden": True,
        "phase_4_blocked": True,
    }


def future_execution_schema_payload() -> dict[str, Any]:
    return {
        "future_execution_required_in_separate_branch": True,
        "allowed_future_actions": [
            "load the signed proxy specs",
            "compute H3/H4 on pre-decision OHLC only",
            "write computability and leakage reports",
            "produce descriptive diagnostic tables only",
        ],
        "forbidden_future_actions": [
            "matched-control replay",
            "Phase 4",
            "runtime integration",
            "threshold optimization",
            "scoring",
            "live-entry filters",
            "profitability claims",
        ],
        "required_outputs": [
            "proxy_computability_report",
            "h3_tight_sl_proxy_results",
            "h4_zone_retest_proxy_results",
            "leakage_check_report",
            "threshold_policy_compliance_report",
        ],
    }


def decision_matrix_payload() -> dict[str, Any]:
    return {
        "phase_4_blocked": True,
        "outcomes": [
            {
                "decision_code": "PROXY_MEASURABLE_AND_STABLE",
                "condition": "Proxy can be computed consistently and leakage checks pass.",
                "allowed_next_action": "bounded diagnostic execution only",
                "phase_4_status": "blocked",
            },
            {
                "decision_code": "PROXY_NOT_COMPUTABLE_RELIABLY",
                "condition": "Proxy requires unclear zone definitions or missing data.",
                "allowed_next_action": "reject or defer concept",
                "phase_4_status": "blocked",
            },
            {
                "decision_code": "POST_ENTRY_LEAKAGE_DETECTED",
                "condition": "Proxy works only with post-entry information.",
                "allowed_next_action": "reject as leakage",
                "phase_4_status": "blocked",
            },
            {
                "decision_code": "ARBITRARY_THRESHOLD_TUNING_REQUIRED",
                "condition": "Proxy depends on choosing thresholds after seeing results.",
                "allowed_next_action": "reject or require new plan",
                "phase_4_status": "blocked",
            },
            {
                "decision_code": "HIGH_MANUAL_DISAGREEMENT",
                "condition": "Proxy has high disagreement with manual evidence.",
                "allowed_next_action": "keep research-only or redefine in new plan",
                "phase_4_status": "blocked",
            },
        ],
    }


def summary_payload() -> dict[str, Any]:
    return {
        "plan_only": True,
        "ohlc_read": False,
        "samples_collected": False,
        "replay_run": False,
        "matched_control_replay_run": False,
        "phase_4_blocked": True,
        "runtime_logic_modified": False,
        "live_trading_enabled": False,
        "telegram_enabled": False,
        "broker_execution_enabled": False,
        "profitability_claim_made": False,
        "primary_proxy_concepts": PRIMARY_PROXY_CONCEPTS,
        "volume_profile_deferred": True,
        "proxy_execution_required_future_branch": True,
        "verdict_flags": [
            "OHLC_PROXY_PLAN_CREATED",
            "PROXY_FORMULAS_PRE_REGISTERED",
            "NO_PROXY_EXECUTION",
            "NO_OHLC_READ",
            "NO_PHASE_4",
            "ADELIN_REMAINS_RESEARCH_ONLY",
            "NO_LIVE_DEPLOYMENT_DECISION",
        ],
    }


def validate_plan_payloads() -> None:
    if [H3_SPEC["concept_id"], H4_SPEC["concept_id"]] != PRIMARY_PROXY_CONCEPTS:
        raise ValueError("primary proxy concepts must be exactly H3/H4")
    for spec in (H3_SPEC, H4_SPEC):
        if "post_entry_candles" not in spec["forbidden_inputs"]:
            raise ValueError(f"{spec['proxy_id']} missing post-entry candle ban")
        policy = json.dumps(spec["threshold_policy"]).lower()
        if "after observing" not in policy and "after seeing" not in policy:
            raise ValueError(f"{spec['proxy_id']} threshold policy does not forbid result tuning")


def write_plan(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    validate_plan_payloads()
    write_json(output_dir / "proxy_feature_plan.json", plan_payload())
    write_json(output_dir / "h3_tight_sl_proxy_spec.json", H3_SPEC)
    write_json(output_dir / "h4_zone_retest_proxy_spec.json", H4_SPEC)
    write_json(output_dir / "allowed_inputs.json", ALLOWED_INPUTS)
    write_json(output_dir / "forbidden_inputs.json", {"forbidden_inputs": FORBIDDEN_INPUTS})
    write_json(output_dir / "future_execution_schema.json", future_execution_schema_payload())
    write_json(output_dir / "leakage_guards.json", leakage_guards_payload())
    write_json(output_dir / "decision_matrix.json", decision_matrix_payload())
    summary = summary_payload()
    write_json(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    summary = write_plan()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
