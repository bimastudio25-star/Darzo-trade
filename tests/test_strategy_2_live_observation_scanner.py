from __future__ import annotations

import ast
import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from dazro_trade.analytics.strategy_2_live_observation_scanner import (
    DEFAULT_MAX_BARS,
    MarketSnapshot,
    build_live_observation_event,
    ensure_compatibility_files,
    read_mt5_snapshot,
    run_live_observation_scanner,
)


FIXED_NOW = datetime(2026, 5, 25, 9, 30, tzinfo=UTC)


class FakeMT5:
    TIMEFRAME_M1 = "M1"
    TIMEFRAME_M5 = "M5"
    TIMEFRAME_M15 = "M15"
    TIMEFRAME_H1 = "H1"

    def __init__(self, *, symbol_available: bool = True) -> None:
        self.symbol_available = symbol_available
        self.shutdown_called = False
        self.copied: list[tuple[str, str, int, int]] = []

    def initialize(self) -> bool:
        return True

    def shutdown(self) -> None:
        self.shutdown_called = True

    def symbol_info(self, symbol: str):
        return SimpleNamespace(name=symbol) if self.symbol_available else None

    def symbol_select(self, _symbol: str, _enabled: bool) -> bool:
        return self.symbol_available

    def symbol_info_tick(self, _symbol: str):
        return SimpleNamespace(time=int(FIXED_NOW.timestamp()), bid=2345.1, ask=2345.3)

    def copy_rates_from_pos(self, symbol: str, timeframe: str, start_pos: int, count: int):
        self.copied.append((symbol, timeframe, start_pos, count))
        seconds = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}[timeframe]
        forming_time = int(FIXED_NOW.timestamp())
        closed_time = int((FIXED_NOW - timedelta(seconds=seconds)).timestamp())
        return [
            {"time": forming_time, "open": 11.0, "high": 12.0, "low": 10.0, "close": 11.5},
            {"time": closed_time, "open": 21.0, "high": 22.0, "low": 20.0, "close": 21.5},
        ]


def fixed_now() -> datetime:
    return FIXED_NOW


def fake_snapshot() -> MarketSnapshot:
    return read_mt5_snapshot(
        symbol="XAUUSD",
        max_bars=dict(DEFAULT_MAX_BARS),
        closed_candle_only=True,
        mt5_module=FakeMT5(),
        now=fixed_now,
    )


def fake_candidate() -> dict[str, object]:
    return {
        "direction": "LONG",
        "theoretical_entry": 2345.5,
        "theoretical_SL": 2342.5,
        "theoretical_TP1": 2346.5,
        "theoretical_TP2": 2347.5,
        "theoretical_TP3": 2348.5,
        "theoretical_TP4": 2349.5,
        "theoretical_RR_TP1": 0.33,
        "theoretical_RR_TP2": 0.67,
        "theoretical_RR_TP3": 1.0,
        "theoretical_RR_TP4": 1.33,
        "H1_reference_level": 2344.0,
        "H1_reference_candle_time": "2026-05-25T08:00:00Z",
        "H1_dominant_flag": False,
        "M15_reference_level": 2344.5,
        "M15_invalidation_level": 2350.0,
        "M15_invalidation_happened_first": False,
        "liquidity_side": "LOW",
        "sweep_distance": 1.0,
        "MAE_entry_candidate": 2345.5,
        "MAE_reached": True,
        "reentry_confirmed": True,
        "reentry_inside_H1_range_pips": 12.0,
        "strategy_2_reason_code": "TEST_EXISTING_RUNTIME_LOGIC",
        "setup_description": "Synthetic Strategy 2 observation fixture.",
    }


def test_strategy_2_live_scanner_no_order_send(tmp_path: Path):
    for path in [
        Path("scripts/run_strategy_2_live_observation_scanner.py"),
        Path("dazro_trade/analytics/strategy_2_live_observation_scanner.py"),
    ]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                assert not (isinstance(func, ast.Attribute) and func.attr == "order_send")
                assert not (isinstance(func, ast.Name) and func.id == "order_send")

    result = run_live_observation_scanner(
        symbol="XAUUSD",
        output_dir=tmp_path,
        mt5_module=FakeMT5(),
        setup_detector=lambda _snapshot: None,
        now=fixed_now,
        dry_run=True,
    )
    assert result.safety_audit["no_order_send"] is True
    assert result.safety_audit["no_broker_execution"] is True


