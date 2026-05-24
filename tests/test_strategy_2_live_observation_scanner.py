from __future__ import annotations

import ast
import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from dazro_trade.analytics import strategy_2_live_observation_scanner as scanner
from dazro_trade.analytics.strategy_2_live_observation_scanner import (
    DEFAULT_MAX_BARS,
    MarketSnapshot,
    build_live_observation_event,
    ensure_compatibility_files,
    diagnose_mt5_feed,
    read_mt5_snapshot,
    run_live_observation_scanner,
)
from dazro_trade.analytics.strategy_2_runtime_detector import (
    RuntimeCandidate,
    RuntimeDetectionResult,
    RuntimeDetectorStatus,
)


FIXED_NOW = datetime(2026, 5, 25, 9, 30, tzinfo=UTC)


class FakeMT5:
    TIMEFRAME_M1 = "M1"
    TIMEFRAME_M5 = "M5"
    TIMEFRAME_M15 = "M15"
    TIMEFRAME_H1 = "H1"

    def __init__(
        self,
        *,
        symbol_available: bool = True,
        closed_offsets: dict[str, int] | None = None,
        missing_timeframes: set[str] | None = None,
        chronological_order: bool = False,
    ) -> None:
        self.symbol_available = symbol_available
        self.closed_offsets = closed_offsets or {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}
        self.missing_timeframes = missing_timeframes or set()
        self.chronological_order = chronological_order
        self.shutdown_called = False
        self.copied: list[tuple[str, str, int, int]] = []

    def initialize(self, *args, **kwargs) -> bool:
        return True

    def terminal_info(self):
        return SimpleNamespace(path="C:\\Program Files\\MetaTrader 5\\terminal64.exe", trade_allowed=False)

    def version(self):
        return (500, 1, "test")

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
        if timeframe in self.missing_timeframes:
            return []
        seconds = self.closed_offsets[timeframe]
        forming_time = int(FIXED_NOW.timestamp())
        closed_time = int((FIXED_NOW - timedelta(seconds=seconds)).timestamp())
        stale_time = int((FIXED_NOW - timedelta(days=7)).timestamp())
        rows = [
            {"time": forming_time, "open": 11.0, "high": 12.0, "low": 10.0, "close": 11.5},
            {"time": closed_time, "open": 21.0, "high": 22.0, "low": 20.0, "close": 21.5},
        ]
        if self.chronological_order:
            return [
                {"time": stale_time, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5},
                rows[1],
                rows[0],
            ]
        return rows


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


def fake_runtime_candidate() -> RuntimeCandidate:
    return RuntimeCandidate(
        symbol="XAUUSD",
        direction="LONG",
        candidate_time="2026-05-25T09:15:00Z",
        H1_reference_level=2344.0,
        H1_reference_candle_time="2026-05-25T08:00:00Z",
        H1_dominant_flag=False,
        M15_reference_level=2350.0,
        M15_invalidation_level=2350.0,
        M15_invalidation_happened_first=False,
        liquidity_side="LOW",
        sweep_distance=1.0,
        MAE_entry_candidate=2343.0,
        MAE_reached=True,
        reentry_confirmed=True,
        reentry_inside_H1_range_pips=1.0,
        strategy_2_reason_code="TEST_RUNTIME_CANDIDATE",
        setup_description="Synthetic runtime candidate.",
        theoretical_entry=2344.1,
        theoretical_SL=2342.0,
        theoretical_TP1=2345.0,
        theoretical_TP2=2346.0,
        theoretical_TP3=2347.0,
        theoretical_TP4=2348.0,
        theoretical_RR_TP1=0.4286,
        theoretical_RR_TP2=0.9048,
        theoretical_RR_TP3=1.381,
        theoretical_RR_TP4=1.8571,
    )


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


def test_strategy_2_live_scanner_selects_latest_timestamps_not_array_start():
    mt5 = FakeMT5(chronological_order=True)
    snapshot = read_mt5_snapshot(
        symbol="XAUUSD",
        max_bars=dict(DEFAULT_MAX_BARS),
        closed_candle_only=True,
        mt5_module=mt5,
        now=fixed_now,
    )

    assert snapshot.latest_forming["M1"].open == 11.0
    assert snapshot.latest_closed["M1"].open == 21.0
    assert snapshot.latest_forming["M1"].source_position_used == 2
    assert snapshot.latest_closed["M1"].source_position_used == 1
    assert snapshot.feed_live_by_internal_consistency is True


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
    def detector(_snapshot: MarketSnapshot) -> RuntimeDetectionResult:
        return RuntimeDetectionResult(
            RuntimeDetectorStatus.RUNTIME_SETUP_CANDIDATE,
            candidates=[fake_runtime_candidate()],
        )

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


def test_strategy_2_live_scanner_runtime_no_setup_maps_to_feed_live_no_setup(tmp_path: Path):
    result = run_live_observation_scanner(
        symbol="XAUUSD",
        output_dir=tmp_path,
        mt5_module=FakeMT5(),
        setup_detector=lambda _snapshot: RuntimeDetectionResult(
            RuntimeDetectorStatus.RUNTIME_NO_SETUP,
            block_reason="NO_VALID_CONTAINING_MODEL_RUNTIME_SETUP",
        ),
        now=fixed_now,
    )

    assert result.scanner_status == "FEED_LIVE_NO_SETUP"
    assert result.event_appended is False
    assert result.summary["fresh_live_event_generated"] is False
    assert result.summary["runtime_detector_status"] == "RUNTIME_NO_SETUP"
    assert (tmp_path / "strategy_2_live_latest_state.json").exists()


