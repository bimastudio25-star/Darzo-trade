from __future__ import annotations

from typing import Any

import pandas as pd

from dazro_trade.core.symbols import get_symbol_spec


def _pip(pip: float | None = None) -> float:
    return float(pip if pip is not None else get_symbol_spec("XAUUSD").pip_size)


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy().rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"})
    if {"h", "l", "c"}.issubset(out.columns):
        if "vol" not in out.columns:
            out["vol"] = 1.0
        return out
    return pd.DataFrame()


def build_volume_profile(
    df: pd.DataFrame,
    price_high: float,
    price_low: float,
    n_bins: int = 120,
    pip: float | None = None,
    crack_ratio: float = 0.15,
    hvn_ratio: float = 0.70,
    min_crack_pips: float = 5.0,
) -> dict[str, Any]:
    frame = _normalize(df)
    high = float(price_high)
    low = float(price_low)
    pip_size = _pip(pip)
    if frame.empty or high <= low or n_bins <= 0:
        return _empty_profile(high, low, n_bins)
    step = (high - low) / n_bins
    buckets = [0.0 for _ in range(n_bins)]
    for _, row in frame.iterrows():
        typical = (float(row["h"]) + float(row["l"]) + float(row["c"])) / 3
        if typical < low or typical > high:
            continue
        idx = min(max(int((typical - low) / step), 0), n_bins - 1)
        buckets[idx] += float(row.get("vol", 1) or 1)
    total = sum(buckets)
    if total <= 0:
        return _empty_profile(high, low, n_bins)
    centers = [round(low + (idx + 0.5) * step, 2) for idx in range(n_bins)]
    poc_idx = max(range(n_bins), key=lambda idx: buckets[idx])
    ranked = sorted(range(n_bins), key=lambda idx: buckets[idx], reverse=True)
    selected: list[int] = []
    running = 0.0
    for idx in ranked:
        selected.append(idx)
        running += buckets[idx]
        if running >= total * 0.70:
            break
    avg = total / n_bins
    hvn = [centers[idx] for idx, vol in enumerate(buckets) if vol >= max(buckets) * hvn_ratio and vol > 0]
    lvn = [centers[idx] for idx, vol in enumerate(buckets) if vol <= avg * max(crack_ratio, 0.01)]
    cracks = _cracks(low, step, buckets, avg, crack_ratio, min_crack_pips, pip_size)
    profile = [{"price": centers[idx], "volume": round(buckets[idx], 2)} for idx in range(n_bins)]
    return {
        "poc": centers[poc_idx],
        "vah": max(centers[idx] for idx in selected),
        "val": min(centers[idx] for idx in selected),
        "volume_cracks": cracks,
        "hvn": hvn[:12],
        "lvn": lvn[:12],
        "profile": profile,
        "price_high": round(high, 2),
        "price_low": round(low, 2),
        "bin_size": step,
        "volume_note": "Volume profile usa tick_volume MT5 come proxy, non vero volume futures.",
    }


def _empty_profile(high: float, low: float, bins: int) -> dict[str, Any]:
    return {
        "poc": None,
        "vah": None,
        "val": None,
        "volume_cracks": [],
        "hvn": [],
        "lvn": [],
        "profile": [],
        "price_high": round(high, 2),
        "price_low": round(low, 2),
        "bin_size": ((high - low) / bins) if high > low and bins > 0 else 0,
        "volume_note": "Volume profile usa tick_volume MT5 come proxy, non vero volume futures.",
    }


def _cracks(low: float, step: float, buckets: list[float], avg: float, ratio: float, min_crack_pips: float, pip: float) -> list[dict[str, float]]:
    cracks: list[dict[str, float]] = []
    start: int | None = None
    for idx, vol in enumerate(buckets):
        is_crack = vol <= avg * ratio
        if is_crack and start is None:
            start = idx
        if start is not None and (not is_crack or idx == len(buckets) - 1):
            end = idx if not is_crack else idx + 1
            crack_low = low + start * step
            crack_high = low + end * step
            width_pips = (crack_high - crack_low) / pip
            if width_pips >= min_crack_pips:
                cracks.append({"low": round(crack_low, 2), "high": round(crack_high, 2), "width_pips": round(width_pips, 1)})
            start = None
    return cracks[:12]


