from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dazro_trade.backtest.simulator import BacktestSignal
from dazro_trade.strategy.risk_labels import classify_sl_risk, risk_label_warning


def test_tight_scalp_boundary():
    assert classify_sl_risk(0.5) == "tight_scalp"
    assert classify_sl_risk(3.0) == "tight_scalp"


def test_normal_scalp_boundary():
    assert classify_sl_risk(3.01) == "normal_scalp"
    assert classify_sl_risk(4.0) == "normal_scalp"
    assert classify_sl_risk(5.0) == "normal_scalp"


def test_wide_scalp_boundary():
    assert classify_sl_risk(5.01) == "wide_scalp"
    assert classify_sl_risk(7.5) == "wide_scalp"
    assert classify_sl_risk(10.0) == "wide_scalp"


def test_extended_risk_boundary():
    assert classify_sl_risk(10.01) == "extended_risk"
    assert classify_sl_risk(50.0) == "extended_risk"
    assert classify_sl_risk(123.5) == "extended_risk"


def test_negative_distance_treated_as_absolute():
    assert classify_sl_risk(-4.0) == "normal_scalp"


def test_warning_only_for_extended_risk():
    assert risk_label_warning("tight_scalp") is None
    assert risk_label_warning("normal_scalp") is None
    assert risk_label_warning("wide_scalp") is None
    msg = risk_label_warning("extended_risk")
    assert msg is not None
    assert "10 USD" in msg


def test_backtest_signal_exposes_sl_distance_and_label():
    sig = BacktestSignal(
        timestamp=datetime(2026, 5, 15, 9, 0, tzinfo=timezone.utc),
        symbol="XAUUSD",
        strategy="strategy_2_liquidity_expansion",
        direction="LONG",
        entry=4700.0,
        stop=4696.5,
        tp1=4710.0,
        rr_tp1=2.0,
    )
    assert sig.sl_distance_usd == 3.5
    assert sig.sl_distance_pips == 35.0
    assert sig.risk_label == "normal_scalp"


def test_backtest_signal_extended_risk_label_for_swing_sized_sl():
    sig = BacktestSignal(
        timestamp=datetime(2026, 5, 15, 9, 0, tzinfo=timezone.utc),
        symbol="XAUUSD",
        strategy="strategy_2_liquidity_expansion",
        direction="LONG",
        entry=4700.0,
        stop=4576.5,
        tp1=4796.8,
        rr_tp1=0.78,
    )
    assert sig.sl_distance_usd == 123.5
    assert sig.risk_label == "extended_risk"


def test_strategy_2_not_in_default_per_strategy_sl_cap():
    from dazro_trade.backtest.runner import BacktestConfig

    cfg = BacktestConfig()
    assert "strategy_2_liquidity_expansion" not in cfg.per_strategy_max_sl
    assert "strategy_2_0" not in cfg.per_strategy_max_sl


def test_report_includes_risk_label_columns(tmp_path):
    import json
    from dazro_trade.backtest.reports import export_backtest_reports
    from dazro_trade.backtest.metrics import compute_backtest_metrics
    from dazro_trade.backtest.simulator import BacktestTrade

    sig = BacktestSignal(
        timestamp=datetime(2026, 5, 15, 9, 0, tzinfo=timezone.utc),
        symbol="XAUUSD",
        strategy="strategy_2_liquidity_expansion",
        direction="LONG",
        entry=4700.0,
        stop=4576.5,
        tp1=4796.8,
        tp2=4893.6,
        rr_tp1=0.78,
    )
    trade = BacktestTrade(
        signal=sig,
        outcome="TP1",
        exit_time=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
        exit_price=4796.8,
        r_multiple=0.78,
        mae=10.0,
        mfe=100.0,
        bars_held=120,
    )
    metrics = compute_backtest_metrics([sig], [trade])
    paths = export_backtest_reports(
        output_dir=str(tmp_path),
        metrics=metrics,
        signals=[sig],
        trades=[trade],
    )
    executed = (tmp_path / "executed_trades.csv").read_text()
    assert "sl_distance_usd" in executed
    assert "sl_distance_pips" in executed
    assert "risk_label" in executed
    assert "extended_risk" in executed
