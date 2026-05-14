from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from dazro_trade.backtest import (
    BacktestConfig,
    compute_backtest_metrics,
    export_backtest_reports,
    run_backtest,
)
from dazro_trade.backtest.data_loader import slice_market_data_up_to
from dazro_trade.backtest.runner import build_equity_curve
from dazro_trade.backtest.simulator import BacktestSignal


def _generate_synthetic_market(symbol: str = "XAUUSD", n_h1: int = 30) -> dict[str, pd.DataFrame]:
    base = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
    h1_rows = []
    price = 4700.0
    for i in range(n_h1):
        h1_rows.append({"time": base + timedelta(hours=i), "open": price, "high": price + 2, "low": price - 2, "close": price + 0.5})
        price += 0.5
    h1 = pd.DataFrame(h1_rows)
    m15_rows = []
    for i in range(n_h1 * 4):
        m15_rows.append({"time": base + timedelta(minutes=15 * i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2})
    m15 = pd.DataFrame(m15_rows)
    m5_rows = []
    for i in range(n_h1 * 12):
        m5_rows.append({"time": base + timedelta(minutes=5 * i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2})
    m5 = pd.DataFrame(m5_rows)
    m1_rows = []
    for i in range(n_h1 * 60):
        m1_rows.append({"time": base + timedelta(minutes=i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2})
    m1 = pd.DataFrame(m1_rows)
    return {"M1": m1, "M5": m5, "M15": m15, "H1": h1}


def test_slice_no_lookahead():
    md = _generate_synthetic_market(n_h1=10)
    cutoff = datetime(2026, 5, 1, 5, 0, tzinfo=timezone.utc)
    sliced = slice_market_data_up_to(md, cutoff)
    cutoff_ts = pd.Timestamp(cutoff)
    for tf, df in sliced.items():
        if len(df) == 0:
            continue
        max_time = df["time"].max()
        assert max_time <= cutoff_ts


def test_runner_runs_without_crashing_on_flat_data():
    md = _generate_synthetic_market(n_h1=20)
    cfg = BacktestConfig(symbol="XAUUSD", timeframes=["M1", "M5", "M15", "H1"])
    signals, trades = run_backtest(md, config=cfg)
    metrics = compute_backtest_metrics(signals, trades)
    assert metrics.valid_trades >= 0


def test_runner_records_signals_when_evaluator_returns_some():
    md = _generate_synthetic_market(n_h1=10)

    def fake_evaluator(market_data, when, session, settings):
        if len(market_data.get("H1", pd.DataFrame())) < 5:
            return []
        return [
            BacktestSignal(
                timestamp=when,
                symbol="XAUUSD",
                strategy="strategy_test",
                direction="LONG",
                entry=4700.0,
                stop=4698.0,
                tp1=4704.0,
                tp2=4708.0,
                rr_tp1=2.0,
                session=session,
            )
        ]

    cfg = BacktestConfig(symbol="XAUUSD")
    signals, trades = run_backtest(md, config=cfg, evaluators={"fake": fake_evaluator})
    assert len(signals) > 0
    assert all(s.accepted is True or "duplicate" in (s.rejection_reasons or [""])[0] for s in signals)


def test_per_strategy_sl_filter_rejects_wide_sl():
    md = _generate_synthetic_market(n_h1=8)

    def wide_sl_evaluator(market_data, when, session, settings):
        if len(market_data.get("H1", pd.DataFrame())) < 5:
            return []
        return [
            BacktestSignal(
                timestamp=when,
                symbol="XAUUSD",
                strategy="strategy_1_adelin",
                direction="LONG",
                entry=4700.0,
                stop=4690.0,
                tp1=4720.0,
                rr_tp1=2.0,
            )
        ]

    cfg = BacktestConfig(symbol="XAUUSD", per_strategy_max_sl={"strategy_1_adelin": 5.0})
    signals, trades = run_backtest(md, config=cfg, evaluators={"wide": wide_sl_evaluator})
    assert all(not s.accepted for s in signals)
    assert all(any("SL_TOO_WIDE" in r for r in s.rejection_reasons) for s in signals)


def test_reports_exported(tmp_path):
    md = _generate_synthetic_market(n_h1=8)

    def evaluator(market_data, when, session, settings):
        if len(market_data.get("H1", pd.DataFrame())) < 5:
            return []
        return [
            BacktestSignal(
                timestamp=when,
                symbol="XAUUSD",
                strategy="strategy_test",
                direction="LONG",
                entry=4700.0,
                stop=4698.0,
                tp1=4704.0,
                tp2=4708.0,
                rr_tp1=2.0,
                session=session,
            )
        ]

    cfg = BacktestConfig(symbol="XAUUSD")
    signals, trades = run_backtest(md, config=cfg, evaluators={"e": evaluator})
    metrics = compute_backtest_metrics(signals, trades)
    paths = export_backtest_reports(
        output_dir=str(tmp_path),
        metrics=metrics,
        signals=signals,
        trades=trades,
        equity_curve=build_equity_curve(trades),
    )
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert "total_signals" in summary
    assert (tmp_path / "executed_trades.csv").exists()
    assert (tmp_path / "rejected_signals.csv").exists()


def test_cli_smoke(tmp_path, monkeypatch):
    import backtest as cli_module
    monkeypatch.setattr(cli_module, "load_csv_timeframes", lambda *a, **kw: _generate_synthetic_market(n_h1=6))
    output = tmp_path / "out"
    rc = cli_module.main([
        "--symbol", "XAUUSD",
        "--from", "2026-05-01",
        "--to", "2026-05-02",
        "--timeframes", "M1,M5,M15,H1",
        "--data-dir", str(tmp_path),
        "--output-dir", str(output),
    ])
    assert rc == 0
    assert (output / "summary.json").exists()
