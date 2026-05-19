from __future__ import annotations

import pandas as pd

from dazro_trade.analysis.human_trade_management import (
    HumanManagementConfig,
    TradeInput,
    build_trade_management_record,
    collect_path_event_state,
    evaluate_entry_quality,
    simulate_trade_path_variant,
)


def _trade(direction: str = "LONG", entry: float = 100.0, stop: float | None = None, tp: float | None = None) -> TradeInput:
    stop = stop if stop is not None else (90.0 if direction == "LONG" else 110.0)
    tp = tp if tp is not None else (130.0 if direction == "LONG" else 70.0)
    return TradeInput(
        trade_id=f"{direction.lower()}-1",
        symbol="XAUUSD",
        strategy="strategy_2_liquidity_expansion",
        direction=direction,  # type: ignore[arg-type]
        signal_timestamp="2026-05-19T14:00:00+00:00",
        entry_timestamp="2026-05-19T14:00:00+00:00",
        entry_price=entry,
        stop_loss=stop,
        original_take_profit=tp,
    )


def test_long_be_trigger_at_plus_10():
    state = collect_path_event_state(
        _trade("LONG"),
        [{"time": "t1", "open": 100, "high": 110, "low": 99, "close": 109}],
    )
    assert state.hit_be_10 is True
    assert state.be_timestamp == "t1"


def test_short_be_trigger_at_plus_10():
    state = collect_path_event_state(
        _trade("SHORT"),
        [{"time": "t1", "open": 100, "high": 101, "low": 90, "close": 91}],
    )
    assert state.hit_be_10 is True
    assert state.be_timestamp == "t1"


def test_long_and_short_partial_triggers_at_15_and_20():
    long_state = collect_path_event_state(
        _trade("LONG"),
        [{"time": "t1", "open": 100, "high": 121, "low": 100, "close": 120}],
    )
    short_state = collect_path_event_state(
        _trade("SHORT"),
        [{"time": "t2", "open": 100, "high": 100, "low": 79, "close": 80}],
    )
    assert long_state.hit_partial_15 is True
    assert long_state.hit_partial_20 is True
    assert short_state.hit_partial_15 is True
    assert short_state.hit_partial_20 is True


def test_no_be_if_price_never_moves_plus_10():
    state = collect_path_event_state(
        _trade("LONG"),
        [{"time": "t1", "open": 100, "high": 109.99, "low": 99, "close": 108}],
    )
    assert state.hit_be_10 is False


def test_be_before_later_sl_sequences_to_be_result():
    result = simulate_trade_path_variant(
        _trade("LONG"),
        [
            {"time": "t1", "open": 100, "high": 111, "low": 100.5, "close": 110},
            {"time": "t2", "open": 110, "high": 111, "low": 100, "close": 101},
        ],
        variant="hard_be",
    )
    assert result.outcome == "BE"
    assert result.r_multiple == 0.0
    assert "MOVE_BE_hard_be" in result.reason_codes


def test_sl_before_be_sequences_to_full_sl():
    result = simulate_trade_path_variant(
        _trade("LONG"),
        [{"time": "t1", "open": 100, "high": 104, "low": 90, "close": 91}],
        variant="hard_be",
    )
    assert result.outcome == "SL"
    assert result.r_multiple == -1.0


def test_partial_before_later_be_stop_keeps_realized_partial_r():
    result = simulate_trade_path_variant(
        _trade("LONG", stop=90, tp=130),
        [
            {"time": "t1", "open": 100, "high": 116, "low": 101, "close": 115},
            {"time": "t2", "open": 115, "high": 116, "low": 100, "close": 101},
        ],
        variant="partial15",
    )
    assert result.outcome == "BE"
    assert result.r_multiple == 0.75
    assert "TAKE_PARTIAL" in result.reason_codes


def test_tp_before_partial_when_fixed_tp_is_closer_than_partial_zone():
    result = simulate_trade_path_variant(
        _trade("LONG", stop=90, tp=112),
        [{"time": "t1", "open": 100, "high": 112.5, "low": 99, "close": 112}],
        variant="partial15",
    )
    assert result.outcome == "TP"
    assert result.r_multiple == 1.2
    assert result.partial_fraction == 0.0


def test_m5_confirmed_be_falls_back_safely_when_m5_missing():
    cfg = HumanManagementConfig(be_mode="m5_confirmed_be")
    result = simulate_trade_path_variant(
        _trade("LONG", stop=90, tp=130),
        [
            {"time": "t1", "open": 100, "high": 111, "low": 101, "close": 110},
            {"time": "t2", "open": 110, "high": 111, "low": 100, "close": 100},
        ],
        config=cfg,
        variant="hard_be",
    )
    assert result.outcome == "BE"
    assert "MOVE_BE_m5_missing_or_unconfirmed_fallback_to_hard_be" in result.reason_codes


def test_structural_be_falls_back_when_no_structure_available():
    cfg = HumanManagementConfig(be_mode="structural_be")
    result = simulate_trade_path_variant(
        _trade("LONG", stop=90, tp=130),
        [
            {"time": "t1", "open": 100, "high": 111, "low": 101, "close": 110},
            {"time": "t2", "open": 110, "high": 111, "low": 100, "close": 100},
        ],
        config=cfg,
        variant="hard_be",
    )
    assert result.outcome == "BE"
    assert "MOVE_BE_structural_fallback_to_hard_be" in result.reason_codes


def test_entry_quality_marks_price_escaped_after_be_threshold():
    result = evaluate_entry_quality("LONG", 2400.0, 2412.0, stop_loss=2395.0, target_price=2425.0)
    assert result["entry_quality"] == "NO_TRADE_PRICE_ESCAPED"
    assert "price_already_beyond_be_trigger" in result["reason_codes"]


def test_trade_record_accepts_pandas_dataframes_for_real_overlay_paths():
    trade = _trade("LONG", entry=100, stop=95, tp=112)
    m1 = pd.DataFrame(
        [
            {"time": "2026-05-19T14:01:00+00:00", "open": 100, "high": 111, "low": 99, "close": 110},
            {"time": "2026-05-19T14:02:00+00:00", "open": 110, "high": 112, "low": 101, "close": 112},
        ]
    )
    m5 = pd.DataFrame(
        [
            {"time": "2026-05-19T14:05:00+00:00", "open": 100, "high": 112, "low": 99, "close": 111},
        ]
    )
    row = build_trade_management_record(trade, m1_candles=m1, m5_candles=m5)
    assert row["trade_id"] == "long-1"
    assert row["result_baseline_R"] > 0
