from __future__ import annotations

from datetime import datetime


def classify_quarter(month: int) -> str:
    if month < 1 or month > 12:
        raise ValueError("month must be 1..12")
    return f"Q{((month - 1) // 3) + 1}"


def monthly_role(month: int) -> str:
    pos = (month - 1) % 3
    return ["quarter_open", "quarter_expansion", "quarter_delivery"][pos]


def quarterly_phase(date: datetime) -> dict:
    return {"quarter": classify_quarter(date.month), "month": date.month, "monthly_role": monthly_role(date.month)}


def quarterly_range(candles: list[dict]) -> dict:
    if not candles:
        return {"state": "neutral", "reason": "insufficient_data"}
    high = max(float(c["h"]) for c in candles)
    low = min(float(c["l"]) for c in candles)
    mid = (high + low) / 2
    return {"high": high, "low": low, "mid": mid, "state": "ready"}


def premium_discount(price: float, low: float, high: float) -> str:
    if high <= low:
        return "neutral"
    mid = (high + low) / 2
    if price > mid:
        return "premium"
    if price < mid:
        return "discount"
    return "neutral"


def directional_weight(price: float, low: float, high: float) -> dict:
    zone = premium_discount(price, low, high)
    if zone == "premium":
        return {"bias": "bearish", "confidence_delta": 0.05, "reason": "quarterly_premium"}
    if zone == "discount":
        return {"bias": "bullish", "confidence_delta": 0.05, "reason": "quarterly_discount"}
    return {"bias": "neutral", "confidence_delta": 0.0, "reason": "quarterly_neutral"}
