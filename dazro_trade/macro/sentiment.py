def classify_sentiment(items: list[dict] | None) -> dict:
    if not items:
        return {"state": "uncertain", "confidence": 0.0, "reason": "no_macro_items"}
    score = 0
    for item in items:
        tone = str(item.get("tone", "")).lower()
        if tone in {"bullish_gold", "usd_bearish", "risk_off"}:
            score += 1
        elif tone in {"bearish_gold", "usd_bullish", "risk_on"}:
            score -= 1
    if score > 1:
        return {"state": "bullish", "confidence": min(0.6, score / 10), "reason": "macro_inputs_tilt_bullish"}
    if score < -1:
        return {"state": "bearish", "confidence": min(0.6, abs(score) / 10), "reason": "macro_inputs_tilt_bearish"}
    return {"state": "neutral", "confidence": 0.1, "reason": "mixed_macro_inputs"}
