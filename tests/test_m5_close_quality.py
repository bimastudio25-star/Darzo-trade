from __future__ import annotations

from dazro_trade.analysis.human_trade_management import evaluate_m5_close_quality


def test_good_close_for_strong_directional_long_close():
    result = evaluate_m5_close_quality(
        {"open": 100, "high": 112, "low": 99, "close": 111},
        "LONG",
        entry_price=100,
    )
    assert result["quality"] == "GOOD_CLOSE"
    assert "directional_bullish_close" in result["reason_codes"]


def test_bad_close_for_weak_adverse_long_close():
    result = evaluate_m5_close_quality(
        {"open": 100, "high": 112, "low": 99, "close": 100},
        "LONG",
        entry_price=100,
    )
    assert result["quality"] == "BAD_CLOSE"
    assert "large_upper_wick_rejection" in result["reason_codes"]
    assert result["reason_codes"]


def test_invalidating_close_for_long_close_through_invalidation_level():
    result = evaluate_m5_close_quality(
        {"open": 100, "high": 102, "low": 94, "close": 94.5},
        "LONG",
        entry_price=100,
        invalidation_level=95,
    )
    assert result["quality"] == "INVALIDATING_CLOSE"
    assert "close_below_invalidation_level" in result["reason_codes"]


def test_good_close_for_strong_directional_short_close():
    result = evaluate_m5_close_quality(
        {"open": 100, "high": 101, "low": 88, "close": 89},
        "SHORT",
        entry_price=100,
    )
    assert result["quality"] == "GOOD_CLOSE"
    assert "directional_bearish_close" in result["reason_codes"]


def test_invalidating_close_for_short_close_through_invalidation_level():
    result = evaluate_m5_close_quality(
        {"open": 100, "high": 106, "low": 98, "close": 105.5},
        "SHORT",
        entry_price=100,
        invalidation_level=105,
    )
    assert result["quality"] == "INVALIDATING_CLOSE"
    assert "close_above_invalidation_level" in result["reason_codes"]
