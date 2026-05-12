def rejection_after_sweep(candle: dict, level: float, direction: str) -> dict:
    close = float(candle.get("c", candle.get("close", 0)))
    if direction in {"SELL", "bearish"}:
        rejected = close < level
    else:
        rejected = close > level
    return {"rejected": rejected, "reason": "close_back_inside_range" if rejected else "no_reentry"}
