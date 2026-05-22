from __future__ import annotations

import importlib
import json
from pathlib import Path

from scripts.create_adelin_v2_good_fast_expanded_sample_plan import (
    DEFAULT_OUTPUT_DIR,
    write_plan,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / DEFAULT_OUTPUT_DIR
REQUIRED_FILES = [
    "expanded_sample_plan.json",
    "frozen_hypotheses.json",
    "sample_collection_schema.json",
    "inclusion_exclusion_rules.json",
    "minimum_n_gates.json",
    "future_execution_schema.json",
    "decision_matrix.json",
    "summary.json",
]


def _load(name: str):
    return json.loads((OUTPUT_DIR / name).read_text(encoding="utf-8"))


def test_module_import_is_safe():
    module = importlib.import_module("scripts.create_adelin_v2_good_fast_expanded_sample_plan")
    assert hasattr(module, "write_plan")


def test_write_plan_creates_required_files(tmp_path: Path):
    write_plan(tmp_path)
    assert all((tmp_path / name).exists() for name in REQUIRED_FILES)


def test_generated_plan_files_exist():
    assert all((OUTPUT_DIR / name).exists() for name in REQUIRED_FILES)


def test_summary_confirms_plan_only_and_no_execution():
    payload = _load("summary.json")
    assert payload["plan_only"] is True
    assert payload["samples_collected"] is False
    assert payload["ohlc_read"] is False
    assert payload["replay_run"] is False
    assert payload["matched_control_replay_run"] is False
    assert payload["phase_4_blocked"] is True
    assert payload["live_trading_enabled"] is False
    assert payload["orders_enabled"] is False
    assert payload["telegram_enabled"] is False
    assert payload["broker_execution_enabled"] is False
    assert payload["profitability_claim_made"] is False


def test_primary_hypotheses_are_exactly_h1_h2():
    summary = _load("summary.json")
    frozen = _load("frozen_hypotheses.json")
    assert summary["primary_hypotheses"] == ["fvg_ifvg_near_20p", "liquidity_htf_recent_level"]
    assert [item["feature_name"] for item in frozen["primary_hypotheses"]] == [
        "fvg_ifvg_near_20p",
        "liquidity_htf_recent_level",
    ]


def test_post_hoc_origin_disclosure_exists():
    summary = _load("summary.json")
    frozen = _load("frozen_hypotheses.json")
    disclosure = summary["hypothesis_origin_disclosure"]
    assert disclosure["hypothesis_origin"] == "post_hoc_from_underpowered_exploratory_diagnostic"
    assert disclosure["originating_good_fast_reaction_n"] == 10
    assert disclosure["originating_fast_failure_n"] == 27
    assert disclosure["originating_verdict"] == "MIXED_AMBIGUOUS_SMALL_N"
    assert disclosure["validation_status"] == "not_validated"
    assert disclosure["may_be_rejected_by_future_test"] is True
    assert disclosure["not_deployment_evidence"] is True
    assert "FAST_FAILURE N=27" in disclosure["disclosure"]
    assert frozen["hypothesis_origin_disclosure"] == disclosure


def test_h1_h2_are_post_hoc_and_not_validated():
    frozen = _load("frozen_hypotheses.json")
    for hypothesis in frozen["primary_hypotheses"]:
        assert hypothesis["hypothesis_origin"] == "post_hoc_from_underpowered_exploratory_diagnostic"
        assert hypothesis["originating_good_fast_reaction_n"] == 10
        assert hypothesis["originating_fast_failure_n"] == 27
        assert hypothesis["originating_verdict"] == "MIXED_AMBIGUOUS_SMALL_N"
        assert hypothesis["validation_status"] == "not_validated"
        assert hypothesis["may_be_rejected_by_future_test"] is True
        assert hypothesis["not_deployment_evidence"] is True


def test_secondary_features_are_not_primary_hypotheses():
    summary = _load("summary.json")
    assert summary["secondary_tracked_features"] == ["m1_large_body_ge_0_60", "m1_close_high_ge_0_70"]
    assert not set(summary["secondary_tracked_features"]).intersection(summary["primary_hypotheses"])
    frozen = _load("frozen_hypotheses.json")
    assert all(item["role"] == "SECONDARY_TRACKED_ONLY" for item in frozen["secondary_tracked_features"])


def test_minimum_n_gates_exist_and_preserve_previous_gate():
    gates = _load("minimum_n_gates.json")
    assert gates["target_total_expanded_samples"] == 80
    assert gates["hard_minimum_total_samples_for_useful_expanded_diagnostic"] == 60
    assert gates["target_good_fast_reaction_n"] == 20
    assert gates["hard_minimum_good_fast_reaction_n"] == 11
    assert gates["if_good_fast_reaction_n_lte_10"]["strongest_allowed_verdict"] == "MIXED_AMBIGUOUS_SMALL_N"
    assert gates["if_good_fast_reaction_n_lte_10"]["phase_4_blocked"] is True
    assert gates["target_fast_failure_n"] == 40
    assert gates["hard_minimum_fast_failure_n"] == 25


def test_future_execution_cannot_auto_unlock_phase_4():
    matrix = _load("decision_matrix.json")
    assert matrix["phase_4_blocked"] is True
    assert all(item["phase_4_status"] != "unblocked" for item in matrix["outcomes"])
    repeating = next(item for item in matrix["outcomes"] if item["decision_code"] == "HYPOTHESES_REPEAT_WITH_SUFFICIENT_N")
    assert "no automatic Phase 4" in repeating["phase_4_status"]


def test_forbidden_interpretations_registered():
    schema = _load("future_execution_schema.json")
    forbidden = set(schema["forbidden"])
    assert "build a score" in forbidden
    assert "convert H1/H2 into live filters" in forbidden
    assert "claim profitability" in forbidden
    assert "run matched-control replay" in forbidden
    assert "optimize thresholds" in forbidden


def test_sample_collection_schema_prevents_selection_bias():
    schema = _load("sample_collection_schema.json")
    assert "not because they support or refute H1/H2" in schema["sample_selection_rule"]
    assert schema["primary_comparison_groups"] == ["GOOD_FAST_REACTION", "FAST_FAILURE"]
    assert schema["secondary_review_groups"] == ["MIXED_REACTION", "CHOP_AFTER_ENTRY"]


def test_h2_htf_definition_is_frozen():
    schema = _load("future_execution_schema.json")
    h2 = schema["feature_definitions"]["liquidity_htf_recent_level"]
    assert h2["htf_definition"] == "H1 recent high/low from the prior 24h or M15 recent high/low from the prior 6h."
    assert h2["recency_window"].startswith("H1: [decision_timestamp - 24h")
    assert h2["excluded_timeframes"] == ["M5", "M1"]
