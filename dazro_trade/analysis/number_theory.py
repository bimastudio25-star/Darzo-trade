from __future__ import annotations

from dataclasses import dataclass

from dazro_trade.core.symbols import price_to_pips


@dataclass(frozen=True)
class NumberTheoryLevel:
    level: float
    kind: str
    distance_pips: float


def nearest_number_theory_levels(price: float, *, symbol: str = "XAUUSD", radius: float = 15.0) -> list[NumberTheoryLevel]:
    start = int((price - radius) // 1)
    end = int((price + radius) // 1) + 1
    levels: dict[float, str] = {}
    for whole in range(start, end + 1):
        if whole % 10 == 0:
            levels[float(whole)] = "round_number"
        if whole % 5 == 0:
            levels[float(whole)] = "half_handle"
        levels[whole + 2.5] = "quarter_level"
        levels[whole + 7.5] = "quarter_level"
        levels[whole + 0.5] = "micro_handle"
    return sorted(
        [
            NumberTheoryLevel(round(level, 2), kind, round(price_to_pips(symbol, abs(level - price)), 1))
            for level, kind in levels.items()
            if abs(level - price) <= radius
        ],
        key=lambda item: item.distance_pips,
    )[:12]


def has_number_theory_confluence(
    level: float,
    *,
    symbol: str = "XAUUSD",
    tolerance_pips: float = 1.2,
    strict_pips: float = 0.8,
) -> dict:
    nearby = nearest_number_theory_levels(level, symbol=symbol, radius=10.0)
    if not nearby:
        return {"confluence": False, "tier": "none", "nearest": None, "reason": "no_number_level_nearby"}
    best = nearby[0]
    if best.distance_pips <= strict_pips:
        tier = "strict"
    elif best.distance_pips <= tolerance_pips:
        tier = "loose"
    else:
        tier = "none"
    return {
        "confluence": tier in {"strict", "loose"},
        "tier": tier,
        "nearest": {"level": best.level, "kind": best.kind, "distance_pips": best.distance_pips},
        "reason": f"near_{best.kind}" if tier in {"strict", "loose"} else "number_level_too_far",
    }


__all__ = ["NumberTheoryLevel", "has_number_theory_confluence", "nearest_number_theory_levels"]
