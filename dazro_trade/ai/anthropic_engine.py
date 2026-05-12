from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from dazro_trade.ai.schemas import AIValidationResponse, parse_ai_validation
from dazro_trade.core.config import Settings
from dazro_trade.core.context import SignalContext

log = logging.getLogger(__name__)


class AnthropicEngine:
    def __init__(self, settings: Settings, client: Any | None = None):
        self.settings = settings
        self.client = client

    @property
    def available(self) -> bool:
        return bool(self.settings.anthropic_api_key or self.client)

    def review(self, context: SignalContext, task: str = "deep_validation") -> AIValidationResponse:
        if not context.has_deterministic_candidate:
            return AIValidationResponse(
                signal=False,
                direction="NONE",
                confidence=0.0,
                reasoning="No deterministic candidate was supplied for AI review.",
                rejection_reason="missing_deterministic_candidate",
            )
        if not self.available:
            return AIValidationResponse(
                signal=False,
                direction="NONE",
                confidence=0.0,
                reasoning="Anthropic provider unavailable because ANTHROPIC_API_KEY is missing.",
                rejection_reason="anthropic_unavailable",
            )
        raw = self._request_json(context, task)
        try:
            parsed = parse_ai_validation(raw)
        except (ValidationError, ValueError, TypeError) as exc:
            log.warning("Invalid Anthropic AIValidationResponse raw=%s error=%s", raw, exc)
            return AIValidationResponse(
                signal=False,
                direction="NONE",
                confidence=0.0,
                reasoning="Anthropic response failed schema validation.",
                rejection_reason="invalid_ai_output",
            )
        if parsed.signal and parsed.direction != context.candidate_direction:
            return AIValidationResponse(
                signal=False,
                direction="NONE",
                confidence=0.0,
                reasoning="AI response conflicted with deterministic direction.",
                rejection_reason="ai_direction_conflict",
            )
        return parsed

    def _request_json(self, context: SignalContext, task: str) -> str:
        client = self.client
        if client is None:
            import anthropic  # type: ignore

            client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
            self.client = client
        model = self.settings.anthropic_fast_model if task == "fast_filter" else self.settings.anthropic_deep_model
        message = client.messages.create(
            model=model,
            max_tokens=800,
            temperature=0,
            messages=[{"role": "user", "content": json.dumps({"task": task, "context": context.to_safe_dict()})}],
        )
        block = message.content[0]
        return getattr(block, "text", str(block))
