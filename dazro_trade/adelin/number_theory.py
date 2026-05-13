from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor
from typing import Any

from dazro_trade.core.symbols import get_symbol_spec


@dataclass(frozen=True)
class NumberTheoryLevel:
    level: float
    kind: str
    weight: int
    distance_pips: float

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "kind": self.kind, "weight": self.weight, "distance_pips": self.distance_pips}


def _pip(pip: float | None = None) -> float:
    return float(pip if pip is not None else get_symbol_spec("XAUUSD").pip_size)


def _level_kind(value: float) -> tuple[str, int]:
    cents = round((value - floor(value)) * 100)
    if cents == 0:
        return "integer", 3
    if cents == 50:
        return "half", 2
    return "quarter", 1


def get_number_theory_levels(price: float, lookback_range: float = 10.0, pip: float | None = None) -> list[dict[str, Any]]:
    pip_size = _pip(pip)
    start = floor((float(price) - float(lookback_range)) * 4) / 4
    end = ceil((float(price) + float(lookback_range)) * 4) / 4
    levels: list[NumberTheoryLevel] = []
    steps = int(round((end - start) / 0.25)) + 1
    for idx in range(steps):
        level = round(start + idx * 0.25, 2)
        cents = round((level - floor(level)) * 100)
        if cents not in {0, 25, 50, 75}:
            continue
        kind, weight = _level_kind(level)
        levels.append(NumberTheoryLevel(level, kind, weight, round(abs(level - price) / pip_size, 1)))
    return [level.to_dict() for level in sorted(levels, key=lambda item: (item.distance_pips, -item.weight))]


def nearest_number_theory(price: float, tolerance_pips: float = 15.0, pip: float | None = None) -> dict[str, Any]:
    pip_size = _pip(pip)
    levels = get_number_theory_levels(price, lookback_range=max(2.0, tolerance_pips * pip_size * 2), pip=pip_size)
    if not levels:
        return {"confluence": False, "nearest": None, "reason": "no_number_level_nearby"}
    nearest = levels[0]
    confluence = float(nearest["distance_pips"]) <= tolerance_pips
    return {
        "confluence": confluence,
        "nearest": nearest,
        "reason": f"near_{nearest['kind']}" if confluence else "number_level_too_far",
    }


def is_near_nt_level(price: float, tolerance_pips: float = 15.0, min_weight: int = 1, pip: float | None = None) -> bool:
    nearest = nearest_number_theory(price, tolerance_pips=tolerance_pips, pip=pip)
    level = nearest.get("nearest")
    return bool(nearest["confluence"] and level and int(level["weight"]) >= min_weight)


def score_number_theory_confluence(price: float, fvg_top: float, fvg_bot: float, pip: float | None = None) -> dict[str, Any]:
    low = min(float(fvg_top), float(fvg_bot))
    high = max(float(fvg_top), float(fvg_bot))
    levels = get_number_theory_levels((low + high) / 2, lookback_range=max(high - low, 1.0), pip=pip)
    inside = [level for level in levels if low <= float(level["level"]) <= high]
    nearest = nearest_number_theory(price, tolerance_pips=15.0, pip=pip)
    score = 0
    if inside:
        score += max(int(level["weight"]) for level in inside) * 10
    if nearest["confluence"]:
        score += int(nearest["nearest"]["weight"]) * 5
    return {
        "score": min(40, score),
        "inside_fvg": inside,
        "nearest": nearest.get("nearest"),
        "confluence": bool(inside and nearest["confluence"]),
        "reason": "number_theory_inside_fvg" if inside else "number_theory_not_inside_fvg",
    }


__all__ = [
    "NumberTheoryLevel",
    "get_number_theory_levels",
    "is_near_nt_level",
    "nearest_number_theory",
    "score_number_theory_confluence",
]
