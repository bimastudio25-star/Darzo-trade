"""Objective Adelin v2 visual-sample outcome replay.

This module is diagnostic-only. It reads visual review samples and historical
candles, replays transparent entry-level hypotheses, and writes
candidate-vs-control baseline reports. It does not import or call live trading,
broker, order, or notification code.
"""
from __future__ import annotations

import csv
import html
import json
import math
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from dazro_trade.backtest.data_loader import load_csv_timeframes
from dazro_trade.core.symbols import get_symbol_spec, price_to_pips


DEFAULT_VISUAL_PACK_DIR = Path("backtests/reports/adelin_v2_visual_review_pack")
DEFAULT_OUTPUT_DIR = Path("backtests/reports/adelin_v2_objective_outcome_replay")
ROUND_LEVEL_TOUCH_ENTRY = "ROUND_LEVEL_TOUCH_ENTRY"
ROUND_LEVEL = "ROUND_LEVEL"
SWEEP_EXTREME = "SWEEP_EXTREME"
SWEPT_LIQUIDITY_LEVEL = "SWEPT_LIQUIDITY_LEVEL"
REACTION_ZONE_LEVEL = "REACTION_ZONE_LEVEL"
FVG_BOUNDARY = "FVG_BOUNDARY"
IFVG_BOUNDARY = "IFVG_BOUNDARY"
ANCHOR_LEVEL = "ANCHOR_LEVEL"
UNKNOWN_ENTRY_SOURCE = "UNKNOWN"
ENTRY_DIRECTION_CONFLICT = "ENTRY_DIRECTION_CONFLICT"
UNKNOWN_ENTRY_LEVEL = "UNKNOWN_ENTRY_LEVEL"
UNKNOWN_DIRECTION = "UNKNOWN_DIRECTION"
UNKNOWN_INSUFFICIENT_FORWARD_DATA = "UNKNOWN_INSUFFICIENT_FORWARD_DATA"
FAST_SL_20 = "FAST_SL_20"
FAST_SL_40 = "FAST_SL_40"
NO_REACTION = "NO_REACTION"
GOOD_FAST_REACTION = "GOOD_FAST_REACTION"
GOOD_SLOW_REACTION = "GOOD_SLOW_REACTION"
GOOD_REACTION_BUT_DIRTY_ACCUMULATION = "GOOD_REACTION_BUT_DIRTY_ACCUMULATION"
MFE_GOOD_BUT_BE_REQUIRED = "MFE_GOOD_BUT_BE_REQUIRED"
RUNNER_CANDIDATE = "RUNNER_CANDIDATE"
STRONG_RUNNER = "STRONG_RUNNER"
CHECKPOINT_MINUTES = (5, 15, 30, 60, 240)
MILESTONES = (50, 100, 250, 500, 1000)
OUTPUT_CSV = "objective_outcome_replay.csv"
OUTPUT_JSON = "objective_outcome_replay_summary.json"
OUTPUT_MD = "objective_outcome_replay.md"
OUTPUT_HTML = "index.html"
OUTPUT_ENRICHED_LABELS = "enriched_manual_labels_template.csv"
PRE_REGISTERED_CRITERIA_FILE = "decision_criteria.md"
PRE_REGISTERED_VERDICT_CONTINUE = "CONTINUE_DETECTOR_REFINEMENT"
PRE_REGISTERED_VERDICT_STOP = "STOP_ARCHIVE_DETECTOR"
PRE_REGISTERED_VERDICT_REPEAT = "REPEAT_EXPANSION_ONCE"
PRE_REGISTERED_VERDICT_INCONCLUSIVE = "INCONCLUSIVE"
PRE_REGISTERED_VERDICTS = (
    PRE_REGISTERED_VERDICT_CONTINUE,
    PRE_REGISTERED_VERDICT_STOP,
    PRE_REGISTERED_VERDICT_REPEAT,
    PRE_REGISTERED_VERDICT_INCONCLUSIVE,
)
SOURCE_MINIMUM_SAMPLE_SIZES = {
    SWEEP_EXTREME: 80,
    ROUND_LEVEL: 50,
    SWEPT_LIQUIDITY_LEVEL: 50,
}
KEY_DECISION_METRICS = ("fast_reaction", "fast_sl20", "runner")
ROBUST_CI_EXCLUDES_ZERO = "DIRECTIONAL_AND_CI95_EXCLUDES_ZERO"
ROBUST_CI_INCLUDES_ZERO = "DIRECTIONAL_NOT_STATISTICALLY_ROBUST_AT_CURRENT_N"
ROBUST_FLAT = "FLAT_OR_NO_DIRECTIONAL_EFFECT"
ROBUST_INELIGIBLE = "INELIGIBLE_UNDERPOWERED_SOURCE"


@dataclass(frozen=True)
class ObjectiveReplayConfig:
    symbol: str = "XAUUSD"
    data_dir: Path | str = Path("data")
    visual_pack_dir: Path | str = DEFAULT_VISUAL_PACK_DIR
    output_dir: Path | str = DEFAULT_OUTPUT_DIR
    forward_hours: float = 4.0
    direction_lookback_minutes: int = 30
    reaction_fast_minutes: int = 15
    reaction_slow_minutes: int = 30
    include_control_random: int = 800
    pip_size_override: float | None = None
    dry_run: bool = True
    round_level_threshold_pips: float = 5.0
    random_seed: int = 42
    control_match_entry_source: bool = True
    control_match_session: bool = True
    allow_unmatched_session_controls: bool = False
    control_max_attempts_per_row: int = 25
    sweep_control_lookback_minutes: int = 60
    sweep_control_min_anchor_delay_minutes: int = 5
    sweep_control_min_rejection_pips: float = 5.0


@dataclass(frozen=True)
class PipSizeResolution:
    pip_size: float
    source: str


@dataclass(frozen=True)
class DirectionInference:
    direction_guess: str
    direction_source_timeframe: str | None
    sweep_type: str | None
    swept_level: float | None
    sweep_timestamp: datetime | None
    direction_confidence: str
    direction_reason_codes: tuple[str, ...]
    sweep_extreme: float | None = None


@dataclass(frozen=True)
class EntryHypothesis:
    entry_hypothesis_type: str
    entry_price: float | None
    entry_level_source: str | None
    entry_is_heuristic: bool
    limitation: str | None = None
    entry_level_confidence: str = "UNKNOWN"
    entry_level_reason_codes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReplayInputSample:
    row_type: str
    sample_id: str
    symbol: str
    anchor_timestamp: datetime
    source_mode: str
    html_path: str | None = None
    chart_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ControlGenerationResult:
    samples: list[ReplayInputSample]
    limitations: list[str]
    stats: dict[str, Any]


def resolve_pip_size(symbol: str, override: float | None = None) -> PipSizeResolution:
    if override is not None:
        return PipSizeResolution(float(override), "cli_override")
    spec = get_symbol_spec(symbol)
    return PipSizeResolution(float(spec.pip_size), "core.symbols.get_symbol_spec")


def _to_path(value: Path | str) -> Path:
    return value if isinstance(value, Path) else Path(value)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        out = float(text)
    except ValueError:
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _read_csv_rows(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def _metadata_from_sample_html(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="ignore")
    out: dict[str, str] = {}
    for key, value in re.findall(r"<tr><th>(.*?)</th><td>(.*?)</td></tr>", text, flags=re.IGNORECASE | re.DOTALL):
        clean_key = html.unescape(re.sub(r"<.*?>", "", key)).strip()
        clean_value = html.unescape(re.sub(r"<.*?>", "", value)).strip()
        if clean_key:
            out[clean_key] = clean_value
    return out


def load_visual_review_samples(visual_pack_dir: Path | str, symbol: str) -> tuple[list[ReplayInputSample], list[dict[str, Any]], list[str]]:
    pack_dir = _to_path(visual_pack_dir)
    labels_path = pack_dir / "manual_labels_template.csv"
    if not labels_path.exists():
        return [], [], ["VISUAL_PACK_MANUAL_LABEL_TEMPLATE_MISSING"]
    rows, _ = _read_csv_rows(labels_path)
    samples: list[ReplayInputSample] = []
    limitations: list[str] = []
    for row in rows:
        anchor = _parse_dt(row.get("anchor_timestamp"))
        if anchor is None:
            limitations.append("VISUAL_SAMPLE_MISSING_ANCHOR_TIMESTAMP")
            continue
        html_path = str(row.get("html_path") or "")
        meta = dict(row)
        if html_path:
            meta.update(_metadata_from_sample_html(pack_dir / html_path))
        samples.append(
            ReplayInputSample(
                row_type="CANDIDATE",
                sample_id=str(row.get("sample_id") or f"candidate_{len(samples) + 1:03d}"),
                symbol=str(row.get("symbol") or symbol),
                anchor_timestamp=anchor,
                source_mode=str(row.get("source_mode") or "VISUAL_PACK"),
                html_path=html_path or None,
                chart_path=str(row.get("chart_path") or "") or None,
                metadata=meta,
            )
        )
    return samples, rows, limitations


def _slice_time(df: pd.DataFrame, start: datetime, end: datetime, *, inclusive_end: bool = True) -> pd.DataFrame:
    if df is None or df.empty or "time" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], utc=True, errors="coerce")
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if inclusive_end:
        out = out[(out["time"] >= start_ts) & (out["time"] <= end_ts)].copy()
    else:
        out = out[(out["time"] >= start_ts) & (out["time"] < end_ts)].copy()
    return out.sort_values("time").reset_index(drop=True)


def _slice_before(df: pd.DataFrame, start: datetime, anchor: datetime) -> pd.DataFrame:
    return _slice_time(df, start, anchor, inclusive_end=False)


def _nearest_candle_close(frames: Mapping[str, pd.DataFrame], anchor: datetime) -> float | None:
    for tf in ("M1", "M5", "M15", "H1"):
        df = frames.get(tf, pd.DataFrame())
        if df.empty:
            continue
        view = _slice_time(df, anchor - timedelta(minutes=30), anchor)
        if not view.empty:
            return _parse_float(view.iloc[-1].get("close"))
    return None


def _nearest_pre_anchor_close(frames: Mapping[str, pd.DataFrame], anchor: datetime) -> float | None:
    for tf in ("M1", "M5", "M15", "H1"):
        df = frames.get(tf, pd.DataFrame())
        if df.empty:
            continue
        view = _slice_before(df, anchor - timedelta(minutes=30), anchor)
        if not view.empty:
            return _parse_float(view.iloc[-1].get("close"))
    return None


def _nearest_round_level(price: float, step: float = 10.0) -> float:
    return math.floor(float(price) / step + 0.5) * step


def _round_level_distance_pips(symbol: str, price: float, level: float) -> float:
    return round(abs(price_to_pips(symbol, float(price) - float(level))), 4)


def _entry_direction_conflicts(
    *,
    entry_price: float,
    direction: DirectionInference,
    frames: Mapping[str, pd.DataFrame],
    anchor: datetime,
    pip_size: float,
) -> bool:
    anchor_price = _nearest_candle_close(frames, anchor)
    if anchor_price is None or direction.direction_guess not in {"LONG", "SHORT"}:
        return False
    tolerance = 5 * pip_size
    if direction.direction_guess == "LONG":
        return entry_price > anchor_price + tolerance
    return entry_price < anchor_price - tolerance


def _with_conflict_check(
    entry: EntryHypothesis,
    *,
    direction: DirectionInference,
    frames: Mapping[str, pd.DataFrame],
    anchor: datetime,
    pip_size: float,
    check_conflict: bool,
) -> EntryHypothesis:
    if not check_conflict or entry.entry_price is None:
        return entry
    if not _entry_direction_conflicts(
        entry_price=entry.entry_price,
        direction=direction,
        frames=frames,
        anchor=anchor,
        pip_size=pip_size,
    ):
        return entry
    return EntryHypothesis(
        entry_hypothesis_type=UNKNOWN_ENTRY_LEVEL,
        entry_price=None,
        entry_level_source=UNKNOWN_ENTRY_SOURCE,
        entry_is_heuristic=True,
        limitation=ENTRY_DIRECTION_CONFLICT,
        entry_level_confidence="UNKNOWN",
        entry_level_reason_codes=(*entry.entry_level_reason_codes, ENTRY_DIRECTION_CONFLICT),
    )


def _round_level_entry(
    sample: ReplayInputSample,
    frames: Mapping[str, pd.DataFrame],
    *,
    symbol: str,
    threshold_pips: float = 5.0,
) -> EntryHypothesis:
    explicit_level = _parse_float(
        sample.metadata.get("number_theory_level")
        or sample.metadata.get("round_level")
    )
    if explicit_level is not None:
        return EntryHypothesis(
            entry_hypothesis_type=ROUND_LEVEL_TOUCH_ENTRY,
            entry_price=round(float(explicit_level), 2),
            entry_level_source=ROUND_LEVEL,
            entry_is_heuristic=True,
            entry_level_confidence="HIGH",
            entry_level_reason_codes=("EXPLICIT_ROUND_LEVEL_METADATA",),
        )
    anchor_price = _nearest_candle_close(frames, sample.anchor_timestamp)
    if anchor_price is None:
        return EntryHypothesis(
            UNKNOWN_ENTRY_LEVEL,
            None,
            UNKNOWN_ENTRY_SOURCE,
            True,
            "ANCHOR_PRICE_UNAVAILABLE",
            "UNKNOWN",
            ("ANCHOR_PRICE_UNAVAILABLE",),
        )
    level = _nearest_round_level(anchor_price)
    distance = _round_level_distance_pips(symbol, anchor_price, level)
    if distance <= threshold_pips:
        return EntryHypothesis(
            entry_hypothesis_type=ROUND_LEVEL_TOUCH_ENTRY,
            entry_price=round(level, 2),
            entry_level_source=ROUND_LEVEL,
            entry_is_heuristic=True,
            entry_level_confidence="MEDIUM",
            entry_level_reason_codes=("ANCHOR_PRICE_NEAR_ROUND_LEVEL",),
        )
    return EntryHypothesis(
        UNKNOWN_ENTRY_LEVEL,
        None,
        UNKNOWN_ENTRY_SOURCE,
        True,
        "NO_ROUND_LEVEL_WITHIN_THRESHOLD",
        "UNKNOWN",
        ("NO_ROUND_LEVEL_WITHIN_THRESHOLD",),
    )


