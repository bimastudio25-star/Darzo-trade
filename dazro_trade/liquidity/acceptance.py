def acceptance_after_sweep(closes: list[float], level: float, direction: str, min_closes: int = 1) -> dict:
    if len(closes) < min_closes:
        return {"accepted": False, "reason": "insufficient_closes"}
    recent = closes[-min_closes:]
    if direction in {"BUY", "bullish"}:
        ok = all(close > level for close in recent)
    else:
        ok = all(close < level for close in recent)
    return {"accepted": ok, "reason": "close_acceptance_after_sweep" if ok else "no_acceptance_after_sweep"}
