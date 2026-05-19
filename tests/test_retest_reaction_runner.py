from __future__ import annotations

from dazro_trade.analysis.human_trade_management import (
    detect_runner_opportunity,
    evaluate_reaction_state,
    evaluate_retest_quality,
)


def test_reaction_alive_when_follow_through_continues():
    result = evaluate_reaction_state(
        [
            {"open": 100, "high": 104, "low": 99, "close": 103},
            {"open": 103, "high": 108, "low": 102, "close": 107},
            {"open": 107, "high": 112, "low": 106, "close": 111},
        ],
        "LONG",
        100,
        stop_loss=95,
    )
    assert result["reaction_state"] == "REACTION_ALIVE"
    assert "favorable_acceptance" in result["reason_codes"]


def test_reaction_weak_when_price_stalls():
    result = evaluate_reaction_state(
        [{"open": 100, "high": 100.8, "low": 99.4, "close": 100.1}],
        "LONG",
        100,
        stop_loss=95,
    )
    assert result["reaction_state"] == "REACTION_WEAK"
    assert "no_follow_through" in result["reason_codes"]


def test_reaction_dead_when_displacement_absorbed():
    result = evaluate_reaction_state(
        [
            {"open": 100, "high": 106, "low": 99, "close": 99.5},
            {"open": 99.5, "high": 100, "low": 97, "close": 98},
            {"open": 98, "high": 99, "low": 96, "close": 97},
        ],
        "LONG",
        100,
        stop_loss=95,
    )
    assert result["reaction_state"] == "REACTION_DEAD"
    assert "displacement_absorbed" in result["reason_codes"]


def test_healthy_retest_after_plus_10_holds_and_confirms():
    result = evaluate_retest_quality(
        [
            {"time": "t1", "open": 100, "high": 111, "low": 100, "close": 110},
            {"time": "t2", "open": 110, "high": 103, "low": 99.8, "close": 102},
            {"time": "t3", "open": 102, "high": 106, "low": 101, "close": 104},
        ],
        "LONG",
        100,
        stop_loss=95,
        be_trigger_usd=10,
    )
    assert result["retest_quality"] == "HEALTHY_RETEST"
    assert "close_holds_level" in result["reason_codes"]
    assert "continuation_confirmed" in result["reason_codes"]


def test_failed_retest_when_close_breaks_level():
    result = evaluate_retest_quality(
        [
            {"time": "t1", "open": 100, "high": 111, "low": 100, "close": 110},
            {"time": "t2", "open": 110, "high": 103, "low": 98, "close": 99},
        ],
        "LONG",
        100,
        stop_loss=95,
        be_trigger_usd=10,
    )
    assert result["retest_quality"] == "FAILED_RETEST"
    assert "close_breaks_level" in result["reason_codes"]


def test_retest_pending_when_level_holds_without_confirmation():
    result = evaluate_retest_quality(
        [
            {"time": "t1", "open": 100, "high": 111, "low": 100, "close": 110},
            {"time": "t2", "open": 110, "high": 103, "low": 99.8, "close": 102},
        ],
        "LONG",
        100,
        stop_loss=95,
        be_trigger_usd=10,
    )
    assert result["retest_quality"] == "RETEST_PENDING"
    assert "awaiting_next_candle_confirmation" in result["reason_codes"]


def test_no_retest_when_price_never_returns_to_level():
    result = evaluate_retest_quality(
        [
            {"time": "t1", "open": 100, "high": 111, "low": 100, "close": 110},
            {"time": "t2", "open": 110, "high": 115, "low": 108, "close": 114},
        ],
        "LONG",
        100,
        stop_loss=95,
        be_trigger_usd=10,
    )
    assert result["retest_quality"] == "NO_RETEST"


def test_runner_standard_default_without_dynamic_target():
    result = detect_runner_opportunity("LONG", 100, 95, original_take_profit=110)
    assert result["runner_opportunity"] == "STANDARD_TP"
    assert "no_dynamic_target_data" in result["target_blockers"]


def test_runner_liquidity_magnet_when_clean_target_exists():
    result = detect_runner_opportunity(
        "LONG",
        100,
        95,
        original_take_profit=110,
        liquidity_levels=[116],
        context={"trend_continuation": True},
    )
    assert result["runner_opportunity"] == "LIQUIDITY_MAGNET_RUN"
    assert result["liquidity_target_price"] == 116
    assert result["dynamic_target_R"] == 3.2


def test_runner_blocks_when_target_space_insufficient():
    result = detect_runner_opportunity("LONG", 100, 95, original_take_profit=110, liquidity_levels=[103])
    assert result["runner_opportunity"] == "STANDARD_TP"
    assert "target_space_insufficient" in result["target_blockers"]