def build_round_level_entry(
    sample: ReplayInputSample,
    frames: Mapping[str, pd.DataFrame],
    *,
    symbol: str,
    threshold_pips: float = 5.0,
) -> EntryHypothesis:
    """Backward-compatible ROUND_LEVEL-only entry resolver."""
    return _round_level_entry(sample, frames, symbol=symbol, threshold_pips=threshold_pips)


def _sweep_entry_confidence(direction: DirectionInference) -> str:
    if direction.direction_source_timeframe == "M5" and direction.direction_confidence in {"HIGH", "MEDIUM"}:
        return "MEDIUM"
    if direction.direction_confidence in {"HIGH", "MEDIUM", "LOW"}:
        return "LOW"
    return "UNKNOWN"


def _explicit_entry_level_from_metadata(sample: ReplayInputSample) -> EntryHypothesis | None:
    explicit_source = str(
        sample.metadata.get("entry_level_source")
        or sample.metadata.get("candidate_source_type")
        or ""
    ).strip()
    explicit_price = _parse_float(
        sample.metadata.get("entry_level_price")
        or sample.metadata.get("entry_price")
        or sample.metadata.get("entry_level")
    )
    if explicit_price is None or explicit_source in {"", UNKNOWN_ENTRY_SOURCE}:
        return None
    if explicit_source not in {ROUND_LEVEL, SWEEP_EXTREME, SWEPT_LIQUIDITY_LEVEL}:
        return None
    confidence = str(sample.metadata.get("entry_level_confidence") or "").strip() or (
        "HIGH" if explicit_source == ROUND_LEVEL else "MEDIUM"
    )
    return EntryHypothesis(
        entry_hypothesis_type=ROUND_LEVEL_TOUCH_ENTRY,
        entry_price=round(float(explicit_price), 2),
        entry_level_source=explicit_source,
        entry_is_heuristic=True,
        entry_level_confidence=confidence,
        entry_level_reason_codes=(
            "EXPLICIT_ENTRY_LEVEL_METADATA_FROM_VISUAL_PACK",
            f"EXPLICIT_SOURCE_{explicit_source}",
        ),
    )


def build_entry_hypothesis(
    sample: ReplayInputSample,
    frames: Mapping[str, pd.DataFrame],
    direction: DirectionInference,
    *,
    symbol: str,
    threshold_pips: float = 5.0,
    pip_size: float = 0.1,
) -> EntryHypothesis:
    explicit_entry = _explicit_entry_level_from_metadata(sample)
    if explicit_entry is not None:
        return _with_conflict_check(
            explicit_entry,
            direction=direction,
            frames=frames,
            anchor=sample.anchor_timestamp,
            pip_size=pip_size,
            check_conflict=explicit_entry.entry_level_source != ROUND_LEVEL,
        )

    round_entry = _round_level_entry(sample, frames, symbol=symbol, threshold_pips=threshold_pips)
    if round_entry.entry_price is not None:
        return _with_conflict_check(
            round_entry,
            direction=direction,
            frames=frames,
            anchor=sample.anchor_timestamp,
            pip_size=pip_size,
            check_conflict=False,
        )

    if direction.direction_guess == UNKNOWN_DIRECTION:
        return EntryHypothesis(
            UNKNOWN_ENTRY_LEVEL,
            None,
            UNKNOWN_ENTRY_SOURCE,
            True,
            "DIRECTION_REQUIRED_FOR_SWEEP_ENTRY",
            "UNKNOWN",
            ("DIRECTION_REQUIRED_FOR_SWEEP_ENTRY",),
        )

    explicit_swept_level = _parse_float(
        sample.metadata.get("swept_liquidity_level")
        or sample.metadata.get("sweep_level")
        or sample.metadata.get("liquidity_level")
    )
    if explicit_swept_level is not None:
        return _with_conflict_check(
            EntryHypothesis(
                entry_hypothesis_type=ROUND_LEVEL_TOUCH_ENTRY,
                entry_price=round(float(explicit_swept_level), 2),
                entry_level_source=SWEPT_LIQUIDITY_LEVEL,
                entry_is_heuristic=True,
                entry_level_confidence="MEDIUM",
                entry_level_reason_codes=("EXPLICIT_SWEPT_LIQUIDITY_LEVEL_METADATA",),
            ),
            direction=direction,
            frames=frames,
            anchor=sample.anchor_timestamp,
            pip_size=pip_size,
            check_conflict=True,
        )

    if direction.sweep_extreme is not None:
        return EntryHypothesis(
            entry_hypothesis_type=ROUND_LEVEL_TOUCH_ENTRY,
            entry_price=round(float(direction.sweep_extreme), 2),
            entry_level_source=SWEEP_EXTREME,
            entry_is_heuristic=True,
            entry_level_confidence=_sweep_entry_confidence(direction),
            entry_level_reason_codes=(
                "DIRECTION_INFERRED_SWEEP_EXTREME_HEURISTIC",
                f"{direction.direction_source_timeframe or 'UNKNOWN'}_{direction.sweep_type or 'UNKNOWN_SWEEP'}",
            ),
        )

    if direction.swept_level is not None:
        return EntryHypothesis(
            entry_hypothesis_type=ROUND_LEVEL_TOUCH_ENTRY,
            entry_price=round(float(direction.swept_level), 2),
            entry_level_source=SWEPT_LIQUIDITY_LEVEL,
            entry_is_heuristic=True,
            entry_level_confidence="LOW",
            entry_level_reason_codes=("DIRECTION_INFERRED_SWEPT_LIQUIDITY_LEVEL_HEURISTIC",),
        )

    return EntryHypothesis(
        UNKNOWN_ENTRY_LEVEL,
        None,
        UNKNOWN_ENTRY_SOURCE,
        True,
        "NO_DEFENSIBLE_ENTRY_LEVEL",
        "UNKNOWN",
        ("NO_DEFENSIBLE_ENTRY_LEVEL",),
    )


def _sweep_confidence(penetration_pips: float, closed_back: bool) -> str:
    if closed_back and penetration_pips >= 10:
        return "HIGH"
    if closed_back or penetration_pips >= 5:
        return "MEDIUM"
    return "LOW"


def _infer_direction_from_frame(
    df: pd.DataFrame,
    *,
    anchor: datetime,
    lookback_minutes: int,
    pip_size: float,
    timeframe: str,
    include_anchor: bool = True,
) -> DirectionInference:
    window = _slice_time(df, anchor - timedelta(minutes=lookback_minutes), anchor, inclusive_end=include_anchor)
    if len(window) < 3:
        return DirectionInference(
            "UNKNOWN_DIRECTION",
            timeframe,
            None,
            None,
            None,
            "UNKNOWN",
            ("INSUFFICIENT_LOOKBACK_CANDLES",),
        )
    events: list[dict[str, Any]] = []
    for idx in range(1, len(window)):
        prior = window.iloc[:idx]
        current = window.iloc[idx]
        prior_high = float(prior["high"].max())
        prior_low = float(prior["low"].min())
        high = float(current["high"])
        low = float(current["low"])
        close = float(current["close"])
        when = pd.Timestamp(current["time"]).to_pydatetime()
        if high > prior_high:
            penetration_pips = (high - prior_high) / pip_size
            closed_back = close <= prior_high
            stalled_near = close <= prior_high + 5 * pip_size
            if closed_back or stalled_near:
                events.append(
                    {
                        "direction": "SHORT",
                        "sweep_type": "UPWARD_SWEEP",
                        "level": prior_high,
                        "sweep_extreme": high,
                        "timestamp": when,
                        "confidence": _sweep_confidence(penetration_pips, closed_back),
                        "penetration_pips": penetration_pips,
                        "reason": "RECENT_LOCAL_HIGH_TAKEN_AND_REJECTED_OR_STALLED",
                    }
                )
        if low < prior_low:
            penetration_pips = (prior_low - low) / pip_size
            closed_back = close >= prior_low
            stalled_near = close >= prior_low - 5 * pip_size
            if closed_back or stalled_near:
                events.append(
                    {
                        "direction": "LONG",
                        "sweep_type": "DOWNWARD_SWEEP",
                        "level": prior_low,
                        "sweep_extreme": low,
                        "timestamp": when,
                        "confidence": _sweep_confidence(penetration_pips, closed_back),
                        "penetration_pips": penetration_pips,
                        "reason": "RECENT_LOCAL_LOW_TAKEN_AND_REJECTED_OR_STALLED",
                    }
                )
    if not events:
        return DirectionInference("UNKNOWN_DIRECTION", timeframe, None, None, None, "UNKNOWN", ("NO_CLEAR_SWEEP_IN_LOOKBACK",))
    chosen = sorted(events, key=lambda item: (item["timestamp"], item["penetration_pips"]))[-1]
    return DirectionInference(
        direction_guess=str(chosen["direction"]),
        direction_source_timeframe=timeframe,
        sweep_type=str(chosen["sweep_type"]),
        swept_level=round(float(chosen["level"]), 2),
        sweep_timestamp=chosen["timestamp"],
        direction_confidence=str(chosen["confidence"]),
        direction_reason_codes=(str(chosen["reason"]),),
        sweep_extreme=round(float(chosen["sweep_extreme"]), 2),
    )


def infer_reversal_direction(
    frames: Mapping[str, pd.DataFrame],
    anchor: datetime,
    *,
    lookback_minutes: int = 30,
    pip_size: float = 0.1,
    include_anchor: bool = True,
) -> DirectionInference:
    for timeframe in ("M5", "M1"):
        inference = _infer_direction_from_frame(
            frames.get(timeframe, pd.DataFrame()),
            anchor=anchor,
            lookback_minutes=lookback_minutes,
            pip_size=pip_size,
            timeframe=timeframe,
            include_anchor=include_anchor,
        )
        if inference.direction_guess != "UNKNOWN_DIRECTION":
            return inference
    return DirectionInference("UNKNOWN_DIRECTION", None, None, None, None, "UNKNOWN", ("NO_CLEAR_M5_OR_M1_SWEEP",))


def _favorable_adverse(row: Any, direction: str, entry: float, pip_size: float) -> tuple[float, float]:
    high = float(getattr(row, "high"))
    low = float(getattr(row, "low"))
    if direction == "LONG":
        return max(0.0, (high - entry) / pip_size), max(0.0, (entry - low) / pip_size)
    if direction == "SHORT":
        return max(0.0, (entry - low) / pip_size), max(0.0, (high - entry) / pip_size)
    return 0.0, 0.0


def _reaction_at_checkpoint(path: pd.DataFrame, anchor: datetime, entry: float, direction: str, minutes: int, pip_size: float) -> float | None:
    checkpoint = anchor + timedelta(minutes=minutes)
    view = _slice_time(path, anchor, checkpoint)
    if view.empty:
        return None
    close = float(view.iloc[-1]["close"])
    if direction == "LONG":
        return round((close - entry) / pip_size, 4)
    if direction == "SHORT":
        return round((entry - close) / pip_size, 4)
    return None


def _first_time(mapping: Mapping[int, float | None], value: int) -> float | None:
    out = mapping.get(value)
    return None if out is None else float(out)


def _entry_cross_count(path: pd.DataFrame, anchor: datetime, entry: float) -> int:
    view = _slice_time(path, anchor, anchor + timedelta(minutes=60))
    signs: list[int] = []
    for close in view.get("close", []):
        value = float(close)
        if value > entry:
            signs.append(1)
        elif value < entry:
            signs.append(-1)
    return sum(1 for prev, cur in zip(signs, signs[1:]) if prev != cur)


def _returned_to_entry_after(path: pd.DataFrame, anchor: datetime, entry: float, direction: str, after_minutes: float | None) -> bool:
    if after_minutes is None:
        return False
    view = _slice_time(path, anchor + timedelta(minutes=after_minutes), anchor + timedelta(minutes=240))
    if view.empty:
        return False
    if direction == "LONG":
        return bool((view["low"].astype(float) <= entry).any())
    if direction == "SHORT":
        return bool((view["high"].astype(float) >= entry).any())
    return False


def _m5_followthrough_quality(frames: Mapping[str, pd.DataFrame], anchor: datetime, entry: float, direction: str, pip_size: float) -> str:
    m5 = _slice_time(frames.get("M5", pd.DataFrame()), anchor, anchor + timedelta(minutes=60))
    if m5.empty:
        return "UNKNOWN"
    max_fav = max((_favorable_adverse(row, direction, entry, pip_size)[0] for row in m5.itertuples(index=False)), default=0.0)
    crosses = _entry_cross_count(m5, anchor, entry)
    if max_fav >= 100:
        return "GOOD"
    if max_fav >= 50 and crosses < 3:
        return "MODERATE"
    if crosses >= 3:
        return "CHOP"
    return "POOR"


