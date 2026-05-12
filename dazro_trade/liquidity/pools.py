from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiquidityPool:
    kind: str
    level: float
    confidence: str = "inferred"
    notes: str = "Probable liquidity zone inferred from price data; true institutional liquidity is not visible on XAUUSD spot/CFD."


def equal_highs_lows(levels: list[float], tolerance: float):
    out = []
    for i in range(len(levels) - 1):
        for j in range(i + 1, len(levels)):
            if abs(levels[i] - levels[j]) <= tolerance:
                out.append((levels[i], levels[j]))
    return out


def detect_equal_highs(candles: list[dict], tolerance: float = 0.1) -> list[LiquidityPool]:
    highs = [float(c["h"]) for c in candles if "h" in c]
    pairs = equal_highs_lows(highs, tolerance)
    return [LiquidityPool("equal_highs", round(sum(pair) / 2, 5)) for pair in pairs]


def detect_equal_lows(candles: list[dict], tolerance: float = 0.1) -> list[LiquidityPool]:
    lows = [float(c["l"]) for c in candles if "l" in c]
    pairs = equal_highs_lows(lows, tolerance)
    return [LiquidityPool("equal_lows", round(sum(pair) / 2, 5)) for pair in pairs]


def period_extremes(candles: list[dict], kind: str) -> list[LiquidityPool]:
    if not candles:
        return []
    high = max(float(c["h"]) for c in candles)
    low = min(float(c["l"]) for c in candles)
    return [LiquidityPool(f"{kind}_high", high), LiquidityPool(f"{kind}_low", low)]


def range_extremes(candles: list[dict]) -> list[LiquidityPool]:
    return period_extremes(candles, "range")


def infer_liquidity_pools(candles: list[dict], tolerance: float = 0.1) -> list[LiquidityPool]:
    return detect_equal_highs(candles, tolerance) + detect_equal_lows(candles, tolerance) + range_extremes(candles)
