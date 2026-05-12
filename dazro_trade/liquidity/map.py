from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from dazro_trade.core.symbols import price_to_pips

PoolSide = Literal["buy_side", "sell_side"]
SweepStatus = Literal["untouched", "approaching", "sweeping_intrabar", "swept_confirmed", "accepted_breakout", "failed_sweep"]


@dataclass
class LiquidityPool:
    id: str
    symbol: str
    timeframe: str
    level: float
    side: PoolSide
    pool_type: str
    distance_pips: float
    distance_points: float
    swept: bool = False
    sweep_status: SweepStatus = "untouched"
    strength_score: int = 0
    confluences: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def distance_band(self) -> str:
        if self.distance_pips < 80:
            return "under_80_pips"
        if self.distance_pips < 250:
            return "reaction_80_250_pips"
        if self.distance_pips < 500:
            return "reaction_250_500_pips"
        return "remote_500_plus_pips"


def build_liquidity_map(
    frames: dict[str, pd.DataFrame],
    *,
    symbol: str,
    current_price: float,
    session_ranges: dict[str, tuple[float, float]] | None = None,
    qb_levels: list[float] | None = None,
) -> list[LiquidityPool]:
    pools: list[LiquidityPool] = []
    for timeframe in ("D1", "H4", "H1", "M15", "M5", "M1"):
        df = _normalize(frames.get(timeframe))
        if df.empty:
            continue
        pools.extend(_range_pools(symbol, timeframe, df, current_price))
        pools.extend(_swing_pools(symbol, timeframe, df, current_price))
        pools.extend(_equal_high_low_pools(symbol, timeframe, df, current_price))
    pools.extend(_previous_day_pools(symbol, _normalize(frames.get("D1")), current_price))
    for session_name, levels in (session_ranges or {}).items():
        high, low = levels
        pools.append(_make_pool(symbol, session_name, high, "buy_side", "session_high", current_price, 65, ["session_range"]))
        pools.append(_make_pool(symbol, session_name, low, "sell_side", "session_low", current_price, 65, ["session_range"]))
    for idx, level in enumerate(qb_levels or []):
        pools.append(_make_pool(symbol, "QB", level, "buy_side" if level >= current_price else "sell_side", "quarterly_block_boundary", current_price, 60, ["QB"]))
    deduped: dict[str, LiquidityPool] = {}
    for pool in pools:
        key = f"{pool.symbol}:{pool.timeframe}:{pool.pool_type}:{pool.side}:{round(pool.level, 2)}"
        existing = deduped.get(key)
        if existing is None or pool.strength_score > existing.strength_score:
            deduped[key] = pool
    return sorted(deduped.values(), key=lambda pool: (pool.distance_pips, -pool.strength_score))


def classify_distance_pips(distance_pips: float) -> str:
    if distance_pips < 80:
        return "under_80_pips"
    if distance_pips < 250:
        return "reaction_80_250_pips"
    if distance_pips < 500:
        return "reaction_250_500_pips"
    return "remote_500_plus_pips"


def important_reaction_pools(pools: list[LiquidityPool], min_pips: float = 80.0, max_pips: float = 500.0) -> list[LiquidityPool]:
    return [pool for pool in pools if min_pips <= pool.distance_pips <= max_pips]


def _range_pools(symbol: str, timeframe: str, df: pd.DataFrame, current_price: float) -> list[LiquidityPool]:
    recent = df.tail(_lookback(timeframe))
    high = float(recent["h"].max())
    low = float(recent["l"].min())
    return [
        _make_pool(symbol, timeframe, high, "buy_side", "external_high" if timeframe in {"D1", "H4", "H1", "M15"} else "internal_high", current_price, 70, [timeframe]),
        _make_pool(symbol, timeframe, low, "sell_side", "external_low" if timeframe in {"D1", "H4", "H1", "M15"} else "internal_low", current_price, 70, [timeframe]),
    ]


def _previous_day_pools(symbol: str, df: pd.DataFrame, current_price: float) -> list[LiquidityPool]:
    if df.empty or len(df) < 2:
        return []
    previous = df.iloc[-2]
    return [
        _make_pool(symbol, "D1", float(previous["h"]), "buy_side", "previous_day_high", current_price, 85, ["PDH"]),
        _make_pool(symbol, "D1", float(previous["l"]), "sell_side", "previous_day_low", current_price, 85, ["PDL"]),
    ]


def _swing_pools(symbol: str, timeframe: str, df: pd.DataFrame, current_price: float) -> list[LiquidityPool]:
    pools: list[LiquidityPool] = []
    if len(df) < 5:
        return pools
    lookback = df.tail(min(len(df), _lookback(timeframe)))
    for i in range(2, len(lookback) - 2):
        row = lookback.iloc[i]
        prev_next = lookback.iloc[i - 2 : i + 3]
        if float(row["h"]) == float(prev_next["h"].max()):
            pools.append(_make_pool(symbol, timeframe, float(row["h"]), "buy_side", "internal_high", current_price, 45, ["swing_high"]))
        if float(row["l"]) == float(prev_next["l"].min()):
            pools.append(_make_pool(symbol, timeframe, float(row["l"]), "sell_side", "internal_low", current_price, 45, ["swing_low"]))
    return pools[-12:]


def _equal_high_low_pools(symbol: str, timeframe: str, df: pd.DataFrame, current_price: float, tolerance: float = 0.08) -> list[LiquidityPool]:
    pools: list[LiquidityPool] = []
    recent = df.tail(min(len(df), 80))
    highs = recent["h"].astype(float).tolist()
    lows = recent["l"].astype(float).tolist()
    for values, side, pool_type in ((highs, "buy_side", "equal_highs"), (lows, "sell_side", "equal_lows")):
        for i in range(len(values) - 1):
            if abs(values[i] - values[i + 1]) <= tolerance:
                pools.append(_make_pool(symbol, timeframe, (values[i] + values[i + 1]) / 2, side, pool_type, current_price, 60, [pool_type]))
    return pools[-6:]


def _make_pool(
    symbol: str,
    timeframe: str,
    level: float,
    side: PoolSide,
    pool_type: str,
    current_price: float,
    strength_score: int,
    confluences: list[str] | None = None,
) -> LiquidityPool:
    distance_points = abs(float(level) - float(current_price))
    distance_pips = round(price_to_pips(symbol, distance_points), 1)
    return LiquidityPool(
        id=f"{symbol}_{timeframe}_{pool_type}_{round(level, 2)}".replace(".", "_"),
        symbol=symbol,
        timeframe=timeframe,
        level=round(float(level), 2),
        side=side,
        pool_type=pool_type,
        distance_pips=distance_pips,
        distance_points=round(distance_points, 2),
        strength_score=strength_score,
        confluences=confluences or [],
        metadata={"distance_band": classify_distance_pips(distance_pips)},
    )


def _lookback(timeframe: str) -> int:
    return {"D1": 30, "H4": 80, "H1": 120, "M15": 120, "M5": 120, "M1": 180}.get(timeframe, 80)


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy().rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"})
    if {"o", "h", "l", "c"}.issubset(out.columns):
        return out
    return pd.DataFrame()


__all__ = ["LiquidityPool", "build_liquidity_map", "classify_distance_pips", "important_reaction_pools"]
