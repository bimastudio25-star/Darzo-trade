from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from dazro_trade.analysis.human_trade_management import (
    M5_CLOSE_QUALITIES,
    REACTION_STATES,
    RETEST_QUALITIES,
    RUNNER_OPPORTUNITIES,
)


SUGGESTED_ACTIONS = ("HOLD", "EXIT_EARLY", "MOVE_BE", "TAKE_PARTIAL", "WAIT_RETEST", "LET_RUN", "NO_TRADE")


@dataclass(frozen=True)
class LocalAIJudgeConfig:
    enabled: bool = False
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "qwen3:8b"
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "LocalAIJudgeConfig":
        return cls(
            enabled=str(os.getenv("DARZO_LOCAL_AI_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "y"},
            provider=os.getenv("DARZO_LOCAL_AI_PROVIDER", "ollama").strip() or "ollama",
            base_url=os.getenv("DARZO_LOCAL_AI_BASE_URL", "http://localhost:11434").rstrip("/"),
            model=os.getenv("DARZO_LOCAL_AI_MODEL", "qwen3:8b").strip() or "qwen3:8b",
            timeout_seconds=float(os.getenv("DARZO_LOCAL_AI_TIMEOUT_SECONDS", "30") or 30),
        )


@dataclass(frozen=True)
class LocalAIJudgeResult:
    enabled: bool
    status: str
    m5_close_quality: str | None = None
    reaction_state: str | None = None
    retest_quality: str | None = None
    runner_opportunity: str | None = None
    suggested_action: str | None = None
    confidence: float | None = None
    reason_codes: tuple[str, ...] = ()
    notes: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "status": self.status,
            "m5_close_quality": self.m5_close_quality,
            "reaction_state": self.reaction_state,
            "retest_quality": self.retest_quality,
            "runner_opportunity": self.runner_opportunity,
            "suggested_action": self.suggested_action,
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "notes": self.notes,
            "error": self.error,
        }


class LocalAITradeJudge:
    """Optional local AI classifier for report-only trade-management logs."""

    def __init__(self, config: LocalAIJudgeConfig | None = None):
        self.config = config or LocalAIJudgeConfig.from_env()

    def judge(self, payload: dict[str, Any]) -> LocalAIJudgeResult:
        if not self.config.enabled:
            return LocalAIJudgeResult(enabled=False, status="disabled")
        if self.config.provider != "ollama":
            return LocalAIJudgeResult(enabled=True, status="unsupported_provider", error=self.config.provider)
        prompt = build_judge_prompt(payload)
        request_payload = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        try:
            raw = _post_json(
                f"{self.config.base_url}/api/generate",
                request_payload,
                timeout=self.config.timeout_seconds,
            )
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            return LocalAIJudgeResult(enabled=True, status="request_error", error=str(exc))

        response_text = raw.get("response") if isinstance(raw, dict) else None
        if not isinstance(response_text, str):
            return LocalAIJudgeResult(enabled=True, status="invalid_response_shape", error=json.dumps(raw, sort_keys=True))
        return parse_ai_judge_json(response_text, enabled=True)


def _post_json(url: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read().decode("utf-8")
    parsed = json.loads(data)
    return parsed if isinstance(parsed, dict) else {"response": parsed}


def build_judge_prompt(payload: dict[str, Any]) -> str:
    schema = {
        "m5_close_quality": "GOOD_CLOSE | ACCEPTABLE_CLOSE | BAD_CLOSE | INVALIDATING_CLOSE",
        "reaction_state": "REACTION_ALIVE | REACTION_WEAK | REACTION_DEAD",
        "retest_quality": "HEALTHY_RETEST | FAILED_RETEST | RETEST_PENDING | NO_RETEST",
        "runner_opportunity": "STANDARD_TP | EXTENDED_RUNNER | LIQUIDITY_MAGNET_RUN | REVERSAL_RUN",
        "suggested_action": "HOLD | EXIT_EARLY | MOVE_BE | TAKE_PARTIAL | WAIT_RETEST | LET_RUN | NO_TRADE",
        "confidence": 0.0,
        "reason_codes": [],
        "notes": "",
    }
    return "\n".join(
        [
            "You are a research-only Darzo Trade local AI judge.",
            "Classify the supplied numeric candle/trade-management data. Return JSON only.",
            "Do not provide a live trading recommendation. Do not place orders. Do not send alerts. Do not modify strategy rules.",
            "+10/+15/+20 are XAUUSD price movement thresholds, not account-dollar profit.",
            "+15/+20 are partial/protection zones, not maximum TP. Healthy retests can occur after +10.",
            "Do not invent missing data; use reason_codes such as missing_m1_path_data or missing_m5_context_data when needed.",
            "Allowed JSON schema:",
            json.dumps(schema, sort_keys=True),
            "Input data:",
            json.dumps(payload, sort_keys=True, default=str),
        ]
    )


def parse_ai_judge_json(text: str, *, enabled: bool = True) -> LocalAIJudgeResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return LocalAIJudgeResult(enabled=enabled, status="invalid_json", error=str(exc), notes=text[:500])
    if not isinstance(data, dict):
        return LocalAIJudgeResult(enabled=enabled, status="invalid_json", error="json_root_not_object")

    errors: list[str] = []
    m5 = _validate_label(data.get("m5_close_quality"), M5_CLOSE_QUALITIES, "m5_close_quality", errors)
    reaction = _validate_label(data.get("reaction_state"), REACTION_STATES, "reaction_state", errors)
    retest = _validate_label(data.get("retest_quality"), RETEST_QUALITIES, "retest_quality", errors)
    runner = _validate_label(data.get("runner_opportunity"), RUNNER_OPPORTUNITIES, "runner_opportunity", errors)
    action = _validate_label(data.get("suggested_action"), SUGGESTED_ACTIONS, "suggested_action", errors)
    confidence_raw = data.get("confidence")
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = None
        errors.append("confidence_not_numeric")
    if confidence is not None:
        confidence = min(max(confidence, 0.0), 1.0)
    reason_raw = data.get("reason_codes", [])
    if isinstance(reason_raw, list):
        reasons = tuple(str(code) for code in reason_raw if code is not None)
    else:
        reasons = (str(reason_raw),) if reason_raw else ()
    notes = str(data.get("notes", "") or "")
    return LocalAIJudgeResult(
        enabled=enabled,
        status="ok" if not errors else "invalid_labels",
        m5_close_quality=m5,
        reaction_state=reaction,
        retest_quality=retest,
        runner_opportunity=runner,
        suggested_action=action,
        confidence=confidence,
        reason_codes=reasons,
        notes=notes,
        error=";".join(errors) if errors else None,
    )


def _validate_label(value: Any, allowed: tuple[str, ...], field_name: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or value not in allowed:
        errors.append(f"{field_name}_invalid")
        return None
    return value


__all__ = [
    "LocalAIJudgeConfig",
    "LocalAIJudgeResult",
    "LocalAITradeJudge",
    "SUGGESTED_ACTIONS",
    "build_judge_prompt",
    "parse_ai_judge_json",
]
