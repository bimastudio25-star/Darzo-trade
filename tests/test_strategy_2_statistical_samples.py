from __future__ import annotations

from pathlib import Path

import pandas as pd

from dazro_trade.analysis.strategy_2_statistical_samples import (
    StatisticalRecorderConfig,
    build_statistical_profile,
    conservative_stop_distance,
    evaluate_h1_sample,
    price_to_pips,
    select_m15_x45,
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
        "h1_reference_range_bucket": "RANGE_20_40",
    }


def _m15() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": "2026-05-19T00:45:00+00:00", "open": 1, "high": 999, "low": 1, "close": 2},
            {"time": "2026-05-19T14:30:00+00:00", "open": 1, "high": 888, "low": 1, "close": 2},
            {"time": "2026-05-19T14:45:00+00:00", "open": 101, "high": 130, "low": 90, "close": 102},
        ]
    )


def _m1_valid_long() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": "2026-05-19T14:00:00+00:00", "open": 104, "high": 110, "low": 101, "close": 103},
            {"time": "2026-05-19T14:01:00+00:00", "open": 103, "high": 104, "low": 99, "close": 100},
            {"time": "2026-05-19T14:02:00+00:00", "open": 100, "high": 102, "low": 99.5, "close": 101},
        ]
    )


def _m5() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": "2026-05-19T14:00:00+00:00", "open": 104, "high": 104, "low": 99, "close": 101},
            {"time": "2026-05-19T14:05:00+00:00", "open": 101, "high": 104, "low": 100, "close": 103},
        ]
    )


def test_m15_x45_selector_uses_hourly_minute_45_not_daily_0045():
    selected = select_m15_x45(_m15(), "2026-05-19T14:00:00+00:00")
    assert selected["m15_x45_timestamp"] == "2026-05-19T14:45:00+00:00"
    assert selected["m15_x45_high"] == 130


def test_long_invalidates_when_m15_x45_high_taken_before_h1_low():
    m1 = pd.DataFrame(
        [
            {"time": "2026-05-19T14:00:00+00:00", "open": 104, "high": 131, "low": 101, "close": 110},
            {"time": "2026-05-19T14:01:00+00:00", "open": 110, "high": 111, "low": 99, "close": 100},
        ]
    )
    row = evaluate_h1_sample(
        symbol="XAUUSD",
        h1_context=_h1_context(),
        reference=_reference(),
        direction="LONG",
        m1_window=m1,
        m5_window=_m5(),
        m15=_m15(),
        config=StatisticalRecorderConfig(),
    )
    assert row["sample_status"] == "INVALID_OPPOSITE_M15_X45_TAKEN_FIRST"


def test_short_invalidates_when_m15_x45_low_taken_before_h1_high():
    m1 = pd.DataFrame(
        [
            {"time": "2026-05-19T14:00:00+00:00", "open": 104, "high": 110, "low": 89, "close": 95},
            {"time": "2026-05-19T14:01:00+00:00", "open": 95, "high": 121, "low": 94, "close": 119},
        ]
    )
    row = evaluate_h1_sample(
        symbol="XAUUSD",
        h1_context=_h1_context(),
        reference=_reference(),
        direction="SHORT",
        m1_window=m1,
        m5_window=_m5(),
        m15=_m15(),
        config=StatisticalRecorderConfig(),
    )
    assert row["sample_status"] == "INVALID_OPPOSITE_M15_X45_TAKEN_FIRST"


def test_valid_long_sample_measures_manipulation_and_expansion_separately():
    row = evaluate_h1_sample(
        symbol="XAUUSD",
        h1_context=_h1_context(),
        reference=_reference(),
        direction="LONG",
        m1_window=_m1_valid_long(),
        m5_window=_m5(),
        m15=_m15(),
        config=StatisticalRecorderConfig(),
    )
    assert row["sample_status"] == "VALID_SAMPLE_UNCLASSIFIED"
    assert row["manipulation_depth_price"] == 1.0
    assert row["distribution_distance_price"] == 4.0
    assert row["manipulation_depth_pips"] == 10.0


def test_valid_no_entry_samples_are_included_in_mae_and_sl_profile():
    rows = [
        {"sample_status": "VALID_SAMPLE_NO_ENTRY_MANIPULATED_LESS", "manipulation_depth_price": 1.0, "distribution_distance_price": 8.0},
        {"sample_status": "VALID_SAMPLE_TRADE_TRIGGERED", "manipulation_depth_price": 3.0, "distribution_distance_price": 16.0},
    ]
    profile = build_statistical_profile(rows, config=StatisticalRecorderConfig())
    assert profile["mae_profile"]["average_price"] == 2.0
    assert profile["max_excursion_profile"]["risky_stop_distance_price"] == 3.0
    assert profile["max_excursion_profile"]["conservative_stop_distance_price"] == 3.75
    assert profile["max_excursion_profile"]["global_xauusd_max_excursion_used"] is False


def test_tp_distances_are_h1_anchored_and_short_prices_subtract_from_h1_high():
    rows = [{"sample_status": "VALID_SAMPLE_TRADE_TRIGGERED", "manipulation_depth_price": 2.0, "distribution_distance_price": 40.0}]
    profile = build_statistical_profile(rows, config=StatisticalRecorderConfig())
    tp = profile["tp_profile"]
    assert tp["tp_anchor_is_entry"] is False
    assert tp["tp1_distance_price"] == 10.0
    h1_high = 120.0
    h1_low = 100.0
    assert h1_low + tp["tp1_distance_price"] == 110.0
    assert h1_high - tp["tp1_distance_price"] == 110.0


def test_unit_conversion_and_conservative_stop_formula():
    assert price_to_pips(4.59, 10) == 45.9
    assert conservative_stop_distance(98.8) == 123.5


def test_profiles_above_realistic_range_are_flagged_not_clamped():
    rows = [{"sample_status": "VALID_SAMPLE_TRADE_TRIGGERED", "manipulation_depth_price": 20.0, "distribution_distance_price": 40.0}]
    profile = build_statistical_profile(rows, config=StatisticalRecorderConfig(risk_guardrail_usd=12.0))
    assert profile["max_excursion_profile"]["profile_risk_too_large"] is True
    assert profile["max_excursion_profile"]["conservative_stop_distance_price"] == 25.0


def test_new_code_does_not_import_strategy_3_or_write_market_data():
    paths = [
        Path("dazro_trade/analysis/strategy_2_statistical_samples.py"),
        Path("dazro_trade/analytics/strategy_2_statistical_sample_audit.py"),
        Path("scripts/analyze_strategy_2_statistical_samples.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    assert "strategy_3" not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "open(\"data/xauusd" not in combined
