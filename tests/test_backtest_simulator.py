from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from dazro_trade.backtest.simulator import BacktestSignal, simulate_trade_outcome


def _m1(start: datetime, rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame([
        {"time": start + timedelta(minutes=i), "open": o, "high": h, "low": l, "close": c}
        for i, (o, h, l, c) in enumerate(rows)
    ])


def _signal_long() -> BacktestSignal:
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
    )


def _signal_short() -> BacktestSignal:
    return BacktestSignal(
        timestamp=datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc),
        symbol="XAUUSD",
        strategy="strategy_2_liquidity_expansion",
        direction="SHORT",
        entry=4700.0,
        stop=4705.0,
        tp1=4690.0,
        tp2=4680.0,
        tp3=4670.0,
        tp4=4660.0,
        rr_tp1=2.0,
    )


def test_long_tp1_hit_first():
    base = datetime(2026, 5, 13, 9, 1, tzinfo=timezone.utc)
    m1 = _m1(base, [
        (4700, 4702, 4699, 4701),
        (4701, 4705, 4700, 4704),
        (4704, 4711, 4703, 4710),
    ])
    trade = simulate_trade_outcome(_signal_long(), m1)
    assert trade.outcome == "TP1"
    assert trade.r_multiple == 2.0
    assert trade.bars_held == 3


def test_long_sl_hit_first():
    base = datetime(2026, 5, 13, 9, 1, tzinfo=timezone.utc)
    m1 = _m1(base, [
        (4700, 4702, 4699, 4701),
        (4701, 4704, 4694, 4695),
    ])
    trade = simulate_trade_outcome(_signal_long(), m1)
    assert trade.outcome == "SL"
    assert trade.r_multiple == -1.0


def test_short_tp1_hit_first():
    base = datetime(2026, 5, 13, 9, 1, tzinfo=timezone.utc)
    m1 = _m1(base, [
        (4700, 4701, 4699, 4700),
        (4700, 4701, 4690, 4691),
    ])
    trade = simulate_trade_outcome(_signal_short(), m1)
    assert trade.outcome == "TP1"
    assert trade.r_multiple == 2.0


def test_short_sl_hit_first():
    base = datetime(2026, 5, 13, 9, 1, tzinfo=timezone.utc)
    m1 = _m1(base, [
        (4700, 4706, 4699, 4705),
    ])
    trade = simulate_trade_outcome(_signal_short(), m1)
    assert trade.outcome == "SL"


def test_timeout_close_when_neither_reached_within_max_bars():
    base = datetime(2026, 5, 13, 9, 1, tzinfo=timezone.utc)
    m1 = _m1(base, [(4700, 4701, 4699, 4700)] * 5)
    trade = simulate_trade_outcome(_signal_long(), m1, max_bars=5)
    assert trade.outcome == "TIMEOUT_CLOSE"
    assert trade.r_multiple == 0.0
    assert trade.exit_price == 4700.0


def test_end_of_data_close_marks_available_close_r_multiple():
    base = datetime(2026, 5, 13, 9, 1, tzinfo=timezone.utc)
    m1 = _m1(base, [
        (4700, 4701, 4699, 4701),
        (4701, 4703, 4700, 4702),
    ])
    trade = simulate_trade_outcome(_signal_long(), m1, max_bars=5)
    assert trade.outcome == "END_OF_DATA_CLOSE"
    assert trade.exit_price == 4702.0
    assert trade.r_multiple == 0.4


def test_mae_mfe_tracked_correctly_long():
    base = datetime(2026, 5, 13, 9, 1, tzinfo=timezone.utc)
    m1 = _m1(base, [
        (4700, 4702, 4697, 4700),
        (4700, 4709, 4699, 4708),
        (4708, 4711, 4707, 4710),
    ])
    trade = simulate_trade_outcome(_signal_long(), m1)
    assert trade.mae >= 3.0
    assert trade.mfe >= 11.0
    assert trade.outcome == "TP1"


def test_sl_and_tp_in_same_candle_resolves_to_sl():
    base = datetime(2026, 5, 13, 9, 1, tzinfo=timezone.utc)
    m1 = _m1(base, [
        (4700, 4711, 4694, 4710),
    ])
    trade = simulate_trade_outcome(_signal_long(), m1)
    assert trade.outcome == "SL"


def test_no_data_returns_no_data_outcome():
    trade = simulate_trade_outcome(_signal_long(), pd.DataFrame())
    assert trade.outcome == "NO_DATA"
    assert trade.r_multiple == 0.0


def test_rejected_signal_returns_no_data():
    sig = _signal_long()
    sig.accepted = False
    sig.rejection_reasons.append("SL_TOO_WIDE")
    base = datetime(2026, 5, 13, 9, 1, tzinfo=timezone.utc)
    m1 = _m1(base, [(4700, 4711, 4699, 4710)])
    trade = simulate_trade_outcome(sig, m1)
    assert trade.outcome == "NO_DATA"
