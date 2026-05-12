from __future__ import annotations


def detect_turtle_soup(candles: list[dict], lookback: int = 5, min_rr: float = 2.0) -> dict:
    if len(candles) < lookback + 1:
        return {"type": "none", "confirmed": False, "rejection_reasons": ["insufficient_data"]}
    prior = candles[-lookback - 1 : -1]
    last = candles[-1]
    prior_high = max(float(c["h"]) for c in prior)
    prior_low = min(float(c["l"]) for c in prior)
    high, low, close = float(last["h"]), float(last["l"]), float(last["c"])
    open_ = float(last.get("o", close))

    if high > prior_high and close < prior_high:
        entry, sl, tp = close, high, prior_low
        risk, reward = sl - entry, entry - tp
        rr = reward / risk if risk > 0 else -1
        reasons = []
        if close >= open_:
            reasons.append("no_bearish_confirmation")
        if rr < min_rr:
            reasons.append("poor_rr")
        return {"type": "bearish_turtle_soup", "direction": "SELL", "entry": entry, "sl": sl, "tp": tp, "rr": rr, "confirmed": not reasons, "rejection_reasons": reasons}

    if low < prior_low and close > prior_low:
        entry, sl, tp = close, low, prior_high
        risk, reward = entry - sl, tp - entry
        rr = reward / risk if risk > 0 else -1
        reasons = []
        if close <= open_:
            reasons.append("no_bullish_confirmation")
        if rr < min_rr:
            reasons.append("poor_rr")
        return {"type": "bullish_turtle_soup", "direction": "BUY", "entry": entry, "sl": sl, "tp": tp, "rr": rr, "confirmed": not reasons, "rejection_reasons": reasons}

    return {"type": "none", "confirmed": False, "rejection_reasons": ["no_sweep_reentry"]}
