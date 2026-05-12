from __future__ import annotations

from dazro_trade.ai.anthropic_engine import AnthropicEngine
from dazro_trade.ai.router import AIRouter
from dazro_trade.core.config import Settings
from dazro_trade.core.context import SignalContext


class AIEngine:
    """Compatibility wrapper for the legacy root import path.

    New code should use dazro_trade.ai.router.AIRouter directly. This wrapper
    never creates signals; it only reviews a supplied deterministic context.
    """

    def __init__(self, key: str = ""):
        self.settings = Settings(anthropic_api_key=key)
        self.router = AIRouter(self.settings, anthropic_engine=AnthropicEngine(self.settings))

    def call_haiku(self, data: dict) -> dict:
        return self._review_dict(data, "fast").__dict__

    def call_sonnet(self, data: dict) -> dict:
        return self._review_dict(data, "deep").__dict__

    def _review_dict(self, data: dict, route: str):
        context = SignalContext(
            symbol=data.get("symbol", "XAUUSD"),
            current_price=float(data.get("price", data.get("entry", 0)) or 0),
            spread=float(data.get("spread", 0) or 0),
            session=data.get("session", "unknown"),
            candidate_direction=data.get("direction", "NONE"),
            candidate_entry=data.get("entry"),
            candidate_sl=data.get("sl"),
            candidate_tp=data.get("tp", data.get("tp1")),
            deterministic_reason_codes=data.get("reason_codes", []),
            rejection_reasons=data.get("rejection_reasons", []),
        )
        if route == "fast":
            return self.router.fast_filter(context)
        return self.router.deep_validation(context)
