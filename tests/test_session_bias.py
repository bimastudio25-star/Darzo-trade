from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from dazro_trade.runtime.session_bias import (
    apply_session_bias_to_strategy,
    classify_session_relationship,
)


def _m15_rows(start: datetime, candles: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    rows = []
    for idx, (o, h, l, c) in enumerate(candles):
        rows.append({"time": start + timedelta(minutes=15 * idx), "o": o, "h": h, "l": l, "c": c, "vol": 50})
    return pd.DataFrame(rows)


def _asia_candles(o: float = 4700.0, range_pts: float = 1.5) -> list[tuple[float, float, float, float]]:
    out = []
    price = o
    for _ in range(28):
        out.append((price, price + range_pts * 0.4, price - range_pts * 0.4, price + 0.05))
        price += 0.05
    return out


def test_asia_accumulation_tight_range():
    asia_start = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
    candles = _asia_candles(4700.0, range_pts=1.0)
    m15 = _m15_rows(asia_start, candles)
    now = datetime(2026, 5, 13, 5, 0, tzinfo=timezone.utc)
    rel = classify_session_relationship({"M15": m15}, now, asia_range_max_pips=200.0)
    assert rel.active_session == "asia"
    assert rel.label == "ASIA_ACCUMULATION"


def test_london_opening_drive_breaks_asia():
    asia_start = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
    asia = _asia_candles(4700.0, range_pts=1.0)
    london_start = datetime(2026, 5, 13, 7, 0, tzinfo=timezone.utc)
    london = []
    price = 4701.0
    for _ in range(20):
        london.append((price, price + 1.2, price - 0.3, price + 1.0))
        price += 1.0
    rows = _m15_rows(asia_start, asia + london)
    now = datetime(2026, 5, 13, 11, 0, tzinfo=timezone.utc)
    rel = classify_session_relationship({"M15": rows}, now)
    assert rel.active_session == "london"
    assert rel.label == "LONDON_OPENING_DRIVE"
    assert rel.directional_bias == "bullish"


def test_london_reversal_of_asia_sweep_and_return():
    asia_start = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
    asia = _asia_candles(4700.0, range_pts=1.0)
    london = []
    london.append((4701.5, 4710.0, 4701.0, 4702.0))
    for _ in range(19):
        london.append((4701.5, 4701.6, 4700.5, 4700.8))
    rows = _m15_rows(asia_start, asia + london)
    now = datetime(2026, 5, 13, 11, 0, tzinfo=timezone.utc)
    rel = classify_session_relationship({"M15": rows}, now)
    assert rel.active_session == "london"
    assert rel.label == "LONDON_REVERSAL_OF_ASIA"
    assert rel.swept_level == "asia_high"


def test_ny_continuation_aligned_with_london():
    asia_start = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
    asia = _asia_candles(4700.0, range_pts=1.0)
    london = []
    price = 4701.0
    for _ in range(22):
        london.append((price, price + 1.2, price - 0.3, price + 1.0))
        price += 1.0
    ny = []
    price = london[-1][3]
    for _ in range(20):
        ny.append((price, price + 1.5, price - 0.3, price + 1.2))
        price += 1.2
    rows = _m15_rows(asia_start, asia + london + ny)
    now = datetime(2026, 5, 13, 15, 0, tzinfo=timezone.utc)
    rel = classify_session_relationship({"M15": rows}, now)
    assert rel.active_session == "ny"
    assert rel.label == "NY_CONTINUATION"
    assert rel.directional_bias == "bullish"


def test_ny_manipulation_reversal_sweep_london_and_reverse():
    asia_start = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
    asia = _asia_candles(4700.0, range_pts=1.0)
    london = []
    price = 4701.0
    for _ in range(22):
        london.append((price, price + 1.0, price - 0.3, price + 0.8))
        price += 0.8
    london_high = max(r[1] for r in london)
    london_low = min(r[2] for r in london)
    ny = []
    ny.append((london[-1][3], london_high + 2.0, london[-1][3] - 0.5, london[-1][3] - 1.0))
    price = ny[-1][3]
    for _ in range(18):
        new_low = max(price - 0.4, london_low + 0.5)
        new_close = max(price - 0.3, london_low + 0.7)
        ny.append((price, price + 0.2, new_low, new_close))
        price = new_close
    rows = _m15_rows(asia_start, asia + london + ny)
    now = datetime(2026, 5, 13, 15, 0, tzinfo=timezone.utc)
    rel = classify_session_relationship({"M15": rows}, now)
    assert rel.active_session == "ny"
    assert rel.label == "NY_MANIPULATION_REVERSAL"
    assert rel.directional_bias == "bearish"
    assert rel.swept_level == "london_high"


def test_ny_range_inside_london():
    asia_start = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
    asia = _asia_candles(4700.0, range_pts=1.0)
    london = []
    london.append((4701.0, 4710.0, 4699.0, 4705.0))
    for _ in range(20):
        london.append((4705.0, 4708.0, 4702.0, 4705.0))
    ny = []
    for _ in range(20):
        ny.append((4705.0, 4706.5, 4703.5, 4705.0))
    rows = _m15_rows(asia_start, asia + london + ny)
    now = datetime(2026, 5, 13, 15, 0, tzinfo=timezone.utc)
    rel = classify_session_relationship({"M15": rows}, now)
    assert rel.active_session == "ny"
    assert rel.label == "NY_RANGE_INSIDE_LONDON"


def test_unclear_with_no_data():
    rel = classify_session_relationship({"M15": pd.DataFrame()}, datetime(2026, 5, 13, 15, 0, tzinfo=timezone.utc))
    assert rel.label == "UNCLEAR"


def test_apply_bias_boost_on_aligned_continuation():
    rel = classify_session_relationship({"M15": pd.DataFrame()}, datetime(2026, 5, 13, 15, 0, tzinfo=timezone.utc))
    bullish_rel = rel.__class__(
        label="NY_CONTINUATION",
        active_session="ny",
        previous_session="london",
        directional_bias="bullish",
        confidence=0.8,
        asia_range=rel.asia_range,
        london_range=rel.london_range,
        ny_range=rel.ny_range,
        swept_level="london_high",
        reason_codes=["ny_extended_past_london_high"],
        notes=[],
    )
    effect = apply_session_bias_to_strategy("LONG", bullish_rel)
    assert effect["effect"] == "boost"


def test_apply_bias_demote_on_manipulation_against_direction():
    rel = classify_session_relationship({"M15": pd.DataFrame()}, datetime(2026, 5, 13, 15, 0, tzinfo=timezone.utc))
    bearish_rel = rel.__class__(
        label="NY_MANIPULATION_REVERSAL",
        active_session="ny",
        previous_session="london",
        directional_bias="bearish",
        confidence=0.75,
        asia_range=rel.asia_range,
        london_range=rel.london_range,
        ny_range=rel.ny_range,
        swept_level="london_high",
        reason_codes=["ny_swept_london_high"],
        notes=[],
    )
    effect = apply_session_bias_to_strategy("LONG", bearish_rel)
    assert effect["effect"] == "demote"


def test_apply_bias_neutral_when_unclear():
    rel = classify_session_relationship({"M15": pd.DataFrame()}, datetime(2026, 5, 13, 15, 0, tzinfo=timezone.utc))
    effect = apply_session_bias_to_strategy("LONG", rel)
    assert effect["effect"] == "neutral"
