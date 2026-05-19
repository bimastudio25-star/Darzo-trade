from __future__ import annotations

import pandas as pd

from dazro_trade.analysis.strategy_2_1_liquidity_expansion_spec import (
    build_spec_stop,
    build_spec_targets,
    evaluate_spec_setup,
)
from dazro_trade.analysis.strategy_2_liquidity_expansion_stats import (
    LiquidityExpansionStatsProfile,
    adaptive_tp1_distance,
    expansion_quartiles,
    find_m15_0045_for_h1,
    max_excursion_plus_25,
    validate_liquidity_sequence,
)
from dazro_trade.analytics.strategy_2_spec_alignment_audit import audit_trade_against_spec


def _profile(**updates: object) -> LiquidityExpansionStatsProfile:
    values = {
        "average_mae": 2.0,
        "median_mae": 2.0,
        "p75_mae": 3.0,
        "p90_mae": 4.0,
        "max_excursion": 4.0,
        "average_expansion": 3.0,
        "median_expansion": 4.0,
        "max_expansion": 16.0,
        "tp_quartile_distance": 4.0,
        "suggested_sl_distance": 5.0,
        "effective_risk_from_mae_entry": 7.0,
        "effective_risk_gt_12": False,
        "samples": 20,
    }
    values.update(updates)
    return LiquidityExpansionStatsProfile(**values)


def _h1() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": "2026-05-19T13:00:00+00:00", "open": 110, "high": 120, "low": 100, "close": 106},
            {"time": "2026-05-19T14:00:00+00:00", "open": 106, "high": 112, "low": 98, "close": 104},
        ]
    )


def _m15() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": "2026-05-19T13:45:00+00:00", "open": 106, "high": 130, "low": 105, "close": 108},
            {"time": "2026-05-19T14:45:00+00:00", "open": 104, "high": 109, "low": 99, "close": 101},
        ]
    )


def _m1_valid_long() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": "2026-05-19T14:00:00+00:00", "open": 106, "high": 110, "low": 101, "close": 104},
            {"time": "2026-05-19T14:01:00+00:00", "open": 104, "high": 104.5, "low": 99, "close": 100},
            {"time": "2026-05-19T14:02:00+00:00", "open": 100, "high": 101, "low": 98, "close": 100.5},
            {"time": "2026-05-19T14:03:00+00:00", "open": 100.5, "high": 109, "low": 100, "close": 108},
        ]
    )


def test_m15_0045_extraction_and_liquidity_sequence_validation():
    m15_ref = find_m15_0045_for_h1(_m15(), "2026-05-19T13:00:00+00:00")
    assert m15_ref["m15_0045_high"] == 130
    seq = validate_liquidity_sequence(
        _m1_valid_long(),
        direction="LONG",
        h1_start="2026-05-19T14:00:00+00:00",
        h1_level=100,
        m15_opposite_level=130,
        end="2026-05-19T14:59:00+00:00",
    )
    assert seq["liquidity_sequence_valid"] is True
    assert seq["h1_liquidity_taken"] is True


def test_mae_max_excursion_quartiles_and_adaptive_tp1():
    assert max_excursion_plus_25(4) == 5
    assert expansion_quartiles(16)["tp4_quartile_distance"] == 16
    assert adaptive_tp1_distance(average_expansion=3, max_expansion=16) == 3


def test_strategy_2_1_long_setup_uses_mae_entry_h1_stop_and_h1_targets():
    row = evaluate_spec_setup(
        symbol="XAUUSD",
        h1_current=_h1().iloc[1],
        h1_reference=_h1().iloc[0],
        m1=_m1_valid_long(),
        m15=_m15(),
        profile=_profile(),
        direction="LONG",
    )
    assert row["decision"] == "TRADE"
    assert row["entry_price"] == 98
    assert row["stop_loss"] == 95
    assert row["tp1"] == 103
    assert row["tp2"] == 108
    assert row["tp_anchor"] == "H1_LEVEL"


def test_strategy_2_1_rejects_long_when_m15_high_taken_first():
    m1 = pd.DataFrame(
        [
            {"time": "2026-05-19T14:00:00+00:00", "open": 106, "high": 131, "low": 105, "close": 110},
            {"time": "2026-05-19T14:01:00+00:00", "open": 110, "high": 111, "low": 99, "close": 100},
        ]
    )
    row = evaluate_spec_setup(
        symbol="XAUUSD",
        h1_current=_h1().iloc[1],
        h1_reference=_h1().iloc[0],
        m1=m1,
        m15=_m15(),
        profile=_profile(),
        direction="LONG",
    )
    assert row["decision"] == "NO_TRADE"
    assert "opposite_m15_level_taken_before_h1" in row["no_trade_reason_codes"]


def test_strategy_2_1_risk_over_12_defaults_to_no_trade():
    row = evaluate_spec_setup(
        symbol="XAUUSD",
        h1_current=_h1().iloc[1],
        h1_reference=_h1().iloc[0],
        m1=_m1_valid_long(),
        m15=_m15(),
        profile=_profile(max_excursion=20.0, suggested_sl_distance=25.0, effective_risk_from_mae_entry=27.0, effective_risk_gt_12=True),
        direction="LONG",
    )
    assert row["decision"] == "NO_TRADE"
    assert "RISK_TOO_LARGE" in row["no_trade_reason_codes"]


def test_short_stop_and_tp_are_anchored_to_h1_high():
    profile = _profile()
    targets = build_spec_targets("SHORT", 120, profile)
    assert build_spec_stop("SHORT", 120, profile) == 125
    assert targets.tp1 == 117
    assert targets.tp4 == 104


def test_spec_alignment_audit_flags_sl_gt_12_and_entry_anchor_detection():
    row = audit_trade_against_spec(
        {
            "timestamp": "2026-05-19T14:02:00+00:00",
            "direction": "LONG",
            "entry": "98",
            "stop": "80",
            "tp2": "108",
            "reward_distance": "10",
            "outcome": "SL",
            "r_multiple": "-1",
        },
        index=0,
        m1=_m1_valid_long(),
        m15=_m15(),
        h1=_h1(),
        profile=_profile(),
    )
    assert row["sl_exceeds_12_usd"] is True
    assert row["current_tp_appears_entry_anchored"] is True
    assert row["spec_alignment_label"] in {"PARTIALLY_ALIGNED", "NOT_ALIGNED"}