def test_strategy_2_live_scanner_heartbeat(tmp_path: Path):
    result = run_live_observation_scanner(
        symbol="XAUUSD",
        output_dir=tmp_path,
        mt5_module=FakeMT5(),
        setup_detector=lambda _snapshot: None,
        now=fixed_now,
    )

    assert result.scanner_status == "FEED_LIVE_NO_SETUP"
    heartbeat_rows = (tmp_path / "strategy_2_live_heartbeat.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(heartbeat_rows) == 1
    heartbeat = json.loads(heartbeat_rows[0])
    assert heartbeat["scanner_status"] == "FEED_LIVE_NO_SETUP"
    assert heartbeat["order_send_allowed"] is False


def test_strategy_2_live_scanner_closed_candle_only():
    mt5 = FakeMT5()
    snapshot = read_mt5_snapshot(
        symbol="XAUUSD",
        max_bars=dict(DEFAULT_MAX_BARS),
        closed_candle_only=True,
        mt5_module=mt5,
        now=fixed_now,
    )

    assert snapshot.latest_closed["M15"].source_position_used == 1
    assert snapshot.latest_closed["H1"].source_position_used == 1
    assert snapshot.latest_closed["M15"].open == 21.0
    assert snapshot.latest_closed["H1"].open == 21.0
    assert all(call[2] == 0 for call in mt5.copied)


def test_strategy_2_live_scanner_stale_historical_not_alert_eligible(tmp_path: Path):
    old_row = {
        "signal_id": "hist_1",
        "strategy_id": "strategy_2",
        "timestamp_utc": "2026-05-01T00:00:00Z",
    }
    (tmp_path / "strategy_2_observation_events.jsonl").write_text(json.dumps(old_row) + "\n", encoding="utf-8")
    with (tmp_path / "strategy_2_observation_events.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(old_row))
        writer.writeheader()
        writer.writerow(old_row)

    ensure_compatibility_files(tmp_path)

    jsonl_row = json.loads((tmp_path / "strategy_2_observation_events.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert jsonl_row["source_mode"] == "HISTORICAL_EXPORT"
    assert jsonl_row["freshness_status"] == "HISTORICAL"
    assert jsonl_row["alert_eligible"] is False
    with (tmp_path / "strategy_2_observation_events.csv").open(newline="", encoding="utf-8") as handle:
        csv_row = next(csv.DictReader(handle))
    assert csv_row["source_mode"] == "HISTORICAL_EXPORT"
    assert csv_row["freshness_status"] == "HISTORICAL"
    assert csv_row["alert_eligible"] == "False"


def test_strategy_2_live_scanner_fresh_event_schema():
    event = build_live_observation_event(
        symbol="XAUUSD",
        direction="LONG",
        snapshot=fake_snapshot(),
        candidate=fake_candidate(),
        created_at=FIXED_NOW,
    )

    assert event["source_mode"] == "LIVE_OBSERVATION"
    assert event["freshness_status"] == "FRESH"
    assert event["alert_eligible"] is True
    assert event["strategy_status"] == "OBSERVATION_ONLY"
    assert event["validation_status"] == "RESEARCH_ONLY"
    assert event["execution_status"] == "NOT_EXECUTED"
    assert event["human_review_status"] == "PENDING"
    assert event["human_action"] == ""
    assert event["human_manual_entry"] == ""
    assert event["broker_execution_allowed"] is False
    assert event["order_send_allowed"] is False


def test_strategy_2_live_scanner_duplicate_protection(tmp_path: Path):
    def detector(_snapshot: MarketSnapshot) -> dict[str, object]:
        return fake_candidate()

    first = run_live_observation_scanner(
        symbol="XAUUSD",
        output_dir=tmp_path,
        mt5_module=FakeMT5(),
        setup_detector=detector,
        now=fixed_now,
    )
    second = run_live_observation_scanner(
        symbol="XAUUSD",
        output_dir=tmp_path,
        mt5_module=FakeMT5(),
        setup_detector=detector,
        now=fixed_now,
    )

    assert first.event_appended is True
    assert second.event_appended is False
    assert second.duplicate_event_blocked is True
    live_rows = (tmp_path / "strategy_2_live_observation_events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(live_rows) == 1
    latest = json.loads((tmp_path / "strategy_2_live_latest_state.json").read_text(encoding="utf-8"))
    assert latest["duplicate_events_blocked"] == 1


def test_strategy_2_live_scanner_missing_runtime_logic(tmp_path: Path):
    result = run_live_observation_scanner(
        symbol="XAUUSD",
        output_dir=tmp_path,
        mt5_module=FakeMT5(),
        now=fixed_now,
    )

    assert result.scanner_status == "LIVE_SCANNER_BLOCKED_BY_MISSING_RUNTIME_LOGIC"
    assert result.event_appended is False
    assert result.summary["fresh_live_event_generated"] is False
    assert "No existing Strategy 2 runtime detector" in result.summary["missing_runtime_logic_reason"]
    assert (tmp_path / "strategy_2_live_latest_state.json").exists()


def test_strategy_2_live_scanner_safety_audit(tmp_path: Path):
    result = run_live_observation_scanner(
        symbol="XAUUSD",
        output_dir=tmp_path,
        mt5_module=FakeMT5(),
        now=fixed_now,
    )
    audit = json.loads((tmp_path / "strategy_2_live_safety_audit.json").read_text(encoding="utf-8"))

    assert result.safety_audit == audit
    assert audit["no_live_trading"] is True
    assert audit["no_order_send"] is True
    assert audit["no_broker_execution"] is True
    assert audit["no_data_xauusd_modification"] is True
    assert audit["no_parameter_tuning"] is True
    assert audit["strategy_status"] == "OBSERVATION_ONLY"
