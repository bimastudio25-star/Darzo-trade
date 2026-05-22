from __future__ import annotations

import ast
import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from scripts.analyze_adelin_v2_direction_metadata_recovery import (
    RecoveryConfig,
    recover_sample_direction,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _sweep_frames() -> dict[str, pd.DataFrame]:
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(10):
        ts = start + timedelta(minutes=i)
        rows.append(
            {
                "time": pd.Timestamp(ts),
                "open": 100.0,
                "high": 100.4,
                "low": 99.4,
                "close": 100.0,
            }
        )
    # A downward sweep at 00:04, at least five minutes before the 00:10 anchor.
    rows[4].update({"open": 99.6, "high": 99.8, "low": 98.7, "close": 99.6})
    rows[5].update({"open": 99.6, "high": 100.2, "low": 99.5, "close": 100.1})
    return {"M1": pd.DataFrame(rows), "M5": pd.DataFrame()}


def test_module_import_is_safe():
    module = importlib.import_module("scripts.analyze_adelin_v2_direction_metadata_recovery")
    assert hasattr(module, "run_recovery")


def test_existing_direction_is_preserved():
    row = recover_sample_direction(
        {"sample_id": "s1", "direction_guess": "LONG", "anchor_timestamp": "2026-01-01T00:10:00+00:00"},
        {},
        RecoveryConfig(),
        0.1,
    )
    assert row["final_direction"] == "LONG"
    assert row["direction_source"] == "EXISTING_METADATA"
    assert row["direction_confidence"] == 3
    assert row["used_post_entry_data"] is False


def test_missing_direction_recovers_from_candidate_side_metadata():
    row = recover_sample_direction(
        {
            "sample_id": "s2",
            "direction_guess": "UNKNOWN",
            "candidate_side": "sell",
            "anchor_timestamp": "2026-01-01T00:10:00+00:00",
        },
        {},
        RecoveryConfig(),
        0.1,
    )
    assert row["recovered_direction"] == "SHORT"
    assert row["direction_source"] == "CANDIDATE_SIDE_METADATA"
    assert row["direction_confidence"] == 3


def test_missing_direction_recovers_from_pre_decision_sweep():
    row = recover_sample_direction(
        {"sample_id": "s3", "direction_guess": "UNKNOWN", "anchor_timestamp": "2026-01-01T00:10:00+00:00"},
        _sweep_frames(),
        RecoveryConfig(sweep_lookback_minutes=15, sweep_min_anchor_delay_minutes=5),
        0.1,
    )
    assert row["recovered_direction"] == "LONG"
    assert row["direction_source"] == "PRE_DECISION_SWEEP_INFERENCE"
    assert row["direction_confidence"] == 2
    assert "POST_ANCHOR_CANDLES_EXCLUDED" in row["direction_recovery_reason"]


def test_conflicting_pre_entry_evidence_results_in_unknown():
    row = recover_sample_direction(
        {
            "sample_id": "s4",
            "direction_guess": "UNKNOWN",
            "candidate_side": "buy",
            "anchor_timestamp": "2026-01-01T00:10:00+00:00",
        },
        {},
        RecoveryConfig(),
        0.1,
        reason_codes="M15_SWING_HIGH_SWEEP_VISUAL_CANDIDATE",
    )
    assert row["final_direction"] == "UNKNOWN"
    assert row["direction_source"] == "CONFLICTING_DIRECTION_EVIDENCE"
    assert row["usable_for_directional_replay"] is False


def test_generated_recovery_summary_counts_and_post_entry_guard():
    path = REPO_ROOT / "backtests" / "reports" / "adelin_v2_direction_metadata_recovery" / "direction_recovery_summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["total_samples"] == 40
    assert payload["existing_direction_count"] == 21
    assert payload["missing_direction_count"] == 19
    assert payload["recovered_direction_count"] == 19
    assert payload["final_direction_unknown_count"] == 0
    assert payload["used_post_entry_data_count"] == 0
    assert "DIRECTION_COVERAGE_IMPROVED" in payload["verdict_flags"]


def test_direction_recovery_rows_are_pre_entry_only():
    path = REPO_ROOT / "backtests" / "reports" / "adelin_v2_direction_metadata_recovery" / "direction_recovery.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert rows
    assert all(row["pre_entry_only"] is True for row in rows)
    assert all(row["used_post_entry_data"] is False for row in rows)


def test_recovered_diagnostics_remove_unknown_direction_limitation():
    path = (
        REPO_ROOT
        / "backtests"
        / "reports"
        / "adelin_v2_preentry_outcome_diagnostics_direction_recovered"
        / "summary.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["samples_with_sufficient_data"] == 40
    assert payload["samples_with_insufficient_data"] == 0
    assert payload["direction_recovery_applied"] is True
    assert "UNKNOWN_DIRECTION_NO_DIRECTIONAL_REPLAY" not in payload["limitations"]


def test_tag_semantics_are_multi_label_confirmed():
    path = REPO_ROOT / "backtests" / "reports" / "adelin_v2_direction_metadata_recovery" / "direction_recovery_summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["diagnostic_tags_multi_label_confirmed"] is True


def test_script_has_no_broker_order_telegram_calls():
    path = REPO_ROOT / "scripts" / "analyze_adelin_v2_direction_metadata_recovery.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
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
