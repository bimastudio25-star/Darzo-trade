from __future__ import annotations


def smt_divergence(primary: list[float], correlated: list[float]) -> bool:
    return detect_smt_divergence(primary, correlated)["state"] != "neutral"


def detect_smt_divergence(primary: list[float], correlated: list[float], pair: str = "DXY_XAUUSD") -> dict:
    if len(primary) < 2 or len(correlated) < 2:
        return {"state": "neutral", "confidence_delta": 0.0, "reason": "insufficient_data", "pair": pair}
    p_delta = primary[-1] - primary[-2]
    c_delta = correlated[-1] - correlated[-2]
    if p_delta > 0 and c_delta > 0:
        return {"state": "bearish", "confidence_delta": -0.05, "reason": "positive_correlation_conflict", "pair": pair}
    if p_delta > 0 and c_delta < 0:
        return {"state": "bullish", "confidence_delta": 0.05, "reason": "inverse_divergence", "pair": pair}
    if p_delta < 0 and c_delta > 0:
        return {"state": "bearish", "confidence_delta": 0.05, "reason": "inverse_divergence", "pair": pair}
    return {"state": "neutral", "confidence_delta": 0.0, "reason": "no_divergence", "pair": pair}
