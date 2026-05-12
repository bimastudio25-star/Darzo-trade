from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from dazro_trade.analysis.scalping import (
    SignalDeduplicator,
    build_zones,
    choose_primary_zone,
    detect_zone_interactions_since_last_scan,
    evaluate_scalping_setup,
)
from dazro_trade.core.models import SetupZone
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
    assert decision.state in {"WATCH", "ARMED", "ENTERED"}
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
    assert decision.state == "ENTERED"
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
    assert message.splitlines()[0] == "XAUUSD - DECISIONE OPERATIVA"
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
    scanner = ScalpingScanner(Settings(telegram_token="x", telegram_chat_id="1"), telegram_bot=sender)
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
    assert scanner._maybe_send_automatic_signal(watch, "London") is False
    assert sender.sent == []

    triggered.state = "TRIGGERED"
    triggered.score = 95
    triggered.rejection_reasons = []
    triggered.reason_codes = ["test_confirmed"]
    assert scanner._maybe_send_automatic_signal(triggered, "London") is True
    assert len(sender.sent) == 1
    assert scanner._maybe_send_automatic_signal(triggered, "London") is False
    assert len(sender.sent) == 1
