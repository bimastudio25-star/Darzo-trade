from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd


@dataclass(frozen=True)
class VolumeProfile:
    poc: float | None
    hvn: list[float]
    lvn: list[float]
    volume_cracks: list[tuple[float, float]]


def build_volume_profile(df: pd.DataFrame, *, bins: int = 24) -> VolumeProfile:
    frame = _normalize(df)
    if frame.empty:
        return VolumeProfile(None, [], [], [])
    low = float(frame["l"].min())
    high = float(frame["h"].max())
    if high <= low:
        return VolumeProfile(None, [], [], [])
    step = (high - low) / bins
    buckets = [0.0 for _ in range(bins)]
    for _, row in frame.iterrows():
        price = (float(row["h"]) + float(row["l"]) + float(row["c"])) / 3
        idx = min(max(int((price - low) / step), 0), bins - 1)
        buckets[idx] += float(row.get("vol", 1) or 1)
    max_vol = max(buckets) if buckets else 0
    if max_vol <= 0:
        return VolumeProfile(None, [], [], [])
    poc_idx = buckets.index(max_vol)
    avg = sum(buckets) / len(buckets)
    hvn = [round(low + (idx + 0.5) * step, 2) for idx, vol in enumerate(buckets) if vol >= avg * 1.25]
    lvn = [round(low + (idx + 0.5) * step, 2) for idx, vol in enumerate(buckets) if vol <= avg * 0.55]
    cracks = []
    in_crack = False
    crack_start = None
    for idx, vol in enumerate(buckets):
        if vol <= avg * 0.45 and not in_crack:
            in_crack = True
            crack_start = low + idx * step
        if in_crack and (vol > avg * 0.45 or idx == len(buckets) - 1):
            end_idx = idx if vol > avg * 0.45 else idx + 1
            cracks.append((round(crack_start or low, 2), round(low + end_idx * step, 2)))
            in_crack = False
    return VolumeProfile(round(low + (poc_idx + 0.5) * step, 2), hvn[:8], lvn[:8], cracks[:8])


def daily_range_from(
    d1_df: pd.DataFrame,
    *,
    now_utc: datetime | None = None,
    min_age_minutes_for_open_candle: int = 60,
) -> tuple[float, float, str] | None:
    """Returns (low, high, source). source in {"d1_current","d1_previous"}."""
    frame = _normalize(d1_df)
    if frame.empty or len(frame) < 2:
        return None
    idx = -2
    source = "d1_previous"
    if "time" in frame.columns:
        now = now_utc or datetime.now(timezone.utc)
        last_time = pd.Timestamp(frame["time"].iloc[-1]).to_pydatetime()
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)
        age_minutes = (now.astimezone(timezone.utc) - last_time.astimezone(timezone.utc)).total_seconds() / 60
        if age_minutes >= min_age_minutes_for_open_candle:
            idx = -1
            source = "d1_current"
    row = frame.iloc[idx]
    low = float(row["l"])
    high = float(row["h"])
    if high <= low:
        return None
    return low, high, source


def build_daily_anchored_profile(
    daily_low: float,
    daily_high: float,
    intraday_df: pd.DataFrame,
    *,
    bins: int = 30,
) -> VolumeProfile:
    """Same shape as build_volume_profile, anchored exactly to the D1 range."""
    frame = _normalize(intraday_df)
    low = float(daily_low)
    high = float(daily_high)
    if frame.empty or high <= low:
        return VolumeProfile(None, [], [], [])
    step = (high - low) / bins
    buckets = [0.0 for _ in range(bins)]
    for _, row in frame.iterrows():
        price = (float(row["h"]) + float(row["l"]) + float(row["c"])) / 3
        if price < low or price > high:
            continue
        idx = min(max(int((price - low) / step), 0), bins - 1)
        buckets[idx] += float(row.get("vol", 1) or 1)
    max_vol = max(buckets) if buckets else 0
    if max_vol <= 0:
        return VolumeProfile(None, [], [], [])
    poc_idx = buckets.index(max_vol)
    avg = sum(buckets) / len(buckets)
    hvn = [round(low + (idx + 0.5) * step, 2) for idx, vol in enumerate(buckets) if vol >= avg * 1.25]
    lvn = [round(low + (idx + 0.5) * step, 2) for idx, vol in enumerate(buckets) if vol <= avg * 0.55]
    cracks = []
    in_crack = False
    crack_start = None
    for idx, vol in enumerate(buckets):
        if vol <= avg * 0.45 and not in_crack:
            in_crack = True
            crack_start = low + idx * step
        if in_crack and (vol > avg * 0.45 or idx == len(buckets) - 1):
            end_idx = idx if vol > avg * 0.45 else idx + 1
            cracks.append((round(crack_start or low, 2), round(low + end_idx * step, 2)))
            in_crack = False
    return VolumeProfile(round(low + (poc_idx + 0.5) * step, 2), hvn[:8], lvn[:8], cracks[:8])


def volume_crack_confluence(profile: VolumeProfile, level: float) -> dict:
    for low, high in profile.volume_cracks:
        if low <= level <= high:
            return {"confluence": True, "reason": "volume_crack_reaction_candidate", "range": (low, high)}
    for lvn in profile.lvn:
        if abs(lvn - level) <= 0.5:
            return {"confluence": True, "reason": "lvn_reaction_candidate", "level": lvn}
    return {"confluence": False, "reason": "no_volume_crack_nearby"}


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy().rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"})
    if {"h", "l", "c"}.issubset(out.columns):
        return out
    return pd.DataFrame()


__all__ = ["VolumeProfile", "build_daily_anchored_profile", "build_volume_profile", "daily_range_from", "volume_crack_confluence"]
