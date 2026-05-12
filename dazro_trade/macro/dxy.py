def classify_dxy(prices: list[float]) -> dict:
    if len(prices) < 3:
        return {"state": "uncertain", "reason": "insufficient_dxy_data"}
    if prices[-1] > max(prices[-3:-1]):
        return {"state": "bearish_gold", "reason": "dxy_strength"}
    if prices[-1] < min(prices[-3:-1]):
        return {"state": "bullish_gold", "reason": "dxy_weakness"}
    return {"state": "neutral", "reason": "dxy_range"}
