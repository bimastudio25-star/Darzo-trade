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
    if {"o", "h", "l", "c"}.issubset(out.columns):
        if "vol" not in out.columns:
            out["vol"] = 1.0
        return out
    return pd.DataFrame()


def calculate_vwap(df: pd.DataFrame) -> float | None:
    frame = _normalize(df)
    if frame.empty:
        return None
    typical = (frame["h"].astype(float) + frame["l"].astype(float) + frame["c"].astype(float)) / 3
    vol = frame["vol"].astype(float).replace(0, 1)
    total = float(vol.sum())
    if total <= 0:
        return None
    return round(float((typical * vol).sum() / total), 2)


def calculate_vwap_bands(df: pd.DataFrame) -> dict[str, float] | None:
    frame = _normalize(df)
    vwap = calculate_vwap(frame)
    if vwap is None or frame.empty:
        return None
    typical = (frame["h"].astype(float) + frame["l"].astype(float) + frame["c"].astype(float)) / 3
    std = float(typical.std() or 0)
    return {
        "vwap": vwap,
        "std": round(std, 4),
        "upper_1": round(vwap + std, 2),
        "lower_1": round(vwap - std, 2),
        "upper_2": round(vwap + 2 * std, 2),
        "lower_2": round(vwap - 2 * std, 2),
    }


def find_liquidity_sweep(df_m5: pd.DataFrame, df_m1: pd.DataFrame, liq_map: list[dict[str, Any]] | None = None, pip: float | None = None) -> dict[str, Any] | None:
    pip_size = _pip(pip)
    m5 = _normalize(df_m5)
    m1 = _normalize(df_m1)
    if m5.empty or len(m5) < 3:
        return None
    levels = liq_map or _fallback_equal_levels(m5, pip_size)
    if not levels:
        return None
    candle = m5.iloc[-1]
    for level in sorted(levels, key=lambda item: -int(item.get("priority", 0))):
        event = _sweep_against_level(candle, level, m1, pip_size)
        if event is not None:
            return event
    return None


def _sweep_against_level(candle: pd.Series, level: dict[str, Any], m1: pd.DataFrame, pip: float) -> dict[str, Any] | None:
    price = float(level["level"])
    side = str(level.get("side"))
    high = float(candle["h"])
    low = float(candle["l"])
    close = float(candle["c"])
    if side == "buy_side" and high > price and close < price:
        direction = "SHORT"
        penetration = (high - price) / pip
    elif side == "sell_side" and low < price and close > price:
        direction = "LONG"
        penetration = (price - low) / pip
    else:
        return None
    displacement = _m1_displacement(m1, direction)
    fvg = _post_liq_fvg(m1 if len(m1) >= 3 else pd.DataFrame([candle]), direction, pip)
    confidence = 0.35
    confidence += 0.25 if displacement else 0
    confidence += 0.25 if fvg.get("has_fvg") or fvg.get("has_ifvg") else 0
    confidence += min(0.15, max(0.0, penetration) / 100)
    return {
        "liquidity_swept": True,
        "level": price,
        "level_name": level.get("name"),
        "level_kind": level.get("kind"),
        "side": side,
        "direction": direction,
        "close_back_inside": True,
        "m1_displacement": displacement,
        "fvg_after_liquidity": bool(fvg.get("has_fvg")),
        "ifvg_after_liquidity": bool(fvg.get("has_ifvg")),
        "fvg": fvg,
        "penetration_pips": round(penetration, 1),
        "confidence": round(min(1.0, confidence), 2),
        "source": "liquidity_map",
    }


def _m1_displacement(m1: pd.DataFrame, direction: str) -> bool:
    if m1.empty or len(m1) < 4:
        return False
    bodies = (m1["c"].astype(float) - m1["o"].astype(float)).abs()
    avg = float(bodies.iloc[:-1].tail(5).mean() or 0.01)
    last = m1.iloc[-1]
    body = abs(float(last["c"]) - float(last["o"]))
    if direction == "LONG":
        return body >= avg * 1.2 and float(last["c"]) > float(last["o"])
    return body >= avg * 1.2 and float(last["c"]) < float(last["o"])


def _post_liq_fvg(frame: pd.DataFrame, direction: str, pip: float) -> dict[str, Any]:
    df = _normalize(frame)
    if len(df) < 3:
        return {"has_fvg": False, "has_ifvg": False}
    a = df.iloc[-3]
    c = df.iloc[-1]
    if direction == "LONG" and float(c["l"]) > float(a["h"]):
        bot = float(a["h"])
        top = float(c["l"])
        return {"has_fvg": True, "has_ifvg": False, "top": round(top, 2), "bot": round(bot, 2), "size_pips": round((top - bot) / pip, 1), "type": "bullish_fvg"}
    if direction == "SHORT" and float(c["h"]) < float(a["l"]):
        top = float(a["l"])
        bot = float(c["h"])
        return {"has_fvg": True, "has_ifvg": False, "top": round(top, 2), "bot": round(bot, 2), "size_pips": round((top - bot) / pip, 1), "type": "bearish_fvg"}
    return {"has_fvg": False, "has_ifvg": False}


def _fallback_equal_levels(m5: pd.DataFrame, pip: float) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    tolerance = 2.5 * pip
    recent = m5.tail(min(len(m5), 50)).reset_index(drop=True)
    for idx in range(len(recent) - 1):
        h1 = float(recent["h"].iloc[idx])
        h2 = float(recent["h"].iloc[idx + 1])
        l1 = float(recent["l"].iloc[idx])
        l2 = float(recent["l"].iloc[idx + 1])
        if abs(h1 - h2) <= tolerance:
            levels.append({"name": "m5_equal_highs_fallback", "level": round((h1 + h2) / 2, 2), "side": "buy_side", "kind": "equal_highs", "priority": 10})
        if abs(l1 - l2) <= tolerance:
            levels.append({"name": "m5_equal_lows_fallback", "level": round((l1 + l2) / 2, 2), "side": "sell_side", "kind": "equal_lows", "priority": 10})
    return levels[-8:]


__all__ = ["calculate_vwap", "calculate_vwap_bands", "find_liquidity_sweep"]
