from __future__ import annotations

import json

from dazro_trade.analytics.strategy_2_hourly_session_diagnostics import (
    build_strategy_2_hourly_session_diagnostics,
    extract_trade_hour,
    in_14_16_window,
    write_strategy_2_hourly_session_outputs,
)


def _row(idx: int, *, hour: int, r: float, outcome: str = "TP1", strategy: str = "strategy_2_liquidity_expansion") -> dict[str, str]:
    return {
        "trade_id": str(idx),
        "strategy": strategy,
        "entry_timestamp": f"2026-05-19T{hour:02d}:15:00+00:00",
        "symbol": "XAUUSD",
        "direction": "LONG",
        "outcome": outcome,
        "r_multiple": str(r),
        "result_baseline_R": str(r),
        "result_hard_be_R": "0" if outcome == "BE" else str(r),
        "result_m5_confirmed_be_R": str(r),
        "result_structural_be_R": str(r),
        "result_partial15_R": str(r + 0.25),
        "result_partial20_R": str(r + 0.1),
        "result_exit_bad_m5_R": str(r),
        "result_hold_healthy_retest_R": str(r),
        "result_runner_liquidity_R": str(r + 0.5),
        "hit_be_10": "True",
        "hit_partial_15": "True" if r > 0 else "False",
        "hit_partial_20": "False",
        "runner_opportunity": "LIQUIDITY_MAGNET_RUN" if r > 0 else "STANDARD_TP",
        "mfe_R": "2.0",
        "mae_R": "0.5",
    }


def test_hour_extraction_and_14_16_filter_work():
    row = _row(1, hour=14, r=1)
    assert extract_trade_hour(row) == 14
    assert in_14_16_window(row) is True
    assert in_14_16_window(_row(2, hour=16, r=1)) is False


def test_hourly_session_aggregation_computes_core_metrics():
    rows = [_row(1, hour=14, r=1), _row(2, hour=15, r=-1, outcome="SL"), _row(3, hour=9, r=2)]
    report = build_strategy_2_hourly_session_diagnostics(rows, rows[0].keys(), source_path="x.csv")
    summary = report["summary"]
    assert summary["full_day"]["trades"] == 3
    assert summary["full_day"]["PF"] == 3.0
    assert summary["full_day"]["WR"] == 0.6667
    assert summary["full_day"]["AvgR"] == 0.6667
    assert summary["full_day"]["total_R"] == 2.0
    assert summary["window_14_16"]["trades"] == 2
    assert summary["live_filter_activated"] is False


def test_management_variants_are_compared_without_activating_live_filter():
    rows = [_row(1, hour=14, r=1), _row(2, hour=15, r=-1, outcome="SL")]
    report = build_strategy_2_hourly_session_diagnostics(rows, rows[0].keys(), source_path="x.csv")
    variants = report["variant_summary"]
    assert variants["baseline"]["trades"] == 2
    assert variants["partial_15"]["AvgR"] == 0.25
    assert variants["runner_liquidity"]["AvgR"] == 0.5
    assert report["summary"]["live_filter_activated"] is False


def test_strategy_2_outputs_are_written(tmp_path):
    rows = [_row(1, hour=14, r=1)]
    report = build_strategy_2_hourly_session_diagnostics(rows, rows[0].keys(), source_path="x.csv")
    paths = write_strategy_2_hourly_session_outputs(report, tmp_path)
    assert (tmp_path / "strategy_2_hourly_session_breakdown.csv").exists()
    assert (tmp_path / "strategy_2_hourly_session_summary.json").exists()
    assert (tmp_path / "strategy_2_14_16_report.md").exists()
    assert (tmp_path / "strategy_2_management_variants.csv").exists()
    assert (tmp_path / "strategy_2_management_variants_summary.json").exists()
    summary = json.loads((tmp_path / "strategy_2_hourly_session_summary.json").read_text(encoding="utf-8"))
    assert summary["live_filter_activated"] is False
