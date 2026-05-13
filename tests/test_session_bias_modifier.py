from __future__ import annotations

from datetime import datetime, timezone

from dazro_trade.analysis.liquidity_expansion import (
    LiquidityExpansionSignal,
    LiquidityReferenceLevels,
    SweepStatistics,
)
from dazro_trade.core.config import Settings
from dazro_trade.runtime.coordinator import combine_strategy_results
from dazro_trade.runtime.scanner import ScalpingScanner
from dazro_trade.runtime.session_bias import SessionRelationship


class Sender:
    def __init__(self):
        self.sent = []

    def send_text(self, text):
        self.sent.append(text)
        return {"ok": True}


def _lex_signal(direction: str = "LONG", entry: float = 4700.0) -> LiquidityExpansionSignal:
    sign = 1 if direction == "LONG" else -1
    return LiquidityExpansionSignal(
        symbol="XAUUSD",
        direction=direction,  # type: ignore[arg-type]
        candle_model="IMMEDIATE_EXPANSION",
        reference=LiquidityReferenceLevels(
            h1_ref_high=entry + 5,
            h1_ref_low=entry - 5,
            m15_ref_high=entry + 3,
            m15_ref_low=entry - 3,
            h1_source="previous_h1",
            m15_source="minute_45",
        ),
        stats=SweepStatistics(mae_avg_pips=5.0, max_excursion_pips=12.0, avg_expansion_pips=25.0, max_expansion_pips=80.0, samples=15),
        entry=entry,
        stop=entry - sign * 1.5,
        tp1=entry + sign * 2.0,
        tp2=entry + sign * 4.0,
        tp3=entry + sign * 6.0,
        tp4=entry + sign * 8.0,
        tp1_basis="quartile_25",
        rr_tp1=2.5,
        rr_tp4=8.0,
        trigger_kind="reclaim",
        reason_codes=["liquidity_expansion_model_2_0"],
        timestamp_utc=datetime.now(timezone.utc),
    )


def _relationship(label: str = "NY_MANIPULATION_REVERSAL", bias: str = "bearish") -> SessionRelationship:
    return SessionRelationship(
        label=label,  # type: ignore[arg-type]
        active_session="ny",
        previous_session="london",
        directional_bias=bias,  # type: ignore[arg-type]
        confidence=0.8,
        asia_range={"range_pips": 20.0},
        london_range={"range_pips": 60.0},
        ny_range={"range_pips": 45.0},
        swept_level="london_high",
        reason_codes=[f"test_{label.lower()}"],
        notes=[],
    )


def test_scanner_demote_warning_text_in_message():
    sender = Sender()
    settings = Settings(
        telegram_token="x",
        telegram_chat_id="1",
        session_bias_enabled=True,
        session_bias_modifier_enabled=True,
        session_bias_demote_adds_warning=True,
        liquidity_expansion_require_risk_ok=False,
    )
    scanner = ScalpingScanner(settings, telegram_bot=sender)
    scanner.first_silent_scan_pending = False
    scanner.latest_session_bias = _relationship()
    lex = _lex_signal("LONG")
    coord = combine_strategy_results(None, lex, session_relationship=scanner.latest_session_bias)
    scanner.latest_coordinator_decision = coord

    assert scanner._dispatch_coordinator(coord, None, lex, "NY", datetime.now(timezone.utc))

    text = sender.sent[-1]
    assert "WARNING SESSION BIAS" in text
    assert "NY_MANIPULATION_REVERSAL" in text
    assert "demote" in text
    assert text.splitlines()[-1] == "Paper/demo signal only. No real-money execution."


def test_scanner_does_not_apply_bias_when_modifier_disabled():
    sender = Sender()
    settings = Settings(
        telegram_token="x",
        telegram_chat_id="1",
        session_bias_enabled=True,
        session_bias_modifier_enabled=False,
        session_bias_demote_adds_warning=True,
        liquidity_expansion_require_risk_ok=False,
    )
    scanner = ScalpingScanner(settings, telegram_bot=sender)
    scanner.first_silent_scan_pending = False
    scanner.latest_session_bias = _relationship()
    lex = _lex_signal("LONG")
    bias_for_coord = (
        scanner.latest_session_bias
        if (scanner.settings.session_bias_enabled and scanner.settings.session_bias_modifier_enabled)
        else None
    )
    coord = combine_strategy_results(None, lex, session_relationship=bias_for_coord)
    scanner.latest_coordinator_decision = coord

    assert scanner._dispatch_coordinator(coord, None, lex, "NY", datetime.now(timezone.utc))

    assert scanner.latest_coordinator_decision.bias_effect_s2 is None
    assert scanner.latest_coordinator_decision.bias_demoted is False
    assert "WARNING SESSION BIAS" not in sender.sent[-1]
    assert sender.sent[-1].splitlines()[-1] == "Paper/demo signal only. No real-money execution."
