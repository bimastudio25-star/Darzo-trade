from __future__ import annotations


def detect_sweep(candle: dict, level: float, side: str) -> dict:
    high = float(candle.get("h", candle.get("high", 0)))
    low = float(candle.get("l", candle.get("low", 0)))
    close = float(candle.get("c", candle.get("close", 0)))
    if side in {"high", "buy_side", "bearish"} and high > level:
        confirmed = close < level
        return {"sweep": True, "side": "buy_side", "confirmed": confirmed, "failed": not confirmed, "level": level}
    if side in {"low", "sell_side", "bullish"} and low < level:
        confirmed = close > level
        return {"sweep": True, "side": "sell_side", "confirmed": confirmed, "failed": not confirmed, "level": level}
    return {"sweep": False, "side": side, "confirmed": False, "failed": False, "level": level}


def sweep_candidates(candles: list[dict], pools: list) -> list[dict]:
    if not candles:
        return []
    last = candles[-1]
    out = []
    for pool in pools:
        kind = getattr(pool, "kind", None)
        level = getattr(pool, "level", None)
        if isinstance(pool, dict):
            kind = pool.get("kind", kind)
            level = pool.get("level", level)
        if kind is None or level is None:
            continue
        if "high" in kind:
            out.append(detect_sweep(last, level, "high"))
        elif "low" in kind:
            out.append(detect_sweep(last, level, "low"))
    return [item for item in out if item["sweep"]]
