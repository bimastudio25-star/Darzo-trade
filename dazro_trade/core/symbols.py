from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    pip_size: float
    point_size: float
    digits: int
    min_tick: float

    def pips_to_price(self, pips: float) -> float:
        return float(pips) * self.pip_size

    def price_to_pips(self, distance: float) -> float:
        return float(distance) / self.pip_size if self.pip_size else 0.0

    def normalize_price(self, price: float) -> float:
        return round(float(price), self.digits)


DEFAULT_SYMBOL_SPECS = {
    "XAUUSD": SymbolSpec("XAUUSD", pip_size=0.01, point_size=0.01, digits=2, min_tick=0.01),
}


def get_symbol_spec(symbol: str) -> SymbolSpec:
    normalized = symbol.upper().replace(".", "").replace("M", "")
    if normalized.startswith("XAUUSD") or normalized.startswith("GOLD"):
        return DEFAULT_SYMBOL_SPECS["XAUUSD"]
    return SymbolSpec(symbol.upper(), pip_size=0.0001, point_size=0.00001, digits=5, min_tick=0.00001)


def pips_to_price(symbol: str, pips: float) -> float:
    return get_symbol_spec(symbol).pips_to_price(pips)


def price_to_pips(symbol: str, distance: float) -> float:
    return get_symbol_spec(symbol).price_to_pips(distance)


def normalize_price(symbol: str, price: float) -> float:
    return get_symbol_spec(symbol).normalize_price(price)


__all__ = ["SymbolSpec", "get_symbol_spec", "normalize_price", "pips_to_price", "price_to_pips"]
