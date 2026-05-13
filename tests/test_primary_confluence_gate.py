from __future__ import annotations

from dazro_trade.analysis.scalping import evaluate_primary_confluence
from dazro_trade.core.models import SetupZone
from dazro_trade.liquidity.sweep import SweepEvent


def sweep(**overrides) -> SweepEvent:
    values = {
        "pool_id": "p1",
        "symbol": "XAUUSD",
        "level": 2010.0,
        "direction": "bearish_reversal_candidate",
        "timeframe": "M15",
        "sweep_type": "external",
        "penetration_pips": 8.0,
        "wick_rejection_ratio": 0.6,
        "close_back_inside": True,
        "accepted_breakout": False,
        "displacement_after_sweep": True,
        "choch_after_sweep": True,
        "fvg_after_sweep": True,
        "ifvg_after_sweep": False,
        "number_theory_confluence": True,
        "vwap_deviation_confluence": True,
        "volume_crack_confluence": False,
        "status": "CONFIRMED_SWEEP",
        "score": 80,
        "reason_codes": [],
    }
    values.update(overrides)
    return SweepEvent(**values)


def zone(distance: float = 0.50) -> SetupZone:
    return SetupZone(
        id="z1",
        symbol="XAUUSD",
        timeframe="M15",
        zone_type="buy_side_liquidity_sweep",
        role="LTF_SETUP",
        state="CONFIRMED_SWEEP",
        direction="SELL",
        low=2009.75,
        high=2010.25,
        distance_from_price=distance,
    )


def test_primary_confluence_full_chain_passes():
    out = evaluate_primary_confluence(sweep(), zone(), True, True, True)
    assert out.passed
    assert out.score_bonus == 15
    assert out.reasons_missing == []


def test_primary_confluence_missing_number_theory_fails():
    out = evaluate_primary_confluence(sweep(number_theory_confluence=False), zone(), True, True, True)
    assert not out.passed
    assert "number_theory_missing" in out.reasons_missing


def test_primary_confluence_missing_sweep_fails():
    out = evaluate_primary_confluence(None, zone(), True, True, True)
    assert not out.passed
    assert "sweep_not_in_confirmed_or_triggered" in out.reasons_missing


def test_primary_confluence_zone_too_far_fails():
    out = evaluate_primary_confluence(sweep(), zone(distance=1.20), True, True, True)
    assert not out.passed
    assert "primary_zone_too_far" in out.reasons_missing


def test_primary_confluence_accepts_ifvg_without_fvg():
    out = evaluate_primary_confluence(sweep(fvg_after_sweep=False, ifvg_after_sweep=True), zone(), True, True, True)
    assert out.passed
