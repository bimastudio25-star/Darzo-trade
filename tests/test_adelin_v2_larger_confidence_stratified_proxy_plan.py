from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN_DIR = REPO_ROOT / "backtests" / "reports" / "adelin_v2_larger_confidence_stratified_proxy_plan"
DOC_PATH = REPO_ROOT / "docs" / "research" / "adelin_v2_larger_confidence_stratified_proxy_plan.md"


def _load(name: str):
    return json.loads((PLAN_DIR / name).read_text(encoding="utf-8"))


def test_plan_files_exist_and_parse():
    for name in [
        "diagnostic_plan.json",
        "acceptance_criteria.json",
        "sampling_rules.json",
        "summary.json",
    ]:
        assert (PLAN_DIR / name).exists()
        assert isinstance(_load(name), dict)
    assert DOC_PATH.exists()


def test_summary_is_plan_only_and_safe():
    summary = _load("summary.json")
    assert summary["plan_only"] is True
    assert summary["samples_collected"] is False
    assert summary["ohlc_read"] is False
    assert summary["h3_h4_proxies_executed"] is False
    assert summary["matched_control_run"] is False
    assert summary["phase_4_unlocked"] is False
    assert summary["runtime_logic_modified"] is False
    assert summary["strategy_2_modified"] is False
    assert summary["strategy_3_modified"] is False
    assert summary["data_xauusd_csv_modified"] is False
    assert summary["order_send_used"] is False


def test_primary_target_and_additional_confidence_3_requirement():
    plan = _load("diagnostic_plan.json")
    target = plan["primary_sample_target"]
    assert target["direction_source"] == "EXISTING_METADATA"
    assert target["direction_confidence"] == 3
    assert target["minimum_total_confidence_3_samples"] == 60
    assert target["existing_confidence_3_samples_already_analyzed"] == 21
    assert target["minimum_additional_confidence_3_samples_required"] == 39
    assert target["if_target_not_met"] == "INSUFFICIENT_CONFIDENCE_3_SAMPLE"


def test_evidence_hierarchy_and_confidence_2_guardrail():
    plan = _load("diagnostic_plan.json")
    assert plan["evidence_hierarchy"][0]["sample"] == "confidence-3 / EXISTING_METADATA"
    assert plan["evidence_hierarchy"][0]["role"] == "primary_evidence"
    assert plan["secondary_sample_policy"]["direction_source"] == "PRE_DECISION_SWEEP_INFERENCE"
    assert plan["secondary_sample_policy"]["direction_confidence"] == 2
    assert plan["secondary_sample_policy"]["may_drive_primary_conclusions"] is False
    assert plan["evidence_hierarchy"][2]["role"] == "descriptive_only_not_decision_basis"


def test_sample_sourcing_rules_are_explicit_and_do_not_use_h3_h4_quotas():
    rules = _load("sampling_rules.json")
    assert rules["sample_sourcing_must_not_be_ambiguous"] is True
    sources = {row["source_id"]: row for row in rules["allowed_sources"]}
    assert sources["A"]["allowed"] is True
    assert sources["B"]["allowed"] is True
    assert sources["C"]["allowed"] is False
    assert rules["h3_h4_states_are_not_sampling_quotas"] is True
    disallowed = rules["recommended_primary_sourcing_rule"]["must_not_use_for_selection"]
    assert "H3/H4 proxy states" in disallowed
    assert "outcome labels" in disallowed
    assert "MFE/MAE" in disallowed


def test_frozen_h3_h4_rules_are_preserved():
    plan = _load("diagnostic_plan.json")
    h3 = plan["frozen_h3"]
    h4 = plan["frozen_h4"]
    assert h3["formula_commit"] == "56dcff0"
    assert h3["thresholds_frozen"] is True
    assert h3["thresholds"] == {
        "TIGHT": "<= 0.25",
        "MEDIUM": "> 0.25 and <= 0.50",
        "WIDE": "> 0.50",
    }
    assert set(h3["missing_states"]) == {
        "UNKNOWN_REFERENCE_PRICE",
        "NO_VALID_INVALIDATION_EXTREME",
        "INVALID_GEOMETRY",
        "INSUFFICIENT_PRE_DECISION_RANGE",
    }
    assert h4["states_frozen"] is True
    assert set(h4["states"]) == {
        "NO_ZONE_AVAILABLE",
        "INSIDE_ZONE",
        "RETEST_HELD",
        "RECLAIM_CONFIRMED",
        "RETEST_FAILED_PRE_DECISION",
    }


def test_acceptance_criteria_keep_all_gates_blocked():
    criteria = _load("acceptance_criteria.json")
    reqs = criteria["minimum_methodology_usability_requirements"]
    assert reqs["primary_sample_size"]["confidence_3_existing_metadata_samples_minimum_total"] == 60
    assert reqs["primary_sample_size"]["minimum_additional_confidence_3_samples_required"] == 39
    assert reqs["leakage"]["post_entry_data_used_must_equal"] == 0
    assert reqs["leakage"]["leakage_failures_must_equal"] == 0
    assert reqs["reporting"]["h3_h4_states_not_sampling_quotas"] is True
    assert reqs["gate_status"]["phase_4_remains_blocked"] is True
    assert reqs["gate_status"]["matched_control_remains_blocked"] is True
    assert all(outcome["unlocks_phase_4"] is False for outcome in criteria["future_decision_outcomes"])
    assert "order_send" in criteria["no_future_outcome_may_unlock"]


def test_doc_contains_honest_power_statement_and_no_auto_unlock():
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "H3 x H4 creates up to 20 state-combination cells" in text
    assert "N=60 confidence-3 is a minimum gate for methodology review" in text
    assert "H3/H4 states must be measured and reported after proxy computation" in text
    assert "They must not be sampling quotas" in text
    assert "No future decision outcome in this plan can unlock Phase 4" in text
