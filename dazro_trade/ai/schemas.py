from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AIValidationResponse(BaseModel):
    signal: bool
    direction: Literal["BUY", "SELL", "NONE"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    rejection_reason: str | None = None
    risk_notes: str | None = None
    macro_notes: str | None = None


class AIReviewRequest(BaseModel):
    task: Literal["fast_filter", "deep_validation", "audit"]
    context: dict


def parse_ai_validation(raw: str) -> AIValidationResponse:
    if hasattr(AIValidationResponse, "model_validate_json"):
        return AIValidationResponse.model_validate_json(raw)  # type: ignore[attr-defined]
    return AIValidationResponse.parse_raw(raw)
