from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pandas as pd

from dazro_trade.analysis.reentry import evaluate_reentry
from dazro_trade.analysis.scalping import ScalpingConfig, apply_execution_gates, target_validation_passes
from dazro_trade.analysis.targets import TargetPolicy, build_intelligent_targets, validate_target_space
from dazro_trade.analysis.volatility import volatility_snapshot
from dazro_trade.core.config import Settings
from dazro_trade.core.models import ScalpingDecision, SetupZone
from dazro_trade.core.symbols import pips_to_price, price_to_pips
from dazro_trade.notifications.telegram_bot import format_scalping_decision
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
    assert pips_to_price("XAUUSD", 50) == 5.00
    assert pips_to_price("XAUUSD", 80) == 8.00
    assert pips_to_price("XAUUSD", 100) == 10.00
    assert pips_to_price("XAUUSD", 300) == 30.00


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
    assert snap["spread_pips"] == 2.0


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


def test_short_bug_live_price_above_stop_is_invalidated_with_score_zero():
    d = apply_execution_gates(decision("SHORT", entry_area=(4719.25, 4719.85), stop=4722.17), 4725.61)
    assert d.state == "INVALIDATED"
    assert d.score == 0
    assert "current_price_above_short_stop" in d.rejection_reasons
    assert "setup_invalidated_before_signal" in d.reason_codes


def test_long_invalidated_when_price_below_stop():
    d = apply_execution_gates(decision("LONG", entry_area=(4720, 4721), stop=4718), 4717.80)
    assert d.state == "INVALIDATED"
    assert "current_price_below_long_stop" in d.rejection_reasons
    assert not d.telegram_allowed


def test_short_bearish_zone_below_price_is_invalidated():
    d = decision("SHORT", entry_area=(4719.25, 4719.85), stop=4730.0)
    d.primary_zone.high = 4721.37
    d.primary_zone.zone_type = "bearish_ob"
    apply_execution_gates(d, 4725.61)
    assert d.state == "INVALIDATED"
    assert "short_zone_below_current_price_invalid" in d.rejection_reasons


def test_long_bullish_zone_above_price_is_invalidated():
    d = decision("LONG", entry_area=(4725.0, 4726.0), stop=4710.0)
    d.primary_zone.low = 4723.0
    d.primary_zone.zone_type = "bullish_fvg"
    apply_execution_gates(d, 4718.0)
    assert d.state == "INVALIDATED"
    assert "long_zone_above_current_price_invalid" in d.rejection_reasons


def test_entry_missed_do_not_chase_short():
    d = apply_execution_gates(decision("SHORT", entry_area=(4719.5, 4720.0), stop=4723.16), 4718.0)
    assert d.state == "EXPIRED"
    assert "entry_missed_do_not_chase" in d.rejection_reasons
    assert "state_corrected_from_entered_to_not_actionable" in d.reason_codes
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
    assert target_validation_passes(out, ScalpingConfig(min_rr=2.0, min_rr_vwap_scalp=1.0))


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
    assert "official_tp1_too_close" in rejected["reason_codes"]
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
    trade.status = "ENTERED"
    scanner.trades.append(trade)
    scanner._update_trade_outcome(trade, {"M1": frame([(4720, 4724, 4717, 4719)])}, datetime.now(timezone.utc))
    assert trade.status == "STOP_HIT"
    assert "ambiguous_intrabar_path_assume_conservative_stop" in trade.reentry_reason_codes