def test_strategy_2_live_scanner_blocked_runtime_maps_to_missing_runtime_logic(tmp_path: Path):
    result = run_live_observation_scanner(
        symbol="XAUUSD",
        output_dir=tmp_path,
        mt5_module=FakeMT5(),
        setup_detector=lambda _snapshot: RuntimeDetectionResult(
            RuntimeDetectorStatus.RUNTIME_BLOCKED_UNSUPPORTED_CURRENT_LOGIC,
            block_reason="M1_CLOSED_CANDLES_REQUIRED_FOR_EXISTING_MAE_REENTRY_LOGIC",
        ),
        now=fixed_now,
    )

    assert result.scanner_status == "LIVE_SCANNER_BLOCKED_BY_MISSING_RUNTIME_LOGIC"
    assert result.event_appended is False
    assert result.summary["runtime_detector_status"] == "RUNTIME_BLOCKED_UNSUPPORTED_CURRENT_LOGIC"
    assert result.summary["missing_runtime_logic_reason"] == "M1_CLOSED_CANDLES_REQUIRED_FOR_EXISTING_MAE_REENTRY_LOGIC"


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


def test_strategy_2_live_scanner_platform_diagnostic_fields_present(tmp_path: Path):
    result = run_live_observation_scanner(
        symbol="XAUUSD",
        output_dir=tmp_path,
        mt5_module=FakeMT5(),
        now=fixed_now,
    )

    latest = result.latest_state
    heartbeat = result.heartbeat
    for payload in (latest, heartbeat):
        assert "runtime_platform" in payload
        assert "python_executable" in payload
        assert "is_wsl_detected" in payload
        assert "mt5_terminal_info_available" in payload
        assert "mt5_terminal_path_detected" in payload
        assert "mt5_version" in payload
        assert "feed_staleness_reason" in payload
        assert "feed_freshness_diagnostic" in payload
        assert "recommended_command" in payload
    assert latest["recommended_command"].endswith("python scripts\\run_strategy_2_live_observation_scanner.py --symbol XAUUSD")


def test_strategy_2_live_scanner_h1_old_alone_waits_not_stale(tmp_path: Path):
    mt5 = FakeMT5(closed_offsets={"M1": 60, "M5": 300, "M15": 900, "H1": 5 * 3600})
    result = run_live_observation_scanner(
        symbol="XAUUSD",
        output_dir=tmp_path,
        mt5_module=mt5,
        setup_detector=lambda _snapshot: None,
        now=fixed_now,
    )

    assert result.scanner_status == "FEED_LIVE_WAITING_H1_CLOSE"
    assert result.latest_state["feed_staleness_reason"] == "H1_OLD_BUT_M1_M5_M15_FRESH"
    assert result.latest_state["feed_live_by_internal_consistency"] is True


def test_strategy_2_live_scanner_m1_stale_makes_feed_stale(tmp_path: Path):
    mt5 = FakeMT5(closed_offsets={"M1": 20 * 60, "M5": 300, "M15": 900, "H1": 3600})
    result = run_live_observation_scanner(
        symbol="XAUUSD",
        output_dir=tmp_path,
        mt5_module=mt5,
        setup_detector=lambda _snapshot: None,
        now=fixed_now,
    )

    assert result.scanner_status == "FEED_STALE"
    assert result.latest_state["feed_staleness_reason"] == "M1_STALE_RELATIVE_TO_TICK"


def test_strategy_2_live_scanner_m15_absent_waiting_m15_not_stale(tmp_path: Path):
    mt5 = FakeMT5(missing_timeframes={"M15"})
    result = run_live_observation_scanner(
        symbol="XAUUSD",
        output_dir=tmp_path,
        mt5_module=mt5,
        setup_detector=lambda _snapshot: None,
        now=fixed_now,
    )

    assert result.scanner_status == "FEED_LIVE_WAITING_M15_CLOSE"
    assert result.latest_state["feed_staleness_reason"] == "M15_CLOSED_CANDLE_NOT_AVAILABLE_YET"
    assert result.latest_state["feed_live_by_internal_consistency"] is True


def test_strategy_2_live_scanner_wsl_stale_runtime_mismatch_status(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(scanner.platform, "system", lambda: "Linux")
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    mt5 = FakeMT5(closed_offsets={"M1": 20 * 60, "M5": 300, "M15": 900, "H1": 3600})

    result = run_live_observation_scanner(
        symbol="XAUUSD",
        output_dir=tmp_path,
        mt5_module=mt5,
        setup_detector=lambda _snapshot: None,
        now=fixed_now,
    )

    assert result.scanner_status == "FEED_STALE_RUNTIME_MISMATCH_POSSIBLE"
    assert result.latest_state["is_wsl_detected"] is True
    assert "RUNTIME_ENVIRONMENT_MISMATCH_POSSIBLE" in result.latest_state["feed_staleness_reason"]


def test_strategy_2_mt5_feed_diagnostic_script_read_only():
    path = Path("scripts/diagnose_strategy_2_mt5_feed.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            assert not (isinstance(func, ast.Attribute) and func.attr == "order_send")
            assert not (isinstance(func, ast.Name) and func.id == "order_send")

    result = diagnose_mt5_feed(symbol="XAUUSD", mt5_module=FakeMT5(), now=fixed_now)
    assert result["safety"]["mt5_read_only"] is True
    assert result["safety"]["no_order_send"] is True
    assert result["symbol_selected"] is True
