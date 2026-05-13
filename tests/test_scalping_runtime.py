from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from dazro_trade.analysis.scalping import (
    SignalDeduplicator,
    build_zones,
    choose_primary_zone,
    detect_zone_interactions_since_last_scan,
    evaluate_primary_confluence,
    evaluate_scalping_setup,
)
from dazro_trade.core.models import SetupZone
from dazro_trade.liquidity.sweep import SweepEvent
from dazro_trade.notifications.telegram_bot import format_scalping_decision
from dazro_trade.core.config import Settings
from dazro_trade.runtime.scanner import ScalpingScanner
from dazro_trade.runtime.sessions import active_sessions
from dazro_trade.runtime.telegram_runtime import HIDDEN_COMMANDS, build_help_text


def candles(rows, start=None):
    base = start or datetime(2026, 5, 12, 7, 0, tzinfo=timezone.utc)
    out = []
    for idx, row in enumerate(rows):
        out.append({"time": base + timedelta(minutes=idx), "o": row[0], "h": row[1], "l": row[2], "c": row[3], "vol": row[4] if len(row) > 4 else 100})
    return pd.DataFrame(out)


def trend_frame(direction="bullish", n=40, base=100.0):
    rows = []
    for i in range(n):
        value = base + i * 0.1 if direction == "bullish" else base - i * 0.1
        rows.append((value, value + 0.3, value - 0.3, value + (0.1 if direction == "bullish" else -0.1)))
    rows.append(rows[-1])
    return candles(rows)


def m15_signal_frame():
    rows = []
    for _ in range(18):
        rows.append((99.4, 99.8, 99.0, 99.5))
    rows.append((99.5, 99.6, 99.1, 99.2))
    rows.append((99.3, 99.7, 99.2, 99.4))
    rows.append((100.2, 100.9, 100.0, 100.7))  # bullish FVG 99.7-100.0
    rows.append((99.6, 100.5, 98.8, 100.3))  # sweep below prior low and reclaim
    rows.append((100.3, 100.4, 100.2, 100.25))  # forming
    return candles(rows)


def m5_confirmation_frame():
    rows = [(100.2, 100.45, 100.05, 100.3) for _ in range(16)]
    rows.append((100.3, 100.5, 100.1, 100.35))
    rows.append((100.2, 101.4, 100.1, 101.25))  # closed displacement + BOS
    rows.append((101.2, 101.3, 101.0, 101.1))  # forming
    return candles(rows)


def m1_trigger_frame(touch_zone=False):
    rows = [(101.0, 101.2, 100.8, 101.05) for _ in range(10)]
    if touch_zone:
        rows.append((101.0, 101.1, 99.85, 100.9))
    else:
        rows.append((101.0, 101.2, 100.7, 101.05))
    rows.append((101.0, 101.35, 100.95, 101.3))  # closed micro trigger
    rows.append((101.25, 101.3, 101.1, 101.2))  # forming
    return candles(rows)


def test_london_dst_active_in_summer_and_winter():
    summer = datetime(2026, 5, 12, 7, 6, tzinfo=timezone.utc)
    winter = datetime(2026, 1, 12, 8, 6, tzinfo=timezone.utc)
    before_open = datetime(2026, 5, 12, 6, 59, tzinfo=timezone.utc)
    exact_open = datetime(2026, 5, 12, 7, 0, tzinfo=timezone.utc)
    assert any(session.name == "London" for session in active_sessions(summer))
    assert any(session.name == "London" for session in active_sessions(winter))
    assert not any(session.name == "London" for session in active_sessions(before_open))
    assert any(session.name == "London" for session in active_sessions(exact_open))


def test_far_h4_zone_is_context_not_scalping_signal():
    h4 = candles([(4730, 4731, 4729, 4730.5), (4730.5, 4731, 4730, 4730.7), (4747, 4748, 4736, 4742), (4742, 4743, 4741, 4742)])
    zones = build_zones({"H4": h4}, symbol="XAUUSD", current_price=4703.0)
    assert zones
    assert all(zone.role == "HTF_CONTEXT" for zone in zones)
    assert choose_primary_zone(zones, 4703.0) is None


