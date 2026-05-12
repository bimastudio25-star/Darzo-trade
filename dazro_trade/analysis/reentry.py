from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from dazro_trade.analysis.targets import build_intelligent_targets, validate_target_space
from dazro_trade.analysis.volatility import volatility_snapshot
from dazro_trade.core.symbols import price_to_pips, pips_to_price


@dataclass
class ReentryContext:
    original_signal_id: str
    symbol: str
    original_direction: str
    original_entry: float
    original_stop: float
    stop_hit_price: float
    stop_hit_time: datetime
    current_price: float
    state: str
    reason_codes: list[str] = field(default_factory=list)
    volatility_snapshot: dict = field(default_factory=dict)
    new_entry_area: tuple[float, float] | None = None
    new_stop: float | None = None
    new_targets: list[dict] = field(default_factory=list)


def evaluate_reentry(
    *,
    symbol: str,
    original_signal_id: str,
    direction: str,
    original_entry: float,
    original_stop: float,
    stop_hit_price: float,
    stop_hit_time: datetime,
    current_price: float,
    m1: pd.DataFrame | None,
    m5: pd.DataFrame | None,
    vwap_snapshot: dict | None = None,
    liquidity_pools: list[dict] | None = None,
    spread_pips: float = 0.0,
    settings: Any | None = None,
) -> ReentryContext:
    vol = volatility_snapshot(symbol=symbol, m1=m1, m5=m5, spread_pips=spread_pips, max_spread_pips=float(getattr(settings, "max_spread_pips", 30.0)))
    reasons: list[str] = ["stop_sweep_detected"]
    state = "REENTRY_WATCH"
    if not vol["safe_for_reentry"]:
        return ReentryContext(original_signal_id, symbol, direction, original_entry, original_stop, stop_hit_price, stop_hit_time, current_price, "NO_REENTRY", [*reasons, *vol["reason_codes"]], vol)
    if direction in {"SHORT", "SELL"}:
        if current_price > original_stop:
            return ReentryContext(original_signal_id, symbol, direction, original_entry, original_stop, stop_hit_price, stop_hit_time, current_price, "NO_REENTRY", [*reasons, "accepted_breakout_above_stop"], vol)
        reasons.append("close_back_below_old_stop")
        choch = _choch(m1, "SELL")
        displacement = _displacement(m5, "SELL")
        fvg = _fvg(m5, "SELL")
        if choch:
            reasons.append("m1_choch_after_stop_sweep")
        if displacement:
            reasons.append("m5_displacement_after_stop_sweep")
        if fvg:
            reasons.append("bearish_fvg_after_stop_sweep")
        entry = current_price
        stop = original_stop + pips_to_price(symbol, 10)
    else:
        if current_price < original_stop:
            return ReentryContext(original_signal_id, symbol, direction, original_entry, original_stop, stop_hit_price, stop_hit_time, current_price, "NO_REENTRY", [*reasons, "accepted_breakout_below_stop"], vol)
        reasons.append("close_back_above_old_stop")
        choch = _choch(m1, "BUY")
        displacement = _displacement(m5, "BUY")
        fvg = _fvg(m5, "BUY")
        if choch:
            reasons.append("m1_choch_after_stop_sweep")
        if displacement:
            reasons.append("m5_displacement_after_stop_sweep")
        if fvg:
            reasons.append("bullish_fvg_after_stop_sweep")
        entry = current_price
        stop = original_stop - pips_to_price(symbol, 10)
    if getattr(settings, "reentry_require_choch", True) and not choch:
        reasons.append("no_reentry_missing_choch")
    if getattr(settings, "reentry_require_fvg_or_ifvg", True) and not fvg:
        reasons.append("no_reentry_missing_fvg")
    distance_from_stop = price_to_pips(symbol, abs(current_price - original_stop))
    if distance_from_stop > float(getattr(settings, "reentry_no_chase_max_distance_pips", 80.0)):
        reasons.append("no_reentry_price_chased")
    entry_area = (round(entry - pips_to_price(symbol, 10), 2), round(entry + pips_to_price(symbol, 10), 2))
    targets = build_intelligent_targets(symbol=symbol, direction=direction, entry=entry, stop=stop, vwap_snapshot=vwap_snapshot, liquidity_pools=liquidity_pools or [])
    validation = validate_target_space(symbol, direction, entry, stop, targets, vwap_snapshot, liquidity_pools or [], settings)
    reasons.extend(validation["reason_codes"])
    if any(reason.startswith("no_reentry") for reason in reasons) or not validation["valid"]:
        state = "NO_REENTRY"
    elif choch and displacement and fvg:
        state = "REENTRY_VALID"
        reasons.extend(["new_entry_area_valid", "reentry_target_valid"])
    else:
        state = "REENTRY_CANDIDATE"
    return ReentryContext(original_signal_id, symbol, direction, original_entry, original_stop, stop_hit_price, stop_hit_time, current_price, state, reasons, vol, entry_area, stop, targets)


def _choch(df: pd.DataFrame | None, direction: str) -> bool:
    frame = _normalize(df)
    if len(frame) < 6:
        return False
    prev = frame.iloc[-6:-1]
    close = float(frame["c"].iloc[-1])
    return close < float(prev["l"].min()) if direction == "SELL" else close > float(prev["h"].max())


def _displacement(df: pd.DataFrame | None, direction: str) -> bool:
    frame = _normalize(df)
    if len(frame) < 5:
        return False
    bodies = (frame["c"].astype(float) - frame["o"].astype(float)).abs()
    avg = float(bodies.iloc[-5:-1].mean() or 0.01)
    for _, last in frame.tail(2).iterrows():
        body = abs(float(last["c"]) - float(last["o"]))
        if body >= avg * 1.2 and ((direction == "SELL" and float(last["c"]) < float(last["o"])) or (direction == "BUY" and float(last["c"]) > float(last["o"]))):
            return True
    return False


def _fvg(df: pd.DataFrame | None, direction: str) -> bool:
    frame = _normalize(df)
    if len(frame) < 3:
        return False
    a = frame.iloc[-3]
    c = frame.iloc[-1]
    return float(c["h"]) < float(a["l"]) if direction == "SELL" else float(c["l"]) > float(a["h"])


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy().rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"})
    if {"o", "h", "l", "c"}.issubset(out.columns):
        return out
    return pd.DataFrame()


__all__ = ["ReentryContext", "evaluate_reentry"]
