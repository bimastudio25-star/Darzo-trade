from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


VALID_LAYER_A_STATES = {"VALID_LONG", "VALID_SHORT"}
MAE_NOT_REACHED_STATE = "MAE_NOT_REACHED"
DEFAULT_MECHANICAL_PATH = Path("backtests/reports/strategy_2_mechanical_spec_correction/corrected_mechanical_samples.csv")
REACTION_DESCRIPTORS = [
    "FAST_REENTRY",
    "WICK_REJECTION_CANDIDATE",
    "BODY_SHIFT_CANDIDATE",
    "COMPRESSION_THEN_SHIFT_CANDIDATE",
    "WEAK_REACTION_CANDIDATE",
    "CHOP_AFTER_SWEEP_CANDIDATE",
    "NOT_ENOUGH_DATA",
    "UNKNOWN",
]
LAYER_B_LABELS = [
    "STRONG_REACTION_CANDIDATE",
    "WEAK_REACTION_CANDIDATE",
    "CHOPPY_REACTION_CANDIDATE",
    "UNKNOWN_REACTION_CANDIDATE",
]
SAFETY = {
    "research_only": True,
    "diagnostics_only": True,
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "broker_execution_called": False,
    "orders_sent": False,
    "order_send_called": False,
    "signals_generated": False,
    "runtime_registration": False,
    "parameters_optimized": False,
    "thresholds_tuned": False,
    "ml_used": False,
    "backtest_run": False,
    "pnl_metrics_generated": False,
    "outcome_columns_used": False,
    "market_data_written": False,
}
VERDICT_FLAGS = [
    "LAYER_B_REACTION_DIAGNOSTICS_CREATED",
    "VALID_STATES_ONLY",
    "NO_TAKE_SKIP_DECISION",
    "NO_PERFORMANCE_CLAIM",
    "NO_OUTCOME_USAGE",
    "FUTURE_DATA_AUDITED",
    "MANUAL_VALIDATION_REQUIRED",
    "STRATEGY_2_REMAINS_RESEARCH_ONLY",
    "NO_DEPLOYMENT_DECISION",
]


@dataclass(frozen=True)
class LayerBReactionQualityResult:
    per_sample: pd.DataFrame
    descriptor_distribution: pd.DataFrame
    null_report: pd.DataFrame
    future_data_audit: pd.DataFrame
    summary: dict[str, Any]
    report_markdown: str


def usd_to_pips(value: float | None, pip_factor: float = 10.0) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value) * float(pip_factor), 6)


