"""Create the Adelin v2 manual screenshot concept audit.

This is documentation/schema/audit tooling only. It does not inspect image
pixels, auto-label screenshots, read OHLC, run replay/backtests, modify runtime
logic, or unlock Phase 4.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_OUTPUT_DIR = Path("backtests/reports/adelin_v2_manual_screenshot_concept_audit")

ALLOWED_COVERAGE = {"COVERED", "PARTIAL", "MISSING", "UNKNOWN"}
ALLOWED_MEASURABILITY = {
    "MEASURABLE_NOW",
    "MEASURABLE_WITH_EXISTING_OHLC_PROXY",
    "MEASURABLE_WITH_NEW_DATA",
    "HEURISTIC_ONLY",
    "NOT_RELIABLY_MEASURABLE",
}
ALLOWED_RISK = {"LOW", "MEDIUM", "HIGH"}
ALLOWED_YES_NO = {"YES", "NO"}
ALLOWED_PRIORITY = {"HIGH", "MEDIUM", "LOW"}

CONCEPTS: list[dict[str, Any]] = [
    {
        "concept_id": "PRE_DECISION_SWEEP_HIGH_LOW",
        "concept_name": "Pre-decision sweep high/low",
        "human_description": "Price takes a visible high or low before the reaction context is evaluated.",
        "screenshot_observation_note": "Human screenshots repeatedly emphasize a sweep before the reaction rather than a naked entry.",
        "current_adelin_feature_coverage": "PARTIAL",
        "measurability_status": "MEASURABLE_NOW",
        "possible_proxy": "Completed pre-decision M1/M5 candle trades beyond a prior high/low and maps high sweep to SHORT context or low sweep to LONG context.",
        "required_data": "Existing OHLC candles; no image data required.",
        "leakage_risk": "LOW",
        "runtime_safe_now": "NO",
        "future_priority": "HIGH",
        "notes": "Related to frozen direction governance rule adelin_v2_pre_decision_sweep_v1, but not yet a standalone entry feature.",
    },
    {
        "concept_id": "FAST_M1_REACTION_AFTER_SWEEP",
        "concept_name": "Fast M1 reaction after sweep",
        "human_description": "A quick M1 rejection or favorable impulse appears shortly after the sweep.",
        "screenshot_observation_note": "Manual examples visually separate fast reaction from slow/choppy continuation.",
        "current_adelin_feature_coverage": "PARTIAL",
        "measurability_status": "MEASURABLE_WITH_EXISTING_OHLC_PROXY",
        "possible_proxy": "Pre-register a sweep timestamp and measure only pre-decision reaction if used as context; post-entry reaction remains diagnostic-only.",
        "required_data": "Existing M1 OHLC; strict timestamp boundary is required.",
        "leakage_risk": "HIGH",
        "runtime_safe_now": "NO",
        "future_priority": "HIGH",
        "notes": "If measured after entry, it is an outcome diagnostic, not an entry feature.",
    },
    {
        "concept_id": "TIGHT_SL_BEHIND_SPIKE_OR_SWING",
        "concept_name": "Tight SL behind spike or swing",
        "human_description": "Manual examples often place the stop just beyond the spike, wick, or local swing invalidation.",
        "screenshot_observation_note": "Tight invalidation is visually important in the examples.",
        "current_adelin_feature_coverage": "MISSING",
        "measurability_status": "MEASURABLE_WITH_EXISTING_OHLC_PROXY",
        "possible_proxy": "Distance from entry/reference price to nearest completed pre-decision local swing or spike extreme.",
        "required_data": "Existing M1/M5 OHLC and a frozen swing/spike definition.",
        "leakage_risk": "MEDIUM",
        "runtime_safe_now": "NO",
        "future_priority": "HIGH",
        "notes": "Must not use whether the stop later held or failed.",
    },
    {
        "concept_id": "SWING_HIGH_LOW_ZONE_PROXIMITY",
        "concept_name": "Swing high/low zone proximity",
        "human_description": "Price reacts around a swing zone, not only a single exact level.",
        "screenshot_observation_note": "Manual examples often mark a swing area as the relevant context.",
        "current_adelin_feature_coverage": "PARTIAL",
        "measurability_status": "MEASURABLE_WITH_EXISTING_OHLC_PROXY",
        "possible_proxy": "Distance from entry/reference price to a pre-defined recent swing high/low zone width.",
        "required_data": "Existing OHLC and a frozen swing-zone width rule.",
        "leakage_risk": "MEDIUM",
        "runtime_safe_now": "NO",
        "future_priority": "HIGH",
        "notes": "Current H1 liquidity and recent HTF liquidity features only partially cover zone behavior.",
    },
    {
        "concept_id": "HTF_LTF_LEVEL_CONFLUENCE",
        "concept_name": "HTF/LTF level confluence",
        "human_description": "A higher-timeframe level aligns with a lower-timeframe sweep/reaction area.",
        "screenshot_observation_note": "The manual examples suggest context stacks across timeframes.",
        "current_adelin_feature_coverage": "PARTIAL",
        "measurability_status": "MEASURABLE_WITH_EXISTING_OHLC_PROXY",
        "possible_proxy": "Distance between frozen HTF level and LTF swing/sweep level at decision timestamp.",
        "required_data": "Existing M1/M5/M15/H1/H4/D1 OHLC where available.",
        "leakage_risk": "MEDIUM",
        "runtime_safe_now": "NO",
        "future_priority": "HIGH",
        "notes": "Related to liquidity_htf_recent_level but needs a true two-timeframe confluence definition.",
    },
    {
        "concept_id": "VOLUME_PROFILE_ZONE_PROXIMITY",
        "concept_name": "Volume profile zone proximity",
        "human_description": "Manual charts show reactions around volume distribution levels or profile zones.",
        "screenshot_observation_note": "Volume profile appears visually important but is not supported by screenshot observation alone.",
        "current_adelin_feature_coverage": "MISSING",
        "measurability_status": "MEASURABLE_WITH_NEW_DATA",
        "possible_proxy": "Distance to POC/HVN/LVN/value-area levels from a frozen rolling volume-profile calculation.",
        "required_data": "Tick volume or real volume plus a frozen volume-profile indicator/binning method.",
        "leakage_risk": "MEDIUM",
        "runtime_safe_now": "NO",
        "future_priority": "HIGH",
        "notes": "Not marked MEASURABLE_NOW because the current audit did not verify suitable volume-profile data support.",
    },
    {
        "concept_id": "PRICE_INSIDE_REACTION_ZONE",
        "concept_name": "Price inside reaction zone",
        "human_description": "The trade location is inside or near a zone, not merely close to a line.",
        "screenshot_observation_note": "Manual examples frame reaction as an area with boundaries.",
        "current_adelin_feature_coverage": "PARTIAL",
        "measurability_status": "MEASURABLE_WITH_EXISTING_OHLC_PROXY",
        "possible_proxy": "Entry/reference price lies within frozen FVG, IFVG, swing-zone, or volume-zone boundaries.",
        "required_data": "Existing OHLC for FVG/swing zones; new volume-profile data for profile zones.",
        "leakage_risk": "MEDIUM",
        "runtime_safe_now": "NO",
        "future_priority": "HIGH",
        "notes": "fvg_ifvg_near_20p is proximity-only and does not fully cover inside-zone behavior.",
    },
    {
        "concept_id": "CLEAN_TARGET_SPACE_TO_NEXT_ZONE",
        "concept_name": "Clean target space to next zone",
        "human_description": "The path to opposing liquidity or the next reaction zone appears open enough for continuation after reaction.",
        "screenshot_observation_note": "Manual examples often imply room-to-target matters.",
        "current_adelin_feature_coverage": "PARTIAL",
        "measurability_status": "MEASURABLE_WITH_EXISTING_OHLC_PROXY",
        "possible_proxy": "Distance from entry/reference price to next opposing pre-decision swing/liquidity/reaction zone.",
        "required_data": "Existing OHLC and frozen opposing-zone definitions.",
        "leakage_risk": "MEDIUM",
        "runtime_safe_now": "NO",
        "future_priority": "MEDIUM",
        "notes": "Avoid using whether the future target was actually reached.",
    },
    {
        "concept_id": "DIRTY_REACTION_CHOP_AFTER_ENTRY",
        "concept_name": "Dirty reaction or chop after entry",
        "human_description": "The post-entry path is messy, delayed, or choppy instead of clean.",
        "screenshot_observation_note": "Manual examples distinguish clean reactions from dirty reactions.",
        "current_adelin_feature_coverage": "PARTIAL",
        "measurability_status": "HEURISTIC_ONLY",
        "possible_proxy": "Diagnostic-only post-entry chop tag; do not use as a clean pre-entry feature.",
        "required_data": "Post-entry OHLC for diagnostics only.",
        "leakage_risk": "HIGH",
        "runtime_safe_now": "NO",
        "future_priority": "LOW",
        "notes": "This is explicitly not an entry feature and must remain diagnostic/outcome-only unless reframed as a pre-entry risk proxy.",
    },
    {
        "concept_id": "ZONE_RETEST_OR_RECLAIM",
        "concept_name": "Zone retest or reclaim",
        "human_description": "Price retests or reclaims a previously defined zone before the decision.",
        "screenshot_observation_note": "Manual examples imply the reaction is sometimes confirmed by reclaim/retest behavior.",
        "current_adelin_feature_coverage": "MISSING",
        "measurability_status": "MEASURABLE_WITH_EXISTING_OHLC_PROXY",
        "possible_proxy": "A completed pre-decision candle crosses and closes back inside/outside a frozen zone boundary.",
        "required_data": "Existing OHLC and a frozen zone definition.",
        "leakage_risk": "MEDIUM",
        "runtime_safe_now": "NO",
        "future_priority": "HIGH",
        "notes": "Needs pre-registered zone source and retest/reclaim semantics.",
    },
    {
        "concept_id": "ROUND_OR_NUMERIC_LEVEL_CONFLUENCE",
        "concept_name": "Round or numeric level confluence",
        "human_description": "The setup aligns with a visible round/numeric level.",
        "screenshot_observation_note": "Manual examples often include obvious number-level context.",
        "current_adelin_feature_coverage": "COVERED",
        "measurability_status": "MEASURABLE_NOW",
        "possible_proxy": "Distance to locked XAUUSD numeric grid, with 004 primary numeric-level hypothesis and 005 stratification only.",
        "required_data": "Price level only; existing OHLC metadata is sufficient.",
        "leakage_risk": "LOW",
        "runtime_safe_now": "NO",
        "future_priority": "MEDIUM",
        "notes": "Already governed by Phase 2 numeric-level overlap fix.",
    },
    {
        "concept_id": "SESSION_CONTEXT_ASIA_TO_NY_WINDOW",
        "concept_name": "Session context Asia to NY window",
        "human_description": "The trade context depends on session or time-of-day behavior.",
        "screenshot_observation_note": "Examples appear session-aware, including Asia/London/NY windows.",
        "current_adelin_feature_coverage": "COVERED",
        "measurability_status": "MEASURABLE_NOW",
        "possible_proxy": "Timestamp-derived session bucket, hour, and premium-session indicator.",
        "required_data": "Timestamp metadata only.",
        "leakage_risk": "LOW",
        "runtime_safe_now": "NO",
        "future_priority": "LOW",
        "notes": "Covered as context/stratification; not evidence of edge.",
    },
]

COVERAGE_ROWS: list[dict[str, str]] = [
    {
        "concept_id": "PRE_DECISION_SWEEP_HIGH_LOW",
        "concept_name": "Pre-decision sweep high/low",
        "existing_feature_name": "pre-decision sweep inference; h1_sweep_reaction_context",
        "coverage_status": "PARTIAL",
        "gap_description": "Direction governance uses sweep inference, but it is not a standalone candidate feature.",
        "future_action": "Freeze a pre-entry sweep feature only in a separate plan.",
    },
    {
        "concept_id": "FAST_M1_REACTION_AFTER_SWEEP",
        "concept_name": "Fast M1 reaction after sweep",
        "existing_feature_name": "fast_reaction diagnostics; m1_large_body_ge_0_60; m1_close_high_ge_0_70",
        "coverage_status": "PARTIAL",
        "gap_description": "Current use is mostly diagnostic/outcome-side or candle anatomy, not a clean pre-entry reaction proxy.",
        "future_action": "Define strict pre-decision-only reaction timing before any test.",
    },
    {
        "concept_id": "TIGHT_SL_BEHIND_SPIKE_OR_SWING",
        "concept_name": "Tight SL behind spike or swing",
        "existing_feature_name": "",
        "coverage_status": "MISSING",
        "gap_description": "No locked invalidation-distance proxy exists.",
        "future_action": "Define local spike/swing invalidation distance with no future SL outcome.",
    },
    {
        "concept_id": "SWING_HIGH_LOW_ZONE_PROXIMITY",
        "concept_name": "Swing high/low zone proximity",
        "existing_feature_name": "h1_sweep_reaction_context; liquidity_htf_recent_level",
        "coverage_status": "PARTIAL",
        "gap_description": "Single/recent levels exist, but zone-width behavior is not fully represented.",
        "future_action": "Define swing-zone width and proximity rules.",
    },
    {
        "concept_id": "HTF_LTF_LEVEL_CONFLUENCE",
        "concept_name": "HTF/LTF level confluence",
        "existing_feature_name": "liquidity_htf_recent_level",
        "coverage_status": "PARTIAL",
        "gap_description": "HTF recency exists, but explicit HTF/LTF distance confluence is not locked.",
        "future_action": "Define HTF and LTF level sources and distance thresholds.",
    },
    {
        "concept_id": "VOLUME_PROFILE_ZONE_PROXIMITY",
        "concept_name": "Volume profile zone proximity",
        "existing_feature_name": "",
        "coverage_status": "MISSING",
        "gap_description": "No validated volume-profile data source or binning method is locked.",
        "future_action": "Run data feasibility/governance branch before any feature plan.",
    },
    {
        "concept_id": "PRICE_INSIDE_REACTION_ZONE",
        "concept_name": "Price inside reaction zone",
        "existing_feature_name": "fvg_ifvg_near_20p",
        "coverage_status": "PARTIAL",
        "gap_description": "Proximity to FVG/iFVG exists, but inside-zone boundary logic is not locked.",
        "future_action": "Define reaction-zone source and boundary rules.",
    },
    {
        "concept_id": "CLEAN_TARGET_SPACE_TO_NEXT_ZONE",
        "concept_name": "Clean target space to next zone",
        "existing_feature_name": "target space proxy if present",
        "coverage_status": "PARTIAL",
        "gap_description": "A general target-space proxy exists in diagnostics, but next-zone definition is not frozen.",
        "future_action": "Define next opposing zone using pre-decision data only.",
    },
    {
        "concept_id": "DIRTY_REACTION_CHOP_AFTER_ENTRY",
        "concept_name": "Dirty reaction or chop after entry",
        "existing_feature_name": "dirty_chop_after_entry diagnostic tag",
        "coverage_status": "PARTIAL",
        "gap_description": "Covered only as post-entry diagnostic behavior, not a pre-entry feature.",
        "future_action": "Do not use as entry feature; consider only pre-entry risk proxies.",
    },
    {
        "concept_id": "ZONE_RETEST_OR_RECLAIM",
        "concept_name": "Zone retest or reclaim",
        "existing_feature_name": "",
        "coverage_status": "MISSING",
        "gap_description": "No dedicated reclaim/retest proxy exists.",
        "future_action": "Freeze zone definitions and reclaim/retest candle rules.",
    },
    {
        "concept_id": "ROUND_OR_NUMERIC_LEVEL_CONFLUENCE",
        "concept_name": "Round or numeric level confluence",
        "existing_feature_name": "numeric level confluence; tight_numeric_level_touch_band",
        "coverage_status": "COVERED",
        "gap_description": "Primary and stratification roles are already separated.",
        "future_action": "Keep 005 stratification-only; no standalone predictive interpretation.",
    },
    {
        "concept_id": "SESSION_CONTEXT_ASIA_TO_NY_WINDOW",
        "concept_name": "Session context Asia to NY window",
        "existing_feature_name": "session/hour; premium session context",
        "coverage_status": "COVERED",
        "gap_description": "Timestamp/session bucket is available as context.",
        "future_action": "Use only as pre-registered stratification or context.",
    },
]

FUTURE_TASKS = [
    {
        "task_id": "FUTURE_001",
        "title": "Pre-entry sweep feature governance",
        "concept_ids": ["PRE_DECISION_SWEEP_HIGH_LOW"],
        "allowed_scope": "Define deterministic pre-entry sweep proxy; no replay or optimization.",
    },
    {
        "task_id": "FUTURE_002",
        "title": "Tight invalidation distance proxy",
        "concept_ids": ["TIGHT_SL_BEHIND_SPIKE_OR_SWING"],
        "allowed_scope": "Define local spike/swing invalidation distance using completed pre-decision candles only.",
    },
    {
        "task_id": "FUTURE_003",
        "title": "Volume profile data feasibility",
        "concept_ids": ["VOLUME_PROFILE_ZONE_PROXIMITY"],
        "allowed_scope": "Check whether tick/volume/profile data exists and can be computed reproducibly; no trading claims.",
    },
    {
        "task_id": "FUTURE_004",
        "title": "Reaction-zone boundary and reclaim proxy",
        "concept_ids": ["PRICE_INSIDE_REACTION_ZONE", "ZONE_RETEST_OR_RECLAIM"],
        "allowed_scope": "Freeze zone definitions and retest/reclaim semantics before any empirical execution.",
    },
    {
        "task_id": "FUTURE_005",
        "title": "Target-space pre-entry proxy",
        "concept_ids": ["CLEAN_TARGET_SPACE_TO_NEXT_ZONE"],
        "allowed_scope": "Define next opposing zone from pre-decision data only; do not use future TP outcome.",
    },
]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def validate_concepts(concepts: Sequence[Mapping[str, Any]]) -> None:
    required = {
        "concept_id",
        "concept_name",
        "human_description",
        "screenshot_observation_note",
        "current_adelin_feature_coverage",
        "measurability_status",
        "possible_proxy",
        "required_data",
        "leakage_risk",
        "runtime_safe_now",
        "future_priority",
        "notes",
    }
    for concept in concepts:
        missing = required.difference(concept)
        if missing:
            raise ValueError(f"{concept.get('concept_id', 'UNKNOWN')} missing fields: {sorted(missing)}")
        if concept["current_adelin_feature_coverage"] not in ALLOWED_COVERAGE:
            raise ValueError(f"invalid coverage: {concept}")
        if concept["measurability_status"] not in ALLOWED_MEASURABILITY:
            raise ValueError(f"invalid measurability: {concept}")
        if concept["leakage_risk"] not in ALLOWED_RISK:
            raise ValueError(f"invalid leakage risk: {concept}")
        if concept["runtime_safe_now"] not in ALLOWED_YES_NO:
            raise ValueError(f"invalid runtime safe flag: {concept}")
        if concept["future_priority"] not in ALLOWED_PRIORITY:
            raise ValueError(f"invalid priority: {concept}")


def summary_payload(concepts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = Counter(concept["measurability_status"] for concept in concepts)
    high_priority_missing = [
        concept["concept_id"]
        for concept in concepts
        if concept["future_priority"] == "HIGH"
        and concept["current_adelin_feature_coverage"] in {"MISSING", "PARTIAL"}
    ]
    return {
        "audit_only": True,
        "screenshots_auto_labeled": False,
        "screenshots_used_as_validation": False,
        "manual_screenshot_paths_detected": [],
        "manual_screenshot_paths_listed_only": True,
        "ohlc_read": False,
        "replay_run": False,
        "matched_control_replay_run": False,
        "phase_4_blocked": True,
        "runtime_logic_modified": False,
        "live_trading_enabled": False,
        "telegram_enabled": False,
        "broker_execution_enabled": False,
        "profitability_claim_made": False,
        "total_concepts": len(concepts),
        "measurable_now_count": counts.get("MEASURABLE_NOW", 0),
        "existing_ohlc_proxy_count": counts.get("MEASURABLE_WITH_EXISTING_OHLC_PROXY", 0),
        "new_data_required_count": counts.get("MEASURABLE_WITH_NEW_DATA", 0),
        "heuristic_only_count": counts.get("HEURISTIC_ONLY", 0),
        "not_reliably_measurable_count": counts.get("NOT_RELIABLY_MEASURABLE", 0),
        "high_priority_missing_concepts": high_priority_missing,
        "verdict_flags": [
            "MANUAL_SCREENSHOT_CONCEPT_AUDIT_COMPLETE",
            "QUALITATIVE_REFERENCE_ONLY",
            "NO_SCREENSHOT_VALIDATION",
            "NO_AUTO_LABELING",
            "NO_PHASE_4",
            "ADELIN_REMAINS_RESEARCH_ONLY",
            "NO_LIVE_DEPLOYMENT_DECISION",
        ],
    }


def missing_feature_candidates(concepts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "concept_id": concept["concept_id"],
            "concept_name": concept["concept_name"],
            "current_adelin_feature_coverage": concept["current_adelin_feature_coverage"],
            "measurability_status": concept["measurability_status"],
            "future_priority": concept["future_priority"],
            "possible_proxy": concept["possible_proxy"],
            "required_data": concept["required_data"],
            "allowed_next_step": "pre-register proxy methodology before empirical testing",
        }
        for concept in concepts
        if concept["current_adelin_feature_coverage"] in {"MISSING", "PARTIAL"}
    ]


def write_audit(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    validate_concepts(CONCEPTS)
    taxonomy = {
        "taxonomy_name": "adelin_v2_manual_screenshot_concept_taxonomy",
        "audit_only": True,
        "qualitative_reference_only": True,
        "concept_ids": [concept["concept_id"] for concept in CONCEPTS],
        "allowed_measurability_statuses": sorted(ALLOWED_MEASURABILITY),
        "allowed_coverage_statuses": sorted(ALLOWED_COVERAGE),
        "concepts": CONCEPTS,
    }
    summary = summary_payload(CONCEPTS)
    write_json(output_dir / "manual_screenshot_concept_taxonomy.json", taxonomy)
    write_csv(output_dir / "concept_measurability_audit.csv", CONCEPTS)
    write_json(output_dir / "concept_measurability_audit.json", CONCEPTS)
    write_csv(output_dir / "current_feature_coverage_map.csv", COVERAGE_ROWS)
    write_json(output_dir / "missing_feature_candidates.json", missing_feature_candidates(CONCEPTS))
    write_json(output_dir / "future_research_tasks.json", FUTURE_TASKS)
    write_json(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    summary = write_audit()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
