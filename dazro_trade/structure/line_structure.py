from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StructureState = Literal["bullish", "bearish", "range", "unknown"]


@dataclass(frozen=True)
class StructureEvent:
    state: str
    level: float | None = None
    accepted: bool = False
    reason: str = ""


def close_based_bos(closes: list[float], level: float, direction: str) -> bool:
    if not closes:
        return False
    last_close = closes[-1]
    if direction in {"bullish", "BUY"}:
        return last_close > level
    if direction in {"bearish", "SELL"}:
        return last_close < level
    return False


def accepted_breakout(closes: list[float], level: float, direction: str, min_closes: int = 1) -> StructureEvent:
    if len(closes) < min_closes:
        return StructureEvent("unknown", level, False, "insufficient_closes")
    recent = closes[-min_closes:]
    if direction in {"bullish", "BUY"}:
        ok = all(close > level for close in recent)
        return StructureEvent("accepted_breakout" if ok else "failed_breakout", level, ok, "close_above_level" if ok else "no_close_acceptance")
    ok = all(close < level for close in recent)
    return StructureEvent("accepted_breakout" if ok else "failed_breakout", level, ok, "close_below_level" if ok else "no_close_acceptance")


def reclaimed_structure(closes: list[float], level: float, direction: str) -> StructureEvent:
    if len(closes) < 2:
        return StructureEvent("unknown", level, False, "insufficient_closes")
    prev, last = closes[-2], closes[-1]
    if direction in {"bullish", "BUY"} and prev < level < last:
        return StructureEvent("reclaimed_structure", level, True, "bullish_reclaim")
    if direction in {"bearish", "SELL"} and prev > level > last:
        return StructureEvent("reclaimed_structure", level, True, "bearish_reclaim")
    return StructureEvent("no_reclaim", level, False, "level_not_reclaimed")


def structure_retest(closes: list[float], level: float, tolerance: float) -> StructureEvent:
    if not closes:
        return StructureEvent("unknown", level, False, "insufficient_closes")
    if abs(closes[-1] - level) <= tolerance:
        return StructureEvent("structure_retest", level, True, "close_retested_level")
    return StructureEvent("no_retest", level, False, "close_not_near_level")


def infer_structure(closes: list[float], lookback: int = 5) -> StructureState:
    if len(closes) < max(3, lookback):
        return "unknown"
    window = closes[-lookback:]
    if window[-1] > max(window[:-1]):
        return "bullish"
    if window[-1] < min(window[:-1]):
        return "bearish"
    return "range"


def choch(prev_bias: str, new_bias: str) -> bool:
    return prev_bias != new_bias and prev_bias in {"bullish", "bearish"} and new_bias in {"bullish", "bearish"}
