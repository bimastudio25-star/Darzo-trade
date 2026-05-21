from __future__ import annotations

from pathlib import Path

from dazro_trade.adelin.safety import (
    ADELIN_BLOCKED_CONTINUATION_REASON,
    ADELIN_RESEARCH_ONLY_REASON,
    adelin_continuation_permission,
    adelin_live_permission,
)
from dazro_trade.adelin.telemetry import build_signal_telemetry, distance_bucket, distance_to_liquidity_pips
from dazro_trade.core.config import Settings


def test_adelin_live_disabled_by_default_research_scan_still_enabled():
    settings = Settings()
    assert settings.adelin_enabled is True
    assert settings.adelin_live_enabled is False
    assert settings.adelin_block_continuation_entries is True
    assert "score_not_predictive" in settings.adelin_disabled_reason
    assert adelin_live_permission(settings) == (False, ADELIN_RESEARCH_ONLY_REASON)


def test_adelin_live_opt_in_is_explicit():
    assert adelin_live_permission(Settings(adelin_live_enabled=True)) == (True, None)


def test_adelin_safety_flags_parse_from_env(monkeypatch):
    monkeypatch.setenv("ADELIN_LIVE_ENABLED", "true")
    monkeypatch.setenv("ADELIN_BLOCK_CONTINUATION_ENTRIES", "false")
    monkeypatch.setenv("ADELIN_DISABLED_REASON", "research_lock")
    settings = Settings.from_env()
    assert settings.adelin_live_enabled is True
    assert settings.adelin_block_continuation_entries is False
    assert settings.adelin_disabled_reason == "research_lock"


def test_continuation_safety_blocks_with_reason():
    result = {"signal": {"telemetry": {"continuation_candidate": True}}}
    assert adelin_continuation_permission(Settings(adelin_block_continuation_entries=True), result) == (
        False,
        ADELIN_BLOCKED_CONTINUATION_REASON,
    )


def test_continuation_research_payload_is_not_deleted_when_flag_off():
    result = {"signal": {"telemetry": {"continuation_candidate": True}}}
    assert adelin_continuation_permission(Settings(adelin_block_continuation_entries=False), result) == (True, None)
    assert result["signal"]["telemetry"]["continuation_candidate"] is True


def test_distance_bucket_helper():
    assert distance_bucket(None) == "UNKNOWN"
    assert distance_bucket(5) == "0-10"
    assert distance_bucket(25) == "20-40"
    assert distance_bucket(170) == "150+"


def test_distance_to_liquidity_is_none_safe():
    assert distance_to_liquidity_pips(symbol="XAUUSD", current_price=None, liquidity_price=4700.0) is None
    assert distance_to_liquidity_pips(symbol="XAUUSD", current_price=4703.0, liquidity_price=4700.0) == 30.0


def test_signal_telemetry_backward_compatible_with_missing_fields():
    telemetry = build_signal_telemetry(
        symbol="XAUUSD",
        current_price=4700.0,
        liquidity=None,
        pip_size=0.1,
        score_detail=None,
    )
    assert telemetry["liquidity_price"] is None
    assert telemetry["distance_to_liquidity_pips"] is None
    assert telemetry["distance_to_liquidity_bucket"] == "UNKNOWN"
    assert telemetry["score_components"] == {}
    assert telemetry["score_reason_codes"] == []


def test_signal_telemetry_exposes_score_components_and_reason_codes():
    telemetry = build_signal_telemetry(
        symbol="XAUUSD",
        current_price=4703.0,
        liquidity={"level": 4700.0, "timeframe": "H1", "kind": "swing_high"},
        pip_size=0.1,
        score_detail={
            "components": {"liquidity_swept": 25, "number_theory": 15},
            "hard_filters": {"spread_ok": True, "target_clean": False},
        },
        continuation_candidate=False,
    )
    assert telemetry["symbol"] == "XAUUSD"
    assert telemetry["current_price"] == 4703.0
    assert telemetry["liquidity_price"] == 4700.0
    assert telemetry["liquidity_timeframe"] == "H1"
    assert telemetry["liquidity_type"] == "swing_high"
    assert telemetry["distance_to_liquidity_pips"] == 30.0
    assert telemetry["score_components"] == {"liquidity_swept": 25, "number_theory": 15}
    assert telemetry["score_reason_codes"] == ["liquidity_swept", "number_theory", "spread_ok"]


def test_new_adelin_modules_do_not_import_dynamic_sl():
    root = Path("dazro_trade/adelin")
    combined = (root / "safety.py").read_text() + (root / "telemetry.py").read_text()
    assert "dynamic" not in combined.lower()