def price_in_volume_crack(price: float, vp: dict[str, Any], tolerance_pips: float = 5.0, pip: float | None = None) -> dict[str, Any]:
    tolerance = tolerance_pips * _pip(pip)
    for crack in vp.get("volume_cracks", []) or []:
        low = float(crack["low"]) - tolerance
        high = float(crack["high"]) + tolerance
        if low <= price <= high:
            return {"confluence": True, "crack": crack, "reason": "price_inside_volume_crack"}
    for lvn in vp.get("lvn", []) or []:
        if abs(float(lvn) - price) <= tolerance:
            return {"confluence": True, "lvn": lvn, "reason": "price_near_lvn"}
    return {"confluence": False, "reason": "no_volume_crack_or_lvn_nearby"}


def crack_covers_fvg(fvg_top: float, fvg_bot: float, vp: dict[str, Any], overlap_threshold: float = 0.5) -> dict[str, Any]:
    fvg_low = min(float(fvg_top), float(fvg_bot))
    fvg_high = max(float(fvg_top), float(fvg_bot))
    fvg_width = max(fvg_high - fvg_low, 0.0)
    if fvg_width <= 0:
        return {"confluence": False, "reason": "invalid_fvg_range"}
    for crack in vp.get("volume_cracks", []) or []:
        low = max(fvg_low, float(crack["low"]))
        high = min(fvg_high, float(crack["high"]))
        overlap = max(0.0, high - low) / fvg_width
        if overlap >= overlap_threshold:
            return {"confluence": True, "crack": crack, "overlap": round(overlap, 2), "reason": "volume_crack_covers_fvg"}
    return {"confluence": False, "reason": "volume_crack_does_not_cover_fvg"}


def build_multi_anchor_volume_profiles(frames: dict[str, pd.DataFrame], liquidity_map: list[dict[str, Any]], current_price: float, pip: float | None = None) -> dict[str, dict[str, Any]]:
    intraday = _normalize(frames.get("M5"))
    if intraday.empty:
        intraday = _normalize(frames.get("M15"))
    profiles: dict[str, dict[str, Any]] = {}
    d1 = _normalize(frames.get("D1"))
    if len(d1) >= 1:
        row = d1.iloc[-1]
        profiles["daily_current"] = build_volume_profile(intraday, float(row["h"]), float(row["l"]), pip=pip)
    if len(d1) >= 2:
        row = d1.iloc[-2]
        profiles["previous_day"] = build_volume_profile(intraday, float(row["h"]), float(row["l"]), pip=pip)
    for timeframe in ("H4", "H1", "M15"):
        frame = _normalize(frames.get(timeframe))
        if len(frame) >= 5:
            recent = frame.tail(min(len(frame), 80))
            profiles[f"{timeframe.lower()}_swing"] = build_volume_profile(intraday, float(recent["h"].max()), float(recent["l"].min()), pip=pip)
    for item in liquidity_map[:8]:
        level = float(item.get("level", current_price))
        width = max(50 * _pip(pip), abs(level - current_price))
        profiles[f"liquidity_{item.get('name', item.get('kind', 'range'))}_{round(level, 2)}"] = build_volume_profile(intraday, level + width, level - width, pip=pip)
    return profiles


def find_best_volume_crack_confluence(level_or_fvg: float | tuple[float, float], profiles: dict[str, dict[str, Any]], tolerance_pips: float = 5.0, pip: float | None = None) -> dict[str, Any]:
    for name, profile in profiles.items():
        if isinstance(level_or_fvg, tuple):
            out = crack_covers_fvg(level_or_fvg[0], level_or_fvg[1], profile)
        else:
            out = price_in_volume_crack(float(level_or_fvg), profile, tolerance_pips=tolerance_pips, pip=pip)
        if out.get("confluence"):
            return {"confluence": True, "profile": name, **out}
    return {"confluence": False, "reason": "no_anchor_volume_crack_confluence"}


__all__ = [
    "build_multi_anchor_volume_profiles",
    "build_volume_profile",
    "crack_covers_fvg",
    "find_best_volume_crack_confluence",
    "price_in_volume_crack",
]
