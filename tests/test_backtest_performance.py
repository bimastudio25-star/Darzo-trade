from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from dazro_trade.adelin.liquidity_map import _swing_levels
from dazro_trade.adelin.pipeline import run_adelin_scan
from dazro_trade.backtest.data_loader import BacktestDataSlicer
from dazro_trade.backtest.runner import (
    STRATEGY_1_NAME,
    STRATEGY_2_NAME,
    BacktestConfig,
    BacktestInterrupted,
    BacktestPerformanceConfig,
    run_backtest,
)
from dazro_trade.backtest.simulator import BacktestSignal, BacktestTrade


def _market(n_m5: int = 12) -> dict[str, pd.DataFrame]:
    base = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
    return {
        "M1": pd.DataFrame([
            {"time": base + timedelta(minutes=i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2}
            for i in range(n_m5 * 5)
        ]),
        "M5": pd.DataFrame([
            {"time": base + timedelta(minutes=5 * i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2}
            for i in range(n_m5)
        ]),
        "M15": pd.DataFrame([
            {"time": base + timedelta(minutes=15 * i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2}
            for i in range(max(4, n_m5 // 3))
        ]),
        "H1": pd.DataFrame([
            {"time": base + timedelta(hours=i), "open": 4700, "high": 4701, "low": 4699, "close": 4700.2}
            for i in range(max(2, n_m5 // 12 + 2))
        ]),
        "H4": pd.DataFrame([
            {"time": base + timedelta(hours=4 * i), "open": 4700, "high": 4702, "low": 4698, "close": 4700.2}
            for i in range(3)
        ]),
        "D1": pd.DataFrame([
            {"time": base + timedelta(days=i), "open": 4700, "high": 4703, "low": 4697, "close": 4700.2}
            for i in range(3)
        ]),
    }


def test_strategies_adelin_only_runs_adelin_evaluator():
    cfg = BacktestConfig(
        strategies=["adelin"],
        performance=BacktestPerformanceConfig(max_candles=1, fast_mode=True),
    )
    run_backtest(_market(), config=cfg)
    assert STRATEGY_1_NAME in cfg.strategy_diagnostics
    assert STRATEGY_2_NAME not in cfg.strategy_diagnostics


def test_strategies_strategy_2_only_runs_strategy_2_evaluator():
    cfg = BacktestConfig(
        strategies=["strategy_2_0"],
        performance=BacktestPerformanceConfig(max_candles=1, fast_mode=True),
    )
    run_backtest(_market(), config=cfg)
    assert STRATEGY_2_NAME in cfg.strategy_diagnostics
    assert STRATEGY_1_NAME not in cfg.strategy_diagnostics


def test_max_candles_stops_at_requested_count():
    calls: list[datetime] = []

    def evaluator(market_data, when, session, settings):
        calls.append(when)
        return []

    cfg = BacktestConfig(
        driver_timeframe="M5",
        performance=BacktestPerformanceConfig(max_candles=3, fast_mode=True),
    )
    run_backtest(_market(n_m5=10), config=cfg, evaluators={"fake": evaluator})
    assert len(calls) == 3


def test_progress_logging_does_not_crash(caplog):
    def evaluator(market_data, when, session, settings):
        return []

    cfg = BacktestConfig(
        driver_timeframe="M5",
        performance=BacktestPerformanceConfig(max_candles=3, progress_every_candles=2, fast_mode=True),
    )
    caplog.set_level(logging.INFO, logger="dazro_trade.backtest.runner")
    run_backtest(_market(n_m5=10), config=cfg, evaluators={"fake": evaluator})
    assert any("[fake] M5 2/3" in record.message for record in caplog.records)
    assert any("elapsed=" in record.message and "ETA=" in record.message for record in caplog.records)


def test_searchsorted_slicing_returns_only_candles_before_cutoff():
    md = _market(n_m5=10)
    cutoff = datetime(2026, 5, 1, 0, 7, tzinfo=timezone.utc)
    sliced = BacktestDataSlicer(md).slice_up_to(cutoff)
    assert sliced["M1"]["time"].max() <= pd.Timestamp(cutoff)
    assert sliced["M5"]["time"].max() <= pd.Timestamp(cutoff)


def test_fast_slicing_has_no_lookahead_and_applies_lookback():
    md = _market(n_m5=10)
    cutoff = datetime(2026, 5, 1, 0, 7, tzinfo=timezone.utc)
    sliced = BacktestDataSlicer(md, fast_mode=True, lookback_by_timeframe={"M1": 3, "M5": 2}).slice_up_to(cutoff)
    assert len(sliced["M1"]) == 3
    assert len(sliced["M5"]) == 2
    assert sliced["M1"]["time"].max() <= pd.Timestamp(cutoff)
    assert sliced["M5"]["time"].max() <= pd.Timestamp(cutoff)


def test_cli_partial_output_on_keyboard_interrupt(tmp_path, monkeypatch):
    import backtest as cli_module

    ts = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    sig = BacktestSignal(
        timestamp=ts,
        symbol="XAUUSD",
        strategy="strategy_test",
        direction="LONG",
        entry=4700.0,
        stop=4698.0,
        tp1=4704.0,
        rr_tp1=2.0,
    )
    trade = BacktestTrade(sig, "TP1", ts + timedelta(minutes=10), 4704.0, 2.0, 0.5, 4.0, 10)

    def interrupted(market_data, *, config):
        raise BacktestInterrupted([sig], [trade], config)

    monkeypatch.setattr(cli_module, "load_csv_timeframes", lambda *a, **kw: _market(n_m5=4))
    monkeypatch.setattr(cli_module, "run_backtest", interrupted)
    output = tmp_path / "out"
    rc = cli_module.main([
        "--symbol", "XAUUSD",
        "--from", "2026-05-01",
        "--to", "2026-05-02",
        "--timeframes", "M1,M5,M15,H1,H4,D1",
        "--data-dir", str(tmp_path),
        "--output-dir", str(output),
        "--strategies", "adelin",
        "--fast",
    ])
    assert rc == 130
    assert (output / "summary_partial.json").exists()
    assert (output / "executed_trades.csv").exists()
    assert (output / "rejected_signals.csv").exists()
    assert json.loads((output / "summary_partial.json").read_text())["partial"] is True


def test_cli_passes_strategies_fast_and_max_candles(tmp_path, monkeypatch):
    import backtest as cli_module

    captured: dict[str, BacktestConfig] = {}

    def fake_run(market_data, *, config):
        captured["config"] = config
        return [], []

    monkeypatch.setattr(cli_module, "load_csv_timeframes", lambda *a, **kw: _market(n_m5=4))
    monkeypatch.setattr(cli_module, "run_backtest", fake_run)
    output = tmp_path / "out"
    rc = cli_module.main([
        "--symbol", "XAUUSD",
        "--from", "2026-05-01",
        "--to", "2026-05-02",
        "--timeframes", "M1,M5,M15,H1,H4,D1",
        "--data-dir", str(tmp_path),
        "--output-dir", str(output),
        "--strategies", "strategy_2_0",
        "--fast",
        "--max-candles", "2000",
        "--liquidity-map-lookback", "H4=30,H1=50,M15=100,M5=150",
    ])
    assert rc == 0
    assert captured["config"].strategies == [STRATEGY_2_NAME]
    assert captured["config"].performance.fast_mode is True
    assert captured["config"].performance.max_candles == 2000
    assert captured["config"].performance.liquidity_map_lookback_by_timeframe["M5"] == 150


def test_adelin_liquidity_map_cache_hit_and_miss(monkeypatch):
    calls: list[tuple[object, object, object, object]] = []

    def fake_build(h4, h1, m15, m5, pip):
        calls.append((
            h4["time"].iloc[-1] if h4 is not None and len(h4) else None,
            h1["time"].iloc[-1] if h1 is not None and len(h1) else None,
            m15["time"].iloc[-1] if m15 is not None and len(m15) else None,
            m5["time"].iloc[-1] if m5 is not None and len(m5) else None,
        ))
        return [{"name": "cached", "level": 4700.0, "side": "buy_side", "timeframe": "H1", "scope": "external", "kind": "swing_high", "priority": 80, "metadata": {}}]

    md = _market(n_m5=12)
    slicer = BacktestDataSlicer(md, fast_mode=True)
    cache: dict[tuple[object, ...], list[dict]] = {}
    monkeypatch.setattr("dazro_trade.adelin.pipeline.build_liquidity_map", fake_build)
    settings = type("S", (), {
        "mt5_symbol": "XAUUSD",
        "adelin_session_gate_enabled": False,
        "adelin_news_gate_enabled": False,
        "adelin_send_vwap_research": False,
    })()
    cutoff_same = datetime(2026, 5, 1, 0, 16, tzinfo=timezone.utc)
    run_adelin_scan(
        market_data=slicer.slice_up_to(cutoff_same),
        current_price=4700.0,
        settings=settings,
        now_utc=cutoff_same,
        liquidity_map_cache=cache,
        liquidity_map_lookback_by_timeframe={"H4": 300, "H1": 500, "M15": 1000, "M5": 1500},
    )
    run_adelin_scan(
        market_data=slicer.slice_up_to(cutoff_same),
        current_price=4700.0,
        settings=settings,
        now_utc=cutoff_same,
        liquidity_map_cache=cache,
        liquidity_map_lookback_by_timeframe={"H4": 300, "H1": 500, "M15": 1000, "M5": 1500},
    )
    cutoff_new_m5 = datetime(2026, 5, 1, 0, 20, tzinfo=timezone.utc)
    run_adelin_scan(
        market_data=slicer.slice_up_to(cutoff_new_m5),
        current_price=4700.0,
        settings=settings,
        now_utc=cutoff_new_m5,
        liquidity_map_cache=cache,
        liquidity_map_lookback_by_timeframe={"H4": 300, "H1": 500, "M15": 1000, "M5": 1500},
    )
    assert len(calls) == 2


def test_cached_liquidity_map_uses_no_lookahead_frames(monkeypatch):
    seen_max_times: list[pd.Timestamp] = []

    def fake_build(h4, h1, m15, m5, pip):
        for frame in (h4, h1, m15, m5):
            if frame is not None and len(frame):
                seen_max_times.append(pd.Timestamp(frame["time"].max()))
        return []

    md = _market(n_m5=20)
    slicer = BacktestDataSlicer(md, fast_mode=True, lookback_by_timeframe={"M5": 5, "M15": 5, "H1": 5, "H4": 5})
    cutoff = datetime(2026, 5, 1, 0, 31, tzinfo=timezone.utc)
    settings = type("S", (), {
        "mt5_symbol": "XAUUSD",
        "adelin_session_gate_enabled": False,
        "adelin_news_gate_enabled": False,
        "adelin_send_vwap_research": False,
    })()
    monkeypatch.setattr("dazro_trade.adelin.pipeline.build_liquidity_map", fake_build)
    run_adelin_scan(
        market_data=slicer.slice_up_to(cutoff),
        current_price=4700.0,
        settings=settings,
        now_utc=cutoff,
        liquidity_map_cache={},
        liquidity_map_lookback_by_timeframe={"H4": 300, "H1": 500, "M15": 1000, "M5": 3},
    )
    assert seen_max_times
    assert all(item <= pd.Timestamp(cutoff) for item in seen_max_times)


def test_swing_levels_numpy_fast_path_matches_reference_algorithm():
    rows = [
        {"h": 100.0, "l": 95.0, "c": 98.0},
        {"h": 101.0, "l": 96.0, "c": 99.0},
        {"h": 103.0, "l": 94.0, "c": 100.0},
        {"h": 101.2, "l": 96.2, "c": 99.5},
        {"h": 100.2, "l": 95.2, "c": 99.0},
        {"h": 103.1, "l": 97.0, "c": 101.0},
        {"h": 101.0, "l": 94.1, "c": 98.0},
        {"h": 99.0, "l": 96.0, "c": 98.0},
    ]
    frame = pd.DataFrame(rows)

    def reference(frame: pd.DataFrame) -> list[dict]:
        levels: list[dict] = []
        recent = frame.tail(min(len(frame), 120)).reset_index(drop=True)
        tolerance = 2.5 * 0.10
        for idx in range(2, len(recent) - 2):
            window = recent.iloc[idx - 2: idx + 3]
            high = float(recent.iloc[idx]["h"])
            low = float(recent.iloc[idx]["l"])
            high_touches = int((recent["h"].astype(float).sub(high).abs() <= tolerance).sum())
            low_touches = int((recent["l"].astype(float).sub(low).abs() <= tolerance).sum())
            if high == float(window["h"].max()) and high_touches >= 2:
                levels.append(("swing_high", round(high, 2)))
            if low == float(window["l"].min()) and low_touches >= 2:
                levels.append(("swing_low", round(low, 2)))
        return levels[-16:]

    optimized = [(item["kind"], item["level"]) for item in _swing_levels(frame, "M5", "internal", 0.10)]
    assert optimized == reference(frame)