def replay_forward_path(
    sample: ReplayInputSample,
    frames: Mapping[str, pd.DataFrame],
    entry: EntryHypothesis,
    direction: DirectionInference,
    *,
    symbol: str,
    pip_size: float,
    forward_hours: float = 4.0,
    reaction_fast_minutes: int = 15,
    reaction_slow_minutes: int = 30,
) -> dict[str, Any]:
    anchor = sample.anchor_timestamp
    end = anchor + timedelta(hours=forward_hours)
    path = _slice_time(frames.get("M1", pd.DataFrame()), anchor, end)
    if path.empty:
        path = _slice_time(frames.get("M5", pd.DataFrame()), anchor, end)
    limitations: list[str] = []
    reason_codes: list[str] = list(entry.entry_level_reason_codes)
    secondary_flags: list[str] = []
    if entry.entry_price is None:
        limitations.append(entry.limitation or UNKNOWN_ENTRY_LEVEL)
        return _unknown_row(sample, entry, direction, symbol, pip_size, UNKNOWN_ENTRY_LEVEL, limitations)
    if direction.direction_guess == "UNKNOWN_DIRECTION":
        limitations.append("DIRECTION_NOT_INFERRED")
        return _unknown_row(sample, entry, direction, symbol, pip_size, UNKNOWN_DIRECTION, limitations)
    if path.empty:
        limitations.append("NO_FORWARD_M1_M5_CANDLES")
        return _unknown_row(sample, entry, direction, symbol, pip_size, UNKNOWN_INSUFFICIENT_FORWARD_DATA, limitations)
    last_time = pd.Timestamp(path.iloc[-1]["time"]).to_pydatetime()
    forward_minutes_available = (last_time - anchor).total_seconds() / 60.0
    if forward_minutes_available < min(60.0, forward_hours * 60.0):
        limitations.append("LESS_THAN_60_MINUTES_FORWARD_DATA")
        return _unknown_row(sample, entry, direction, symbol, pip_size, UNKNOWN_INSUFFICIENT_FORWARD_DATA, limitations)

    entry_price = float(entry.entry_price)
    reactions = {
        minutes: _reaction_at_checkpoint(path, anchor, entry_price, direction.direction_guess, minutes, pip_size)
        for minutes in CHECKPOINT_MINUTES
    }
    max_fav = 0.0
    max_adv = 0.0
    time_to_max_fav: float | None = None
    time_to_max_adv: float | None = None
    milestone_times: dict[int, float | None] = {level: None for level in MILESTONES}
    sl_times: dict[int, float | None] = {20: None, 40: None}
    for row in path.itertuples(index=False):
        when = pd.Timestamp(getattr(row, "time")).to_pydatetime()
        minutes = round((when - anchor).total_seconds() / 60.0, 4)
        fav, adv = _favorable_adverse(row, direction.direction_guess, entry_price, pip_size)
        if fav > max_fav:
            max_fav = fav
            time_to_max_fav = minutes
        if adv > max_adv:
            max_adv = adv
            time_to_max_adv = minutes
        for level in MILESTONES:
            if milestone_times[level] is None and fav >= level:
                milestone_times[level] = minutes
        for sl in (20, 40):
            if sl_times[sl] is None and adv >= sl:
                sl_times[sl] = minutes

    time_50 = _first_time(milestone_times, 50)
    time_100 = _first_time(milestone_times, 100)
    entry_cross_count = _entry_cross_count(path, anchor, entry_price)
    returned_to_entry = _returned_to_entry_after(path, anchor, entry_price, direction.direction_guess, time_100)
    first30 = _slice_time(path, anchor, anchor + timedelta(minutes=30))
    first30_range_pips = 0.0
    if not first30.empty:
        first30_range_pips = price_to_pips(symbol, float(first30["high"].max()) - float(first30["low"].min()))
    accumulation = bool((time_50 is None or time_50 > 30) and first30_range_pips <= 40)
    dirty_chop = bool(entry_cross_count >= 3)
    m5_quality = _m5_followthrough_quality(frames, anchor, entry_price, direction.direction_guess, pip_size)
    sl20_before_50 = sl_times[20] is not None and (time_50 is None or sl_times[20] <= time_50)
    sl40_before_50 = sl_times[40] is not None and (time_50 is None or sl_times[40] <= time_50)
    label = _classify_outcome(
        sl20_before_50=sl20_before_50,
        sl40_before_50=sl40_before_50,
        time_50=time_50,
        time_100=time_100,
        time_500=_first_time(milestone_times, 500),
        time_1000=_first_time(milestone_times, 1000),
        sl40_time=sl_times[40],
        accumulation=accumulation,
        dirty_chop=dirty_chop,
        returned_to_entry=returned_to_entry,
        reaction_fast_minutes=reaction_fast_minutes,
        reaction_slow_minutes=reaction_slow_minutes,
    )
    if accumulation:
        secondary_flags.append("ACCUMULATION_AFTER_ENTRY")
    if dirty_chop:
        secondary_flags.append("DIRTY_CHOP_AFTER_ENTRY")
    if returned_to_entry:
        secondary_flags.append("RETURNED_TO_ENTRY_AFTER_100_PIPS")
    if sl20_before_50:
        reason_codes.append("SL20_BEFORE_50P")
    if time_100 is not None and time_100 <= reaction_fast_minutes:
        reason_codes.append("FAST_100P_REACTION")
    elif time_100 is not None and time_100 >= reaction_slow_minutes:
        reason_codes.append("SLOW_100P_REACTION")

    return {
        **_base_row(sample, entry, direction, symbol, pip_size),
        "sl_20_price": _sl_price(entry_price, direction.direction_guess, 20, pip_size),
        "sl_40_price": _sl_price(entry_price, direction.direction_guess, 40, pip_size),
        "sl_20_hit": sl_times[20] is not None,
        "sl_40_hit": sl_times[40] is not None,
        "time_to_sl_20_minutes": sl_times[20],
        "time_to_sl_40_minutes": sl_times[40],
        "reaction_5m_pips": reactions[5],
        "reaction_15m_pips": reactions[15],
        "reaction_30m_pips": reactions[30],
        "reaction_60m_pips": reactions[60],
        "reaction_240m_pips": reactions[240],
        "time_to_50_pips_minutes": time_50,
        "time_to_100_pips_minutes": time_100,
        "time_to_250_pips_minutes": _first_time(milestone_times, 250),
        "time_to_500_pips_minutes": _first_time(milestone_times, 500),
        "time_to_1000_pips_minutes": _first_time(milestone_times, 1000),
        "fast_reaction_100pips_15m": time_100 is not None and time_100 <= reaction_fast_minutes,
        "slow_reaction_100pips_30m_plus": time_100 is not None and time_100 >= reaction_slow_minutes,
        "immediate_reaction_good": time_50 is not None and time_50 <= reaction_fast_minutes,
        "max_favorable_pips": round(max_fav, 4),
        "max_adverse_pips": round(max_adv, 4),
        "time_to_max_favorable_minutes": time_to_max_fav,
        "time_to_max_adverse_minutes": time_to_max_adv,
        "hit_50_pips": milestone_times[50] is not None,
        "hit_100_pips": milestone_times[100] is not None,
        "hit_250_pips": milestone_times[250] is not None,
        "hit_500_pips": milestone_times[500] is not None,
        "hit_1000_pips": milestone_times[1000] is not None,
        "be_possible_after_100_pips": time_100 is not None,
        "returned_to_entry_after_100_pips": returned_to_entry,
        "be_would_protect_after_100_pips": bool(time_100 is not None and returned_to_entry),
        "accumulation_after_entry": accumulation,
        "dirty_chop_after_entry": dirty_chop,
        "entry_cross_count_first_60m": entry_cross_count,
        "m5_followthrough_quality": m5_quality,
        "automatic_outcome_label": label,
        "secondary_outcome_flags": "|".join(secondary_flags),
        "reason_codes": "|".join(reason_codes),
        "limitations": "|".join(limitations),
    }


def _classify_outcome(
    *,
    sl20_before_50: bool,
    sl40_before_50: bool,
    time_50: float | None,
    time_100: float | None,
    time_500: float | None,
    time_1000: float | None,
    sl40_time: float | None,
    accumulation: bool,
    dirty_chop: bool,
    returned_to_entry: bool,
    reaction_fast_minutes: int,
    reaction_slow_minutes: int,
) -> str:
    if sl20_before_50:
        return FAST_SL_20
    if sl40_before_50:
        return FAST_SL_40
    if time_50 is None or time_50 > 60:
        return NO_REACTION
    if time_100 is not None and time_100 <= reaction_fast_minutes:
        return GOOD_FAST_REACTION
    if time_100 is not None and time_100 >= reaction_slow_minutes:
        return GOOD_SLOW_REACTION
    if (time_50 is not None or time_100 is not None) and (accumulation or dirty_chop):
        return GOOD_REACTION_BUT_DIRTY_ACCUMULATION
    if time_100 is not None and returned_to_entry:
        return MFE_GOOD_BUT_BE_REQUIRED
    if time_1000 is not None and (sl40_time is None or time_1000 < sl40_time):
        return STRONG_RUNNER
    if time_500 is not None and (sl40_time is None or time_500 < sl40_time):
        return RUNNER_CANDIDATE
    if time_100 is not None:
        return GOOD_SLOW_REACTION
    return GOOD_REACTION_BUT_DIRTY_ACCUMULATION


def _sl_price(entry: float, direction: str, sl_pips: int, pip_size: float) -> float | None:
    if direction == "LONG":
        return round(entry - sl_pips * pip_size, 2)
    if direction == "SHORT":
        return round(entry + sl_pips * pip_size, 2)
    return None


def _base_row(
    sample: ReplayInputSample,
    entry: EntryHypothesis,
    direction: DirectionInference,
    symbol: str,
    pip_size: float,
) -> dict[str, Any]:
    return {
        "row_type": sample.row_type,
        "sample_id": sample.sample_id,
        "symbol": symbol,
        "anchor_timestamp": sample.anchor_timestamp.isoformat(),
        "source_mode": sample.source_mode,
        "session": classify_session(sample.anchor_timestamp),
        "volatility_bucket": sample.metadata.get("volatility_bucket"),
        "daily_atr_at_anchor": sample.metadata.get("daily_atr_at_anchor"),
        "direction_guess": direction.direction_guess,
        "direction_confidence": direction.direction_confidence,
        "direction_source_timeframe": direction.direction_source_timeframe,
        "sweep_type": direction.sweep_type,
        "swept_level": direction.swept_level,
        "sweep_extreme": direction.sweep_extreme,
        "sweep_timestamp": direction.sweep_timestamp.isoformat() if direction.sweep_timestamp else None,
        "direction_reason_codes": "|".join(direction.direction_reason_codes),
        "entry_hypothesis_type": entry.entry_hypothesis_type,
        "entry_price": entry.entry_price,
        "entry_level_source": entry.entry_level_source,
        "entry_level_confidence": entry.entry_level_confidence,
        "entry_level_reason_codes": "|".join(entry.entry_level_reason_codes),
        "entry_is_heuristic": entry.entry_is_heuristic,
        "entry_level_is_heuristic": entry.entry_is_heuristic,
        "entry_direction_conflict": ENTRY_DIRECTION_CONFLICT in entry.entry_level_reason_codes,
        "pip_size": pip_size,
        "matched_control_for_entry_source": sample.metadata.get("matched_control_for_entry_source"),
        "matched_control_for_session": sample.metadata.get("matched_control_for_session"),
        "control_generation_method": sample.metadata.get("control_generation_method"),
        "control_random_seed": sample.metadata.get("control_random_seed"),
        "control_lookahead_safe": sample.metadata.get("control_lookahead_safe"),
        "sweep_control_lookback_minutes": sample.metadata.get("sweep_control_lookback_minutes"),
        "sweep_control_anchor_delay_minutes": sample.metadata.get("sweep_control_anchor_delay_minutes"),
        "control_skip_reason": sample.metadata.get("control_skip_reason"),
        "visual_html_path": sample.html_path,
    }


def _unknown_row(
    sample: ReplayInputSample,
    entry: EntryHypothesis,
    direction: DirectionInference,
    symbol: str,
    pip_size: float,
    label: str,
    limitations: Sequence[str],
) -> dict[str, Any]:
    row = {
        **_base_row(sample, entry, direction, symbol, pip_size),
        "sl_20_price": None,
        "sl_40_price": None,
        "sl_20_hit": False,
        "sl_40_hit": False,
        "time_to_sl_20_minutes": None,
        "time_to_sl_40_minutes": None,
        "reaction_5m_pips": None,
        "reaction_15m_pips": None,
        "reaction_30m_pips": None,
        "reaction_60m_pips": None,
        "reaction_240m_pips": None,
        "time_to_50_pips_minutes": None,
        "time_to_100_pips_minutes": None,
        "time_to_250_pips_minutes": None,
        "time_to_500_pips_minutes": None,
        "time_to_1000_pips_minutes": None,
        "fast_reaction_100pips_15m": False,
        "slow_reaction_100pips_30m_plus": False,
        "immediate_reaction_good": False,
        "max_favorable_pips": None,
        "max_adverse_pips": None,
        "time_to_max_favorable_minutes": None,
        "time_to_max_adverse_minutes": None,
        "hit_50_pips": False,
        "hit_100_pips": False,
        "hit_250_pips": False,
        "hit_500_pips": False,
        "hit_1000_pips": False,
        "be_possible_after_100_pips": False,
        "returned_to_entry_after_100_pips": False,
        "be_would_protect_after_100_pips": False,
        "accumulation_after_entry": False,
        "dirty_chop_after_entry": False,
        "entry_cross_count_first_60m": None,
        "m5_followthrough_quality": "UNKNOWN",
        "automatic_outcome_label": label,
        "secondary_outcome_flags": "",
        "reason_codes": "|".join([label, *entry.entry_level_reason_codes]),
        "limitations": "|".join(limitations),
    }
    return row


def classify_session(ts: datetime) -> str:
    try:
        local = ts.astimezone(ZoneInfo("Europe/Rome"))
    except Exception:
        local = ts
    minutes = local.hour * 60 + local.minute
    if 105 <= minutes <= 135:
        return "ASIA_OPEN"
    if 525 <= minutes <= 555:
        return "LONDON_OPEN"
    if 915 <= minutes <= 945:
        return "NEW_YORK_OPEN"
    if 0 <= minutes < 420:
        return "ASIA"
    if 420 <= minutes < 780:
        return "LONDON"
    if 780 <= minutes < 1080:
        return "NEW_YORK"
    return "OTHER"


