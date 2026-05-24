from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd

from dazro_trade.analysis.strategy_2_mechanical_spec import (
    MechanicalSpecConfig,
    evaluate_context_model,
    references_for_context,
)


STRATEGY_STATUS = "OBSERVATION_ONLY"
VALIDATION_STATUS = "RESEARCH_ONLY"
EXECUTION_STATUS = "NOT_EXECUTED"
ALERT_DISCLAIMER = "OBSERVATION ONLY - compare with Adelin manual entry - not validated - no broker execution."

DEFAULT_RUNTIME_PROFILE = {
    "profile_source": "strategy_2_containing_diagnostic_unit_corrected",
    "conservative_sl": 22.6163,
    "tp_quartiles": {"tp1": 1.6798, "tp2": 3.3595, "tp3": 5.0393, "tp4": 6.719},
    "mae_avg_usd": 4.6471,
    "min_distribution_usd": 1.0,
    "level_take_pips": 1.0,
    "reentry_pips": 1.0,
    "pip_factor": 10.0,
}


class RuntimeDetectorStatus(str, Enum):
    RUNTIME_NO_SETUP = "RUNTIME_NO_SETUP"
    RUNTIME_SETUP_CANDIDATE = "RUNTIME_SETUP_CANDIDATE"
    RUNTIME_WAITING_M15_CONFIRMATION = "RUNTIME_WAITING_M15_CONFIRMATION"
    RUNTIME_WAITING_H1_CONTEXT = "RUNTIME_WAITING_H1_CONTEXT"
    RUNTIME_BLOCKED_MISSING_REQUIRED_FIELDS = "RUNTIME_BLOCKED_MISSING_REQUIRED_FIELDS"
    RUNTIME_BLOCKED_INSUFFICIENT_HISTORY = "RUNTIME_BLOCKED_INSUFFICIENT_HISTORY"
    RUNTIME_BLOCKED_UNSUPPORTED_CURRENT_LOGIC = "RUNTIME_BLOCKED_UNSUPPORTED_CURRENT_LOGIC"


@dataclass(frozen=True)
class RuntimeCandidate:
    symbol: str
    direction: str
    candidate_time: str
    H1_reference_level: float
    H1_reference_candle_time: str | None
    H1_dominant_flag: bool
    M15_reference_level: float | None
    M15_invalidation_level: float | None
    M15_invalidation_happened_first: bool
    liquidity_side: str | None
    sweep_distance: float | None
    MAE_entry_candidate: float | None
    MAE_reached: bool
    reentry_confirmed: bool
    reentry_inside_H1_range_pips: float | None
    strategy_2_reason_code: str | None
    setup_description: str
    theoretical_entry: float
    theoretical_SL: float
    theoretical_TP1: float
    theoretical_TP2: float
    theoretical_TP3: float
    theoretical_TP4: float
    theoretical_RR_TP1: float
    theoretical_RR_TP2: float
    theoretical_RR_TP3: float
    theoretical_RR_TP4: float
    source_logic: str = "strategy_2_runtime_detector_foundation"
    source_mode: str = "LIVE_OBSERVATION"
    freshness_status: str = "FRESH"
    strategy_status: str = STRATEGY_STATUS
    validation_status: str = VALIDATION_STATUS
    execution_status: str = EXECUTION_STATUS
    broker_execution_allowed: bool = False
    order_send_allowed: bool = False
    real_money_allowed: bool = False
    alert_disclaimer: str = ALERT_DISCLAIMER

    def to_event_candidate(self) -> dict[str, Any]:
        return {
            "timestamp_server": self.candidate_time,
            "direction": self.direction,
            "theoretical_entry": self.theoretical_entry,
            "theoretical_SL": self.theoretical_SL,
            "theoretical_TP1": self.theoretical_TP1,
            "theoretical_TP2": self.theoretical_TP2,
            "theoretical_TP3": self.theoretical_TP3,
            "theoretical_TP4": self.theoretical_TP4,
            "theoretical_RR_TP1": self.theoretical_RR_TP1,
            "theoretical_RR_TP2": self.theoretical_RR_TP2,
            "theoretical_RR_TP3": self.theoretical_RR_TP3,
            "theoretical_RR_TP4": self.theoretical_RR_TP4,
            "H1_reference_level": self.H1_reference_level,
            "H1_reference_candle_time": self.H1_reference_candle_time,
            "H1_dominant_flag": self.H1_dominant_flag,
            "M15_reference_level": self.M15_reference_level,
            "M15_invalidation_level": self.M15_invalidation_level,
            "M15_invalidation_happened_first": self.M15_invalidation_happened_first,
            "liquidity_side": self.liquidity_side,
            "sweep_distance": self.sweep_distance,
            "MAE_entry_candidate": self.MAE_entry_candidate,
            "MAE_reached": self.MAE_reached,
            "reentry_confirmed": self.reentry_confirmed,
            "reentry_inside_H1_range_pips": self.reentry_inside_H1_range_pips,
            "strategy_2_reason_code": self.strategy_2_reason_code,
            "setup_description": self.setup_description,
            "source_logic": self.source_logic,
            "broker_execution_allowed": False,
            "order_send_allowed": False,
            "real_money_allowed": False,
            "alert_disclaimer": self.alert_disclaimer,
        }


