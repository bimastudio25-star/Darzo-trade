from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from dazro_trade.analysis.strategy_3_vwap_1r import Strategy3Diagnostics, Strategy3Signal, evaluate_strategy_3_vwap_1r
from dazro_trade.analysis.vwap import VwapSnapshot, session_vwap_snapshot
from dazro_trade.backtest.runner import (
    DEFAULT_EVALUATORS,
    STRATEGY_1_NAME,
    STRATEGY_2_NAME,
    STRATEGY_3_NAME,
    BacktestConfig,
    BacktestPerformanceConfig,
    resolve_strategy_selection,
    run_backtest,
)
from dazro_trade.backtest.simulator import BacktestSignal, simulate_trade_outcome


def _frame(base: datetime, minutes: int, step: int = 1, price: float = 100.0) -> pd.DataFrame:
    rows = []
    for i in range(minutes):
        rows.append(
            {
                "time": base + timedelta(minutes=i * step),
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price,
                "tick_volume": 100,
            }
        )
    return pd.DataFrame(rows)


def _market() -> dict[str, pd.DataFrame]:
    base = datetime(2026, 5, 10, tzinfo=timezone.utc)
    return {
        "M1": _frame(base, 20, 1, 98.0),
        "M5": _frame(base, 20, 5, 98.0),
        "M15": _frame(base, 20, 15, 98.0),
        "H1": _frame(base, 10, 60, 100.0),
        "H4": _frame(base, 5, 240, 100.0),
        "D1": _frame(base, 3, 1440, 100.0),
    }


def test_strategy_3_registered_and_selectable():
    assert STRATEGY_3_NAME == "strategy_3_vwap_1r"
    assert STRATEGY_3_NAME in DEFAULT_EVALUATORS
    assert resolve_strategy_selection("strategy_3_vwap_1r") == [STRATEGY_3_NAME]
    assert resolve_strategy_selection("vwap_1r") == [STRATEGY_3_NAME]


def test_strategy_3_generates_expected_research_signal(monkeypatch):
    import dazro_trade.analysis.strategy_3_vwap_1r as module

    monkeypatch.setattr(
        module,
        "session_vwap_snapshot",
        lambda df, price=None: VwapSnapshot(
            vwap=100.0,
            std=2.0,
            upper_1=102.0,
            upper_2=104.0,
            upper_3=106.0,
            lower_1=98.0,
            lower_2=96.0,
            lower_3=94.0,
            z_score=-1.1,
            slope=0.1,
        ),
    )
    monkeypatch.setattr(module, "build_liquidity_map", lambda *a, **kw: [{"level": 97.5, "side": "sell_side", "timeframe": "M5", "kind": "equal_lows", "scope": "internal", "priority": 80}])
    monkeypatch.setattr(module, "find_liquidity_sweep", lambda *a, **kw: {"liquidity_swept": True, "level": 97.5, "direction": "LONG", "fvg_after_liquidity": True, "ifvg_after_liquidity": False, "fvg": {"has_fvg": True}})
    monkeypatch.setattr(module, "build_multi_anchor_volume_profiles", lambda *a, **kw: {})
    monkeypatch.setattr(module, "find_best_volume_crack_confluence", lambda *a, **kw: {"confluence": False, "reason": "no_volume"})
    diagnostics = Strategy3Diagnostics()
    signal = evaluate_strategy_3_vwap_1r(_market(), symbol="XAUUSD", now_utc=datetime(2026, 5, 10, tzinfo=timezone.utc), diagnostics=diagnostics)
    assert signal is not None
    assert signal.setup_mode == "reversal"
    assert signal.direction == "LONG"
    assert signal.rr_tp1 == 1.0
    assert signal.stop < signal.entry < signal.tp1
    assert signal.reason_codes
    assert signal.band_touched == "sigma_1_lower"
    assert signal.liquidity_context["distance_pips"] <= 120
    assert diagnostics.signals_emitted == 1


