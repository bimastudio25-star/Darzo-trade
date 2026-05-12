from __future__ import annotations

from dataclasses import dataclass

from dazro_trade.ai.anthropic_engine import AnthropicEngine
from dazro_trade.ai.openai_engine import OpenAIEngine
from dazro_trade.ai.schemas import AIValidationResponse
from dazro_trade.core.config import ProviderName, Settings
from dazro_trade.core.context import SignalContext


@dataclass
class AIRouter:
    settings: Settings
    openai_engine: OpenAIEngine | None = None
    anthropic_engine: AnthropicEngine | None = None

    def __post_init__(self) -> None:
        if self.openai_engine is None:
            self.openai_engine = OpenAIEngine(self.settings)
        if self.anthropic_engine is None:
            self.anthropic_engine = AnthropicEngine(self.settings)

    def fast_filter(self, context: SignalContext, required: bool = False) -> AIValidationResponse:
        return self._route(self.settings.ai_fast_provider, context, "fast_filter", required)

    def deep_validation(self, context: SignalContext, required: bool = True) -> AIValidationResponse:
        return self._route(self.settings.ai_deep_provider, context, "deep_validation", required)

    def audit(self, context: SignalContext, required: bool = False) -> AIValidationResponse:
        return self._route(self.settings.ai_audit_provider, context, "audit", required)

    def _route(self, provider: ProviderName, context: SignalContext, task: str, required: bool) -> AIValidationResponse:
        if not self.settings.ai_enabled or provider == "none":
            return AIValidationResponse(
                signal=True,
                direction=context.candidate_direction,
                confidence=0.5,
                reasoning="AI route disabled; deterministic and risk gates remain authoritative.",
            )
        engine = self.openai_engine if provider == "openai" else self.anthropic_engine
        assert engine is not None
        if not engine.available:
            return AIValidationResponse(
                signal=False,
                direction="NONE",
                confidence=0.0,
                reasoning=f"{provider} unavailable.",
                rejection_reason=f"{provider}_required_missing_key" if required else f"{provider}_optional_missing_key",
            )
        return engine.review(context, task=task)
