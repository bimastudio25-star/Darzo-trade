from __future__ import annotations

import ast
from pathlib import Path

from dazro_trade.analytics.strategy_2_runtime_detector import (
    RuntimeDetectorStatus,
    build_runtime_observation_event,
    detect_strategy_2_runtime_candidates,
)


PROFILE = {
    "conservative_sl": 2.0,
    "tp_quartiles": {"tp1": 1.0, "tp2": 2.0, "tp3": 3.0, "tp4": 4.0},
    "mae_avg_usd": 1.0,
    "min_distribution_usd": 0.1,
    "level_take_pips": 1.0,
    "reentry_pips": 1.0,
    "pip_factor": 10.0,
}


def _h1_rows() -> list[dict[str, object]]:
    return [
        {"time": "2026-05-25T07:00:00Z", "open": 106.0, "high": 108.0, "low": 104.0, "close": 105.0},
        {"time": "2026-05-25T08:00:00Z", "open": 105.0, "high": 110.0, "low": 100.0, "close": 103.0},
    ]


def _m15_rows() -> list[dict[str, object]]:
    return [
        {"time": "2026-05-25T08:45:00Z", "open": 103.0, "high": 106.0, "low": 101.0, "close": 102.0},
        {"time": "2026-05-25T09:00:00Z", "open": 102.0, "high": 106.0, "low": 99.5, "close": 100.5},
        {"time": "2026-05-25T09:15:00Z", "open": 100.5, "high": 101.5, "low": 99.0, "close": 101.0},
    ]


def _m1_rows(*, include_reentry: bool = True, include_future_reentry: bool = False) -> list[dict[str, object]]:
    mae_high = 100.6 if include_reentry else 100.0
    rows: list[dict[str, object]] = [
        {"time": "2026-05-25T09:00:00Z", "open": 102.0, "high": 103.0, "low": 101.0, "close": 101.5},
        {"time": "2026-05-25T09:04:00Z", "open": 101.5, "high": 102.0, "low": 100.2, "close": 100.4},
        {"time": "2026-05-25T09:05:00Z", "open": 100.4, "high": mae_high, "low": 98.8, "close": 99.4},
    ]
    if include_reentry:
        rows.append({"time": "2026-05-25T09:06:00Z", "open": 99.4, "high": 101.0, "low": 99.2, "close": 100.7})
    if include_future_reentry:
        rows.append({"time": "2026-05-25T09:30:00Z", "open": 99.4, "high": 101.0, "low": 99.2, "close": 100.7})
    rows.append({"time": "2026-05-25T09:15:00Z", "open": 100.7, "high": 101.2, "low": 100.1, "close": 100.9})
    return rows


def test_runtime_detector_uses_only_closed_candles_and_builds_candidate():
    result = detect_strategy_2_runtime_candidates(
        symbol="XAUUSD",
        closed_h1=_h1_rows(),
        closed_m15=_m15_rows(),
        closed_m1=_m1_rows(),
        profile=PROFILE,
        now_context={"as_of_time": "2026-05-25T09:15:00Z"},
    )

    assert result.status == RuntimeDetectorStatus.RUNTIME_SETUP_CANDIDATE
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.direction == "LONG"
    assert candidate.theoretical_entry == 100.1
    assert candidate.theoretical_SL == 98.0
    assert candidate.theoretical_TP1 == 101.0
    assert candidate.theoretical_TP4 == 104.0
    assert candidate.M15_invalidation_happened_first is False
    assert candidate.strategy_status == "OBSERVATION_ONLY"
    assert candidate.execution_status == "NOT_EXECUTED"
    assert candidate.order_send_allowed is False


def test_runtime_detector_does_not_use_future_candles():
    result = detect_strategy_2_runtime_candidates(
        symbol="XAUUSD",
        closed_h1=_h1_rows(),
        closed_m15=_m15_rows(),
        closed_m1=_m1_rows(include_reentry=False, include_future_reentry=True),
        profile=PROFILE,
        now_context={"as_of_time": "2026-05-25T09:10:00Z"},
    )

    assert result.status == RuntimeDetectorStatus.RUNTIME_NO_SETUP
    assert not result.candidates


