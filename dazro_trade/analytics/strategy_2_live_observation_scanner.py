from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


SCANNER_VERSION = "1.0.0"
STRATEGY_ID = "strategy_2"
STRATEGY_STATUS = "OBSERVATION_ONLY"
VALIDATION_STATUS = "RESEARCH_ONLY"
EXECUTION_STATUS = "NOT_EXECUTED"
DEFAULT_OUTPUT_DIR = Path("backtests/reports/strategy_2_forward_observation_alerts")
NO_LIVE_CONFIRMATION = "NO_LIVE_TRADING_NO_BROKER_EXECUTION_NO_ORDER_SEND"
ALERT_DISCLAIMER = "OBSERVATION ONLY - compare with Adelin manual entry - not validated - no broker execution."
ROME_TZ = ZoneInfo("Europe/Rome")

TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "H1": 3600,
}

DEFAULT_MAX_BARS = {
    "M1": 2000,
    "M5": 1000,
    "M15": 500,
    "H1": 300,
}

ALLOWED_STATUSES = {
    "FEED_LIVE_NO_SETUP",
    "FEED_LIVE_WAITING_M15_CLOSE",
    "FEED_LIVE_WAITING_H1_CLOSE",
    "FEED_LIVE_SETUP_DETECTED",
    "FEED_STALE",
    "FEED_STALE_RUNTIME_MISMATCH_POSSIBLE",
    "MT5_UNAVAILABLE",
    "SYMBOL_UNAVAILABLE",
    "LIVE_SCANNER_BLOCKED_BY_MISSING_RUNTIME_LOGIC",
    "ERROR",
}

LIVE_EVENT_FIELDS = [
    "event_id",
    "signal_id",
    "source_mode",
    "freshness_status",
    "alert_eligible",
    "strategy_id",
    "strategy_status",
    "validation_status",
    "execution_status",
    "symbol",
    "direction",
    "timestamp_server",
    "timestamp_utc_estimated",
    "timestamp_europe_rome",
    "created_at_utc",
    "latest_tick_server_time",
    "latest_closed_m1_time",
    "latest_closed_m5_time",
    "latest_closed_m15_time",
    "latest_closed_h1_time",
    "spread_usd",
    "feed_live_by_internal_consistency",
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
    "H1_reference_candle_time",
    "H1_dominant_flag",
    "M15_reference_level",
    "M15_invalidation_level",
    "M15_invalidation_happened_first",
    "liquidity_side",
    "sweep_distance",
    "MAE_entry_candidate",
    "MAE_reached",
    "reentry_confirmed",
    "reentry_inside_H1_range_pips",
    "strategy_2_reason_code",
    "setup_description",
    "human_review_status",
    "human_action",
    "human_manual_entry",
    "human_manual_SL",
    "human_manual_TP1",
    "human_manual_TP2",
    "human_manual_TP3",
    "human_manual_TP4",
    "human_match_status",
    "human_reason",
    "human_notes",
    "screenshot_path",
    "broker_execution_allowed",
    "order_send_allowed",
    "real_money_allowed",
    "alert_disclaimer",
    "no_live_confirmation",
    "scanner_version",
    "source_logic",
    "missing_required_fields",
    "missing_field_reason",
    "duplicate_event_blocked",
    "no_future_candle_confirmation",
]

HEARTBEAT_FIELDS = [
    "heartbeat_id",
    "generated_at_utc",
    "generated_at_europe_rome",
    "symbol",
    "mt5_initialized",
    "mt5_symbol_available",
    "feed_live_by_internal_consistency",
    "latest_tick_server_time",
    "latest_tick_bid",
    "latest_tick_ask",
    "spread_usd",
    "latest_closed_m1_time",
    "latest_closed_m5_time",
    "latest_closed_m15_time",
    "latest_closed_h1_time",
    "server_offset_hours_estimate",
    "runtime_platform",
    "python_executable",
    "is_wsl_detected",
    "mt5_terminal_info_available",
    "mt5_terminal_path_detected",
    "mt5_version",
    "feed_staleness_reason",
    "feed_freshness_diagnostic",
    "recommended_runtime",
    "recommended_command",
    "scanner_status",
    "no_live_confirmation",
    "broker_execution_allowed",
    "order_send_allowed",
    "real_money_allowed",
]


@dataclass(frozen=True)
class ClosedCandle:
    timeframe: str
    time: str | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    source_position_used: int | None


@dataclass(frozen=True)
class RuntimeDiagnostics:
    runtime_platform: str
    python_executable: str
    cwd: str
    python_version: str
    is_wsl_detected: bool
    mt5_terminal_info_available: bool = False
    mt5_terminal_path_detected: str | None = None
    mt5_terminal_info: dict[str, Any] | None = None
    mt5_version: str | None = None
    recommended_runtime: str = "Windows native Python connected to the running MT5 terminal"
    recommended_command: str = (
        'cd "C:\\Users\\90NA00VIX\\OneDrive\\Documenti\\LAVORO\\darzo trade human-mgmt"; '
        "python scripts\\run_strategy_2_live_observation_scanner.py --symbol XAUUSD"
    )


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    mt5_initialized: bool
    mt5_symbol_available: bool
    latest_tick_server_time: str | None
    latest_tick_bid: float | None
    latest_tick_ask: float | None
    spread_usd: float | None
    latest_forming: dict[str, ClosedCandle]
    latest_closed: dict[str, ClosedCandle]
    server_offset_hours_estimate: float | None
    feed_live_by_internal_consistency: bool
    feed_status: str
    feed_staleness_reason: str | None
    feed_freshness_diagnostic: dict[str, Any]
    runtime: RuntimeDiagnostics
    error: str | None = None

    def latest_closed_time(self, timeframe: str) -> str | None:
        candle = self.latest_closed.get(timeframe)
        return candle.time if candle else None

    def latest_forming_time(self, timeframe: str) -> str | None:
        candle = self.latest_forming.get(timeframe)
        return candle.time if candle else None


@dataclass(frozen=True)
class LiveScannerResult:
    scanner_status: str
    heartbeat: dict[str, Any]
    latest_state: dict[str, Any]
    summary: dict[str, Any]
    safety_audit: dict[str, Any]
    event_appended: bool
    duplicate_event_blocked: bool
    paths: dict[str, str]


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def detect_wsl() -> bool:
    if platform.system().lower() != "linux":
        return False
    if "WSL_DISTRO_NAME" in os.environ:
        return True
    try:
        version_text = Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        version_text = ""
    return "microsoft" in version_text or "wsl" in version_text