def _control_direction_from_metadata(sample: ReplayInputSample) -> DirectionInference | None:
    if sample.row_type != "CONTROL":
        return None
    direction = str(sample.metadata.get("control_direction_guess") or "").strip()
    if not direction:
        return None
    sweep_timestamp = _parse_dt(sample.metadata.get("control_sweep_timestamp"))
    return DirectionInference(
        direction_guess=direction,
        direction_source_timeframe=str(sample.metadata.get("control_direction_source_timeframe") or ""),
        sweep_type=str(sample.metadata.get("control_sweep_type") or "") or None,
        swept_level=_parse_float(sample.metadata.get("control_swept_level")),
        sweep_timestamp=sweep_timestamp,
        direction_confidence=str(sample.metadata.get("control_direction_confidence") or "UNKNOWN"),
        direction_reason_codes=tuple(
            item for item in str(sample.metadata.get("control_direction_reason_codes") or "").split("|") if item
        )
        or ("CONTROL_PRE_ANCHOR_DIRECTION_METADATA",),
        sweep_extreme=_parse_float(sample.metadata.get("control_sweep_extreme")),
    )


def _control_entry_from_metadata(sample: ReplayInputSample) -> EntryHypothesis | None:
    if sample.row_type != "CONTROL":
        return None
    entry_price = _parse_float(sample.metadata.get("control_entry_price"))
    entry_source = str(sample.metadata.get("control_entry_level_source") or "").strip()
    if entry_price is None or not entry_source:
        return None
    return EntryHypothesis(
        entry_hypothesis_type=ROUND_LEVEL_TOUCH_ENTRY,
        entry_price=round(entry_price, 2),
        entry_level_source=entry_source,
        entry_is_heuristic=str(sample.metadata.get("control_entry_level_is_heuristic") or "true").lower() != "false",
        entry_level_confidence=str(sample.metadata.get("control_entry_level_confidence") or "UNKNOWN"),
        entry_level_reason_codes=tuple(
            item for item in str(sample.metadata.get("control_entry_level_reason_codes") or "").split("|") if item
        )
        or ("CONTROL_PRE_ANCHOR_ENTRY_METADATA",),
    )


def _coverage_ok(frames: Mapping[str, pd.DataFrame], anchor: datetime, forward_hours: float) -> bool:
    context = not _slice_time(frames.get("M15", pd.DataFrame()), anchor - timedelta(minutes=90), anchor + timedelta(minutes=180)).empty
    context = context or not _slice_time(frames.get("H1", pd.DataFrame()), anchor - timedelta(hours=3), anchor + timedelta(hours=1)).empty
    if not context:
        return False
    m5 = _slice_time(frames.get("M5", pd.DataFrame()), anchor - timedelta(minutes=90), anchor + timedelta(minutes=180))
    m1 = _slice_time(frames.get("M1", pd.DataFrame()), anchor - timedelta(minutes=90), anchor + timedelta(minutes=180))
    if m5.empty or m1.empty:
        return False
    forward = _slice_time(frames.get("M1", pd.DataFrame()), anchor, anchor + timedelta(hours=forward_hours))
    if forward.empty:
        return False
    return (pd.Timestamp(forward.iloc[-1]["time"]).to_pydatetime() - anchor).total_seconds() >= 60 * 60


def detect_pre_anchor_sweep_control(
    frames: Mapping[str, pd.DataFrame],
    anchor: datetime,
    *,
    lookback_minutes: int = 60,
    min_anchor_delay_minutes: int = 5,
    min_rejection_pips: float = 5.0,
    pip_size: float = 0.1,
) -> tuple[DirectionInference, EntryHypothesis] | None:
    """Detect a sweep using only candles before the control anchor.

    The anchor candle and all post-anchor candles are intentionally excluded.
    """
    min_rejection_price = min_rejection_pips * pip_size
    latest_allowed_sweep = anchor - timedelta(minutes=min_anchor_delay_minutes)
    events: list[dict[str, Any]] = []
    for timeframe in ("M5", "M1"):
        window = _slice_before(frames.get(timeframe, pd.DataFrame()), anchor - timedelta(minutes=lookback_minutes), anchor)
        if len(window) < 4:
            continue
        for idx in range(1, len(window)):
            current = window.iloc[idx]
            when = pd.Timestamp(current["time"]).to_pydatetime()
            if when > latest_allowed_sweep:
                continue
            prior = window.iloc[:idx]
            subsequent = window.iloc[idx + 1 :]
            prior_high = float(prior["high"].max())
            prior_low = float(prior["low"].min())
            high = float(current["high"])
            low = float(current["low"])
            close = float(current["close"])
            if high > prior_high:
                penetration_pips = (high - prior_high) / pip_size
                closed_back = close <= prior_high or (not subsequent.empty and (subsequent["close"].astype(float) <= prior_high).any())
                moved_away = not subsequent.empty and (subsequent["low"].astype(float) <= high - min_rejection_price).any()
                if closed_back or moved_away:
                    events.append(
                        {
                            "direction": "SHORT",
                            "sweep_type": "UPWARD_SWEEP",
                            "swept_level": prior_high,
                            "sweep_extreme": high,
                            "timestamp": when,
                            "timeframe": timeframe,
                            "confidence": _sweep_confidence(penetration_pips, bool(closed_back)),
                            "penetration_pips": penetration_pips,
                            "reason": "PRE_ANCHOR_UPWARD_SWEEP_REJECTED_OR_MOVED_AWAY",
                        }
                    )
            if low < prior_low:
                penetration_pips = (prior_low - low) / pip_size
                closed_back = close >= prior_low or (not subsequent.empty and (subsequent["close"].astype(float) >= prior_low).any())
                moved_away = not subsequent.empty and (subsequent["high"].astype(float) >= low + min_rejection_price).any()
                if closed_back or moved_away:
                    events.append(
                        {
                            "direction": "LONG",
                            "sweep_type": "DOWNWARD_SWEEP",
                            "swept_level": prior_low,
                            "sweep_extreme": low,
                            "timestamp": when,
                            "timeframe": timeframe,
                            "confidence": _sweep_confidence(penetration_pips, bool(closed_back)),
                            "penetration_pips": penetration_pips,
                            "reason": "PRE_ANCHOR_DOWNWARD_SWEEP_REJECTED_OR_MOVED_AWAY",
                        }
                    )
    if not events:
        return None
    chosen = sorted(events, key=lambda item: (item["timestamp"], item["penetration_pips"]))[-1]
    direction = DirectionInference(
        direction_guess=str(chosen["direction"]),
        direction_source_timeframe=str(chosen["timeframe"]),
        sweep_type=str(chosen["sweep_type"]),
        swept_level=round(float(chosen["swept_level"]), 2),
        sweep_timestamp=chosen["timestamp"],
        direction_confidence=str(chosen["confidence"]),
        direction_reason_codes=(
            str(chosen["reason"]),
            "CONTROL_SWEEP_USED_PRE_ANCHOR_CANDLES_ONLY",
            "ANCHOR_CANDLE_EXCLUDED",
            "POST_ANCHOR_CANDLES_EXCLUDED",
        ),
        sweep_extreme=round(float(chosen["sweep_extreme"]), 2),
    )
    entry = EntryHypothesis(
        entry_hypothesis_type=ROUND_LEVEL_TOUCH_ENTRY,
        entry_price=round(float(chosen["sweep_extreme"]), 2),
        entry_level_source=SWEEP_EXTREME,
        entry_is_heuristic=True,
        entry_level_confidence=_sweep_entry_confidence(direction),
        entry_level_reason_codes=(
            "PRE_ANCHOR_SWEEP_EXTREME_CONTROL",
            "CONTROL_ENTRY_USED_PRE_ANCHOR_CANDLES_ONLY",
        ),
    )
    return direction, entry


def _increment_counter(counter: dict[str, int], key: str, amount: int = 1) -> None:
    counter[key] = counter.get(key, 0) + amount


def _source_session_key(source: str, session: str) -> str:
    return f"{source}|{session}"


