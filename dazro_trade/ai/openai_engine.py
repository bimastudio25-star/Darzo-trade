from __future__ import annotations

import json
import logging
import time
from typing import Any

from pydantic import ValidationError

from dazro_trade.ai.schemas import AIValidationResponse, parse_ai_validation
from dazro_trade.core.config import Settings
from dazro_trade.core.context import SignalContext

log = logging.getLogger(__name__)


class OpenAIEngine:
    def __init__(self, settings: Settings, client: Any | None = None, timeout_seconds: float = 20.0, max_retries: int = 2):
        self.settings = settings
        self.client = client
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    @property
    def available(self) -> bool:
        return bool(self.settings.openai_api_key or self.client)

    def review(self, context: SignalContext, task: str = "audit") -> AIValidationResponse:
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
                reasoning="OpenAI provider unavailable because OPENAI_API_KEY is missing.",
                rejection_reason="openai_unavailable",
            )

        payload = {
            "task": task,
            "rules": [
                "Review only the supplied deterministic candidate.",
                "Do not invent new entries, stops, targets, or directions.",
                "Reject if context is weak, contradictory, or risk notes are concerning.",
                "Return only JSON matching the requested schema.",
            ],
            "schema": AIValidationResponse.model_json_schema()
            if hasattr(AIValidationResponse, "model_json_schema")
            else AIValidationResponse.schema(),
            "context": context.to_safe_dict(),
        }
        raw = self._request_json(payload)
        try:
            parsed = parse_ai_validation(raw)
        except (ValidationError, ValueError, TypeError) as exc:
            log.warning("Invalid OpenAI AIValidationResponse raw=%s error=%s", raw, exc)
            return AIValidationResponse(
                signal=False,
                direction="NONE",
                confidence=0.0,
                reasoning="OpenAI response failed schema validation.",
                rejection_reason="invalid_ai_output",
            )
        if parsed.signal and parsed.direction != context.candidate_direction:
            log.warning("OpenAI tried to change direction raw=%s", raw)
            return AIValidationResponse(
                signal=False,
                direction="NONE",
                confidence=0.0,
                reasoning="AI response conflicted with deterministic direction.",
                rejection_reason="ai_direction_conflict",
            )
        return parsed

    def _request_json(self, payload: dict[str, Any]) -> str:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                client = self._client()
                if hasattr(client, "responses"):
                    response = client.responses.create(
                        model=self.settings.openai_audit_model or self.settings.openai_model,
                        input=json.dumps(payload),
                        timeout=self.timeout_seconds,
                    )
                    return getattr(response, "output_text", "") or self._extract_response_text(response)
                response = client.chat.completions.create(
                    model=self.settings.openai_audit_model or self.settings.openai_model,
                    messages=[{"role": "user", "content": json.dumps(payload)}],
                    temperature=0,
                    timeout=self.timeout_seconds,
                )
                return response.choices[0].message.content
            except Exception as exc:  # pragma: no cover - concrete SDK failures are mocked in tests
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(0.25 * (attempt + 1))
        raise RuntimeError(f"OpenAI request failed after retries: {last_error}")

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        from openai import OpenAI  # type: ignore

        self.client = OpenAI(api_key=self.settings.openai_api_key, timeout=self.timeout_seconds)
        return self.client

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        try:
            return response.output[0].content[0].text
        except Exception:
            return str(response)
