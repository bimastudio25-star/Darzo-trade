from __future__ import annotations

from pathlib import Path

import pandas as pd

from dazro_trade.analytics.strategy_5_asymmetric_liquidity_reclaim_2r3r import (
    OUTPUT_FIELDS,
    Strategy5Config,
    evaluate_outcome,
    scan_strategy_5,
    target_for_mode,
    write_outputs,
)
from scripts import analyze_strategy_5_asymmetric_liquidity_reclaim_2r3r as script


def test_fixed_2r_target_equals_2r():
    target, r = target_for_mode("LONG", 100.0, 2.0, "fixed_2r", 110.0, Strategy5Config())
    assert target == 104.0
    assert r == 2.0


def test_fixed_3r_target_equals_3r():
    target, r = target_for_mode("SHORT", 100.0, 2.0, "fixed_3r", 90.0, Strategy5Config())
    assert target == 94.0
    assert r == 3.0


def test_no_1r_exit_fields_or_modes_exist():
    joined = " ".join(OUTPUT_FIELDS).lower()
    assert "1r" not in joined
    assert "partial_1r" not in Path("dazro_trade/analytics/strategy_5_asymmetric_liquidity_reclaim_2r3r.py").read_text(encoding="utf-8").lower()


def test_trades_below_min_rr_are_rejected_by_structural_mode():
    target, r = target_for_mode("LONG", 100.0, 2.0, "structural_min_2r", 103.0, Strategy5Config())
    assert target == 103.0
    assert r == 1.5
    assert r < 2.0


def test_stop_is_beyond_sweep_extreme_in_generated_long_candidate():
    m15 = pd.DataFrame([
        {"time": "2026-05-20T00:00:00Z", "open": 100, "high": 101, "low": 99, "close": 100, "tick_volume": 1},
        {"time": "2026-05-20T00:15:00Z", "open": 100, "high": 101, "low": 98, "close": 100.2, "tick_volume": 1},
        {"time": "2026-05-20T00:30:00Z", "open": 100.2, "high": 103, "low": 101.5, "close": 102.8, "tick_volume": 1},
        {"time": "2026-05-20T00:45:00Z", "open": 102.8, "high": 103, "low": 99, "close": 101, "tick_volume": 1},
        {"time": "2026-05-20T01:00:00Z", "open": 101, "high": 106, "low": 101, "close": 105, "tick_volume": 1},
    ])
    h1 = pd.DataFrame([
        {"time": "2026-05-19T23:00:00Z", "open": 100, "high": 108, "low": 99, "close": 100, "tick_volume": 1},
        {"time": "2026-05-20T00:00:00Z", "open": 100, "high": 103, "low": 98, "close": 102, "tick_volume": 1},
    ])
    result = scan_strategy_5({"M15": m15, "H1": h1}, Strategy5Config(max_context_candles=50, max_forward_candles=1))
    rows = [r for r in result["candidates"] if r["direction"] == "LONG" and r["entry_price"] != ""]
    assert rows
    assert all(float(r["stop_loss"]) < 98.0 for r in rows)
    assert all(r["order_sent"] is False and r["telegram_sent"] is False and r["broker_called"] is False for r in rows)


def test_missing_data_creates_rejection_not_crash():
    result = scan_strategy_5({}, Strategy5Config())
    assert result["rejected"]
    assert result["rejected"][0]["rejection_reason"] == "REQUIRED_DATA_MISSING"


def test_output_files_created_safely(tmp_path):
    result = scan_strategy_5({}, Strategy5Config())
    paths = write_outputs(result, tmp_path / "out")
    assert Path(paths["candidates"]).exists()
    assert Path(paths["accepted"]).exists()
    assert Path(paths["rejected"]).exists()
    assert Path(paths["summary"]).exists()
    assert Path(paths["diagnostic"]).exists()
    assert Path(paths["mode_comparison"]).exists()


def test_script_import_safe_and_no_forbidden_calls():
    assert hasattr(script, "main")
    source = Path("dazro_trade/analytics/strategy_5_asymmetric_liquidity_reclaim_2r3r.py").read_text(encoding="utf-8").lower()
    assert "order_send(" not in source
    assert "telegram_bot" not in source
    assert "broker_called = true" not in source


def test_outcome_timeout_without_target_or_stop():
    forward = pd.DataFrame([
        {"time": "2026-05-20T00:15:00Z", "open": 100, "high": 101, "low": 99, "close": 100},
    ])
    assert evaluate_outcome("LONG", forward, 95.0, 105.0) == "TIMEOUT"
