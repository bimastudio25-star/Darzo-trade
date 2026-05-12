from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pandas as pd

from dazro_trade.analysis.reentry import evaluate_reentry
from dazro_trade.analysis.scalping import apply_execution_gates
from dazro_trade.analysis.targets import TargetPolicy, build_intelligent_targets, validate_target_space
from dazro_trade.analysis.volatility import volatility_snapshot
from dazro_trade.core.config import Settings
from dazro_trade.core.models import ScalpingDecision, SetupZone
from dazro_trade.core.symbols import pips_to_price, price_to_pips
from dazro_trade.runtime.scanner import ScalpingScanner, VirtualTrade
from mt5_handler import MT5Handler
import mt5_handler


def frame(rows):
    base = datetime(2026, 5, 12, 7, 0, tzinfo=timezone.utc)
    return pd.DataFrame(
        [{"time": base, "o": r[0], "h": r[1], "l": r[2], "c": r[3], "vol": r[4] if len(r) > 4 else 100} for r in rows]
    )


def decision(direction="SHORT", entry_area=(4719.0, 4720.0), stop=4723.16):
    zone = SetupZone("z", "XAUUSD", "M15", "liquidity_sweep", "LTF_SETUP", "TRIGGERED", "SELL" if direction == "SHORT" else "BUY", 4719, 4720)
    return ScalpingDecision(
        symbol="XAUUSD",
        setup_type="REVERSAL_AFTER_SWEEP",
        direction=direction,
        state="TRIGGERED",
        score=95,
        confidence=0.95,
        htf_context={},
        intraday_context={},
        liquidity={},
        primary_zone=zone,
        entry_area=entry_area,
        stop=stop,
        targets=[{"label": "TP1", "price": 4718, "basis": "test"}],
    )


def test_symbol_conversion_specific_values():
    assert pips_to_price("XAUUSD", 50) == 0.50
    assert pips_to_price("XAUUSD", 80) == 0.80
    assert pips_to_price("XAUUSD", 100) == 1.00
    assert pips_to_price("XAUUSD", 300) == 3.00


def test_mt5_tick_snapshot_spread_uses_symbol_spec(monkeypatch):
    class Tick:
        bid = 4720.00
        ask = 4720.20
        time = 123

    class FakeMT5:
        @staticmethod
        def symbol_info_tick(symbol):
            return Tick()

    monkeypatch.setattr(mt5_handler, "mt5", FakeMT5)
    handler = MT5Handler("", "", "")
    handler.symbol = "XAUUSD"
    snap = handler.get_tick_snapshot()
    assert snap["spread_pips"] == 20


def test_scanner_collect_market_data_requests_d1():
    class FakeHandler:
        symbol = "XAUUSD"

        def __init__(self):
            self.calls = {}

        def get_candles(self, tf, n):
            self.calls[tf] = n
            return frame([(1, 2, 0.5, 1.5)])

        def get_tick_snapshot(self):
            return {"ok": True, "bid": 4720.0, "ask": 4720.2, "mid": 4720.1, "spread_pips": 20}

    fake = FakeHandler()
    scanner = ScalpingScanner(Settings(), mt5_handler=fake)
    asyncio.run(scanner.collect_market_data())
    assert fake.calls["D1"] == 300


def test_short_invalidated_when_price_above_stop():
    d = apply_execution_gates(decision("SHORT", stop=4723.16), 4724.00)
    assert d.state == "INVALIDATED"
    assert "current_price_above_short_stop" in d.rejection_reasons
    assert not d.telegram_allowed


def test_long_invalidated_when_price_below_stop():
    d = apply_execution_gates(decision("LONG", entry_area=(4720, 4721), stop=4718), 4717.80)
    assert d.state == "INVALIDATED"
    assert "current_price_below_long_stop" in d.rejection_reasons
    assert not d.telegram_allowed


def test_entry_missed_do_not_chase_short():
    d = apply_execution_gates(decision("SHORT", entry_area=(4719.5, 4720.0), stop=4723.16), 4718.0)
    assert d.state == "ENTERED"
    assert "entry_missed_do_not_chase" in d.rejection_reasons
    assert not d.telegram_allowed


def test_vwap_1r_scalp_target_valid():
    targets = build_intelligent_targets(
        symbol="XAUUSD",
        direction="SHORT",
        entry=4720.0,
        stop=4720.30,
        vwap_snapshot={"vwap": 4719.50},
        liquidity_pools=[],
    )
    out = validate_target_space("XAUUSD", "SHORT", 4720.0, 4720.30, targets, {"vwap": 4719.50}, [], TargetPolicy())
    assert out["valid"]
    assert out["setup_target_type"] == "VWAP_1R_SCALP"
    assert "vwap_1r_target_valid" in out["reason_codes"]


def test_normal_target_below_50_pips_rejected_and_100_valid():
    rejected = validate_target_space(
        "XAUUSD",
        "SHORT",
        4720.0,
        4720.5,
        [{"price": 4719.70, "distance_pips": 30, "basis": "liquidity"}],
        None,
        [],
        TargetPolicy(),
    )
    assert not rejected["valid"]
    assert "target_space_below_minimum" in rejected["reason_codes"]
    valid = validate_target_space(
        "XAUUSD",
        "SHORT",
        4720.0,
        4720.5,
        [{"price": 4719.00, "distance_pips": 100, "basis": "liquidity"}],
        None,
        [],
        TargetPolicy(),
    )
    assert valid["valid"]
    assert "preferred_reaction_target_100_pips_available" in valid["reason_codes"]


