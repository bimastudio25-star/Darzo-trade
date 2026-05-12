from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class VwapSnapshot:
    vwap: float
    std: float
    upper_1: float
    upper_2: float
    upper_3: float
    lower_1: float
    lower_2: float
    lower_3: float
    z_score: float
    slope: float


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    frame = _normalize(df)
    if frame.empty:
        return pd.Series(dtype=float)
    typical = (frame["h"].astype(float) + frame["l"].astype(float) + frame["c"].astype(float)) / 3
    volume = frame.get("vol", pd.Series([1] * len(frame), index=frame.index)).astype(float).clip(lower=1)
    return (typical * volume).cumsum() / volume.cumsum()


def vwap_snapshot(df: pd.DataFrame, price: float | None = None) -> VwapSnapshot | None:
    frame = _normalize(df)
    if frame.empty:
        return None
    vwap = calculate_vwap(frame)
    if vwap.empty:
        return None
    close = frame["c"].astype(float)
    residual = close - vwap
    std = float(residual.tail(min(len(residual), 120)).std() or 0.0)
    current_vwap = float(vwap.iloc[-1])
    current_price = float(price if price is not None else close.iloc[-1])
    z = (current_price - current_vwap) / std if std > 0 else 0.0
    slope = float(vwap.iloc[-1] - vwap.iloc[-min(len(vwap), 10)])
    return VwapSnapshot(
        vwap=round(current_vwap, 2),
        std=round(std, 4),
        upper_1=round(current_vwap + std, 2),
        upper_2=round(current_vwap + std * 2, 2),
        upper_3=round(current_vwap + std * 3, 2),
        lower_1=round(current_vwap - std, 2),
        lower_2=round(current_vwap - std * 2, 2),
        lower_3=round(current_vwap - std * 3, 2),
        z_score=round(z, 2),
        slope=round(slope, 4),
    )


def vwap_deviation_confluence(df: pd.DataFrame, price: float, direction: str) -> dict:
    snapshot = vwap_snapshot(df, price)
    if snapshot is None:
        return {"confluence": False, "reason": "vwap_unavailable"}
    if direction == "SELL" and snapshot.z_score >= 2:
        return {"confluence": True, "reason": "vwap_2sigma_rejection", "snapshot": snapshot.__dict__}
    if direction == "BUY" and snapshot.z_score <= -2:
        return {"confluence": True, "reason": "vwap_minus_2sigma_rejection", "snapshot": snapshot.__dict__}
    return {"confluence": False, "reason": "vwap_not_extended", "snapshot": snapshot.__dict__}


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy().rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"})
    if {"h", "l", "c"}.issubset(out.columns):
        return out
    return pd.DataFrame()


__all__ = ["VwapSnapshot", "calculate_vwap", "vwap_deviation_confluence", "vwap_snapshot"]