def build_runtime_diagnostics(
    *,
    terminal_info: Any | None = None,
    mt5_version: Any | None = None,
) -> RuntimeDiagnostics:
    path = None
    terminal_info_dict = None
    if terminal_info is not None:
        if hasattr(terminal_info, "_asdict"):
            terminal_info_dict = dict(terminal_info._asdict())
            path = terminal_info_dict.get("path")
        elif isinstance(terminal_info, dict):
            terminal_info_dict = dict(terminal_info)
            path = terminal_info.get("path")
        else:
            path = getattr(terminal_info, "path", None)
            terminal_info_dict = {
                key: getattr(terminal_info, key)
                for key in dir(terminal_info)
                if not key.startswith("_") and isinstance(getattr(terminal_info, key), (str, int, float, bool, type(None)))
            }
    version_text = None
    if mt5_version is not None:
        version_text = ".".join(str(part) for part in mt5_version) if isinstance(mt5_version, (tuple, list)) else str(mt5_version)
    return RuntimeDiagnostics(
        runtime_platform=platform.system(),
        python_executable=sys.executable,
        cwd=str(Path.cwd()),
        python_version=platform.python_version(),
        is_wsl_detected=detect_wsl(),
        mt5_terminal_info_available=terminal_info is not None,
        mt5_terminal_path_detected=str(path) if path else None,
        mt5_terminal_info=terminal_info_dict,
        mt5_version=version_text,
    )


def parse_max_bars(value: str | None) -> dict[str, int]:
    if not value:
        return dict(DEFAULT_MAX_BARS)
    parsed = dict(DEFAULT_MAX_BARS)
    for part in value.split(","):
        if not part.strip():
            continue
        if "=" not in part:
            raise ValueError(f"Invalid max-bars entry: {part}")
        key, raw_count = part.split("=", 1)
        timeframe = key.strip().upper()
        if timeframe not in DEFAULT_MAX_BARS:
            raise ValueError(f"Unsupported timeframe in max-bars: {timeframe}")
        count = int(raw_count.strip())
        if count < 2:
            raise ValueError(f"max-bars for {timeframe} must be at least 2 so pos 1 is available")
        parsed[timeframe] = count
    return parsed


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_signal_id(parts: list[Any]) -> str:
    payload = "|".join("" if part is None else str(part) for part in parts)
    return "s2_live_" + _hash_text(payload)[:24]


def _event_id(signal_id: str, created_at_utc: str) -> str:
    return "evt_live_" + _hash_text(f"{signal_id}|{created_at_utc}")[:24]


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rate_value(rate: Any, key: str) -> Any:
    if isinstance(rate, dict):
        return rate.get(key)
    if hasattr(rate, key):
        return getattr(rate, key)
    try:
        return rate[key]
    except Exception:
        return None


def _tick_value(tick: Any, key: str) -> Any:
    if tick is None:
        return None
    if isinstance(tick, dict):
        return tick.get(key)
    if hasattr(tick, "_asdict"):
        return tick._asdict().get(key)
    if hasattr(tick, key):
        return getattr(tick, key)
    return None


def _timestamp_from_epoch(value: Any) -> str | None:
    number = _as_float(value)
    if number is None:
        return None
    return isoformat_z(datetime.fromtimestamp(number, tz=UTC))


def _candle_from_rates(rates: Any, timeframe: str, *, position: int) -> ClosedCandle:
    if rates is None or len(rates) <= position:
        return ClosedCandle(timeframe, None, None, None, None, None, None)
    rate = rates[position]
    return ClosedCandle(
        timeframe=timeframe,
        time=_timestamp_from_epoch(_rate_value(rate, "time")),
        open=_as_float(_rate_value(rate, "open")),
        high=_as_float(_rate_value(rate, "high")),
        low=_as_float(_rate_value(rate, "low")),
        close=_as_float(_rate_value(rate, "close")),
        source_position_used=position,
    )


def _latest_forming_and_closed_from_rates(rates: Any, timeframe: str, *, closed_candle_only: bool) -> tuple[ClosedCandle, ClosedCandle]:
    if rates is None or len(rates) == 0:
        empty = ClosedCandle(timeframe, None, None, None, None, None, None)
        return empty, empty
    indexed_rates = []
    for index, rate in enumerate(rates):
        timestamp = _as_float(_rate_value(rate, "time"))
        if timestamp is None:
            continue
        indexed_rates.append((timestamp, index, rate))
    if not indexed_rates:
        empty = ClosedCandle(timeframe, None, None, None, None, None, None)
        return empty, empty
    indexed_rates.sort(key=lambda item: item[0])
    forming_index = indexed_rates[-1][1]
    closed_index = indexed_rates[-2][1] if closed_candle_only and len(indexed_rates) >= 2 else forming_index
    return (
        _candle_from_rates(rates, timeframe, position=forming_index),
        _candle_from_rates(rates, timeframe, position=closed_index),
    )


def _timeframe_constants(mt5_module: Any) -> dict[str, Any]:
    return {
        "M1": getattr(mt5_module, "TIMEFRAME_M1"),
        "M5": getattr(mt5_module, "TIMEFRAME_M5"),
        "M15": getattr(mt5_module, "TIMEFRAME_M15"),
        "H1": getattr(mt5_module, "TIMEFRAME_H1"),
    }


def import_mt5_module() -> Any:
    try:
        import MetaTrader5 as mt5  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(f"MetaTrader5 import failed: {exc}") from exc
    return mt5