@dataclass(frozen=True)
class RuntimeDetectionResult:
    status: RuntimeDetectorStatus
    candidates: list[RuntimeCandidate] = field(default_factory=list)
    block_reason: str | None = None
    missing_required_fields: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _to_frame(rows: Any) -> pd.DataFrame:
    if rows is None:
        return pd.DataFrame()
    if isinstance(rows, pd.DataFrame):
        frame = rows.copy()
    else:
        frame = pd.DataFrame(list(rows))
    if frame.empty:
        return frame
    required = {"time", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        return pd.DataFrame()
    frame = frame[["time", "open", "high", "low", "close"]].copy()
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["time"]).copy()
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close"]).sort_values("time").reset_index(drop=True)
    return frame


def _filter_as_of(frame: pd.DataFrame, as_of: pd.Timestamp | None) -> pd.DataFrame:
    if frame.empty or as_of is None:
        return frame
    return frame[frame["time"] <= as_of].copy().reset_index(drop=True)


def _as_of_timestamp(now_context: dict[str, Any] | None, *frames: pd.DataFrame) -> pd.Timestamp | None:
    raw = (now_context or {}).get("as_of_time") or (now_context or {}).get("current_time")
    if raw:
        ts = pd.Timestamp(raw)
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    candidates = [pd.Timestamp(frame["time"].max()) for frame in frames if not frame.empty]
    return max(candidates) if candidates else None


def _active_h1_open(m15: pd.DataFrame) -> pd.Timestamp | None:
    if m15.empty:
        return None
    latest_m15 = pd.Timestamp(m15["time"].max())
    return latest_m15.floor("h")


def _context_end(context_open: pd.Timestamp) -> pd.Timestamp:
    return context_open + pd.Timedelta(hours=1)


def _profile_value(profile: dict[str, Any], key: str) -> Any:
    return profile.get(key, DEFAULT_RUNTIME_PROFILE.get(key))


def _runtime_config(profile: dict[str, Any]) -> MechanicalSpecConfig:
    return MechanicalSpecConfig(
        pip_factor=float(_profile_value(profile, "pip_factor")),
        h1_reference_mode="both",
        m15_filter_model="containing",
        mae_avg_usd=float(_profile_value(profile, "mae_avg_usd")),
        min_distribution_usd=float(_profile_value(profile, "min_distribution_usd")),
        level_take_pips=float(_profile_value(profile, "level_take_pips")),
        reentry_pips=float(_profile_value(profile, "reentry_pips")),
    )


def _round_price(value: float | None) -> float | None:
    return round(float(value), 4) if value is not None else None


