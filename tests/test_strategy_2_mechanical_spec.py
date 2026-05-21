from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd

from dazro_trade.analysis.strategy_2_mechanical_spec import (
    MechanicalSpecConfig,
    conservative_sl_distance,
    dominant_h1_reference,
    evaluate_context_model,
    evaluate_m15_sequence,
    evaluate_mechanical_entry,
    pips_to_price,
    select_relevant_m15,
    tp_quartiles_from_h1,
)


def _m15() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": "2026-05-19T00:45:00+00:00", "open": 1, "high": 999, "low": 1, "close": 2},
            {"time": "2026-05-19T14:00:00+00:00", "open": 100, "high": 110, "low": 97, "close": 101},
            {"time": "2026-05-19T14:15:00+00:00", "open": 101, "high": 103, "low": 95, "close": 99},
            {"time": "2026-05-19T14:30:00+00:00", "open": 99, "high": 104, "low": 94, "close": 100},
            {"time": "2026-05-19T14:45:00+00:00", "open": 100, "high": 105, "low": 93, "close": 101},
        ]
    )


def _h1_context() -> pd.Series:
    return pd.Series({"time": pd.Timestamp("2026-05-19T14:00:00+00:00"), "open": 105, "high": 112, "low": 98, "close": 104})


def _reference() -> dict[str, object]:
    return {
        "h1_reference_type": "previous_h1",
        "h1_reference_timestamp": "2026-05-19T13:00:00+00:00",
        "h1_reference_high": 120.0,
        "h1_reference_low": 100.0,
        "h1_reference_range": 20.0,
        "dominant_contains_internal_count": 0,
        "dominant_high_taken": False,
        "dominant_low_taken": False,
    }


def test_relevant_m15_is_not_fixed_hh45_or_daily_0045():
    selected = select_relevant_m15(
        _m15(),
        h1_context_open="2026-05-19T14:00:00+00:00",
        take_timestamp="2026-05-19T14:12:00+00:00",
        model="containing",
    )
    assert selected.iloc[0]["time"] == pd.Timestamp("2026-05-19T14:00:00+00:00")
    assert selected.iloc[0]["time"] != pd.Timestamp("2026-05-19T14:45:00+00:00")
    assert selected.iloc[0]["time"] != pd.Timestamp("2026-05-19T00:45:00+00:00")


def test_containing_model_selects_m15_containing_take_timestamp():
    selected = select_relevant_m15(_m15(), h1_context_open="2026-05-19T14:00:00+00:00", take_timestamp="2026-05-19T14:16:00+00:00", model="containing")
    assert selected.iloc[0]["time"] == pd.Timestamp("2026-05-19T14:15:00+00:00")


def test_preceding_model_selects_last_fully_closed_m15_before_take():
    selected = select_relevant_m15(_m15(), h1_context_open="2026-05-19T14:00:00+00:00", take_timestamp="2026-05-19T14:16:00+00:00", model="preceding")
    assert selected.iloc[0]["time"] == pd.Timestamp("2026-05-19T14:00:00+00:00")


def test_approach_window_selects_all_m15_from_context_open_to_take():
    selected = select_relevant_m15(_m15(), h1_context_open="2026-05-19T14:00:00+00:00", take_timestamp="2026-05-19T14:31:00+00:00", model="approach_window")
    assert selected["time"].tolist() == [
        pd.Timestamp("2026-05-19T14:00:00+00:00"),
        pd.Timestamp("2026-05-19T14:15:00+00:00"),
        pd.Timestamp("2026-05-19T14:30:00+00:00"),
    ]


def test_long_invalidates_when_current_m15_high_taken_before_h1_low_take():
    m1 = pd.DataFrame(
        [
            {"time": "2026-05-19T14:05:00+00:00", "open": 105, "high": 110, "low": 104, "close": 106},
            {"time": "2026-05-19T14:10:00+00:00", "open": 106, "high": 107, "low": 99.8, "close": 100},
        ]
    )
    result = evaluate_m15_sequence(
        m1,
        _m15(),
        direction="LONG",
        h1_context_open="2026-05-19T14:00:00+00:00",
        take_timestamp="2026-05-19T14:10:00+00:00",
        model="containing",
    )
    assert result["m15_sequence_valid"] is False
    assert result["m15_invalid_reason"] == "INVALID_CURRENT_M15_HIGH_TAKEN_FIRST_FOR_LONG"


def test_short_invalidates_when_current_m15_low_taken_before_h1_high_take():
    m1 = pd.DataFrame(
        [
            {"time": "2026-05-19T14:05:00+00:00", "open": 105, "high": 106, "low": 97, "close": 99},
            {"time": "2026-05-19T14:10:00+00:00", "open": 99, "high": 120.2, "low": 98, "close": 119},
        ]
    )
    result = evaluate_m15_sequence(
        m1,
        _m15(),
        direction="SHORT",
        h1_context_open="2026-05-19T14:00:00+00:00",
        take_timestamp="2026-05-19T14:10:00+00:00",
        model="containing",
    )
    assert result["m15_sequence_valid"] is False
    assert result["m15_invalid_reason"] == "INVALID_CURRENT_M15_LOW_TAKEN_FIRST_FOR_SHORT"


def test_entry_requires_average_mae_reached_within_same_h1_candle_as_take():
    m1 = pd.DataFrame(
        [
            {"time": "2026-05-19T14:58:00+00:00", "open": 100, "high": 101, "low": 99.8, "close": 100},
            {"time": "2026-05-19T15:00:00+00:00", "open": 100, "high": 101, "low": 95.0, "close": 96},
        ]
    )
    result = evaluate_mechanical_entry(
        m1,
        direction="LONG",
        h1_level=100.0,
        take_timestamp="2026-05-19T14:58:00+00:00",
        h1_context_end="2026-05-19T15:00:00+00:00",
        mae_avg_usd=4.0,
        reentry_threshold_price=0.1,
    )
    assert result["entry_status"] == "NO_ENTRY_MAE_NOT_REACHED"


