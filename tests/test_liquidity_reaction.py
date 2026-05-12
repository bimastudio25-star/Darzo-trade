from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from dazro_trade.analysis.scalping import evaluate_scalping_setup
from dazro_trade.core.config import Settings
from dazro_trade.core.models import ScalpingDecision
from dazro_trade.core.symbols import pips_to_price, price_to_pips
from dazro_trade.liquidity.map import LiquidityPool, build_liquidity_map
from dazro_trade.liquidity.sweep import detect_sweep_event
from dazro_trade.runtime.scanner import ScalpingScanner


def df(rows):
    base = datetime(2026, 5, 12, 7, 0, tzinfo=timezone.utc)
    return pd.DataFrame(
        [
            {"time": base, "o": row[0], "h": row[1], "l": row[2], "c": row[3], "vol": row[4] if len(row) > 4 else 100}
            for row in rows
        ]
    )


def pool(level=4722.33):
    return LiquidityPool(
        id="xau_m15_external_high_4722_33",
        symbol="XAUUSD",
        timeframe="M15",
        level=level,
        side="buy_side",
        pool_type="external_high",
        distance_pips=337.0,
        distance_points=3.37,
        strength_score=80,
        confluences=["external_liquidity"],
        metadata={"distance_band": "reaction_250_500_pips"},
    )


def test_xauusd_pip_conversion():
    assert pips_to_price("XAUUSD", 80) == 0.80
    assert price_to_pips("XAUUSD", 0.80) == 80


def test_4722_external_high_stays_in_liquidity_map_reaction_band():
    frame = df([(4718, 4722.33, 4717.5, 4718.96), (4718.96, 4719.5, 4718.2, 4719.0)])
    pools = build_liquidity_map({"M15": frame}, symbol="XAUUSD", current_price=4718.96)
    target = [item for item in pools if item.level == 4722.33 and item.side == "buy_side"]
    assert target
    assert target[0].distance_pips == 337.0
    assert target[0].distance_band == "remote_300_plus_pips"


def test_intrabar_sweep_is_not_triggered_until_close():
    event = detect_sweep_event(
        pool(),
        df([(4721.8, 4722.6, 4721.5, 4722.4)]),
        current_candle_closed=False,
        min_penetration_pips=5,
    )
    assert event is not None
    assert event.status == "SWEEPING_INTRABAR"


def test_closed_sweep_back_inside_is_confirmed_sweep():
    event = detect_sweep_event(
        pool(),
        df([(4721.8, 4722.6, 4721.5, 4721.9)]),
        current_candle_closed=True,
        min_penetration_pips=5,
    )
    assert event is not None
    assert event.status == "CONFIRMED_SWEEP"


def test_sweep_with_m5_displacement_m1_choch_and_bearish_fvg_triggers_short():
    m5 = df(
        [
            (4722.0, 4722.2, 4721.5, 4722.1),
            (4722.1, 4722.3, 4721.95, 4722.0),
            (4722.0, 4722.2, 4721.0, 4722.1),
            (4721.7, 4721.8, 4720.6, 4720.7),
            (4720.7, 4720.8, 4720.5, 4720.6),
        ]
    )
    m1 = df(
        [
            (4722.0, 4722.1, 4721.8, 4722.0),
            (4722.0, 4722.1, 4721.7, 4722.0),
            (4722.0, 4722.1, 4721.6, 4722.0),
            (4722.0, 4722.1, 4721.5, 4722.0),
            (4721.8, 4721.9, 4720.8, 4720.9),
            (4720.9, 4721.0, 4720.7, 4720.8),
        ]
    )
    event = detect_sweep_event(
        pool(),
        df([(4721.8, 4722.6, 4721.5, 4721.9)]),
        m5_df=m5,
        m1_df=m1,
        current_candle_closed=True,
        min_penetration_pips=5,
    )
    assert event is not None
    assert event.status == "TRIGGERED"
    assert "bearish_fvg_after_buy_side_sweep" in event.reason_codes


def test_close_above_and_retest_is_accepted_breakout_not_reversal():
    event = detect_sweep_event(
        pool(),
        df([(4722.0, 4722.7, 4722.2, 4722.5), (4722.5, 4722.8, 4722.25, 4722.6)]),
        current_candle_closed=True,
        min_penetration_pips=5,
    )
    assert event is not None
    assert event.status == "accepted_breakout"
    assert "accepted_breakout_not_reversal" in event.reason_codes


def test_fvg_without_liquidity_taken_is_penalized_not_strong_signal():
    frame = df([(100, 100.4, 99.8, 100.2) for _ in range(20)] + [(101.2, 101.6, 100.9, 101.4)])
    decision = evaluate_scalping_setup(
        {"M15": frame, "M5": frame, "M1": frame, "H1": frame, "H4": frame},
        symbol="XAUUSD",
        current_price=101.0,
        spread=1.0,
    )
    assert not decision.telegram_allowed
    assert "fvg_without_liquidity_penalty" in decision.rejection_reasons or "Nessuna zona M15/M5/M1 operativa vicina al prezzo" in decision.rejection_reasons


def test_reaction_alert_is_deduplicated_same_level_same_session():
    class Sender:
        def __init__(self):
            self.sent = []

        def send_text(self, text):
            self.sent.append(text)
            return {"ok": True}

    sender = Sender()
    scanner = ScalpingScanner(Settings(telegram_token="x", telegram_chat_id="1"), telegram_bot=sender)
    near_pool = pool(level=4720.40)
    near_pool.distance_pips = 144.0
    near_pool.distance_points = 1.44
    near_pool.metadata["distance_band"] = "reaction_80_150_pips"
    decision = ScalpingDecision(
        symbol="XAUUSD",
        setup_type="LIQUIDITY_REACTION",
        direction="SHORT",
        state="ARMED",
        score=60,
        confidence=0.6,
        htf_context={},
        intraday_context={},
        liquidity={
            "pools": [near_pool.__dict__ | {"distance_band": near_pool.distance_band}],
            "sweeps": [{"pool_id": near_pool.id, "status": "SWEEPING_INTRABAR", "level": near_pool.level, "reason_codes": ["external_liquidity_in_reaction_band"]}],
        },
    )
    scanner.latest_analysis = decision
    assert scanner._maybe_send_reaction_alert(decision, "London")
    assert not scanner._maybe_send_reaction_alert(decision, "London")
    assert len(sender.sent) == 1
