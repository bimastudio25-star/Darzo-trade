from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from dazro_trade.analysis.candle_path import classify_candle_path
from dazro_trade.analysis.session_candles import classify_session_candle
from dazro_trade.analysis.time_behaviour import classify_time_behaviour


def frame(rows):
    base = datetime(2026, 5, 12, 6, 0, tzinfo=timezone.utc)
    return pd.DataFrame(
        [{"time": base + pd.Timedelta(minutes=i), "o": r[0], "h": r[1], "l": r[2], "c": r[3], "vol": r[4] if len(r) > 4 else 100} for i, r in enumerate(rows)]
    )


def test_time_behaviour_asia_range_building():
    ctx = classify_time_behaviour(datetime(2026, 5, 11, 23, 0, tzinfo=timezone.utc), {}, timezone="Europe/Rome")
    assert ctx.time_window == "asia_early_range_building"
    assert "asia_range_building" in ctx.reason_codes
    assert "low_volatility_liquidity_accumulation" in ctx.reason_codes


def test_time_behaviour_midday_retrace_chop():
    ctx = classify_time_behaviour(datetime(2026, 5, 12, 9, 0, tzinfo=timezone.utc), {}, timezone="Europe/Rome")
    assert ctx.time_window == "midday"
    assert "midday_retrace_window" in ctx.reason_codes
    assert "no_trade_chop_risk" in ctx.reason_codes


def test_candle_path_high_first_reversal():
    higher = frame([(4718, 4722.5, 4717.8, 4718.5)]).iloc[0]
    lower = frame([(4718, 4719, 4718.2, 4718.8), (4718.8, 4722.5, 4718.7, 4721.8), (4721.8, 4722.0, 4717.8, 4718.5)])
    ctx = classify_candle_path(higher, lower, reference_high=4722.0, reference_low=4717.0)
    assert ctx.path_type == "HIGH_FIRST_REVERSAL"
    assert "high_taken_first" in ctx.reason_codes


def test_candle_path_one_way_up():
    higher = frame([(4718, 4722.5, 4717.8, 4722.3)]).iloc[0]
    lower = frame([(4718, 4719, 4717.8, 4719), (4719, 4721, 4718.9, 4720.8), (4720.8, 4722.5, 4720.7, 4722.3)])
    ctx = classify_candle_path(higher, lower)
    assert ctx.path_type == "ONE_WAY_UP"


def test_london_open_buy_side_manipulation():
    time_ctx = classify_time_behaviour(datetime(2026, 5, 12, 6, 5, tzinfo=timezone.utc), {}, timezone="Europe/Rome")
    candle = frame([(4718, 4722.5, 4717.8, 4721.8)]).iloc[0]
    event = classify_session_candle(
        symbol="XAUUSD",
        timeframe="M5",
        candle=candle,
        lower_tf=frame([(4718, 4722.5, 4717.8, 4721.8)]),
        session_name="London",
        time_context=time_ctx,
        reference_ranges={"asia_high": 4722.0, "asia_low": 4717.0},
        ema_context={},
        vwap_context={},
        liquidity_pools=[],
    )
    assert event.classification == "OPEN_MANIPULATION_BUY_SIDE_SWEEP"
    assert "manipulation_candle_candidate" in event.reason_codes


def test_london_open_accepted_breakout_continuation():
    time_ctx = classify_time_behaviour(datetime(2026, 5, 12, 6, 5, tzinfo=timezone.utc), {}, timezone="Europe/Rome")
    event = classify_session_candle(
        symbol="XAUUSD",
        timeframe="M5",
        candle=frame([(4718, 4723.0, 4717.8, 4722.8)]).iloc[0],
        lower_tf=frame([(4718, 4719, 4717.8, 4719), (4719, 4721, 4718.9, 4721), (4721, 4723, 4720.9, 4722.8)]),
        session_name="London",
        time_context=time_ctx,
        reference_ranges={"asia_high": 4722.0, "asia_low": 4717.0},
        ema_context={"ema_alignment": "bullish"},
        vwap_context={"vwap": 4720.0},
        liquidity_pools=[],
    )
    assert event.classification == "OPEN_DRIVE_CONTINUATION_LONG"
    assert "accepted_breakout" in event.reason_codes


def test_ny_manipulation_reversal_short_candidate():
    time_ctx = classify_time_behaviour(datetime(2026, 5, 12, 12, 35, tzinfo=timezone.utc), {}, timezone="Europe/Rome")
    event = classify_session_candle(
        symbol="XAUUSD",
        timeframe="M5",
        candle=frame([(4718, 4722.5, 4717.8, 4721.8)]).iloc[0],
        lower_tf=frame([(4718, 4722.5, 4717.8, 4721.8)]),
        session_name="New York",
        time_context=time_ctx,
        reference_ranges={"london_high": 4722.0, "london_low": 4717.0},
        ema_context={},
        vwap_context={},
        liquidity_pools=[],
    )
    assert event.classification == "NY_MANIPULATION_REVERSAL_SHORT"


def test_liquidity_search_no_trade():
    time_ctx = classify_time_behaviour(datetime(2026, 5, 12, 6, 5, tzinfo=timezone.utc), {}, timezone="Europe/Rome")
    event = classify_session_candle(
        symbol="XAUUSD",
        timeframe="M5",
        candle=frame([(4718, 4722.5, 4716.5, 4718.1)]).iloc[0],
        lower_tf=frame([(4718, 4722.5, 4717.8, 4718.5), (4718.5, 4719, 4716.5, 4718.1)]),
        session_name="London",
        time_context=time_ctx,
        reference_ranges={"asia_high": 4722.0, "asia_low": 4717.0},
        ema_context={},
        vwap_context={},
        liquidity_pools=[],
    )
    assert event.classification == "LIQUIDITY_SEARCH_NO_TRADE"


def test_amd_distribution_short_after_confirmations():
    time_ctx = classify_time_behaviour(datetime(2026, 5, 12, 6, 5, tzinfo=timezone.utc), {}, timezone="Europe/Rome")
    event = classify_session_candle(
        symbol="XAUUSD",
        timeframe="M5",
        candle=frame([(4718, 4722.5, 4717.8, 4721.8)]).iloc[0],
        lower_tf=frame([(4718, 4722.5, 4717.8, 4721.8)]),
        session_name="London",
        time_context=time_ctx,
        reference_ranges={"asia_high": 4722.0, "asia_low": 4717.0},
        ema_context={},
        vwap_context={},
        liquidity_pools=[{"reason_codes": ["m1_choch", "m5_displacement", "bearish_fvg_after_buy_side_sweep"]}],
    )
    assert event.classification == "AMD_DISTRIBUTION_SHORT"
