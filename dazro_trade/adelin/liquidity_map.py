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
        return out
    return pd.DataFrame()


def build_liquidity_map(df_h4: pd.DataFrame | None, df_h1: pd.DataFrame | None, df_m15: pd.DataFrame | None, df_m5: pd.DataFrame | None, pip: float | None = None) -> list[dict[str, Any]]:
    pip_size = _pip(pip)
    pools: list[dict[str, Any]] = []
    h4 = _normalize(df_h4)
    h1 = _normalize(df_h1)
    m15 = _normalize(df_m15)
    m5 = _normalize(df_m5)
    if len(h4):
        pools.extend(_range_levels(h4.tail(30), "PWH", "PWL", "H4", "external"))
        pools.extend(_swing_levels(h4, "H4", "external", pip_size))
    if len(h1):
        pools.extend(_range_levels(h1.tail(24), "PDH", "PDL", "H1", "external"))
        pools.extend(_swing_levels(h1, "H1", "external", pip_size))
        pools.extend(_session_levels(h1))
    if len(m15):
        pools.extend(_swing_levels(m15, "M15", "internal", pip_size))
        pools.extend(_equal_levels(m15, "M15", pip_size))
        pools.extend(_fvg_levels(m15, "M15"))
    if len(m5):
        pools.extend(_swing_levels(m5, "M5", "internal", pip_size))
        pools.extend(_equal_levels(m5, "M5", pip_size))
        pools.extend(_fvg_levels(m5, "M5"))
    return _dedupe_levels(pools)


def _range_levels(frame: pd.DataFrame, high_name: str, low_name: str, timeframe: str, scope: str) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return [
        _level(high_name, float(frame["h"].max()), "buy_side", timeframe, scope, "range_high", 90),
        _level(low_name, float(frame["l"].min()), "sell_side", timeframe, scope, "range_low", 90),
    ]


def _session_levels(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    chunks = {"asia": frame.tail(24).iloc[:8], "london": frame.tail(24).iloc[8:16], "ny": frame.tail(24).iloc[16:24]}
    levels: list[dict[str, Any]] = []
    for name, chunk in chunks.items():
        if chunk.empty:
            continue
        levels.append(_level(f"{name}_high", float(chunk["h"].max()), "buy_side", "H1", "session", "session_high", 70))
        levels.append(_level(f"{name}_low", float(chunk["l"].min()), "sell_side", "H1", "session", "session_low", 70))
    return levels


def _swing_levels(frame: pd.DataFrame, timeframe: str, scope: str, pip: float) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    if len(frame) < 5:
        return levels
    recent = frame.tail(min(len(frame), 120)).reset_index(drop=True)
    tolerance = 2.5 * pip
    for idx in range(2, len(recent) - 2):
        window = recent.iloc[idx - 2 : idx + 3]
        row = recent.iloc[idx]
        high = float(row["h"])
        low = float(row["l"])
        high_touches = int((recent["h"].astype(float).sub(high).abs() <= tolerance).sum())
        low_touches = int((recent["l"].astype(float).sub(low).abs() <= tolerance).sum())
        if high == float(window["h"].max()) and high_touches >= 2:
            levels.append(_level(f"{timeframe}_swing_high", high, "buy_side", timeframe, scope, "swing_high", 80))
        if low == float(window["l"].min()) and low_touches >= 2:
            levels.append(_level(f"{timeframe}_swing_low", low, "sell_side", timeframe, scope, "swing_low", 80))
    return levels[-16:]


def _equal_levels(frame: pd.DataFrame, timeframe: str, pip: float) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    recent = frame.tail(min(len(frame), 80)).reset_index(drop=True)
    tolerance = 2.5 * pip
    for column, side, kind in (("h", "buy_side", "equal_highs"), ("l", "sell_side", "equal_lows")):
        values = recent[column].astype(float).tolist()
        for idx in range(len(values) - 1):
            if abs(values[idx] - values[idx + 1]) <= tolerance:
                levels.append(_level(f"{timeframe}_{kind}", (values[idx] + values[idx + 1]) / 2, side, timeframe, "internal", kind, 60))
    return levels[-10:]


def _fvg_levels(frame: pd.DataFrame, timeframe: str) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    recent = frame.tail(min(len(frame), 80)).reset_index(drop=True)
    for idx in range(2, len(recent)):
        high_two_back = float(recent["h"].iloc[idx - 2])
        low_two_back = float(recent["l"].iloc[idx - 2])
        low = float(recent["l"].iloc[idx])
        high = float(recent["h"].iloc[idx])
        if low > high_two_back:
            meta = _ifvg_metadata(recent, idx, high_two_back, low, "bullish")
            kind = "ifvg" if meta["is_true_ifvg"] else "fvg"
            levels.append(_level(f"{timeframe}_bullish_{kind}", (high_two_back + low) / 2, "sell_side", timeframe, "internal", f"bullish_{kind}", 55, meta))
        if high < low_two_back:
            meta = _ifvg_metadata(recent, idx, high, low_two_back, "bearish")
            kind = "ifvg" if meta["is_true_ifvg"] else "fvg"
            levels.append(_level(f"{timeframe}_bearish_{kind}", (high + low_two_back) / 2, "buy_side", timeframe, "internal", f"bearish_{kind}", 55, meta))
    return levels[-8:]


def _ifvg_metadata(frame: pd.DataFrame, created_idx: int, low: float, high: float, direction: str) -> dict[str, Any]:
    later = frame.iloc[created_idx + 1 :]
    if direction == "bullish":
        mitigated = later.index[later["c"].astype(float) < low].tolist()
        retested = frame.iloc[(mitigated[0] + 1) :].index[frame.iloc[(mitigated[0] + 1) :]["h"].astype(float) >= low].tolist() if mitigated else []
    else:
        mitigated = later.index[later["c"].astype(float) > high].tolist()
        retested = frame.iloc[(mitigated[0] + 1) :].index[frame.iloc[(mitigated[0] + 1) :]["l"].astype(float) <= high].tolist() if mitigated else []
    mitigated_idx = int(mitigated[0]) if mitigated else None
    retested_idx = int(retested[0]) if retested else None
    return {
        "created_index": int(created_idx),
        "mitigated_index": mitigated_idx,
        "inverted_index": mitigated_idx,
        "retested_index": retested_idx,
        "is_true_ifvg": mitigated_idx is not None and retested_idx is not None,
    }


def _level(name: str, level: float, side: str, timeframe: str, scope: str, kind: str, priority: int, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "level": round(float(level), 2),
        "side": side,
        "timeframe": timeframe,
        "scope": scope,
        "kind": kind,
        "priority": priority,
        "metadata": metadata or {},
    }


def _dedupe_levels(levels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[tuple[str, str, str, float], dict[str, Any]] = {}
    for item in levels:
        key = (str(item["timeframe"]), str(item["side"]), str(item["kind"]), round(float(item["level"]), 1))
        existing = out.get(key)
        if existing is None or int(item["priority"]) > int(existing["priority"]):
            out[key] = item
    return sorted(out.values(), key=lambda item: (-int(item["priority"]), str(item["timeframe"]), float(item["level"])))


def find_swept_level(sweep_price: float, liq_map: list[dict[str, Any]], tolerance_pips: float = 25.0, pip: float | None = None) -> dict[str, Any] | None:
    tolerance = tolerance_pips * _pip(pip)
    candidates = [item for item in liq_map if abs(float(item["level"]) - float(sweep_price)) <= tolerance]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-int(item["priority"]), abs(float(item["level"]) - float(sweep_price))))[0]


__all__ = ["build_liquidity_map", "find_swept_level"]
