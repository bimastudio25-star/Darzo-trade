from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

from scripts.analyze_adelin_v2_expanded_sample_diagnostic_execution import (
    DEFAULT_OUTPUT_DIR,
    DIRECTION_RULE_VERSION,
    ExpandedDiagnosticConfig,
    allowed_sample_source,
    final_verdict,
    leakage_check,
    minimum_n_report,
    validate_signed_plan,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / DEFAULT_OUTPUT_DIR
SCRIPT_PATH = REPO_ROOT / "scripts" / "analyze_adelin_v2_expanded_sample_diagnostic_execution.py"


def _load(name: str):
    return json.loads((OUTPUT_DIR / name).read_text(encoding="utf-8"))


def test_module_import_is_safe():
    module = importlib.import_module("scripts.analyze_adelin_v2_expanded_sample_diagnostic_execution")
    assert hasattr(module, "run_execution")


def test_signoff_required_before_execution(tmp_path: Path):
    valid, details = validate_signed_plan(ExpandedDiagnosticConfig(signoff_path=tmp_path / "missing.md"))
    assert valid is False
    assert details["signoff_exists"] is False
    assert details["plan_valid"] is False


def test_generated_outputs_exist():
    for name in [
        "expanded_sample_inventory.csv",
        "expanded_sample_inventory.json",
        "expanded_sample_summary.json",
        "h1_h2_feature_results.csv",
        "h1_h2_feature_results.json",
        "confidence_stratification_summary.csv",
        "confidence_stratification_summary.json",
        "minimum_n_gate_report.json",
        "leakage_check_report.json",
        "excluded_samples.csv",
        "human_review_priority.csv",
        "verdict.json",
        "execution_summary.json",
    ]:
        assert (OUTPUT_DIR / name).exists()


def test_plan_validation_requires_post_hoc_disclosure_and_not_validated_status():
    summary = _load("execution_summary.json")
    validation = summary["plan_validation"]
    assert validation["plan_valid"] is True
    assert validation["signoff_decision_approve"] is True
    assert validation["post_hoc_disclosure_exists"] is True
    assert validation["h1_h2_not_validated"] is True
    assert validation["minimum_n_gates_exist"] is True
    assert validation["direction_rule_version"] == DIRECTION_RULE_VERSION


def test_sample_selection_rejects_manual_cherry_pick_source():
    assert allowed_sample_source("manual_cherry_pick") is False
    report = leakage_check(["fvg_ifvg_near_20p"], [{"sample_source": "MANUAL_CHERRY_PICK"}])
    assert report["leakage_passed"] is False
    assert report["manual_cherry_pick_sources_found"] == ["MANUAL_CHERRY_PICK"]


def test_minimum_n_gates_calculated_and_good_lte_10_caps_verdict():
    rows = [{"diagnostic_outcome_group": "GOOD_FAST_REACTION"}] * 10
    rows += [{"diagnostic_outcome_group": "FAST_FAILURE"}] * 40
    rows += [{"diagnostic_outcome_group": "MIXED_REACTION"}] * 20
    gates = minimum_n_report(rows)
    assert gates["total_samples"] == 70
    assert gates["good_fast_reaction_n"] == 10
    assert gates["fast_failure_n"] == 40
    assert gates["good_lte_10_gate_active"] is True
    verdict, reason = final_verdict(gates, [], [], {"leakage_passed": True})
    assert verdict == "MIXED_AMBIGUOUS_SMALL_N"
    assert "N <= 10" in reason


def test_h1_h2_only_primary_hypotheses_and_secondary_features_do_not_drive_verdict():
    summary = _load("execution_summary.json")
    h1_h2 = _load("h1_h2_feature_results.json")
    secondary_names = {row["feature_name"] for row in summary["secondary_tracked_feature_summary"]}
    assert [row["feature_name"] for row in h1_h2] == ["fvg_ifvg_near_20p", "liquidity_htf_recent_level"]
    assert secondary_names == {"m1_large_body_ge_0_60", "m1_close_high_ge_0_70"}
    assert summary["final_verdict"] == "HYPOTHESES_FAIL_TO_REPEAT"
    assert summary["h1_result"]["effect_repeats_prior_direction"] is True
    assert summary["h2_result"]["effect_repeats_prior_direction"] is False


def test_confidence_stratification_required_and_present():
    summary = _load("execution_summary.json")
    c3 = summary["confidence_3_sensitivity"]
    c2 = summary["confidence_2_caution"]
    assert c3 and c2
    assert all(row["direction_confidence"] == 3 for row in c3)
    assert all(row["direction_confidence"] == 2 for row in c2)
    assert all(row["phase_4_blocked"] is True for row in c3 + c2)


def test_leakage_check_catches_forbidden_features_and_generated_report_passes():
    generated = _load("leakage_check_report.json")
    assert generated["leakage_passed"] is True
    assert generated["forbidden_fields_found"] == []
    assert generated["post_entry_candles_used_for_h1_h2"] is False
    failed = leakage_check(["future_mfe"], [])
    assert failed["leakage_passed"] is False
    assert failed["post_entry_feature_usage_detected"] is True


def test_phase_4_always_blocked_and_no_matched_control_or_runtime_logic():
    summary = _load("execution_summary.json")
    verdict = _load("verdict.json")
    assert summary["phase_4_blocked"] is True
    assert verdict["phase_4_blocked"] is True
    assert summary["matched_control_replay_run"] is False
    assert summary["replay_run"] is False
    assert summary["candidate_generation_run"] is False
    safety = summary["safety"]
    assert safety["runtime_logic_modified"] is False
    assert safety["strategy_2_touched"] is False
    assert safety["strategy_3_touched"] is False
    assert safety["live_trading_enabled"] is False
    assert safety["orders_enabled"] is False
    assert safety["telegram_enabled"] is False
    assert safety["broker_execution_enabled"] is False
    assert safety["v3_stash_applied_or_popped"] is False


def test_execution_summary_records_pre_entry_ohlc_use_only():
    summary = _load("execution_summary.json")
    assert summary["ohlc_read"] is True
    assert summary["pre_entry_only_feature_extraction"] is True
    assert summary["post_entry_candles_used_for_h1_h2"] is False
    assert summary["ohlc_timeframes_loaded"] >= 1


def test_script_has_no_broker_order_telegram_or_matched_control_calls():
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    forbidden_import_roots = {"telegram", "MetaTrader5", "mt5_handler", "runtime"}
    forbidden_call_names = {"order_send", "send_message"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_import_roots
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_import_roots
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                assert func.id not in forbidden_call_names
            if isinstance(func, ast.Attribute):
                assert func.attr not in forbidden_call_names