def _estimate_server_offset_hours(latest_tick_server_time: str | None, now_utc: datetime) -> float | None:
    if not latest_tick_server_time:
        return None
    try:
        tick_dt = datetime.fromisoformat(latest_tick_server_time.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
    delta_hours = (tick_dt - now_utc).total_seconds() / 3600
    return round(delta_hours)


def _is_recent(
    timestamp_text: str | None,
    now_utc: datetime,
    max_age_seconds: int,
    *,
    server_offset_hours_estimate: float | None = None,
) -> bool:
    if not timestamp_text:
        return False
    try:
        timestamp = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return False
    if server_offset_hours_estimate is not None:
        timestamp = timestamp - timedelta(hours=server_offset_hours_estimate)
    age = abs((now_utc - timestamp).total_seconds())
    return age <= max_age_seconds


def _parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _delta_seconds(left: str | None, right: str | None) -> float | None:
    left_dt = _parse_iso_utc(left)
    right_dt = _parse_iso_utc(right)
    if left_dt is None or right_dt is None:
        return None
    return abs((left_dt - right_dt).total_seconds())


def _freshness_status_from_internal_times(snapshot: MarketSnapshot) -> tuple[str, str | None, dict[str, Any]]:
    tick_time = snapshot.latest_tick_server_time
    m1_forming_time = snapshot.latest_forming_time("M1")
    m1_closed_time = snapshot.latest_closed_time("M1")
    m5_closed_time = snapshot.latest_closed_time("M5")
    m15_closed_time = snapshot.latest_closed_time("M15")
    h1_closed_time = snapshot.latest_closed_time("H1")

    tick_to_m1_forming = _delta_seconds(tick_time, m1_forming_time)
    tick_to_m1_closed = _delta_seconds(tick_time, m1_closed_time)
    tick_to_m5_closed = _delta_seconds(tick_time, m5_closed_time)
    tick_to_m15_closed = _delta_seconds(tick_time, m15_closed_time)
    tick_to_h1_closed = _delta_seconds(tick_time, h1_closed_time)

    diagnostic = {
        "tick_vs_current_forming_m1_seconds": tick_to_m1_forming,
        "tick_vs_latest_m1_seconds": tick_to_m1_closed,
        "tick_vs_latest_m5_seconds": tick_to_m5_closed,
        "tick_vs_latest_m15_seconds": tick_to_m15_closed,
        "tick_vs_latest_h1_seconds": tick_to_h1_closed,
        "current_forming_m1_time": m1_forming_time,
        "current_forming_m5_time": snapshot.latest_forming_time("M5"),
        "current_forming_m15_time": snapshot.latest_forming_time("M15"),
        "current_forming_h1_time": snapshot.latest_forming_time("H1"),
        "latest_closed_m1_time": m1_closed_time,
        "latest_closed_m5_time": m5_closed_time,
        "latest_closed_m15_time": m15_closed_time,
        "latest_closed_h1_time": h1_closed_time,
        "h1_old_is_not_feed_stale_by_itself": True,
    }

    if not tick_time:
        return "FEED_STALE", "TICK_MISSING", diagnostic
    if tick_to_m1_closed is None:
        return "FEED_STALE", "M1_CLOSED_CANDLE_MISSING", diagnostic
    if tick_to_m1_closed > 10 * 60:
        return "FEED_STALE", "M1_STALE_RELATIVE_TO_TICK", diagnostic
    if m5_closed_time is None:
        return "FEED_LIVE_WAITING_M15_CLOSE", "M5_CLOSED_CANDLE_MISSING_WAITING", diagnostic
    if tick_to_m5_closed is not None and tick_to_m5_closed > 20 * 60:
        return "FEED_STALE", "M5_STALE_RELATIVE_TO_TICK", diagnostic
    if m15_closed_time is None:
        return "FEED_LIVE_WAITING_M15_CLOSE", "M15_CLOSED_CANDLE_NOT_AVAILABLE_YET", diagnostic
    if tick_to_m15_closed is not None and tick_to_m15_closed > 60 * 60:
        return "FEED_LIVE_WAITING_M15_CLOSE", "M15_NOT_FRESH_WAITING_FOR_FIRST_RECENT_CLOSE", diagnostic
    if h1_closed_time is None or (tick_to_h1_closed is not None and tick_to_h1_closed > 3 * 3600):
        return "FEED_LIVE_WAITING_H1_CLOSE", "H1_OLD_BUT_M1_M5_M15_FRESH", diagnostic
    return "FEED_LIVE", None, diagnostic


def read_mt5_snapshot(
    *,
    symbol: str,
    max_bars: dict[str, int],
    closed_candle_only: bool = True,
    mt5_terminal_path: str | None = None,
    mt5_module: Any | None = None,
    now: Callable[[], datetime] = utc_now,
) -> MarketSnapshot:
    current_time = now()
    fallback_runtime = build_runtime_diagnostics()
    try:
        mt5 = mt5_module if mt5_module is not None else import_mt5_module()
    except RuntimeError as exc:
        return MarketSnapshot(
            symbol=symbol,
            mt5_initialized=False,
            mt5_symbol_available=False,
            latest_tick_server_time=None,
            latest_tick_bid=None,
            latest_tick_ask=None,
            spread_usd=None,
            latest_forming={},
            latest_closed={},
            server_offset_hours_estimate=None,
            feed_live_by_internal_consistency=False,
            feed_status="MT5_UNAVAILABLE",
            feed_staleness_reason="MT5_IMPORT_FAILED",
            feed_freshness_diagnostic={"error": str(exc)},
            runtime=fallback_runtime,
            error=str(exc),
        )

    initialized = bool(mt5.initialize(path=str(mt5_terminal_path))) if mt5_terminal_path else bool(mt5.initialize())
    if not initialized:
        return MarketSnapshot(
            symbol=symbol,
            mt5_initialized=False,
            mt5_symbol_available=False,
            latest_tick_server_time=None,
            latest_tick_bid=None,
            latest_tick_ask=None,
            spread_usd=None,
            latest_forming={},
            latest_closed={},
            server_offset_hours_estimate=None,
            feed_live_by_internal_consistency=False,
            feed_status="MT5_UNAVAILABLE",
            feed_staleness_reason="MT5_INITIALIZE_FAILED",
            feed_freshness_diagnostic={"mt5_terminal_path_argument": mt5_terminal_path},
            runtime=fallback_runtime,
            error="mt5.initialize returned false",
        )

    try:
        terminal_info = mt5.terminal_info() if callable(getattr(mt5, "terminal_info", None)) else None
        mt5_version = mt5.version() if callable(getattr(mt5, "version", None)) else None
        runtime = build_runtime_diagnostics(terminal_info=terminal_info, mt5_version=mt5_version)
        info = mt5.symbol_info(symbol)
        symbol_available = info is not None
        if symbol_available:
            selected = mt5.symbol_select(symbol, True)
            symbol_available = bool(selected)
        if not symbol_available:
            return MarketSnapshot(
                symbol=symbol,
                mt5_initialized=True,
                mt5_symbol_available=False,
                latest_tick_server_time=None,
                latest_tick_bid=None,
                latest_tick_ask=None,
                spread_usd=None,
                latest_forming={},
                latest_closed={},
                server_offset_hours_estimate=None,
                feed_live_by_internal_consistency=False,
                feed_status="SYMBOL_UNAVAILABLE",
                feed_staleness_reason="SYMBOL_UNAVAILABLE_OR_SELECT_FAILED",
                feed_freshness_diagnostic={"symbol": symbol},
                runtime=runtime,
                error="symbol unavailable or could not be selected",
            )

        tick = mt5.symbol_info_tick(symbol)
        tick_time = _timestamp_from_epoch(_tick_value(tick, "time"))
        tick_bid = _as_float(_tick_value(tick, "bid"))
        tick_ask = _as_float(_tick_value(tick, "ask"))
        spread = round(tick_ask - tick_bid, 5) if tick_bid is not None and tick_ask is not None else None

        latest_forming: dict[str, ClosedCandle] = {}
        latest_closed: dict[str, ClosedCandle] = {}
        for timeframe, mt5_timeframe in _timeframe_constants(mt5).items():
            rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, max_bars.get(timeframe, DEFAULT_MAX_BARS[timeframe]))
            forming, closed = _latest_forming_and_closed_from_rates(
                rates,
                timeframe,
                closed_candle_only=closed_candle_only,
            )
            latest_forming[timeframe] = forming
            latest_closed[timeframe] = closed

        snapshot = MarketSnapshot(
            symbol=symbol,
            mt5_initialized=True,
            mt5_symbol_available=True,
            latest_tick_server_time=tick_time,
            latest_tick_bid=tick_bid,
            latest_tick_ask=tick_ask,
            spread_usd=spread,
            latest_forming=latest_forming,
            latest_closed=latest_closed,
            server_offset_hours_estimate=_estimate_server_offset_hours(tick_time, current_time),
            feed_live_by_internal_consistency=False,
            feed_status="FEED_STALE",
            feed_staleness_reason=None,
            feed_freshness_diagnostic={},
            runtime=runtime,
            error=None,
        )
        feed_status, stale_reason, freshness_diagnostic = _freshness_status_from_internal_times(snapshot)
        if feed_status == "FEED_STALE" and runtime.is_wsl_detected:
            feed_status = "FEED_STALE_RUNTIME_MISMATCH_POSSIBLE"
            stale_reason = f"{stale_reason}; RUNTIME_ENVIRONMENT_MISMATCH_POSSIBLE"
        return MarketSnapshot(
            symbol=snapshot.symbol,
            mt5_initialized=snapshot.mt5_initialized,
            mt5_symbol_available=snapshot.mt5_symbol_available,
            latest_tick_server_time=snapshot.latest_tick_server_time,
            latest_tick_bid=snapshot.latest_tick_bid,
            latest_tick_ask=snapshot.latest_tick_ask,
            spread_usd=snapshot.spread_usd,
            latest_forming=snapshot.latest_forming,
            latest_closed=snapshot.latest_closed,
            server_offset_hours_estimate=snapshot.server_offset_hours_estimate,
            feed_live_by_internal_consistency=feed_status in {
                "FEED_LIVE",
                "FEED_LIVE_WAITING_M15_CLOSE",
                "FEED_LIVE_WAITING_H1_CLOSE",
            },
            feed_status=feed_status,
            feed_staleness_reason=stale_reason,
            feed_freshness_diagnostic=freshness_diagnostic,
            runtime=snapshot.runtime,
            error=snapshot.error,
        )
    finally:
        shutdown = getattr(mt5, "shutdown", None)
        if callable(shutdown):
            shutdown()


