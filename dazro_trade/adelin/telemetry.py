from __future__ import annotations

from typing import Any

from dazro_trade.core.symbols import get_symbol_spec


def distance_to_liquidity_pips(
    *,
    symbol: str,
    current_price: float | None,
    liquidity_price: float | None,
    pip_size: float | None = None,
) -> float | None:
    if current_price is None or liquidity_price is None:
        return None
    pip = float(pip_size if pip_size is not None else get_symbol_spec(symbol).pip_size)
    if pip <= 0:
        return None
    return round(abs(float(current_price) - float(liquidity_price)) / pip, 1)


def distance_bucket(distance_pips: float | None) -> str:
    if distance_pips is None:
        return "UNKNOWN"
    value = float(distance_pips)
    if value < 10:
        return "0-10"
    if value < 20:
        return "10-20"
    if value < 40:
        return "20-40"
    if value < 80:
        return "40-80"
    if value < 150:
        return "80-150"
    return "150+"


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _liquidity_price(payload: dict[str, Any] | None) -> float | None:
    if not isinstance(payload, dict):
        return None
    return _as_float(payload.get("level") if payload.get("level") is not None else payload.get("price"))


def build_signal_telemetry(
    *,
    symbol: str,
    current_price: float | None,
    liquidity: dict[str, Any] | None,
    pip_size: float | None,
    score_detail: dict[str, Any] | None,
    continuation_candidate: bool | None = None,
) -> dict[str, Any]:
    liq_price = _liquidity_price(liquidity)
    components = dict((score_detail or {}).get("components") or {})
    hard_filters = dict((score_detail or {}).get("hard_filters") or {})
    reason_codes = sorted([key for key, value in {**components, **hard_filters}.items() if bool(value)])
    distance = distance_to_liquidity_pips(
        symbol=symbol,
        current_price=current_price,
        liquidity_price=liq_price,
        pip_size=pip_size,
    )
    return {
        "symbol": symbol,
        "current_price": current_price,
        "liquidity_price": liq_price,
        "liquidity_timeframe": (liquidity or {}).get("timeframe") if isinstance(liquidity, dict) else None,
        "liquidity_type": (liquidity or {}).get("kind") if isinstance(liquidity, dict) else None,
        "distance_to_liquidity_pips": distance,
        "distance_to_liquidity_bucket": distance_bucket(distance),
        "score_components": components,
        "score_reason_codes": reason_codes,
        "continuation_candidate": bool(continuation_candidate) if continuation_candidate is not None else None,
    }


__all__ = ["build_signal_telemetry", "distance_bucket", "distance_to_liquidity_pips"]
