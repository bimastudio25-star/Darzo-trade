from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable, Literal

import pandas as pd


SweepDirection = Literal["sweep_low_then_expand_up", "sweep_high_then_expand_down"]
CandleDevelopmentModel = Literal["IMMEDIATE_EXPANSION", "ACCUMULATION_BEFORE_EXPANSION", "UNKNOWN"]


@dataclass(frozen=True)
class LiquidityExpansionStatsProfile:
    average_mae: float
    median_mae: float
    p75_mae: float
    p90_mae: float
    max_excursion: float
    average_expansion: float
    median_expansion: float
    max_expansion: float
    tp_quartile_distance: float
    suggested_sl_distance: float
    effective_risk_from_mae_entry: float
    effective_risk_gt_12: bool
    samples: int
    calibration_from: str | None = None
    calibration_to: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "average_mae": self.average_mae,
            "median_mae": self.median_mae,
            "p75_mae": self.p75_mae,
            "p90_mae": self.p90_mae,
            "max_excursion": self.max_excursion,
            "average_expansion": self.average_expansion,
            "median_expansion": self.median_expansion,
            "max_expansion": self.max_expansion,
            "tp_quartile_distance": self.tp_quartile_distance,
            "suggested_sl_distance": self.suggested_sl_distance,
            "effective_risk_from_mae_entry": self.effective_risk_from_mae_entry,
            "effective_risk_gt_12": self.effective_risk_gt_12,
            "samples": self.samples,
            "calibration_from": self.calibration_from,
            "calibration_to": self.calibration_to,
        }


EVENT_FIELDS = [
    "symbol",
    "timestamp",
    "direction",
    "h1_reference_timestamp",
    "h1_reference_level",
    "m15_0045_timestamp",
    "m15_0045_high",
    "m15_0045_low",
    "m15_sequence_valid",
    "max_adverse_excursion_from_h1_level",
    "average_adverse_excursion_candidate",
    "expansion_after_sweep",
    "max_expansion_after_sweep",
    "tp1_quartile_distance",
    "tp2_quartile_distance",
    "tp3_quartile_distance",
    "tp4_quartile_distance",
    "candle_development_model",
    "session_hour",
]


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value: Any) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _timestamp_text(value: Any) -> str | None:
    ts = _timestamp(value)
    return ts.isoformat() if ts is not None else None