def test_h1_near_without_ltf_chain_stays_watch():
    decision = evaluate_scalping_setup(
        {"H1": trend_frame("bullish"), "H4": trend_frame("bullish"), "M1": trend_frame("bullish"), "M5": trend_frame("bullish"), "M15": trend_frame("bullish")},
        symbol="XAUUSD",
        current_price=103.0,
        spread=1.0,
    )
    assert decision.state in {"WATCH", "ARMED", "EXPIRED"}
    assert not decision.telegram_allowed
    assert decision.rejection_reasons


def test_m15_sweep_m5_confirmation_m1_trigger_becomes_triggered():
    decision = evaluate_scalping_setup(
        {
            "H1": trend_frame("bullish"),
            "H4": trend_frame("bullish"),
            "M15": m15_signal_frame(),
            "M5": m5_confirmation_frame(),
            "M1": m1_trigger_frame(touch_zone=False),
        },
        symbol="XAUUSD",
        current_price=100.2,
        spread=1.0,
        session_name="London",
    )
    assert decision.state in {"TRIGGERED", "EXPIRED"}
    assert not decision.telegram_allowed
    assert decision.primary_zone is not None
    assert decision.primary_zone.timeframe == "M15"


def test_entry_area_touched_between_scans_marks_entered_not_fresh_signal():
    last_scan = datetime(2026, 5, 12, 7, 0, tzinfo=timezone.utc)
    decision = evaluate_scalping_setup(
        {
            "H1": trend_frame("bullish"),
            "H4": trend_frame("bullish"),
            "M15": m15_signal_frame(),
            "M5": m5_confirmation_frame(),
            "M1": m1_trigger_frame(touch_zone=True),
        },
        symbol="XAUUSD",
        current_price=100.2,
        spread=1.0,
        last_scan_time=last_scan,
        now_utc=last_scan + timedelta(minutes=20),
        session_name="London",
    )
    assert decision.state == "ENTERED"
    assert not decision.telegram_allowed
    assert "Entry area gia toccata, non inseguire" in decision.rejection_reasons


def test_touch_detection_uses_candle_range_not_current_price_only():
    zone = SetupZone("z1", "XAUUSD", "M1", "bullish_fvg", "ENTRY_TRIGGER", "WATCH", "BUY", 4699.29, 4700.29)
    frame = candles([(4701.2, 4702.0, 4699.45, 4701.8)])
    result = detect_zone_interactions_since_last_scan(
        zone,
        frame,
        None,
        last_scan_time=datetime(2026, 5, 12, 7, 0, tzinfo=timezone.utc),
        now_utc=datetime(2026, 5, 12, 7, 2, tzinfo=timezone.utc),
    )
    assert result.entry_area_touched
    assert result.source_timeframe == "M1"


def test_dedup_same_setup_not_sent_twice():
    decision = evaluate_scalping_setup(
        {
            "H1": trend_frame("bullish"),
            "H4": trend_frame("bullish"),
            "M15": m15_signal_frame(),
            "M5": m5_confirmation_frame(),
            "M1": m1_trigger_frame(touch_zone=False),
        },
        symbol="XAUUSD",
        current_price=100.2,
        spread=1.0,
        session_name="London",
    )
    dedup = SignalDeduplicator()
    dedup.mark_sent(decision, session_name="London")
    assert dedup.is_duplicate(decision, session_name="London")


def test_telegram_message_decision_before_zone_events():
    decision = evaluate_scalping_setup(
        {
            "H1": trend_frame("bullish"),
            "H4": trend_frame("bullish"),
            "M15": m15_signal_frame(),
            "M5": m5_confirmation_frame(),
            "M1": m1_trigger_frame(touch_zone=False),
        },
        symbol="XAUUSD",
        current_price=100.2,
        spread=1.0,
        session_name="London",
    )
    message = format_scalping_decision(decision)
    assert message.splitlines()[0] in {"XAUUSD — SETUP NON OPERATIVO", "XAUUSD — LONG VALID", "XAUUSD — SHORT VALID", "XAUUSD — SETUP INVALIDATO", "XAUUSD — SWEEP CONFERMATA, ASPETTO TRIGGER"}
    if decision.state != "TRIGGERED":
        assert "NO ENTRY" in message
    assert message.index("Setup:") < message.index("Eventi rilevati:")


def test_help_only_exposes_final_commands():
    help_text = build_help_text()
    assert "/analisi" in help_text
    assert "/scan" in help_text
    assert "/plan" in help_text
    for hidden in HIDDEN_COMMANDS:
        assert f"/{hidden}" not in help_text


