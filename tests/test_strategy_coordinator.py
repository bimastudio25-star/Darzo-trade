from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from dazro_trade.adelin.volume_profile import build_volume_profile
from dazro_trade.analysis.liquidity_expansion import (
    LiquidityExpansionSignal,
    LiquidityReferenceLevels,
    SweepStatistics,
)
from dazro_trade.core.symbols import pips_to_price
from dazro_trade.runtime.coordinator import combine_strategy_results


def _adelin_result(direction: str, entry: float, valid: bool = True) -> dict | None:
    if not valid:
        return {"signal": None, "rejected": [], "setup_mode": "NO_TRADE"}
    return {
        "signal": {
            "symbol": "XAUUSD",
            "direction": direction,
            "entry": entry,
            "sl": entry - 5 if direction == "LONG" else entry + 5,
            "tp1": {"price": entry + 10 if direction == "LONG" else entry - 10, "rr": 2.0},
            "tp2": {"price": entry + 15 if direction == "LONG" else entry - 15, "rr": 3.0},
            "setup_mode": "LIQ_VP_NT_FVG_SCALP",
        },
        "rejected": [],
        "setup_mode": "LIQ_VP_NT_FVG_SCALP",
    }


def _lex_signal(direction: str, entry: float) -> LiquidityExpansionSignal:
    ref = LiquidityReferenceLevels(
        h1_ref_high=entry + 5,
        h1_ref_low=entry - 5,
        m15_ref_high=entry + 3,
        m15_ref_low=entry - 3,
        h1_source="previous_h1",
        m15_source="minute_45",
    )
    stats = SweepStatistics(mae_avg_pips=5.0, max_excursion_pips=12.0, avg_expansion_pips=25.0, max_expansion_pips=80.0, samples=15)
    sign = 1 if direction == "LONG" else -1
    return LiquidityExpansionSignal(
        symbol="XAUUSD",
        direction=direction,  # type: ignore[arg-type]
        candle_model="IMMEDIATE_EXPANSION",
        reference=ref,
        stats=stats,
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


def test_no_trade_when_both_none():
    decision = combine_strategy_results(None, None)
    assert decision.combined_mode == "NO_TRADE"
    assert decision.should_send is False
    assert decision.suppress_reason == "no_strategy_valid"


def test_strategy_1_only():
    decision = combine_strategy_results(_adelin_result("LONG", 4700.0), None)
    assert decision.combined_mode == "STRATEGY_1_ONLY"
    assert decision.primary_strategy == "strategy_1"
    assert decision.should_send is True
    assert decision.strategy_1_signal is not None
    assert decision.strategy_2_signal is None


def test_strategy_2_only():
    decision = combine_strategy_results(None, _lex_signal("LONG", 4700.0))
    assert decision.combined_mode == "STRATEGY_2_ONLY"
    assert decision.primary_strategy == "strategy_2"
    assert decision.should_send is True
    assert decision.strategy_2_signal is not None


def test_a_plus_plus_same_direction_close_zone():
    adelin = _adelin_result("LONG", 4700.00)
    lex = _lex_signal("LONG", 4700.20)
    decision = combine_strategy_results(adelin, lex, zone_tolerance_pips=30.0)
    assert decision.combined_mode == "A_PLUS_PLUS"
    assert decision.primary_strategy == "both"
    assert decision.should_send is True
    assert decision.distance_pips is not None
    assert decision.distance_pips <= 30.0


def test_a_plus_plus_not_triggered_when_zones_far():
    adelin = _adelin_result("LONG", 4700.0)
    lex = _lex_signal("LONG", 4710.0)
    decision = combine_strategy_results(adelin, lex, zone_tolerance_pips=30.0, conflict_tolerance_pips=50.0)
    assert decision.combined_mode == "INDEPENDENT_BOTH"
    assert decision.should_send is True


def test_conflict_opposite_direction_same_zone():
    adelin = _adelin_result("LONG", 4700.00)
    lex = _lex_signal("SHORT", 4700.40)
    decision = combine_strategy_results(adelin, lex, conflict_tolerance_pips=50.0)
    assert decision.combined_mode == "CONFLICT"
    assert decision.should_send is False
    assert decision.suppress_reason == "opposite_signals_same_zone"
    assert decision.warnings


def test_conflict_independent_when_zones_far():
    adelin = _adelin_result("LONG", 4680.0)
    lex = _lex_signal("SHORT", 4720.0)
    decision = combine_strategy_results(adelin, lex, conflict_tolerance_pips=50.0)
    assert decision.combined_mode == "INDEPENDENT_BOTH"
    assert decision.should_send is True


def test_invalid_adelin_signal_treated_as_none():
    decision = combine_strategy_results({"signal": {"direction": "WAIT", "entry": 0}}, None)
    assert decision.combined_mode == "NO_TRADE"


def test_independent_both_policy_send_first():
    from dazro_trade.core.config import Settings
    from dazro_trade.runtime.scanner import ScalpingScanner

    class _Sender:
        def __init__(self):
            self.sent = []

        def send_text(self, text):
            self.sent.append(text)
            return {"ok": True}

    settings = Settings(telegram_token="x", telegram_chat_id="1", strategy_independent_both_policy="send_first", max_daily_signals=10)
    scanner = ScalpingScanner(settings, telegram_bot=_Sender())
    scanner.first_silent_scan_pending = False
    scanner.last_price = 4700.0
    scanner.last_spread = 1.0
    adelin = _adelin_result("LONG", 4700.0)
    lex = _lex_signal("LONG", 4720.0)
    coord = combine_strategy_results(adelin, lex, zone_tolerance_pips=30.0, conflict_tolerance_pips=50.0)
    assert coord.combined_mode == "INDEPENDENT_BOTH"
    scanner._dispatch_coordinator(coord, adelin, lex, "London", datetime.now(timezone.utc))
    sent = scanner.telegram_bot.sent
    assert any("STRATEGY 1.0" in m for m in sent)
    assert not any("LIQUIDITY EXPANSION MODEL (STRATEGY 2.0)" in m for m in sent)


def test_independent_both_policy_send_best_picks_higher_rr():
    from dazro_trade.core.config import Settings
    from dazro_trade.runtime.scanner import ScalpingScanner

    class _Sender:
        def __init__(self):
            self.sent = []

        def send_text(self, text):
            self.sent.append(text)
            return {"ok": True}

    settings = Settings(telegram_token="x", telegram_chat_id="1", strategy_independent_both_policy="send_best", max_daily_signals=10, min_rr=1.0)
    scanner = ScalpingScanner(settings, telegram_bot=_Sender())
    scanner.first_silent_scan_pending = False
    scanner.last_price = 4720.0
    scanner.last_spread = 1.0
    adelin = _adelin_result("LONG", 4700.0)
    adelin["signal"]["tp1"]["rr"] = 1.5
    lex = _lex_signal("LONG", 4720.0)
    coord = combine_strategy_results(adelin, lex, zone_tolerance_pips=30.0, conflict_tolerance_pips=50.0)
    scanner._dispatch_coordinator(coord, adelin, lex, "London", datetime.now(timezone.utc))
    sent = scanner.telegram_bot.sent
    assert any("LIQUIDITY EXPANSION MODEL (STRATEGY 2.0)" in m for m in sent)
    assert not any("STRATEGY 1.0" in m for m in sent)


def test_a_plus_plus_creates_virtual_trade():
    from dazro_trade.core.config import Settings
    from dazro_trade.runtime.scanner import ScalpingScanner

    class _Sender:
        def __init__(self):
            self.sent = []

        def send_text(self, text):
            self.sent.append(text)
            return {"ok": True}

    settings = Settings(telegram_token="x", telegram_chat_id="1", max_daily_signals=10, min_rr=1.0)
    scanner = ScalpingScanner(settings, telegram_bot=_Sender())
    scanner.first_silent_scan_pending = False
    scanner.last_price = 4700.0
    scanner.last_spread = 1.0
    adelin = _adelin_result("LONG", 4700.0)
    lex = _lex_signal("LONG", 4700.2)
    coord = combine_strategy_results(adelin, lex, zone_tolerance_pips=30.0)
    assert coord.combined_mode == "A_PLUS_PLUS"
    scanner._dispatch_coordinator(coord, adelin, lex, "London", datetime.now(timezone.utc))
    assert len(scanner.trades) == 1
    trade = scanner.trades[0]
    assert trade.strategy == "A_PLUS_PLUS"
    assert trade.source == "coordinator"
    assert trade.tp3 is not None
    assert trade.tp4 is not None
    assert trade.strategy_payload.get("combined_mode") == "A_PLUS_PLUS"
    assert "strategy_1" in trade.strategy_payload
    assert "strategy_2" in trade.strategy_payload


def test_format_analysis_includes_coordinator_section():
    from dazro_trade.core.config import Settings
    from dazro_trade.runtime.scanner import ScalpingScanner

    settings = Settings(telegram_token="x", telegram_chat_id="1")
    scanner = ScalpingScanner(settings)
    scanner.latest_adelin_result = _adelin_result("LONG", 4700.0)
    scanner.latest_liquidity_expansion_signal = _lex_signal("LONG", 4700.2)
    scanner.latest_coordinator_decision = combine_strategy_results(
        scanner.latest_adelin_result, scanner.latest_liquidity_expansion_signal,
    )
    section = scanner._format_coordinator_section()
    assert "COORDINATOR" in section
    assert "Strategy 1.0 (Adelin)" in section
    assert "Strategy 2.0 (Liquidity Expansion)" in section
    assert "Coordinator mode:" in section


def test_volume_profile_distributes_volume_across_bins():
    rows = [
        {"o": 100.0, "h": 100.5, "l": 99.5, "c": 100.0, "vol": 100},
        {"o": 100.0, "h": 100.2, "l": 99.8, "c": 100.0, "vol": 50},
    ]
    df = pd.DataFrame(rows)
    profile = build_volume_profile(df, 101.0, 99.0, n_bins=20)
    assert profile["poc"] is not None
    volumes = [bucket["volume"] for bucket in profile["profile"]]
    non_zero = [v for v in volumes if v > 0]
    assert len(non_zero) >= 4
    typical_only_idx = volumes.index(max(volumes))
    assert volumes[typical_only_idx] < sum(non_zero)
