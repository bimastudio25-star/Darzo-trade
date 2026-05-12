from __future__ import annotations


def detect_msnr_retest(closes: list[float], breakout_level: float, direction: str, tolerance: float = 0.1) -> dict:
    if len(closes) < 3:
        return {"state": "unknown", "accepted": False, "reason": "insufficient_closes"}
    accepted = closes[-3] > breakout_level if direction in {"BUY", "bullish"} else closes[-3] < breakout_level
    retested = abs(closes[-2] - breakout_level) <= tolerance
    continued = closes[-1] > closes[-2] if direction in {"BUY", "bullish"} else closes[-1] < closes[-2]
    if accepted and retested and continued:
        return {"state": "msnr_retest", "accepted": True, "reason": "accepted_breakout_retest_continuation"}
    if retested and not continued:
        return {"state": "rejection_retest", "accepted": False, "reason": "retest_without_continuation"}
    if accepted and continued:
        return {"state": "continuation_retest", "accepted": True, "reason": "continuation_after_acceptance"}
    return {"state": "none", "accepted": False, "reason": "no_msnr_pattern"}
