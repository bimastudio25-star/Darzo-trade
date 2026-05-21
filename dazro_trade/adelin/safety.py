from __future__ import annotations

from typing import Any


ADELIN_RESEARCH_ONLY_WARNING = (
    "Adelin is research-only: existing score is not predictive and continuation is toxic."
)
ADELIN_DEFAULT_DISABLED_REASON = (
    "score_not_predictive_low_score_variance_continuation_toxic_rejection_oos_break_even"
)
ADELIN_RESEARCH_ONLY_REASON = "adelin_research_only_live_disabled"
ADELIN_BLOCKED_CONTINUATION_REASON = "blocked_toxic_continuation"


def adelin_live_permission(settings: Any) -> tuple[bool, str | None]:
    """Return whether Adelin may dispatch live/Telegram signals.

    `adelin_enabled` keeps research/backtest scans available. Live
    dispatch requires the separate opt-in flag so an old environment
    cannot accidentally promote Adelin after the score audit.
    """
    if not bool(getattr(settings, "adelin_live_enabled", False)):
        return False, ADELIN_RESEARCH_ONLY_REASON
    return True, None


def _nested_dict(value: Any, key: str) -> dict[str, Any]:
    if isinstance(value, dict):
        nested = value.get(key)
        if isinstance(nested, dict):
            return nested
    return {}


def adelin_signal_is_continuation(result_or_signal: dict[str, Any] | None) -> bool:
    if not isinstance(result_or_signal, dict):
        return False
    signal = result_or_signal.get("signal") if isinstance(result_or_signal.get("signal"), dict) else result_or_signal
    telemetry = _nested_dict(signal, "telemetry")
    if bool(telemetry.get("continuation_candidate") or telemetry.get("continuation")):
        return True
    if bool(signal.get("continuation_candidate") or signal.get("continuation")):
        return True
    features = _nested_dict(signal, "features")
    return bool(features.get("continuation_candidate") or features.get("continuation"))


def adelin_continuation_permission(settings: Any, result_or_signal: dict[str, Any] | None) -> tuple[bool, str | None]:
    if bool(getattr(settings, "adelin_block_continuation_entries", True)) and adelin_signal_is_continuation(result_or_signal):
        return False, ADELIN_BLOCKED_CONTINUATION_REASON
    return True, None


__all__ = [
    "ADELIN_BLOCKED_CONTINUATION_REASON",
    "ADELIN_DEFAULT_DISABLED_REASON",
    "ADELIN_RESEARCH_ONLY_REASON",
    "ADELIN_RESEARCH_ONLY_WARNING",
    "adelin_continuation_permission",
    "adelin_live_permission",
    "adelin_signal_is_continuation",
]