def missing_runtime_logic_reason() -> str:
    return (
        "No existing Strategy 2 runtime detector was found that can transform read-only MT5 "
        "closed candles into a complete live setup with mechanical entry, SL, H1-anchored "
        "TP quartiles, M15 invalidation, MAE, and re-entry fields. Historical research "
        "helpers are not used to fabricate live signals."
    )


def detect_live_strategy_2_setup(_snapshot: MarketSnapshot) -> dict[str, Any] | None:
    return None


def _blank_human_fields() -> dict[str, Any]:
    return {
        "human_review_status": "PENDING",
        "human_action": "",
        "human_manual_entry": "",
        "human_manual_SL": "",
        "human_manual_TP1": "",
        "human_manual_TP2": "",
        "human_manual_TP3": "",
        "human_manual_TP4": "",
        "human_match_status": "",
        "human_reason": "",
        "human_notes": "",
        "screenshot_path": "",
    }


def _event_signal_parts(event: dict[str, Any]) -> list[Any]:
    return [
        event.get("strategy_id"),
        event.get("source_mode"),
        event.get("latest_closed_m15_time"),
        event.get("latest_closed_h1_time"),
        event.get("direction"),
        event.get("theoretical_entry"),
        event.get("theoretical_SL"),
        event.get("H1_reference_level"),
        event.get("M15_invalidation_level"),
    ]


def build_live_observation_event(
    *,
    symbol: str,
    direction: str,
    snapshot: MarketSnapshot,
    candidate: dict[str, Any],
    created_at: datetime | None = None,
    duplicate_event_blocked: bool = False,
) -> dict[str, Any]:
    created = created_at or utc_now()
    created_at_utc = isoformat_z(created)
    timestamp_server = candidate.get("timestamp_server") or snapshot.latest_closed_time("M15") or snapshot.latest_tick_server_time
    timestamp_utc_estimated = timestamp_server
    timestamp_rome = (
        datetime.fromisoformat(timestamp_utc_estimated.replace("Z", "+00:00")).astimezone(ROME_TZ).isoformat()
        if timestamp_utc_estimated
        else None
    )
    base = {
        "source_mode": "LIVE_OBSERVATION",
        "freshness_status": "FRESH",
        "alert_eligible": True,
        "strategy_id": STRATEGY_ID,
        "strategy_status": STRATEGY_STATUS,
        "validation_status": VALIDATION_STATUS,
        "execution_status": EXECUTION_STATUS,
        "symbol": symbol,
        "direction": direction,
        "timestamp_server": timestamp_server,
        "timestamp_utc_estimated": timestamp_utc_estimated,
        "timestamp_europe_rome": timestamp_rome,
        "created_at_utc": created_at_utc,
        "latest_tick_server_time": snapshot.latest_tick_server_time,
        "latest_closed_m1_time": snapshot.latest_closed_time("M1"),
        "latest_closed_m5_time": snapshot.latest_closed_time("M5"),
        "latest_closed_m15_time": snapshot.latest_closed_time("M15"),
        "latest_closed_h1_time": snapshot.latest_closed_time("H1"),
        "spread_usd": snapshot.spread_usd,
        "feed_live_by_internal_consistency": snapshot.feed_live_by_internal_consistency,
        "broker_execution_allowed": False,
        "order_send_allowed": False,
        "real_money_allowed": False,
        "alert_disclaimer": ALERT_DISCLAIMER,
        "no_live_confirmation": NO_LIVE_CONFIRMATION,
        "scanner_version": SCANNER_VERSION,
        "source_logic": candidate.get("source_logic", "existing_strategy_2_runtime_logic"),
        "missing_required_fields": candidate.get("missing_required_fields", []),
        "missing_field_reason": candidate.get("missing_field_reason", ""),
        "duplicate_event_blocked": duplicate_event_blocked,
        "no_future_candle_confirmation": "CLOSED_CANDLES_ONLY_POS_1_FOR_M15_H1",
    }
    bot_fields = {
        "theoretical_entry": candidate.get("theoretical_entry"),
        "theoretical_SL": candidate.get("theoretical_SL"),
        "theoretical_TP1": candidate.get("theoretical_TP1"),
        "theoretical_TP2": candidate.get("theoretical_TP2"),
        "theoretical_TP3": candidate.get("theoretical_TP3"),
        "theoretical_TP4": candidate.get("theoretical_TP4"),
        "theoretical_RR_TP1": candidate.get("theoretical_RR_TP1"),
        "theoretical_RR_TP2": candidate.get("theoretical_RR_TP2"),
        "theoretical_RR_TP3": candidate.get("theoretical_RR_TP3"),
        "theoretical_RR_TP4": candidate.get("theoretical_RR_TP4"),
        "H1_reference_level": candidate.get("H1_reference_level"),
        "H1_reference_candle_time": candidate.get("H1_reference_candle_time"),
        "H1_dominant_flag": candidate.get("H1_dominant_flag"),
        "M15_reference_level": candidate.get("M15_reference_level"),
        "M15_invalidation_level": candidate.get("M15_invalidation_level"),
        "M15_invalidation_happened_first": candidate.get("M15_invalidation_happened_first"),
        "liquidity_side": candidate.get("liquidity_side"),
        "sweep_distance": candidate.get("sweep_distance"),
        "MAE_entry_candidate": candidate.get("MAE_entry_candidate"),
        "MAE_reached": candidate.get("MAE_reached"),
        "reentry_confirmed": candidate.get("reentry_confirmed"),
        "reentry_inside_H1_range_pips": candidate.get("reentry_inside_H1_range_pips"),
        "strategy_2_reason_code": candidate.get("strategy_2_reason_code"),
        "setup_description": candidate.get("setup_description"),
    }
    event = {**base, **bot_fields, **_blank_human_fields()}
    signal_id = stable_signal_id(_event_signal_parts(event))
    event["signal_id"] = signal_id
    event["event_id"] = _event_id(signal_id, created_at_utc or "")
    return {field: event.get(field) for field in LIVE_EVENT_FIELDS}


