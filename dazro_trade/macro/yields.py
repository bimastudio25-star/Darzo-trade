def classify_yields(yields: list[float]) -> dict:
    if len(yields) < 3:
        return {"state": "uncertain", "reason": "insufficient_yield_data"}
    if yields[-1] > max(yields[-3:-1]):
        return {"state": "bearish_gold", "reason": "yields_rising"}
    if yields[-1] < min(yields[-3:-1]):
        return {"state": "bullish_gold", "reason": "yields_falling"}
    return {"state": "neutral", "reason": "yields_range"}
