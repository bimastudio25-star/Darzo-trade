"""Adelin v2 pre-entry vs outcome diagnostics.

This script is research-only. It reads existing visual-review sample metadata
and local OHLC data, then separates pre-entry context features from objective
post-entry outcomes. It does not generate candidates, run matched controls,
modify runtime logic, call broker/order code, send Telegram alerts, or claim
profitability.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.backtest.data_loader import load_csv_timeframes
from dazro_trade.core.symbols import get_symbol_spec


DEFAULT_VISUAL_PACK_DIR = Path("backtests/reports/adelin_v2_visual_review_pack")
DEFAULT_PHASE3_SCHEMA_PATH = Path(
    "backtests/reports/adelin_v2_phase_3_visual_review_labels/phase_3_label_schema.json"
)
DEFAULT_FEATURE_SPECS_PATH = Path(
    "backtests/reports/adelin_v2_pre_registered_context_feature_test_plan/feature_test_specs.json"
)
DEFAULT_OUTPUT_DIR = Path("backtests/reports/adelin_v2_preentry_outcome_diagnostics")

VERDICT_FLAGS = [
    "STATIC_LABELING_NOT_USABLE",
    "OBJECTIVE_REPLAY_DIAGNOSTICS_COMPLETE",
    "PRE_ENTRY_OUTCOME_SEPARATION_REPORTED",
    "FAILURE_MODES_REPORTED",
    "NO_PHASE_4_MATCHED_CONTROL_YET",
    "ADELIN_REMAINS_RESEARCH_ONLY",
    "NO_LIVE_DEPLOYMENT_DECISION",
]

FAILURE_MODES = [
    "NO_IMMEDIATE_REACTION",
    "REACTION_TOO_LATE",
    "PRICE_CHOP_AFTER_ENTRY",
    "TARGET_TOO_FAR",
    "STOP_TOO_TIGHT",
    "STOP_TOO_WIDE",
    "DIRTY_LIQUIDITY_CONTEXT",
    "LIQUIDITY_ALREADY_CONSUMED",
    "VOLUME_NOT_CONFIRMING_REVERSAL",
    "CONTINUATION_AGAINST_ENTRY",
    "INSUFFICIENT_DATA",
]

WIN_MODES = [
    "FAST_REACTION",
    "CLEAN_SWEEP_REJECTION",
    "ROUND_LEVEL_REACTION",
    "FVG_IFVG_REACTION",
    "VOLUME_CRACK_REACTION",
    "CLEAN_TARGET_SPACE",
    "STRONG_MFE_LOW_MAE",
]

CSV_OUTPUT = "sample_diagnostics.csv"
JSON_OUTPUT = "sample_diagnostics.json"
FEATURE_SUMMARY_OUTPUT = "feature_outcome_summary.csv"
FAILURE_SUMMARY_OUTPUT = "failure_modes_summary.csv"
WIN_SUMMARY_OUTPUT = "win_modes_summary.csv"
HUMAN_PRIORITY_OUTPUT = "human_review_priority.csv"
SUMMARY_OUTPUT = "summary.json"
DOC_OUTPUT = "objective_summary.md"


@dataclass(frozen=True)
class DiagnosticConfig:
    symbol: str = "XAUUSD"
    data_dir: Path = Path("data")
    visual_pack_dir: Path = DEFAULT_VISUAL_PACK_DIR
    phase3_schema_path: Path = DEFAULT_PHASE3_SCHEMA_PATH
    feature_specs_path: Path = DEFAULT_FEATURE_SPECS_PATH
    output_dir: Path = DEFAULT_OUTPUT_DIR
    direction_recovery_path: Path | None = None
    forward_minutes: int = 240
    fast_reaction_minutes: int = 15
    slow_reaction_minutes: int = 30
    diagnostic_only: bool = True


def parse_timestamp(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def as_iso(ts: pd.Timestamp | None) -> str:
    if ts is None or pd.isna(ts):
        return ""
    return pd.Timestamp(ts).isoformat()


def pips(distance: float | None, pip_size: float) -> float | None:
    if distance is None or pip_size <= 0 or not math.isfinite(float(distance)):
        return None
    return float(distance) / pip_size


def fmt(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return round(value, 6)
    if isinstance(value, pd.Timestamp):
        return as_iso(value)
    if isinstance(value, (list, tuple, set)):
        return "|".join(str(v) for v in value)
    return value


def load_visual_samples(visual_pack_dir: Path | str, symbol: str) -> tuple[list[dict[str, str]], list[str]]:
    labels_path = Path(visual_pack_dir) / "manual_labels_template.csv"
    if not labels_path.exists():
        return [], [f"VISUAL_REVIEW_TEMPLATE_MISSING:{labels_path}"]
    with labels_path.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if not symbol or row.get("symbol", symbol) == symbol]
    limitations = []
    if not rows:
        limitations.append("NO_VISUAL_SAMPLE_ROWS_LOADED")
    return rows, limitations


def load_direction_recovery_overrides(path: Path | str | None) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Load pre-entry direction recovery rows by sample_id.

    Recovery rows are rejected if they claim post-entry data was used. Unknown
    directions are left as unknown instead of being forced into replay.
    """
    if path is None:
        return {}, []
    recovery_path = Path(path)
    if not recovery_path.exists():
        return {}, [f"DIRECTION_RECOVERY_FILE_MISSING:{recovery_path}"]
    if recovery_path.suffix.lower() == ".json":
        payload = json.loads(recovery_path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("rows", [])
    else:
        with recovery_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    overrides: dict[str, dict[str, str]] = {}
    limitations: list[str] = []
    for row in rows:
        sample_id = str(row.get("sample_id") or "").strip()
        final_direction = str(row.get("final_direction") or "").strip().upper()
        used_post_entry = str(row.get("used_post_entry_data") or "").strip().lower()
        if not sample_id:
            limitations.append("DIRECTION_RECOVERY_ROW_MISSING_SAMPLE_ID")
            continue
        if used_post_entry in {"true", "1", "yes"}:
            limitations.append(f"DIRECTION_RECOVERY_ROW_REJECTED_POST_ENTRY:{sample_id}")
            continue
        if final_direction not in {"LONG", "SHORT"}:
            continue
        overrides[sample_id] = {str(key): "" if value is None else str(value) for key, value in row.items()}
    return overrides, limitations


def normalize_frames(frames: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for tf, df in frames.items():
        if df.empty:
            out[tf] = df
            continue
        frame = df.copy()
        frame["time"] = pd.to_datetime(frame["time"], utc=True)
        for col in ("open", "high", "low", "close", "tick_volume", "real_volume"):
            if col in frame.columns:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
        out[tf] = frame.sort_values("time").reset_index(drop=True)
    return out


def frame_window(
    frame: pd.DataFrame,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    *,
    include_end: bool = True,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    mask = pd.Series(True, index=frame.index)
    if start is not None:
        mask &= frame["time"] >= start
    if end is not None:
        mask &= frame["time"] <= end if include_end else frame["time"] < end
    return frame.loc[mask].copy()


def last_completed(frame: pd.DataFrame, ts: pd.Timestamp) -> pd.Series | None:
    subset = frame_window(frame, end=ts, include_end=True)
    if subset.empty:
        return None
    return subset.iloc[-1]


def first_forward(frame: pd.DataFrame, ts: pd.Timestamp, minutes: int) -> pd.DataFrame:
    end = ts + pd.Timedelta(minutes=minutes)
    return frame_window(frame, start=ts, end=end, include_end=True)


def candle_anatomy(candle: pd.Series | None, pip_size: float, prefix: str) -> dict[str, Any]:
    if candle is None:
        return {
            f"{prefix}_range_pips": None,
            f"{prefix}_body_ratio": None,
            f"{prefix}_upper_wick_ratio": None,
            f"{prefix}_lower_wick_ratio": None,
            f"{prefix}_close_location": None,
            f"{prefix}_tick_volume": None,
        }
    high = float(candle["high"])
    low = float(candle["low"])
    open_ = float(candle["open"])
    close = float(candle["close"])
    range_ = max(high - low, 0.0)
    body = abs(close - open_)
    upper = high - max(open_, close)
    lower = min(open_, close) - low
    return {
        f"{prefix}_range_pips": pips(range_, pip_size),
        f"{prefix}_body_ratio": body / range_ if range_ else 0.0,
        f"{prefix}_upper_wick_ratio": upper / range_ if range_ else 0.0,
        f"{prefix}_lower_wick_ratio": lower / range_ if range_ else 0.0,
        f"{prefix}_close_location": (close - low) / range_ if range_ else 0.5,
        f"{prefix}_tick_volume": float(candle["tick_volume"]) if "tick_volume" in candle else None,
    }


def classify_session(ts: pd.Timestamp) -> str:
    utc = pd.Timestamp(ts).tz_convert("UTC")
    minutes = utc.hour * 60 + utc.minute
    if 90 <= minutes < 180:
        return "ASIA_OPEN"
    if 180 <= minutes < 420:
        return "ASIA"
    if 510 <= minutes < 600:
        return "LONDON_OPEN"
    if 600 <= minutes < 780:
        return "LONDON"
    if 870 <= minutes < 960:
        return "NEW_YORK_OPEN"
    if 960 <= minutes < 1260:
        return "NEW_YORK"
    return "OTHER"


def nearest_numeric_level(price: float) -> tuple[float, float]:
    level = round(float(price) / 10.0) * 10.0
    return level, abs(float(price) - level)


def recent_liquidity_proxy(
    frames: Mapping[str, pd.DataFrame],
    decision_ts: pd.Timestamp,
    entry_price: float,
    pip_size: float,
) -> dict[str, Any]:
    best: dict[str, Any] = {
        "nearest_liquidity_level": None,
        "liquidity_type_timeframe": "",
        "distance_to_liquidity_pips": None,
    }
    best_distance: float | None = None
    for tf, minutes in (("H1", 24 * 60), ("M15", 6 * 60), ("M5", 2 * 60)):
        frame = frames.get(tf)
        if frame is None or frame.empty:
            continue
        pre = frame_window(frame, start=decision_ts - pd.Timedelta(minutes=minutes), end=decision_ts)
        if pre.empty:
            continue
        candidates = [
            ("RECENT_HIGH", float(pre["high"].max())),
            ("RECENT_LOW", float(pre["low"].min())),
        ]
        for kind, level in candidates:
            distance = abs(entry_price - level)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best = {
                    "nearest_liquidity_level": level,
                    "liquidity_type_timeframe": f"{tf}_{kind}",
                    "distance_to_liquidity_pips": pips(distance, pip_size),
                }
    return best


def fvg_ifvg_proxy(frames: Mapping[str, pd.DataFrame], decision_ts: pd.Timestamp, entry_price: float, pip_size: float) -> dict[str, Any]:
    m5 = frames.get("M5")
    out = {
        "fvg_ifvg_proximity_available": False,
        "nearest_fvg_ifvg_zone_type": "",
        "nearest_fvg_ifvg_distance_pips": None,
        "nearest_fvg_ifvg_zone_low": None,
        "nearest_fvg_ifvg_zone_high": None,
    }
    if m5 is None or m5.empty:
        return out
    pre = frame_window(m5, start=decision_ts - pd.Timedelta(hours=6), end=decision_ts)
    if len(pre) < 3:
        return out
    zones: list[dict[str, Any]] = []
    rows = list(pre.reset_index(drop=True).itertuples(index=False))
    for i in range(len(rows) - 2):
        c1, c2, c3 = rows[i], rows[i + 1], rows[i + 2]
        high1 = float(c1.high)
        low1 = float(c1.low)
        high3 = float(c3.high)
        low3 = float(c3.low)
        if low3 > high1:
            zone_low, zone_high = high1, low3
            zones.append({"type": "FVG_BULLISH", "low": zone_low, "high": zone_high})
        elif high3 < low1:
            zone_low, zone_high = high3, low1
            zones.append({"type": "FVG_BEARISH", "low": zone_low, "high": zone_high})
    if not zones:
        return out
    def zone_distance(zone: Mapping[str, Any]) -> float:
        if zone["low"] <= entry_price <= zone["high"]:
            return 0.0
        return min(abs(entry_price - float(zone["low"])), abs(entry_price - float(zone["high"])))
    nearest = min(zones, key=zone_distance)
    out.update(
        {
            "fvg_ifvg_proximity_available": True,
            "nearest_fvg_ifvg_zone_type": nearest["type"],
            "nearest_fvg_ifvg_distance_pips": pips(zone_distance(nearest), pip_size),
            "nearest_fvg_ifvg_zone_low": nearest["low"],
            "nearest_fvg_ifvg_zone_high": nearest["high"],
        }
    )
    return out


def compression_and_volume_proxy(frames: Mapping[str, pd.DataFrame], decision_ts: pd.Timestamp, pip_size: float) -> dict[str, Any]:
    m5 = frames.get("M5")
    out = {
        "compression_6_m5_range_pips": None,
        "compression_24_m5_range_pips": None,
        "compression_overlap_proxy": False,
        "expansion_before_decision_proxy": False,
        "m5_tick_volume_ratio_20": None,
        "volume_crack_proxy": False,
    }
    if m5 is None or m5.empty:
        return out
    pre = frame_window(m5, start=decision_ts - pd.Timedelta(hours=3), end=decision_ts)
    if len(pre) < 6:
        return out
    last6 = pre.tail(6)
    out["compression_6_m5_range_pips"] = pips(float(last6["high"].max() - last6["low"].min()), pip_size)
    if len(pre) >= 24:
        last24 = pre.tail(24)
        range24 = float(last24["high"].max() - last24["low"].min())
        out["compression_24_m5_range_pips"] = pips(range24, pip_size)
        if range24 > 0:
            out["compression_overlap_proxy"] = (float(last6["high"].max() - last6["low"].min()) / range24) <= 0.35
    last = pre.iloc[-1]
    anatomy = candle_anatomy(last, pip_size, "tmp")
    ranges = (pre.tail(20)["high"] - pre.tail(20)["low"]).astype(float)
    median_range = float(ranges.median()) if not ranges.empty else 0.0
    last_range = float(last["high"] - last["low"])
    out["expansion_before_decision_proxy"] = bool(median_range > 0 and last_range >= 2.0 * median_range and (anatomy["tmp_body_ratio"] or 0) >= 0.65)
    if "tick_volume" in pre.columns and len(pre) >= 20:
        last_vol = float(last.get("tick_volume", 0) or 0)
        avg_vol = float(pre.tail(20)["tick_volume"].mean())
        if avg_vol > 0:
            out["m5_tick_volume_ratio_20"] = last_vol / avg_vol
            out["volume_crack_proxy"] = out["m5_tick_volume_ratio_20"] >= 2.5 and (anatomy["tmp_body_ratio"] or 0) >= 0.70
    return out


def volatility_context(frames: Mapping[str, pd.DataFrame], decision_ts: pd.Timestamp, pip_size: float) -> dict[str, Any]:
    m15 = frames.get("M15")
    out = {"m15_context_range_pips": None, "volatility_range_context": "UNKNOWN"}
    if m15 is None or m15.empty:
        return out
    pre = frame_window(m15, start=decision_ts - pd.Timedelta(hours=12), end=decision_ts)
    if len(pre) < 12:
        return out
    recent = pre.tail(8)
    range_recent = float(recent["high"].max() - recent["low"].min())
    out["m15_context_range_pips"] = pips(range_recent, pip_size)
    candle_ranges = (pre["high"] - pre["low"]).astype(float)
    q25 = float(candle_ranges.quantile(0.25))
    q75 = float(candle_ranges.quantile(0.75))
    median_recent = float((recent["high"] - recent["low"]).median())
    if median_recent >= q75:
        out["volatility_range_context"] = "HIGH"
    elif median_recent <= q25:
        out["volatility_range_context"] = "LOW"
    else:
        out["volatility_range_context"] = "MID"
    return out


def target_space_proxy(
    frames: Mapping[str, pd.DataFrame],
    decision_ts: pd.Timestamp,
    entry_price: float,
    direction: str,
    pip_size: float,
) -> dict[str, Any]:
    out = {"target_space_proxy_pips": None, "target_space_proxy_source": ""}
    if direction not in {"LONG", "SHORT"}:
        return out
    m15 = frames.get("M15")
    if m15 is None or m15.empty:
        return out
    pre = frame_window(m15, start=decision_ts - pd.Timedelta(hours=6), end=decision_ts)
    if pre.empty:
        return out
    if direction == "LONG":
        level = float(pre["high"].max())
        distance = level - entry_price
        source = "RECENT_M15_HIGH"
    else:
        level = float(pre["low"].min())
        distance = entry_price - level
        source = "RECENT_M15_LOW"
    out["target_space_proxy_pips"] = pips(max(distance, 0.0), pip_size)
    out["target_space_proxy_source"] = source
    return out


def entry_reference(frames: Mapping[str, pd.DataFrame], decision_ts: pd.Timestamp) -> tuple[float | None, str]:
    for tf in ("M1", "M5", "M15"):
        frame = frames.get(tf)
        if frame is None or frame.empty:
            continue
        candle = last_completed(frame, decision_ts)
        if candle is not None:
            return float(candle["close"]), f"LAST_COMPLETED_{tf}_CLOSE_AT_DECISION"
    return None, "MISSING_ENTRY_REFERENCE"


def entry_cross_count(forward: pd.DataFrame, entry_price: float, minutes: int = 60) -> int:
    if forward.empty:
        return 0
    end = forward["time"].iloc[0] + pd.Timedelta(minutes=minutes)
    first = forward[forward["time"] <= end]
    count = 0
    previous_side: int | None = None
    for close in first["close"].astype(float):
        side = 1 if close > entry_price else -1 if close < entry_price else 0
        if side == 0:
            continue
        if previous_side is not None and side != previous_side:
            count += 1
        previous_side = side
    return count


def first_time_to_threshold(
    forward: pd.DataFrame,
    decision_ts: pd.Timestamp,
    entry_price: float,
    direction: str,
    favorable_pips: float | None,
    adverse_pips: float | None,
    pip_size: float,
) -> tuple[float | None, float | None]:
    fav_time: float | None = None
    adv_time: float | None = None
    for row in forward.itertuples(index=False):
        elapsed = (pd.Timestamp(row.time) - decision_ts).total_seconds() / 60.0
        if direction == "LONG":
            fav = (float(row.high) - entry_price) / pip_size
            adv = (entry_price - float(row.low)) / pip_size
        else:
            fav = (entry_price - float(row.low)) / pip_size
            adv = (float(row.high) - entry_price) / pip_size
        if favorable_pips is not None and fav_time is None and fav >= favorable_pips:
            fav_time = elapsed
        if adverse_pips is not None and adv_time is None and adv >= adverse_pips:
            adv_time = elapsed
        if (favorable_pips is None or fav_time is not None) and (adverse_pips is None or adv_time is not None):
            break
    return fav_time, adv_time


def replay_outcome(
    frames: Mapping[str, pd.DataFrame],
    decision_ts: pd.Timestamp,
    entry_price: float | None,
    direction: str,
    pip_size: float,
    forward_minutes: int,
    target_space_pips: float | None,
    round_confluence: bool,
    fvg_distance_pips: float | None,
    volume_crack_proxy: bool,
    m1_anatomy: Mapping[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "post_entry_replay_available": False,
        "max_favorable_pips": None,
        "max_adverse_pips": None,
        "max_favorable_usd": None,
        "max_adverse_usd": None,
        "max_favorable_r_20pip": None,
        "max_adverse_r_20pip": None,
        "time_to_first_50p_favorable_minutes": None,
        "time_to_first_100p_favorable_minutes": None,
        "time_to_first_20p_adverse_minutes": None,
        "time_to_first_40p_adverse_minutes": None,
        "tp1_proxy_50p_hit": False,
        "tp2_proxy_100p_hit": False,
        "tp3_proxy_250p_hit": False,
        "tp4_proxy_500p_hit": False,
        "sl20_hit": False,
        "sl40_hit": False,
        "timeout_no_followthrough": False,
        "entry_cross_count_first_60m": 0,
        "final_diagnostic_outcome": "INSUFFICIENT_DATA",
        "failure_mode_tags": ["INSUFFICIENT_DATA"],
        "win_mode_tags": [],
        "limitations": [],
    }
    if direction not in {"LONG", "SHORT"}:
        out["limitations"].append("UNKNOWN_DIRECTION_NO_DIRECTIONAL_REPLAY")
        return out
    if entry_price is None:
        out["limitations"].append("MISSING_ENTRY_REFERENCE")
        return out
    m1 = frames.get("M1")
    if m1 is None or m1.empty:
        out["limitations"].append("MISSING_M1_FORWARD_DATA")
        return out
    forward = first_forward(m1, decision_ts, forward_minutes)
    forward = forward[forward["time"] > decision_ts]
    if forward.empty:
        out["limitations"].append("NO_FORWARD_CANDLES_AFTER_DECISION")
        return out
    out["post_entry_replay_available"] = True
    if direction == "LONG":
        mfe = float(forward["high"].max()) - entry_price
        mae = entry_price - float(forward["low"].min())
    else:
        mfe = entry_price - float(forward["low"].min())
        mae = float(forward["high"].max()) - entry_price
    mfe_pips = max(mfe / pip_size, 0.0)
    mae_pips = max(mae / pip_size, 0.0)
    out.update(
        {
            "max_favorable_pips": mfe_pips,
            "max_adverse_pips": mae_pips,
            "max_favorable_usd": mfe,
            "max_adverse_usd": mae,
            "max_favorable_r_20pip": mfe_pips / 20.0,
            "max_adverse_r_20pip": mae_pips / 20.0,
            "tp1_proxy_50p_hit": mfe_pips >= 50,
            "tp2_proxy_100p_hit": mfe_pips >= 100,
            "tp3_proxy_250p_hit": mfe_pips >= 250,
            "tp4_proxy_500p_hit": mfe_pips >= 500,
            "sl20_hit": mae_pips >= 20,
            "sl40_hit": mae_pips >= 40,
            "entry_cross_count_first_60m": entry_cross_count(forward, entry_price),
        }
    )
    t50, t20 = first_time_to_threshold(forward, decision_ts, entry_price, direction, 50, 20, pip_size)
    t100, t40 = first_time_to_threshold(forward, decision_ts, entry_price, direction, 100, 40, pip_size)
    out.update(
        {
            "time_to_first_50p_favorable_minutes": t50,
            "time_to_first_100p_favorable_minutes": t100,
            "time_to_first_20p_adverse_minutes": t20,
            "time_to_first_40p_adverse_minutes": t40,
        }
    )
    out["timeout_no_followthrough"] = t50 is None
    failures: list[str] = []
    wins: list[str] = []
    if t50 is None or (t50 is not None and t50 > 60):
        failures.append("NO_IMMEDIATE_REACTION")
    if t100 is not None and t100 > 30:
        failures.append("REACTION_TOO_LATE")
    if out["entry_cross_count_first_60m"] >= 3:
        failures.append("PRICE_CHOP_AFTER_ENTRY")
    if target_space_pips is not None and target_space_pips < 50:
        failures.append("TARGET_TOO_FAR")
    if t20 is not None and (t50 is None or t20 < t50) and mae_pips < 40:
        failures.append("STOP_TOO_TIGHT")
    if mae_pips > 40 and mfe_pips < 50:
        failures.append("STOP_TOO_WIDE")
    if target_space_pips is None:
        failures.append("DIRTY_LIQUIDITY_CONTEXT")
    if t40 is not None and (t50 is None or t40 < t50):
        failures.append("CONTINUATION_AGAINST_ENTRY")
    if not volume_crack_proxy and mfe_pips < 50:
        failures.append("VOLUME_NOT_CONFIRMING_REVERSAL")

    if t100 is not None and t100 <= 15:
        wins.append("FAST_REACTION")
    lower_wick = float(m1_anatomy.get("m1_lower_wick_ratio") or 0)
    upper_wick = float(m1_anatomy.get("m1_upper_wick_ratio") or 0)
    if (direction == "LONG" and lower_wick >= 0.45 and mfe_pips >= 50) or (
        direction == "SHORT" and upper_wick >= 0.45 and mfe_pips >= 50
    ):
        wins.append("CLEAN_SWEEP_REJECTION")
    if round_confluence and mfe_pips >= 50:
        wins.append("ROUND_LEVEL_REACTION")
    if fvg_distance_pips is not None and fvg_distance_pips <= 20 and mfe_pips >= 50:
        wins.append("FVG_IFVG_REACTION")
    if volume_crack_proxy and mfe_pips >= 50:
        wins.append("VOLUME_CRACK_REACTION")
    if target_space_pips is not None and target_space_pips >= 100 and mfe_pips >= 50:
        wins.append("CLEAN_TARGET_SPACE")
    if mfe_pips >= 100 and mae_pips <= 20:
        wins.append("STRONG_MFE_LOW_MAE")

    if not failures and not wins:
        failures.append("NO_IMMEDIATE_REACTION")
    if "FAST_REACTION" in wins or "STRONG_MFE_LOW_MAE" in wins:
        final = "GOOD_FAST_REACTION" if "FAST_REACTION" in wins else "STRONG_MFE_LOW_MAE"
    elif mfe_pips >= 100 and mae_pips <= 40:
        final = "GOOD_REACTION_DIRTY_OR_SLOW"
    elif t20 is not None and (t50 is None or t20 < t50):
        final = "FAST_FAILURE"
    elif out["entry_cross_count_first_60m"] >= 3:
        final = "CHOP_AFTER_ENTRY"
    elif t50 is None:
        final = "NO_FOLLOW_THROUGH"
    else:
        final = "MIXED_REACTION"
    out["final_diagnostic_outcome"] = final
    out["failure_mode_tags"] = sorted(set(failures))
    out["win_mode_tags"] = sorted(set(wins))
    return out


def compute_sample_diagnostic(
    sample: Mapping[str, str],
    frames: Mapping[str, pd.DataFrame],
    symbol: str,
    pip_size: float,
    forward_minutes: int,
) -> dict[str, Any]:
    decision_ts = parse_timestamp(sample.get("anchor_timestamp") or sample.get("decision_timestamp"))
    direction = (sample.get("direction_guess") or "").strip().upper()
    if direction not in {"LONG", "SHORT"}:
        direction = "UNKNOWN"
    row: dict[str, Any] = {
        "sample_id": sample.get("sample_id", ""),
        "source_mode": sample.get("source_mode", ""),
        "symbol": sample.get("symbol") or symbol,
        "direction": direction,
        "direction_recovery_source": sample.get("direction_recovery_source", ""),
        "direction_recovery_confidence": sample.get("direction_recovery_confidence", ""),
        "direction_recovery_reason": sample.get("direction_recovery_reason", ""),
        "decision_timestamp": as_iso(decision_ts),
        "chart_path": sample.get("chart_path", ""),
        "html_path": sample.get("html_path", ""),
        "execution_data_status": sample.get("execution_data_status", ""),
    }
    if decision_ts is None:
        row.update(
            {
                "entry_reference_price": "",
                "entry_reference_source": "MISSING_DECISION_TIMESTAMP",
                "final_diagnostic_outcome": "INSUFFICIENT_DATA",
                "failure_mode_tags": "INSUFFICIENT_DATA",
                "win_mode_tags": "",
                "limitations": "MISSING_DECISION_TIMESTAMP",
            }
        )
        return row
    entry_price, entry_source = entry_reference(frames, decision_ts)
    row["entry_reference_price"] = entry_price
    row["entry_reference_source"] = entry_source

    m1_candle = last_completed(frames.get("M1", pd.DataFrame()), decision_ts)
    m5_candle = last_completed(frames.get("M5", pd.DataFrame()), decision_ts)
    m15_candle = last_completed(frames.get("M15", pd.DataFrame()), decision_ts)
    row.update(candle_anatomy(m1_candle, pip_size, "m1"))
    row.update(candle_anatomy(m5_candle, pip_size, "m5"))
    row.update(candle_anatomy(m15_candle, pip_size, "m15"))
    row["session"] = classify_session(decision_ts)

    if entry_price is not None:
        level, dist_usd = nearest_numeric_level(entry_price)
        round_distance_pips = pips(dist_usd, pip_size)
        row.update(
            {
                "nearest_round_level": level,
                "round_level_distance_pips": round_distance_pips,
                "numeric_level_confluence_20p": bool(round_distance_pips is not None and round_distance_pips <= 20),
                "tight_numeric_level_touch_band": (
                    "0-10_PIPS"
                    if round_distance_pips is not None and round_distance_pips <= 10
                    else "10-20_PIPS"
                    if round_distance_pips is not None and round_distance_pips <= 20
                    else "GT_20_PIPS"
                    if round_distance_pips is not None
                    else "UNKNOWN"
                ),
            }
        )
        row.update(recent_liquidity_proxy(frames, decision_ts, entry_price, pip_size))
        row.update(fvg_ifvg_proxy(frames, decision_ts, entry_price, pip_size))
        row.update(compression_and_volume_proxy(frames, decision_ts, pip_size))
        row.update(volatility_context(frames, decision_ts, pip_size))
        row.update(target_space_proxy(frames, decision_ts, entry_price, direction, pip_size))
        row["sl20_price_proxy"] = entry_price - 20 * pip_size if direction == "LONG" else entry_price + 20 * pip_size if direction == "SHORT" else ""
        row["sl40_price_proxy"] = entry_price - 40 * pip_size if direction == "LONG" else entry_price + 40 * pip_size if direction == "SHORT" else ""
    else:
        row.update(
            {
                "nearest_round_level": "",
                "round_level_distance_pips": "",
                "numeric_level_confluence_20p": False,
                "tight_numeric_level_touch_band": "UNKNOWN",
                "limitations": "MISSING_ENTRY_REFERENCE",
            }
        )

    outcome = replay_outcome(
        frames,
        decision_ts,
        entry_price,
        direction,
        pip_size,
        forward_minutes,
        row.get("target_space_proxy_pips") if isinstance(row.get("target_space_proxy_pips"), (int, float)) else None,
        bool(row.get("numeric_level_confluence_20p")),
        row.get("nearest_fvg_ifvg_distance_pips") if isinstance(row.get("nearest_fvg_ifvg_distance_pips"), (int, float)) else None,
        bool(row.get("volume_crack_proxy")),
        row,
    )
    row.update(outcome)
    row["limitations"] = "|".join(sorted(set(str(v) for v in outcome.get("limitations", []) if v)))
    row["failure_mode_tags"] = "|".join(outcome.get("failure_mode_tags", []))
    row["win_mode_tags"] = "|".join(outcome.get("win_mode_tags", []))
    return row


def is_good_outcome(row: Mapping[str, Any]) -> bool:
    return str(row.get("final_diagnostic_outcome")) in {
        "GOOD_FAST_REACTION",
        "STRONG_MFE_LOW_MAE",
        "GOOD_REACTION_DIRTY_OR_SLOW",
    }


def is_bad_outcome(row: Mapping[str, Any]) -> bool:
    return str(row.get("final_diagnostic_outcome")) in {
        "FAST_FAILURE",
        "CHOP_AFTER_ENTRY",
        "NO_FOLLOW_THROUGH",
        "INSUFFICIENT_DATA",
    }


def feature_flags(row: Mapping[str, Any]) -> dict[str, bool]:
    return {
        "numeric_level_confluence_20p": bool(row.get("numeric_level_confluence_20p")),
        "fvg_ifvg_near_20p": isinstance(row.get("nearest_fvg_ifvg_distance_pips"), (int, float))
        and float(row["nearest_fvg_ifvg_distance_pips"]) <= 20,
        "m5_displacement_proxy": bool(row.get("expansion_before_decision_proxy")),
        "compression_overlap_proxy": bool(row.get("compression_overlap_proxy")),
        "volume_crack_proxy": bool(row.get("volume_crack_proxy")),
        "premium_session_open": str(row.get("session")) in {"ASIA_OPEN", "LONDON_OPEN", "NEW_YORK_OPEN"},
        "high_volatility_context": str(row.get("volatility_range_context")) == "HIGH",
        "clean_target_space_proxy": isinstance(row.get("target_space_proxy_pips"), (int, float))
        and float(row["target_space_proxy_pips"]) >= 100,
    }


def summarize_feature_outcomes(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    features = sorted({key for row in rows for key in feature_flags(row)})
    summary: list[dict[str, Any]] = []
    for feature in features:
        present = [row for row in rows if feature_flags(row).get(feature)]
        absent = [row for row in rows if not feature_flags(row).get(feature)]
        summary.append(
            {
                "feature": feature,
                "present_count": len(present),
                "present_good_count": sum(is_good_outcome(row) for row in present),
                "present_bad_count": sum(is_bad_outcome(row) for row in present),
                "absent_count": len(absent),
                "absent_good_count": sum(is_good_outcome(row) for row in absent),
                "absent_bad_count": sum(is_bad_outcome(row) for row in absent),
                "note": "Descriptive only; no edge claim and no matched controls in this branch.",
            }
        )
    return summary


def summarize_tag_counts(rows: Sequence[Mapping[str, Any]], column: str) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in rows:
        tags = str(row.get(column, "")).split("|")
        for tag in tags:
            if tag:
                counts[tag] += 1
    return [{"tag": tag, "count": count} for tag, count in counts.most_common()]


def human_review_priority(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        score = 0
        reasons: list[str] = []
        outcome = str(row.get("final_diagnostic_outcome", ""))
        mfe = float(row.get("max_favorable_pips") or 0)
        mae = float(row.get("max_adverse_pips") or 0)
        if outcome == "INSUFFICIENT_DATA" or row.get("limitations"):
            score += 4
            reasons.append("DATA_OR_DIRECTION_LIMITATION")
        if mfe >= 250 or mae >= 40:
            score += 3
            reasons.append("EXTREME_OUTCOME")
        flags = feature_flags(row)
        pre_feature_count = sum(1 for value in flags.values() if value)
        if is_good_outcome(row) and pre_feature_count <= 1:
            score += 2
            reasons.append("GOOD_OUTCOME_WITH_FEW_PRE_FEATURES")
        if is_bad_outcome(row) and pre_feature_count >= 3:
            score += 2
            reasons.append("BAD_OUTCOME_DESPITE_PRE_FEATURES")
        if outcome in {"MIXED_REACTION", "GOOD_REACTION_DIRTY_OR_SLOW"}:
            score += 2
            reasons.append("AMBIGUOUS_REACTION")
        out.append(
            {
                "sample_id": row.get("sample_id", ""),
                "priority_score": score,
                "priority_reasons": "|".join(reasons) if reasons else "LOW_PRIORITY_BASELINE",
                "final_diagnostic_outcome": outcome,
                "failure_mode_tags": row.get("failure_mode_tags", ""),
                "win_mode_tags": row.get("win_mode_tags", ""),
                "chart_path": row.get("chart_path", ""),
                "html_path": row.get("html_path", ""),
            }
        )
    return sorted(out, key=lambda item: (-int(item["priority_score"]), str(item["sample_id"])))


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field)) for field in fields})


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def run_diagnostics(config: DiagnosticConfig) -> dict[str, Any]:
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    symbol_spec = get_symbol_spec(config.symbol)
    samples, sample_limitations = load_visual_samples(config.visual_pack_dir, config.symbol)
    direction_overrides, direction_recovery_limitations = load_direction_recovery_overrides(config.direction_recovery_path)
    if direction_overrides:
        updated_samples: list[dict[str, str]] = []
        for sample in samples:
            sample_copy = dict(sample)
            override = direction_overrides.get(str(sample_copy.get("sample_id") or ""))
            if override:
                sample_copy["direction_guess"] = override.get("final_direction", sample_copy.get("direction_guess", ""))
                sample_copy["direction_recovery_source"] = override.get("direction_source", "")
                sample_copy["direction_recovery_confidence"] = override.get("direction_confidence", "")
                sample_copy["direction_recovery_reason"] = override.get("direction_recovery_reason", "")
            updated_samples.append(sample_copy)
        samples = updated_samples
    frames = normalize_frames(
        load_csv_timeframes(config.symbol, ["M1", "M5", "M15", "H1"], data_dir=str(config.data_dir))
    )
    frame_limitations = []
    for tf in ("M1", "M5", "M15", "H1"):
        if tf not in frames or frames[tf].empty:
            frame_limitations.append(f"MISSING_{tf}_DATA")
    rows: list[dict[str, Any]] = []
    for sample in samples:
        rows.append(
            compute_sample_diagnostic(
                sample,
                frames,
                config.symbol,
                symbol_spec.pip_size,
                config.forward_minutes,
            )
        )

    feature_summary = summarize_feature_outcomes(rows)
    failure_summary = summarize_tag_counts(rows, "failure_mode_tags")
    win_summary = summarize_tag_counts(rows, "win_mode_tags")
    priority = human_review_priority(rows)
    outcome_counts = Counter(str(row.get("final_diagnostic_outcome", "")) for row in rows)
    sufficient = sum(bool(row.get("post_entry_replay_available")) for row in rows)
    insufficient = len(rows) - sufficient
    limitations = sorted(
        set(
            sample_limitations
            + direction_recovery_limitations
            + frame_limitations
            + [v for row in rows for v in str(row.get("limitations", "")).split("|") if v]
        )
    )
    summary = {
        "run_started_at": datetime.now(timezone.utc).isoformat(),
        "symbol": config.symbol,
        "output_dir": str(output_dir),
        "visual_pack_dir": str(config.visual_pack_dir),
        "phase3_schema_path": str(config.phase3_schema_path),
        "feature_specs_path": str(config.feature_specs_path),
        "direction_recovery_path": str(config.direction_recovery_path) if config.direction_recovery_path else None,
        "direction_recovery_applied": bool(direction_overrides),
        "direction_recovery_override_count": len(direction_overrides),
        "ohlc_data_read": True,
        "forward_minutes": config.forward_minutes,
        "pip_size": symbol_spec.pip_size,
        "verdict_flags": VERDICT_FLAGS,
        "total_samples_analyzed": len(rows),
        "samples_with_sufficient_data": sufficient,
        "samples_with_insufficient_data": insufficient,
        "outcome_distribution": dict(outcome_counts),
        "top_failure_modes": failure_summary[:10],
        "top_win_modes": win_summary[:10],
        "feature_presence_vs_outcome_rows": len(feature_summary),
        "human_review_priority_rows": len(priority),
        "limitations": limitations,
        "pre_entry_outcome_separation": {
            "pre_entry_features": "computed only from data at or before decision timestamp",
            "post_entry_outcomes": "computed only after decision timestamp for diagnostics",
            "diagnostic_tags": "assigned after replay; not used to redefine pre-entry features",
        },
        "safety": {
            "old_adelin_runtime_modified": False,
            "strategy_2_touched": False,
            "strategy_3_touched": False,
            "live_trading_enabled": False,
            "telegram_trade_alerts_enabled": False,
            "broker_execution_enabled": False,
            "order_execution_enabled": False,
            "candidate_pack_generated": False,
            "matched_control_replay_run": False,
            "phase_4_started": False,
            "thresholds_tuned": False,
            "v3_stash_applied_or_popped": False,
        },
    }
    summary["run_finished_at"] = datetime.now(timezone.utc).isoformat()

    write_csv(output_dir / CSV_OUTPUT, rows)
    write_json(output_dir / JSON_OUTPUT, rows)
    write_csv(output_dir / FEATURE_SUMMARY_OUTPUT, feature_summary)
    write_csv(output_dir / FAILURE_SUMMARY_OUTPUT, failure_summary)
    write_csv(output_dir / WIN_SUMMARY_OUTPUT, win_summary)
    write_csv(output_dir / HUMAN_PRIORITY_OUTPUT, priority)
    write_json(output_dir / SUMMARY_OUTPUT, summary)
    write_markdown_summary(output_dir / DOC_OUTPUT, summary)
    return summary


def write_markdown_summary(path: Path, summary: Mapping[str, Any]) -> None:
    lines = [
        "# Adelin v2 Pre-entry Outcome Diagnostics Summary",
        "",
        "Research-only diagnostic replay. This is not validation, not Phase 4 matched-control replay, and not a live decision.",
        "",
        f"- samples analyzed: {summary['total_samples_analyzed']}",
        f"- sufficient data: {summary['samples_with_sufficient_data']}",
        f"- insufficient data: {summary['samples_with_insufficient_data']}",
        f"- output dir: `{summary['output_dir']}`",
        "",
        "## Verdict flags",
        "",
    ]
    lines.extend(f"- {flag}" for flag in summary["verdict_flags"])
    lines.extend(["", "## Outcome distribution", ""])
    for key, value in summary["outcome_distribution"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Top failure modes", ""])
    for item in summary["top_failure_modes"]:
        lines.append(f"- {item['tag']}: {item['count']}")
    lines.extend(["", "## Top win modes", ""])
    for item in summary["top_win_modes"]:
        lines.append(f"- {item['tag']}: {item['count']}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- no old Adelin runtime changes",
            "- no Strategy 2 or Strategy 3 changes",
            "- no live trading",
            "- no Telegram trade alerts",
            "- no broker/order execution",
            "- no candidate generation",
            "- no matched-control replay",
            "- no threshold tuning",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Adelin v2 pre-entry/outcome diagnostics.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--visual-pack-dir", default=str(DEFAULT_VISUAL_PACK_DIR))
    parser.add_argument("--phase3-schema-path", default=str(DEFAULT_PHASE3_SCHEMA_PATH))
    parser.add_argument("--feature-specs-path", default=str(DEFAULT_FEATURE_SPECS_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--direction-recovery-path", default=None)
    parser.add_argument("--forward-minutes", type=int, default=240)
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser


def config_from_args(args: argparse.Namespace) -> DiagnosticConfig:
    return DiagnosticConfig(
        symbol=args.symbol,
        data_dir=Path(args.data_dir),
        visual_pack_dir=Path(args.visual_pack_dir),
        phase3_schema_path=Path(args.phase3_schema_path),
        feature_specs_path=Path(args.feature_specs_path),
        output_dir=Path(args.output_dir),
        direction_recovery_path=Path(args.direction_recovery_path) if args.direction_recovery_path else None,
        forward_minutes=args.forward_minutes,
        diagnostic_only=bool(args.dry_run),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_diagnostics(config_from_args(args))
    print(
        json.dumps(
            {
                "output_dir": summary["output_dir"],
                "total_samples_analyzed": summary["total_samples_analyzed"],
                "samples_with_sufficient_data": summary["samples_with_sufficient_data"],
                "samples_with_insufficient_data": summary["samples_with_insufficient_data"],
                "top_failure_modes": summary["top_failure_modes"][:5],
                "top_win_modes": summary["top_win_modes"][:5],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