def build_heartbeat(symbol: str, snapshot: MarketSnapshot, scanner_status: str, generated_at: datetime | None = None) -> dict[str, Any]:
    if scanner_status not in ALLOWED_STATUSES:
        raise ValueError(f"Unsupported scanner_status: {scanner_status}")
    generated = generated_at or utc_now()
    generated_utc = isoformat_z(generated)
    heartbeat_id = "hb_s2_" + _hash_text(f"{symbol}|{generated_utc}")[:24]
    return {
        "heartbeat_id": heartbeat_id,
        "generated_at_utc": generated_utc,
        "generated_at_europe_rome": generated.astimezone(ROME_TZ).isoformat(),
        "symbol": symbol,
        "mt5_initialized": snapshot.mt5_initialized,
        "mt5_symbol_available": snapshot.mt5_symbol_available,
        "feed_live_by_internal_consistency": snapshot.feed_live_by_internal_consistency,
        "latest_tick_server_time": snapshot.latest_tick_server_time,
        "latest_tick_bid": snapshot.latest_tick_bid,
        "latest_tick_ask": snapshot.latest_tick_ask,
        "spread_usd": snapshot.spread_usd,
        "latest_closed_m1_time": snapshot.latest_closed_time("M1"),
        "latest_closed_m5_time": snapshot.latest_closed_time("M5"),
        "latest_closed_m15_time": snapshot.latest_closed_time("M15"),
        "latest_closed_h1_time": snapshot.latest_closed_time("H1"),
        "server_offset_hours_estimate": snapshot.server_offset_hours_estimate,
        "runtime_platform": snapshot.runtime.runtime_platform,
        "python_executable": snapshot.runtime.python_executable,
        "is_wsl_detected": snapshot.runtime.is_wsl_detected,
        "mt5_terminal_info_available": snapshot.runtime.mt5_terminal_info_available,
        "mt5_terminal_path_detected": snapshot.runtime.mt5_terminal_path_detected,
        "mt5_version": snapshot.runtime.mt5_version,
        "feed_staleness_reason": snapshot.feed_staleness_reason,
        "feed_freshness_diagnostic": snapshot.feed_freshness_diagnostic,
        "recommended_runtime": snapshot.runtime.recommended_runtime,
        "recommended_command": snapshot.runtime.recommended_command,
        "scanner_status": scanner_status,
        "no_live_confirmation": NO_LIVE_CONFIRMATION,
        "broker_execution_allowed": False,
        "order_send_allowed": False,
        "real_money_allowed": False,
    }


def safety_audit(generated_at: str) -> dict[str, Any]:
    return {
        "generated_at_utc": generated_at,
        "strategy_id": STRATEGY_ID,
        "scanner_version": SCANNER_VERSION,
        "no_live_trading": True,
        "no_order_send": True,
        "no_broker_execution": True,
        "no_data_xauusd_modification": True,
        "no_parameter_tuning": True,
        "no_strategy_promotion": True,
        "strategy_status": STRATEGY_STATUS,
        "mt5_read_only": True,
        "output_only": True,
        "broker_execution_allowed": False,
        "order_send_allowed": False,
        "real_money_allowed": False,
    }


def _candle_payload(candle: ClosedCandle | None) -> dict[str, Any] | None:
    if candle is None:
        return None
    return {
        "time": candle.time,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "source_position_used": candle.source_position_used,
    }


