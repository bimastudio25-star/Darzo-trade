from __future__ import annotations

from typing import Any

import pandas as pd

from dazro_trade.core.symbols import price_to_pips


def ema(series: pd.Series, period: int) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return pd.Series(dtype=float)
    return values.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return pd.Series(dtype=float)
    delta = values.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, pd.NA)
    out = 100 - (100 / (1 + rs))
    out = out.mask((loss == 0) & (gain > 0), 100.0)
    out = out.mask((gain == 0) & (loss > 0), 0.0)
    return out.fillna(50.0)


def ema_context(
    df: pd.DataFrame,
    price: float,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M15",
    fast_period: int = 50,
    slow_period: int = 200,
) -> dict[str, Any]:
    if df is None or len(df) == 0:
        return _empty_ema_context(timeframe)
    close_col = "c" if "c" in df.columns else "close"
    if close_col not in df.columns:
        return _empty_ema_context(timeframe)
    closes = pd.to_numeric(df[close_col], errors="coerce").dropna()
    if closes.empty:
        return _empty_ema_context(timeframe)
    fast = ema(closes, fast_period)
    slow = ema(closes, slow_period)
    ema50 = float(fast.iloc[-1])
    ema200 = float(slow.iloc[-1])
    fast_slope = _slope(fast)
    slow_slope = _slope(slow)
    tolerance = max(abs(price) * 0.00015, 0.05)
    price_vs_ema50 = _price_vs(price, ema50, tolerance)
    price_vs_ema200 = _price_vs(price, ema200, tolerance)
    if abs(ema50 - ema200) <= tolerance and fast_slope == "flat" and slow_slope == "flat":
        alignment = "mixed"
        trend_state = "range"
    elif price > ema50 > ema200 and fast_slope == "up" and slow_slope in {"up", "flat"}:
        alignment = "bullish"
        trend_state = "strong_bullish"
    elif price < ema50 < ema200 and fast_slope == "down" and slow_slope in {"down", "flat"}:
        alignment = "bearish"
        trend_state = "strong_bearish"
    elif ema50 > ema200 and price_vs_ema50 in {"below", "touching"}:
        alignment = "bullish"
        trend_state = "bullish_pullback"
    elif ema50 < ema200 and price_vs_ema50 in {"above", "touching"}:
        alignment = "bearish"
        trend_state = "bearish_pullback"
    else:
        alignment = "mixed"
        trend_state = "range"
    return {
        "timeframe": timeframe,
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "price_vs_ema50": price_vs_ema50,
        "price_vs_ema200": price_vs_ema200,
        "ema50_slope": fast_slope,
        "ema200_slope": slow_slope,
        "ema_alignment": alignment,
        "trend_state": trend_state,
        "distance_from_ema50_pips": round(price_to_pips(symbol, abs(price - ema50)), 1),
        "distance_from_ema200_pips": round(price_to_pips(symbol, abs(price - ema200)), 1),
    }


def multi_tf_ema_context(frames: dict[str, pd.DataFrame], price: float, *, symbol: str = "XAUUSD") -> dict[str, dict[str, Any]]:
    return {
        timeframe: ema_context(frame, price, symbol=symbol, timeframe=timeframe)
        for timeframe, frame in frames.items()
        if timeframe in {"M1", "M5", "M15", "H1", "H4", "D1"}
    }


def rsi_context(df: pd.DataFrame, *, timeframe: str = "M15", period: int = 14) -> dict[str, Any]:
    if df is None or len(df) == 0:
        return {"timeframe": timeframe, "rsi14": None, "rsi_state": "unknown", "rsi_momentum": "flat", "rsi_warning": "insufficient_data"}
    close_col = "c" if "c" in df.columns else "close"
    if close_col not in df.columns:
        return {"timeframe": timeframe, "rsi14": None, "rsi_state": "unknown", "rsi_momentum": "flat", "rsi_warning": "insufficient_data"}
    values = rsi(df[close_col], period)
    if values.empty:
        return {"timeframe": timeframe, "rsi14": None, "rsi_state": "unknown", "rsi_momentum": "flat", "rsi_warning": "insufficient_data"}
    current = float(values.iloc[-1])
    previous = float(values.iloc[-4]) if len(values) >= 4 else float(values.iloc[0])
    if current > 70:
        state = "overbought"
        warning = "rsi_overbought_exhaustion_possible"
    elif current < 30:
        state = "oversold"
        warning = "rsi_oversold_exhaustion_possible"
    else:
        state = "neutral"
        warning = "rsi_neutral"
    if current - previous > 2:
        momentum = "rising"
        if current > 50:
            warning = "rsi_bullish_momentum"
    elif previous - current > 2:
        momentum = "falling"
        if current < 50:
            warning = "rsi_bearish_momentum"
    else:
        momentum = "flat"
    return {
        "timeframe": timeframe,
        "rsi14": round(current, 1),
        "rsi_state": state,
        "rsi_momentum": momentum,
        "rsi_warning": warning,
    }


def multi_tf_rsi_context(frames: dict[str, pd.DataFrame]) -> dict[str, dict[str, Any]]:
    return {
        timeframe: rsi_context(frame, timeframe=timeframe)
        for timeframe, frame in frames.items()
        if timeframe in {"M1", "M5", "M15", "H1", "H4", "D1"}
    }


def _empty_ema_context(timeframe: str) -> dict[str, Any]:
    return {
        "timeframe": timeframe,
        "ema50": None,
        "ema200": None,
        "price_vs_ema50": "unknown",
        "price_vs_ema200": "unknown",
        "ema50_slope": "flat",
        "ema200_slope": "flat",
        "ema_alignment": "mixed",
        "trend_state": "range",
        "distance_from_ema50_pips": None,
        "distance_from_ema200_pips": None,
    }


def _price_vs(price: float, level: float, tolerance: float) -> str:
    if abs(price - level) <= tolerance:
        return "touching"
    return "above" if price > level else "below"


def _slope(values: pd.Series) -> str:
    if len(values) < 4:
        return "flat"
    current = float(values.iloc[-1])
    previous = float(values.iloc[-4])
    tolerance = max(abs(current) * 0.00005, 0.02)
    if current - previous > tolerance:
        return "up"
    if previous - current > tolerance:
        return "down"
    return "flat"


__all__ = ["ema", "ema_context", "multi_tf_ema_context", "multi_tf_rsi_context", "rsi", "rsi_context"]