def _rr(direction: str, entry: float | None, stop: float | None, target: float | None) -> float | None:
    if entry is None or stop is None or target is None:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    reward = target - entry if direction == "LONG" else entry - target
    return round(reward / risk, 4)


def _m15_invalidation_level(row: dict[str, Any], direction: str) -> float | None:
    if direction == "LONG":
        return _as_float(row.get("relevant_m15_high"))
    if direction == "SHORT":
        return _as_float(row.get("relevant_m15_low"))
    return None


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _theoretical_prices(row: dict[str, Any], profile: dict[str, Any], config: MechanicalSpecConfig) -> dict[str, float | None]:
    direction = str(row.get("direction") or "").upper()
    h1_level = _as_float(row.get("h1_liquidity_level"))
    sl_distance = _as_float(_profile_value(profile, "conservative_sl"))
    tp_distances = _profile_value(profile, "tp_quartiles") or {}
    reentry_usd = round(float(config.reentry_pips) / float(config.pip_factor), 4)
    mae_avg = float(config.mae_avg_usd)

    if h1_level is None:
        return {}
    entry = h1_level + reentry_usd if direction == "LONG" else h1_level - reentry_usd if direction == "SHORT" else None
    stop = h1_level - sl_distance if direction == "LONG" and sl_distance is not None else h1_level + sl_distance if direction == "SHORT" and sl_distance is not None else None
    mae_candidate = h1_level - mae_avg if direction == "LONG" else h1_level + mae_avg if direction == "SHORT" else None
    targets: dict[str, float | None] = {}
    for key in ("tp1", "tp2", "tp3", "tp4"):
        distance = _as_float(tp_distances.get(key))
        targets[key] = h1_level + distance if direction == "LONG" and distance is not None else h1_level - distance if direction == "SHORT" and distance is not None else None
    return {
        "entry": _round_price(entry),
        "stop": _round_price(stop),
        "tp1": _round_price(targets.get("tp1")),
        "tp2": _round_price(targets.get("tp2")),
        "tp3": _round_price(targets.get("tp3")),
        "tp4": _round_price(targets.get("tp4")),
        "mae_candidate": _round_price(mae_candidate),
    }


def _candidate_from_row(row: dict[str, Any], profile: dict[str, Any], config: MechanicalSpecConfig) -> tuple[RuntimeCandidate | None, list[str]]:
    direction = str(row.get("direction") or "").upper()
    prices = _theoretical_prices(row, profile, config)
    rr_values = {key: _rr(direction, prices.get("entry"), prices.get("stop"), prices.get(key)) for key in ("tp1", "tp2", "tp3", "tp4")}
    missing = []
    for key, field_name in (
        ("entry", "theoretical_entry"),
        ("stop", "theoretical_SL"),
        ("tp1", "theoretical_TP1"),
        ("tp2", "theoretical_TP2"),
        ("tp3", "theoretical_TP3"),
        ("tp4", "theoretical_TP4"),
    ):
        if prices.get(key) is None:
            missing.append(field_name)
    for index, key in enumerate(("tp1", "tp2", "tp3", "tp4"), start=1):
        if rr_values.get(key) is None:
            missing.append(f"theoretical_RR_TP{index}")
    if missing:
        return None, missing

    candidate_time = str(row.get("entry_timestamp") or row.get("range_reentry_timestamp") or row.get("h1_level_take_timestamp") or "")
    return RuntimeCandidate(
        symbol=str(row.get("symbol") or "XAUUSD"),
        direction=direction,
        candidate_time=candidate_time,
        H1_reference_level=float(row["h1_liquidity_level"]),
        H1_reference_candle_time=row.get("h1_reference_timestamp"),
        H1_dominant_flag=str(row.get("h1_reference_type") or "") == "dominant_h1",
        M15_reference_level=_m15_invalidation_level(row, direction),
        M15_invalidation_level=_m15_invalidation_level(row, direction),
        M15_invalidation_happened_first=bool(row.get("m15_sequence_valid") is False),
        liquidity_side=row.get("h1_liquidity_side"),
        sweep_distance=_as_float(row.get("manipulation_depth_usd")),
        MAE_entry_candidate=prices["mae_candidate"],
        MAE_reached=bool(row.get("mae_reached") is True),
        reentry_confirmed=bool(row.get("range_reentry_reached") is True or row.get("entry_valid") is True),
        reentry_inside_H1_range_pips=_as_float(row.get("range_reentry_required_pips")),
        strategy_2_reason_code=row.get("sample_reason_codes") or row.get("entry_status"),
        setup_description=(
            "Strategy 2 runtime observation candidate; model=containing; "
            f"status={row.get('sample_status')}; entry_status={row.get('entry_status')}."
        ),
        theoretical_entry=float(prices["entry"]),
        theoretical_SL=float(prices["stop"]),
        theoretical_TP1=float(prices["tp1"]),
        theoretical_TP2=float(prices["tp2"]),
        theoretical_TP3=float(prices["tp3"]),
        theoretical_TP4=float(prices["tp4"]),
        theoretical_RR_TP1=float(rr_values["tp1"]),
        theoretical_RR_TP2=float(rr_values["tp2"]),
        theoretical_RR_TP3=float(rr_values["tp3"]),
        theoretical_RR_TP4=float(rr_values["tp4"]),
    ), []


