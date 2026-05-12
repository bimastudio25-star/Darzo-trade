from __future__ import annotations


def qb_proximity(price: float, qb_levels: list[float], tolerance: float = 1.0) -> dict:
    if not qb_levels:
        return {"state": "neutral", "nearest": None, "confidence_delta": 0.0, "reason": "insufficient_data"}
    nearest = min(qb_levels, key=lambda level: abs(price - level))
    distance = abs(price - nearest)
    if distance <= tolerance:
        return {"state": "near_qb", "nearest": nearest, "confidence_delta": 0.03, "reason": "qb_proximity"}
    return {"state": "neutral", "nearest": nearest, "confidence_delta": 0.0, "reason": "not_near_qb"}