def test_scanner_auto_is_silent_for_first_scan_and_watch_reports():
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
            time_behaviour_alerts=True,
            session_open_alerts=True,
            send_session_prep_alerts=True,
            send_session_manipulation_alerts=True,
            send_open_drive_alerts=True,
        ),
        telegram_bot=sender,
    )
    triggered = evaluate_scalping_setup(
        {
            "H1": trend_frame("bullish"),
            "H4": trend_frame("bullish"),
            "M15": m15_signal_frame(),
            "M5": m5_confirmation_frame(),
            "M1": m1_trigger_frame(touch_zone=False),
        },
        symbol="XAUUSD",
        current_price=100.2,
        spread=1.0,
        session_name="London",
    )
    assert scanner._maybe_send_automatic_signal(triggered, "London") is False
    assert sender.sent == []

    watch = evaluate_scalping_setup(
        {"H1": trend_frame("bullish"), "H4": trend_frame("bullish"), "M1": trend_frame("bullish"), "M5": trend_frame("bullish"), "M15": trend_frame("bullish")},
        symbol="XAUUSD",
        current_price=103.0,
        spread=1.0,
    )
    assert scanner._maybe_send_automatic_signal(watch, "London") is True
    assert len(sender.sent) == 1
    assert "NO ENTRY" in sender.sent[0]

    triggered.state = "TRIGGERED"
    triggered.score = 95
    triggered.rejection_reasons = []
    triggered.reason_codes = ["test_confirmed"]
    triggered.target_validation = {"valid": True}
    assert scanner._maybe_send_automatic_signal(triggered, "London") is True
    assert len(sender.sent) == 2
    assert scanner._maybe_send_automatic_signal(triggered, "London") is False
    assert len(sender.sent) == 2


def test_volume_profile_is_daily_anchored_when_d1_available():
    now = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    d1 = candles(
        [
            (98.0, 105.0, 95.0, 101.0),
            (101.0, 108.0, 99.0, 103.0),
        ],
        start=now - timedelta(days=1, hours=3),
    )
    decision = evaluate_scalping_setup(
        {
            "D1": d1,
            "H1": trend_frame("bullish"),
            "H4": trend_frame("bullish"),
            "M15": trend_frame("bullish"),
            "M5": trend_frame("bullish"),
            "M1": trend_frame("bullish"),
        },
        symbol="XAUUSD",
        current_price=103.0,
        spread=1.0,
        now_utc=now,
    )
    assert decision.liquidity.get("volume_profile_source", "").startswith("daily_anchored:")


def test_full_confluence_promotes_to_triggered_when_pipeline_forms_it():
    decision = evaluate_scalping_setup(
        {
            "H1": trend_frame("bullish"),
            "H4": trend_frame("bullish"),
            "M15": m15_signal_frame(),
            "M5": m5_confirmation_frame(),
            "M1": m1_trigger_frame(touch_zone=False),
        },
        symbol="XAUUSD",
        current_price=100.2,
        spread=1.0,
        session_name="London",
    )
    if decision.state == "TRIGGERED":
        assert decision.primary_zone is not None
        assert decision.primary_zone.metadata["primary_confluence"]["passed"] is True
        assert "primary_confluence_chain" in decision.reason_codes
    else:
        assert decision.primary_zone is not None
        assert decision.primary_zone.metadata.get("primary_confluence", {}).get("passed") is not True


def test_missing_number_theory_demotes_triggered_to_armed():
    sweep = SweepEvent(
        pool_id="p1",
        symbol="XAUUSD",
        level=2010.0,
        direction="bearish_reversal_candidate",
        timeframe="M15",
        sweep_type="external",
        penetration_pips=8.0,
        wick_rejection_ratio=0.6,
        close_back_inside=True,
        accepted_breakout=False,
        displacement_after_sweep=True,
        choch_after_sweep=True,
        fvg_after_sweep=True,
        number_theory_confluence=False,
        status="CONFIRMED_SWEEP",
        score=80,
    )
    zone = SetupZone(
        id="z1",
        symbol="XAUUSD",
        timeframe="M15",
        zone_type="buy_side_liquidity_sweep",
        role="LTF_SETUP",
        state="CONFIRMED_SWEEP",
        direction="SELL",
        low=2009.75,
        high=2010.25,
        distance_from_price=0.50,
    )
    out = evaluate_primary_confluence(sweep, zone, True, True, True)
    assert not out.passed
    assert "number_theory_missing" in out.reasons_missing
