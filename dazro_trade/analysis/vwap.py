from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from dazro_trade.runtime.sessions import current_session_name


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
    session: str | None = None
    equal_weight_fallback: bool = False


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


def session_vwap_snapshot(df: pd.DataFrame, price: float | None = None) -> VwapSnapshot | None:
    frame = _normalize(df)
    if frame.empty or "time" not in frame.columns:
        return vwap_snapshot(frame, price)
    out = frame.copy()
    out["time"] = pd.to_datetime(out["time"], utc=True, errors="coerce")
    out = out.dropna(subset=["time"])
    if out.empty:
        return vwap_snapshot(frame, price)
    sessions = out["time"].map(lambda ts: current_session_name(ts.to_pydatetime()))
    current_session = str(sessions.iloc[-1])
    same_session = sessions == current_session
    # Use only the latest contiguous block of the active session. This
    # resets VWAP when the session label changes and avoids future data
    # because callers pass sliced backtest data up to the evaluation bar.
    start_idx = len(out) - 1
    while start_idx > 0 and bool(same_session.iloc[start_idx - 1]):
        start_idx -= 1
    session_frame = out.iloc[start_idx:]
    snapshot = _snapshot_from_frame(session_frame, price)
    if snapshot is None:
        return None
    return VwapSnapshot(**{**snapshot.__dict__, "session": current_session})


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
        if "vol" not in out.columns:
            out["vol"] = 1.0
        return out
    return pd.DataFrame()


def _snapshot_from_frame(df: pd.DataFrame, price: float | None = None) -> VwapSnapshot | None:
    frame = _normalize(df)
    if frame.empty:
        return None
    typical = (frame["h"].astype(float) + frame["l"].astype(float) + frame["c"].astype(float)) / 3
    volume = frame.get("vol", pd.Series([1] * len(frame), index=frame.index)).astype(float)
    equal_weight_fallback = bool((volume <= 0).all())
    volume = volume.where(volume > 0, 1.0)
    weighted = (typical * volume).cumsum() / volume.cumsum()
    if weighted.empty:
        return None
    current_vwap = float(weighted.iloc[-1])
    residual = typical - current_vwap
    if len(residual) < 2:
        std = 0.0
    else:
        total_volume = float(volume.sum())
        std = float(((volume * (residual ** 2)).sum() / total_volume) ** 0.5) if total_volume > 0 else 0.0
    close = frame["c"].astype(float)
    current_price = float(price if price is not None else close.iloc[-1])
    z = (current_price - current_vwap) / std if std > 0 else 0.0
    slope = float(weighted.iloc[-1] - weighted.iloc[-min(len(weighted), 10)])
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
        equal_weight_fallback=equal_weight_fallback,
    )


__all__ = ["VwapSnapshot", "calculate_vwap", "session_vwap_snapshot", "vwap_deviation_confluence", "vwap_snapshot"]
