from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from dazro_trade.backtest import (
    BacktestConfig,
    compute_backtest_metrics,
    compute_per_strategy_metrics,
    export_backtest_reports,
    run_backtest,
)
from dazro_trade.backtest.runner import AdelinDiagnostics, DEFAULT_EVALUATORS
from dazro_trade.backtest.simulator import BacktestSignal, BacktestTrade


def _generate_flat_market(n_h1: int = 20) -> dict[str, pd.DataFrame]:
    base = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
    h1 = pd.DataFrame([{"time": base + timedelta(hours=i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2} for i in range(n_h1)])
    m15 = pd.DataFrame([{"time": base + timedelta(minutes=15 * i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2} for i in range(n_h1 * 4)])
    m5 = pd.DataFrame([{"time": base + timedelta(minutes=5 * i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2} for i in range(n_h1 * 12)])
    m1 = pd.DataFrame([{"time": base + timedelta(minutes=i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2} for i in range(n_h1 * 60)])
    return {"M1": m1, "M5": m5, "M15": m15, "H1": h1}


def test_default_evaluators_include_adelin_and_strategy_2():
    assert "strategy_2_liquidity_expansion" in DEFAULT_EVALUATORS
    assert "strategy_1_adelin_scalp" in DEFAULT_EVALUATORS


def test_backtest_runs_both_strategies_and_populates_diagnostics():
    md = _generate_flat_market(n_h1=12)
    cfg = BacktestConfig()
    signals, trades = run_backtest(md, config=cfg)
    diags = cfg.strategy_diagnostics
    assert "strategy_2_liquidity_expansion" in diags
    assert "strategy_1_adelin_scalp" in diags
    s2 = diags["strategy_2_liquidity_expansion"]
    adelin = diags["strategy_1_adelin_scalp"]
    assert s2.total_calls >= 1
    assert adelin.total_calls >= 1


def test_adelin_uses_m5_driver_strategy_2_uses_m15():
    cfg = BacktestConfig()
    assert cfg.evaluator_drivers["strategy_2_liquidity_expansion"] == "M15"
    assert cfg.evaluator_drivers["strategy_1_adelin_scalp"] == "M5"


def test_backtest_config_exposes_tf_architecture_per_strategy():
    cfg = BacktestConfig()
    assert cfg.strategy_2_setup_tf == "M15"
    assert cfg.strategy_2_refinement_tf == "M5"
    assert cfg.strategy_2_trigger_tf == "M1"
    assert cfg.strategy_2_htf_context == ["D1", "H4", "H1"]
    assert cfg.adelin_scalp_driver == "M5"
    assert cfg.adelin_scalp_setup_tf == "M15"
    assert cfg.adelin_scalp_refinement_tf == "M5"
    assert cfg.adelin_scalp_trigger_tf == "M1"
    assert cfg.adelin_scalp_htf_context == ["D1", "H4", "H1"]


def test_diagnostics_expose_tf_metadata_and_signals_per_day():
    md = _generate_flat_market(n_h1=12)
    cfg = BacktestConfig()
    run_backtest(md, config=cfg)
    s2_diag = cfg.strategy_diagnostics["strategy_2_liquidity_expansion"].to_dict()
    adelin_diag = cfg.strategy_diagnostics["strategy_1_adelin_scalp"].to_dict()
    assert s2_diag["driver_timeframe"] == "M15"
    assert s2_diag["setup_timeframe"] == "M15"
    assert s2_diag["refinement_timeframe"] == "M5"
    assert s2_diag["trigger_timeframe"] == "M1"
    assert s2_diag["htf_context_timeframes"] == ["D1", "H4", "H1"]
    assert "signals_per_day" in s2_diag
    assert "rejections_by_layer" in s2_diag
    assert "evaluation_count" in s2_diag
    assert adelin_diag["driver_timeframe"] == "M5"
    assert adelin_diag["setup_timeframe"] == "M15"
    assert adelin_diag["trigger_timeframe"] == "M1"
    assert "signals_per_day" in adelin_diag
    assert "rejections_by_layer" in adelin_diag


def test_per_strategy_metrics_separates_strategies():
    ts = datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc)
    s_adelin = BacktestSignal(timestamp=ts, symbol="XAUUSD", strategy="strategy_1_adelin_scalp", direction="LONG", entry=4700.0, stop=4696.5, tp1=4710.0, rr_tp1=2.0)
    s_strategy_2 = BacktestSignal(timestamp=ts + timedelta(days=1), symbol="XAUUSD", strategy="strategy_2_liquidity_expansion", direction="SHORT", entry=4710.0, stop=4830.0, tp1=4600.0, rr_tp1=0.9)
    trade_adelin = BacktestTrade(signal=s_adelin, outcome="TP1", exit_time=ts + timedelta(minutes=30), exit_price=4710.0, r_multiple=2.0, mae=2.0, mfe=10.0, bars_held=30)
    trade_s2 = BacktestTrade(signal=s_strategy_2, outcome="SL", exit_time=ts + timedelta(hours=8), exit_price=4830.0, r_multiple=-1.0, mae=120.0, mfe=10.0, bars_held=480)
    per = compute_per_strategy_metrics([s_adelin, s_strategy_2], [trade_adelin, trade_s2])
    assert "strategy_1_adelin_scalp" in per
    assert "strategy_2_liquidity_expansion" in per
    assert per["strategy_1_adelin_scalp"]["wins"] == 1
    assert per["strategy_1_adelin_scalp"]["losses"] == 0
    assert per["strategy_2_liquidity_expansion"]["wins"] == 0
    assert per["strategy_2_liquidity_expansion"]["losses"] == 1
    assert per["strategy_2_liquidity_expansion"]["average_mae"] >= 100


def test_per_strategy_metrics_signals_per_day():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    signals = [
        BacktestSignal(timestamp=base + timedelta(days=i), symbol="XAUUSD", strategy="strategy_1_adelin_scalp",
                       direction="LONG", entry=4700.0, stop=4697.0, tp1=4706.0, rr_tp1=2.0)
        for i in range(10)
    ]
    trades = [
        BacktestTrade(signal=signals[i], outcome="TP1", exit_time=signals[i].timestamp + timedelta(hours=2),
                      exit_price=4706.0, r_multiple=2.0, mae=1.0, mfe=6.0, bars_held=120)
        for i in range(10)
    ]
    per = compute_per_strategy_metrics(signals, trades)
    adelin_stats = per["strategy_1_adelin_scalp"]
    assert adelin_stats["days_observed"] >= 9
    assert 0 < adelin_stats["signals_per_day"] <= 2.0


def test_reports_export_per_strategy_json(tmp_path):
    md = _generate_flat_market(n_h1=10)
    cfg = BacktestConfig()
    signals, trades = run_backtest(md, config=cfg)
    metrics = compute_backtest_metrics(signals, trades)
    paths = export_backtest_reports(
        output_dir=str(tmp_path),
        metrics=metrics,
        signals=signals,
        trades=trades,
        strategy_diagnostics=cfg.strategy_diagnostics,
    )
    assert (tmp_path / "per_strategy.json").exists()
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert "strategy_diagnostics" in summary
    diags = summary["strategy_diagnostics"]
    assert "strategy_1_adelin_scalp" in diags
    assert "strategy_2_liquidity_expansion" in diags


def test_adelin_diagnostics_tracks_setup_modes_and_reasons():
    md = _generate_flat_market(n_h1=10)
    cfg = BacktestConfig()
    run_backtest(md, config=cfg)
    adelin = cfg.strategy_diagnostics["strategy_1_adelin_scalp"]
    assert isinstance(adelin, AdelinDiagnostics)
    assert adelin.total_calls >= 1
    # On flat synthetic data Adelin should reject most calls
    assert adelin.no_signal_count + sum(adelin.setup_modes.values()) >= 1
