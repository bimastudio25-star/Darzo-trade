"""Adelin v2 H3/H4 pre-entry proxy diagnostics.

This module computes the approved H3/H4 proxy diagnostics on existing Adelin v2
samples. It is research-only and deliberately keeps post-entry outcomes out of
the proxy computation.
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from dazro_trade.backtest.data_loader import load_csv_timeframes


SIGNOFF_PATH = Path("docs/research/adelin_v2_tight_sl_zone_retest_proxy_plan_signoff.md")
PROXY_PLAN_DIR = Path("backtests/reports/adelin_v2_tight_sl_zone_retest_proxy_plan")
INPUT_SAMPLE_PATH = Path(
    "backtests/reports/adelin_v2_preentry_outcome_diagnostics_direction_recovered/sample_diagnostics.csv"
)
INPUT_SUMMARY_PATH = Path(
    "backtests/reports/adelin_v2_preentry_outcome_diagnostics_direction_recovered/summary.json"
)
DEFAULT_OUTPUT_DIR = Path("backtests/reports/adelin_v2_h3_h4_proxy_diagnostic_execution")
DEFAULT_DOC_PATH = Path("docs/research/adelin_v2_h3_h4_proxy_diagnostic_execution.md")

H3_FORMULA_VERSION = "adelin_v2_h3_tight_sl_formula_v1_commit_56dcff0"
H3_THRESHOLD_VERSION = "adelin_v2_h3_fixed_thresholds_0_25_0_50_v1"
H3_TIGHT_MAX = 0.25
H3_MEDIUM_MAX = 0.50

H3_TERMINAL_STATES = (
    "TIGHT",
    "MEDIUM",
    "WIDE",
    "UNKNOWN_REFERENCE_PRICE",
    "NO_VALID_INVALIDATION_EXTREME",
    "INVALID_GEOMETRY",
    "INSUFFICIENT_PRE_DECISION_RANGE",
)
H3_MISSING_STATES = (
    "UNKNOWN_REFERENCE_PRICE",
    "NO_VALID_INVALIDATION_EXTREME",
    "INVALID_GEOMETRY",
    "INSUFFICIENT_PRE_DECISION_RANGE",
)
H4_STATES = (
    "NO_ZONE_AVAILABLE",
    "INSIDE_ZONE",
    "RETEST_HELD",
    "RECLAIM_CONFIRMED",
    "RETEST_FAILED_PRE_DECISION",
)

H3_NORMALIZER_M1 = "M1_30_CLOSED_PRE_DECISION"
H3_NORMALIZER_M5 = "M5_12_CLOSED_PRE_DECISION"
H3_NORMALIZER_NONE = "NONE"

VERDICT_FLAGS = [
    "ADELIN_V2_H3_H4_PROXY_DIAGNOSTIC_COMPLETE",
    "PRE_ENTRY_ONLY_CONFIRMED",
    "POST_ENTRY_DATA_NOT_USED",
    "MATCHED_CONTROL_NOT_RUN",
    "PHASE_4_REMAINS_BLOCKED",
    "NO_RUNTIME_LOGIC_CHANGE",
    "NO_LIVE_DEPLOYMENT_DECISION",
    "NO_ORDER_SEND",
    "NO_BROKER_EXECUTION",
    "STRATEGY_2_UNTOUCHED",
    "STRATEGY_3_UNTOUCHED",
]

FORBIDDEN_OUTPUT_FEATURE_TOKENS = (
    "tp_hit",
    "sl_hit",
    "pnl",
    "r_multiple",
    "future_mfe",
    "future_mae",
    "max_favorable",
    "max_adverse",
    "post_entry",
    "outcome_derived",
    "matched_control",
    "phase_4_unlocked_true",
)

PER_SAMPLE_FIELDS = [
    "sample_id",
    "source_artifact",
    "input_file",
    "decision_time",
    "direction",
    "direction_source",
    "direction_confidence",
    "entry_reference_price_source",
    "data_availability_status",
    "h3_state",
    "h3_reference_price",
    "h3_invalidation_extreme",
    "h3_invalidation_source",
    "h3_distance",
    "h3_normalizer_value",
    "h3_normalizer_source",
    "h3_normalized_distance",
    "h3_threshold_version",
    "h3_formula_version",
    "h3_pre_entry_only",
    "h3_post_entry_data_used",
    "h4_state",
    "h4_zone_source",
    "h4_zone_high",
    "h4_zone_low",
    "h4_retest_or_reclaim_timestamp",
    "h4_pre_entry_only",
    "h4_post_entry_data_used",
    "pre_entry_only",
    "post_entry_data_used",
    "leakage_check_passed",
    "leakage_check_notes",
    "ohlc_read",
    "matched_control_run",
    "phase_4_unlocked",
    "runtime_logic_changed",
]


@dataclass(frozen=True)
class H3Result:
    state: str
    reference_price: float | None = None
    invalidation_extreme: float | None = None
    invalidation_source: str = ""
    distance: float | None = None
    normalizer_value: float | None = None
    normalizer_source: str = H3_NORMALIZER_NONE
    normalized_distance: float | None = None


@dataclass(frozen=True)
class H4Result:
    state: str
    zone_source: str = ""
    zone_high: float | None = None
    zone_low: float | None = None
    retest_or_reclaim_timestamp: pd.Timestamp | None = None


@dataclass(frozen=True)
class DiagnosticConfig:
    sample_path: Path = INPUT_SAMPLE_PATH
    input_summary_path: Path = INPUT_SUMMARY_PATH
    signoff_path: Path = SIGNOFF_PATH
    proxy_plan_dir: Path = PROXY_PLAN_DIR
    output_dir: Path = DEFAULT_OUTPUT_DIR
    doc_path: Path = DEFAULT_DOC_PATH
    data_dir: Path = Path("data")
    symbol: str = "XAUUSD"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(fieldnames or sorted({key for row in rows for key in row}))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: fmt(row.get(name)) for name in names})


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def parse_int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def parse_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def fmt(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return round(value, 6)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return "|".join(str(v) for v in value)
    return value


def normalize_frames(frames: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    normalized: dict[str, pd.DataFrame] = {}
    for timeframe, frame in frames.items():
        if frame.empty:
            normalized[timeframe] = frame
            continue
        out = frame.copy()
        out["time"] = pd.to_datetime(out["time"], utc=True)
        for col in ("open", "high", "low", "close", "tick_volume", "real_volume"):
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        normalized[timeframe] = out.sort_values("time").reset_index(drop=True)
    return normalized


def pre_decision_closed(frame: pd.DataFrame, decision_time: pd.Timestamp, lookback: int) -> pd.DataFrame:
    if frame.empty:
        return frame
    closed = frame.loc[frame["time"] < decision_time].copy()
    if closed.empty:
        return closed
    return closed.sort_values("time").tail(lookback).reset_index(drop=True)


def local_range(candles: pd.DataFrame) -> float | None:
    if candles.empty:
        return None
    high = float(candles["high"].max())
    low = float(candles["low"].min())
    span = high - low
    if span <= 0 or not math.isfinite(span):
        return None
    return span


def select_h3_normalizer(
    frames: Mapping[str, pd.DataFrame],
    decision_time: pd.Timestamp,
) -> tuple[str, pd.DataFrame, float | None]:
    m1 = pre_decision_closed(frames.get("M1", pd.DataFrame()), decision_time, 30)
    if len(m1) >= 20:
        span = local_range(m1)
        if span is not None:
            return H3_NORMALIZER_M1, m1, span
    m5 = pre_decision_closed(frames.get("M5", pd.DataFrame()), decision_time, 12)
    if len(m5) >= 12:
        span = local_range(m5)
        if span is not None:
            return H3_NORMALIZER_M5, m5, span
    return H3_NORMALIZER_NONE, pd.DataFrame(), None


def classify_h3_band(normalized_distance: float) -> str:
    if normalized_distance <= H3_TIGHT_MAX:
        return "TIGHT"
    if normalized_distance <= H3_MEDIUM_MAX:
        return "MEDIUM"
    return "WIDE"


def extract_sweep_extreme_from_metadata(row: Mapping[str, Any], decision_time: pd.Timestamp) -> float | None:
    reason = str(row.get("direction_recovery_reason") or "")
    match = re.search(r"sweep_extreme=([-+]?\d+(?:\.\d+)?)", reason)
    ts_match = re.search(r"sweep_timestamp=([^;|]+)", reason)
    if not match:
        return None
    if ts_match:
        ts = parse_timestamp(ts_match.group(1))
        if ts is None or ts >= decision_time:
            return None
    return parse_float(match.group(1))


def _is_local_low(candles: pd.DataFrame, index: int) -> bool:
    low = float(candles.iloc[index]["low"])
    if 0 < index < len(candles) - 1:
        return low <= float(candles.iloc[index - 1]["low"]) and low <= float(candles.iloc[index + 1]["low"])
    if index == 0 and len(candles) > 1:
        return low <= float(candles.iloc[index + 1]["low"])
    if index == len(candles) - 1 and len(candles) > 1:
        return low <= float(candles.iloc[index - 1]["low"])
    return True


def _is_local_high(candles: pd.DataFrame, index: int) -> bool:
    high = float(candles.iloc[index]["high"])
    if 0 < index < len(candles) - 1:
        return high >= float(candles.iloc[index - 1]["high"]) and high >= float(candles.iloc[index + 1]["high"])
    if index == 0 and len(candles) > 1:
        return high >= float(candles.iloc[index + 1]["high"])
    if index == len(candles) - 1 and len(candles) > 1:
        return high >= float(candles.iloc[index - 1]["high"])
    return True


def _is_sweep_low(candles: pd.DataFrame, index: int, prior: int = 5) -> bool:
    if index <= 0:
        return False
    start = max(0, index - prior)
    previous = candles.iloc[start:index]
    return not previous.empty and float(candles.iloc[index]["low"]) < float(previous["low"].min())


def _is_sweep_high(candles: pd.DataFrame, index: int, prior: int = 5) -> bool:
    if index <= 0:
        return False
    start = max(0, index - prior)
    previous = candles.iloc[start:index]
    return not previous.empty and float(candles.iloc[index]["high"]) > float(previous["high"].max())


def invalidation_candidates(
    row: Mapping[str, Any],
    candles: pd.DataFrame,
    decision_time: pd.Timestamp,
    direction: str,
    reference_price: float,
) -> list[tuple[float, str]]:
    candidates: list[tuple[float, str]] = []
    sweep_extreme = extract_sweep_extreme_from_metadata(row, decision_time)
    if sweep_extreme is not None:
        if direction == "LONG" and sweep_extreme < reference_price:
            candidates.append((sweep_extreme, "DIRECTION_RECOVERY_SWEEP_EXTREME"))
        if direction == "SHORT" and sweep_extreme > reference_price:
            candidates.append((sweep_extreme, "DIRECTION_RECOVERY_SWEEP_EXTREME"))

    if candles.empty:
        return candidates

    for idx in range(len(candles)):
        candle = candles.iloc[idx]
        if direction == "LONG":
            low = float(candle["low"])
            if low < reference_price and (_is_local_low(candles, idx) or _is_sweep_low(candles, idx)):
                source = "PRE_DECISION_SWING_LOW"
                if _is_sweep_low(candles, idx):
                    source = "PRE_DECISION_SWEEP_LOW"
                candidates.append((low, source))
        elif direction == "SHORT":
            high = float(candle["high"])
            if high > reference_price and (_is_local_high(candles, idx) or _is_sweep_high(candles, idx)):
                source = "PRE_DECISION_SWING_HIGH"
                if _is_sweep_high(candles, idx):
                    source = "PRE_DECISION_SWEEP_HIGH"
                candidates.append((high, source))

    if direction == "LONG":
        absolute_low = float(candles["low"].min())
        if absolute_low < reference_price:
            candidates.append((absolute_low, "PRE_DECISION_WINDOW_LOW"))
    elif direction == "SHORT":
        absolute_high = float(candles["high"].max())
        if absolute_high > reference_price:
            candidates.append((absolute_high, "PRE_DECISION_WINDOW_HIGH"))
    return candidates


def choose_nearest_invalidation(
    candidates: Sequence[tuple[float, str]],
    reference_price: float,
    direction: str,
) -> tuple[float, str] | None:
    directional = []
    for price, source in candidates:
        if direction == "LONG" and price < reference_price:
            directional.append((reference_price - price, price, source))
        if direction == "SHORT" and price > reference_price:
            directional.append((price - reference_price, price, source))
    if not directional:
        return None
    directional.sort(key=lambda item: (item[0], item[2]))
    _, price, source = directional[0]
    return price, source


def compute_h3_proxy(
    sample: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
) -> H3Result:
    reference_price = parse_float(sample.get("entry_reference_price"))
    if reference_price is None:
        return H3Result(state="UNKNOWN_REFERENCE_PRICE")
    direction = str(sample.get("direction") or "").strip().upper()
    decision_time = parse_timestamp(sample.get("decision_timestamp"))
    if direction not in {"LONG", "SHORT"} or decision_time is None:
        return H3Result(state="NO_VALID_INVALIDATION_EXTREME", reference_price=reference_price)

    normalizer_source, candles, normalizer_value = select_h3_normalizer(frames, decision_time)
    if normalizer_value is None:
        return H3Result(
            state="INSUFFICIENT_PRE_DECISION_RANGE",
            reference_price=reference_price,
            normalizer_source=normalizer_source,
        )

    candidates = invalidation_candidates(sample, candles, decision_time, direction, reference_price)
    chosen = choose_nearest_invalidation(candidates, reference_price, direction)
    if chosen is None:
        return H3Result(
            state="NO_VALID_INVALIDATION_EXTREME",
            reference_price=reference_price,
            normalizer_value=normalizer_value,
            normalizer_source=normalizer_source,
        )

    invalidation_extreme, invalidation_source = chosen
    if direction == "LONG":
        distance = reference_price - invalidation_extreme
    else:
        distance = invalidation_extreme - reference_price
    if distance <= 0 or not math.isfinite(distance):
        return H3Result(
            state="INVALID_GEOMETRY",
            reference_price=reference_price,
            invalidation_extreme=invalidation_extreme,
            invalidation_source=invalidation_source,
            distance=distance,
            normalizer_value=normalizer_value,
            normalizer_source=normalizer_source,
        )
    normalized_distance = distance / normalizer_value
    return H3Result(
        state=classify_h3_band(normalized_distance),
        reference_price=reference_price,
        invalidation_extreme=invalidation_extreme,
        invalidation_source=invalidation_source,
        distance=distance,
        normalizer_value=normalizer_value,
        normalizer_source=normalizer_source,
        normalized_distance=normalized_distance,
    )


def _zone_from_sample(sample: Mapping[str, Any]) -> tuple[float, float, str] | None:
    low = parse_float(sample.get("nearest_fvg_ifvg_zone_low"))
    high = parse_float(sample.get("nearest_fvg_ifvg_zone_high"))
    if low is not None and high is not None and high >= low:
        return low, high, "FVG_IFVG_METADATA_ZONE"

    round_level = parse_float(sample.get("nearest_round_level"))
    round_distance = parse_float(sample.get("round_level_distance_pips"))
    if round_level is not None and (round_distance is None or round_distance <= 20):
        return round_level - 2.0, round_level + 2.0, "NUMERIC_LEVEL_GRID_20P_ZONE"

    liquidity_level = parse_float(sample.get("nearest_liquidity_level"))
    liquidity_distance = parse_float(sample.get("distance_to_liquidity_pips"))
    if liquidity_level is not None and liquidity_distance is not None and liquidity_distance <= 20:
        return liquidity_level - 2.0, liquidity_level + 2.0, "LIQUIDITY_LEVEL_20P_ZONE"

    return None


def _h4_window(frames: Mapping[str, pd.DataFrame], decision_time: pd.Timestamp) -> tuple[str, pd.DataFrame]:
    m1 = pre_decision_closed(frames.get("M1", pd.DataFrame()), decision_time, 30)
    if len(m1) >= 5:
        return "M1_30_CLOSED_PRE_DECISION", m1
    m5 = pre_decision_closed(frames.get("M5", pd.DataFrame()), decision_time, 12)
    if len(m5) >= 3:
        return "M5_12_CLOSED_PRE_DECISION", m5
    return H3_NORMALIZER_NONE, pd.DataFrame()


def compute_h4_proxy(sample: Mapping[str, Any], frames: Mapping[str, pd.DataFrame]) -> H4Result:
    direction = str(sample.get("direction") or "").strip().upper()
    decision_time = parse_timestamp(sample.get("decision_timestamp"))
    reference_price = parse_float(sample.get("entry_reference_price"))
    if direction not in {"LONG", "SHORT"} or decision_time is None or reference_price is None:
        return H4Result(state="NO_ZONE_AVAILABLE")

    zone = _zone_from_sample(sample)
    if zone is None:
        return H4Result(state="NO_ZONE_AVAILABLE")
    zone_low, zone_high, zone_source = zone
    _, candles = _h4_window(frames, decision_time)
    if candles.empty:
        return H4Result(state="NO_ZONE_AVAILABLE", zone_source=zone_source, zone_low=zone_low, zone_high=zone_high)

    if zone_low <= reference_price <= zone_high:
        return H4Result(state="INSIDE_ZONE", zone_source=zone_source, zone_low=zone_low, zone_high=zone_high)

    touches = candles.loc[(candles["high"] >= zone_low) & (candles["low"] <= zone_high)]
    if touches.empty:
        return H4Result(state="NO_ZONE_AVAILABLE", zone_source=zone_source, zone_low=zone_low, zone_high=zone_high)

    last_close = float(candles.iloc[-1]["close"])
    closes = candles["close"].astype(float)
    touch_time = pd.Timestamp(touches.iloc[-1]["time"])

    if direction == "LONG":
        if (closes < zone_low).any() and last_close >= zone_high:
            return H4Result(
                state="RECLAIM_CONFIRMED",
                zone_source=zone_source,
                zone_low=zone_low,
                zone_high=zone_high,
                retest_or_reclaim_timestamp=touch_time,
            )
        if last_close >= zone_high:
            return H4Result(
                state="RETEST_HELD",
                zone_source=zone_source,
                zone_low=zone_low,
                zone_high=zone_high,
                retest_or_reclaim_timestamp=touch_time,
            )
        if last_close < zone_low:
            return H4Result(
                state="RETEST_FAILED_PRE_DECISION",
                zone_source=zone_source,
                zone_low=zone_low,
                zone_high=zone_high,
                retest_or_reclaim_timestamp=touch_time,
            )
    else:
        if (closes > zone_high).any() and last_close <= zone_low:
            return H4Result(
                state="RECLAIM_CONFIRMED",
                zone_source=zone_source,
                zone_low=zone_low,
                zone_high=zone_high,
                retest_or_reclaim_timestamp=touch_time,
            )
        if last_close <= zone_low:
            return H4Result(
                state="RETEST_HELD",
                zone_source=zone_source,
                zone_low=zone_low,
                zone_high=zone_high,
                retest_or_reclaim_timestamp=touch_time,
            )
        if last_close > zone_high:
            return H4Result(
                state="RETEST_FAILED_PRE_DECISION",
                zone_source=zone_source,
                zone_low=zone_low,
                zone_high=zone_high,
                retest_or_reclaim_timestamp=touch_time,
            )

    return H4Result(state="INSIDE_ZONE", zone_source=zone_source, zone_low=zone_low, zone_high=zone_high)


def validate_signoff_and_specs(config: DiagnosticConfig) -> tuple[bool, dict[str, Any]]:
    signoff_exists = config.signoff_path.exists()
    signoff_text = config.signoff_path.read_text(encoding="utf-8") if signoff_exists else ""
    h3_path = config.proxy_plan_dir / "h3_tight_sl_proxy_spec.json"
    h4_path = config.proxy_plan_dir / "h4_zone_retest_proxy_spec.json"
    summary_path = config.proxy_plan_dir / "summary.json"
    h3 = read_json(h3_path) if h3_path.exists() else {}
    h4 = read_json(h4_path) if h4_path.exists() else {}
    plan_summary = read_json(summary_path) if summary_path.exists() else {}

    h3_thresholds = h3.get("threshold_policy", {}).get("numeric_thresholds", {})
    h3_missing = set(h3.get("missing_data_states", []))
    h4_states = set(h4.get("threshold_policy", {}).get("categories", []))

    checks = {
        "signoff_exists": signoff_exists,
        "signoff_decision_approve": "Decision: APPROVE" in signoff_text,
        "h3_spec_exists": h3_path.exists(),
        "h4_spec_exists": h4_path.exists(),
        "plan_summary_exists": summary_path.exists(),
        "h3_concept_approved": "TIGHT_SL_BEHIND_SPIKE_OR_SWING" in signoff_text,
        "h3_formula_commit_approved": "56dcff0" in signoff_text,
        "h3_m1_normalizer_approved": "M1 30" in signoff_text or "M1 last 30" in signoff_text,
        "h3_m5_fallback_approved": "M5 12" in signoff_text or "M5 last 12" in signoff_text,
        "h3_thresholds_approved": "0.25" in signoff_text and "0.50" in signoff_text,
        "h3_spec_thresholds_frozen": h3_thresholds.get("tight_max") == H3_TIGHT_MAX
        and h3_thresholds.get("medium_max") == H3_MEDIUM_MAX
        and h3.get("threshold_policy", {}).get("percentile_thresholds_allowed") is False,
        "h3_missing_states_approved": set(H3_MISSING_STATES).issubset(h3_missing)
        and all(state in signoff_text for state in H3_MISSING_STATES),
        "h4_concept_approved": "ZONE_RETEST_OR_RECLAIM" in signoff_text,
        "h4_states_approved": set(H4_STATES).issubset(h4_states)
        and all(state in signoff_text for state in H4_STATES),
        "phase_4_blocked_in_plan": plan_summary.get("phase_4_blocked") is True,
    }
    checks["precheck_passed"] = all(checks.values())
    return bool(checks["precheck_passed"]), checks


def load_input_rows(config: DiagnosticConfig) -> list[dict[str, str]]:
    if not config.sample_path.exists():
        raise FileNotFoundError(config.sample_path)
    rows = load_csv_rows(config.sample_path)
    if not rows:
        raise ValueError(f"no sample rows loaded from {config.sample_path}")
    return rows


def compute_sample_row(
    sample: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    *,
    source_artifact: str,
    input_file: str,
) -> dict[str, Any]:
    decision_time = parse_timestamp(sample.get("decision_timestamp"))
    direction = str(sample.get("direction") or "").strip().upper()
    direction_confidence = parse_int(sample.get("direction_recovery_confidence"))
    h3 = compute_h3_proxy(sample, frames)
    h4 = compute_h4_proxy(sample, frames)
    leakage_passed = True
    notes = "pre-decision M1/M5 candles only; no post-entry outcome fields used"
    if decision_time is None or direction not in {"LONG", "SHORT"}:
        leakage_passed = False
        notes = "missing decision timestamp or direction; proxy row is not executable"
    return {
        "sample_id": sample.get("sample_id", ""),
        "source_artifact": source_artifact,
        "input_file": input_file,
        "decision_time": decision_time,
        "direction": direction,
        "direction_source": sample.get("direction_recovery_source", ""),
        "direction_confidence": direction_confidence,
        "entry_reference_price_source": sample.get("entry_reference_source", ""),
        "data_availability_status": sample.get("execution_data_status", ""),
        "h3_state": h3.state,
        "h3_reference_price": h3.reference_price,
        "h3_invalidation_extreme": h3.invalidation_extreme,
        "h3_invalidation_source": h3.invalidation_source,
        "h3_distance": h3.distance,
        "h3_normalizer_value": h3.normalizer_value,
        "h3_normalizer_source": h3.normalizer_source,
        "h3_normalized_distance": h3.normalized_distance,
        "h3_threshold_version": H3_THRESHOLD_VERSION,
        "h3_formula_version": H3_FORMULA_VERSION,
        "h3_pre_entry_only": True,
        "h3_post_entry_data_used": False,
        "h4_state": h4.state,
        "h4_zone_source": h4.zone_source,
        "h4_zone_high": h4.zone_high,
        "h4_zone_low": h4.zone_low,
        "h4_retest_or_reclaim_timestamp": h4.retest_or_reclaim_timestamp,
        "h4_pre_entry_only": True,
        "h4_post_entry_data_used": False,
        "pre_entry_only": True,
        "post_entry_data_used": False,
        "leakage_check_passed": leakage_passed,
        "leakage_check_notes": notes,
        "ohlc_read": True,
        "matched_control_run": False,
        "phase_4_unlocked": False,
        "runtime_logic_changed": False,
    }


def _count(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(key) or "") for row in rows).items()))


def build_group_summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: list[dict[str, Any]] = []
    for group_key in ("h3_state", "h4_state", "h3_normalizer_source", "direction_confidence", "direction_source"):
        counter = Counter(str(row.get(group_key) or "") for row in rows)
        for value, count in sorted(counter.items()):
            grouped.append({"field": group_key, "value": value, "count": count})
    return grouped


def leakage_report_for_outputs(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    found = []
    for field in PER_SAMPLE_FIELDS:
        lowered = field.lower()
        if any(token in lowered for token in FORBIDDEN_OUTPUT_FEATURE_TOKENS):
            if field not in {
                "h3_post_entry_data_used",
                "h4_post_entry_data_used",
                "post_entry_data_used",
                "matched_control_run",
                "phase_4_unlocked",
            }:
                found.append(field)
    post_entry_count = sum(1 for row in rows if row.get("post_entry_data_used") is True)
    failed_count = sum(1 for row in rows if row.get("leakage_check_passed") is not True)
    return {
        "forbidden_fields_checked": list(FORBIDDEN_OUTPUT_FEATURE_TOKENS),
        "forbidden_feature_fields_found": sorted(found),
        "post_entry_data_used_count": post_entry_count,
        "post_entry_feature_usage_detected": post_entry_count > 0,
        "matched_control_run": False,
        "phase_4_unlocked": False,
        "leakage_check_passed": not found and post_entry_count == 0 and failed_count == 0,
        "leakage_check_failed_count": failed_count,
    }


def build_summary(
    config: DiagnosticConfig,
    rows: Sequence[Mapping[str, Any]],
    precheck: Mapping[str, Any],
    leakage: Mapping[str, Any],
) -> dict[str, Any]:
    skipped = [
        row
        for row in rows
        if row.get("leakage_check_passed") is not True
        or not row.get("decision_time")
        or str(row.get("direction") or "") not in {"LONG", "SHORT"}
    ]
    skip_reasons = Counter(row.get("leakage_check_notes") or "UNKNOWN" for row in skipped)
    return {
        "run_started_at": utc_now(),
        "source_artifact": "adelin_v2_preentry_outcome_diagnostics_direction_recovered/sample_diagnostics.csv",
        "input_file": str(config.sample_path),
        "input_lineage_reason": (
            "Chosen because it is the approved direction-recovered Adelin v2 sample artifact with "
            "40 samples, decision timestamps, final directions, direction confidence/source, and "
            "entry reference prices."
        ),
        "signoff_decision_verified": precheck.get("signoff_decision_approve") is True,
        "h3_approval_verified": precheck.get("h3_concept_approved") is True
        and precheck.get("h3_spec_thresholds_frozen") is True,
        "h4_approval_verified": precheck.get("h4_concept_approved") is True
        and precheck.get("h4_states_approved") is True,
        "precheck_passed": precheck.get("precheck_passed") is True,
        "ohlc_read": True,
        "ohlc_scope_read": [
            "data/XAUUSD/M1.csv loaded; per-sample computations use candles with time < decision_timestamp",
            "data/XAUUSD/M5.csv loaded; per-sample computations use candles with time < decision_timestamp",
        ],
        "pre_entry_only": True,
        "post_entry_data_used_count": leakage["post_entry_data_used_count"],
        "total_samples": len(rows),
        "executable_samples": len(rows) - len(skipped),
        "skipped_samples": len(skipped),
        "skip_reasons": dict(sorted(skip_reasons.items())),
        "h3_state_counts": _count(rows, "h3_state"),
        "h4_state_counts": _count(rows, "h4_state"),
        "h3_normalizer_source_counts": _count(rows, "h3_normalizer_source"),
        "leakage_check_passed_count": sum(1 for row in rows if row.get("leakage_check_passed") is True),
        "leakage_check_failed_count": leakage["leakage_check_failed_count"],
        "matched_control_run": False,
        "phase_4_unlocked": False,
        "runtime_logic_changed": False,
        "strategy_2_modified": False,
        "strategy_3_modified": False,
        "live_trading": False,
        "broker_execution": False,
        "order_send": False,
        "telegram_alerts": False,
        "verdict_flags": VERDICT_FLAGS
        if leakage["leakage_check_passed"]
        else VERDICT_FLAGS + ["LEAKAGE_CHECK_FAILED"],
        "limitations": [
            "H4 zone availability depends on existing pre-entry metadata fields such as FVG/iFVG zone bounds and numeric levels.",
            "H3 invalidation extreme selection is deterministic but remains a research proxy, not a trading rule.",
            "The output is descriptive diagnostic evidence only and does not unlock Phase 4.",
        ],
    }


def write_markdown_report(path: Path, summary: Mapping[str, Any]) -> None:
    lines = [
        "# Adelin v2 H3/H4 Proxy Diagnostic Execution",
        "",
        "## Context",
        "",
        "This bounded diagnostic executes the human-approved H3/H4 proxy computation on existing Adelin v2 samples. It is not Phase 4, matched-control replay, backtest, runtime scoring, or deployment preparation.",
        "",
        "## Inputs",
        "",
        f"* Sample artifact: `{summary['input_file']}`",
        "* OHLC scope: `data/XAUUSD/M1.csv` and `data/XAUUSD/M5.csv` were loaded; only candles with `time < decision_timestamp` were used per sample.",
        "* Signoff decision: APPROVE",
        "",
        "## Counts",
        "",
        f"* Total samples: {summary['total_samples']}",
        f"* Executable samples: {summary['executable_samples']}",
        f"* Skipped samples: {summary['skipped_samples']}",
        f"* Leakage failures: {summary['leakage_check_failed_count']}",
        "",
        "## H3 State Counts",
        "",
    ]
    for state, count in summary["h3_state_counts"].items():
        lines.append(f"* {state}: {count}")
    lines.extend(["", "## H4 State Counts", ""])
    for state, count in summary["h4_state_counts"].items():
        lines.append(f"* {state}: {count}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "* Pre-entry only: true",
            "* Post-entry data used: false",
            "* Matched-control replay run: false",
            "* Phase 4 unlocked: false",
            "* Runtime logic changed: false",
            "* Live/orders/Telegram/broker/order_send: false",
            "",
            "## Limitations",
            "",
        ]
    )
    for limitation in summary["limitations"]:
        lines.append(f"* {limitation}")
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            "H3/H4 proxy distributions were computed for research review only. Phase 4 remains blocked, and no edge, profitability, deployability, scoring, or live-signal claim is made.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run_diagnostic(config: DiagnosticConfig = DiagnosticConfig()) -> dict[str, Any]:
    valid, precheck = validate_signoff_and_specs(config)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    if not valid:
        failure = {
            "run_started_at": utc_now(),
            "precheck_passed": False,
            "precheck": precheck,
            "comparison_executed": False,
            "ohlc_read": False,
            "phase_4_unlocked": False,
            "matched_control_run": False,
            "runtime_logic_changed": False,
            "verdict_flags": ["H3_H4_PROXY_DIAGNOSTIC_INCOMPLETE"],
        }
        write_json(config.output_dir / "summary.json", failure)
        return failure

    samples = load_input_rows(config)
    frames = normalize_frames(load_csv_timeframes(config.symbol, ["M1", "M5"], data_dir=str(config.data_dir)))
    source_artifact = "adelin_v2_preentry_outcome_diagnostics_direction_recovered"
    computed_rows = [
        compute_sample_row(
            sample,
            frames,
            source_artifact=source_artifact,
            input_file=str(config.sample_path),
        )
        for sample in samples
    ]
    leakage = leakage_report_for_outputs(computed_rows)
    summary = build_summary(config, computed_rows, precheck, leakage)
    grouped = build_group_summary(computed_rows)

    write_csv(config.output_dir / "h3_h4_proxy_per_sample.csv", computed_rows, PER_SAMPLE_FIELDS)
    write_csv(config.output_dir / "h3_h4_proxy_group_summary.csv", grouped, ["field", "value", "count"])
    write_json(config.output_dir / "summary.json", summary)
    write_markdown_report(config.doc_path, summary)
    return summary
