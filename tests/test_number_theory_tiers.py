from __future__ import annotations

from dazro_trade.analysis.number_theory import has_number_theory_confluence


def test_number_theory_strict_tier():
    out = has_number_theory_confluence(2010.04, symbol="XAUUSD")
    assert out["confluence"]
    assert out["tier"] == "strict"


def test_number_theory_loose_tier():
    out = has_number_theory_confluence(2010.10, symbol="XAUUSD")
    assert out["confluence"]
    assert out["tier"] == "loose"


def test_number_theory_none_tier():
    out = has_number_theory_confluence(2010.20, symbol="XAUUSD")
    assert not out["confluence"]
    assert out["tier"] == "none"


def test_number_theory_strict_threshold_is_configurable():
    out = has_number_theory_confluence(2010.04, symbol="XAUUSD", strict_pips=0.2)
    assert out["confluence"]
    assert out["tier"] == "loose"
