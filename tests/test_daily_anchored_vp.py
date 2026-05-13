from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from dazro_trade.analysis.volume_profile import build_daily_anchored_profile, daily_range_from


def d1_frame(now: datetime) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": now - timedelta(days=2), "o": 100.0, "h": 104.0, "l": 99.0, "c": 102.0, "vol": 100},
            {"time": now - timedelta(days=1), "o": 102.0, "h": 106.0, "l": 101.0, "c": 105.0, "vol": 100},
            {"time": now - timedelta(minutes=10), "o": 105.0, "h": 110.0, "l": 104.0, "c": 108.0, "vol": 100},
        ]
    )


def test_daily_range_uses_previous_when_current_candle_is_young():
    now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
    out = daily_range_from(d1_frame(now), now_utc=now)
    assert out == (101.0, 106.0, "d1_previous")


def test_daily_range_uses_current_when_candle_is_old_enough():
    now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
    frame = d1_frame(now)
    frame.loc[2, "time"] = now - timedelta(hours=2)
    out = daily_range_from(frame, now_utc=now)
    assert out == (104.0, 110.0, "d1_current")


def test_daily_range_without_time_falls_back_to_previous():
    frame = d1_frame(datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)).drop(columns=["time"])
    out = daily_range_from(frame)
    assert out == (101.0, 106.0, "d1_previous")


def test_daily_range_empty_is_none():
    assert daily_range_from(pd.DataFrame()) is None


def test_daily_anchored_profile_drops_outside_typical_prices():
    rows = []
    for idx in range(40):
        base = 101.8 + (idx % 3) * 0.05
        rows.append({"o": base, "h": base + 0.2, "l": base - 0.2, "c": base, "vol": 100})
    for _ in range(10):
        rows.append({"o": 90.0, "h": 90.2, "l": 89.8, "c": 90.0, "vol": 1000})
    profile = build_daily_anchored_profile(100.0, 105.0, pd.DataFrame(rows))
    assert profile.poc is not None
    assert 100.0 <= profile.poc <= 105.0
    assert profile.hvn
