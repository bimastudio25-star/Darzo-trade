from __future__ import annotations

import importlib
import json
from pathlib import Path

from scripts.create_adelin_v2_tight_sl_zone_retest_proxy_plan import (
    DEFAULT_OUTPUT_DIR,
    PRIMARY_PROXY_CONCEPTS,
    write_plan,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / DEFAULT_OUTPUT_DIR


def _load(name: str):
    return json.loads((OUTPUT_DIR / name).read_text(encoding="utf-8"))


def test_module_import_is_safe():
    module = importlib.import_module("scripts.create_adelin_v2_tight_sl_zone_retest_proxy_plan")
    assert hasattr(module, "write_plan")


def test_write_plan_creates_required_files(tmp_path: Path):
    summary = write_plan(tmp_path)
    assert summary["plan_only"] is True
    for name in [
        "proxy_feature_plan.json",
        "h3_tight_sl_proxy_spec.json",
        "h4_zone_retest_proxy_spec.json",
        "allowed_inputs.json",
        "forbidden_inputs.json",
        "future_execution_schema.json",
        "leakage_guards.json",
        "decision_matrix.json",
        "summary.json",
    ]:
        assert (tmp_path / name).exists()


def test_proxy_plan_files_exist():
    for name in [
        "proxy_feature_plan.json",
        "h3_tight_sl_proxy_spec.json",
        "h4_zone_retest_proxy_spec.json",
        "allowed_inputs.json",
        "forbidden_inputs.json",
        "future_execution_schema.json",
        "leakage_guards.json",
        "decision_matrix.json",
        "summary.json",
    ]:
        assert (OUTPUT_DIR / name).exists()


def test_only_h3_h4_are_primary_proxy_concepts():
    summary = _load("summary.json")
    plan = _load("proxy_feature_plan.json")
    assert summary["primary_proxy_concepts"] == PRIMARY_PROXY_CONCEPTS
    assert plan["primary_proxy_concepts"] == PRIMARY_PROXY_CONCEPTS
    assert [spec["concept_id"] for spec in plan["proxy_specs"]] == PRIMARY_PROXY_CONCEPTS


def test_h3_h4_specs_exist_and_have_required_fields():
    h3 = _load("h3_tight_sl_proxy_spec.json")
    h4 = _load("h4_zone_retest_proxy_spec.json")
    required = {
        "proxy_id",
        "concept_id",
        "proxy_name",
        "human_concept_description",
        "deterministic_formula_description",
        "allowed_timeframes",
        "required_inputs",
        "allowed_inputs",
        "forbidden_inputs",
        "pre_decision_only_rule",
        "candidate_reference_price_definition",
        "normalization_method",
        "threshold_policy",
        "leakage_risks",
        "validation_requirements",
        "future_execution_outputs",
    }
    assert required.issubset(h3)
    assert required.issubset(h4)
    assert h3["proxy_id"] == "H3"
    assert h4["proxy_id"] == "H4"


def test_volume_profile_deferred_and_plan_only_summary():
    summary = _load("summary.json")
    assert summary["plan_only"] is True
    assert summary["ohlc_read"] is False
    assert summary["samples_collected"] is False
    assert summary["replay_run"] is False
    assert summary["matched_control_replay_run"] is False
    assert summary["phase_4_blocked"] is True
    assert summary["runtime_logic_modified"] is False
    assert summary["volume_profile_deferred"] is True
    assert summary["proxy_execution_required_future_branch"] is True


def test_forbidden_inputs_include_post_entry_and_outcome_fields():
    forbidden = set(_load("forbidden_inputs.json")["forbidden_inputs"])
    for name in [
        "post_entry_candles",
        "tp_hit",
        "sl_hit",
        "pnl",
        "r_multiple",
        "future_mfe",
        "future_mae",
        "outcome_derived_thresholds",
        "non_directional_max_move_replay",
    ]:
        assert name in forbidden
    h3 = _load("h3_tight_sl_proxy_spec.json")
    h4 = _load("h4_zone_retest_proxy_spec.json")
    assert forbidden.issubset(set(h3["forbidden_inputs"]))
    assert forbidden.issubset(set(h4["forbidden_inputs"]))


def test_threshold_tuning_from_results_is_forbidden():
    h3 = _load("h3_tight_sl_proxy_spec.json")
    h4 = _load("h4_zone_retest_proxy_spec.json")
    policy_text = json.dumps([h3["threshold_policy"], h4["threshold_policy"]]).lower()
    assert "after observing good/fast separation" in policy_text
    assert "after seeing outcomes" in policy_text
    assert "best-performing band" in policy_text
    leakage = _load("leakage_guards.json")
    assert leakage["threshold_tuning_from_results_forbidden"] is True


def test_future_execution_required_in_separate_branch():
    schema = _load("future_execution_schema.json")
    assert schema["future_execution_required_in_separate_branch"] is True
    assert "matched-control replay" in schema["forbidden_future_actions"]
    assert "Phase 4" in schema["forbidden_future_actions"]
    assert "threshold optimization" in schema["forbidden_future_actions"]


def test_decision_matrix_never_unblocks_phase_4():
    matrix = _load("decision_matrix.json")
    assert matrix["phase_4_blocked"] is True
    assert all(outcome["phase_4_status"] == "blocked" for outcome in matrix["outcomes"])
