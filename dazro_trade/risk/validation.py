from __future__ import annotations

from dazro_trade.core.config import Settings


def calculate_rr(direction: str, entry: float, sl: float, tp: float) -> float:
    if direction == "BUY":
        risk = entry - sl
        reward = tp - entry
    elif direction == "SELL":
        risk = sl - entry
        reward = entry - tp
    else:
        return -1
    return reward / risk if risk > 0 else -1


def validate_trade(signal: dict, settings: Settings, spread: float = 0.0, session: str | None = None) -> dict:
    reasons: list[str] = []
    required = ["direction", "entry", "sl", "tp"]
    missing = [key for key in required if signal.get(key) in (None, "")]
    if missing:
        return {"accepted": False, "rejection_reasons": [f"missing_{key}" for key in missing], "rr": -1}
    direction = str(signal["direction"]).upper()
    entry = float(signal["entry"])
    sl = float(signal["sl"])
    tp = float(signal["tp"])
    if direction not in {"BUY", "SELL"}:
        reasons.append("invalid_direction")
    if direction == "BUY" and sl >= entry:
        reasons.append("impossible_sl_direction")
    if direction == "SELL" and sl <= entry:
        reasons.append("impossible_sl_direction")
    rr = calculate_rr(direction, entry, sl, tp)
    if rr <= 0:
        reasons.append("negative_or_invalid_rr")
    if rr < settings.min_rr:
        reasons.append("rr_below_minimum")
    if abs(tp - entry) <= spread:
        reasons.append("too_close_tp")
    if spread > settings.max_spread_pips:
        reasons.append("max_spread_exceeded")
    if session and session.lower() in {"dead", "closed", "illiquid"}:
        reasons.append("dead_session")
    return {"accepted": not reasons, "rejection_reasons": reasons, "rr": rr}