def test_pending_entry_stop_before_entry_is_invalidated_before_entry():
    scanner = ScalpingScanner(Settings())
    trade = VirtualTrade("t1", "sig", "XAUUSD", "SHORT", "z", datetime.now(timezone.utc), 4719, 4720, 4723.16, 4718, 4717)
    scanner._update_pending_trade(trade, {"M1": frame([(4724, 4724.2, 4723.4, 4724)])}, datetime.now(timezone.utc), None)
    assert trade.status == "INVALIDATED_BEFORE_ENTRY"
    assert "setup_invalidated_before_entry" in trade.reason_codes


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
        vwap_snapshot={"vwap": 4720.0},
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
    scanner = ScalpingScanner(
        Settings(
            telegram_token="x",
            telegram_chat_id="1",
            send_triggered_only=False,
            send_approaching_alerts=True,
        ),
        telegram_bot=sender,
    )
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
    scanner = ScalpingScanner(
        Settings(
            telegram_token="x",
            telegram_chat_id="1",
            send_triggered_only=False,
            send_approaching_alerts=True,
        ),
        telegram_bot=sender,
    )
    assert scanner._maybe_send_reaction_alert(_reaction_decision(14.8, "ARMED"), "London")
    assert not scanner._maybe_send_reaction_alert(_reaction_decision(14.8, "ARMED"), "London")
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
    scanner = ScalpingScanner(
        Settings(
            telegram_token="x",
            telegram_chat_id="1",
            send_triggered_only=False,
            send_sweep_intrabar_alerts=True,
        ),
        telegram_bot=sender,
    )
    decision = _reaction_decision(75, "SWEEPING_INTRABAR")
    assert scanner._maybe_send_reaction_alert(decision, "London")
    assert "SWEEP IN CORSO" in sender.sent[0]
    assert "NO ENTRY ANCORA" in sender.sent[0]


def test_reentry_alerts_are_sent_once_per_state():
    class Sender:
        def __init__(self):
            self.sent = []

        def send_text(self, text):
            self.sent.append(text)
            return {"ok": True}

    sender = Sender()
    scanner = ScalpingScanner(Settings(telegram_token="x", telegram_chat_id="1"), telegram_bot=sender)
    trade = VirtualTrade("t1", "sig", "XAUUSD", "SHORT", "z", datetime.now(timezone.utc), 4719, 4720, 4723.16, 4718, 4717)
    trade.status = "STOP_HIT"
    trade.stop_hit_price = 4723.16
    trade.reentry_state = "REENTRY_WATCH"
    assert scanner._maybe_send_reentry_alert(trade)
    assert not scanner._maybe_send_reentry_alert(trade)
    trade.reentry_state = "REENTRY_VALID"
    trade.reentry_reason_codes = ["stop_sweep_detected", "close_back_below_old_stop"]
    assert scanner._maybe_send_reentry_alert(trade)
    assert not scanner._maybe_send_reentry_alert(trade)
    assert len(sender.sent) == 2


def test_status_shows_dynamic_alert_config():
    scanner = ScalpingScanner(Settings(send_approaching_alerts=True, send_armed_reaction_alerts=False, send_sweep_intrabar_alerts=True, send_triggered_only=False))
    text = scanner.format_status()
    assert "Alert automatici:" in text
    assert "approaching=on" in text
    assert "armed=off" in text


def test_watch_message_uses_no_entry_and_theoretical_levels():
    d = decision("SHORT", entry_area=(4719.25, 4719.85), stop=4722.17)
    d.state = "WATCH"
    d.score = 40
    text = format_scalping_decision(d)
    assert "NO ENTRY" in text
    assert "Entry teorica solo dopo trigger" in text
    assert "SL teorico" in text


def test_triggered_message_can_show_operational_entry():
    d = decision("SHORT", entry_area=(4719.25, 4719.85), stop=4722.17)
    text = format_scalping_decision(d)
    assert "XAUUSD — SHORT VALID" in text
    assert "Entry area" in text
    assert "SL:" in text


def test_stale_tick_blocks_signal():
    scanner = ScalpingScanner(Settings())
    scanner.mt5_handler = object()
    scanner.last_tick_snapshot = {"ok": True}
    scanner.last_tick_time = datetime.now(timezone.utc) - timedelta(seconds=20)
    d = decision("SHORT", entry_area=(4719.25, 4719.85), stop=4722.17)
    scanner._apply_tick_freshness_gate(d, datetime.now(timezone.utc))
    assert d.state == "WATCH"
    assert "stale_price_data" in d.reason_codes
    assert not d.telegram_allowed