def load_state_split_samples(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Layer A state split input missing: {source}")
    frame = pd.read_csv(source)
    required = {"sample_id", "h1_context_id", "direction_candidate", "final_state"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Layer A state split input missing required columns: {missing}")
    return frame.copy()


def load_mechanical_details(path: str | Path = DEFAULT_MECHANICAL_PATH) -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        return pd.DataFrame(columns=["sample_id"])
    frame = pd.read_csv(source)
    if "m15_filter_model" in frame.columns:
        frame = frame[frame["m15_filter_model"].astype(str).str.lower().eq("containing")].copy()
    return frame


def load_ohlc_data(data_dir: str | Path, symbol: str, timeframe: str = "M1") -> pd.DataFrame:
    path = Path(data_dir) / symbol / f"{timeframe}.csv"
    if not path.exists():
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume", "spread"])
    frame = _read_ohlc_csv(path)
    frame["time"] = pd.to_datetime(frame["time"], format="%Y.%m.%d %H:%M", utc=True, errors="coerce")
    for column in ["open", "high", "low", "close"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time").reset_index(drop=True)


def _read_ohlc_csv(path: Path) -> pd.DataFrame:
    names = ["time", "open", "high", "low", "close", "volume", "spread"]
    last_error: Exception | None = None
    for encoding in ("utf-8", "utf-16", "utf-16-le"):
        try:
            return pd.read_csv(path, header=None, names=names, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return pd.read_csv(path, header=None, names=names)


def build_layer_b_reaction_quality(
    input_path: str | Path,
    *,
    data_dir: str | Path = "data",
    symbol: str = "XAUUSD",
    pip_factor: float = 10.0,
    mechanical_path: str | Path = DEFAULT_MECHANICAL_PATH,
) -> LayerBReactionQualityResult:
    started = time.perf_counter()
    state_frame = load_state_split_samples(input_path)
    mechanical = load_mechanical_details(mechanical_path)
    ohlc = load_ohlc_data(data_dir, symbol, "M1")
    merged = state_frame.merge(mechanical, on="sample_id", how="left", suffixes=("", "_mechanical"))
    per_sample_rows = [
        derive_reaction_features(row, ohlc=ohlc, pip_factor=pip_factor)
        for row in merged.to_dict("records")
    ]
    per_sample = pd.DataFrame(per_sample_rows, columns=OUTPUT_COLUMNS)
    descriptor_distribution = build_descriptor_distribution(per_sample)
    null_report = build_null_report(per_sample)
    future_data_audit = build_future_data_audit()
    state_counts = Counter(state_frame["final_state"]) if not state_frame.empty else Counter()
    eligible = per_sample[per_sample["layer_b_eligible"]]
    excluded_counts = {str(state): int(count) for state, count in state_counts.items() if state not in VALID_LAYER_A_STATES}
    descriptor_counts = Counter(eligible["reaction_descriptor"]) if not eligible.empty else Counter()
    label_counts = Counter(eligible["layer_b_candidate_label"]) if not eligible.empty else Counter()
    missing_data_count = int(eligible["missing_required_data"].sum()) if not eligible.empty else 0
    future_count = int(eligible["uses_future_data"].sum()) if not eligible.empty else 0
    summary = {
        "runtime_seconds": round(time.perf_counter() - started, 4),
        "input_path": str(Path(input_path)),
        "data_dir": str(Path(data_dir)),
        "symbol": symbol,
        "samples_loaded": int(len(state_frame)),
        "eligible_valid_long_count": int(state_counts.get("VALID_LONG", 0)),
        "eligible_valid_short_count": int(state_counts.get("VALID_SHORT", 0)),
        "layer_b_eligible_count": int(len(eligible)),
        "excluded_count": int(len(state_frame) - len(eligible)),
        "excluded_states": excluded_counts,
        "mae_not_reached_count": int(state_counts.get(MAE_NOT_REACHED_STATE, 0)),
        "reaction_descriptor_distribution": dict(sorted(descriptor_counts.items())),
        "layer_b_candidate_label_distribution": dict(sorted(label_counts.items())),
        "missing_data_count": missing_data_count,
        "future_data_diagnostic_only_count": future_count,
        "future_data_features_are_diagnostic_only": True,
        "take_skip_decision_produced": False,
        "outcome_columns_used": False,
        "pnl_metrics_generated": False,
        "pip_factor_used": float(pip_factor),
        "verdict_flags": VERDICT_FLAGS,
        "safety": SAFETY,
    }
    return LayerBReactionQualityResult(
        per_sample=per_sample,
        descriptor_distribution=descriptor_distribution,
        null_report=null_report,
        future_data_audit=future_data_audit,
        summary=summary,
        report_markdown=render_layer_b_report(summary, descriptor_distribution, null_report, future_data_audit),
    )


def derive_reaction_features(row: dict[str, Any], *, ohlc: pd.DataFrame, pip_factor: float) -> dict[str, Any]:
    sample_id = _clean(row.get("sample_id"))
    layer_a_state = _clean(row.get("final_state"))
    direction = _clean(row.get("direction_candidate")).upper()
    eligible = layer_a_state in VALID_LAYER_A_STATES
    sweep_ts = _timestamp(row.get("h1_level_take_timestamp"))
    reentry_ts = _timestamp(row.get("range_reentry_timestamp")) or _timestamp(row.get("entry_timestamp"))
    decision_time = reentry_ts
    h1_start = _timestamp(row.get("h1_context_timestamp"))
    h1_level = _to_float(row.get("h1_liquidity_level"))
    data_window_start = sweep_ts or h1_start
    data_window_end = decision_time
    warnings: list[str] = []
    null_reasons: list[str] = []
    if not eligible:
        return _base_output(
            row,
            layer_a_state=layer_a_state,
            eligible=False,
            sweep_ts=sweep_ts,
            decision_time=decision_time,
            data_window_start=data_window_start,
            data_window_end=data_window_end,
            pip_factor=pip_factor,
            descriptor="UNKNOWN",
            label="UNKNOWN_REACTION_CANDIDATE",
            missing=True,
            null_reasons=f"EXCLUDED_LAYER_A_STATE_{layer_a_state}",
            warnings="Layer A state excluded from Layer B derivation",
        )
    if ohlc.empty:
        null_reasons.append("M1_DATA_UNAVAILABLE")
    if sweep_ts is None:
        null_reasons.append("SWEEP_TIMESTAMP_MISSING")
    if decision_time is None:
        null_reasons.append("DECISION_TIME_MISSING")
    if h1_level is None:
        null_reasons.append("H1_LIQUIDITY_LEVEL_MISSING")
    if direction not in {"LONG", "SHORT"}:
        null_reasons.append("DIRECTION_MISSING")
    if null_reasons:
        return _base_output(
            row,
            layer_a_state=layer_a_state,
            eligible=True,
            sweep_ts=sweep_ts,
            decision_time=decision_time,
            data_window_start=data_window_start,
            data_window_end=data_window_end,
            pip_factor=pip_factor,
            descriptor="NOT_ENOUGH_DATA",
            label="UNKNOWN_REACTION_CANDIDATE",
            missing=True,
            null_reasons=_join(null_reasons),
            warnings="Required decision-time data missing",
        )

    window = ohlc[(ohlc["time"] >= sweep_ts) & (ohlc["time"] <= decision_time)].copy()
    decision_candle = candle_at_or_before(ohlc, decision_time)
    if window.empty or decision_candle is None:
        return _base_output(
            row,
            layer_a_state=layer_a_state,
            eligible=True,
            sweep_ts=sweep_ts,
            decision_time=decision_time,
            data_window_start=data_window_start,
            data_window_end=data_window_end,
            pip_factor=pip_factor,
            descriptor="NOT_ENOUGH_DATA",
            label="UNKNOWN_REACTION_CANDIDATE",
            missing=True,
            null_reasons="REACTION_WINDOW_EMPTY",
            warnings="No M1 candles inside sweep-to-decision window",
        )

    range_reentry_detected = _tri_state(row.get("range_reentry_reached"))
    time_to_reentry_seconds = max(0.0, (decision_time - sweep_ts).total_seconds())
    reentry_distance = compute_reentry_distance(decision_candle, direction, h1_level)
    body_displacement = abs(float(decision_candle["close"]) - float(decision_candle["open"]))
    wick_ratio = compute_rejection_wick_ratio(decision_candle, direction)
    micro_range = float(window["high"].max() - window["low"].min())
    compression_seconds = time_to_reentry_seconds
    clean_dirty = classify_clean_dirty_path(window, direction, h1_level)
    acceleration = compute_future_acceleration(ohlc, decision_time, direction, float(decision_candle["close"]))
    uses_future = acceleration is not None
    if uses_future:
        warnings.append("acceleration_after_reentry_usd uses candles after decision_time and is diagnostic_only")
    descriptor = classify_reaction_descriptor(
        range_reentry_detected=range_reentry_detected,
        time_to_reentry_seconds=time_to_reentry_seconds,
        reentry_distance_usd=reentry_distance,
        rejection_wick_ratio=wick_ratio,
        body_displacement_usd=body_displacement,
        micro_range_size_usd=micro_range,
        clean_vs_dirty_path_candidate=clean_dirty,
    )
    label = candidate_label_for_descriptor(descriptor)
    return {
        "sample_id": sample_id,
        "h1_context_id": _clean(row.get("h1_context_id")),
        "direction_candidate": direction,
        "layer_a_state": layer_a_state,
        "layer_b_eligible": True,
        "sweep_timestamp": _format_ts(sweep_ts),
        "decision_time": _format_ts(decision_time),
        "feature_time_boundary": _format_ts(decision_time),
        "data_window_start": _format_ts(data_window_start),
        "data_window_end": _format_ts(data_window_end),
        "range_reentry_detected": range_reentry_detected,
        "time_to_reentry_seconds": round(time_to_reentry_seconds, 3),
        "reentry_distance_usd": _round(reentry_distance),
        "reentry_distance_pips": usd_to_pips(reentry_distance, pip_factor),
        "rejection_wick_ratio": _round(wick_ratio),
        "body_displacement_usd": _round(body_displacement),
        "body_displacement_pips": usd_to_pips(body_displacement, pip_factor),
        "post_sweep_compression_seconds": round(compression_seconds, 3),
        "micro_range_size_usd": _round(micro_range),
        "micro_range_size_pips": usd_to_pips(micro_range, pip_factor),
        "acceleration_after_reentry_usd": _round(acceleration),
        "acceleration_after_reentry_pips": usd_to_pips(acceleration, pip_factor),
        "clean_vs_dirty_path_candidate": clean_dirty,
        "reaction_descriptor": descriptor,
        "layer_b_candidate_label": label,
        "uses_future_data": bool(uses_future),
        "diagnostic_only": bool(uses_future),
        "missing_required_data": False,
        "null_feature_reasons": "",
        "feature_warnings": _join(warnings),
        "pip_factor_used": float(pip_factor),
    }


def _base_output(
    row: dict[str, Any],
    *,
    layer_a_state: str,
    eligible: bool,
    sweep_ts: pd.Timestamp | None,
    decision_time: pd.Timestamp | None,
    data_window_start: pd.Timestamp | None,
    data_window_end: pd.Timestamp | None,
    pip_factor: float,
    descriptor: str,
    label: str,
    missing: bool,
    null_reasons: str,
    warnings: str,
) -> dict[str, Any]:
    return {
        "sample_id": _clean(row.get("sample_id")),
        "h1_context_id": _clean(row.get("h1_context_id")),
        "direction_candidate": _clean(row.get("direction_candidate")).upper(),
        "layer_a_state": layer_a_state,
        "layer_b_eligible": bool(eligible),
        "sweep_timestamp": _format_ts(sweep_ts),
        "decision_time": _format_ts(decision_time),
        "feature_time_boundary": _format_ts(decision_time),
        "data_window_start": _format_ts(data_window_start),
        "data_window_end": _format_ts(data_window_end),
        "range_reentry_detected": "UNKNOWN",
        "time_to_reentry_seconds": None,
        "reentry_distance_usd": None,
        "reentry_distance_pips": None,
        "rejection_wick_ratio": None,
        "body_displacement_usd": None,
        "body_displacement_pips": None,
        "post_sweep_compression_seconds": None,
        "micro_range_size_usd": None,
        "micro_range_size_pips": None,
        "acceleration_after_reentry_usd": None,
        "acceleration_after_reentry_pips": None,
        "clean_vs_dirty_path_candidate": "UNKNOWN",
        "reaction_descriptor": descriptor,
        "layer_b_candidate_label": label,
        "uses_future_data": False,
        "diagnostic_only": False,
        "missing_required_data": bool(missing),
        "null_feature_reasons": null_reasons,
        "feature_warnings": warnings,
        "pip_factor_used": float(pip_factor),
    }


def compute_reentry_distance(candle: pd.Series, direction: str, h1_level: float) -> float:
    if direction == "LONG":
        return max(0.0, float(candle["high"]) - h1_level)
    if direction == "SHORT":
        return max(0.0, h1_level - float(candle["low"]))
    return 0.0


def compute_rejection_wick_ratio(candle: pd.Series, direction: str) -> float | None:
    body = abs(float(candle["close"]) - float(candle["open"]))
    if body == 0:
        return None
    if direction == "LONG":
        wick = min(float(candle["open"]), float(candle["close"])) - float(candle["low"])
    elif direction == "SHORT":
        wick = float(candle["high"]) - max(float(candle["open"]), float(candle["close"]))
    else:
        return None
    return max(0.0, wick) / body


def compute_future_acceleration(ohlc: pd.DataFrame, decision_time: pd.Timestamp, direction: str, decision_close: float) -> float | None:
    end = decision_time + pd.Timedelta(minutes=5)
    future = ohlc[(ohlc["time"] > decision_time) & (ohlc["time"] <= end)]
    if future.empty:
        return None
    if direction == "LONG":
        return max(0.0, float(future["high"].max()) - decision_close)
    if direction == "SHORT":
        return max(0.0, decision_close - float(future["low"].min()))
    return None


def classify_clean_dirty_path(window: pd.DataFrame, direction: str, h1_level: float) -> str:
    if window.empty:
        return "UNKNOWN"
    close_diff = window["close"].diff().dropna()
    signs = [1 if value > 0 else -1 if value < 0 else 0 for value in close_diff]
    signs = [value for value in signs if value != 0]
    flips = sum(1 for left, right in zip(signs, signs[1:]) if left != right)
    if direction == "LONG":
        sweep_count = int((window["low"] < h1_level).sum())
    elif direction == "SHORT":
        sweep_count = int((window["high"] > h1_level).sum())
    else:
        return "UNKNOWN"
    if flips <= 1 and sweep_count <= 2:
        return "CLEAN"
    if flips >= 4 or sweep_count >= 5:
        return "DIRTY"
    return "UNKNOWN"


def classify_reaction_descriptor(
    *,
    range_reentry_detected: str,
    time_to_reentry_seconds: float | None,
    reentry_distance_usd: float | None,
    rejection_wick_ratio: float | None,
    body_displacement_usd: float | None,
    micro_range_size_usd: float | None,
    clean_vs_dirty_path_candidate: str,
) -> str:
    if range_reentry_detected != "TRUE":
        return "WEAK_REACTION_CANDIDATE"
    if clean_vs_dirty_path_candidate == "DIRTY":
        return "CHOP_AFTER_SWEEP_CANDIDATE"
    if time_to_reentry_seconds is not None and time_to_reentry_seconds <= 300 and (reentry_distance_usd or 0.0) > 0:
        return "FAST_REENTRY"
    if rejection_wick_ratio is not None and rejection_wick_ratio >= 2.0:
        return "WICK_REJECTION_CANDIDATE"
    if body_displacement_usd is not None and micro_range_size_usd and body_displacement_usd >= micro_range_size_usd * 0.5:
        return "BODY_SHIFT_CANDIDATE"
    if time_to_reentry_seconds is not None and time_to_reentry_seconds >= 900 and clean_vs_dirty_path_candidate != "DIRTY":
        return "COMPRESSION_THEN_SHIFT_CANDIDATE"
    if reentry_distance_usd is None:
        return "NOT_ENOUGH_DATA"
    return "UNKNOWN"


def candidate_label_for_descriptor(descriptor: str) -> str:
    if descriptor in {"FAST_REENTRY", "WICK_REJECTION_CANDIDATE", "BODY_SHIFT_CANDIDATE", "COMPRESSION_THEN_SHIFT_CANDIDATE"}:
        return "STRONG_REACTION_CANDIDATE"
    if descriptor == "WEAK_REACTION_CANDIDATE":
        return "WEAK_REACTION_CANDIDATE"
    if descriptor == "CHOP_AFTER_SWEEP_CANDIDATE":
        return "CHOPPY_REACTION_CANDIDATE"
    return "UNKNOWN_REACTION_CANDIDATE"


def candle_at_or_before(ohlc: pd.DataFrame, timestamp: pd.Timestamp) -> pd.Series | None:
    subset = ohlc[ohlc["time"] <= timestamp]
    if subset.empty:
        return None
    return subset.iloc[-1]


def build_descriptor_distribution(per_sample: pd.DataFrame) -> pd.DataFrame:
    eligible = per_sample[per_sample["layer_b_eligible"]].copy()
    rows: list[dict[str, Any]] = []
    total = len(eligible)
    for column, dist_type in (("reaction_descriptor", "reaction_descriptor"), ("layer_b_candidate_label", "layer_b_candidate_label")):
        counts = eligible[column].value_counts().sort_index() if total else pd.Series(dtype="int64")
        for value, count in counts.items():
            rows.append({"distribution_type": dist_type, "value": value, "count": int(count), "rate": _rate(int(count), total)})
    return pd.DataFrame(rows, columns=["distribution_type", "value", "count", "rate"])


def build_null_report(per_sample: pd.DataFrame) -> pd.DataFrame:
    eligible = per_sample[per_sample["layer_b_eligible"]].copy()
    feature_columns = [
        "sweep_timestamp",
        "decision_time",
        "range_reentry_detected",
        "time_to_reentry_seconds",
        "reentry_distance_usd",
        "rejection_wick_ratio",
        "body_displacement_usd",
        "post_sweep_compression_seconds",
        "micro_range_size_usd",
        "clean_vs_dirty_path_candidate",
    ]
    rows: list[dict[str, Any]] = []
    total = len(eligible)
    for column in feature_columns:
        if column not in eligible.columns:
            count = total
        else:
            series = eligible[column]
            cleaned = series.fillna("").astype(str).str.strip().str.upper()
            count = int((series.isna() | cleaned.isin({"", "UNKNOWN", "NAN", "NONE"})).sum())
        rows.append({"feature_name": column, "null_or_unknown_count": count, "null_or_unknown_rate": _rate(count, total)})
    reason_counts = Counter()
    for value in eligible["null_feature_reasons"].dropna().astype(str):
        for token in value.split(";"):
            if token:
                reason_counts[token] += 1
    for reason, count in sorted(reason_counts.items()):
        rows.append({"feature_name": f"reason::{reason}", "null_or_unknown_count": int(count), "null_or_unknown_rate": _rate(int(count), total)})
    return pd.DataFrame(rows, columns=["feature_name", "null_or_unknown_count", "null_or_unknown_rate"])


def build_future_data_audit() -> pd.DataFrame:
    rows = [
        {
            "feature_name": "range_reentry_detected",
            "uses_future_data": False,
            "diagnostic_only": False,
            "feature_time_boundary": "decision_time",
            "allowed_for_candidate_label": True,
        },
        {
            "feature_name": "time_to_reentry_seconds",
            "uses_future_data": False,
            "diagnostic_only": False,
            "feature_time_boundary": "decision_time",
            "allowed_for_candidate_label": True,
        },
        {
            "feature_name": "reentry_distance_usd",
            "uses_future_data": False,
            "diagnostic_only": False,
            "feature_time_boundary": "decision_time",
            "allowed_for_candidate_label": True,
        },
        {
            "feature_name": "rejection_wick_ratio",
            "uses_future_data": False,
            "diagnostic_only": False,
            "feature_time_boundary": "decision_time",
            "allowed_for_candidate_label": True,
        },
        {
            "feature_name": "body_displacement_usd",
            "uses_future_data": False,
            "diagnostic_only": False,
            "feature_time_boundary": "decision_time",
            "allowed_for_candidate_label": True,
        },
        {
            "feature_name": "post_sweep_compression_seconds",
            "uses_future_data": False,
            "diagnostic_only": False,
            "feature_time_boundary": "decision_time",
            "allowed_for_candidate_label": True,
        },
        {
            "feature_name": "micro_range_size_usd",
            "uses_future_data": False,
            "diagnostic_only": False,
            "feature_time_boundary": "decision_time",
            "allowed_for_candidate_label": True,
        },
        {
            "feature_name": "clean_vs_dirty_path_candidate",
            "uses_future_data": False,
            "diagnostic_only": False,
            "feature_time_boundary": "decision_time",
            "allowed_for_candidate_label": True,
        },
        {
            "feature_name": "acceleration_after_reentry_usd",
            "uses_future_data": True,
            "diagnostic_only": True,
            "feature_time_boundary": "decision_time_plus_5_minutes",
            "allowed_for_candidate_label": False,
        },
    ]
    return pd.DataFrame(rows)


def write_layer_b_outputs(
    result: LayerBReactionQualityResult,
    output_dir: str | Path,
    *,
    docs_path: str | Path | None = None,
) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "per_sample": output / "layer_b_reaction_features_per_sample.csv",
        "descriptor_distribution": output / "layer_b_reaction_descriptor_distribution.csv",
        "null_report": output / "layer_b_feature_null_report.csv",
        "future_data_audit": output / "layer_b_future_data_audit.csv",
        "summary": output / "layer_b_eligible_sample_summary.json",
        "report": output / "layer_b_reaction_quality_report.md",
    }
    result.per_sample.to_csv(paths["per_sample"], index=False)
    result.descriptor_distribution.to_csv(paths["descriptor_distribution"], index=False)
    result.null_report.to_csv(paths["null_report"], index=False)
    result.future_data_audit.to_csv(paths["future_data_audit"], index=False)
    paths["summary"].write_text(json.dumps(result.summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    paths["report"].write_text(result.report_markdown, encoding="utf-8")
    if docs_path:
        docs = Path(docs_path)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(result.report_markdown, encoding="utf-8")
        paths["docs"] = docs
    return {key: str(path) for key, path in paths.items()}


def render_layer_b_report(
    summary: dict[str, Any],
    descriptor_distribution: pd.DataFrame,
    null_report: pd.DataFrame,
    future_data_audit: pd.DataFrame,
) -> str:
    lines = [
        "# Strategy 2 Layer B Reaction Quality Diagnostics",
        "",
        "## Context",
        "",
        "Layer A taxonomy is now clean. Only `VALID_LONG` and `VALID_SHORT` states are eligible for Layer B reaction-quality descriptors. Behavioral Layer B remains unvalidated.",
        "",
        "## Method",
        "",
        "- Compute reaction candidate descriptors only.",
        "- Do not produce TAKE/SKIP decisions.",
        "- Do not use outcome columns.",
        "- Do not compute performance metrics.",
        "- Do not optimize thresholds.",
        "",
        "## Eligibility",
        "",
        f"- samples loaded: `{summary['samples_loaded']}`",
        f"- eligible VALID_LONG: `{summary['eligible_valid_long_count']}`",
        f"- eligible VALID_SHORT: `{summary['eligible_valid_short_count']}`",
        f"- excluded count: `{summary['excluded_count']}`",
        f"- MAE_NOT_REACHED reported separately: `{summary['mae_not_reached_count']}`",
        "",
        "Excluded states:",
        "",
    ]
    for state, count in summary["excluded_states"].items():
        lines.append(f"- `{state}`: `{count}`")
    lines.extend(["", "## Feature Distributions", "", "| Type | Value | Count | Rate |", "|---|---|---:|---:|"])
    for row in descriptor_distribution.to_dict("records"):
        lines.append(f"| {row['distribution_type']} | {row['value']} | {row['count']} | {row['rate']} |")
    lines.extend(["", "## Null / Missing Data", "", "| Feature | Null Or Unknown | Rate |", "|---|---:|---:|"])
    for row in null_report.head(20).to_dict("records"):
        lines.append(f"| {row['feature_name']} | {row['null_or_unknown_count']} | {row['null_or_unknown_rate']} |")
    lines.extend(["", "## Leakage Audit", "", "| Feature | Uses Future Data | Diagnostic Only | Allowed For Candidate Label |", "|---|---|---|---|"])
    for row in future_data_audit.to_dict("records"):
        lines.append(
            f"| {row['feature_name']} | {row['uses_future_data']} | {row['diagnostic_only']} | {row['allowed_for_candidate_label']} |"
        )
    lines.extend(
        [
            "",
            "Future-looking acceleration is exported only as diagnostic-only metadata and is not used in the candidate label.",
            "",
            "## Critical Limitations",
            "",
            "- Descriptors are not validated.",
            "- No manual labels are used yet.",
            "- No edge claim.",
            "- No deployment decision.",
            "- Human validation is required.",
            "",
            "## Verdict Flags",
            "",
            "\n".join(f"- `{flag}`" for flag in summary["verdict_flags"]),
            "",
            "## Next Strategy 2-Only Step",
            "",
            "`feat/strategy-2-layer-b-manual-validation-pack`",
        ]
    )
    return "\n".join(lines) + "\n"


OUTPUT_COLUMNS = [
    "sample_id",
    "h1_context_id",
    "direction_candidate",
    "layer_a_state",
    "layer_b_eligible",
    "sweep_timestamp",
    "decision_time",
    "feature_time_boundary",
    "data_window_start",
    "data_window_end",
    "range_reentry_detected",
    "time_to_reentry_seconds",
    "reentry_distance_usd",
    "reentry_distance_pips",
    "rejection_wick_ratio",
    "body_displacement_usd",
    "body_displacement_pips",
    "post_sweep_compression_seconds",
    "micro_range_size_usd",
    "micro_range_size_pips",
    "acceleration_after_reentry_usd",
    "acceleration_after_reentry_pips",
    "clean_vs_dirty_path_candidate",
    "reaction_descriptor",
    "layer_b_candidate_label",
    "uses_future_data",
    "diagnostic_only",
    "missing_required_data",
    "null_feature_reasons",
    "feature_warnings",
    "pip_factor_used",
]


def _timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    parsed = pd.to_datetime(text, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed


def _format_ts(value: pd.Timestamp | None) -> str:
    if value is None or pd.isna(value):
        return ""
    return value.isoformat()


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _to_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tri_state(value: Any) -> str:
    if value is None or pd.isna(value):
        return "UNKNOWN"
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return "TRUE"
    if text in {"false", "0", "no", "n"}:
        return "FALSE"
    return "UNKNOWN"


def _round(value: float | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 6)


def _join(values: list[str]) -> str:
    return ";".join(dict.fromkeys(value for value in values if value))


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


__all__ = [
    "LayerBReactionQualityResult",
    "VALID_LAYER_A_STATES",
    "build_layer_b_reaction_quality",
    "build_descriptor_distribution",
    "build_future_data_audit",
    "build_null_report",
    "candidate_label_for_descriptor",
    "classify_clean_dirty_path",
    "classify_reaction_descriptor",
    "compute_future_acceleration",
    "compute_reentry_distance",
    "compute_rejection_wick_ratio",
    "derive_reaction_features",
    "load_ohlc_data",
    "load_state_split_samples",
    "usd_to_pips",
    "write_layer_b_outputs",
]