def test_long_entry_requires_reentry_above_h1_low_by_one_pip_no_close_required():
    m1 = pd.DataFrame(
        [
            {"time": "2026-05-19T14:10:00+00:00", "open": 100, "high": 100.0, "low": 95.8, "close": 96},
            {"time": "2026-05-19T14:11:00+00:00", "open": 96, "high": 100.1, "low": 95.9, "close": 99.5},
        ]
    )
    result = evaluate_mechanical_entry(
        m1,
        direction="LONG",
        h1_level=100.0,
        take_timestamp="2026-05-19T14:10:00+00:00",
        h1_context_end="2026-05-19T15:00:00+00:00",
        mae_avg_usd=4.0,
        reentry_threshold_price=0.1,
    )
    assert result["entry_valid"] is True
    assert result["entry_timestamp"] == "2026-05-19T14:11:00+00:00"


def test_short_entry_requires_reentry_below_h1_high_by_one_pip_no_close_required():
    m1 = pd.DataFrame(
        [
            {"time": "2026-05-19T14:10:00+00:00", "open": 120, "high": 124.2, "low": 120.0, "close": 123},
            {"time": "2026-05-19T14:11:00+00:00", "open": 123, "high": 123.5, "low": 119.9, "close": 120.5},
        ]
    )
    result = evaluate_mechanical_entry(
        m1,
        direction="SHORT",
        h1_level=120.0,
        take_timestamp="2026-05-19T14:10:00+00:00",
        h1_context_end="2026-05-19T15:00:00+00:00",
        mae_avg_usd=4.0,
        reentry_threshold_price=0.1,
    )
    assert result["entry_valid"] is True
    assert result["entry_timestamp"] == "2026-05-19T14:11:00+00:00"


def test_mae_reached_without_reentry_produces_no_entry_no_range_reentry():
    m1 = pd.DataFrame([{"time": "2026-05-19T14:10:00+00:00", "open": 100, "high": 99.9, "low": 95.8, "close": 96}])
    result = evaluate_mechanical_entry(
        m1,
        direction="LONG",
        h1_level=100.0,
        take_timestamp="2026-05-19T14:10:00+00:00",
        h1_context_end="2026-05-19T15:00:00+00:00",
        mae_avg_usd=4.0,
        reentry_threshold_price=0.1,
    )
    assert result["mae_reached"] is True
    assert result["entry_status"] == "NO_ENTRY_NO_RANGE_REENTRY"


def test_level_taken_by_one_pip_is_enough_and_reaction_not_gate():
    m1 = pd.DataFrame(
        [
            {"time": "2026-05-19T14:10:00+00:00", "open": 101, "high": 101, "low": 95.0, "close": 96},
            {"time": "2026-05-19T14:11:00+00:00", "open": 96, "high": 101, "low": 96, "close": 99},
        ]
    )
    result = evaluate_context_model(
        symbol="XAUUSD",
        h1_context=_h1_context(),
        reference=_reference(),
        m1_window=m1,
        m15=_m15(),
        model="containing",
        config=MechanicalSpecConfig(mae_avg_usd=4.0, min_distribution_usd=1.0),
    )
    assert result["h1_level_take_timestamp"] == "2026-05-19T14:10:00+00:00"
    assert result["reaction_confirmation_used_as_gate"] is False


def test_conservative_sl_and_tp_h1_anchor():
    assert pips_to_price(1, 10) == 0.1
    assert conservative_sl_distance(98.8) == 123.5
    tp = tp_quartiles_from_h1(40.0)
    assert tp["tp_anchor"] == "H1_LEVEL"
    assert tp["tp1"] == 10.0


def test_dominant_h1_internal_ranges_use_full_containment():
    h1 = pd.DataFrame(
        [
            {"time": "2026-05-19T10:00:00+00:00", "open": 100, "high": 120, "low": 90, "close": 110},
            {"time": "2026-05-19T11:00:00+00:00", "open": 110, "high": 119, "low": 91, "close": 111},
            {"time": "2026-05-19T12:00:00+00:00", "open": 111, "high": 118, "low": 92, "close": 112},
            {"time": "2026-05-19T13:00:00+00:00", "open": 112, "high": 121, "low": 93, "close": 113},
        ]
    )
    ref = dominant_h1_reference(h1, 3, contained_count=2)
    assert ref is not None
    assert ref["h1_reference_timestamp"] == "2026-05-19T10:00:00+00:00"
    assert ref["dominant_contains_internal_count"] == 2

    partial_overlap = h1.copy()
    partial_overlap.loc[1, "high"] = 120
    assert dominant_h1_reference(partial_overlap, 3, contained_count=2) is None


def test_new_mechanical_code_does_not_import_forbidden_modules_or_write_market_data():
    paths = [
        Path("dazro_trade/analysis/strategy_2_mechanical_spec.py"),
        Path("dazro_trade/analytics/strategy_2_mechanical_spec_audit.py"),
        Path("scripts/analyze_strategy_2_mechanical_spec_correction.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden = "strategy" + "_3"
    assert forbidden not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "open(\"data/xauusd" not in combined
    assert "order_send(" not in combined


def test_importing_script_does_not_execute_analysis_automatically():
    module = importlib.import_module("scripts.analyze_strategy_2_mechanical_spec_correction")
    assert hasattr(module, "main")
    assert hasattr(module, "run")

