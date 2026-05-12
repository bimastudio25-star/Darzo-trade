from __future__ import annotations

import pandas as pd

from dazro_trade.core.symbols import price_to_pips


def volatility_snapshot(
    *,
    symbol: str,
    m1: pd.DataFrame | None,
    m5: pd.DataFrame | None,
    spread_pips: float = 0.0,
    max_spread_pips: float = 30.0,
) -> dict:
    m1_frame = _normalize(m1)
    m5_frame = _normalize(m5)
    atr_m1 = _atr_pips(symbol, m1_frame)
    atr_m5 = _atr_pips(symbol, m5_frame)
    last_range = _last_range_pips(symbol, m1_frame)
    avg_range = _avg_range_pips(symbol, m1_frame)
    range_expansion = last_range / avg_range if avg_range else 0.0
    volume_spike = _volume_spike_ratio(m1_frame)
    reasons: list[str] = []
    if spread_pips > max_spread_pips:
        reasons.append("spread_too_high_no_reentry")
    if range_expansion >= 3.0 or volume_spike >= 3.0:
        state = "extreme"
        reasons.append("volatility_extreme_no_reentry")
    elif range_expansion >= 1.8 or volume_spike >= 1.8:
        state = "elevated"
        reasons.append("volatility_elevated_requires_strong_confirmation")
    else:
        state = "normal"
        reasons.append("volatility_normal")
    return {
        "volatility_state": state,
        "atr_m1_pips": atr_m1,
        "atr_m5_pips": atr_m5,
        "last_range_pips": last_range,
        "range_expansion_ratio": round(range_expansion, 2),
        "volume_spike_ratio": round(volume_spike, 2),
        "spread_pips": spread_pips,
        "safe_for_reentry": state != "extreme" and spread_pips <= max_spread_pips,
        "reason_codes": reasons,
    }


def _atr_pips(symbol: str, df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    ranges = df["h"].astype(float) - df["l"].astype(float)
    return round(price_to_pips(symbol, float(ranges.tail(20).mean() or 0)), 1)


def _last_range_pips(symbol: str, df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    last = df.iloc[-1]
    return round(price_to_pips(symbol, float(last["h"]) - float(last["l"])), 1)


def _avg_range_pips(symbol: str, df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    ranges = df["h"].astype(float) - df["l"].astype(float)
    return round(price_to_pips(symbol, float(ranges.tail(20).mean() or 0)), 1)


def _volume_spike_ratio(df: pd.DataFrame) -> float:
    if df.empty or "vol" not in df.columns or len(df) < 2:
        return 0.0
    avg = float(df["vol"].astype(float).tail(20).iloc[:-1].mean() or 1)
    last = float(df["vol"].iloc[-1] or 0)
    return last / avg if avg else 0.0


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy().rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"})
    if {"o", "h", "l", "c"}.issubset(out.columns):
        return out
    return pd.DataFrame()


__all__ = ["volatility_snapshot"]