def test_runtime_detector_does_not_read_historical_corrected_samples():
    text = Path("dazro_trade/analytics/strategy_2_runtime_detector.py").read_text(encoding="utf-8")
    assert "corrected_mechanical_samples" not in text
    assert "pd.read_csv" not in text
    assert "read_csv" not in text
    assert "strategy_3" not in text
    assert "dazro_trade.adelin" not in text
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            assert not (isinstance(func, ast.Attribute) and func.attr == "order_send")
            assert not (isinstance(func, ast.Name) and func.id == "order_send")


def test_runtime_detector_no_setup_for_incomplete_structure():
    result = detect_strategy_2_runtime_candidates(
        symbol="XAUUSD",
        closed_h1=_h1_rows(),
        closed_m15=_m15_rows(),
        closed_m1=[
            {"time": "2026-05-25T09:00:00Z", "open": 103.0, "high": 104.0, "low": 102.0, "close": 103.0},
            {"time": "2026-05-25T09:15:00Z", "open": 103.0, "high": 104.0, "low": 102.0, "close": 103.0},
        ],
        profile=PROFILE,
        now_context={"as_of_time": "2026-05-25T09:15:00Z"},
    )

    assert result.status == RuntimeDetectorStatus.RUNTIME_NO_SETUP
    assert result.block_reason == "NO_VALID_CONTAINING_MODEL_RUNTIME_SETUP"


def test_runtime_detector_blocks_instead_of_faking_when_profile_fields_missing():
    result = detect_strategy_2_runtime_candidates(
        symbol="XAUUSD",
        closed_h1=_h1_rows(),
        closed_m15=_m15_rows(),
        closed_m1=_m1_rows(),
        profile={**PROFILE, "conservative_sl": None},
        now_context={"as_of_time": "2026-05-25T09:15:00Z"},
    )

    assert result.status == RuntimeDetectorStatus.RUNTIME_BLOCKED_MISSING_REQUIRED_FIELDS
    assert "theoretical_SL" in result.missing_required_fields
    assert not result.candidates


def test_runtime_detector_blocks_when_m1_required_for_existing_logic():
    result = detect_strategy_2_runtime_candidates(
        symbol="XAUUSD",
        closed_h1=_h1_rows(),
        closed_m15=_m15_rows(),
        closed_m1=[],
        profile=PROFILE,
        now_context={"as_of_time": "2026-05-25T09:15:00Z"},
    )

    assert result.status == RuntimeDetectorStatus.RUNTIME_BLOCKED_UNSUPPORTED_CURRENT_LOGIC
    assert result.block_reason == "M1_CLOSED_CANDLES_REQUIRED_FOR_EXISTING_MAE_REENTRY_LOGIC"


def test_runtime_observation_event_payload_contains_required_fields():
    result = detect_strategy_2_runtime_candidates(
        symbol="XAUUSD",
        closed_h1=_h1_rows(),
        closed_m15=_m15_rows(),
        closed_m1=_m1_rows(),
        profile=PROFILE,
        now_context={"as_of_time": "2026-05-25T09:15:00Z"},
    )

    payload = build_runtime_observation_event(result.candidates[0])
    for field in (
        "theoretical_entry",
        "theoretical_SL",
        "theoretical_TP1",
        "theoretical_TP2",
        "theoretical_TP3",
        "theoretical_TP4",
        "theoretical_RR_TP1",
        "theoretical_RR_TP2",
        "theoretical_RR_TP3",
        "theoretical_RR_TP4",
        "H1_reference_level",
        "M15_invalidation_level",
        "MAE_reached",
        "reentry_confirmed",
    ):
        assert payload[field] is not None
    assert payload["broker_execution_allowed"] is False
    assert payload["real_money_allowed"] is False
