from __future__ import annotations

from dataclasses import replace

from dazro_trade.ai.anthropic_engine import AnthropicEngine
from dazro_trade.ai.openai_engine import OpenAIEngine
from dazro_trade.ai.router import AIRouter
from dazro_trade.ai.schemas import AIValidationResponse, parse_ai_validation
from dazro_trade.core.config import Settings
from dazro_trade.core.context import SignalContext


def candidate_context() -> SignalContext:
    return SignalContext(
        symbol="XAUUSD",
        current_price=2300,
        spread=10,
        session="london",
        candidate_direction="BUY",
        candidate_entry=2300,
        candidate_sl=2290,
        candidate_tp=2325,
        deterministic_reason_codes=["crt_confirmed"],
    )


def test_config_demo_requires_mt5_credentials():
    settings = Settings(demo_execution=True, paper_mode=True)
    validation = settings.validate_runtime()
    assert any("MT5" in err for err in validation.errors)


def test_config_ai_disabled_requires_no_keys():
    settings = Settings(ai_enabled=False, telegram_enabled=False)
    assert settings.validate_runtime().errors == []


def test_ai_schema_validation_accepts_required_shape():
    raw = '{"signal": true, "direction": "BUY", "confidence": 0.7, "reasoning": "context aligns"}'
    parsed = parse_ai_validation(raw)
    assert isinstance(parsed, AIValidationResponse)
    assert parsed.direction == "BUY"


class FakeResponses:
    def create(self, **kwargs):
        class Response:
            output_text = '{"signal": true, "direction": "BUY", "confidence": 0.6, "reasoning": "audit ok"}'

        return Response()


class FakeOpenAIClient:
    responses = FakeResponses()


def test_openai_engine_mocked_review():
    engine = OpenAIEngine(Settings(openai_api_key="test"), client=FakeOpenAIClient())
    result = engine.review(candidate_context())
    assert result.signal is True
    assert result.direction == "BUY"


def test_openai_engine_rejects_invalid_output():
    class BadResponses:
        def create(self, **kwargs):
            class Response:
                output_text = "not json"

            return Response()

    class BadClient:
        responses = BadResponses()

    engine = OpenAIEngine(Settings(openai_api_key="test"), client=BadClient())
    result = engine.review(candidate_context())
    assert result.signal is False
    assert result.rejection_reason == "invalid_ai_output"


def test_anthropic_engine_mocked_review():
    class MsgClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                class Block:
                    text = '{"signal": true, "direction": "BUY", "confidence": 0.65, "reasoning": "deep ok"}'

                class Message:
                    content = [Block()]

                return Message()

    engine = AnthropicEngine(Settings(anthropic_api_key="test"), client=MsgClient())
    result = engine.review(candidate_context())
    assert result.signal is True


def test_ai_router_missing_required_provider_rejects():
    settings = Settings(ai_enabled=True, ai_deep_provider="openai", openai_api_key="")
    result = AIRouter(settings).deep_validation(candidate_context(), required=True)
    assert result.signal is False
    assert result.rejection_reason == "openai_required_missing_key"


def test_ai_router_none_provider_passes_to_deterministic_gates():
    settings = replace(Settings(ai_enabled=True), ai_fast_provider="none")
    result = AIRouter(settings).fast_filter(candidate_context())
    assert result.signal is True
    assert result.direction == "BUY"