def explain_runtime_block_reason(result: RuntimeDetectionResult) -> str:
    if result.block_reason:
        return result.block_reason
    if result.missing_required_fields:
        return "Missing required fields: " + ", ".join(result.missing_required_fields)
    return result.status.value


def build_runtime_observation_event(candidate: RuntimeCandidate) -> dict[str, Any]:
    return candidate.to_event_candidate()


def detect_strategy_2_runtime_candidates(
    *,
    symbol: str,
    closed_h1: Any,
    closed_m15: Any,
    closed_m5: Any | None = None,
    closed_m1: Any | None = None,
    profile: dict[str, Any] | None = None,
    now_context: dict[str, Any] | None = None,
) -> RuntimeDetectionResult:
    profile = {**DEFAULT_RUNTIME_PROFILE, **(profile or {})}
    h1 = _to_frame(closed_h1)
    m15 = _to_frame(closed_m15)
    m1 = _to_frame(closed_m1)
    as_of = _as_of_timestamp(now_context, m1, m15, h1)
    h1 = _filter_as_of(h1, as_of)
    m15 = _filter_as_of(m15, as_of)
    m1 = _filter_as_of(m1, as_of)

    diagnostics: dict[str, Any] = {
        "symbol": symbol,
        "as_of_time": as_of.isoformat() if as_of is not None else None,
        "closed_h1_count": len(h1),
        "closed_m15_count": len(m15),
        "closed_m1_count": len(m1),
        "m15_model": "containing",
        "source_logic": "strategy_2_mechanical_spec.evaluate_context_model",
    }

    if h1.empty:
        return RuntimeDetectionResult(
            RuntimeDetectorStatus.RUNTIME_WAITING_H1_CONTEXT,
            block_reason="WAITING_FOR_CLOSED_H1_REFERENCE",
            diagnostics=diagnostics,
        )
    if m15.empty:
        return RuntimeDetectionResult(
            RuntimeDetectorStatus.RUNTIME_WAITING_M15_CONFIRMATION,
            block_reason="WAITING_FOR_CLOSED_M15_CONTEXT",
            diagnostics=diagnostics,
        )
    if m1.empty:
        return RuntimeDetectionResult(
            RuntimeDetectorStatus.RUNTIME_BLOCKED_UNSUPPORTED_CURRENT_LOGIC,
            block_reason="M1_CLOSED_CANDLES_REQUIRED_FOR_EXISTING_MAE_REENTRY_LOGIC",
            diagnostics=diagnostics,
        )

    active_open = _active_h1_open(m15)
    if active_open is None:
        return RuntimeDetectionResult(
            RuntimeDetectorStatus.RUNTIME_WAITING_M15_CONFIRMATION,
            block_reason="ACTIVE_H1_CONTEXT_NOT_DERIVABLE_FROM_M15",
            diagnostics=diagnostics,
        )
    active_end = _context_end(active_open)
    latest_h1_time = pd.Timestamp(h1["time"].max())
    diagnostics.update(
        {
            "active_h1_open": active_open.isoformat(),
            "active_h1_end": active_end.isoformat(),
            "latest_closed_h1_time": latest_h1_time.isoformat(),
        }
    )
    if latest_h1_time < active_open - pd.Timedelta(hours=1):
        return RuntimeDetectionResult(
            RuntimeDetectorStatus.RUNTIME_WAITING_H1_CONTEXT,
            block_reason="LATEST_CLOSED_H1_NOT_ADJACENT_TO_ACTIVE_CONTEXT",
            diagnostics=diagnostics,
        )

    config = _runtime_config(profile)
    references = references_for_context(
        h1,
        len(h1),
        mode="both",
        dominant_contained_count=config.dominant_contained_count,
        dominant_lookback=config.dominant_lookback,
    )
    if not references:
        return RuntimeDetectionResult(
            RuntimeDetectorStatus.RUNTIME_WAITING_H1_CONTEXT,
            block_reason="NO_H1_REFERENCE_AVAILABLE",
            diagnostics=diagnostics,
        )

    m1_window = m1[(m1["time"] >= active_open) & (m1["time"] < active_end)].copy()
    m15_window = m15[(m15["time"] >= active_open - pd.Timedelta(minutes=15)) & (m15["time"] < active_end)].copy()
    if m1_window.empty:
        return RuntimeDetectionResult(
            RuntimeDetectorStatus.RUNTIME_NO_SETUP,
            block_reason="NO_CLOSED_M1_CANDLES_IN_ACTIVE_H1_CONTEXT",
            diagnostics=diagnostics,
        )

    candidates: list[RuntimeCandidate] = []
    missing_fields: list[str] = []
    evaluated_rows: list[dict[str, Any]] = []
    for reference in references:
        h1_context = pd.Series({"time": active_open})
        row = evaluate_context_model(
            symbol=symbol,
            h1_context=h1_context,
            reference=reference,
            m1_window=m1_window,
            m15=m15_window,
            model="containing",
            config=config,
        )
        evaluated_rows.append(
            {
                "h1_reference_type": row.get("h1_reference_type"),
                "sample_status": row.get("sample_status"),
                "entry_status": row.get("entry_status"),
                "sample_reason_codes": row.get("sample_reason_codes"),
            }
        )
        if row.get("sample_status") != "VALID_SAMPLE_TRADE_TRIGGERED" or row.get("entry_valid") is not True:
            continue
        candidate, missing = _candidate_from_row(row, profile, config)
        if candidate:
            candidates.append(candidate)
        else:
            missing_fields.extend(missing)

    diagnostics["evaluated_rows"] = evaluated_rows
    if candidates:
        return RuntimeDetectionResult(
            RuntimeDetectorStatus.RUNTIME_SETUP_CANDIDATE,
            candidates=candidates,
            diagnostics=diagnostics,
        )
    if missing_fields:
        return RuntimeDetectionResult(
            RuntimeDetectorStatus.RUNTIME_BLOCKED_MISSING_REQUIRED_FIELDS,
            block_reason="CRITICAL_THEORETICAL_FIELDS_NOT_COMPUTABLE",
            missing_required_fields=sorted(set(missing_fields)),
            diagnostics=diagnostics,
        )
    return RuntimeDetectionResult(
        RuntimeDetectorStatus.RUNTIME_NO_SETUP,
        block_reason="NO_VALID_CONTAINING_MODEL_RUNTIME_SETUP",
        diagnostics=diagnostics,
    )