def test_strategy_3_backtest_signal_has_required_metadata(monkeypatch):
    import dazro_trade.backtest.runner as runner

    def fake_eval(*args, **kwargs):
        diagnostics = kwargs.get("diagnostics")
        if diagnostics is not None:
            diagnostics.signals_emitted += 1
        return Strategy3Signal(
            symbol="XAUUSD",
            direction="LONG",
            setup_mode="reversal",
            entry=100.0,
            stop=99.0,
            tp1=101.0,
            rr_tp1=1.0,
            timestamp_utc=datetime(2026, 5, 10, tzinfo=timezone.utc),
            reason_codes=["liquidity_sweep", "vwap_band_sigma_1_lower", "target_1r"],
            confluences={"vwap": {}},
            vwap_distance_pips=0.0,
            band_touched="sigma_1_lower",
            liquidity_context={"level": 99.0, "distance_pips": 10.0},
            fvg_ifvg_context={"has_fvg": True},
            number_theory_context={"confluence": False},
        )

    monkeypatch.setattr(runner, "evaluate_strategy_3_vwap_1r", fake_eval)
    cfg = BacktestConfig(
        strategies=["strategy_3_vwap_1r"],
        performance=BacktestPerformanceConfig(max_candles=1, fast_mode=True),
    )
    signals, _ = run_backtest(_market(), config=cfg)
    assert signals
    sig = signals[0]
    assert sig.strategy == STRATEGY_3_NAME
    assert sig.tp1 is not None
    assert sig.stop != sig.entry
    assert sig.metadata["setup_mode"] in {"trend_following", "reversal"}
    assert sig.metadata["target_model"] == "1R"
    assert sig.metadata["research_only"] is True
    assert "reason_codes" in sig.metadata
    assert "vwap" in sig.metadata
    assert "vwap_distance" in sig.metadata
    assert sig.metadata["band_touched"] == "sigma_1_lower"


def test_strategy_3_only_does_not_run_strategy_1_or_2():
    cfg = BacktestConfig(
        strategies=["strategy_3_vwap_1r"],
        performance=BacktestPerformanceConfig(max_candles=1, fast_mode=True),
    )
    run_backtest(_market(), config=cfg)
    assert STRATEGY_3_NAME in cfg.strategy_diagnostics
    assert STRATEGY_1_NAME not in cfg.strategy_diagnostics
    assert STRATEGY_2_NAME not in cfg.strategy_diagnostics


def test_strategy_3_module_does_not_import_live_telegram_or_orders():
    text = Path("dazro_trade/analysis/strategy_3_vwap_1r.py").read_text()
    lowered = text.lower()
    assert "telegram" not in lowered
    assert "send_text" not in lowered
    assert "order" not in lowered
    assert "dynamic" not in lowered


def test_simulator_still_closes_timeout_post_strategy_3_registration():
    ts = datetime(2026, 5, 10, tzinfo=timezone.utc)
    signal = BacktestSignal(
        timestamp=ts,
        symbol="XAUUSD",
        strategy=STRATEGY_3_NAME,
        direction="LONG",
        entry=100.0,
        stop=99.0,
        tp1=101.0,
        rr_tp1=1.0,
    )
    future = pd.DataFrame(
        [{"time": ts + timedelta(minutes=i + 1), "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.1} for i in range(3)]
    )
    trade = simulate_trade_outcome(signal, future, max_bars=3)
    assert trade.outcome == "TIMEOUT_CLOSE"
    assert trade.r_multiple == 0.1


def test_session_vwap_resets_by_session_and_uses_no_future_rows():
    base = datetime(2026, 5, 10, 1, 0, tzinfo=timezone.utc)
    frame = pd.DataFrame(
        [
            {"time": base, "open": 100, "high": 100, "low": 100, "close": 100, "tick_volume": 10},
            {"time": base + timedelta(hours=1), "open": 110, "high": 110, "low": 110, "close": 110, "tick_volume": 10},
            {"time": base + timedelta(hours=9), "open": 130, "high": 130, "low": 130, "close": 130, "tick_volume": 10},
        ]
    )
    first_two = session_vwap_snapshot(frame.iloc[:2], price=110)
    all_rows = session_vwap_snapshot(frame, price=130)
    assert first_two is not None
    assert all_rows is not None
    assert first_two.vwap == 105.0
    assert all_rows.vwap == 130.0


def test_session_vwap_equal_weight_fallback_and_small_sample():
    base = datetime(2026, 5, 10, 9, 0, tzinfo=timezone.utc)
    frame = pd.DataFrame(
        [{"time": base, "open": 100, "high": 101, "low": 99, "close": 100, "tick_volume": 0}]
    )
    snapshot = session_vwap_snapshot(frame, price=100)
    assert snapshot is not None
    assert snapshot.vwap == 100.0
    assert snapshot.std == 0.0
    assert snapshot.equal_weight_fallback is True