def _session_distribution(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        session = str(row.get("session") or classify_session(_parse_dt(row.get("anchor_timestamp")) or _utc_now()))
        _increment_counter(out, session)
    return dict(sorted(out.items()))


def _candidate_control_targets(
    candidate_rows: Sequence[Mapping[str, Any]],
    *,
    requested: int,
    match_entry_source: bool,
    match_session: bool,
) -> tuple[dict[tuple[str, str], int], dict[str, int], list[str]]:
    supported_sources = {ROUND_LEVEL, SWEEP_EXTREME}
    group_counts: dict[tuple[str, str], int] = {}
    unsupported_counts: dict[str, int] = {}
    limitations: list[str] = []
    for row in candidate_rows:
        source = str(row.get("entry_level_source") or UNKNOWN_ENTRY_SOURCE)
        if source == UNKNOWN_ENTRY_SOURCE:
            continue
        if source not in supported_sources:
            _increment_counter(unsupported_counts, source)
            continue
        session = str(row.get("session") or "UNKNOWN") if match_session else "ANY"
        source_key = source if match_entry_source else ROUND_LEVEL
        group_counts[(source_key, session)] = group_counts.get((source_key, session), 0) + 1
    for source, count in unsupported_counts.items():
        limitations.append(f"CONTROL_SOURCE_UNSUPPORTED_{source}_CANDIDATES_{count}")
    if not group_counts or requested <= 0:
        return {}, unsupported_counts, limitations
    total = sum(group_counts.values())
    raw: list[tuple[tuple[str, str], float]] = [(key, requested * count / total) for key, count in group_counts.items()]
    quotas = {key: max(1, int(value)) for key, value in raw}
    while sum(quotas.values()) > requested:
        key = max(quotas, key=lambda item: quotas[item])
        if quotas[key] <= 1:
            break
        quotas[key] -= 1
    while sum(quotas.values()) < requested:
        key = max(raw, key=lambda item: item[1] - int(item[1]))[0]
        quotas[key] += 1
    return quotas, unsupported_counts, limitations


def _control_metadata_common(
    *,
    source: str,
    target_session: str,
    actual_session: str,
    method: str,
    seed: int,
    lookahead_safe: bool,
    cfg: ObjectiveReplayConfig,
) -> dict[str, Any]:
    return {
        "matched_control_for_entry_source": True,
        "matched_control_for_session": target_session == actual_session,
        "control_generation_method": method,
        "control_random_seed": seed,
        "control_lookahead_safe": lookahead_safe,
        "sweep_control_lookback_minutes": cfg.sweep_control_lookback_minutes if source == SWEEP_EXTREME else "",
        "sweep_control_anchor_delay_minutes": cfg.sweep_control_min_anchor_delay_minutes if source == SWEEP_EXTREME else "",
        "control_target_entry_source": source,
        "control_target_session": target_session,
    }


def _metadata_from_direction(direction: DirectionInference) -> dict[str, Any]:
    return {
        "control_direction_guess": direction.direction_guess,
        "control_direction_source_timeframe": direction.direction_source_timeframe or "",
        "control_sweep_type": direction.sweep_type or "",
        "control_swept_level": direction.swept_level if direction.swept_level is not None else "",
        "control_sweep_extreme": direction.sweep_extreme if direction.sweep_extreme is not None else "",
        "control_sweep_timestamp": direction.sweep_timestamp.isoformat() if direction.sweep_timestamp else "",
        "control_direction_confidence": direction.direction_confidence,
        "control_direction_reason_codes": "|".join(direction.direction_reason_codes),
    }


def _metadata_from_entry(entry: EntryHypothesis) -> dict[str, Any]:
    return {
        "control_entry_price": entry.entry_price if entry.entry_price is not None else "",
        "control_entry_level_source": entry.entry_level_source or "",
        "control_entry_level_confidence": entry.entry_level_confidence,
        "control_entry_level_reason_codes": "|".join(entry.entry_level_reason_codes),
        "control_entry_level_is_heuristic": entry.entry_is_heuristic,
    }


def generate_control_samples(
    candidate_samples: Sequence[ReplayInputSample],
    frames: Mapping[str, pd.DataFrame],
    *,
    symbol: str,
    requested: int = 800,
    forward_hours: float = 4.0,
    threshold_pips: float = 5.0,
    seed: int = 42,
    candidate_rows: Sequence[Mapping[str, Any]] | None = None,
    pip_size: float = 0.1,
    cfg: ObjectiveReplayConfig | None = None,
) -> ControlGenerationResult:
    cfg = cfg or ObjectiveReplayConfig(symbol=symbol, include_control_random=requested, random_seed=seed)
    stats: dict[str, Any] = {
        "attempts_by_source": {},
        "success_by_source": {},
        "attempts_by_source_and_session": {},
        "success_by_source_and_session": {},
        "skip_reasons": {},
        "quota_by_source_and_session": {},
        "unmatched_session_controls_allowed": bool(cfg.allow_unmatched_session_controls),
    }
    if requested <= 0:
        return ControlGenerationResult([], [], stats)
    m15 = frames.get("M15", pd.DataFrame())
    if m15 is None or m15.empty or not candidate_samples:
        return ControlGenerationResult([], ["CONTROL_GROUP_INPUTS_MISSING"], stats)
    candidate_anchors = [sample.anchor_timestamp for sample in candidate_samples]
    min_anchor = min(candidate_anchors)
    max_anchor = max(candidate_anchors)
    rows = _slice_time(frames.get("M1", pd.DataFrame()), min_anchor, max_anchor)
    if rows.empty:
        rows = _slice_time(frames.get("M5", pd.DataFrame()), min_anchor, max_anchor)
    if rows.empty:
        return ControlGenerationResult([], ["CONTROL_DATE_RANGE_EMPTY"], stats)
    if candidate_rows is None:
        candidate_rows = [
            {
                "entry_level_source": ROUND_LEVEL,
                "session": classify_session(sample.anchor_timestamp),
                "anchor_timestamp": sample.anchor_timestamp.isoformat(),
            }
            for sample in candidate_samples
        ]
    quotas, _, quota_limitations = _candidate_control_targets(
        candidate_rows,
        requested=requested,
        match_entry_source=cfg.control_match_entry_source,
        match_session=cfg.control_match_session,
    )
    stats["quota_by_source_and_session"] = {_source_session_key(source, session): quota for (source, session), quota in sorted(quotas.items())}
    limitations = list(quota_limitations)
    if not quotas:
        limitations.append("CONTROL_GROUP_NO_SUPPORTED_ENTRY_SOURCE_TARGETS")
        return ControlGenerationResult([], limitations, stats)
    rng = random.Random(seed)
    anchor_times = [pd.Timestamp(row.time).to_pydatetime() for row in rows.itertuples(index=False)]
    candidate_anchor_set = {pd.Timestamp(anchor).isoformat() for anchor in candidate_anchors}
    selected: list[ReplayInputSample] = []
    used: set[tuple[str, str]] = set()

    for (source, target_session), quota in sorted(quotas.items()):
        attempts = 0
        successes = 0
        max_attempts = max(quota, quota * max(1, cfg.control_max_attempts_per_row))
        while successes < quota and attempts < max_attempts and anchor_times:
            attempts += 1
            _increment_counter(stats["attempts_by_source"], source)
            _increment_counter(stats["attempts_by_source_and_session"], _source_session_key(source, target_session))
            anchor = rng.choice(anchor_times)
            anchor_key = pd.Timestamp(anchor).isoformat()
            actual_session = classify_session(anchor)
            if anchor_key in candidate_anchor_set or (source, anchor_key) in used:
                _increment_counter(stats["skip_reasons"], "CONTROL_ANCHOR_OVERLAPS_CANDIDATE_OR_DUPLICATE")
                continue
            if cfg.control_match_session and actual_session != target_session and not cfg.allow_unmatched_session_controls:
                _increment_counter(stats["skip_reasons"], "SESSION_MISMATCH")
                continue
            if not _coverage_ok(frames, anchor, forward_hours):
                _increment_counter(stats["skip_reasons"], "MISSING_EXECUTION_COVERAGE")
                continue

            direction: DirectionInference
            entry: EntryHypothesis
            method: str
            if source == ROUND_LEVEL:
                pre_anchor_price = _nearest_pre_anchor_close(frames, anchor)
                if pre_anchor_price is None:
                    _increment_counter(stats["skip_reasons"], "ROUND_LEVEL_PRE_ANCHOR_PRICE_MISSING")
                    continue
                level = _nearest_round_level(pre_anchor_price)
                if _round_level_distance_pips(symbol, pre_anchor_price, level) > threshold_pips:
                    _increment_counter(stats["skip_reasons"], "ROUND_LEVEL_NOT_NEAR_PRE_ANCHOR_PRICE")
                    continue
                direction = infer_reversal_direction(
                    frames,
                    anchor,
                    lookback_minutes=cfg.direction_lookback_minutes,
                    pip_size=pip_size,
                    include_anchor=False,
                )
                entry = EntryHypothesis(
                    entry_hypothesis_type=ROUND_LEVEL_TOUCH_ENTRY,
                    entry_price=round(level, 2),
                    entry_level_source=ROUND_LEVEL,
                    entry_is_heuristic=True,
                    entry_level_confidence="MEDIUM",
                    entry_level_reason_codes=("CONTROL_PRE_ANCHOR_ROUND_LEVEL",),
                )
                method = "ROUND_LEVEL_PRE_ANCHOR_RANDOM"
            elif source == SWEEP_EXTREME:
                detected = detect_pre_anchor_sweep_control(
                    frames,
                    anchor,
                    lookback_minutes=cfg.sweep_control_lookback_minutes,
                    min_anchor_delay_minutes=cfg.sweep_control_min_anchor_delay_minutes,
                    min_rejection_pips=cfg.sweep_control_min_rejection_pips,
                    pip_size=pip_size,
                )
                if detected is None:
                    _increment_counter(stats["skip_reasons"], "SWEEP_EXTREME_NOT_DETECTED_PRE_ANCHOR")
                    continue
                direction, entry = detected
                method = "SWEEP_EXTREME_PRE_ANCHOR_RANDOM"
            else:
                _increment_counter(stats["skip_reasons"], f"UNSUPPORTED_CONTROL_SOURCE_{source}")
                break

            metadata = {
                **_control_metadata_common(
                    source=source,
                    target_session=target_session,
                    actual_session=actual_session,
                    method=method,
                    seed=seed,
                    lookahead_safe=True,
                    cfg=cfg,
                ),
                **_metadata_from_direction(direction),
                **_metadata_from_entry(entry),
                "candidate_reason_codes": f"{method}|ENTRY_SOURCE_SESSION_MATCHED_CONTROL",
                "control_skip_reason": "",
            }
            if source == ROUND_LEVEL and entry.entry_price is not None:
                metadata["number_theory_level"] = str(entry.entry_price)
            selected.append(
                ReplayInputSample(
                    row_type="CONTROL",
                    sample_id=f"control_{len(selected) + 1:04d}",
                    symbol=symbol,
                    anchor_timestamp=anchor,
                    source_mode="ENTRY_SOURCE_SESSION_MATCHED_CONTROL",
                    metadata=metadata,
                )
            )
            used.add((source, anchor_key))
            successes += 1
            _increment_counter(stats["success_by_source"], source)
            _increment_counter(stats["success_by_source_and_session"], _source_session_key(source, target_session))
        if successes < quota:
            limitations.append(f"CONTROL_GROUP_NOT_FILLED_{source}_{target_session}_{successes}_OF_{quota}")

    if len(selected) < requested:
        limitations.append("CONTROL_GROUP_NOT_FILLED")
    total_attempts = sum(stats["attempts_by_source"].values())
    total_success = len(selected)
    stats["session_match_success_rate"] = round(total_success / total_attempts, 4) if total_attempts else 0.0
    return ControlGenerationResult(selected, limitations, stats)


OUTPUT_FIELDS = [
    "row_type",
    "sample_id",
    "symbol",
    "anchor_timestamp",
    "source_mode",
    "session",
    "volatility_bucket",
    "daily_atr_at_anchor",
    "direction_guess",
    "direction_confidence",
    "direction_source_timeframe",
    "sweep_type",
    "swept_level",
    "sweep_extreme",
    "sweep_timestamp",
    "direction_reason_codes",
    "entry_hypothesis_type",
    "entry_price",
    "entry_level_source",
    "entry_level_confidence",
    "entry_level_reason_codes",
    "entry_is_heuristic",
    "entry_level_is_heuristic",
    "entry_direction_conflict",
    "pip_size",
    "matched_control_for_entry_source",
    "matched_control_for_session",
    "control_generation_method",
    "control_random_seed",
    "control_lookahead_safe",
    "sweep_control_lookback_minutes",
    "sweep_control_anchor_delay_minutes",
    "control_skip_reason",
    "sl_20_price",
    "sl_40_price",
    "sl_20_hit",
    "sl_40_hit",
    "time_to_sl_20_minutes",
    "time_to_sl_40_minutes",
    "reaction_5m_pips",
    "reaction_15m_pips",
    "reaction_30m_pips",
    "reaction_60m_pips",
    "reaction_240m_pips",
    "time_to_50_pips_minutes",
    "time_to_100_pips_minutes",
    "time_to_250_pips_minutes",
    "time_to_500_pips_minutes",
    "time_to_1000_pips_minutes",
    "fast_reaction_100pips_15m",
    "slow_reaction_100pips_30m_plus",
    "immediate_reaction_good",
    "max_favorable_pips",
    "max_adverse_pips",
    "time_to_max_favorable_minutes",
    "time_to_max_adverse_minutes",
    "hit_50_pips",
    "hit_100_pips",
    "hit_250_pips",
    "hit_500_pips",
    "hit_1000_pips",
    "be_possible_after_100_pips",
    "returned_to_entry_after_100_pips",
    "be_would_protect_after_100_pips",
    "accumulation_after_entry",
    "dirty_chop_after_entry",
    "entry_cross_count_first_60m",
    "m5_followthrough_quality",
    "automatic_outcome_label",
    "secondary_outcome_flags",
    "reason_codes",
    "limitations",
    "visual_html_path",
]


def _counts(rows: Sequence[Mapping[str, Any]], row_type: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        if row.get("row_type") != row_type:
            continue
        label = str(row.get("automatic_outcome_label") or "UNKNOWN")
        out[label] = out.get(label, 0) + 1
    return dict(sorted(out.items()))


def _rate(rows: Sequence[Mapping[str, Any]], row_type: str, predicate: Any) -> float:
    subset = [row for row in rows if row.get("row_type") == row_type]
    if not subset:
        return 0.0
    return round(sum(1 for row in subset if predicate(row)) / len(subset), 4)


def _is_known_entry(row: Mapping[str, Any]) -> bool:
    return _parse_float(row.get("entry_price")) is not None and str(row.get("entry_level_source") or UNKNOWN_ENTRY_SOURCE) != UNKNOWN_ENTRY_SOURCE


def _source_counts(rows: Sequence[Mapping[str, Any]], row_type: str | None = None) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        if row_type is not None and row.get("row_type") != row_type:
            continue
        source = str(row.get("entry_level_source") or UNKNOWN_ENTRY_SOURCE)
        out[source] = out.get(source, 0) + 1
    return dict(sorted(out.items()))


def _value_distribution(rows: Sequence[Mapping[str, Any]], field: str, row_type: str | None = None) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        if row_type is not None and row.get("row_type") != row_type:
            continue
        value = str(row.get(field) or "UNKNOWN")
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def _outcome_counts_by_source(rows: Sequence[Mapping[str, Any]], row_type: str) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        if row.get("row_type") != row_type:
            continue
        source = str(row.get("entry_level_source") or UNKNOWN_ENTRY_SOURCE)
        label = str(row.get("automatic_outcome_label") or "UNKNOWN")
        out.setdefault(source, {})
        out[source][label] = out[source].get(label, 0) + 1
    return {source: dict(sorted(counts.items())) for source, counts in sorted(out.items())}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _metric_success(row: Mapping[str, Any], metric: str) -> bool:
    if metric == "fast_reaction":
        return _truthy(row.get("fast_reaction_100pips_15m"))
    if metric == "fast_sl20":
        return row.get("automatic_outcome_label") == FAST_SL_20
    if metric == "runner":
        return row.get("automatic_outcome_label") in {RUNNER_CANDIDATE, STRONG_RUNNER} or _truthy(row.get("hit_500_pips"))
    raise ValueError(f"Unsupported metric: {metric}")


def normal_proportion_ci95(successes: int, n: int) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 0.0
    p = successes / n
    se = math.sqrt(max(p * (1.0 - p), 0.0) / n)
    lower = max(0.0, p - 1.96 * se)
    upper = min(1.0, p + 1.96 * se)
    return round(lower, 6), round(upper, 6)


def effect_size_ci95(candidate_rate: float, candidate_n: int, control_rate: float, control_n: int) -> tuple[float, float]:
    if candidate_n <= 0 or control_n <= 0:
        return 0.0, 0.0
    cand_se = math.sqrt(max(candidate_rate * (1.0 - candidate_rate), 0.0) / candidate_n)
    ctrl_se = math.sqrt(max(control_rate * (1.0 - control_rate), 0.0) / control_n)
    effect = candidate_rate - control_rate
    se = math.sqrt(cand_se * cand_se + ctrl_se * ctrl_se)
    return round(effect - 1.96 * se, 6), round(effect + 1.96 * se, 6)


def _effect_excludes_zero(lower: float, upper: float) -> bool:
    return (lower > 0 and upper > 0) or (lower < 0 and upper < 0)


def _robustness_label(*, eligible: bool, effect: float, lower: float, upper: float) -> str:
    if not eligible:
        return ROBUST_INELIGIBLE
    if abs(effect) < 0.01:
        return ROBUST_FLAT
    if _effect_excludes_zero(lower, upper):
        return ROBUST_CI_EXCLUDES_ZERO
    return ROBUST_CI_INCLUDES_ZERO


def build_source_metrics_with_confidence(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    present_sources = {
        str(row.get("entry_level_source") or UNKNOWN_ENTRY_SOURCE)
        for row in rows
        if str(row.get("entry_level_source") or UNKNOWN_ENTRY_SOURCE) != UNKNOWN_ENTRY_SOURCE
    }
    ordered_sources = [source for source in (ROUND_LEVEL, SWEEP_EXTREME, SWEPT_LIQUIDITY_LEVEL) if source in present_sources or source in SOURCE_MINIMUM_SAMPLE_SIZES]
    out: dict[str, Any] = {}
    for source in ordered_sources:
        candidate_rows = [
            row for row in rows if row.get("row_type") == "CANDIDATE" and str(row.get("entry_level_source") or UNKNOWN_ENTRY_SOURCE) == source
        ]
        control_rows = [
            row for row in rows if row.get("row_type") == "CONTROL" and str(row.get("entry_level_source") or UNKNOWN_ENTRY_SOURCE) == source
        ]
        candidate_n = len(candidate_rows)
        control_n = len(control_rows)
        min_n = SOURCE_MINIMUM_SAMPLE_SIZES.get(source)
        eligible = min_n is not None and candidate_n >= min_n and control_n > 0
        metrics: dict[str, Any] = {
            "candidate_n": candidate_n,
            "control_n": control_n,
            "required_candidate_min_n": min_n,
            "eligible_for_pre_registered_verdict": eligible,
        }
        for metric in KEY_DECISION_METRICS:
            cand_successes = sum(1 for row in candidate_rows if _metric_success(row, metric))
            ctrl_successes = sum(1 for row in control_rows if _metric_success(row, metric))
            cand_rate = round(cand_successes / candidate_n, 6) if candidate_n else 0.0
            ctrl_rate = round(ctrl_successes / control_n, 6) if control_n else 0.0
            cand_lower, cand_upper = normal_proportion_ci95(cand_successes, candidate_n)
            ctrl_lower, ctrl_upper = normal_proportion_ci95(ctrl_successes, control_n)
            effect = round(cand_rate - ctrl_rate, 6)
            effect_lower, effect_upper = effect_size_ci95(cand_rate, candidate_n, ctrl_rate, control_n)
            excludes_zero = _effect_excludes_zero(effect_lower, effect_upper)
            metrics.update(
                {
                    f"candidate_{metric}_successes": cand_successes,
                    f"control_{metric}_successes": ctrl_successes,
                    f"candidate_{metric}_rate": cand_rate,
                    f"candidate_{metric}_ci95_lower": cand_lower,
                    f"candidate_{metric}_ci95_upper": cand_upper,
                    f"control_{metric}_rate": ctrl_rate,
                    f"control_{metric}_ci95_lower": ctrl_lower,
                    f"control_{metric}_ci95_upper": ctrl_upper,
                    f"{metric}_effect_size": effect,
                    f"{metric}_effect_size_ci95_lower": effect_lower,
                    f"{metric}_effect_size_ci95_upper": effect_upper,
                    f"{metric}_effect_size_excludes_zero": excludes_zero,
                    f"{metric}_robustness_label": _robustness_label(
                        eligible=eligible,
                        effect=effect,
                        lower=effect_lower,
                        upper=effect_upper,
                    ),
                }
            )
        out[source] = metrics
    unknown_candidate_n = sum(
        1 for row in rows if row.get("row_type") == "CANDIDATE" and str(row.get("entry_level_source") or UNKNOWN_ENTRY_SOURCE) == UNKNOWN_ENTRY_SOURCE
    )
    if unknown_candidate_n:
        out[UNKNOWN_ENTRY_SOURCE] = {
            "candidate_n": unknown_candidate_n,
            "control_n": sum(
                1
                for row in rows
                if row.get("row_type") == "CONTROL" and str(row.get("entry_level_source") or UNKNOWN_ENTRY_SOURCE) == UNKNOWN_ENTRY_SOURCE
            ),
            "required_candidate_min_n": None,
            "eligible_for_pre_registered_verdict": False,
            "limitation": "UNKNOWN_ENTRY_SOURCE_EXCLUDED_FROM_PRE_REGISTERED_VERDICT",
        }
    return out


def _source_metrics_without_confidence(source_metrics: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for source, metrics in source_metrics.items():
        out[source] = {
            "candidate_n": metrics.get("candidate_n", 0),
            "control_n": metrics.get("control_n", 0),
            "required_candidate_min_n": metrics.get("required_candidate_min_n"),
            "eligible_for_pre_registered_verdict": metrics.get("eligible_for_pre_registered_verdict", False),
        }
        for metric in KEY_DECISION_METRICS:
            for suffix in ("rate",):
                out[source][f"candidate_{metric}_{suffix}"] = metrics.get(f"candidate_{metric}_{suffix}", 0.0)
                out[source][f"control_{metric}_{suffix}"] = metrics.get(f"control_{metric}_{suffix}", 0.0)
            out[source][f"{metric}_effect_size"] = metrics.get(f"{metric}_effect_size", 0.0)
    return out


def load_pre_registered_criteria(visual_pack_dir: Path | str) -> dict[str, Any]:
    path = _to_path(visual_pack_dir) / PRE_REGISTERED_CRITERIA_FILE
    if not path.exists():
        return {
            "loaded": False,
            "source_path": str(path),
            "verbatim": "",
            "limitation": "PRE_REGISTERED_CRITERIA_FILE_MISSING",
        }
    return {
        "loaded": True,
        "source_path": str(path),
        "verbatim": path.read_text(encoding="utf-8"),
        "limitation": None,
    }


def apply_pre_registered_decision(source_metrics: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    eligible_sources = [
        source
        for source, metrics in source_metrics.items()
        if source != UNKNOWN_ENTRY_SOURCE and bool(metrics.get("eligible_for_pre_registered_verdict"))
    ]
    ineligible_sources = {
        source: {
            "candidate_n": metrics.get("candidate_n", 0),
            "control_n": metrics.get("control_n", 0),
            "required_candidate_min_n": metrics.get("required_candidate_min_n"),
            "reason": (
                "UNKNOWN_SOURCE_EXCLUDED"
                if source == UNKNOWN_ENTRY_SOURCE
                else "BELOW_MIN_N_OR_NO_CONTROL_BASELINE"
            ),
        }
        for source, metrics in source_metrics.items()
        if source == UNKNOWN_ENTRY_SOURCE or not bool(metrics.get("eligible_for_pre_registered_verdict"))
    }

    for source in (ROUND_LEVEL, SWEEP_EXTREME, SWEPT_LIQUIDITY_LEVEL):
        if source not in eligible_sources:
            continue
        metrics = source_metrics[source]
        continue_checks = (
            ("fast_reaction", float(metrics.get("fast_reaction_effect_size", 0.0)), 0.07, ">="),
            ("runner", float(metrics.get("runner_effect_size", 0.0)), 0.05, ">="),
            ("fast_sl20", float(metrics.get("fast_sl20_effect_size", 0.0)), -0.10, "<="),
        )
        for metric, effect, threshold, operator in continue_checks:
            fired = effect >= threshold if operator == ">=" else effect <= threshold
            if fired:
                lower = metrics.get(f"{metric}_effect_size_ci95_lower")
                upper = metrics.get(f"{metric}_effect_size_ci95_upper")
                excludes_zero = bool(metrics.get(f"{metric}_effect_size_excludes_zero", False))
                if excludes_zero:
                    robustness_note = (
                        f"{PRE_REGISTERED_VERDICT_CONTINUE} per pre-registered criteria; "
                        f"triggering {source} {metric} effect CI95 excludes zero."
                    )
                else:
                    robustness_note = (
                        f"{PRE_REGISTERED_VERDICT_CONTINUE} per pre-registered criteria, "
                        "but robustness is weak at current N because the triggering effect CI95 includes zero."
                    )
                return {
                    "pre_registered_verdict": PRE_REGISTERED_VERDICT_CONTINUE,
                    "verdict_reason": f"{source}_{metric}_effect_{effect:.4f}_meets_{operator}_{threshold:.2f}",
                    "decision_source": source,
                    "decision_metric": metric,
                    "decision_effect_size": effect,
                    "decision_effect_size_ci95_lower": lower,
                    "decision_effect_size_ci95_upper": upper,
                    "decision_effect_size_excludes_zero": excludes_zero,
                    "decision_robustness_note": robustness_note,
                    "candidate_n": metrics.get("candidate_n", 0),
                    "control_n": metrics.get("control_n", 0),
                    "eligible_sources": eligible_sources,
                    "ineligible_sources": ineligible_sources,
                }

    if eligible_sources:
        stop_fires = all(
            abs(float(source_metrics[source].get("fast_reaction_effect_size", 0.0))) <= 0.03
            and float(source_metrics[source].get("fast_sl20_effect_size", 0.0)) >= -0.03
            and float(source_metrics[source].get("runner_effect_size", 0.0)) <= 0.02
            for source in eligible_sources
        )
        if stop_fires:
            return {
                "pre_registered_verdict": PRE_REGISTERED_VERDICT_STOP,
                "verdict_reason": "ALL_ELIGIBLE_SOURCES_FLAT_OR_WORSE_BY_PRE_REGISTERED_STOP_RULE",
                "decision_source": "ALL_ELIGIBLE_SOURCES",
                "decision_metric": "COMPOSITE_STOP_RULE",
                "decision_effect_size": None,
                "decision_effect_size_ci95_lower": None,
                "decision_effect_size_ci95_upper": None,
                "decision_effect_size_excludes_zero": None,
                "decision_robustness_note": "STOP_ARCHIVE_DETECTOR fired by locked descriptive criteria; CI95 metadata does not alter this verdict.",
                "candidate_n": sum(int(source_metrics[source].get("candidate_n", 0)) for source in eligible_sources),
                "control_n": sum(int(source_metrics[source].get("control_n", 0)) for source in eligible_sources),
                "eligible_sources": eligible_sources,
                "ineligible_sources": ineligible_sources,
            }
    else:
        visible_effect = None
        for source, metrics in source_metrics.items():
            if source == UNKNOWN_ENTRY_SOURCE:
                continue
            for metric in KEY_DECISION_METRICS:
                effect = float(metrics.get(f"{metric}_effect_size", 0.0))
                if abs(effect) >= 0.05:
                    visible_effect = (source, metric, effect)
                    break
            if visible_effect:
                break
        if visible_effect:
            source, metric, effect = visible_effect
            metrics = source_metrics[source]
            return {
                "pre_registered_verdict": PRE_REGISTERED_VERDICT_REPEAT,
                "verdict_reason": "VISIBLE_EFFECT_WITHOUT_ANY_SOURCE_MEETING_MIN_N",
                "decision_source": source,
                "decision_metric": metric,
                "decision_effect_size": effect,
                "decision_effect_size_ci95_lower": metrics.get(f"{metric}_effect_size_ci95_lower"),
                "decision_effect_size_ci95_upper": metrics.get(f"{metric}_effect_size_ci95_upper"),
                "decision_effect_size_excludes_zero": metrics.get(f"{metric}_effect_size_excludes_zero"),
                "decision_robustness_note": "REPEAT_EXPANSION_ONCE fired by locked underpowered-source criterion; CI95 metadata does not alter this verdict.",
                "candidate_n": metrics.get("candidate_n", 0),
                "control_n": metrics.get("control_n", 0),
                "eligible_sources": eligible_sources,
                "ineligible_sources": ineligible_sources,
            }

    return {
        "pre_registered_verdict": PRE_REGISTERED_VERDICT_INCONCLUSIVE,
        "verdict_reason": "NO_PRE_REGISTERED_RULE_FIRED",
        "decision_source": None,
        "decision_metric": None,
        "decision_effect_size": None,
        "decision_effect_size_ci95_lower": None,
        "decision_effect_size_ci95_upper": None,
        "decision_effect_size_excludes_zero": None,
        "decision_robustness_note": "INCONCLUSIVE by locked criteria; pause Adelin v2 and do not iterate ad hoc.",
        "candidate_n": sum(int(metrics.get("candidate_n", 0)) for metrics in source_metrics.values()),
        "control_n": sum(int(metrics.get("control_n", 0)) for metrics in source_metrics.values()),
        "eligible_sources": eligible_sources,
        "ineligible_sources": ineligible_sources,
    }


def _read_visual_pack_summary(visual_pack_dir: Path | str) -> dict[str, Any]:
    path = _to_path(visual_pack_dir) / "review_pack_summary.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"limitation": "VISUAL_PACK_SUMMARY_JSON_INVALID"}


def _recommended_next_action(verdict: str) -> str:
    if verdict == PRE_REGISTERED_VERDICT_CONTINUE:
        return "Proceed to detector refinement, still research-only and no live deployment."
    if verdict == PRE_REGISTERED_VERDICT_STOP:
        return "Pause/archive the Adelin v2 detector."
    if verdict == PRE_REGISTERED_VERDICT_REPEAT:
        return "Run one final 500-sample expansion only, then stop ad-hoc iteration."
    return "Pause Adelin v2; do not keep iterating without a new pre-registered plan."


def _comparison_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    return {
        "candidate_fast_reaction_rate": _rate(rows, "CANDIDATE", lambda row: bool(row.get("fast_reaction_100pips_15m"))),
        "control_fast_reaction_rate": _rate(rows, "CONTROL", lambda row: bool(row.get("fast_reaction_100pips_15m"))),
        "candidate_fast_sl_20_rate": _rate(rows, "CANDIDATE", lambda row: row.get("automatic_outcome_label") == FAST_SL_20),
        "control_fast_sl_20_rate": _rate(rows, "CONTROL", lambda row: row.get("automatic_outcome_label") == FAST_SL_20),
        "candidate_runner_candidate_rate": _rate(rows, "CANDIDATE", lambda row: row.get("automatic_outcome_label") in {RUNNER_CANDIDATE, STRONG_RUNNER}),
        "control_runner_candidate_rate": _rate(rows, "CONTROL", lambda row: row.get("automatic_outcome_label") in {RUNNER_CANDIDATE, STRONG_RUNNER}),
        "candidate_unknown_rate": _rate(rows, "CANDIDATE", lambda row: str(row.get("automatic_outcome_label", "")).startswith("UNKNOWN")),
        "control_unknown_rate": _rate(rows, "CONTROL", lambda row: str(row.get("automatic_outcome_label", "")).startswith("UNKNOWN")),
    }


def _matched_group_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    candidate_rows = [row for row in rows if row.get("row_type") == "CANDIDATE"]
    control_rows = [row for row in rows if row.get("row_type") == "CONTROL"]
    metrics = _comparison_metrics(rows)
    return {
        "candidate_count": len(candidate_rows),
        "control_count": len(control_rows),
        **metrics,
        "descriptive_effect_size_fast_reaction": round(
            metrics["candidate_fast_reaction_rate"] - metrics["control_fast_reaction_rate"], 4
        ),
        "descriptive_effect_size_fast_sl20": round(
            metrics["candidate_fast_sl_20_rate"] - metrics["control_fast_sl_20_rate"], 4
        ),
        "limitations": [
            "DESCRIPTIVE_ONLY_NOT_VALIDATION",
            *([] if len(candidate_rows) >= 20 else ["SMALL_CANDIDATE_SAMPLE"]),
            *([] if control_rows else ["NO_MATCHED_CONTROLS"]),
        ],
    }


def _entry_source_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sources = sorted({str(row.get("entry_level_source") or UNKNOWN_ENTRY_SOURCE) for row in rows})
    return {
        source: _matched_group_metrics([row for row in rows if str(row.get("entry_level_source") or UNKNOWN_ENTRY_SOURCE) == source])
        for source in sources
    }


def _entry_source_session_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    groups = sorted(
        {
            (
                str(row.get("entry_level_source") or UNKNOWN_ENTRY_SOURCE),
                str(row.get("session") or "UNKNOWN"),
            )
            for row in rows
        }
    )
    return {
        _source_session_key(source, session): _matched_group_metrics(
            [
                row
                for row in rows
                if str(row.get("entry_level_source") or UNKNOWN_ENTRY_SOURCE) == source
                and str(row.get("session") or "UNKNOWN") == session
            ]
        )
        for source, session in groups
    }


def build_summary(
    *,
    cfg: ObjectiveReplayConfig,
    started: datetime,
    pip_resolution: PipSizeResolution,
    candidate_loaded: int,
    control_requested: int,
    control_generated: int,
    rows: Sequence[Mapping[str, Any]],
    limitations: Sequence[str],
    control_generation_stats: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    control_generation_stats = dict(control_generation_stats or {})
    candidate_counts = _counts(rows, "CANDIDATE")
    control_counts = _counts(rows, "CONTROL")
    known_entry_rows = [row for row in rows if _is_known_entry(row)]
    round_level_rows = [row for row in rows if row.get("entry_level_source") == ROUND_LEVEL]
    sweep_extreme_rows = [row for row in rows if row.get("entry_level_source") == SWEEP_EXTREME]
    candidate_known_count = sum(1 for row in rows if row.get("row_type") == "CANDIDATE" and _is_known_entry(row))
    control_known_count = sum(1 for row in rows if row.get("row_type") == "CONTROL" and _is_known_entry(row))
    candidate_replayed = sum(1 for row in rows if row.get("row_type") == "CANDIDATE")
    control_replayed = sum(1 for row in rows if row.get("row_type") == "CONTROL")
    candidate_unknown_entry_count = candidate_counts.get(UNKNOWN_ENTRY_LEVEL, 0)
    control_unknown_entry_count = control_counts.get(UNKNOWN_ENTRY_LEVEL, 0)
    summary_limitations = list(limitations)
    if candidate_counts.get(UNKNOWN_ENTRY_LEVEL):
        summary_limitations.append(f"CANDIDATE_UNKNOWN_ENTRY_LEVEL_ROWS_{candidate_counts[UNKNOWN_ENTRY_LEVEL]}")
    if candidate_counts.get(UNKNOWN_DIRECTION):
        summary_limitations.append(f"CANDIDATE_UNKNOWN_DIRECTION_ROWS_{candidate_counts[UNKNOWN_DIRECTION]}")
    if control_counts.get(UNKNOWN_ENTRY_LEVEL):
        summary_limitations.append(f"CONTROL_UNKNOWN_ENTRY_LEVEL_ROWS_{control_counts[UNKNOWN_ENTRY_LEVEL]}")
    if control_counts.get(UNKNOWN_DIRECTION):
        summary_limitations.append(f"CONTROL_UNKNOWN_DIRECTION_ROWS_{control_counts[UNKNOWN_DIRECTION]}")
    if any(row.get("entry_level_source") == SWEEP_EXTREME and row.get("row_type") == "CANDIDATE" for row in rows) and not any(
        row.get("entry_level_source") == SWEEP_EXTREME and row.get("row_type") == "CONTROL" for row in rows
    ):
        summary_limitations.append("CONTROL_SWEEP_EXTREME_ROWS_0_BASELINE_UNAVAILABLE")
    criteria = load_pre_registered_criteria(cfg.visual_pack_dir)
    if criteria.get("limitation"):
        summary_limitations.append(str(criteria["limitation"]))
    visual_pack_summary = _read_visual_pack_summary(cfg.visual_pack_dir)
    for item in visual_pack_summary.get("limitations", []):
        summary_limitations.append(f"VISUAL_PACK_{item}")
    date_range_coverage = visual_pack_summary.get("date_range_coverage", {})
    if date_range_coverage and not date_range_coverage.get("meets_min_date_range_days", True):
        summary_limitations.append("VISUAL_PACK_DATE_RANGE_BELOW_REQUESTED_MINIMUM")
    source_metrics_with_confidence = build_source_metrics_with_confidence(rows)
    source_metrics = _source_metrics_without_confidence(source_metrics_with_confidence)
    decision = apply_pre_registered_decision(source_metrics_with_confidence)
    finished = _utc_now()
    runtime_seconds = round((finished - started).total_seconds(), 3)
    entry_source_session_metrics = _entry_source_session_metrics(rows)
    return {
        "run_started_at": started.isoformat(),
        "run_finished_at": finished.isoformat(),
        "runtime_seconds": runtime_seconds,
        "symbol": cfg.symbol,
        "visual_pack_dir": str(cfg.visual_pack_dir),
        "output_dir": str(cfg.output_dir),
        "dry_run": bool(cfg.dry_run),
        "pip_size_source": pip_resolution.source,
        "pip_size": pip_resolution.pip_size,
        "forward_hours": cfg.forward_hours,
        "direction_lookback_minutes": cfg.direction_lookback_minutes,
        "reaction_fast_minutes": cfg.reaction_fast_minutes,
        "reaction_slow_minutes": cfg.reaction_slow_minutes,
        "total_candidate_samples_loaded": candidate_loaded,
        "candidate_samples_replayed": candidate_replayed,
        "candidate_count": candidate_replayed,
        "control_random_requested": control_requested,
        "control_samples_generated": control_generated,
        "control_samples_replayed": control_replayed,
        "control_count": control_replayed,
        "rows_written": len(rows),
        "candidate_known_entry_count": candidate_known_count,
        "control_known_entry_count": control_known_count,
        "candidate_unknown_entry_level_count": candidate_unknown_entry_count,
        "control_unknown_entry_level_count": control_unknown_entry_count,
        "candidate_unknown_entry_level_rate": round(candidate_unknown_entry_count / candidate_replayed, 4) if candidate_replayed else 0.0,
        "control_unknown_entry_level_rate": round(control_unknown_entry_count / control_replayed, 4) if control_replayed else 0.0,
        "entry_level_source_counts": _source_counts(rows),
        "candidate_source_counts": _source_counts(rows, "CANDIDATE"),
        "control_source_counts": _source_counts(rows, "CONTROL"),
        "candidate_entry_level_source_counts": _source_counts(rows, "CANDIDATE"),
        "control_entry_level_source_counts": _source_counts(rows, "CONTROL"),
        "candidate_session_distribution": _session_distribution([row for row in rows if row.get("row_type") == "CANDIDATE"]),
        "control_session_distribution": _session_distribution([row for row in rows if row.get("row_type") == "CONTROL"]),
        "candidate_volatility_bucket_distribution": _value_distribution(rows, "volatility_bucket", "CANDIDATE"),
        "control_volatility_bucket_distribution": _value_distribution(rows, "volatility_bucket", "CONTROL"),
        "visual_pack_date_range_coverage": date_range_coverage,
        "control_generation_attempts_by_source": dict(control_generation_stats.get("attempts_by_source", {})),
        "control_generation_success_by_source": dict(control_generation_stats.get("success_by_source", {})),
        "control_generation_attempts_by_source_and_session": dict(control_generation_stats.get("attempts_by_source_and_session", {})),
        "control_generation_success_by_source_and_session": dict(control_generation_stats.get("success_by_source_and_session", {})),
        "control_generation_skip_reasons": dict(control_generation_stats.get("skip_reasons", {})),
        "control_generation_quota_by_source_and_session": dict(control_generation_stats.get("quota_by_source_and_session", {})),
        "session_match_success_rate": control_generation_stats.get("session_match_success_rate", 0.0),
        "unmatched_session_controls_allowed": bool(control_generation_stats.get("unmatched_session_controls_allowed", False)),
        "candidate_outcome_label_counts": candidate_counts,
        "control_outcome_label_counts": control_counts,
        "candidate_outcome_counts_by_entry_level_source": _outcome_counts_by_source(rows, "CANDIDATE"),
        "control_outcome_counts_by_entry_level_source": _outcome_counts_by_source(rows, "CONTROL"),
        "outcome_counts_by_entry_level_source": {
            "CANDIDATE": _outcome_counts_by_source(rows, "CANDIDATE"),
            "CONTROL": _outcome_counts_by_source(rows, "CONTROL"),
        },
        "candidate_vs_control": _comparison_metrics(rows),
        "candidate_vs_control_all_rows": _comparison_metrics(rows),
        "candidate_vs_control_known_entry": _comparison_metrics(known_entry_rows),
        "candidate_vs_control_round_level": _comparison_metrics(round_level_rows),
        "candidate_vs_control_sweep_extreme": _comparison_metrics(sweep_extreme_rows),
        "entry_source_matched_metrics": _entry_source_metrics(rows),
        "entry_source_and_session_matched_metrics": entry_source_session_metrics,
        "source_session_matched_metrics": entry_source_session_metrics,
        "source_metrics": source_metrics,
        "source_metrics_with_confidence": source_metrics_with_confidence,
        "pre_registered_criteria_loaded": bool(criteria.get("loaded")),
        "pre_registered_criteria_source_path": criteria.get("source_path"),
        "pre_registered_criteria": criteria.get("verbatim", ""),
        "pre_registered_verdict": decision["pre_registered_verdict"],
        "verdict_reason": decision["verdict_reason"],
        "decision_source": decision["decision_source"],
        "decision_metric": decision["decision_metric"],
        "decision_effect_size": decision["decision_effect_size"],
        "decision_effect_size_ci95_lower": decision["decision_effect_size_ci95_lower"],
        "decision_effect_size_ci95_upper": decision["decision_effect_size_ci95_upper"],
        "decision_effect_size_excludes_zero": decision["decision_effect_size_excludes_zero"],
        "decision_robustness_note": decision["decision_robustness_note"],
        "candidate_n": decision["candidate_n"],
        "control_n": decision["control_n"],
        "eligible_sources": decision["eligible_sources"],
        "ineligible_sources": decision["ineligible_sources"],
        "recommended_next_action": _recommended_next_action(decision["pre_registered_verdict"]),
        "limitations": sorted(set(summary_limitations)),
        "safety": {
            "live_trading_enabled": False,
            "telegram_enabled": False,
            "broker_execution_enabled": False,
            "order_execution_enabled": False,
            "strategy_2_touched": False,
            "strategy_3_touched": False,
            "data_modified": False,
        },
    }


def _write_csv(rows: Sequence[Mapping[str, Any]], output_dir: Path) -> None:
    with (output_dir / OUTPUT_CSV).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in OUTPUT_FIELDS})


def _write_json(summary: Mapping[str, Any], output_dir: Path) -> None:
    (output_dir / OUTPUT_JSON).write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _write_markdown(summary: Mapping[str, Any], output_dir: Path) -> None:
    lines = [
        "# Adelin v2 Objective Outcome Replay",
        "",
        "Status: diagnostic baseline comparison only. Candidate windows are not signals and this is not validation.",
        "",
        f"- symbol: `{summary['symbol']}`",
        f"- pip_size: `{summary['pip_size']}` from `{summary['pip_size_source']}`",
        f"- forward_hours: `{summary['forward_hours']}`",
        "",
        "Forward windows above 4h may overstate runner quality on XAUUSD.",
        "",
        "CI95 robustness metadata annotates noise and directionality only. It does not change the locked pre-registered verdict.",
        "",
        "Entry-source/session-matched controls improve baseline quality but are still descriptive and not validation.",
        "Candidate sample size remains small; do not interpret as statistically significant. Report effect sizes only.",
        "",
        "## Pre-Registered Verdict",
        "",
        f"- criteria loaded: `{summary['pre_registered_criteria_loaded']}`",
        f"- criteria source: `{summary['pre_registered_criteria_source_path']}`",
        f"- verdict: `{summary['pre_registered_verdict']}`",
        f"- verdict reason: `{summary['verdict_reason']}`",
        f"- decision source: `{summary['decision_source']}`",
        f"- decision metric: `{summary['decision_metric']}`",
        f"- decision effect size: `{summary['decision_effect_size']}`",
        f"- decision effect CI95: `{summary['decision_effect_size_ci95_lower']}` to `{summary['decision_effect_size_ci95_upper']}`",
        f"- triggering effect CI95 excludes zero: `{summary['decision_effect_size_excludes_zero']}`",
        f"- robustness note: {summary['decision_robustness_note']}",
        f"- recommended next action: {summary['recommended_next_action']}",
        "",
        "The decision criteria were loaded from the expanded pack and are not changed by this replay branch.",
        "",
        "## Counts",
        "",
        f"- candidate samples loaded: `{summary['total_candidate_samples_loaded']}`",
        f"- candidate samples replayed: `{summary['candidate_samples_replayed']}`",
        f"- control samples generated: `{summary['control_samples_generated']}`",
        f"- rows written: `{summary['rows_written']}`",
        f"- candidate known-entry rows: `{summary['candidate_known_entry_count']}`",
        f"- control known-entry rows: `{summary['control_known_entry_count']}`",
        f"- candidate unknown entry-level rate: `{summary['candidate_unknown_entry_level_rate']}`",
        "",
        "Known-entry subset is still descriptive and not validation.",
        "",
        "## Entry Level Source Counts",
        "",
        "### Candidate",
        "",
        *[f"- `{source}`: `{count}`" for source, count in summary["candidate_entry_level_source_counts"].items()],
        "",
        "### Control",
        "",
        *[f"- `{source}`: `{count}`" for source, count in summary["control_entry_level_source_counts"].items()],
        "",
        "## Session Distribution",
        "",
        "### Candidate",
        "",
        *[f"- `{session}`: `{count}`" for session, count in summary["candidate_session_distribution"].items()],
        "",
        "### Control",
        "",
        *[f"- `{session}`: `{count}`" for session, count in summary["control_session_distribution"].items()],
        "",
        "## Volatility Bucket Distribution",
        "",
        "### Candidate",
        "",
        *[f"- `{bucket}`: `{count}`" for bucket, count in summary["candidate_volatility_bucket_distribution"].items()],
        "",
        "### Control",
        "",
        *[f"- `{bucket}`: `{count}`" for bucket, count in summary["control_volatility_bucket_distribution"].items()],
        "",
        "## Control Generation",
        "",
        f"- unmatched session controls allowed: `{summary['unmatched_session_controls_allowed']}`",
        f"- session match success rate: `{summary['session_match_success_rate']}`",
        "",
        "### Attempts By Source And Session",
        "",
        *[
            f"- `{key}`: attempts `{summary['control_generation_attempts_by_source_and_session'].get(key, 0)}`, "
            f"success `{summary['control_generation_success_by_source_and_session'].get(key, 0)}`"
            for key in sorted(summary["control_generation_attempts_by_source_and_session"])
        ],
        "",
        "### Skip Reasons",
        "",
        *[f"- `{reason}`: `{count}`" for reason, count in summary["control_generation_skip_reasons"].items()],
        "",
        "## Candidate Outcome Counts",
        "",
        *[f"- `{label}`: `{count}`" for label, count in summary["candidate_outcome_label_counts"].items()],
        "",
        "## Control Outcome Counts",
        "",
        *[f"- `{label}`: `{count}`" for label, count in summary["control_outcome_label_counts"].items()],
        "",
        "## Candidate Vs Control",
        "",
        *[f"- `{key}`: `{value}`" for key, value in summary["candidate_vs_control"].items()],
        "",
        "## Candidate Vs Control Known Entry",
        "",
        *[f"- `{key}`: `{value}`" for key, value in summary["candidate_vs_control_known_entry"].items()],
        "",
        "## Entry Source Matched Metrics",
        "",
        *[
            f"- `{source}`: {json.dumps(metrics, sort_keys=True)}"
            for source, metrics in summary["entry_source_matched_metrics"].items()
        ],
        "",
        "## Source Metrics With CI95",
        "",
        *[
            f"- `{source}`: {json.dumps(metrics, sort_keys=True)}"
            for source, metrics in summary["source_metrics_with_confidence"].items()
        ],
        "",
        "## Entry Source And Session Matched Metrics",
        "",
        *[
            f"- `{key}`: {json.dumps(metrics, sort_keys=True)}"
            for key, metrics in summary["entry_source_and_session_matched_metrics"].items()
        ],
        "",
        "## Candidate Outcome Counts By Entry Source",
        "",
        *[
            f"- `{source}`: {json.dumps(counts, sort_keys=True)}"
            for source, counts in summary["candidate_outcome_counts_by_entry_level_source"].items()
        ],
        "",
        "## Control Outcome Counts By Entry Source",
        "",
        *[
            f"- `{source}`: {json.dumps(counts, sort_keys=True)}"
            for source, counts in summary["control_outcome_counts_by_entry_level_source"].items()
        ],
        "",
        "## Limitations",
        "",
        *[f"- `{item}`" for item in summary.get("limitations", [])],
    ]
    (output_dir / OUTPUT_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_html(summary: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], output_dir: Path) -> None:
    def label_table(counts: Mapping[str, int]) -> str:
        body = "".join(f"<tr><td>{html.escape(label)}</td><td>{count}</td></tr>" for label, count in counts.items())
        return f"<table><tr><th>label</th><th>count</th></tr>{body}</table>"

    body_rows = []
    for row in rows:
        link = row.get("visual_html_path")
        sample = html.escape(str(row.get("sample_id")))
        if link:
            sample = f'<a href="../adelin_v2_visual_review_pack/{html.escape(str(link))}">{sample}</a>'
        body_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('row_type')))}</td>"
            f"<td>{sample}</td>"
            f"<td>{html.escape(str(row.get('anchor_timestamp')))}</td>"
            f"<td>{html.escape(str(row.get('direction_guess')))}</td>"
            f"<td>{html.escape(str(row.get('entry_price')))}</td>"
            f"<td>{html.escape(str(row.get('entry_level_source')))}</td>"
            f"<td>{html.escape(str(row.get('entry_level_confidence')))}</td>"
            f"<td>{html.escape(str(row.get('automatic_outcome_label')))}</td>"
            f"<td>{html.escape(str(row.get('max_favorable_pips')))}</td>"
            f"<td>{html.escape(str(row.get('max_adverse_pips')))}</td>"
            "</tr>"
        )
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Adelin v2 Objective Outcome Replay</title>
  <style>
    body {{ font-family: Arial, Helvetica, sans-serif; margin: 24px; color: #172033; }}
    .warning {{ border-left: 5px solid #b91c1c; background: #fff1f2; padding: 12px; font-weight: 700; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border: 1px solid #d7d7d2; padding: 7px; text-align: left; font-size: 13px; }}
    th {{ background: #eceee8; }}
  </style>
</head>
<body>
  <h1>Adelin v2 Objective Outcome Replay</h1>
  <p class="warning">Diagnostic baseline comparison only. Not validation, not signals, not live trading.</p>
  <p><strong>Entry-source/session-matched controls improve baseline quality but remain descriptive and not validation. Candidate sample sizes are small; report effect sizes only.</strong></p>
  <p><strong>CI95 robustness metadata annotates the locked verdict only; it does not change the pre-registered decision.</strong></p>
  <h2>Pre-Registered Verdict</h2>
  <table>
    <tr><th>field</th><th>value</th></tr>
    <tr><td>criteria loaded</td><td>{html.escape(str(summary["pre_registered_criteria_loaded"]))}</td></tr>
    <tr><td>criteria source</td><td>{html.escape(str(summary["pre_registered_criteria_source_path"]))}</td></tr>
    <tr><td>verdict</td><td>{html.escape(str(summary["pre_registered_verdict"]))}</td></tr>
    <tr><td>reason</td><td>{html.escape(str(summary["verdict_reason"]))}</td></tr>
    <tr><td>decision source</td><td>{html.escape(str(summary["decision_source"]))}</td></tr>
    <tr><td>decision metric</td><td>{html.escape(str(summary["decision_metric"]))}</td></tr>
    <tr><td>decision effect</td><td>{html.escape(str(summary["decision_effect_size"]))}</td></tr>
    <tr><td>effect CI95</td><td>{html.escape(str(summary["decision_effect_size_ci95_lower"]))} to {html.escape(str(summary["decision_effect_size_ci95_upper"]))}</td></tr>
    <tr><td>effect CI95 excludes zero</td><td>{html.escape(str(summary["decision_effect_size_excludes_zero"]))}</td></tr>
    <tr><td>robustness note</td><td>{html.escape(str(summary["decision_robustness_note"]))}</td></tr>
    <tr><td>recommended next action</td><td>{html.escape(str(summary["recommended_next_action"]))}</td></tr>
  </table>
  <h2>Entry Level Source Counts</h2>
  <h3>Candidate</h3>
  {label_table(summary["candidate_entry_level_source_counts"])}
  <h3>Control</h3>
  {label_table(summary["control_entry_level_source_counts"])}
  <h2>Session Distribution</h2>
  <h3>Candidate</h3>
  {label_table(summary["candidate_session_distribution"])}
  <h3>Control</h3>
  {label_table(summary["control_session_distribution"])}
  <h2>Volatility Bucket Distribution</h2>
  <h3>Candidate</h3>
  {label_table(summary["candidate_volatility_bucket_distribution"])}
  <h3>Control</h3>
  {label_table(summary["control_volatility_bucket_distribution"])}
  <h2>Control Generation</h2>
  {label_table(summary["control_generation_success_by_source_and_session"])}
  <h2>Candidate Outcome Counts</h2>
  {label_table(summary["candidate_outcome_label_counts"])}
  <h2>Control Outcome Counts</h2>
  {label_table(summary["control_outcome_label_counts"])}
  <h2>Candidate Vs Control</h2>
  {label_table(summary["candidate_vs_control"])}
  <h2>Candidate Vs Control Known Entry</h2>
  {label_table(summary["candidate_vs_control_known_entry"])}
  <h2>Entry Source Matched Metrics</h2>
  <pre>{html.escape(json.dumps(summary["entry_source_matched_metrics"], indent=2, sort_keys=True))}</pre>
  <h2>Source Metrics With CI95</h2>
  <pre>{html.escape(json.dumps(summary["source_metrics_with_confidence"], indent=2, sort_keys=True))}</pre>
  <h2>Entry Source And Session Matched Metrics</h2>
  <pre>{html.escape(json.dumps(summary["entry_source_and_session_matched_metrics"], indent=2, sort_keys=True))}</pre>
  <h2>Rows</h2>
  <table><tr><th>type</th><th>sample</th><th>anchor</th><th>direction</th><th>entry</th><th>source</th><th>confidence</th><th>label</th><th>MFE</th><th>MAE</th></tr>
  {''.join(body_rows)}
  </table>
</body>
</html>
"""
    (output_dir / OUTPUT_HTML).write_text(html_text, encoding="utf-8")


def _write_enriched_labels(
    original_rows: Sequence[Mapping[str, Any]],
    replay_rows: Sequence[Mapping[str, Any]],
    output_dir: Path,
) -> None:
    if not original_rows:
        with (output_dir / OUTPUT_ENRICHED_LABELS).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["sample_id", "automatic_outcome_label"])
            writer.writeheader()
        return
    by_sample = {str(row.get("sample_id")): row for row in replay_rows if row.get("row_type") == "CANDIDATE"}
    original_fields = list(original_rows[0].keys())
    objective_fields = [
        "automatic_outcome_label",
        "direction_guess",
        "entry_price",
        "entry_level_source",
        "entry_level_confidence",
        "entry_level_reason_codes",
        "entry_level_is_heuristic",
        "max_favorable_pips",
        "max_adverse_pips",
        "time_to_100_pips_minutes",
        "fast_reaction_100pips_15m",
        "sl_20_hit",
        "sl_40_hit",
        "limitations",
    ]
    with (output_dir / OUTPUT_ENRICHED_LABELS).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=original_fields + objective_fields)
        writer.writeheader()
        for row in original_rows:
            merged = dict(row)
            replay = by_sample.get(str(row.get("sample_id")), {})
            for field in objective_fields:
                merged[field] = replay.get(field)
            writer.writerow(merged)


def run_objective_replay(cfg: ObjectiveReplayConfig) -> dict[str, Any]:
    started = _utc_now()
    output_dir = _to_path(cfg.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    limitations: list[str] = []
    if cfg.forward_hours > 4:
        limitations.append("FORWARD_WINDOW_ABOVE_4H_MAY_OVERSTATE_RUNNER_QUALITY")
    pip_resolution = resolve_pip_size(cfg.symbol, cfg.pip_size_override)
    frames = load_csv_timeframes(cfg.symbol, ["M1", "M5", "M15", "H1"], data_dir=str(cfg.data_dir))
    for tf in ("M1", "M5", "M15", "H1"):
        if tf not in frames:
            limitations.append(f"MISSING_TIMEFRAME_{tf}")
    candidate_samples, original_rows, visual_limitations = load_visual_review_samples(cfg.visual_pack_dir, cfg.symbol)
    limitations.extend(visual_limitations)
    replay_rows: list[dict[str, Any]] = []
    for sample in candidate_samples:
        direction = infer_reversal_direction(
            frames,
            sample.anchor_timestamp,
            lookback_minutes=cfg.direction_lookback_minutes,
            pip_size=pip_resolution.pip_size,
        )
        entry = build_entry_hypothesis(
            sample,
            frames,
            direction,
            symbol=cfg.symbol,
            threshold_pips=cfg.round_level_threshold_pips,
            pip_size=pip_resolution.pip_size,
        )
        replay_rows.append(
            replay_forward_path(
                sample,
                frames,
                entry,
                direction,
                symbol=cfg.symbol,
                pip_size=pip_resolution.pip_size,
                forward_hours=cfg.forward_hours,
                reaction_fast_minutes=cfg.reaction_fast_minutes,
                reaction_slow_minutes=cfg.reaction_slow_minutes,
            )
        )
    control_result = generate_control_samples(
        candidate_samples,
        frames,
        symbol=cfg.symbol,
        requested=cfg.include_control_random,
        forward_hours=cfg.forward_hours,
        threshold_pips=cfg.round_level_threshold_pips,
        seed=cfg.random_seed,
        candidate_rows=[row for row in replay_rows if row.get("row_type") == "CANDIDATE"],
        pip_size=pip_resolution.pip_size,
        cfg=cfg,
    )
    limitations.extend(control_result.limitations)
    for sample in control_result.samples:
        direction = _control_direction_from_metadata(sample) or infer_reversal_direction(
            frames,
            sample.anchor_timestamp,
            lookback_minutes=cfg.direction_lookback_minutes,
            pip_size=pip_resolution.pip_size,
            include_anchor=False,
        )
        entry = _control_entry_from_metadata(sample) or build_entry_hypothesis(
            sample,
            frames,
            direction,
            symbol=cfg.symbol,
            threshold_pips=cfg.round_level_threshold_pips,
            pip_size=pip_resolution.pip_size,
        )
        replay_rows.append(
            replay_forward_path(
                sample,
                frames,
                entry,
                direction,
                symbol=cfg.symbol,
                pip_size=pip_resolution.pip_size,
                forward_hours=cfg.forward_hours,
                reaction_fast_minutes=cfg.reaction_fast_minutes,
                reaction_slow_minutes=cfg.reaction_slow_minutes,
            )
        )
    summary = build_summary(
        cfg=cfg,
        started=started,
        pip_resolution=pip_resolution,
        candidate_loaded=len(candidate_samples),
        control_requested=cfg.include_control_random,
        control_generated=len(control_result.samples),
        rows=replay_rows,
        limitations=limitations,
        control_generation_stats=control_result.stats,
    )
    _write_csv(replay_rows, output_dir)
    _write_json(summary, output_dir)
    _write_markdown(summary, output_dir)
    _write_html(summary, replay_rows, output_dir)
    _write_enriched_labels(original_rows, replay_rows, output_dir)
    return summary


__all__ = [
    "FAST_SL_20",
    "GOOD_FAST_REACTION",
    "GOOD_SLOW_REACTION",
    "NO_REACTION",
    "ControlGenerationResult",
    "ObjectiveReplayConfig",
    "PRE_REGISTERED_VERDICT_CONTINUE",
    "PRE_REGISTERED_VERDICT_INCONCLUSIVE",
    "PRE_REGISTERED_VERDICT_REPEAT",
    "PRE_REGISTERED_VERDICT_STOP",
    "ROUND_LEVEL",
    "ROUND_LEVEL_TOUCH_ENTRY",
    "SWEEP_EXTREME",
    "SWEPT_LIQUIDITY_LEVEL",
    "UNKNOWN_DIRECTION",
    "UNKNOWN_ENTRY_LEVEL",
    "UNKNOWN_INSUFFICIENT_FORWARD_DATA",
    "apply_pre_registered_decision",
    "build_entry_hypothesis",
    "build_round_level_entry",
    "build_source_metrics_with_confidence",
    "detect_pre_anchor_sweep_control",
    "effect_size_ci95",
    "generate_control_samples",
    "infer_reversal_direction",
    "load_pre_registered_criteria",
    "normal_proportion_ci95",
    "replay_forward_path",
    "resolve_pip_size",
    "run_objective_replay",
]
