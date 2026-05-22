from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

from scripts.analyze_adelin_v2_good_vs_fast_failure_diagnostic_execution import (
    DEFAULT_OUTPUT_DIR,
    FINAL_VERDICT,
    ExecutionConfig,
    leakage_check,
    validate_plan,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / DEFAULT_OUTPUT_DIR
SCRIPT_PATH = REPO_ROOT / "scripts" / "analyze_adelin_v2_good_vs_fast_failure_diagnostic_execution.py"


def _load(name: str):
    return json.loads((OUTPUT_DIR / name).read_text(encoding="utf-8"))


def test_module_import_is_safe():
    module = importlib.import_module("scripts.analyze_adelin_v2_good_vs_fast_failure_diagnostic_execution")
    assert hasattr(module, "run_execution")


def test_signoff_required_before_execution(tmp_path: Path):
    valid, details = validate_plan(ExecutionConfig(signoff_path=tmp_path / "missing_signoff.md"))
    assert valid is False
    assert details["signoff_exists"] is False
    assert details["plan_valid"] is False


def test_generated_execution_outputs_exist():
    for name in [
        "execution_summary.json",
        "comparison_results.csv",
        "feature_frequency_summary.csv",
        "difference_in_proportions.csv",
        "confidence_sensitivity_summary.csv",
        "confidence_2_caution_table.csv",
        "leakage_check_report.json",
        "human_review_priority.csv",
        "decision_matrix_applied.json",
        "verdict.json",
    ]:
        assert (OUTPUT_DIR / name).exists()


def test_minimum_n_gate_active_and_verdict_capped():
    summary = _load("execution_summary.json")
    verdict = _load("verdict.json")
    assert summary["signoff_verified"] is True
    assert summary["plan_loaded"] is True
    assert summary["minimum_n_gate_active"] is True
    assert summary["good_fast_reaction_n"] == 10
    assert summary["fast_failure_n"] == 27
    assert summary["strong_descriptive_separation_forbidden"] is True
    assert summary["final_verdict"] == FINAL_VERDICT
    assert verdict["final_verdict"] == FINAL_VERDICT
    assert "VERDICT_CAPPED_AT_MIXED_AMBIGUOUS_SMALL_N" in verdict["verdict_flags"]


def test_phase_4_and_matched_control_remain_blocked():
    summary = _load("execution_summary.json")
    verdict = _load("verdict.json")
    assert summary["phase_4_blocked"] is True
    assert summary["phase_4_started"] is False
    assert summary["matched_control_replay_run"] is False
    assert verdict["matched_control_replay_run"] is False
    assert "NO_MATCHED_CONTROL_REPLAY" in verdict["verdict_flags"]


def test_secondary_groups_excluded_from_primary_comparison():
    summary = _load("execution_summary.json")
    decision = _load("decision_matrix_applied.json")
    assert summary["primary_samples_compared"] == 37
    assert summary["secondary_groups_excluded"] == ["MIXED_REACTION", "CHOP_AFTER_ENTRY"]
    assert summary["secondary_group_counts"] == {"CHOP_AFTER_ENTRY": 1, "MIXED_REACTION": 2}
    assert decision["secondary_groups_excluded"] == ["MIXED_REACTION", "CHOP_AFTER_ENTRY"]


def test_leakage_check_passes_and_rejects_forbidden_feature_name():
    report = _load("leakage_check_report.json")
    assert report["leakage_passed"] is True
    assert report["forbidden_fields_found"] == []
    assert report["post_entry_feature_usage_detected"] is False
    assert report["post_entry_candles_used"] is False
    failed = leakage_check(["future MFE"], {"excluded_features": [{"name": "future MFE"}]})
    assert failed["leakage_passed"] is False
    assert failed["post_entry_feature_usage_detected"] is True


def test_confidence_outputs_exist_and_are_stratified():
    summary = _load("execution_summary.json")
    assert summary["confidence_3_only_sensitivity_top"]
    assert summary["confidence_2_caution_top"]
    assert all(row["direction_confidence"] == 3 for row in summary["confidence_3_only_sensitivity_top"])
    assert all("WEAK_RESEARCH_ONLY_CONFIDENCE_2" in row["caution"] for row in summary["confidence_2_caution_top"])


def test_execution_summary_safety_flags():
    summary = _load("execution_summary.json")
    assert summary["ohlc_read"] is False
    assert summary["pre_entry_only"] is True
    assert summary["post_entry_candles_used"] is False
    assert summary["comparison_executed"] is True
    safety = summary["safety"]
    assert safety["runtime_logic_modified"] is False
    assert safety["strategy_2_touched"] is False
    assert safety["strategy_3_touched"] is False
    assert safety["live_trading_enabled"] is False
    assert safety["orders_enabled"] is False
    assert safety["telegram_enabled"] is False
    assert safety["broker_execution_enabled"] is False
    assert safety["v3_stash_applied_or_popped"] is False


def test_script_has_no_broker_order_telegram_calls():
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