def diagnose_mt5_feed(
    *,
    symbol: str = "XAUUSD",
    max_bars: dict[str, int] | None = None,
    mt5_terminal_path: str | None = None,
    mt5_module: Any | None = None,
    now: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    snapshot = read_mt5_snapshot(
        symbol=symbol,
        max_bars=max_bars or dict(DEFAULT_MAX_BARS),
        closed_candle_only=True,
        mt5_terminal_path=mt5_terminal_path,
        mt5_module=mt5_module,
        now=now,
    )
    return {
        "platform_system": snapshot.runtime.runtime_platform,
        "sys_executable": snapshot.runtime.python_executable,
        "cwd": snapshot.runtime.cwd,
        "python_version": snapshot.runtime.python_version,
        "is_wsl_detected": snapshot.runtime.is_wsl_detected,
        "mt5_import_ok": snapshot.mt5_initialized or snapshot.feed_staleness_reason != "MT5_IMPORT_FAILED",
        "mt5_initialized": snapshot.mt5_initialized,
        "mt5_terminal_info": snapshot.runtime.mt5_terminal_info,
        "mt5_terminal_info_available": snapshot.runtime.mt5_terminal_info_available,
        "mt5_terminal_path_detected": snapshot.runtime.mt5_terminal_path_detected,
        "mt5_version": snapshot.runtime.mt5_version,
        "symbol": symbol,
        "symbol_info_available": snapshot.mt5_symbol_available,
        "symbol_selected": snapshot.mt5_symbol_available,
        "tick": {
            "time": snapshot.latest_tick_server_time,
            "bid": snapshot.latest_tick_bid,
            "ask": snapshot.latest_tick_ask,
            "spread_usd": snapshot.spread_usd,
        },
        "tick_vs_latest_m1_seconds": snapshot.feed_freshness_diagnostic.get("tick_vs_latest_m1_seconds"),
        "estimated_server_offset_hours": snapshot.server_offset_hours_estimate,
        "current_forming": {
            timeframe: _candle_payload(snapshot.latest_forming.get(timeframe)) for timeframe in DEFAULT_MAX_BARS
        },
        "last_closed": {
            timeframe: _candle_payload(snapshot.latest_closed.get(timeframe)) for timeframe in DEFAULT_MAX_BARS
        },
        "feed_live_by_internal_consistency": snapshot.feed_live_by_internal_consistency,
        "feed_status": snapshot.feed_status,
        "feed_staleness_reason": snapshot.feed_staleness_reason,
        "feed_freshness_diagnostic": snapshot.feed_freshness_diagnostic,
        "recommendation": snapshot.runtime.recommended_command
        if snapshot.feed_status == "FEED_STALE_RUNTIME_MISMATCH_POSSIBLE"
        else snapshot.runtime.recommended_runtime,
        "safety": {
            "mt5_read_only": True,
            "no_order_send": True,
            "no_broker_execution": True,
            "no_live_trading": True,
        },
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, default=_json_default) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _event_csv_fields(rows: list[dict[str, Any]]) -> list[str]:
    fields = list(LIVE_EVENT_FIELDS)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    return fields


def _normalize_event_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    source_mode = str(normalized.get("source_mode") or "").strip()
    if not source_mode:
        normalized["source_mode"] = "HISTORICAL_EXPORT"
        normalized["freshness_status"] = "HISTORICAL"
        normalized["alert_eligible"] = False
    elif source_mode == "HISTORICAL_EXPORT":
        normalized["freshness_status"] = "HISTORICAL"
        normalized["alert_eligible"] = False
    return normalized


def ensure_compatibility_files(output_dir: Path, live_events: list[dict[str, Any]] | None = None) -> dict[str, int]:
    live_events = live_events or []
    compat_jsonl = output_dir / "strategy_2_observation_events.jsonl"
    compat_csv = output_dir / "strategy_2_observation_events.csv"

    rows = [_normalize_event_row(row) for row in _read_jsonl(compat_jsonl)]
    existing_ids = {str(row.get("signal_id")) for row in rows if row.get("signal_id")}
    for event in live_events:
        if str(event.get("signal_id")) not in existing_ids:
            rows.append(event)
            existing_ids.add(str(event.get("signal_id")))

    if rows:
        compat_jsonl.write_text(
            "".join(json.dumps(row, sort_keys=True, default=_json_default) + "\n" for row in rows),
            encoding="utf-8",
        )
    elif not compat_jsonl.exists():
        compat_jsonl.write_text("", encoding="utf-8")

    csv_rows = [_normalize_event_row(row) for row in _read_csv(compat_csv)]
    csv_ids = {str(row.get("signal_id")) for row in csv_rows if row.get("signal_id")}
    for event in live_events:
        if str(event.get("signal_id")) not in csv_ids:
            csv_rows.append(event)
            csv_ids.add(str(event.get("signal_id")))
    _write_csv(compat_csv, csv_rows, _event_csv_fields(csv_rows))
    return {
        "compat_jsonl_rows": len(rows),
        "compat_csv_rows": len(csv_rows),
        "historical_rows_marked_not_alert_eligible": sum(1 for row in rows if row.get("source_mode") == "HISTORICAL_EXPORT"),
    }


def _existing_live_signal_ids(output_dir: Path) -> set[str]:
    rows = _read_jsonl(output_dir / "strategy_2_live_observation_events.jsonl")
    rows.extend(_read_jsonl(output_dir / "strategy_2_observation_events.jsonl"))
    return {str(row.get("signal_id")) for row in rows if row.get("signal_id")}


def _load_live_events(output_dir: Path) -> list[dict[str, Any]]:
    return _read_jsonl(output_dir / "strategy_2_live_observation_events.jsonl")


def _write_live_event_files(output_dir: Path, events: list[dict[str, Any]]) -> None:
    jsonl_path = output_dir / "strategy_2_live_observation_events.jsonl"
    if events:
        jsonl_path.write_text(
            "".join(json.dumps(event, sort_keys=True, default=_json_default) + "\n" for event in events),
            encoding="utf-8",
        )
    elif not jsonl_path.exists():
        jsonl_path.write_text("", encoding="utf-8")
    _write_csv(output_dir / "strategy_2_live_observation_events.csv", events, LIVE_EVENT_FIELDS)


def latest_state_payload(
    *,
    symbol: str,
    snapshot: MarketSnapshot,
    scanner_status: str,
    generated_at: datetime,
    live_events: list[dict[str, Any]],
    total_heartbeats: int,
    duplicate_events_blocked: int,
) -> dict[str, Any]:
    latest_event = live_events[-1] if live_events else {}
    return {
        "generated_at_utc": isoformat_z(generated_at),
        "generated_at_europe_rome": generated_at.astimezone(ROME_TZ).isoformat(),
        "strategy_id": STRATEGY_ID,
        "strategy_status": STRATEGY_STATUS,
        "scanner_version": SCANNER_VERSION,
        "symbol": symbol,
        "mt5_initialized": snapshot.mt5_initialized,
        "feed_live_by_internal_consistency": snapshot.feed_live_by_internal_consistency,
        "scanner_status": scanner_status,
        "latest_tick_server_time": snapshot.latest_tick_server_time,
        "latest_closed_m1_time": snapshot.latest_closed_time("M1"),
        "latest_closed_m5_time": snapshot.latest_closed_time("M5"),
        "latest_closed_m15_time": snapshot.latest_closed_time("M15"),
        "latest_closed_h1_time": snapshot.latest_closed_time("H1"),
        "runtime_platform": snapshot.runtime.runtime_platform,
        "python_executable": snapshot.runtime.python_executable,
        "is_wsl_detected": snapshot.runtime.is_wsl_detected,
        "mt5_terminal_info_available": snapshot.runtime.mt5_terminal_info_available,
        "mt5_terminal_path_detected": snapshot.runtime.mt5_terminal_path_detected,
        "mt5_version": snapshot.runtime.mt5_version,
        "feed_staleness_reason": snapshot.feed_staleness_reason,
        "feed_freshness_diagnostic": snapshot.feed_freshness_diagnostic,
        "recommended_runtime": snapshot.runtime.recommended_runtime,
        "recommended_command": snapshot.runtime.recommended_command,
        "latest_live_event_time": latest_event.get("created_at_utc"),
        "latest_live_signal_id": latest_event.get("signal_id"),
        "total_live_events": len(live_events),
        "total_heartbeats": total_heartbeats,
        "duplicate_events_blocked": duplicate_events_blocked,
        "no_live_confirmation": NO_LIVE_CONFIRMATION,
        "broker_execution_allowed": False,
        "order_send_allowed": False,
        "real_money_allowed": False,
    }


def compatibility_latest_state_payload(latest_state: dict[str, Any], compat_counts: dict[str, int]) -> dict[str, Any]:
    return {
        **latest_state,
        "source_mode_summary": {
            "live_observation_events": latest_state.get("total_live_events", 0),
            "historical_export_rows_preserved": compat_counts.get("historical_rows_marked_not_alert_eligible", 0),
        },
        "latest_live_event_time": latest_state.get("latest_live_event_time"),
        "live_scanner_status": latest_state.get("scanner_status"),
        "latest_closed_m15_time": latest_state.get("latest_closed_m15_time"),
        "latest_closed_h1_time": latest_state.get("latest_closed_h1_time"),
        "alert_eligible_live_events": latest_state.get("total_live_events", 0),
    }


def _readme_text() -> str:
    return """# Strategy 2 Live Observation Scanner

This scanner is Strategy 2 observation infrastructure for XAUUSD. It reads MT5 market data in read-only mode, writes a heartbeat on every run, and writes fresh live observation events only if existing Strategy 2 runtime logic can safely produce a complete mechanical setup.

It does not trade, place orders, call broker execution, send operational Telegram signals, tune parameters, optimize thresholds, validate Strategy 2, or claim profitability.

## Live event policy

- Historical rows are `source_mode=HISTORICAL_EXPORT`, `freshness_status=HISTORICAL`, and `alert_eligible=false`.
- Fresh live rows are `source_mode=LIVE_OBSERVATION`, `freshness_status=FRESH`, and `alert_eligible=true`.
- If no safe runtime Strategy 2 setup can be produced, the scanner writes heartbeat/latest-state only and uses `LIVE_SCANNER_BLOCKED_BY_MISSING_RUNTIME_LOGIC`.

## Closed candle policy

The scanner treats MT5 position 0 as the forming candle and position 1 as the last closed candle. Strategy 2 decisions must use closed candles only.

## Feed freshness diagnostics

Feed freshness is checked with MT5-internal consistency:

- tick time versus current and closed M1 bars
- tick time versus closed M5 and M15 bars
- H1 is allowed to be old during the first hour after market open; old H1 alone becomes `FEED_LIVE_WAITING_H1_CLOSE`, not hard stale

If MT5 initializes but the candles are stale under WSL/Linux, the scanner reports `FEED_STALE_RUNTIME_MISMATCH_POSSIBLE`. Run the scanner from Windows PowerShell connected to the active MT5 terminal:

```powershell
cd "C:\\Users\\90NA00VIX\\OneDrive\\Documenti\\LAVORO\\darzo trade human-mgmt"
python scripts\\diagnose_strategy_2_mt5_feed.py --symbol XAUUSD
python scripts\\run_strategy_2_live_observation_scanner.py --symbol XAUUSD
```

## Run

```bash
python scripts/run_strategy_2_live_observation_scanner.py --symbol XAUUSD --output-dir backtests/reports/strategy_2_forward_observation_alerts
```

## Control Center files

The scanner keeps these compatibility files updated:

- `strategy_2_latest_state.json`
- `strategy_2_observation_events.jsonl`
- `strategy_2_observation_events.csv`
"""


def _summary_payload(
    *,
    generated_at: datetime,
    symbol: str,
    scanner_status: str,
    snapshot: MarketSnapshot,
    event_appended: bool,
    duplicate_event_blocked: bool,
    scanner_block_reason: str | None,
    live_events: list[dict[str, Any]],
    heartbeat: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "generated_at_utc": isoformat_z(generated_at),
        "symbol": symbol,
        "strategy_id": STRATEGY_ID,
        "strategy_status": STRATEGY_STATUS,
        "validation_status": VALIDATION_STATUS,
        "scanner_status": scanner_status,
        "mt5_initialized": snapshot.mt5_initialized,
        "mt5_symbol_available": snapshot.mt5_symbol_available,
        "feed_live_by_internal_consistency": snapshot.feed_live_by_internal_consistency,
        "feed_status": snapshot.feed_status,
        "feed_staleness_reason": snapshot.feed_staleness_reason,
        "feed_freshness_diagnostic": snapshot.feed_freshness_diagnostic,
        "runtime_platform": snapshot.runtime.runtime_platform,
        "python_executable": snapshot.runtime.python_executable,
        "is_wsl_detected": snapshot.runtime.is_wsl_detected,
        "mt5_terminal_info_available": snapshot.runtime.mt5_terminal_info_available,
        "mt5_terminal_path_detected": snapshot.runtime.mt5_terminal_path_detected,
        "mt5_version": snapshot.runtime.mt5_version,
        "recommended_runtime": snapshot.runtime.recommended_runtime,
        "recommended_command": snapshot.runtime.recommended_command,
        "latest_closed_m1_time": snapshot.latest_closed_time("M1"),
        "latest_closed_m5_time": snapshot.latest_closed_time("M5"),
        "latest_closed_m15_time": snapshot.latest_closed_time("M15"),
        "latest_closed_h1_time": snapshot.latest_closed_time("H1"),
        "fresh_live_event_generated": event_appended,
        "duplicate_event_blocked": duplicate_event_blocked,
        "total_live_events": len(live_events),
        "heartbeat_id": heartbeat.get("heartbeat_id"),
        "dry_run": dry_run,
        "dry_run_writes_report_outputs": True,
        "scanner_block_reason": scanner_block_reason,
        "missing_runtime_logic_reason": scanner_block_reason
        if scanner_status == "LIVE_SCANNER_BLOCKED_BY_MISSING_RUNTIME_LOGIC"
        else None,
        "historical_events_blocked_from_live_alerts": True,
        "no_live_confirmation": NO_LIVE_CONFIRMATION,
    }


def _write_outputs(
    *,
    output_dir: Path,
    heartbeat: dict[str, Any],
    latest_state: dict[str, Any],
    summary: dict[str, Any],
    safety: dict[str, Any],
    live_events: list[dict[str, Any]],
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    _append_jsonl(output_dir / "strategy_2_live_heartbeat.jsonl", heartbeat)
    _write_live_event_files(output_dir, live_events)
    _write_json(output_dir / "strategy_2_live_latest_state.json", latest_state)
    _write_json(output_dir / "strategy_2_live_observation_summary.json", summary)
    _write_json(output_dir / "strategy_2_live_safety_audit.json", safety)
    (output_dir / "README_strategy_2_live_observation_scanner.md").write_text(_readme_text(), encoding="utf-8")
    compat_counts = ensure_compatibility_files(output_dir, live_events=live_events)
    _write_json(output_dir / "strategy_2_latest_state.json", compatibility_latest_state_payload(latest_state, compat_counts))
    return {
        "live_events_jsonl": str(output_dir / "strategy_2_live_observation_events.jsonl"),
        "live_events_csv": str(output_dir / "strategy_2_live_observation_events.csv"),
        "live_latest_state": str(output_dir / "strategy_2_live_latest_state.json"),
        "live_heartbeat_jsonl": str(output_dir / "strategy_2_live_heartbeat.jsonl"),
        "live_summary": str(output_dir / "strategy_2_live_observation_summary.json"),
        "live_safety_audit": str(output_dir / "strategy_2_live_safety_audit.json"),
        "readme": str(output_dir / "README_strategy_2_live_observation_scanner.md"),
        "compat_events_jsonl": str(output_dir / "strategy_2_observation_events.jsonl"),
        "compat_events_csv": str(output_dir / "strategy_2_observation_events.csv"),
        "compat_latest_state": str(output_dir / "strategy_2_latest_state.json"),
    }


def _scanner_status_for_snapshot(snapshot: MarketSnapshot, *, heartbeat_only: bool, runtime_logic_available: bool) -> tuple[str, str | None]:
    if not snapshot.mt5_initialized:
        return "MT5_UNAVAILABLE", snapshot.error
    if not snapshot.mt5_symbol_available:
        return "SYMBOL_UNAVAILABLE", snapshot.error
    if snapshot.feed_status == "FEED_STALE_RUNTIME_MISMATCH_POSSIBLE":
        return "FEED_STALE_RUNTIME_MISMATCH_POSSIBLE", snapshot.feed_staleness_reason
    if snapshot.feed_status == "FEED_STALE":
        return "FEED_STALE", snapshot.feed_staleness_reason or snapshot.error
    if snapshot.feed_status == "FEED_LIVE_WAITING_M15_CLOSE":
        return "FEED_LIVE_WAITING_M15_CLOSE", snapshot.feed_staleness_reason
    if snapshot.feed_status == "FEED_LIVE_WAITING_H1_CLOSE":
        return "FEED_LIVE_WAITING_H1_CLOSE", snapshot.feed_staleness_reason
    if not snapshot.latest_closed_time("M15"):
        return "FEED_LIVE_WAITING_M15_CLOSE", None
    if not snapshot.latest_closed_time("H1"):
        return "FEED_LIVE_WAITING_H1_CLOSE", None
    if heartbeat_only:
        return "FEED_LIVE_NO_SETUP", None
    if not runtime_logic_available:
        return "LIVE_SCANNER_BLOCKED_BY_MISSING_RUNTIME_LOGIC", missing_runtime_logic_reason()
    return "FEED_LIVE_NO_SETUP", None


def run_live_observation_scanner(
    *,
    symbol: str = "XAUUSD",
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    max_bars: dict[str, int] | None = None,
    closed_candle_only: bool = True,
    heartbeat_only: bool = False,
    dry_run: bool = False,
    mt5_terminal_path: str | None = None,
    mt5_module: Any | None = None,
    setup_detector: Callable[[MarketSnapshot], dict[str, Any] | None] | None = None,
    now: Callable[[], datetime] = utc_now,
) -> LiveScannerResult:
    generated_at = now()
    output_path = Path(output_dir)
    max_bars = max_bars or dict(DEFAULT_MAX_BARS)
    snapshot = read_mt5_snapshot(
        symbol=symbol,
        max_bars=max_bars,
        closed_candle_only=closed_candle_only,
        mt5_terminal_path=mt5_terminal_path,
        mt5_module=mt5_module,
        now=now,
    )
    runtime_logic_available = setup_detector is not None
    scanner_status, scanner_block_reason = _scanner_status_for_snapshot(
        snapshot,
        heartbeat_only=heartbeat_only,
        runtime_logic_available=runtime_logic_available,
    )

    event_appended = False
    duplicate_event_blocked = False
    live_events = _load_live_events(output_path) if output_path.exists() else []

    if scanner_status == "FEED_LIVE_NO_SETUP" and not heartbeat_only and setup_detector is not None:
        candidate = setup_detector(snapshot)
        if candidate:
            event = build_live_observation_event(
                symbol=symbol,
                direction=str(candidate.get("direction") or ""),
                snapshot=snapshot,
                candidate=candidate,
                created_at=generated_at,
            )
            existing_ids = _existing_live_signal_ids(output_path) if output_path.exists() else set()
            if event["signal_id"] in existing_ids:
                duplicate_event_blocked = True
            else:
                live_events.append(event)
                event_appended = True
                scanner_status = "FEED_LIVE_SETUP_DETECTED"

    heartbeat = build_heartbeat(symbol, snapshot, scanner_status, generated_at)
    total_heartbeats = len(_read_jsonl(output_path / "strategy_2_live_heartbeat.jsonl")) + 1 if output_path.exists() else 1
    duplicate_count_prior = 0
    prior_latest = output_path / "strategy_2_live_latest_state.json"
    if prior_latest.exists():
        try:
            duplicate_count_prior = int(json.loads(prior_latest.read_text(encoding="utf-8")).get("duplicate_events_blocked") or 0)
        except (ValueError, json.JSONDecodeError):
            duplicate_count_prior = 0
    duplicate_count = duplicate_count_prior + (1 if duplicate_event_blocked else 0)
    latest_state = latest_state_payload(
        symbol=symbol,
        snapshot=snapshot,
        scanner_status=scanner_status,
        generated_at=generated_at,
        live_events=live_events,
        total_heartbeats=total_heartbeats,
        duplicate_events_blocked=duplicate_count,
    )
    safety = safety_audit(isoformat_z(generated_at) or "")
    summary = _summary_payload(
        generated_at=generated_at,
        symbol=symbol,
        scanner_status=scanner_status,
        snapshot=snapshot,
        event_appended=event_appended,
        duplicate_event_blocked=duplicate_event_blocked,
        scanner_block_reason=scanner_block_reason,
        live_events=live_events,
        heartbeat=heartbeat,
        dry_run=dry_run,
    )
    paths: dict[str, str] = {}
    paths = _write_outputs(
        output_dir=output_path,
        heartbeat=heartbeat,
        latest_state=latest_state,
        summary=summary,
        safety=safety,
        live_events=live_events,
    )
    return LiveScannerResult(
        scanner_status=scanner_status,
        heartbeat=heartbeat,
        latest_state=latest_state,
        summary=summary,
        safety_audit=safety,
        event_appended=event_appended,
        duplicate_event_blocked=duplicate_event_blocked,
        paths=paths,
    )


def result_to_dict(result: LiveScannerResult) -> dict[str, Any]:
    return {
        "scanner_status": result.scanner_status,
        "event_appended": result.event_appended,
        "duplicate_event_blocked": result.duplicate_event_blocked,
        "heartbeat": result.heartbeat,
        "latest_state": result.latest_state,
        "summary": result.summary,
        "safety_audit": result.safety_audit,
        "paths": result.paths,
    }
