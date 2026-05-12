def choch(prev_bias: str, new_bias: str) -> bool:
    return prev_bias != new_bias and prev_bias in {"bullish", "bearish"} and new_bias in {"bullish", "bearish"}


def detect_choch(closes: list[float], prior_swing_high: float, prior_swing_low: float, prev_bias: str) -> dict:
    if not closes:
        return {"choch": False, "new_bias": prev_bias, "reason": "insufficient_closes"}
    last = closes[-1]
    if prev_bias == "bearish" and last > prior_swing_high:
        return {"choch": True, "new_bias": "bullish", "reason": "close_above_prior_swing_high"}
    if prev_bias == "bullish" and last < prior_swing_low:
        return {"choch": True, "new_bias": "bearish", "reason": "close_below_prior_swing_low"}
    return {"choch": False, "new_bias": prev_bias, "reason": "no_close_based_character_change"}