def normalize_ohlc(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]
    out = out.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "tick_volume"})
    required = {"time", "open", "high", "low", "close"}
    if not required.issubset(set(out.columns)):
        return pd.DataFrame()
    out["time"] = pd.to_datetime(out["time"], utc=True, errors="coerce")
    for col in ("open", "high", "low", "close"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time").reset_index(drop=True)


def percentile(values: Iterable[float], q: float) -> float | None:
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return round(vals[0], 4)
    pos = (len(vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(vals) - 1)
    weight = pos - lo
    return round(vals[lo] * (1 - weight) + vals[hi] * weight, 4)


def find_h1_reference_for_time(h1: pd.DataFrame, when: Any) -> dict[str, Any] | None:
    frame = normalize_ohlc(h1)
    ts = _timestamp(when)
    if frame.empty or ts is None:
        return None
    current_candidates = frame[frame["time"] <= ts]
    if current_candidates.empty:
        return None
    current = current_candidates.iloc[-1]
    prior = frame[frame["time"] < current["time"]].tail(1)
    if prior.empty:
        return None
    ref = prior.iloc[0]
    return {
        "current_h1_timestamp": _timestamp_text(current["time"]),
        "h1_reference_timestamp": _timestamp_text(ref["time"]),
        "h1_reference_type": "previous_h1",
        "h1_high": round(float(ref["high"]), 4),
        "h1_low": round(float(ref["low"]), 4),
    }


def find_m15_0045_for_h1(m15: pd.DataFrame, h1_reference_timestamp: Any) -> dict[str, Any] | None:
    frame = normalize_ohlc(m15)
    h1_ts = _timestamp(h1_reference_timestamp)
    if frame.empty or h1_ts is None:
        return None
    target_ts = h1_ts + pd.Timedelta(minutes=45)
    exact = frame[frame["time"] == target_ts]
    if exact.empty:
        return None
    row = exact.iloc[0]
    return {
        "m15_0045_timestamp": _timestamp_text(row["time"]),
        "m15_0045_high": round(float(row["high"]), 4),
        "m15_0045_low": round(float(row["low"]), 4),
    }


def first_level_touch(
    m1: pd.DataFrame,
    *,
    start: Any,
    end: Any,
    level: float,
    side: Literal["high", "low"],
) -> pd.Timestamp | None:
    frame = normalize_ohlc(m1)
    start_ts = _timestamp(start)
    end_ts = _timestamp(end)
    if frame.empty or start_ts is None:
        return None
    if end_ts is None:
        end_ts = start_ts + pd.Timedelta(hours=1)
    window = frame[(frame["time"] >= start_ts) & (frame["time"] <= end_ts)]
    if side == "high":
        hits = window[window["high"] >= float(level)]
    else:
        hits = window[window["low"] <= float(level)]
    if hits.empty:
        return None
    return pd.Timestamp(hits.iloc[0]["time"])


def validate_liquidity_sequence(
    m1: pd.DataFrame,
    *,
    direction: Literal["LONG", "SHORT"],
    h1_start: Any,
    h1_level: float,
    m15_opposite_level: float,
    end: Any | None = None,
) -> dict[str, Any]:
    side = "low" if direction == "LONG" else "high"
    opp_side = "high" if direction == "LONG" else "low"
    h1_taken = first_level_touch(m1, start=h1_start, end=end, level=h1_level, side=side)
    opposite_taken = first_level_touch(m1, start=h1_start, end=h1_taken or end, level=m15_opposite_level, side=opp_side)
    valid = h1_taken is not None and (opposite_taken is None or h1_taken <= opposite_taken)
    reasons: list[str] = []
    if h1_taken is None:
        reasons.append("h1_liquidity_not_taken")
    if opposite_taken is not None and h1_taken is not None and opposite_taken < h1_taken:
        reasons.append("opposite_m15_level_taken_before_h1")
    if valid:
        reasons.append("liquidity_sequence_valid")
    return {
        "h1_liquidity_taken": h1_taken is not None,
        "h1_liquidity_taken_timestamp": _timestamp_text(h1_taken),
        "m15_opposite_level_taken_before_h1": bool(opposite_taken is not None and h1_taken is not None and opposite_taken < h1_taken),
        "liquidity_sequence_valid": valid,
        "liquidity_sequence_reason_codes": reasons,
    }


def expansion_quartiles(max_expansion: float) -> dict[str, float]:
    max_exp = max(0.0, float(max_expansion))
    return {
        "tp1_quartile_distance": round(max_exp * 0.25, 4),
        "tp2_quartile_distance": round(max_exp * 0.50, 4),
        "tp3_quartile_distance": round(max_exp * 0.75, 4),
        "tp4_quartile_distance": round(max_exp, 4),
    }


def adaptive_tp1_distance(*, average_expansion: float, max_expansion: float) -> float:
    standard = max(0.0, float(max_expansion)) * 0.25
    avg = max(0.0, float(average_expansion))
    return round(avg if avg > 0 and avg < standard else standard, 4)


def max_excursion_plus_25(max_excursion: float) -> float:
    return round(max(0.0, float(max_excursion)) * 1.25, 4)


def classify_candle_development_model(m1_window: pd.DataFrame, sweep_time: Any) -> CandleDevelopmentModel:
    frame = normalize_ohlc(m1_window)
    ts = _timestamp(sweep_time)
    if frame.empty or ts is None:
        return "UNKNOWN"
    pre = frame[frame["time"] < ts].tail(15)
    if len(pre) < 4:
        return "UNKNOWN"
    ranges = (pre["high"] - pre["low"]).astype(float)
    overlap_span = float(pre["high"].max() - pre["low"].min())
    avg_range = float(ranges.mean())
    if avg_range > 0 and overlap_span <= avg_range * 3:
        return "ACCUMULATION_BEFORE_EXPANSION"
    return "IMMEDIATE_EXPANSION"


def collect_h1_sweep_events(
    *,
    symbol: str,
    m1: pd.DataFrame,
    m15: pd.DataFrame,
    h1: pd.DataFrame,
    date_from: Any | None = None,
    date_to: Any | None = None,
) -> list[dict[str, Any]]:
    m1f = normalize_ohlc(m1)
    h1f = normalize_ohlc(h1)
    start = _timestamp(date_from) if date_from is not None else None
    end = _timestamp(date_to) if date_to is not None else None
    events: list[dict[str, Any]] = []
    if m1f.empty or h1f.empty or len(h1f) < 2:
        return events
    for idx in range(1, len(h1f)):
        prev = h1f.iloc[idx - 1]
        cur = h1f.iloc[idx]
        h1_start = pd.Timestamp(cur["time"])
        if start is not None and h1_start < start:
            continue
        if end is not None and h1_start > end:
            continue
        h1_end = h1_start + pd.Timedelta(hours=1)
        window = m1f[(m1f["time"] >= h1_start) & (m1f["time"] < h1_end)]
        if window.empty:
            continue
        m15_ref = find_m15_0045_for_h1(m15, prev["time"]) or {}
        prev_low = float(prev["low"])
        prev_high = float(prev["high"])
        low_hit = first_level_touch(window, start=h1_start, end=h1_end, level=prev_low, side="low")
        high_hit = first_level_touch(window, start=h1_start, end=h1_end, level=prev_high, side="high")
        if low_hit is not None:
            events.append(
                _event_from_sweep(
                    symbol=symbol,
                    window=window,
                    h1_reference_timestamp=prev["time"],
                    sweep_time=low_hit,
                    direction="sweep_low_then_expand_up",
                    h1_reference_level=prev_low,
                    m15_ref=m15_ref,
                    sequence_valid=validate_liquidity_sequence(
                        window,
                        direction="LONG",
                        h1_start=h1_start,
                        h1_level=prev_low,
                        m15_opposite_level=float(m15_ref.get("m15_0045_high", prev_high)),
                        end=h1_end,
                    )["liquidity_sequence_valid"],
                )
            )
        if high_hit is not None:
            events.append(
                _event_from_sweep(
                    symbol=symbol,
                    window=window,
                    h1_reference_timestamp=prev["time"],
                    sweep_time=high_hit,
                    direction="sweep_high_then_expand_down",
                    h1_reference_level=prev_high,
                    m15_ref=m15_ref,
                    sequence_valid=validate_liquidity_sequence(
                        window,
                        direction="SHORT",
                        h1_start=h1_start,
                        h1_level=prev_high,
                        m15_opposite_level=float(m15_ref.get("m15_0045_low", prev_low)),
                        end=h1_end,
                    )["liquidity_sequence_valid"],
                )
            )
    return events


def _event_from_sweep(
    *,
    symbol: str,
    window: pd.DataFrame,
    h1_reference_timestamp: Any,
    sweep_time: Any,
    direction: SweepDirection,
    h1_reference_level: float,
    m15_ref: dict[str, Any],
    sequence_valid: bool,
) -> dict[str, Any]:
    ts = _timestamp(sweep_time)
    after = window[window["time"] >= ts] if ts is not None else window
    if direction == "sweep_low_then_expand_up":
        adverse = max(0.0, h1_reference_level - float(after["low"].min()))
        expansion = max(0.0, float(after["high"].max()) - h1_reference_level)
    else:
        adverse = max(0.0, float(after["high"].max()) - h1_reference_level)
        expansion = max(0.0, h1_reference_level - float(after["low"].min()))
    quartiles = expansion_quartiles(expansion)
    return {
        "symbol": symbol,
        "timestamp": _timestamp_text(sweep_time),
        "direction": direction,
        "h1_reference_timestamp": _timestamp_text(h1_reference_timestamp),
        "h1_reference_level": round(float(h1_reference_level), 4),
        "m15_0045_timestamp": m15_ref.get("m15_0045_timestamp"),
        "m15_0045_high": m15_ref.get("m15_0045_high"),
        "m15_0045_low": m15_ref.get("m15_0045_low"),
        "m15_sequence_valid": sequence_valid,
        "max_adverse_excursion_from_h1_level": round(adverse, 4),
        "average_adverse_excursion_candidate": round(adverse, 4),
        "expansion_after_sweep": round(expansion, 4),
        "max_expansion_after_sweep": round(expansion, 4),
        **quartiles,
        "candle_development_model": classify_candle_development_model(window, sweep_time),
        "session_hour": ts.hour if ts is not None else None,
    }


def build_stats_profile(
    events: Iterable[dict[str, Any]],
    *,
    calibration_from: Any | None = None,
    calibration_to: Any | None = None,
) -> LiquidityExpansionStatsProfile:
    rows = list(events)
    mae = [float(v) for row in rows if (v := _to_float(row.get("max_adverse_excursion_from_h1_level"))) is not None]
    expansion = [float(v) for row in rows if (v := _to_float(row.get("max_expansion_after_sweep"))) is not None]
    avg_mae = round(fmean(mae), 4) if mae else 0.0
    median_mae = round(median(mae), 4) if mae else 0.0
    max_exc = round(max(mae), 4) if mae else 0.0
    avg_exp = round(fmean(expansion), 4) if expansion else 0.0
    median_exp = round(median(expansion), 4) if expansion else 0.0
    max_exp = round(max(expansion), 4) if expansion else 0.0
    sl_distance = max_excursion_plus_25(max_exc)
    effective_risk = round(avg_mae + sl_distance, 4)
    return LiquidityExpansionStatsProfile(
        average_mae=avg_mae,
        median_mae=median_mae,
        p75_mae=percentile(mae, 0.75) or 0.0,
        p90_mae=percentile(mae, 0.90) or 0.0,
        max_excursion=max_exc,
        average_expansion=avg_exp,
        median_expansion=median_exp,
        max_expansion=max_exp,
        tp_quartile_distance=round(max_exp * 0.25, 4),
        suggested_sl_distance=sl_distance,
        effective_risk_from_mae_entry=effective_risk,
        effective_risk_gt_12=effective_risk > 12.0,
        samples=len(rows),
        calibration_from=_timestamp_text(calibration_from),
        calibration_to=_timestamp_text(calibration_to),
    )


def build_stats_report(
    *,
    symbol: str,
    m1: pd.DataFrame,
    m15: pd.DataFrame,
    h1: pd.DataFrame,
    calibration_from: Any,
    calibration_to: Any,
) -> dict[str, Any]:
    events = collect_h1_sweep_events(
        symbol=symbol,
        m1=m1,
        m15=m15,
        h1=h1,
        date_from=calibration_from,
        date_to=calibration_to,
    )
    profile = build_stats_profile(events, calibration_from=calibration_from, calibration_to=calibration_to)
    summary = {
        "research_only": True,
        "symbol": symbol,
        "calibration_from": _timestamp_text(calibration_from),
        "calibration_to": _timestamp_text(calibration_to),
        "events": len(events),
        "profile": profile.to_dict(),
        "m15_sequence_valid_count": sum(1 for row in events if row.get("m15_sequence_valid")),
        "m15_sequence_valid_rate": round(sum(1 for row in events if row.get("m15_sequence_valid")) / len(events), 4) if events else 0.0,
        "candle_development_model_counts": dict(Counter(str(row.get("candle_development_model") or "UNKNOWN") for row in events)),
        "stat_profile_unrealistic": profile.effective_risk_gt_12 or profile.samples < 10,
    }
    return {
        "events": events,
        "profile": profile,
        "summary": summary,
        "report_markdown": render_stats_markdown(summary),
    }


def render_stats_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Strategy 2 Liquidity Expansion Statistics",
        "",
        "Status: research-only statistics profile. No optimization, no live trading, no deployment decision.",
        "",
        f"- symbol: `{summary['symbol']}`",
        f"- calibration window: `{summary['calibration_from']}` -> `{summary['calibration_to']}`",
        f"- sweep events: `{summary['events']}`",
        f"- M15 sequence valid rate: `{summary['m15_sequence_valid_rate']}`",
        f"- stat profile unrealistic: `{summary['stat_profile_unrealistic']}`",
        "",
        "## Profile",
        "",
        "```json",
        json.dumps(summary["profile"], indent=2, sort_keys=True),
        "```",
        "",
        "## Candle Development",
        "",
        "```json",
        json.dumps(summary["candle_development_model_counts"], indent=2, sort_keys=True),
        "```",
    ]
    return "\n".join(lines) + "\n"


def write_stats_outputs(report: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "events_csv": str(output_dir / "liquidity_expansion_events.csv"),
        "summary_json": str(output_dir / "liquidity_expansion_stats_summary.json"),
        "report_md": str(output_dir / "liquidity_expansion_stats_report.md"),
    }
    with Path(paths["events_csv"]).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EVENT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["events"])
    Path(paths["summary_json"]).write_text(json.dumps(report["summary"], indent=2, sort_keys=True, default=str), encoding="utf-8")
    Path(paths["report_md"]).write_text(report["report_markdown"], encoding="utf-8")
    return paths


__all__ = [
    "CandleDevelopmentModel",
    "EVENT_FIELDS",
    "LiquidityExpansionStatsProfile",
    "SweepDirection",
    "adaptive_tp1_distance",
    "build_stats_profile",
    "build_stats_report",
    "classify_candle_development_model",
    "collect_h1_sweep_events",
    "expansion_quartiles",
    "find_h1_reference_for_time",
    "find_m15_0045_for_h1",
    "first_level_touch",
    "max_excursion_plus_25",
    "normalize_ohlc",
    "validate_liquidity_sequence",
    "write_stats_outputs",
]
