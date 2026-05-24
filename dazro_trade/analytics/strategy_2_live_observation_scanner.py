from __future__ import annotations

import csv
import hashlib
import json
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
class MarketSnapshot:
    symbol: str
    mt5_initialized: bool
    mt5_symbol_available: bool
    latest_tick_server_time: str | None
    latest_tick_bid: float | None
    latest_tick_ask: float | None
    spread_usd: float | None
    latest_closed: dict[str, ClosedCandle]
    server_offset_hours_estimate: float | None
    feed_live_by_internal_consistency: bool
    error: str | None = None

    def latest_closed_time(self, timeframe: str) -> str | None:
        candle = self.latest_closed.get(timeframe)
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


def _closed_candle_from_rates(rates: Any, timeframe: str, *, closed_candle_only: bool) -> ClosedCandle:
    position = 1 if closed_candle_only else 0
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


def _feed_live_by_internal_consistency(snapshot: MarketSnapshot, now_utc: datetime) -> bool:
    if not snapshot.latest_tick_server_time:
        return False
    offset = snapshot.server_offset_hours_estimate
    checks = [
        _is_recent(snapshot.latest_tick_server_time, now_utc, 20 * 60, server_offset_hours_estimate=offset),
        _is_recent(snapshot.latest_closed_time("M1"), now_utc, 20 * 60, server_offset_hours_estimate=offset),
        _is_recent(snapshot.latest_closed_time("M5"), now_utc, 45 * 60, server_offset_hours_estimate=offset),
        _is_recent(snapshot.latest_closed_time("M15"), now_utc, 120 * 60, server_offset_hours_estimate=offset),
    ]
    return all(checks)


def read_mt5_snapshot(
    *,
    symbol: str,
    max_bars: dict[str, int],
    closed_candle_only: bool = True,
    mt5_module: Any | None = None,
    now: Callable[[], datetime] = utc_now,
) -> MarketSnapshot:
    current_time = now()
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
            latest_closed={},
            server_offset_hours_estimate=None,
            feed_live_by_internal_consistency=False,
            error=str(exc),
        )

    initialized = bool(mt5.initialize())
    if not initialized:
        return MarketSnapshot(
            symbol=symbol,
            mt5_initialized=False,
            mt5_symbol_available=False,
            latest_tick_server_time=None,
            latest_tick_bid=None,
            latest_tick_ask=None,
            spread_usd=None,
            latest_closed={},
            server_offset_hours_estimate=None,
            feed_live_by_internal_consistency=False,
            error="mt5.initialize returned false",
        )

    try:
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
                latest_closed={},
                server_offset_hours_estimate=None,
                feed_live_by_internal_consistency=False,
                error="symbol unavailable or could not be selected",
            )

        tick = mt5.symbol_info_tick(symbol)
        tick_time = _timestamp_from_epoch(_tick_value(tick, "time"))
        tick_bid = _as_float(_tick_value(tick, "bid"))
        tick_ask = _as_float(_tick_value(tick, "ask"))
        spread = round(tick_ask - tick_bid, 5) if tick_bid is not None and tick_ask is not None else None

        latest_closed: dict[str, ClosedCandle] = {}
        for timeframe, mt5_timeframe in _timeframe_constants(mt5).items():
            rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, max_bars.get(timeframe, DEFAULT_MAX_BARS[timeframe]))
            latest_closed[timeframe] = _closed_candle_from_rates(
                rates,
                timeframe,
                closed_candle_only=closed_candle_only,
            )

        snapshot = MarketSnapshot(
            symbol=symbol,
            mt5_initialized=True,
            mt5_symbol_available=True,
            latest_tick_server_time=tick_time,
            latest_tick_bid=tick_bid,
            latest_tick_ask=tick_ask,
            spread_usd=spread,
            latest_closed=latest_closed,
            server_offset_hours_estimate=_estimate_server_offset_hours(tick_time, current_time),
            feed_live_by_internal_consistency=False,
            error=None,
        )
        return MarketSnapshot(
            symbol=snapshot.symbol,
            mt5_initialized=snapshot.mt5_initialized,
            mt5_symbol_available=snapshot.mt5_symbol_available,
            latest_tick_server_time=snapshot.latest_tick_server_time,
            latest_tick_bid=snapshot.latest_tick_bid,
            latest_tick_ask=snapshot.latest_tick_ask,
            spread_usd=snapshot.spread_usd,
            latest_closed=snapshot.latest_closed,
            server_offset_hours_estimate=snapshot.server_offset_hours_estimate,
            feed_live_by_internal_consistency=_feed_live_by_internal_consistency(snapshot, current_time),
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
    missing_runtime_logic: str | None,
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
        "missing_runtime_logic_reason": missing_runtime_logic,
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
    if not snapshot.feed_live_by_internal_consistency:
        return "FEED_STALE", snapshot.error
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
        mt5_module=mt5_module,
        now=now,
    )
    runtime_logic_available = setup_detector is not None
    scanner_status, missing_runtime = _scanner_status_for_snapshot(
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
        missing_runtime_logic=missing_runtime,
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
