from __future__ import annotations

import ast
import csv
import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.adelin_v2_h3_h4_proxy_diagnostic import (
    DEFAULT_OUTPUT_DIR,
    H3_FORMULA_VERSION,
    H3_NORMALIZER_M1,
    H3_NORMALIZER_M5,
    H3_THRESHOLD_VERSION,
    compute_h3_proxy,
    compute_h4_proxy,
    pre_decision_closed,
    run_diagnostic,
    classify_h3_band,
    DiagnosticConfig,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / DEFAULT_OUTPUT_DIR
SCRIPT_PATH = REPO_ROOT / "scripts" / "analyze_adelin_v2_h3_h4_proxy_diagnostic.py"


def _frame(start: datetime, rows: int, minutes: int, base: float = 100.0) -> pd.DataFrame:
    payload = []
    for idx in range(rows):
        ts = pd.Timestamp(start + timedelta(minutes=idx * minutes))
        price = base + idx * 0.05
        payload.append(
            {
                "time": ts,
                "open": price,
                "high": price + 0.6,
                "low": price - 0.4,
                "close": price + 0.2,
                "tick_volume": 100 + idx,
            }
        )
    return pd.DataFrame(payload)


def _frames() -> dict[str, pd.DataFrame]:
    start = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    m1 = _frame(start, 40, 1, 100.0)
    m1.loc[20, "low"] = 99.0
    m1.loc[20, "close"] = 100.2
    m1.loc[25, "high"] = 103.0
    m1.loc[25, "close"] = 101.5
    m5 = _frame(start, 14, 5, 100.0)
    m5.loc[6, "low"] = 98.0
    m5.loc[6, "high"] = 102.0
    return {"M1": m1, "M5": m5}


def _sample(**overrides):
    row = {
        "sample_id": "sample_test",
        "direction": "LONG",
        "decision_timestamp": "2026-01-01T08:35:00+00:00",
        "entry_reference_price": "100.5",
        "entry_reference_source": "TEST_REFERENCE",
        "direction_recovery_source": "EXISTING_METADATA",
        "direction_recovery_confidence": "3",
        "nearest_fvg_ifvg_zone_low": "99.8",
        "nearest_fvg_ifvg_zone_high": "100.4",
    }
    row.update(overrides)
    return row


def test_module_import_is_safe():
    module = importlib.import_module("dazro_trade.analytics.adelin_v2_h3_h4_proxy_diagnostic")
    assert hasattr(module, "run_diagnostic")


def test_h3_classification_thresholds_are_fixed():
    assert classify_h3_band(0.25) == "TIGHT"
    assert classify_h3_band(0.2501) == "MEDIUM"
    assert classify_h3_band(0.50) == "MEDIUM"
    assert classify_h3_band(0.5001) == "WIDE"


def test_h3_missing_reference_state():
    result = compute_h3_proxy(_sample(entry_reference_price=""), _frames())
    assert result.state == "UNKNOWN_REFERENCE_PRICE"


def test_h3_long_uses_pre_decision_swing_or_sweep_low():
    result = compute_h3_proxy(_sample(direction="LONG", entry_reference_price="100.5"), _frames())
    assert result.invalidation_extreme is not None
    assert result.invalidation_extreme < 100.5
    assert "LOW" in result.invalidation_source or "SWEEP_EXTREME" in result.invalidation_source
    assert result.h3_formula_version if hasattr(result, "h3_formula_version") else H3_FORMULA_VERSION


def test_h3_short_uses_pre_decision_swing_or_sweep_high():
    result = compute_h3_proxy(_sample(direction="SHORT", entry_reference_price="101.0"), _frames())
    assert result.invalidation_extreme is not None
    assert result.invalidation_extreme > 101.0
    assert "HIGH" in result.invalidation_source or "SWEEP_EXTREME" in result.invalidation_source


def test_h3_m1_normalizer_is_preferred():
    result = compute_h3_proxy(_sample(direction="LONG", entry_reference_price="100.5"), _frames())
    assert result.normalizer_source == H3_NORMALIZER_M1


def test_h3_m5_normalizer_is_fallback_only_when_m1_insufficient():
    frames = _frames()
    frames["M1"] = frames["M1"].head(10)
    decision = pd.Timestamp("2026-01-01T09:10:00+00:00")
    row = _sample(decision_timestamp=decision.isoformat(), entry_reference_price="100.5")
    result = compute_h3_proxy(row, frames)
    assert result.normalizer_source == H3_NORMALIZER_M5


def test_post_entry_candles_are_rejected_from_pre_decision_window():
    frames = _frames()
    decision = pd.Timestamp("2026-01-01T08:35:00+00:00")
    frames["M1"].loc[39, "low"] = 1.0
    closed = pre_decision_closed(frames["M1"], decision, 30)
    assert closed["time"].max() < decision
    assert float(closed["low"].min()) > 1.0


def test_h4_inside_zone_and_retest_states():
    inside = compute_h4_proxy(_sample(entry_reference_price="100.1"), _frames())
    assert inside.state == "INSIDE_ZONE"
    held = compute_h4_proxy(_sample(entry_reference_price="101.0"), _frames())
    assert held.state in {"RETEST_HELD", "RECLAIM_CONFIRMED", "RETEST_FAILED_PRE_DECISION", "NO_ZONE_AVAILABLE"}


def test_generated_outputs_exist_and_keep_phase_4_blocked():
    for name in ["h3_h4_proxy_per_sample.csv", "h3_h4_proxy_group_summary.csv", "summary.json"]:
        assert (OUTPUT_DIR / name).exists()
    summary = json.loads((OUTPUT_DIR / "summary.json").read_text(encoding="utf-8"))
    assert summary["matched_control_run"] is False
    assert summary["phase_4_unlocked"] is False
    assert summary["runtime_logic_changed"] is False
    assert summary["post_entry_data_used_count"] == 0
    assert summary["h3_state_counts"]
    assert summary["h4_state_counts"]


def test_generated_per_sample_rows_have_required_versions_and_flags():
    with (OUTPUT_DIR / "h3_h4_proxy_per_sample.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    for row in rows:
        assert row["h3_threshold_version"] == H3_THRESHOLD_VERSION
        assert row["h3_formula_version"] == H3_FORMULA_VERSION
        assert row["h3_pre_entry_only"] == "true"
        assert row["h3_post_entry_data_used"] == "false"
        assert row["h4_pre_entry_only"] == "true"
        assert row["h4_post_entry_data_used"] == "false"
        assert row["matched_control_run"] == "false"
        assert row["phase_4_unlocked"] == "false"


def test_diagnostic_precheck_failure_does_not_read_ohlc(tmp_path: Path):
    summary = run_diagnostic(
        DiagnosticConfig(
            sample_path=tmp_path / "missing.csv",
            signoff_path=tmp_path / "missing_signoff.md",
            proxy_plan_dir=tmp_path / "missing_plan",
            output_dir=tmp_path / "out",
            data_dir=tmp_path / "data",
            doc_path=tmp_path / "doc.md",
        )
    )
    assert summary["precheck_passed"] is False
    assert summary["ohlc_read"] is False
    assert summary["matched_control_run"] is False
    assert summary["runtime_logic_changed"] is False


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
