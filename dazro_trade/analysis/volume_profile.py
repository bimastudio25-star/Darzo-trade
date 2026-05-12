from __future__ import annotations

from dataclasses import dataclass

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


__all__ = ["VolumeProfile", "build_volume_profile", "volume_crack_confluence"]
