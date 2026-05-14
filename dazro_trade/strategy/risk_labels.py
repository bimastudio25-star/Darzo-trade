from __future__ import annotations

from typing import Literal

RiskLabel = Literal["tight_scalp", "normal_scalp", "wide_scalp", "extended_risk"]

TIGHT_SCALP_MAX_USD = 3.0
NORMAL_SCALP_MAX_USD = 5.0
WIDE_SCALP_MAX_USD = 10.0


def classify_sl_risk(sl_distance_usd: float) -> RiskLabel:
    distance = abs(float(sl_distance_usd))
    if distance <= TIGHT_SCALP_MAX_USD:
        return "tight_scalp"
    if distance <= NORMAL_SCALP_MAX_USD:
        return "normal_scalp"
    if distance <= WIDE_SCALP_MAX_USD:
        return "wide_scalp"
    return "extended_risk"


def risk_label_warning(label: RiskLabel) -> str | None:
    if label == "extended_risk":
        return "extended_risk: SL > 10 USD — risk warning, not auto-rejected"
    return None


__all__ = ["RiskLabel", "classify_sl_risk", "risk_label_warning",
           "TIGHT_SCALP_MAX_USD", "NORMAL_SCALP_MAX_USD", "WIDE_SCALP_MAX_USD"]
