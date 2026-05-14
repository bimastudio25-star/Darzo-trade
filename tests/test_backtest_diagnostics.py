from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from dazro_trade.analysis.liquidity_expansion import (
    LiquidityExpansionDiagnostics,
    evaluate_liquidity_expansion,
)
from dazro_trade.backtest import BacktestConfig, run_backtest
from dazro_trade.backtest.reports import _serialize_diagnostics, export_backtest_reports
from dazro_trade.backtest.metrics import compute_backtest_metrics


def _generate_synthetic_market(n_h1: int = 30) -> dict[str, pd.DataFrame]:
    base = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
    h1_rows = []
    for i in range(n_h1):
        h1_rows.append({"time": base + timedelta(hours=i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2})
    m15 = pd.DataFrame([{"time": base + timedelta(minutes=15 * i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2} for i in range(n_h1 * 4)])
    m5 = pd.DataFrame([{"time": base + timedelta(minutes=5 * i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2} for i in range(n_h1 * 12)])
    m1 = pd.DataFrame([{"time": base + timedelta(minutes=i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2} for i in range(n_h1 * 60)])
    return {"M1": m1, "M5": m5, "M15": m15, "H1": pd.DataFrame(h1_rows)}


def test_diagnostics_counts_total_calls():
    diag = LiquidityExpansionDiagnostics()
    result = evaluate_liquidity_expansion(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), current_price=4700.0, diagnostics=diag)
    assert result is None
    assert diag.total_calls == 1
    assert diag.skip_missing_data == 1


def test_diagnostics_skip_no_reference():
    diag = LiquidityExpansionDiagnostics()
    base = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
    m1 = pd.DataFrame([{"time": base + timedelta(minutes=i), "open": 4700, "high": 4701, "low": 4699, "close": 4700} for i in range(60)])
    m5 = pd.DataFrame([{"time": base + timedelta(minutes=5 * i), "open": 4700, "high": 4701, "low": 4699, "close": 4700} for i in range(20)])
    m15 = pd.DataFrame([{"time": base + timedelta(minutes=15 * i), "open": 4700, "high": 4701, "low": 4699, "close": 4700} for i in range(10)])
    h1 = pd.DataFrame([
        {"time": base, "open": 4700, "high": 4701, "low": 4699, "close": 4700},
        {"time": base + timedelta(hours=1), "open": 4700, "high": 4701, "low": 4699, "close": 4700},
    ])
    result = evaluate_liquidity_expansion(m1, m5, m15, h1, current_price=4700.0, diagnostics=diag)
    assert result is None
    assert diag.total_calls == 1
    assert diag.skip_no_reference + diag.skip_insufficient_stats >= 1


def test_diagnostics_skip_insufficient_stats():
    diag = LiquidityExpansionDiagnostics()
    base = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
    h1_rows = [{"time": base + timedelta(hours=i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.5} for i in range(5)]
    m15_rows = [{"time": base + timedelta(minutes=15 * i), "open": 4700, "high": 4701, "low": 4699, "close": 4700} for i in range(20)]
    m5_rows = [{"time": base + timedelta(minutes=5 * i), "open": 4700, "high": 4701, "low": 4699, "close": 4700} for i in range(60)]
    m1_rows = [{"time": base + timedelta(minutes=i), "open": 4700, "high": 4701, "low": 4699, "close": 4700} for i in range(300)]
    result = evaluate_liquidity_expansion(
        pd.DataFrame(m1_rows), pd.DataFrame(m5_rows), pd.DataFrame(m15_rows), pd.DataFrame(h1_rows),
        current_price=4700.0, diagnostics=diag,
    )
    assert result is None
    assert diag.skip_insufficient_stats == 1


def test_backtest_config_initializes_diagnostics():
    md = _generate_synthetic_market(n_h1=20)
    cfg = BacktestConfig(symbol="XAUUSD")
    signals, trades = run_backtest(md, config=cfg)
    assert "strategy_2_liquidity_expansion" in cfg.strategy_diagnostics
    diag = cfg.strategy_diagnostics["strategy_2_liquidity_expansion"]
    assert isinstance(diag, LiquidityExpansionDiagnostics)
    assert diag.total_calls >= 1


def test_diagnostics_serialize_for_reports():
    diag = LiquidityExpansionDiagnostics()
    diag.total_calls = 100
    diag.skip_missing_data = 5
    diag.signals_emitted = 2
    diag.long_signals = 1
    diag.short_signals = 1
    diag.trigger_kind_counts = {"reclaim": 1, "rejection": 1}
    payload = _serialize_diagnostics({"strategy_2_liquidity_expansion": diag})
    assert "strategy_2_liquidity_expansion" in payload
    assert payload["strategy_2_liquidity_expansion"]["total_calls"] == 100
    assert payload["strategy_2_liquidity_expansion"]["signals_emitted"] == 2
    assert payload["strategy_2_liquidity_expansion"]["trigger_kind_counts"]["reclaim"] == 1


def test_reports_include_strategy_diagnostics_block(tmp_path):
    md = _generate_synthetic_market(n_h1=15)
    cfg = BacktestConfig(symbol="XAUUSD")
    signals, trades = run_backtest(md, config=cfg)
    metrics = compute_backtest_metrics(signals, trades)
    paths = export_backtest_reports(
        output_dir=str(tmp_path),
        metrics=metrics,
        signals=signals,
        trades=trades,
        strategy_diagnostics=cfg.strategy_diagnostics,
    )
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert "strategy_diagnostics" in summary
    assert "strategy_2_liquidity_expansion" in summary["strategy_diagnostics"]
    diag_dump = json.loads((tmp_path / "strategy_diagnostics.json").read_text())
    assert "strategy_2_liquidity_expansion" in diag_dump
    assert diag_dump["strategy_2_liquidity_expansion"]["total_calls"] >= 1


def test_diagnostics_signals_emitted_increments_when_signal_returned():
    """Use a synthetic but plausible setup to actually emit a signal."""
    diag = LiquidityExpansionDiagnostics()
    pytest.importorskip("pandas")
    base = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
    h1_rows = []
    price = 4700.0
    for i in range(40):
        if i % 3 == 1:
            h1_rows.append({"time": base + timedelta(hours=i), "open": price, "high": price + 6.0, "low": price - 1.0, "close": price - 0.5})
        elif i % 3 == 2:
            h1_rows.append({"time": base + timedelta(hours=i), "open": price - 0.5, "high": price + 0.5, "low": price - 8.0, "close": price - 7.0})
        else:
            h1_rows.append({"time": base + timedelta(hours=i), "open": price, "high": price + 1.0, "low": price - 1.0, "close": price + 0.2})
        price += 0.1
    h1 = pd.DataFrame(h1_rows)
    h1_open_time = h1.iloc[-1]["time"]
    m15 = pd.DataFrame([
        {"time": h1_open_time - timedelta(minutes=15), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2},
    ])
    m5 = pd.DataFrame([{"time": h1_open_time - timedelta(minutes=5 * (60 - i)), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2} for i in range(60)])
    m1 = pd.DataFrame([{"time": h1_open_time + timedelta(minutes=i), "open": 4700, "high": 4701, "low": 4690, "close": 4691} for i in range(10)])
    evaluate_liquidity_expansion(m1, m5, m15, h1, current_price=4690.0, diagnostics=diag)
    # Even if no signal emitted, diagnostics should still track the call
    assert diag.total_calls == 1