def test_virtual_trade_stop_hit_and_conservative_ambiguous_path():
    scanner = ScalpingScanner(Settings())
    trade = VirtualTrade("t1", "sig", "XAUUSD", "SHORT", "z", datetime.now(timezone.utc), 4719, 4720, 4723.16, 4718, 4717)
    scanner.trades.append(trade)
    scanner._update_trade_outcome(trade, {"M1": frame([(4720, 4724, 4717, 4719)])}, datetime.now(timezone.utc))
    assert trade.status == "STOP_HIT"
    assert "ambiguous_intrabar_path_assume_conservative_stop" in trade.reentry_reason_codes


def test_reentry_no_reentry_on_accepted_breakout_above_stop():
    ctx = evaluate_reentry(
        symbol="XAUUSD",
        original_signal_id="s1",
        direction="SHORT",
        original_entry=4720,
        original_stop=4723.16,
        stop_hit_price=4723.16,
        stop_hit_time=datetime.now(timezone.utc),
        current_price=4724.0,
        m1=frame([(4723, 4724, 4722.8, 4724)]),
        m5=frame([(4723, 4724, 4722.8, 4724)]),
        settings=Settings(),
    )
    assert ctx.state == "NO_REENTRY"
    assert "accepted_breakout_above_stop" in ctx.reason_codes


def test_reentry_valid_after_stop_sweep_close_back_choch_fvg():
    m1 = frame([(4723, 4723.4, 4722.9, 4723.1), (4723, 4723.2, 4722.8, 4723.0), (4723, 4723.1, 4722.7, 4723.0), (4723, 4723.1, 4722.6, 4723.0), (4722.8, 4722.9, 4721.8, 4721.9), (4721.9, 4722, 4721.5, 4721.6)])
    m5 = frame([(4723, 4723.5, 4722.8, 4723.2), (4723.1, 4723.3, 4722.95, 4723.0), (4723, 4723.2, 4722.9, 4723.1), (4722.5, 4722.6, 4721.4, 4721.5), (4721.5, 4721.6, 4721.3, 4721.4)])
    ctx = evaluate_reentry(
        symbol="XAUUSD",
        original_signal_id="s1",
        direction="SHORT",
        original_entry=4720,
        original_stop=4723.16,
        stop_hit_price=4723.16,
        stop_hit_time=datetime.now(timezone.utc),
        current_price=4722.5,
        m1=m1,
        m5=m5,
        vwap_snapshot={"vwap": 4721.5},
        settings=Settings(),
    )
    assert ctx.state in {"REENTRY_VALID", "REENTRY_CANDIDATE"}
    assert "close_back_below_old_stop" in ctx.reason_codes


def test_volatility_extreme_blocks_reentry():
    snap = volatility_snapshot(symbol="XAUUSD", m1=frame([(1, 1.1, 0.9, 1, 100) for _ in range(20)] + [(1, 3, -1, 2, 1000)]), m5=frame([(1, 2, 0, 1)]))
    assert snap["volatility_state"] == "extreme"
    assert not snap["safe_for_reentry"]


def _reaction_decision(distance_pips=150, status="ARMED"):
    pool = {
        "id": "pool1",
        "pool_id": "pool1",
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "level": 4722.3,
        "side": "buy_side",
        "pool_type": "external_high",
        "distance_pips": distance_pips,
        "confluences": ["M15/H1 liquidity"],
    }
    return ScalpingDecision(
        symbol="XAUUSD",
        setup_type="LIQUIDITY_REACTION",
        direction="SHORT",
        state="ARMED",
        score=60,
        confidence=0.6,
        htf_context={},
        intraday_context={},
        liquidity={"pools": [pool], "sweeps": [{"pool_id": "pool1", "status": status, "level": 4722.3, "reason_codes": ["number_theory_confluence"]}]},
    )


def test_remote_300_plus_pips_no_automatic_alert():
    class Sender:
        sent = []

        def send_text(self, text):
            self.sent.append(text)
            return {"ok": True}

    sender = Sender()
    scanner = ScalpingScanner(Settings(telegram_token="x", telegram_chat_id="1"), telegram_bot=sender)
    assert not scanner._maybe_send_reaction_alert(_reaction_decision(301), "London")
    assert sender.sent == []


def test_approaching_and_armed_milestones_send_once():
    class Sender:
        def __init__(self):
            self.sent = []

        def send_text(self, text):
            self.sent.append(text)
            return {"ok": True}

    sender = Sender()
    scanner = ScalpingScanner(Settings(telegram_token="x", telegram_chat_id="1"), telegram_bot=sender)
    assert scanner._maybe_send_reaction_alert(_reaction_decision(148, "ARMED"), "London")
    assert not scanner._maybe_send_reaction_alert(_reaction_decision(148, "ARMED"), "London")
    assert len(sender.sent) == 1
    assert "ZONA IN AVVICINAMENTO" in sender.sent[0]


def test_sweep_intrabar_alert_is_not_trade_signal():
    class Sender:
        def __init__(self):
            self.sent = []

        def send_text(self, text):
            self.sent.append(text)
            return {"ok": True}

    sender = Sender()
    scanner = ScalpingScanner(Settings(telegram_token="x", telegram_chat_id="1"), telegram_bot=sender)
    decision = _reaction_decision(75, "SWEEPING_INTRABAR")
    assert scanner._maybe_send_reaction_alert(decision, "London")
    assert "SWEEP IN CORSO" in sender.sent[0]
    assert "NO ENTRY ANCORA" in sender.sent[0]
