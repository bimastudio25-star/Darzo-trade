from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN_DIR = REPO_ROOT / "backtests" / "reports" / "adelin_v2_confidence3_forward_collection_plan"
DOC_PATH = REPO_ROOT / "docs" / "research" / "adelin_v2_confidence3_forward_collection_plan.md"


def _load(name: str):
    return json.loads((PLAN_DIR / name).read_text(encoding="utf-8"))


def test_plan_files_exist_and_parse():
    for name in [
        "collection_plan.json",
        "eligibility_schema.json",
        "rejection_reasons.json",
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
    assert summary["h3_h4_proxy_computation_run"] is False
    assert summary["proxy_diagnostic_executed"] is False
    assert summary["replay_run"] is False
    assert summary["backtest_run"] is False
    assert summary["matched_control_run"] is False
    assert summary["phase_4_unlocked"] is False
    assert summary["runtime_logic_modified"] is False
    assert summary["strategy_2_modified"] is False
    assert summary["strategy_3_modified"] is False
    assert summary["data_xauusd_csv_modified"] is False
    assert summary["live_trading_enabled"] is False
    assert summary["order_send_used"] is False


def test_target_preserves_existing_21_and_requires_39_more():
    plan = _load("collection_plan.json")
    objective = plan["objective"]
    assert objective["minimum_total_confidence_3_existing_metadata_samples"] == 60
    assert objective["existing_confidence_3_samples_counted_toward_target"] == 21
    assert objective["additional_forward_confidence_3_samples_required"] == 39
    assert objective["target_must_not_be_lowered"] is True


def test_forward_collection_eligibility_and_direction_source_policy():
    plan = _load("collection_plan.json")
    eligibility = plan["forward_collection_definition"]["primary_eligibility"]
    assert eligibility["direction_source"] == "EXISTING_METADATA"
    assert eligibility["direction_confidence"] == 3
    assert eligibility["decision_timestamp"] == "DIRECT_METADATA_REQUIRED"
    assert eligibility["post_entry_data_used_for_inclusion"] is False

    policy = plan["direction_source_policy"]
    assert policy["direction_source_must_be_explicitly_present"] is True
    assert policy["missing_direction_source_rejection_reason"] == "DIRECTION_SOURCE_FIELD_ABSENT"
    assert policy["missing_direction_confidence_rejection_reason"] == "DIRECTION_CONFIDENCE_FIELD_ABSENT"
    assert "PRE_DECISION_SWEEP_INFERENCE" in policy["not_primary"]


def test_timestamp_and_id_policies_fail_closed():
    plan = _load("collection_plan.json")
    timestamp_policy = plan["timestamp_policy"]
    assert timestamp_policy["direct_metadata_required_for_primary_eligibility"] is True
    assert timestamp_policy["reconstructed_timestamps_primary_eligible"] is False
    assert timestamp_policy["infer_timestamps_from_ohlc"] is False
    assert timestamp_policy["missing_timestamp_rejection_reason"] == "DECISION_TIMESTAMP_MISSING"

    id_policy = plan["sample_id_policy"]
    assert id_policy["stable_unique_identifier_required"] is True
    assert id_policy["preferred_authoritative_id_field"] == "sample_id"
    assert id_policy["id_resolution_ambiguous_rejection_reason"] == "ID_RESOLUTION_AMBIGUOUS"
    assert id_policy["duplicate_rejection_reason"] == "DUPLICATE_SAMPLE"


def test_batch_collection_and_rate_policy_exist():
    plan = _load("collection_plan.json")
    batches = plan["collection_batches"]
    assert batches["batching_required"] is True
    assert "actual_collection_rate_samples_per_week" in batches["required_batch_fields"]
    assert batches["silent_batch_mixing_allowed"] is False

    rate = plan["collection_rate_policy"]
    assert rate["actual_rate_recorded_per_batch"] is True
    assert rate["abandon_threshold_weeks_without_minimum_progress"] == 12
    assert "At least 1 new eligible confidence-3" in rate["minimum_progress_definition"]


def test_eligibility_schema_freeze_and_hybrid_manual_pipeline():
    schema = _load("eligibility_schema.json")
    assert schema["eligibility_schema_frozen_at_plan_commit"] is True
    assert schema["any_change_requires_new_pre_registered_plan_branch"] is True
    assert schema["selected_pipeline_relationship"] == "HYBRID"
    assert schema["hybrid_promotion_rules"]["rapid_capture_primary_eligible"] is False
    assert schema["hybrid_promotion_rules"]["full_review_required_for_primary_eligibility"] is True
    assert schema["hybrid_promotion_rules"]["direction_source_required_before_primary_eligibility"] is True
    assert schema["hybrid_promotion_rules"]["direction_confidence_required_before_primary_eligibility"] is True
    assert schema["primary_eligible_required_values"]["direction_source"] == "EXISTING_METADATA"
    assert schema["primary_eligible_required_values"]["direction_confidence"] == 3
    assert schema["primary_eligible_required_values"]["evidence_capture_mode"] == "FULL_REVIEW"


def test_forbidden_selection_criteria_and_future_schema():
    plan = _load("collection_plan.json")
    forbidden = set(plan["forbidden_selection_criteria"])
    assert "H3 state" in forbidden
    assert "H4 state" in forbidden
    assert "GOOD/FAST result" in forbidden
    assert "future MFE" in forbidden
    assert "post-entry candles" in forbidden
    assert "manual balancing of H3/H4 states" in forbidden

    future_schema = plan["future_collection_output_schema"]
    assert "direction_source" in future_schema["required_fields"]
    assert "direction_confidence" in future_schema["required_fields"]
    assert "eligibility_schema_commit" in future_schema["required_fields"]
    assert future_schema["required_boolean_values"]["collected_pre_decision_only"] is True
    assert future_schema["required_boolean_values"]["post_entry_data_used_for_inclusion"] is False
    assert future_schema["required_boolean_values"]["h3_h4_state_known_at_collection"] is False
    assert future_schema["required_boolean_values"]["outcome_used_for_inclusion"] is False


def test_rejection_reasons_cover_missing_source_and_bias_failures():
    reasons = _load("rejection_reasons.json")
    codes = {row["code"] for row in reasons["primary_rejection_reasons"]}
    assert "DIRECTION_SOURCE_FIELD_ABSENT" in codes
    assert "DIRECTION_CONFIDENCE_FIELD_ABSENT" in codes
    assert "NON_PRIMARY_DIRECTION_SOURCE" in codes
    assert "DECISION_TIMESTAMP_MISSING" in codes
    assert "ID_RESOLUTION_AMBIGUOUS" in codes
    assert "H3_H4_STATE_USED_FOR_INCLUSION" in codes
    assert "OUTCOME_USED_FOR_INCLUSION" in codes
    assert "POST_ENTRY_DATA_USED_FOR_INCLUSION" in codes
    assert "SOURCE_LINEAGE_AMBIGUOUS" in reasons["fail_closed_reasons"]


def test_acceptance_criteria_and_decision_outcomes_keep_phase_4_blocked():
    plan = _load("collection_plan.json")
    criteria = plan["acceptance_criteria"]
    assert criteria["additional_confidence_3_existing_metadata_samples_minimum"] == 39
    assert criteria["total_confidence_3_including_existing_21_minimum"] == 60
    assert criteria["h3_h4_proxy_computation_during_collection"] is False
    assert criteria["outcome_based_selection"] is False
    assert criteria["phase_4_unlocked"] is False
    assert criteria["matched_control_run"] is False
    assert criteria["scoring_created"] is False
    assert all(outcome["unlocks_phase_4"] is False for outcome in plan["decision_outcomes"])
    assert any(outcome["decision"] == "PAUSE_H3_H4_PATH" for outcome in plan["decision_outcomes"])


def test_doc_records_required_governance_language():
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "Additional forward/new confidence-3 samples required: 39" in text
    assert "Missing `direction_source` must be rejected" in text
    assert "reconstructed timestamps are not primary-eligible" in text
    assert "Selected relationship: `HYBRID`" in text
    assert "RAPID_CAPTURE rows are not primary-eligible" in text
    assert "Do not select samples based on:" in text
    assert "Adelin v2 remains Level 0 / Diagnostic Research" in text
