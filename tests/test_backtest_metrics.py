from __future__ import annotations

from datetime import datetime, timezone

from dazro_trade.backtest.metrics import compute_backtest_metrics
from dazro_trade.backtest.simulator import BacktestSignal, BacktestTrade


def _signal(accepted: bool = True, reasons: list[str] | None = None) -> BacktestSignal:
    return BacktestSignal(
        timestamp=datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc),
        symbol="XAUUSD",
        strategy="strategy_2_liquidity_expansion",
        direction="LONG",
        entry=4700.0,
        stop=4695.0,
        tp1=4710.0,
        tp2=4720.0,
        tp3=4730.0,
        tp4=4740.0,
        rr_tp1=2.0,
        accepted=accepted,
        rejection_reasons=reasons or [],
    )


def _trade(outcome: str, r: float, mae: float = 1.0, mfe: float = 5.0) -> BacktestTrade:
    return BacktestTrade(
        signal=_signal(),
        outcome=outcome,  # type: ignore[arg-type]
        exit_time=datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc),
        exit_price=4710.0,
        r_multiple=r,
        mae=mae,
        mfe=mfe,
        bars_held=12,
    )


def test_empty_metrics_no_trades():
    metrics = compute_backtest_metrics([], [])
    assert metrics.total_signals == 0
    assert metrics.valid_trades == 0
    assert metrics.win_rate == 0.0
    assert metrics.profit_factor == 0.0


def test_basic_aggregation():
    signals = [_signal() for _ in range(3)]
    trades = [
        _trade("TP1", 2.0, mae=1.0, mfe=10.0),
        _trade("SL", -1.0, mae=5.0, mfe=2.0),
        _trade("TP2", 4.0, mae=2.0, mfe=20.0),
    ]
    m = compute_backtest_metrics(signals, trades)
    assert m.total_signals == 3
    assert m.valid_trades == 3
    assert m.wins == 2
    assert m.losses == 1
    assert m.win_rate == pytest_approx(2 / 3)
    assert m.profit_factor == pytest_approx(6.0 / 1.0)
    assert m.average_r == pytest_approx((2.0 - 1.0 + 4.0) / 3)
    assert m.tp1_hit_rate == pytest_approx(1 / 3)
    assert m.tp2_hit_rate == pytest_approx(1 / 3)
    assert m.sl_hit_rate == pytest_approx(1 / 3)


def test_rejected_signals_counted():
    signals = [
        _signal(accepted=False, reasons=["SL_TOO_WIDE_for_strategy_2_liquidity_expansion_max=5.0_actual=10.0"]),
        _signal(accepted=False, reasons=["LOW_SCORE_for_strategy_2_min=70_actual=55"]),
        _signal(accepted=True),
    ]
    trades = [_trade("TP1", 2.0)]
    m = compute_backtest_metrics(signals, trades)
    assert m.total_signals == 3
    assert m.valid_trades == 1
    assert m.rejected_signals == 2
    assert any("SL_TOO_WIDE" in k for k in m.rejection_reasons.keys())


def test_max_drawdown_calculation():
    trades = [
        _trade("TP1", 1.0),
        _trade("SL", -1.0),
        _trade("SL", -1.0),
        _trade("TP1", 1.0),
        _trade("TP1", 1.0),
    ]
    m = compute_backtest_metrics([_signal() for _ in trades], trades)
    assert m.max_drawdown_r == pytest_approx(2.0)


def pytest_approx(value: float, tol: float = 1e-4):
    class _Approx:
        def __eq__(self, other):
            return abs(float(other) - value) <= tol
    return _Approx()
