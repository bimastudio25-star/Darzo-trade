from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from scripts.create_adelin_v2_good_vs_fast_failure_diagnostic_plan import (
    DEFAULT_OUTPUT_DIR,
    minimum_n_gate_status,
    write_plan,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / DEFAULT_OUTPUT_DIR
REQUIRED_FILES = [
    "diagnostic_plan.json",
    "allowed_features.json",
    "excluded_features.json",
    "comparison_schema.json",
    "decision_matrix.json",
    "summary.json",
]


def _load(name: str) -> Any:
    return json.loads((OUTPUT_DIR / name).read_text(encoding="utf-8"))


def _walk_values(value: Any) -> list[Any]:
    out = [value]
    if isinstance(value, dict):
        for item in value.values():
            out.extend(_walk_values(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(_walk_values(item))
    return out


def test_module_import_is_safe():
    module = importlib.import_module("scripts.create_adelin_v2_good_vs_fast_failure_diagnostic_plan")
    assert hasattr(module, "write_plan")


def test_write_plan_creates_required_files(tmp_path: Path):
    write_plan(tmp_path)
    assert all((tmp_path / name).exists() for name in REQUIRED_FILES)


def test_generated_plan_files_exist():
    assert all((OUTPUT_DIR / name).exists() for name in REQUIRED_FILES)


def test_summary_confirms_plan_only_no_execution():
    payload = _load("summary.json")
    assert payload["plan_only"] is True
    assert payload["ohlc_read"] is False
    assert payload["comparison_executed"] is False
    assert payload["feature_vs_outcome_statistics_generated"] is False
    assert payload["phase_4_blocked"] is True
    assert payload["replay_run"] is False
    assert payload["matched_control_replay_run"] is False


def test_forbidden_leakage_fields_are_registered():
    payload = _load("excluded_features.json")
    names = {item["name"] for item in payload["excluded_features"]}
    assert "TP hit" in names
    assert "SL hit" in names
    assert "future MFE" in names
    assert "future MAE" in names
    assert "post-entry candles" in names
    assert "non-directional max move replay as primary evidence" in names


def test_confidence_guardrails_are_registered():
    plan = _load("diagnostic_plan.json")
    summary = _load("summary.json")
    handling = plan["direction_confidence_handling"]
    assert "confidence_2_guardrail" in handling
    assert "confidence 2" in handling["confidence_2_guardrail"].lower()
    assert handling["mandatory_sensitivity_analysis"] == "confidence_3_only"
    assert summary["confidence_3_sensitivity_required"] is True


def test_sample_groups_are_pre_registered():
    schema = _load("comparison_schema.json")
    assert schema["primary_groups"] == ["GOOD_FAST_REACTION", "FAST_FAILURE"]
    assert schema["secondary_review_groups"] == ["MIXED_REACTION", "CHOP_AFTER_ENTRY"]
    assert "must not be included" in schema["secondary_group_rule"]


def test_decision_matrix_keeps_phase_4_blocked():
    matrix = _load("decision_matrix.json")
    assert matrix["phase_4_blocked"] is True
    assert "minimum_n_thresholds" in matrix
    codes = {item["decision_code"] for item in matrix["outcomes"]}
    assert codes == {
        "STRONG_DESCRIPTIVE_SEPARATION",
        "CONFIDENCE_2_ONLY_SEPARATION",
        "NO_STABLE_SEPARATION",
        "LEAKAGE_DEPENDENT_SEPARATION",
        "MIXED_AMBIGUOUS_SMALL_N",
    }
    assert all(item["phase_4_status"] != "unblocked" for item in matrix["outcomes"])


def test_minimum_n_gate_blocks_any_primary_group_at_or_below_10():
    gate = minimum_n_gate_status({"GOOD_FAST_REACTION": 10, "FAST_FAILURE": 27})
    assert gate["gate_tripped"] is True
    assert gate["blocking_primary_groups"] == ["GOOD_FAST_REACTION"]
    assert gate["strong_descriptive_separation_forbidden"] is True
    assert gate["phase_4_blocked"] is True
    assert gate["strongest_allowed_verdict"] == "MIXED_AMBIGUOUS_SMALL_N"

    other_group_gate = minimum_n_gate_status({"GOOD_FAST_REACTION": 30, "FAST_FAILURE": 10})
    assert other_group_gate["gate_tripped"] is True
    assert other_group_gate["blocking_primary_groups"] == ["FAST_FAILURE"]
    assert other_group_gate["strong_descriptive_separation_forbidden"] is True
    assert other_group_gate["strongest_allowed_verdict"] == "MIXED_AMBIGUOUS_SMALL_N"


def test_generated_minimum_n_gate_blocks_strong_separation():
    matrix = _load("decision_matrix.json")
    gate = matrix["minimum_n_thresholds"]
    assert gate["current_good_fast_reaction_n"] == 10
    assert gate["current_fast_failure_n"] == 27
    assert gate["minimum_n_threshold"] == 10
    assert gate["gate_tripped"] is True
    assert gate["strong_descriptive_separation_forbidden"] is True
    assert gate["strongest_allowed_verdict"] == "MIXED_AMBIGUOUS_SMALL_N"
    strong = next(item for item in matrix["outcomes"] if item["decision_code"] == "STRONG_DESCRIPTIVE_SEPARATION")
    assert strong["blocked_when"] == "any primary group has N <= 10"


def test_summary_records_minimum_n_gate_and_no_replay():
    summary = _load("summary.json")
    assert summary["minimum_n_gate_enforced"] is True
    assert summary["minimum_n_thresholds"]["gate_tripped"] is True
    assert summary["strong_descriptive_separation_allowed_under_current_n"] is False
    assert summary["strongest_allowed_verdict_under_current_n"] == "MIXED_AMBIGUOUS_SMALL_N"
    assert summary["plan_only"] is True
    assert summary["ohlc_read"] is False
    assert summary["comparison_executed"] is False
    assert summary["replay_run"] is False
    assert summary["matched_control_replay_run"] is False


def test_no_output_contains_real_feature_vs_outcome_statistics():
    forbidden_actual_stat_keys = {
        "computed_feature_frequencies",
        "computed_difference_in_proportions",
        "feature_outcome_rows",
        "feature_vs_outcome_table",
        "real_feature_frequency_table",
    }
    for name in REQUIRED_FILES:
        payload = _load(name)
        if isinstance(payload, dict):
            assert forbidden_actual_stat_keys.isdisjoint(payload.keys())
        values = _walk_values(payload)
        assert "computed_feature_frequencies" not in values
        assert "real_feature_frequency_table" not in values
    summary = _load("summary.json")
    assert summary["new_outcome_statistics_generated"] is False
    assert summary["feature_vs_outcome_statistics_generated"] is False


def test_allowed_features_are_pre_entry_only():
    payload = _load("allowed_features.json")
    assert payload["allowed_features"]
    assert all(item["pre_entry_only"] is True for item in payload["allowed_features"])
