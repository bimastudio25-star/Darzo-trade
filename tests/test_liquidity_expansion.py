from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from dazro_trade.analysis.liquidity_expansion import (
    LiquidityExpansionSignal,
    LiquidityReferenceLevels,
    SweepStatistics,
    build_live_mae_stats,
    build_reference_levels,
    calculate_h1_liquidity_levels,
    compute_h1_sweep_stats,
    evaluate_liquidity_expansion,
)
from dazro_trade.core.config import Settings
from dazro_trade.core.symbols import pips_to_price
from dazro_trade.runtime.scanner import ScalpingScanner, VirtualTrade


def _h1_df(rows: list[tuple[float, float, float, float]], start: datetime | None = None) -> pd.DataFrame:
    base = start or datetime(2026, 5, 13, 6, 0, tzinfo=timezone.utc)
    return pd.DataFrame([
        {"time": base + timedelta(hours=idx), "o": o, "h": h, "l": l, "c": c, "vol": 100}
        for idx, (o, h, l, c) in enumerate(rows)
    ])


def _m15_df(rows: list[tuple[datetime, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame([
        {"time": t, "o": o, "h": h, "l": l, "c": c, "vol": 50}
        for (t, o, h, l, c) in rows
    ])


def _m1_df(rows: list[tuple[datetime, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame([
        {"time": t, "o": o, "h": h, "l": l, "c": c, "vol": 10}
        for (t, o, h, l, c) in rows
    ])


def test_reference_levels_minute_45_picked():
    h1 = _h1_df([(100.0, 101.0, 99.0, 100.5), (100.5, 102.0, 100.0, 101.5), (101.5, 102.5, 101.0, 102.0)])
    previous_h1 = datetime(2026, 5, 13, 7, 0, tzinfo=timezone.utc)
    m15 = _m15_df([
        (previous_h1, 100.5, 101.2, 100.4, 101.0),
        (previous_h1 + timedelta(minutes=15), 101.0, 101.5, 100.8, 101.3),
        (previous_h1 + timedelta(minutes=30), 101.3, 101.8, 101.1, 101.6),
        (previous_h1 + timedelta(minutes=45), 101.6, 102.3, 101.4, 102.0),
    ])
    ref = build_reference_levels(h1, m15, symbol="XAUUSD")
    assert ref is not None
    assert ref.m15_source == "minute_45"
    assert ref.m15_ref_high == 102.3
    assert ref.m15_ref_low == 101.4


def test_reference_levels_range_in_range():
    rows = [
        (100.0, 100.5, 99.7, 100.2),
        (100.2, 100.6, 99.8, 100.4),
        (100.4, 100.7, 99.9, 100.5),
        (100.5, 100.8, 100.0, 100.6),
    ]
    h1 = _h1_df(rows)
    previous_h1 = datetime(2026, 5, 13, 8, 0, tzinfo=timezone.utc)
    m15 = _m15_df([(previous_h1 + timedelta(minutes=45), 100.5, 100.7, 100.3, 100.6)])
    ref = build_reference_levels(h1, m15, symbol="XAUUSD", range_in_range_max_pips=30.0)
    assert ref is not None
    assert ref.h1_source == "range_dominant_h1"


def test_compute_stats_insufficient_when_few_rows():
    h1 = _h1_df([(100, 101, 99, 100), (100, 102, 99, 101), (101, 103, 100, 102), (102, 104, 101, 103), (103, 105, 102, 104)])
    stats = compute_h1_sweep_stats(h1, symbol="XAUUSD")
    assert stats.insufficient
    assert stats.samples < 10


def test_compute_stats_two_h1_window():
    rows = []
    for i in range(40):
        if i % 3 == 1:
            rows.append((100.0 + i * 0.05, 101.5 + i * 0.05, 100.0 + i * 0.05, 100.2 + i * 0.05))
        elif i % 3 == 2:
            rows.append((100.0 + i * 0.05, 100.5 + i * 0.05, 98.5 + i * 0.05, 99.0 + i * 0.05))
        else:
            rows.append((100.0 + i * 0.05, 100.5 + i * 0.05, 99.5 + i * 0.05, 100.0 + i * 0.05))
    h1 = _h1_df(rows)
    stats = compute_h1_sweep_stats(h1, symbol="XAUUSD", lookback_h1=60)
    assert stats.samples >= 10
    assert stats.mae_avg_pips > 0
    assert stats.max_excursion_pips >= stats.mae_avg_pips


def test_h1_high_reference_levels_are_anchored_to_reference():
    levels = calculate_h1_liquidity_levels(
        4679.0,
        "H1_HIGH",
        pips_to_price("XAUUSD", 1.0),
        symbol="XAUUSD",
    )
    assert levels.reference_price == 4679.0
    assert levels.reference_type == "H1_HIGH"
    assert levels.entry == 4724.9
    assert levels.sl_risk == 4777.8
    assert levels.sl_conservative == 4802.5
    assert levels.tp1 == 4582.2
    assert levels.tp2 == 4485.4
    assert levels.tp3 == 4388.6
    assert levels.tp4 == 4291.8
    assert levels.rr_to_tp1_risk == 2.7
    assert levels.rr_to_tp1_conservative == 1.84


def test_h1_low_reference_levels_are_anchored_to_reference():
    levels = calculate_h1_liquidity_levels(
        4679.0,
        "H1_LOW",
        pips_to_price("XAUUSD", 1.0),
        symbol="XAUUSD",
    )
    assert levels.reference_price == 4679.0
    assert levels.reference_type == "H1_LOW"
    assert levels.entry == 4633.1
    assert levels.sl_risk == 4580.2
    assert levels.sl_conservative == 4555.5
    assert levels.tp1 == 4775.8
    assert levels.tp2 == 4872.6
    assert levels.tp3 == 4969.4
    assert levels.tp4 == 5066.2
    assert levels.rr_to_tp4_risk == 8.19
    assert levels.rr_to_tp4_conservative == 5.58


def test_evaluate_returns_none_when_stats_insufficient():
    h1 = _h1_df([(100, 101, 99, 100), (100, 102, 99, 101), (101, 103, 100, 102)])
    m15 = _m15_df([(datetime(2026, 5, 13, 6, 45, tzinfo=timezone.utc), 100.5, 101.0, 100.3, 100.7)])
    m5 = _m1_df([(datetime(2026, 5, 13, 7, 0, tzinfo=timezone.utc) + timedelta(minutes=i * 5), 100.0, 100.1, 99.9, 100.0) for i in range(20)])
    m1 = _m1_df([(datetime(2026, 5, 13, 7, 0, tzinfo=timezone.utc) + timedelta(minutes=i), 100.0, 100.1, 99.9, 100.0) for i in range(20)])
    result = evaluate_liquidity_expansion(m1, m5, m15, h1, current_price=100.0, symbol="XAUUSD")
    assert result is None


def test_validity_rule_invalidates_when_m15_high_taken_first():
    base = datetime(2026, 5, 13, 6, 0, tzinfo=timezone.utc)
    h1 = _h1_df([(100.0 + i * 0.1, 100.5 + i * 0.1, 99.7 + i * 0.1, 100.2 + i * 0.1) for i in range(30)] + [(103.0, 103.3, 102.9, 103.0)])
    m15 = _m15_df([(base + timedelta(hours=29, minutes=45), 102.8, 103.0, 102.7, 102.9)])
    h1_open_time = base + timedelta(hours=30)
    m1 = _m1_df([
        (h1_open_time + timedelta(minutes=1), 102.9, 103.3, 102.8, 103.2),
        (h1_open_time + timedelta(minutes=2), 103.2, 103.4, 102.6, 102.7),
    ])
    m5 = _m1_df([(base + timedelta(hours=29, minutes=i * 5), 102.0, 102.5, 101.5, 102.0) for i in range(12)])
    result = evaluate_liquidity_expansion(m1, m5, m15, h1, current_price=102.5, symbol="XAUUSD")
    assert result is None


def test_long_happy_path_reclaim_trigger():
    base = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(40):
        if i % 3 == 1:
            rows.append((100.0, 101.5, 100.0, 100.2))
        elif i % 3 == 2:
            rows.append((100.0, 100.5, 98.5, 99.0))
        else:
            rows.append((100.0, 100.5, 99.5, 100.0))
    rows.append((100.0, 100.5, 99.5, 100.0))
    h1 = _h1_df(rows, start=base)
    h1_open_time = pd.Timestamp(h1.iloc[-1]["time"])
    prev_h1_start = h1_open_time - pd.Timedelta(hours=1)
    m15 = _m15_df([(prev_h1_start.to_pydatetime() + timedelta(minutes=45), 99.5, 99.8, 99.4, 99.6)])
    stats = compute_h1_sweep_stats(h1, symbol="XAUUSD")
    ref = build_reference_levels(h1, m15, symbol="XAUUSD")
    assert ref is not None
    assert not stats.insufficient
    live_mae_stats = build_live_mae_stats(stats, "XAUUSD")
    levels = calculate_h1_liquidity_levels(ref.h1_ref_low, "H1_LOW", symbol="XAUUSD", mae_stats=live_mae_stats)
    target_price = levels.entry
    m1_times = [h1_open_time.to_pydatetime() + timedelta(minutes=i) for i in range(6)]
    m1 = _m1_df([
        (m1_times[0], ref.h1_ref_low, ref.h1_ref_low + 0.05, target_price, target_price + 0.02),
        (m1_times[1], target_price, target_price + 0.05, target_price - 0.02, target_price + 0.01),
        (m1_times[2], target_price, ref.h1_ref_low + 0.02, target_price - 0.01, ref.h1_ref_low + 0.01),
        (m1_times[3], ref.h1_ref_low + 0.01, ref.h1_ref_low + 0.05, ref.h1_ref_low, ref.h1_ref_low + 0.03),
    ])
    m5 = _m1_df([(base + timedelta(minutes=i * 5), 100.0, 100.2, 99.8, 100.0) for i in range(20)])
    result = evaluate_liquidity_expansion(m1, m5, m15, h1, current_price=target_price, symbol="XAUUSD")
    assert result is not None
    assert result.direction == "LONG"
    assert result.trigger_kind == "reclaim"
    assert result.reference_type == "H1_LOW"
    assert result.reference_price == levels.reference_price
    assert result.entry == levels.entry
    assert result.stop == levels.sl_conservative
    assert result.sl_risk == levels.sl_risk
    assert result.sl_conservative == levels.sl_conservative
    assert result.tp1 == levels.tp1
    assert result.tp2 == levels.tp2
    assert result.tp3 == levels.tp3
    assert result.tp4 == levels.tp4
    assert result.rr_tp1 > 0


def test_h1_reference_levels_do_not_calculate_targets_from_entry():
    levels = calculate_h1_liquidity_levels(4700.0, "H1_LOW", symbol="XAUUSD")
    entry_based_tp1 = round(levels.entry + pips_to_price("XAUUSD", 96.8), 2)
    assert levels.tp1 == 4796.8
    assert levels.tp1 != entry_based_tp1


class _DummySender:
    def __init__(self):
        self.sent: list[str] = []

    def send_text(self, text: str) -> dict:
        self.sent.append(text)
        return {"ok": True}


def _make_signal(rr_tp1: float = 2.0, direction: str = "LONG") -> LiquidityExpansionSignal:
    ref = LiquidityReferenceLevels(
        h1_ref_high=4710.0,
        h1_ref_low=4700.0,
        m15_ref_high=4708.0,
        m15_ref_low=4702.0,
        h1_source="previous_h1",
        m15_source="minute_45",
    )
    stats = SweepStatistics(mae_avg_pips=5.0, max_excursion_pips=12.0, avg_expansion_pips=25.0, max_expansion_pips=80.0, samples=15)
    return LiquidityExpansionSignal(
        symbol="XAUUSD",
        direction=direction,  # type: ignore[arg-type]
        candle_model="IMMEDIATE_EXPANSION",
        reference=ref,
        stats=stats,
        entry=4699.5 if direction == "LONG" else 4710.5,
        stop=4698.5 if direction == "LONG" else 4711.5,
        tp1=4702.0 if direction == "LONG" else 4708.0,
        tp2=4704.0 if direction == "LONG" else 4706.0,
        tp3=4706.0 if direction == "LONG" else 4704.0,
        tp4=4708.0 if direction == "LONG" else 4702.0,
        tp1_basis="quartile_25",
        rr_tp1=rr_tp1,
        rr_tp4=8.0,
        trigger_kind="reclaim",
        reason_codes=["liquidity_expansion_model_2_0", "trigger_reclaim"],
        timestamp_utc=datetime.now(timezone.utc),
    )


def _make_scanner(settings_overrides: dict | None = None) -> tuple[ScalpingScanner, _DummySender]:
    sender = _DummySender()
    overrides = {"telegram_token": "x", "telegram_chat_id": "1"}
    overrides.update(settings_overrides or {})
    settings = Settings(**overrides)
    scanner = ScalpingScanner(settings, telegram_bot=sender)
    scanner.first_silent_scan_pending = False
    scanner.last_price = 4699.5
    scanner.last_spread = 1.0
    return scanner, sender


def test_min_rr_floor_blocks_signal():
    scanner, sender = _make_scanner({"liquidity_expansion_min_rr_tp1": 5.0})
    market_data = {"M1": pd.DataFrame([{"time": datetime.now(timezone.utc), "o": 1, "h": 1, "l": 1, "c": 1}])}
    market_data["M5"] = market_data["M1"].copy()
    market_data["M15"] = market_data["M1"].copy()
    market_data["H1"] = market_data["M1"].copy()
    weak_signal = _make_signal(rr_tp1=1.0)
    with patch("dazro_trade.runtime.scanner.evaluate_liquidity_expansion", return_value=weak_signal):
        result = scanner._maybe_send_liquidity_expansion(market_data, "London", datetime.now(timezone.utc))
    assert result is False
    assert sender.sent == []


def test_spread_gate_blocks_before_evaluation():
    scanner, sender = _make_scanner({"liquidity_expansion_max_spread_pips": 1.0})
    scanner.last_spread = 5.0
    market_data: dict = {}
    with patch("dazro_trade.runtime.scanner.evaluate_liquidity_expansion") as mock_eval:
        result = scanner._maybe_send_liquidity_expansion(market_data, "London", datetime.now(timezone.utc))
    assert result is False
    assert sender.sent == []
    mock_eval.assert_not_called()


def test_risk_manager_blocks_signal():
    scanner, sender = _make_scanner({"max_daily_signals": 1})
    scanner.risk.state.signals_today = 5
    market_data = {tf: pd.DataFrame([{"time": datetime.now(timezone.utc), "o": 1, "h": 1, "l": 1, "c": 1}]) for tf in ("M1", "M5", "M15", "H1")}
    good_signal = _make_signal(rr_tp1=3.0)
    pre_count = len(sender.sent)
    pre_register = scanner.risk.state.signals_today
    with patch("dazro_trade.runtime.scanner.evaluate_liquidity_expansion", return_value=good_signal):
        result = scanner._maybe_send_liquidity_expansion(market_data, "London", datetime.now(timezone.utc))
    assert result is False
    assert len(sender.sent) == pre_count
    assert scanner.risk.state.signals_today == pre_register


def test_liquidity_expansion_message_shows_absolute_h1_reference_levels():
    signal = _make_signal(rr_tp1=2.0, direction="SHORT")
    levels = calculate_h1_liquidity_levels(4679.0, "H1_HIGH", symbol="XAUUSD")
    signal = replace(
        signal,
        entry=levels.entry,
        stop=levels.sl_conservative,
        tp1=levels.tp1,
        tp2=levels.tp2,
        tp3=levels.tp3,
        tp4=levels.tp4,
        reference_type=levels.reference_type,
        reference_price=levels.reference_price,
        sl_risk=levels.sl_risk,
        sl_conservative=levels.sl_conservative,
        rr_to_tp1_risk=levels.rr_to_tp1_risk,
        rr_to_tp4_risk=levels.rr_to_tp4_risk,
        rr_to_tp1_conservative=levels.rr_to_tp1_conservative,
        rr_to_tp4_conservative=levels.rr_to_tp4_conservative,
    )
    text = ScalpingScanner._format_liquidity_expansion_message(signal, lot_size=None)
    assert "H1 HIGH reference: 4679.0" in text
    assert "Entry: 4724.9" in text
    assert "SL Risk: 4777.8" in text
    assert "SL Conservative: 4802.5" in text
    assert "TP1: 4582.2" in text
    assert text.splitlines()[-1] == "Paper/demo signal only. No real-money execution."


def test_tp1_hit_moves_stop_to_be_and_progresses_to_tp2():
    when = datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc)
    trade = VirtualTrade(
        trade_id="vt-1",
        signal_key="liqexp:test",
        symbol="XAUUSD",
        direction="LONG",
        zone_id="h1",
        signal_time=when,
        entry_area_low=4700.0,
        entry_area_high=4700.0,
        stop_loss=4690.0,
        tp1=4710.0,
        tp2=4720.0,
        status="ENTERED",
        entry_time=when,
        entry_price=4700.0,
        source="liquidity_expansion",
        strategy="liquidity_expansion",
        tp3=4730.0,
        tp4=4740.0,
        original_stop_loss=4690.0,
    )
    scanner, _ = _make_scanner()
    scanner._update_liquidity_expansion_outcome(trade, candle_high=4711.0, candle_low=4699.0, when=when)
    assert trade.tp1_hit is True
    assert trade.be_activated is True
    assert trade.stop_loss == 4700.0
    assert trade.status == "TP1_HIT"
    scanner._update_liquidity_expansion_outcome(trade, candle_high=4721.0, candle_low=4700.5, when=when)
    assert trade.tp2_hit is True
    assert trade.status == "TP2_HIT"
    scanner._update_liquidity_expansion_outcome(trade, candle_high=4715.0, candle_low=4699.9, when=when)
    assert trade.status == "BE_HIT"


def test_v1_trade_uses_existing_logic():
    when = datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc)
    trade = VirtualTrade(
        trade_id="vt-v1",
        signal_key="v1:test",
        symbol="XAUUSD",
        direction="LONG",
        zone_id="z",
        signal_time=when,
        entry_area_low=4700.0,
        entry_area_high=4700.0,
        stop_loss=4690.0,
        tp1=4710.0,
        tp2=4720.0,
        status="ENTERED",
        entry_time=when,
        entry_price=4700.0,
    )
    scanner, _ = _make_scanner()
    market_data = {"M1": pd.DataFrame([{"time": when, "o": 4700.0, "h": 4711.0, "l": 4699.0, "c": 4710.5}])}
    scanner._update_trade_outcome(trade, market_data, when)
    assert trade.status == "TP1_HIT"
    assert trade.be_activated is False
    assert trade.stop_loss == 4690.0


def test_dedup_namespace_isolated_from_v1():
    scanner, sender = _make_scanner({"liquidity_expansion_min_rr_tp1": 0.5, "max_daily_signals": 99})
    market_data = {tf: pd.DataFrame([{"time": datetime.now(timezone.utc), "o": 1, "h": 1, "l": 1, "c": 1}]) for tf in ("M1", "M5", "M15", "H1")}
    good_signal = _make_signal(rr_tp1=2.0, direction="LONG")
    scanner.deduplicator.sent_keys.add("XAUUSD:LONG:M15:bullish_fvg:4700.0:4700.0:London:" + datetime.now(timezone.utc).date().isoformat())
    pre_v1_keys = len(scanner.deduplicator.sent_keys)
    with patch("dazro_trade.runtime.scanner.evaluate_liquidity_expansion", return_value=good_signal):
        result = scanner._maybe_send_liquidity_expansion(market_data, "London", datetime.now(timezone.utc))
    assert result is True
    new_keys = scanner.deduplicator.sent_keys - {k for k in scanner.deduplicator.sent_keys if not k.startswith("liqexp:")}
    assert any(key.startswith("liqexp:") for key in scanner.deduplicator.sent_keys)
    assert len(scanner.deduplicator.sent_keys) == pre_v1_keys + 1


def test_strategy_1_regression_unchanged():
    from tests.test_scalping_runtime import (
        test_m15_sweep_m5_confirmation_m1_trigger_becomes_triggered as strategy1_test,
    )
    strategy1_test()
