def absorption_heuristic(metrics: dict) -> dict:
    imbalance = float(metrics.get("book_imbalance", 0))
    if imbalance > 0.35:
        return {"state": "possible_seller_absorption", "confidence_delta": 0.02}
    if imbalance < -0.35:
        return {"state": "possible_buyer_absorption", "confidence_delta": 0.02}
    return {"state": "none", "confidence_delta": 0.0}
