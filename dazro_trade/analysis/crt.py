from __future__ import annotations


def _rr(entry: float, sl: float, tp: float, direction: str) -> float:
    risk = entry - sl if direction == "BUY" else sl - entry
    reward = tp - entry if direction == "BUY" else entry - tp
    return reward / risk if risk > 0 else -1


def detect_crt(candles: list[dict], htf_context: str | None = "known", min_rr: float = 2.0):
    if len(candles) < 3:
        return None
    ref, sweep, curr = candles[-3], candles[-2], candles[-1]
    ref_high, ref_low = float(ref["h"]), float(ref["l"])
    sweep_high, sweep_low = float(sweep["h"]), float(sweep["l"])
    curr_close = float(curr["c"])
    curr_open = float(curr.get("o", curr_close))
    rejection_reasons: list[str] = []
    if not htf_context:
        rejection_reasons.append("no_htf_context")

    if sweep_high > ref_high and curr_close < ref_high:
        direction = "SELL"
        entry = curr_close
        sl = sweep_high
        tp = ref_low
        rr = _rr(entry, sl, tp, direction)
        if curr_close >= curr_open:
            rejection_reasons.append("no_bearish_confirmation")
        if rr < min_rr:
            rejection_reasons.append("poor_rr")
        return {
            "type": "bearish_crt",
            "direction": direction,
            "range_high": ref_high,
            "range_low": ref_low,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "rr": rr,
            "confirmed": not rejection_reasons,
            "rejection_reasons": rejection_reasons,
        }

    if sweep_low < ref_low and curr_close > ref_low:
        direction = "BUY"
        entry = curr_close
        sl = sweep_low
        tp = ref_high
        rr = _rr(entry, sl, tp, direction)
        if curr_close <= curr_open:
            rejection_reasons.append("no_bullish_confirmation")
        if rr < min_rr:
            rejection_reasons.append("poor_rr")
        return {
            "type": "bullish_crt",
            "direction": direction,
            "range_high": ref_high,
            "range_low": ref_low,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "rr": rr,
            "confirmed": not rejection_reasons,
            "rejection_reasons": rejection_reasons,
        }
    return None
