def imbalance_state(metrics: dict) -> dict:
    value = float(metrics.get("book_imbalance", 0))
    if value > 0.25:
        return {"state": "bid_heavy", "confidence_delta": 0.02}
    if value < -0.25:
        return {"state": "ask_heavy", "confidence_delta": 0.02}
    return {"state": "balanced", "confidence_delta": 0.0}
