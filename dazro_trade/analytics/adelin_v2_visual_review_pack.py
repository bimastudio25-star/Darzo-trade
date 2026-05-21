"""Build research-only Adelin v2 visual review packs.

The pack is for manual labeling only. Candidate windows are sampled from
historical candles or old Adelin exports, rendered as static HTML/SVG review
pages, and never treated as signals. This module intentionally avoids live
strategy, broker, order, and notification imports.
"""
from __future__ import annotations

import csv
import html
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from dazro_trade.analytics.adelin_v2_operational_audit import (
    AdelinV2AuditConfig,
    audit_trade_row,
    filter_adelin_trade_rows,
    nearest_number_theory_level,
    number_theory_distance_pips,
    pip_size_for_symbol,
)
from dazro_trade.analytics.adelin_v2_objective_outcome_replay import (
    ROUND_LEVEL,
    SWEEP_EXTREME,
    SWEPT_LIQUIDITY_LEVEL,
    UNKNOWN_ENTRY_SOURCE,
    classify_session,
    detect_pre_anchor_sweep_control,
)
from dazro_trade.backtest.data_loader import load_csv_timeframes


RESEARCH_WARNING = "Candidate windows are for visual labeling only and are not trade signals."
DEFAULT_OUTPUT_DIR = Path("backtests/reports/adelin_v2_visual_review_pack")
DEFAULT_AUDIT_PATH = Path("backtests/reports/adelin_v2_operational_audit/adelin_v2_trade_audit.csv")
DEFAULT_TRADES_PATH = Path("backtests/reports/final/executed_trades.csv")
SUPPORTED_TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1"]
REVIEWABLE_M1_M5 = "REVIEWABLE_M1_M5"
REVIEWABLE_M5_ONLY = "REVIEWABLE_M5_ONLY"
WEAK_M1_ONLY = "WEAK_M1_ONLY"
INSUFFICIENT_EXECUTION_DATA = "INSUFFICIENT_EXECUTION_DATA"
MULTI_TF_LIQUIDITY_CLUSTER = "MULTI_TF_LIQUIDITY_CLUSTER"
DECISION_VERDICTS = (
    "CONTINUE_DETECTOR_REFINEMENT",
    "STOP_ARCHIVE_ADELIN_V2_DETECTOR",
    "REPEAT_EXPANSION_ONCE",
    "INCONCLUSIVE_DATA_QUALITY_LIMITATION",
)
PRE_REGISTERED_DECISION_CRITERIA = {
    "useful_source_min_candidate_n": 80,
    "primary_metrics": ["fast_reaction_rate", "runner_rate", "fast_sl20_rate"],
    "continue_detector_refinement": {
        "fast_reaction_improvement_min": 0.07,
        "runner_improvement_min": 0.05,
        "fast_sl20_reduction_min": 0.10,
        "non_worse_fast_reaction_tolerance": -0.03,
    },
    "stop_archive_detector": {
        "flat_fast_reaction_range": [-0.03, 0.03],
        "flat_runner_range": [-0.03, 0.03],
        "fast_sl20_worse_all_sources_min": 0.05,
    },
    "repeat_expansion_once": {
        "underpowered_candidate_n": 100,
        "fast_reaction_visible_effect_min": 0.05,
        "runner_visible_effect_min": 0.03,
        "fast_sl20_visible_reduction_min": 0.10,
    },
    "warning": "Criteria are descriptive project gates, not statistical proof or profitability validation.",
}

MANUAL_LABEL_COLUMNS = [
    "sample_id",
    "source_mode",
    "symbol",
    "direction_guess",
    "direction_confidence",
    "window_start",
    "window_end",
    "anchor_timestamp",
    "anchor_timeframe",
    "anchor_date",
    "month",
    "session",
    "candidate_source_type",
    "entry_level_source",
    "entry_level_confidence",
    "entry_level_price",
    "entry_level_is_heuristic",
    "volatility_bucket",
    "chart_path",
    "html_path",
    "execution_data_status",
    "m1_candles_count",
    "m5_candles_count",
    "m15_candles_count",
    "h1_candles_count",
    "m1_count",
    "m5_count",
    "m15_count",
    "h1_count",
    "execution_window_start",
    "execution_window_end",
    "candidate_reason_codes",
    "limitations",
    "reviewer_should_skip_due_to_missing_ltf_data_manual",
    "htf_liquidity_class_manual",
    "ltf_liquidity_class_manual",
    "multi_tf_alignment_manual",
    "liquidity_taken_manual",
    "liquidity_depth_quality_manual",
    "shallow_liquidity_trap_manual",
    "target_liquidity_available_manual",
    "reaction_zone_present_manual",
    "reaction_zone_type_manual",
    "reaction_zone_age_quality_manual",
    "fvg_valid_manual",
    "ifvg_valid_manual",
    "volume_crack_present_manual",
    "volume_profile_clean_manual",
    "number_theory_confluence_manual",
    "adelin_v2_label_manual",
    "would_trade_manual",
    "no_trade_reason_manual",
    "setup_quality_score_manual",
    "reversal_or_continuation_manual",
    "rare_ifvg_continuation_candidate_manual",
    "expected_sl_pips_manual",
    "sl_acceptable_manual",
    "be_after_reaction_manual",
    "early_close_candidate_manual",
    "accumulation_after_entry_manual",
    "m1_engulfing_against_manual",
    "runner_target_manual",
    "partial_management_manual",
    "expected_target_area_manual",
    "actual_reaction_quality_manual",
    "actual_followthrough_quality_manual",
    "reviewer_confidence_manual",
    "reviewer_notes",
]


@dataclass(frozen=True)
class VisualReviewPackConfig:
    symbol: str = "XAUUSD"
    data_dir: Path | str = Path("data")
    output_dir: Path | str = DEFAULT_OUTPUT_DIR
    trades_path: Path | str | None = None
    audit_path: Path | str | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None
    max_samples: int = 300
    min_date_range_days: int = 180
    max_samples_per_day: int = 5
    min_sample_spacing_minutes: int = 240
    target_session_balance: bool = False
    include_candidate_windows: bool = True
    include_trade_review: bool = True
    allow_weak_m1_only: bool = False
    include_insufficient_execution_debug: bool = False
    dry_run: bool = True
    number_theory_threshold_pips: float = 5.0


@dataclass
class VisualReviewSample:
    sample_id: str
    source_mode: str
    symbol: str
    direction_guess: str
    anchor_timestamp: datetime
    anchor_timeframe: str
    window_start: datetime
    window_end: datetime
    candidate_reason_codes: tuple[str, ...]
    candidate_source_type: str = UNKNOWN_ENTRY_SOURCE
    entry_level_source: str = UNKNOWN_ENTRY_SOURCE
    entry_level_confidence: str = "UNKNOWN"
    entry_level_price: float | None = None
    entry_level_is_heuristic: bool = True
    direction_confidence: str = "UNKNOWN"
    session: str = "OTHER"
    anchor_date: str = ""
    month: str = ""
    volatility_bucket: str = "UNKNOWN"
    limitations: tuple[str, ...] = field(default_factory=tuple)
    sweep_level: float | None = None
    number_theory_level: float | None = None
    distance_to_number_level_pips: float | None = None
    reaction_zone_guess: str | None = None
    old_trade_id: str | None = None
    old_score: float | None = None
    old_setup_mode: str | None = None
    old_outcome: str | None = None
    old_entry_price: float | None = None
    old_stop_loss: float | None = None
    old_take_profit: float | None = None
    chart_path: str = ""
    html_path: str = ""
    execution_data_status: str = INSUFFICIENT_EXECUTION_DATA
    m1_candles_count: int = 0
    m5_candles_count: int = 0
    m15_candles_count: int = 0
    h1_candles_count: int = 0
    execution_window_start: datetime | None = None
    execution_window_end: datetime | None = None
    notes: str = ""
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def to_manual_label_row(self) -> dict[str, Any]:
        row = {column: "" for column in MANUAL_LABEL_COLUMNS}
        row.update(
            {
                "sample_id": self.sample_id,
                "source_mode": self.source_mode,
                "symbol": self.symbol,
                "direction_guess": self.direction_guess,
                "direction_confidence": self.direction_confidence,
                "window_start": self.window_start.isoformat(),
                "window_end": self.window_end.isoformat(),
                "anchor_timestamp": self.anchor_timestamp.isoformat(),
                "anchor_timeframe": self.anchor_timeframe,
                "anchor_date": self.anchor_date or self.anchor_timestamp.date().isoformat(),
                "month": self.month or self.anchor_timestamp.strftime("%Y-%m"),
                "session": self.session,
                "candidate_source_type": self.candidate_source_type,
                "entry_level_source": self.entry_level_source,
                "entry_level_confidence": self.entry_level_confidence,
                "entry_level_price": self.entry_level_price if self.entry_level_price is not None else "",
                "entry_level_is_heuristic": self.entry_level_is_heuristic,
                "volatility_bucket": self.volatility_bucket,
                "chart_path": self.chart_path,
                "html_path": self.html_path,
                "execution_data_status": self.execution_data_status,
                "m1_candles_count": self.m1_candles_count,
                "m5_candles_count": self.m5_candles_count,
                "m15_candles_count": self.m15_candles_count,
                "h1_candles_count": self.h1_candles_count,
                "m1_count": self.m1_candles_count,
                "m5_count": self.m5_candles_count,
                "m15_count": self.m15_candles_count,
                "h1_count": self.h1_candles_count,
                "execution_window_start": self.execution_window_start.isoformat() if self.execution_window_start else "",
                "execution_window_end": self.execution_window_end.isoformat() if self.execution_window_end else "",
                "candidate_reason_codes": "|".join(self.candidate_reason_codes),
                "limitations": "|".join(self.limitations),
            }
        )
        return row


def is_near_number_theory_level(
    price: float,
    *,
    symbol: str = "XAUUSD",
    threshold_pips: float = 5.0,
) -> tuple[bool, float, float]:
    pip_size = pip_size_for_symbol(symbol)
    level, distance = number_theory_distance_pips(price, pip_size=pip_size)
    return distance <= threshold_pips, level, distance


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_path(value: Path | str | None) -> Path | None:
    if value is None:
        return None
    return value if isinstance(value, Path) else Path(value)


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _read_csv_rows(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def _discover_existing_path(explicit: Path | str | None, default_path: Path) -> Path | None:
    if explicit is not None:
        return _to_path(explicit)
    return default_path if default_path.exists() else None


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


def _time_index(frame: pd.DataFrame) -> pd.DatetimeIndex:
    if frame is None or frame.empty or "time" not in frame.columns:
        return pd.DatetimeIndex([], tz="UTC")
    times = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    return pd.DatetimeIndex(times.dropna().sort_values())


def _count_time_window(times: pd.DatetimeIndex, start: datetime, end: datetime) -> int:
    if len(times) == 0:
        return 0
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    left = int(times.searchsorted(start_ts, side="left"))
    right = int(times.searchsorted(end_ts, side="right"))
    return max(0, right - left)


def _set_execution_coverage(sample: VisualReviewSample, time_indexes: Mapping[str, pd.DatetimeIndex]) -> None:
    start = sample.execution_window_start or sample.window_start
    end = sample.execution_window_end or sample.window_end
    sample.execution_window_start = start
    sample.execution_window_end = end
    sample.m1_candles_count = _count_time_window(time_indexes.get("M1", pd.DatetimeIndex([], tz="UTC")), start, end)
    sample.m5_candles_count = _count_time_window(time_indexes.get("M5", pd.DatetimeIndex([], tz="UTC")), start, end)
    sample.m15_candles_count = _count_time_window(time_indexes.get("M15", pd.DatetimeIndex([], tz="UTC")), start, end)
    sample.h1_candles_count = _count_time_window(time_indexes.get("H1", pd.DatetimeIndex([], tz="UTC")), start, end)
    context_exists = sample.m15_candles_count > 0 or sample.h1_candles_count > 0
    if not context_exists or (sample.m1_candles_count <= 0 and sample.m5_candles_count <= 0):
        sample.execution_data_status = INSUFFICIENT_EXECUTION_DATA
    elif sample.m1_candles_count > 0 and sample.m5_candles_count > 0:
        sample.execution_data_status = REVIEWABLE_M1_M5
    elif sample.m5_candles_count > 0:
        sample.execution_data_status = REVIEWABLE_M5_ONLY
    else:
        sample.execution_data_status = WEAK_M1_ONLY


def _set_all_execution_coverage(samples: Iterable[VisualReviewSample], frames: dict[str, pd.DataFrame]) -> None:
    time_indexes = {tf: _time_index(frame) for tf, frame in frames.items() if tf in {"M1", "M5", "M15", "H1"}}
    for sample in samples:
        _set_execution_coverage(sample, time_indexes)


def _coverage_rank(status: str) -> int:
    return {
        REVIEWABLE_M1_M5: 0,
        REVIEWABLE_M5_ONLY: 1,
        WEAK_M1_ONLY: 2,
        INSUFFICIENT_EXECUTION_DATA: 3,
    }.get(status, 4)


def _date_key(ts: datetime) -> str:
    return ts.date().isoformat()


def _month_key(ts: datetime) -> str:
    return ts.strftime("%Y-%m")


def _week_key(ts: datetime) -> str:
    iso = ts.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _passes_spacing(sample: VisualReviewSample, selected: Sequence[VisualReviewSample], min_spacing_minutes: int) -> bool:
    if min_spacing_minutes <= 0:
        return True
    return all(
        abs((sample.anchor_timestamp - prior.anchor_timestamp).total_seconds()) >= min_spacing_minutes * 60
        for prior in selected
    )


def _selection_bucket(sample: VisualReviewSample, *, target_session_balance: bool) -> tuple[str, str, str]:
    session_key = sample.session if target_session_balance else ""
    return (_month_key(sample.anchor_timestamp), sample.candidate_source_type or UNKNOWN_ENTRY_SOURCE, session_key)


def _select_by_regime_constraints(
    candidates: Sequence[VisualReviewSample],
    max_samples: int,
    *,
    max_samples_per_day: int,
    min_sample_spacing_minutes: int,
    target_session_balance: bool,
) -> tuple[list[VisualReviewSample], int, int]:
    """Select samples across months/sources without using forward outcomes."""
    buckets: dict[tuple[str, str, str], list[VisualReviewSample]] = defaultdict(list)
    for sample in sorted(candidates, key=lambda item: item.anchor_timestamp):
        buckets[_selection_bucket(sample, target_session_balance=target_session_balance)].append(sample)
    ordered_keys = sorted(buckets)
    selected: list[VisualReviewSample] = []
    per_day: Counter[str] = Counter()
    skipped_spacing = 0
    skipped_max_per_day = 0
    while len(selected) < max_samples and any(buckets.values()):
        made_progress = False
        for key in ordered_keys:
            if len(selected) >= max_samples:
                break
            bucket = buckets.get(key) or []
            while bucket:
                sample = bucket.pop(0)
                day = _date_key(sample.anchor_timestamp)
                if max_samples_per_day > 0 and per_day[day] >= max_samples_per_day:
                    skipped_max_per_day += 1
                    continue
                if not _passes_spacing(sample, selected, min_sample_spacing_minutes):
                    skipped_spacing += 1
                    continue
                selected.append(sample)
                per_day[day] += 1
                made_progress = True
                break
            buckets[key] = bucket
        if not made_progress:
            break
    return selected[:max_samples], skipped_spacing, skipped_max_per_day


def _prefer_reviewable_samples(
    samples: list[VisualReviewSample],
    max_samples: int,
    *,
    max_samples_per_day: int = 5,
    min_sample_spacing_minutes: int = 240,
    target_session_balance: bool = False,
    allow_weak_m1_only: bool = False,
    include_insufficient_execution_debug: bool = False,
) -> tuple[list[VisualReviewSample], int, int, int]:
    ordered: list[VisualReviewSample] = []
    statuses = [REVIEWABLE_M1_M5]
    if allow_weak_m1_only:
        statuses.append(WEAK_M1_ONLY)
    if include_insufficient_execution_debug:
        statuses.extend([REVIEWABLE_M5_ONLY, WEAK_M1_ONLY, INSUFFICIENT_EXECUTION_DATA])
    for status in statuses:
        group = [sample for sample in samples if sample.execution_data_status == status]
        ordered.extend(sorted(group, key=lambda item: (_month_key(item.anchor_timestamp), _coverage_rank(item.execution_data_status), item.anchor_timestamp)))
    selected, skipped_spacing, skipped_max_per_day = _select_by_regime_constraints(
        ordered,
        max_samples,
        max_samples_per_day=max_samples_per_day,
        min_sample_spacing_minutes=min_sample_spacing_minutes,
        target_session_balance=target_session_balance,
    )
    selected_ids = {id(sample) for sample in selected}
    skipped_insufficient = sum(
        1
        for sample in samples
        if sample.execution_data_status != REVIEWABLE_M1_M5 and id(sample) not in selected_ids
    )
    return selected, skipped_insufficient, skipped_spacing, skipped_max_per_day


def _first(row: Mapping[str, Any], names: Sequence[str]) -> Any:
    normalised = {str(k).strip().lower().replace(" ", "_").replace("-", "_"): v for k, v in row.items()}
    for name in names:
        key = name.strip().lower().replace(" ", "_").replace("-", "_")
        if key in normalised:
            return normalised[key]
    return None


def _load_market_frames(cfg: VisualReviewPackConfig, limitations: list[str]) -> dict[str, pd.DataFrame]:
    try:
        frames = load_csv_timeframes(
            cfg.symbol,
            SUPPORTED_TIMEFRAMES,
            data_dir=str(cfg.data_dir),
            date_from=cfg.from_date,
            date_to=cfg.to_date,
        )
    except Exception as exc:
        limitations.append(f"CANDLE_DATA_LOAD_FAILED:{type(exc).__name__}")
        return {}
    if not frames:
        limitations.append("NO_CANDLE_DATA_LOADED")
    missing = [tf for tf in SUPPORTED_TIMEFRAMES if tf not in frames]
    for tf in missing:
        limitations.append(f"MISSING_TIMEFRAME_{tf}")
    return frames


def _trade_review_samples(cfg: VisualReviewPackConfig, limitations: list[str]) -> tuple[list[VisualReviewSample], int, int]:
    samples: list[VisualReviewSample] = []
    trades_loaded = 0
    audit_rows_loaded = 0
    audit_path = _discover_existing_path(cfg.audit_path, DEFAULT_AUDIT_PATH)
    if audit_path is not None:
        if audit_path.exists():
            audit_rows, _ = _read_csv_rows(audit_path)
            audit_rows_loaded = len(audit_rows)
            for row in audit_rows:
                anchor = _parse_dt(str(_first(row, ("signal_timestamp", "entry_timestamp", "anchor_timestamp")) or ""))
                if anchor is None:
                    continue
                direction = str(_first(row, ("direction", "direction_guess")) or "UNKNOWN").upper()
                reasons = tuple(
                    item for item in str(_first(row, ("reason_codes", "candidate_reason_codes")) or "").split("|") if item
                )
                label = str(_first(row, ("final_adelin_v2_label",)) or "")
                extra_reason = f"AUDIT_LABEL_{label}" if label else "OLD_ADELIN_AUDIT_ROW"
                sample = VisualReviewSample(
                    sample_id="",
                    source_mode="TRADE_REVIEW_MODE",
                    symbol=str(_first(row, ("symbol",)) or cfg.symbol),
                    direction_guess=direction,
                    anchor_timestamp=anchor,
                    anchor_timeframe="M1",
                    window_start=anchor - timedelta(minutes=90),
                    window_end=anchor + timedelta(minutes=180),
                    candidate_reason_codes=(extra_reason,) + reasons,
                    sweep_level=None,
                    number_theory_level=_parse_float(_first(row, ("nearest_number_theory_level",))),
                    distance_to_number_level_pips=_parse_float(_first(row, ("distance_to_number_level_pips",))),
                    reaction_zone_guess=str(_first(row, ("reaction_zone_type",)) or ""),
                    old_trade_id=str(_first(row, ("trade_id",)) or "") or None,
                    old_score=_parse_float(_first(row, ("old_score",))),
                    old_setup_mode=str(_first(row, ("old_setup_mode",)) or "") or None,
                    old_entry_price=_parse_float(_first(row, ("entry_price",))),
                    old_stop_loss=_parse_float(_first(row, ("stop_loss",))),
                    old_take_profit=_parse_float(_first(row, ("take_profit",))),
                    notes="Old Adelin audit row for manual visual review.",
                    raw_metadata=dict(row),
                )
                samples.append(sample)
        else:
            limitations.append("AUDIT_PATH_MISSING")
    else:
        limitations.append("NO_AUDIT_PATH_AVAILABLE")

    trades_path = _discover_existing_path(cfg.trades_path, DEFAULT_TRADES_PATH)
    if trades_path is not None:
        if trades_path.exists():
            trade_rows, _ = _read_csv_rows(trades_path)
            trades_loaded = len(trade_rows)
            adelin_rows, metadata = filter_adelin_trade_rows(trade_rows)
            if metadata.get("filter_limitation"):
                limitations.append(str(metadata["filter_limitation"]))
            if trade_rows and not adelin_rows:
                limitations.append("NO_ADELIN_ROWS_FOUND_IN_TRADES_EXPORT")
            audit_cfg = AdelinV2AuditConfig(symbol=cfg.symbol, number_theory_threshold_pips=cfg.number_theory_threshold_pips)
            for row in adelin_rows:
                record = audit_trade_row(row, audit_cfg)
                anchor = record.signal_timestamp or record.entry_timestamp
                if anchor is None:
                    continue
                sample = VisualReviewSample(
                    sample_id="",
                    source_mode="TRADE_REVIEW_MODE",
                    symbol=record.symbol,
                    direction_guess=(record.direction or "UNKNOWN").upper(),
                    anchor_timestamp=anchor,
                    anchor_timeframe="M1",
                    window_start=anchor - timedelta(minutes=90),
                    window_end=anchor + timedelta(minutes=180),
                    candidate_reason_codes=("OLD_ADELIN_TRADE_EXPORT_ROW",) + record.reason_codes,
                    number_theory_level=record.nearest_number_theory_level,
                    distance_to_number_level_pips=record.distance_to_number_level_pips,
                    reaction_zone_guess=record.reaction_zone_type.value,
                    old_trade_id=record.trade_id,
                    old_score=record.old_score,
                    old_setup_mode=record.old_setup_mode,
                    old_entry_price=record.entry_price,
                    old_stop_loss=record.stop_loss,
                    old_take_profit=record.take_profit,
                    notes="Old Adelin trade export row for manual visual review.",
                    raw_metadata=dict(row),
                )
                samples.append(sample)
        else:
            limitations.append("TRADES_PATH_MISSING")
    else:
        limitations.append("NO_TRADES_PATH_AVAILABLE")
    return samples, trades_loaded, audit_rows_loaded


def _normalised_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty or "time" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["time"] = pd.to_datetime(out["time"], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close"):
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    return out.dropna(subset=["time", "high", "low"]).sort_values("time").reset_index(drop=True)


def _frame_time_bounds(frames: Mapping[str, pd.DataFrame]) -> tuple[datetime | None, datetime | None, int]:
    starts: list[pd.Timestamp] = []
    ends: list[pd.Timestamp] = []
    for timeframe in ("M1", "M5", "M15", "H1", "H4", "D1"):
        frame = frames.get(timeframe, pd.DataFrame())
        if frame is None or frame.empty or "time" not in frame.columns:
            continue
        times = pd.to_datetime(frame["time"], utc=True, errors="coerce").dropna()
        if times.empty:
            continue
        starts.append(times.min())
        ends.append(times.max())
    if not starts or not ends:
        return None, None, 0
    start = min(starts).to_pydatetime()
    end = max(ends).to_pydatetime()
    coverage_days = max(1, (end.date() - start.date()).days + 1)
    return start, end, coverage_days


def _time_bounds_for(frame: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if frame is None or frame.empty or "time" not in frame.columns:
        return None, None
    times = pd.to_datetime(frame["time"], utc=True, errors="coerce").dropna()
    if times.empty:
        return None, None
    return times.min(), times.max()


def _required_execution_time_bounds(frames: Mapping[str, pd.DataFrame]) -> tuple[datetime | None, datetime | None, int]:
    """Coverage where full M1/M5 plus M15-or-H1 review context can exist."""
    m1_start, m1_end = _time_bounds_for(frames.get("M1", pd.DataFrame()))
    m5_start, m5_end = _time_bounds_for(frames.get("M5", pd.DataFrame()))
    m15_start, m15_end = _time_bounds_for(frames.get("M15", pd.DataFrame()))
    h1_start, h1_end = _time_bounds_for(frames.get("H1", pd.DataFrame()))
    context_starts = [value for value in (m15_start, h1_start) if value is not None]
    context_ends = [value for value in (m15_end, h1_end) if value is not None]
    if m1_start is None or m1_end is None or m5_start is None or m5_end is None or not context_starts or not context_ends:
        return None, None, 0
    start = max(m1_start, m5_start, min(context_starts))
    end = min(m1_end, m5_end, max(context_ends))
    if end < start:
        return None, None, 0
    start_dt = start.to_pydatetime()
    end_dt = end.to_pydatetime()
    coverage_days = max(1, (end_dt.date() - start_dt.date()).days + 1)
    return start_dt, end_dt, coverage_days


def _sample_time_bounds(samples: Sequence[VisualReviewSample]) -> tuple[str | None, str | None, int]:
    if not samples:
        return None, None, 0
    dates = sorted(sample.anchor_timestamp.date() for sample in samples)
    coverage_days = max(1, (dates[-1] - dates[0]).days + 1)
    return dates[0].isoformat(), dates[-1].isoformat(), coverage_days


def _daily_range_map(frames: Mapping[str, pd.DataFrame]) -> dict[str, float]:
    source = _normalised_ohlc(frames.get("D1", pd.DataFrame()))
    if not source.empty:
        return {
            pd.Timestamp(row.time).date().isoformat(): float(row.high) - float(row.low)
            for row in source.itertuples(index=False)
        }
    for timeframe in ("H1", "M15"):
        source = _normalised_ohlc(frames.get(timeframe, pd.DataFrame()))
        if source.empty:
            continue
        source["date"] = source["time"].dt.date.astype(str)
        grouped = source.groupby("date").agg(high=("high", "max"), low=("low", "min"))
        return {str(date): float(row.high) - float(row.low) for date, row in grouped.iterrows()}
    return {}


def _volatility_bucket_map(frames: Mapping[str, pd.DataFrame], limitations: list[str]) -> dict[str, str]:
    daily_ranges = _daily_range_map(frames)
    if not daily_ranges:
        limitations.append("VOLATILITY_BUCKETS_UNAVAILABLE")
        return {}
    values = pd.Series(list(daily_ranges.values()), dtype="float64").dropna()
    if values.empty:
        limitations.append("VOLATILITY_BUCKETS_UNAVAILABLE")
        return {}
    if len(values) < 3 or float(values.max()) == float(values.min()):
        return {date: "MID_VOLATILITY" for date in daily_ranges}
    low_cut = float(values.quantile(0.33))
    high_cut = float(values.quantile(0.67))
    buckets: dict[str, str] = {}
    for date, value in daily_ranges.items():
        if value <= low_cut:
            buckets[date] = "LOW_VOLATILITY"
        elif value >= high_cut:
            buckets[date] = "HIGH_VOLATILITY"
        else:
            buckets[date] = "MID_VOLATILITY"
    return buckets


def _append_reason(sample: VisualReviewSample, reason: str) -> None:
    sample.candidate_reason_codes = tuple(dict.fromkeys((*sample.candidate_reason_codes, reason)))


def _annotate_sample_metadata(
    sample: VisualReviewSample,
    frames: Mapping[str, pd.DataFrame],
    cfg: VisualReviewPackConfig,
    volatility_buckets: Mapping[str, str],
) -> None:
    sample.anchor_date = _date_key(sample.anchor_timestamp)
    sample.month = _month_key(sample.anchor_timestamp)
    sample.session = classify_session(sample.anchor_timestamp)
    sample.volatility_bucket = volatility_buckets.get(sample.anchor_date, "UNKNOWN")
    sample.raw_metadata.update(
        {
            "session": sample.session,
            "anchor_date": sample.anchor_date,
            "month": sample.month,
            "volatility_bucket": sample.volatility_bucket,
        }
    )

    if sample.number_theory_level is not None:
        sample.candidate_source_type = ROUND_LEVEL
        sample.entry_level_source = ROUND_LEVEL
        sample.entry_level_confidence = "HIGH"
        sample.entry_level_price = round(float(sample.number_theory_level), 2)
        sample.entry_level_is_heuristic = True
        sample.direction_confidence = "MEDIUM" if sample.direction_guess != "UNKNOWN" else "UNKNOWN"
        _append_reason(sample, "ROUND_LEVEL_ENTRY_METADATA_AVAILABLE")
        return

    pip_size = pip_size_for_symbol(cfg.symbol)
    sweep = detect_pre_anchor_sweep_control(
        frames,
        sample.anchor_timestamp,
        lookback_minutes=60,
        min_anchor_delay_minutes=5,
        min_rejection_pips=5.0,
        pip_size=pip_size,
    )
    if sweep is not None:
        direction, entry = sweep
        sample.candidate_source_type = SWEEP_EXTREME
        sample.entry_level_source = SWEEP_EXTREME
        sample.entry_level_confidence = entry.entry_level_confidence
        sample.entry_level_price = entry.entry_price
        sample.entry_level_is_heuristic = True
        sample.direction_guess = direction.direction_guess
        sample.direction_confidence = direction.direction_confidence
        sample.sweep_level = sample.sweep_level if sample.sweep_level is not None else direction.swept_level
        sample.raw_metadata.update(
            {
                "sweep_type": direction.sweep_type,
                "swept_level": direction.swept_level,
                "sweep_extreme": direction.sweep_extreme,
                "sweep_timestamp": direction.sweep_timestamp.isoformat() if direction.sweep_timestamp else "",
                "direction_source_timeframe": direction.direction_source_timeframe,
            }
        )
        _append_reason(sample, "PRE_ANCHOR_SWEEP_EXTREME_CANDIDATE")
        return

    if sample.sweep_level is not None:
        sample.candidate_source_type = SWEPT_LIQUIDITY_LEVEL
        sample.entry_level_source = SWEPT_LIQUIDITY_LEVEL
        sample.entry_level_confidence = "MEDIUM"
        sample.entry_level_price = round(float(sample.sweep_level), 2)
        sample.entry_level_is_heuristic = True
        sample.direction_confidence = "MEDIUM" if sample.direction_guess != "UNKNOWN" else "UNKNOWN"
        _append_reason(sample, "SWEPT_LIQUIDITY_LEVEL_METADATA_AVAILABLE")
        return

    sample.candidate_source_type = UNKNOWN_ENTRY_SOURCE
    sample.entry_level_source = UNKNOWN_ENTRY_SOURCE
    sample.entry_level_confidence = "UNKNOWN"
    sample.entry_level_price = None
    sample.entry_level_is_heuristic = True
    sample.direction_confidence = "UNKNOWN"
    sample.limitations = tuple(dict.fromkeys((*sample.limitations, "NO_DEFENSIBLE_ENTRY_LEVEL_METADATA")))


def _annotate_samples_metadata(
    samples: Iterable[VisualReviewSample],
    frames: Mapping[str, pd.DataFrame],
    cfg: VisualReviewPackConfig,
    volatility_buckets: Mapping[str, str],
) -> None:
    for sample in samples:
        _annotate_sample_metadata(sample, frames, cfg, volatility_buckets)


def _session_reason(ts: pd.Timestamp, range_pips: float, median_range_pips: float) -> str | None:
    try:
        local = ts.to_pydatetime().astimezone(ZoneInfo("Europe/Rome"))
    except Exception:
        local = ts.to_pydatetime()
    open_minutes = {120: "ASIA_OPEN_CONTEXT", 540: "LONDON_OPEN_CONTEXT", 930: "NEW_YORK_OPEN_CONTEXT"}
    minute_of_day = local.hour * 60 + local.minute
    for minute, label in open_minutes.items():
        if abs(minute_of_day - minute) <= 15 and range_pips >= median_range_pips * 1.25:
            return label
    return None


def _candidate_bucket(reason_codes: Sequence[str]) -> str:
    priority = (
        "M15_SWING_HIGH_SWEEP_VISUAL_CANDIDATE",
        "M15_SWING_LOW_SWEEP_VISUAL_CANDIDATE",
        "NUMBER_THEORY_LEVEL_NEAR",
        "LARGE_UPPER_WICK_REVERSAL_VISUAL_CANDIDATE",
        "LARGE_LOWER_WICK_REVERSAL_VISUAL_CANDIDATE",
        "ASIA_OPEN_CONTEXT",
        "LONDON_OPEN_CONTEXT",
        "NEW_YORK_OPEN_CONTEXT",
    )
    for item in priority:
        if item in reason_codes:
            return item
    return reason_codes[0] if reason_codes else "UNKNOWN_VISUAL_CANDIDATE"


def _dedupe_round_robin(candidates: list[VisualReviewSample], max_samples: int) -> list[VisualReviewSample]:
    buckets: dict[str, list[VisualReviewSample]] = {}
    for sample in sorted(candidates, key=lambda item: item.anchor_timestamp, reverse=True):
        buckets.setdefault(_candidate_bucket(sample.candidate_reason_codes), []).append(sample)
    ordered_keys = sorted(buckets, key=lambda key: len(buckets[key]), reverse=True)
    selected: list[VisualReviewSample] = []
    seen_times: list[datetime] = []
    while len(selected) < max_samples and any(buckets.values()):
        made_progress = False
        for key in list(ordered_keys):
            if len(selected) >= max_samples:
                break
            bucket = buckets.get(key) or []
            while bucket:
                sample = bucket.pop(0)
                if all(abs((sample.anchor_timestamp - prior).total_seconds()) >= 3600 for prior in seen_times):
                    selected.append(sample)
                    seen_times.append(sample.anchor_timestamp)
                    made_progress = True
                    break
            buckets[key] = bucket
        if not made_progress:
            for key in ordered_keys:
                bucket = buckets.get(key) or []
                if bucket and len(selected) < max_samples:
                    selected.append(bucket.pop(0))
                    made_progress = True
            if not made_progress:
                break
    return selected[:max_samples]


def _candidate_window_samples(
    cfg: VisualReviewPackConfig,
    frames: dict[str, pd.DataFrame],
    limitations: list[str],
) -> list[VisualReviewSample]:
    if not frames:
        return []
    anchor_tf = "M15" if "M15" in frames else ("M5" if "M5" in frames else "M1")
    frame = frames.get(anchor_tf, pd.DataFrame()).copy()
    if frame.empty:
        limitations.append("NO_ANCHOR_TIMEFRAME_ROWS")
        return []
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time").reset_index(drop=True)
    if len(frame) < 30:
        limitations.append("INSUFFICIENT_CANDLES_FOR_CANDIDATE_WINDOWS")
        return []

    pip_size = pip_size_for_symbol(cfg.symbol)
    lookback = 20 if anchor_tf == "M15" else 30
    frame["prev_swing_high"] = frame["high"].rolling(lookback).max().shift(1)
    frame["prev_swing_low"] = frame["low"].rolling(lookback).min().shift(1)
    frame["range_pips"] = (frame["high"] - frame["low"]) / pip_size
    median_range = float(frame["range_pips"].median() or 1.0)
    candidates: list[VisualReviewSample] = []
    for row in frame.iloc[lookback:].itertuples(index=False):
        ts = pd.Timestamp(getattr(row, "time")).to_pydatetime()
        reasons: list[str] = []
        direction = "UNKNOWN"
        sweep_level: float | None = None
        high = float(getattr(row, "high"))
        low = float(getattr(row, "low"))
        open_ = float(getattr(row, "open"))
        close = float(getattr(row, "close"))
        prev_high = _parse_float(getattr(row, "prev_swing_high"))
        prev_low = _parse_float(getattr(row, "prev_swing_low"))
        range_pips = float(getattr(row, "range_pips"))
        candle_range = max(high - low, pip_size)
        body = abs(close - open_)
        upper_wick = high - max(open_, close)
        lower_wick = min(open_, close) - low

        if prev_high is not None and high > prev_high and close < prev_high:
            reasons.append(f"{anchor_tf}_SWING_HIGH_SWEEP_VISUAL_CANDIDATE")
            direction = "SHORT"
            sweep_level = prev_high
        if prev_low is not None and low < prev_low and close > prev_low:
            reasons.append(f"{anchor_tf}_SWING_LOW_SWEEP_VISUAL_CANDIDATE")
            direction = "LONG"
            sweep_level = prev_low

        near_nt, nt_level, nt_distance = is_near_number_theory_level(
            close,
            symbol=cfg.symbol,
            threshold_pips=cfg.number_theory_threshold_pips,
        )
        if near_nt:
            reasons.append("NUMBER_THEORY_LEVEL_NEAR")

        if range_pips >= median_range * 1.6:
            if upper_wick / candle_range >= 0.55 and body / candle_range <= 0.45:
                reasons.append("LARGE_UPPER_WICK_REVERSAL_VISUAL_CANDIDATE")
                if direction == "UNKNOWN":
                    direction = "SHORT"
            if lower_wick / candle_range >= 0.55 and body / candle_range <= 0.45:
                reasons.append("LARGE_LOWER_WICK_REVERSAL_VISUAL_CANDIDATE")
                if direction == "UNKNOWN":
                    direction = "LONG"

        session = _session_reason(pd.Timestamp(ts), range_pips, median_range)
        if session:
            reasons.append(session)

        if not reasons:
            continue
        if any("SWING_HIGH" in reason or "SWING_LOW" in reason for reason in reasons):
            reaction_guess = "possible old rejection or wick reaction"
        elif "NUMBER_THEORY_LEVEL_NEAR" in reasons:
            reaction_guess = "number theory confluence only; manual validation required"
        else:
            reaction_guess = "unknown reaction zone; manual validation required"
        candidates.append(
            VisualReviewSample(
                sample_id="",
                source_mode="CANDIDATE_WINDOW_MODE",
                symbol=cfg.symbol,
                direction_guess=direction,
                anchor_timestamp=ts,
                anchor_timeframe=anchor_tf,
                window_start=ts - timedelta(minutes=90),
                window_end=ts + timedelta(minutes=180),
                candidate_reason_codes=tuple(dict.fromkeys(reasons)),
                sweep_level=sweep_level,
                number_theory_level=nt_level if near_nt else None,
                distance_to_number_level_pips=nt_distance if near_nt else None,
                reaction_zone_guess=reaction_guess,
                notes=RESEARCH_WARNING,
            )
        )
    if not candidates:
        limitations.append("NO_CANDIDATE_WINDOWS_FOUND")
    return sorted(candidates, key=lambda item: item.anchor_timestamp)


def _slice_frame(frame: pd.DataFrame, start: datetime, end: datetime, max_rows: int) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    df = frame.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    df = df[(df["time"] >= start_ts) & (df["time"] <= end_ts)].copy()
    if len(df) > max_rows:
        step = max(1, math.ceil(len(df) / max_rows))
        df = df.iloc[::step].copy()
    return df.reset_index(drop=True)


def _panel_svg(
    *,
    title: str,
    df: pd.DataFrame,
    y_offset: int,
    width: int,
    height: int,
    sample: VisualReviewSample,
) -> str:
    x0 = 70
    y0 = y_offset + 34
    chart_w = width - 110
    chart_h = height - 58
    lines = [
        f'<text x="{x0}" y="{y_offset + 20}" class="panel-title">{html.escape(title)}</text>',
        f'<rect x="{x0}" y="{y0}" width="{chart_w}" height="{chart_h}" class="plot-bg"/>',
    ]
    if df.empty:
        lines.append(f'<text x="{x0 + 12}" y="{y0 + 42}" class="muted">No candles available for this timeframe/window.</text>')
        return "\n".join(lines)

    for column in ("open", "high", "low", "close"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if df.empty:
        lines.append(f'<text x="{x0 + 12}" y="{y0 + 42}" class="muted">No valid OHLC rows.</text>')
        return "\n".join(lines)

    extra_levels = [
        sample.sweep_level,
        sample.number_theory_level,
        sample.entry_level_price,
        sample.old_entry_price,
        sample.old_stop_loss,
        sample.old_take_profit,
    ]
    prices = list(df["high"]) + list(df["low"]) + [level for level in extra_levels if level is not None]
    p_min = float(min(prices))
    p_max = float(max(prices))
    pad = max((p_max - p_min) * 0.08, 0.5)
    p_min -= pad
    p_max += pad

    def y(price: float) -> float:
        return y0 + chart_h - ((price - p_min) / (p_max - p_min)) * chart_h

    n = len(df)
    candle_step = chart_w / max(n, 1)
    candle_w = max(2.0, min(8.0, candle_step * 0.65))
    for i, row in enumerate(df.itertuples(index=False)):
        x = x0 + (i + 0.5) * candle_step
        o = float(getattr(row, "open"))
        h = float(getattr(row, "high"))
        l = float(getattr(row, "low"))
        c = float(getattr(row, "close"))
        color = "up" if c >= o else "down"
        y_high = y(h)
        y_low = y(l)
        y_open = y(o)
        y_close = y(c)
        body_top = min(y_open, y_close)
        body_h = max(abs(y_close - y_open), 1.0)
        lines.append(f'<line x1="{x:.2f}" y1="{y_high:.2f}" x2="{x:.2f}" y2="{y_low:.2f}" class="{color}-wick"/>')
        lines.append(
            f'<rect x="{x - candle_w / 2:.2f}" y="{body_top:.2f}" width="{candle_w:.2f}" height="{body_h:.2f}" class="{color}-body"/>'
        )

    def add_level(level: float | None, label: str, css_class: str) -> None:
        if level is None:
            return
        yy = y(level)
        lines.append(f'<line x1="{x0}" y1="{yy:.2f}" x2="{x0 + chart_w}" y2="{yy:.2f}" class="{css_class}"/>')
        lines.append(f'<text x="{x0 + chart_w - 4}" y="{yy - 4:.2f}" text-anchor="end" class="level-label">{html.escape(label)} {level:.2f}</text>')

    add_level(sample.sweep_level, "sweep", "sweep-line")
    add_level(sample.number_theory_level, "round", "number-line")
    add_level(sample.entry_level_price, "entry level", "entry-line")
    add_level(sample.old_entry_price, "old entry", "entry-line")
    add_level(sample.old_stop_loss, "old SL", "sl-line")
    add_level(sample.old_take_profit, "old TP", "tp-line")
    lines.append(f'<text x="{x0}" y="{y0 + chart_h + 18}" class="axis-label">{df.iloc[0]["time"]} to {df.iloc[-1]["time"]}</text>')
    lines.append(f'<text x="{x0 + chart_w}" y="{y0 + chart_h + 18}" text-anchor="end" class="axis-label">{p_min:.2f} - {p_max:.2f}</text>')
    return "\n".join(lines)


def _render_svg_chart(sample: VisualReviewSample, frames: dict[str, pd.DataFrame], chart_path: Path) -> None:
    width = 1120
    panel_h = 250
    height = panel_h * 4 + 54
    execution_start = sample.execution_window_start or sample.window_start
    execution_end = sample.execution_window_end or sample.window_end
    h1 = _slice_frame(frames.get("H1", pd.DataFrame()), sample.anchor_timestamp - timedelta(days=3), sample.anchor_timestamp + timedelta(days=1), 96)
    m15 = _slice_frame(frames.get("M15", pd.DataFrame()), sample.anchor_timestamp - timedelta(hours=12), sample.anchor_timestamp + timedelta(hours=6), 96)
    m5 = _slice_frame(frames.get("M5", pd.DataFrame()), execution_start, execution_end, 220)
    m1 = _slice_frame(frames.get("M1", pd.DataFrame()), execution_start, execution_end, 220)
    subtitle = html.escape(" | ".join(sample.candidate_reason_codes))
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<style>",
        "text{font-family:Arial,Helvetica,sans-serif}.title{font-size:21px;font-weight:700;fill:#1f2937}.subtitle{font-size:12px;fill:#4b5563}.panel-title{font-size:15px;font-weight:700;fill:#111827}.muted{font-size:13px;fill:#6b7280}.plot-bg{fill:#f8fafc;stroke:#cbd5e1;stroke-width:1}.up-body{fill:#15803d;stroke:#14532d;stroke-width:.8}.down-body{fill:#b91c1c;stroke:#7f1d1d;stroke-width:.8}.up-wick{stroke:#14532d;stroke-width:1}.down-wick{stroke:#7f1d1d;stroke-width:1}.sweep-line{stroke:#7c3aed;stroke-width:1.6;stroke-dasharray:6 4}.number-line{stroke:#0f766e;stroke-width:1.4;stroke-dasharray:3 4}.entry-line{stroke:#2563eb;stroke-width:1.4}.sl-line{stroke:#dc2626;stroke-width:1.4}.tp-line{stroke:#16a34a;stroke-width:1.4}.level-label,.axis-label{font-size:11px;fill:#374151}",
        "</style>",
        f'<text x="28" y="28" class="title">Adelin v2 visual review sample {html.escape(sample.sample_id)}</text>',
        f'<text x="28" y="48" class="subtitle">{html.escape(RESEARCH_WARNING)}</text>',
        f'<text x="560" y="48" class="subtitle" text-anchor="middle">{subtitle}</text>',
        _panel_svg(title="H1 liquidity context", df=h1, y_offset=62, width=width, height=panel_h, sample=sample),
        _panel_svg(title="M15 liquidity / reaction context", df=m15, y_offset=62 + panel_h, width=width, height=panel_h, sample=sample),
        _panel_svg(title="M5 reaction / execution context", df=m5, y_offset=62 + panel_h * 2, width=width, height=panel_h, sample=sample),
        _panel_svg(title="M1 execution window", df=m1, y_offset=62 + panel_h * 3, width=width, height=panel_h, sample=sample),
        "</svg>",
    ]
    chart_path.write_text("\n".join(svg), encoding="utf-8")


def _metadata_table(sample: VisualReviewSample) -> str:
    rows = {
        "sample_id": sample.sample_id,
        "source_mode": sample.source_mode,
        "symbol": sample.symbol,
        "direction_guess": sample.direction_guess,
        "direction_confidence": sample.direction_confidence,
        "anchor_timestamp": sample.anchor_timestamp.isoformat(),
        "anchor_timeframe": sample.anchor_timeframe,
        "anchor_date": sample.anchor_date,
        "month": sample.month,
        "session": sample.session,
        "candidate_source_type": sample.candidate_source_type,
        "entry_level_source": sample.entry_level_source,
        "entry_level_confidence": sample.entry_level_confidence,
        "entry_level_price": sample.entry_level_price,
        "entry_level_is_heuristic": sample.entry_level_is_heuristic,
        "volatility_bucket": sample.volatility_bucket,
        "execution_data_status": sample.execution_data_status,
        "m1_candles_count": sample.m1_candles_count,
        "m5_candles_count": sample.m5_candles_count,
        "m15_candles_count": sample.m15_candles_count,
        "h1_candles_count": sample.h1_candles_count,
        "execution_window_start": sample.execution_window_start.isoformat() if sample.execution_window_start else "",
        "execution_window_end": sample.execution_window_end.isoformat() if sample.execution_window_end else "",
        "candidate_reason_codes": ", ".join(sample.candidate_reason_codes),
        "sweep_level": sample.sweep_level,
        "number_theory_level": sample.number_theory_level,
        "distance_to_number_level_pips": sample.distance_to_number_level_pips,
        "reaction_zone_guess": sample.reaction_zone_guess,
        "old_trade_id": sample.old_trade_id,
        "old_score": sample.old_score,
        "old_setup_mode": sample.old_setup_mode,
        "old_entry_price": sample.old_entry_price,
        "old_stop_loss": sample.old_stop_loss,
        "old_take_profit": sample.old_take_profit,
    }
    body = "\n".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape('' if value is None else str(value))}</td></tr>"
        for key, value in rows.items()
    )
    return f"<table class=\"metadata\">{body}</table>"


def _execution_warning_html(sample: VisualReviewSample) -> str:
    if sample.execution_data_status == INSUFFICIENT_EXECUTION_DATA:
        return (
            '<p class="warning">INSUFFICIENT EXECUTION DATA - do not label as A+. '
            "Both M1 and M5 execution/reaction data are missing, or M15/H1 context is absent.</p>"
        )
    if sample.m1_candles_count <= 0:
        return '<p class="warning">M1 execution data missing: this sample is weak for Adelin v2 labeling.</p>'
    if sample.m5_candles_count <= 0:
        return (
            '<p class="warning">M5 reaction context missing: this sample is weak for Adelin v2 labeling '
            "and should not be used as A+ evidence unless explicitly reviewed as a weak/debug case.</p>"
        )
    return ""


def _html_shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: Arial, Helvetica, sans-serif; margin: 0; color: #172033; background: #f7f7f4; }}
    header {{ background: #1f2937; color: white; padding: 18px 24px; }}
    main {{ padding: 20px 24px 36px; max-width: 1220px; margin: 0 auto; }}
    a {{ color: #0f766e; }}
    .warning {{ border-left: 5px solid #b91c1c; background: #fff1f2; padding: 12px 14px; margin: 16px 0; font-weight: 700; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin: 18px 0; }}
    .summary div {{ background: white; border: 1px solid #d7d7d2; padding: 10px; }}
    table {{ border-collapse: collapse; width: 100%; background: white; }}
    th, td {{ border: 1px solid #d7d7d2; padding: 8px 9px; text-align: left; vertical-align: top; font-size: 13px; }}
    th {{ background: #eceee8; }}
    .metadata th {{ width: 260px; }}
    .chart {{ width: 100%; border: 1px solid #d7d7d2; background: white; }}
    .small {{ color: #4b5563; font-size: 13px; }}
  </style>
</head>
<body>
  <header><h1>{html.escape(title)}</h1></header>
  <main>{body}</main>
</body>
</html>
"""


def _write_sample_page(sample: VisualReviewSample, output_dir: Path) -> None:
    chart_src = "../" + sample.chart_path if sample.chart_path else ""
    coverage_warning = _execution_warning_html(sample)
    body = f"""
<p class="warning">{html.escape(RESEARCH_WARNING)} No live deployment, Telegram alert, broker call, or order path is involved.</p>
{coverage_warning}
<p><a href="../index.html">Back to index</a></p>
<img class="chart" src="{html.escape(chart_src)}" alt="Chart for {html.escape(sample.sample_id)}">
<h2>Metadata</h2>
{_metadata_table(sample)}
<h2>Manual Label Guidance</h2>
<p>Use the CSV template to judge liquidity quality, reaction-zone validity, target availability, stop feasibility, post-entry reaction, and whether this is A+ reversal, valid reversal, dirty/no-trade, continuation blocked, rare IFVG continuation candidate, or unknown.</p>
"""
    page_path = output_dir / sample.html_path
    page_path.write_text(_html_shell(f"Adelin v2 sample {sample.sample_id}", body), encoding="utf-8")


def _write_index(samples: Sequence[VisualReviewSample], summary: Mapping[str, Any], output_dir: Path) -> None:
    rows = []
    for sample in samples:
        rows.append(
            "<tr>"
            f"<td>{html.escape(sample.sample_id)}</td>"
            f"<td>{html.escape(sample.source_mode)}</td>"
            f"<td>{html.escape(sample.anchor_timestamp.isoformat())}</td>"
            f"<td>{html.escape(sample.direction_guess)}</td>"
            f"<td>{html.escape(sample.candidate_source_type)}</td>"
            f"<td>{html.escape(sample.entry_level_source)}</td>"
            f"<td>{html.escape(sample.session)}</td>"
            f"<td>{html.escape(sample.month)}</td>"
            f"<td>{html.escape(sample.volatility_bucket)}</td>"
            f"<td>{html.escape(sample.execution_data_status)}</td>"
            f"<td>{sample.m1_candles_count}</td>"
            f"<td>{sample.m5_candles_count}</td>"
            f"<td>{sample.m15_candles_count}</td>"
            f"<td>{html.escape(', '.join(sample.candidate_reason_codes))}</td>"
            f"<td><a href=\"{html.escape(sample.chart_path)}\">chart</a></td>"
            f"<td><a href=\"{html.escape(sample.html_path)}\">page</a></td>"
            "<td>Fill liquidity, reaction zone, target, SL, management, confidence, notes</td>"
            "</tr>"
        )
    table_body = "\n".join(rows) if rows else "<tr><td colspan=\"17\">No samples generated.</td></tr>"
    summary_boxes = "\n".join(
        f"<div><strong>{html.escape(key)}</strong><br>{html.escape(str(value))}</div>"
        for key, value in {
            "total_samples": summary.get("total_samples"),
            "date_range_coverage_days": summary.get("date_range_coverage_days"),
            "samples_per_day_max_observed": summary.get("samples_per_day_max_observed"),
            "reviewable_samples": summary.get("reviewable_samples"),
            "reviewable_m1_m5_count": summary.get("reviewable_m1_m5_count"),
            "insufficient_execution_data_count": summary.get("insufficient_execution_data_count"),
            "candidate_source_counts": summary.get("candidate_source_counts"),
            "entry_level_source_counts": summary.get("entry_level_source_counts"),
            "session_distribution": summary.get("session_distribution"),
            "volatility_bucket_distribution": summary.get("volatility_bucket_distribution"),
            "expanded_pack_generation_verdict": summary.get("expanded_pack_generation_verdict"),
            "source_modes_used": ", ".join(summary.get("source_modes_used", [])),
            "candidate_windows_generated": summary.get("candidate_windows_generated"),
            "charts_generated": summary.get("charts_generated"),
            "html_pages_generated": summary.get("html_pages_generated"),
        }.items()
    )
    coverage_warning = ""
    if summary.get("reviewable_m1_m5_count", 0) != summary.get("total_samples", 0):
        coverage_warning = (
            '<p class="warning">Some samples do not have full M1/M5 execution coverage. '
            "Use the execution_data_status column before labeling.</p>"
        )
    body = f"""
<p class="warning">Research-only. {html.escape(RESEARCH_WARNING)} Adelin live remains disabled.</p>
<p class="warning">Not validation. Not live. Not profitability evidence. Expanded candidate windows are sampled for diagnostic replay and manual review only.</p>
{coverage_warning}
<div class="summary">{summary_boxes}</div>
<p><a href="manual_labels_template.csv">manual_labels_template.csv</a> | <a href="README_manual_review.md">README_manual_review.md</a> | <a href="review_pack_summary.json">review_pack_summary.json</a></p>
<table>
  <thead>
    <tr><th>sample_id</th><th>source_mode</th><th>anchor timestamp</th><th>direction guess</th><th>candidate source</th><th>entry source</th><th>session</th><th>month</th><th>volatility</th><th>execution_data_status</th><th>M1 count</th><th>M5 count</th><th>M15 count</th><th>candidate reason codes</th><th>chart</th><th>sample page</th><th>recommended manual labels to fill</th></tr>
  </thead>
  <tbody>{table_body}</tbody>
</table>
"""
    (output_dir / "index.html").write_text(_html_shell("Adelin v2 Visual Review Pack", body), encoding="utf-8")


def _write_manual_template(samples: Sequence[VisualReviewSample], output_dir: Path) -> None:
    with (output_dir / "manual_labels_template.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANUAL_LABEL_COLUMNS)
        writer.writeheader()
        for sample in samples:
            writer.writerow(sample.to_manual_label_row())


def _write_readme(samples: Sequence[VisualReviewSample], summary: Mapping[str, Any], output_dir: Path) -> None:
    lines = [
        "# Adelin v2 Manual Visual Review",
        "",
        f"Status: research-only. {RESEARCH_WARNING}",
        "",
        "## How To Review",
        "",
        "1. Open `index.html`.",
        "2. Inspect each sample page and chart.",
        "3. Fill `manual_labels_template.csv`.",
        "4. Use `YES`, `NO`, `MAYBE`, or `UNKNOWN` for binary/manual context fields.",
        "5. Do not treat any candidate window as a trade alert or live signal.",
        "",
        "## Suggested Label Values",
        "",
        "- setup labels: `A_PLUS_REVERSAL`, `VALID_REVERSAL`, `DIRTY_REVERSAL`, `NO_TRADE`, `CONTINUATION_BLOCKED`, `RARE_IFVG_CONTINUATION_CANDIDATE`, `UNKNOWN`",
        "- liquidity classes: `HTF_EXTERNAL`, `HTF_INTERNAL`, `LTF_EXTERNAL`, `LTF_INTERNAL`, `MULTI_TF_ALIGNED`, `SHALLOW_INTERNAL`, `DEEP_VALID`, `UNKNOWN`",
        "- reaction zones: `FVG`, `IFVG`, `VOLUME_CRACK`, `VOLUME_PROFILE_SWING`, `OLD_REJECTION`, `OLD_RANGE_REJECTION`, `NUMBER_THEORY`, `NONE`, `UNKNOWN`",
        "",
        "## Review Focus",
        "",
        "- Was meaningful liquidity taken?",
        "- Was the liquidity shallow or deep?",
        "- Was a valid pre-existing reaction zone touched?",
        "- Is number theory only confluence, not the whole thesis?",
        "- Is there a target liquidity pool or likely reaction target?",
        "- Would a 20 pip normal / 40 pip max stop fit behind local structure?",
        "- Did price react quickly, accumulate, or engulf against the setup?",
        "- Check `execution_data_status` first. Skip or down-rank samples with insufficient M1/M5 execution data.",
        "- Review `candidate_source_type`, `entry_level_source`, session, month, and volatility bucket before comparing outcomes.",
        "",
        "## Summary",
        "",
        f"- total_samples: `{summary.get('total_samples')}`",
        f"- date_range_coverage_days: `{summary.get('date_range_coverage_days')}`",
        f"- max_samples_per_day: `{summary.get('max_samples_per_day')}`",
        f"- min_sample_spacing_minutes: `{summary.get('min_sample_spacing_minutes')}`",
        f"- candidate_source_counts: `{summary.get('candidate_source_counts')}`",
        f"- entry_level_source_counts: `{summary.get('entry_level_source_counts')}`",
        f"- session_distribution: `{summary.get('session_distribution')}`",
        f"- volatility_bucket_distribution: `{summary.get('volatility_bucket_distribution')}`",
        f"- reviewable_samples: `{summary.get('reviewable_samples')}`",
        f"- reviewable_m1_m5_count: `{summary.get('reviewable_m1_m5_count')}`",
        f"- insufficient_execution_data_count: `{summary.get('insufficient_execution_data_count')}`",
        f"- source_modes_used: `{', '.join(summary.get('source_modes_used', []))}`",
        f"- expanded_pack_generation_verdict: `{summary.get('expanded_pack_generation_verdict')}`",
        f"- expanded_pack_generation_verdict_reason: `{summary.get('expanded_pack_generation_verdict_reason')}`",
        f"- limitations: `{', '.join(summary.get('limitations', []))}`",
        "",
        "## Pre-Registered Decision Criteria",
        "",
        "Decision criteria are recorded before expanded outcome replay. They are descriptive project gates, not proof of edge.",
        "",
        "- continue refinement if a useful source group clears a fast-reaction, runner, or fast-SL-reduction threshold against matched controls.",
        "- stop/archive if useful source groups are flat and fast SL is not better, or if fast SL is materially worse across all useful sources.",
        "- repeat expansion once only for visible but underpowered effects with fewer than 300 generated candidates due to data constraints.",
    ]
    (output_dir / "README_manual_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _assign_paths(samples: Sequence[VisualReviewSample], output_dir: Path) -> None:
    for index, sample in enumerate(samples, start=1):
        sample.sample_id = f"sample_{index:03d}"
        sample.chart_path = f"charts/{sample.sample_id}.svg"
        sample.html_path = f"examples/{sample.sample_id}.html"


def _write_summary(summary: Mapping[str, Any], output_dir: Path) -> None:
    (output_dir / "review_pack_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _count_attr(samples: Sequence[VisualReviewSample], attr: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for sample in samples:
        value = getattr(sample, attr, None)
        counts[str(value) if value not in {None, ""} else "UNKNOWN"] += 1
    return dict(sorted(counts.items()))


def _nested_count(samples: Sequence[VisualReviewSample], outer_attr: str, inner_attr: str) -> dict[str, dict[str, int]]:
    out: dict[str, Counter[str]] = defaultdict(Counter)
    for sample in samples:
        outer = getattr(sample, outer_attr, None) or "UNKNOWN"
        inner = getattr(sample, inner_attr, None) or "UNKNOWN"
        out[str(outer)][str(inner)] += 1
    return {outer: dict(sorted(counter.items())) for outer, counter in sorted(out.items())}


def _month_distribution(samples: Sequence[VisualReviewSample]) -> dict[str, int]:
    return dict(sorted(Counter(sample.month or _month_key(sample.anchor_timestamp) for sample in samples).items()))


def _week_distribution(samples: Sequence[VisualReviewSample]) -> dict[str, int]:
    return dict(sorted(Counter(_week_key(sample.anchor_timestamp) for sample in samples).items()))


def _max_samples_per_day_observed(samples: Sequence[VisualReviewSample]) -> int:
    if not samples:
        return 0
    counts = Counter(_date_key(sample.anchor_timestamp) for sample in samples)
    return max(counts.values())


def _expanded_pack_generation_verdict(
    samples: Sequence[VisualReviewSample],
    cfg: VisualReviewPackConfig,
    *,
    date_range_coverage_days: int,
    local_data_coverage_days: int,
) -> tuple[str, str]:
    if not samples:
        return "INCONCLUSIVE_DATA_QUALITY_LIMITATION", "NO_EXPANDED_CANDIDATE_SAMPLES_GENERATED"
    if local_data_coverage_days < cfg.min_date_range_days:
        return (
            "INCONCLUSIVE_DATA_QUALITY_LIMITATION",
            f"LOCAL_DATA_COVERAGE_{local_data_coverage_days}_DAYS_BELOW_REQUESTED_{cfg.min_date_range_days}",
        )
    if date_range_coverage_days < cfg.min_date_range_days:
        return (
            "INCONCLUSIVE_DATA_QUALITY_LIMITATION",
            f"SAMPLE_DATE_RANGE_{date_range_coverage_days}_DAYS_BELOW_REQUESTED_{cfg.min_date_range_days}",
        )
    if len(samples) < cfg.max_samples:
        return (
            "INCONCLUSIVE_DATA_QUALITY_LIMITATION",
            f"ONLY_{len(samples)}_OF_{cfg.max_samples}_REQUESTED_SAMPLES_GENERATED_UNDER_SPACING_AND_COVERAGE_RULES",
        )
    source_counts = Counter(sample.entry_level_source or UNKNOWN_ENTRY_SOURCE for sample in samples)
    useful_sources = {source: count for source, count in source_counts.items() if source != UNKNOWN_ENTRY_SOURCE and count >= 80}
    if not useful_sources:
        return (
            "INCONCLUSIVE_DATA_QUALITY_LIMITATION",
            "NO_ENTRY_SOURCE_GROUP_REACHED_USEFUL_SOURCE_MIN_CANDIDATE_N_80",
        )
    return (
        "INCONCLUSIVE_DATA_QUALITY_LIMITATION",
        "OBJECTIVE_REPLAY_AND_MATCHED_CONTROLS_REQUIRED_TO_APPLY_PRIMARY_DECISION_CRITERIA",
    )


def create_visual_review_pack(cfg: VisualReviewPackConfig) -> dict[str, Any]:
    started = _utc_now()
    output_dir = _to_path(cfg.output_dir) or DEFAULT_OUTPUT_DIR
    data_dir = _to_path(cfg.data_dir) or Path("data")
    normalized_cfg = VisualReviewPackConfig(
        symbol=cfg.symbol,
        data_dir=data_dir,
        output_dir=output_dir,
        trades_path=cfg.trades_path,
        audit_path=cfg.audit_path,
        from_date=cfg.from_date,
        to_date=cfg.to_date,
        max_samples=max(0, int(cfg.max_samples)),
        min_date_range_days=max(0, int(cfg.min_date_range_days)),
        max_samples_per_day=max(1, int(cfg.max_samples_per_day)),
        min_sample_spacing_minutes=max(0, int(cfg.min_sample_spacing_minutes)),
        target_session_balance=bool(cfg.target_session_balance),
        include_candidate_windows=cfg.include_candidate_windows,
        include_trade_review=cfg.include_trade_review,
        allow_weak_m1_only=cfg.allow_weak_m1_only,
        include_insufficient_execution_debug=cfg.include_insufficient_execution_debug,
        dry_run=True if cfg.dry_run is None else bool(cfg.dry_run),
        number_theory_threshold_pips=cfg.number_theory_threshold_pips,
    )
    limitations: list[str] = ["MATPLOTLIB_UNAVAILABLE_USING_SVG_CHARTS"]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "examples").mkdir(parents=True, exist_ok=True)
    (output_dir / "charts").mkdir(parents=True, exist_ok=True)

    frames = _load_market_frames(normalized_cfg, limitations)
    all_data_start, all_data_end, all_data_coverage_days = _frame_time_bounds(frames)
    data_start, data_end, local_data_coverage_days = _required_execution_time_bounds(frames)
    volatility_buckets = _volatility_bucket_map(frames, limitations)
    samples: list[VisualReviewSample] = []
    trades_loaded = 0
    audit_rows_loaded = 0
    if normalized_cfg.include_trade_review:
        trade_samples, trades_loaded, audit_rows_loaded = _trade_review_samples(normalized_cfg, limitations)
        samples.extend(trade_samples)
    if normalized_cfg.include_candidate_windows and normalized_cfg.max_samples > 0:
        candidate_cfg = VisualReviewPackConfig(
            symbol=normalized_cfg.symbol,
            data_dir=normalized_cfg.data_dir,
            output_dir=normalized_cfg.output_dir,
            trades_path=normalized_cfg.trades_path,
            audit_path=normalized_cfg.audit_path,
            from_date=normalized_cfg.from_date,
            to_date=normalized_cfg.to_date,
            max_samples=normalized_cfg.max_samples,
            min_date_range_days=normalized_cfg.min_date_range_days,
            max_samples_per_day=normalized_cfg.max_samples_per_day,
            min_sample_spacing_minutes=normalized_cfg.min_sample_spacing_minutes,
            target_session_balance=normalized_cfg.target_session_balance,
            include_candidate_windows=True,
            include_trade_review=False,
            allow_weak_m1_only=normalized_cfg.allow_weak_m1_only,
            include_insufficient_execution_debug=normalized_cfg.include_insufficient_execution_debug,
            dry_run=normalized_cfg.dry_run,
            number_theory_threshold_pips=normalized_cfg.number_theory_threshold_pips,
        )
        samples.extend(_candidate_window_samples(candidate_cfg, frames, limitations))

    _annotate_samples_metadata(samples, frames, normalized_cfg, volatility_buckets)
    _set_all_execution_coverage(samples, frames)
    raw_samples_count = len(samples)
    samples, skipped_missing_ltf, skipped_duplicate_spacing, skipped_max_per_day = _prefer_reviewable_samples(
        samples,
        normalized_cfg.max_samples,
        max_samples_per_day=normalized_cfg.max_samples_per_day,
        min_sample_spacing_minutes=normalized_cfg.min_sample_spacing_minutes,
        target_session_balance=normalized_cfg.target_session_balance,
        allow_weak_m1_only=normalized_cfg.allow_weak_m1_only,
        include_insufficient_execution_debug=normalized_cfg.include_insufficient_execution_debug,
    )
    if skipped_missing_ltf:
        limitations.append("INSUFFICIENT_EXECUTION_DATA_SAMPLES_SKIPPED")
    if len(samples) < normalized_cfg.max_samples and raw_samples_count > len(samples):
        limitations.append("PACK_NOT_FILLED_DUE_TO_COVERAGE_OR_REGIME_CONSTRAINTS")
    if local_data_coverage_days and local_data_coverage_days < normalized_cfg.min_date_range_days:
        limitations.append("LOCAL_DATA_COVERAGE_BELOW_REQUESTED_MIN_DATE_RANGE")
    _assign_paths(samples, output_dir)
    charts_generated = 0
    pages_generated = 0
    for sample in samples:
        _render_svg_chart(sample, frames, output_dir / sample.chart_path)
        charts_generated += 1
        _write_sample_page(sample, output_dir)
        pages_generated += 1

    source_modes = sorted({sample.source_mode for sample in samples})
    candidate_count = sum(1 for sample in samples if sample.source_mode == "CANDIDATE_WINDOW_MODE")
    reviewable_m1_m5_count = sum(1 for sample in samples if sample.execution_data_status == REVIEWABLE_M1_M5)
    reviewable_m5_only_count = sum(1 for sample in samples if sample.execution_data_status == REVIEWABLE_M5_ONLY)
    weak_m1_only_count = sum(1 for sample in samples if sample.execution_data_status == WEAK_M1_ONLY)
    insufficient_execution_data_count = sum(
        1 for sample in samples if sample.execution_data_status == INSUFFICIENT_EXECUTION_DATA
    )
    reviewable_samples = reviewable_m1_m5_count + reviewable_m5_only_count + weak_m1_only_count
    date_range_start, date_range_end, date_range_coverage_days = _sample_time_bounds(samples)
    if local_data_coverage_days >= normalized_cfg.min_date_range_days and date_range_coverage_days < normalized_cfg.min_date_range_days and samples:
        limitations.append("GENERATED_SAMPLE_DATE_RANGE_BELOW_REQUESTED_MIN_DATE_RANGE")
    generation_verdict, generation_verdict_reason = _expanded_pack_generation_verdict(
        samples,
        normalized_cfg,
        date_range_coverage_days=date_range_coverage_days,
        local_data_coverage_days=local_data_coverage_days,
    )
    _write_manual_template(samples, output_dir)
    discovered_trades_path = _discover_existing_path(normalized_cfg.trades_path, DEFAULT_TRADES_PATH)
    discovered_audit_path = _discover_existing_path(normalized_cfg.audit_path, DEFAULT_AUDIT_PATH)
    summary = {
        "run_started_at": started.isoformat(),
        "run_finished_at": _utc_now().isoformat(),
        "symbol": normalized_cfg.symbol,
        "output_dir": str(output_dir),
        "data_dir": str(data_dir),
        "dry_run": normalized_cfg.dry_run,
        "max_samples_requested": normalized_cfg.max_samples,
        "min_date_range_days_requested": normalized_cfg.min_date_range_days,
        "max_samples_per_day": normalized_cfg.max_samples_per_day,
        "min_sample_spacing_minutes": normalized_cfg.min_sample_spacing_minutes,
        "target_session_balance": normalized_cfg.target_session_balance,
        "allow_weak_m1_only": normalized_cfg.allow_weak_m1_only,
        "include_insufficient_execution_debug": normalized_cfg.include_insufficient_execution_debug,
        "date_range_start": date_range_start,
        "date_range_end": date_range_end,
        "date_range_coverage_days": date_range_coverage_days,
        "local_data_range_start": data_start.isoformat() if data_start else None,
        "local_data_range_end": data_end.isoformat() if data_end else None,
        "local_data_coverage_days": local_data_coverage_days,
        "all_loaded_data_range_start": all_data_start.isoformat() if all_data_start else None,
        "all_loaded_data_range_end": all_data_end.isoformat() if all_data_end else None,
        "all_loaded_data_coverage_days": all_data_coverage_days,
        "samples_per_day_max_observed": _max_samples_per_day_observed(samples),
        "samples_per_month_distribution": _month_distribution(samples),
        "samples_per_week_distribution": _week_distribution(samples),
        "candidate_source_counts": _count_attr(samples, "candidate_source_type"),
        "entry_level_source_counts": _count_attr(samples, "entry_level_source"),
        "candidate_source_counts_by_month": _nested_count(samples, "month", "candidate_source_type"),
        "session_distribution": _count_attr(samples, "session"),
        "session_distribution_by_month": _nested_count(samples, "month", "session"),
        "volatility_bucket_distribution": _count_attr(samples, "volatility_bucket"),
        "candidate_source_counts_by_volatility_bucket": _nested_count(samples, "volatility_bucket", "candidate_source_type"),
        "session_counts_by_volatility_bucket": _nested_count(samples, "volatility_bucket", "session"),
        "direction_distribution": _count_attr(samples, "direction_guess"),
        "execution_data_status_counts": _count_attr(samples, "execution_data_status"),
        "m1_m5_full_coverage_count": reviewable_m1_m5_count,
        "samples_skipped_missing_execution": skipped_missing_ltf,
        "samples_skipped_duplicate_spacing": skipped_duplicate_spacing,
        "samples_skipped_max_per_day": skipped_max_per_day,
        "samples_skipped_outside_date_range_goal": 0,
        "decision_criteria_preregistered": True,
        "decision_criteria": PRE_REGISTERED_DECISION_CRITERIA,
        "expanded_pack_generation_verdict": generation_verdict,
        "expanded_pack_generation_verdict_reason": generation_verdict_reason,
        "objective_replay_required_before_final_decision": True,
        "source_modes_used": source_modes,
        "trades_path": str(discovered_trades_path) if discovered_trades_path is not None else None,
        "audit_path": str(discovered_audit_path) if discovered_audit_path is not None else None,
        "trades_loaded": trades_loaded,
        "audit_rows_loaded": audit_rows_loaded,
        "candidate_windows_generated": candidate_count,
        "total_samples": len(samples),
        "total_samples_generated": len(samples),
        "raw_samples_considered": raw_samples_count,
        "reviewable_samples": reviewable_samples,
        "reviewable_m1_m5_count": reviewable_m1_m5_count,
        "reviewable_m5_only_count": reviewable_m5_only_count,
        "weak_m1_only_count": weak_m1_only_count,
        "insufficient_execution_data_count": insufficient_execution_data_count,
        "samples_skipped_due_to_missing_ltf_data": skipped_missing_ltf,
        "charts_generated": charts_generated,
        "html_pages_generated": pages_generated,
        "manual_label_template_path": str(output_dir / "manual_labels_template.csv"),
        "index_path": str(output_dir / "index.html"),
        "readme_path": str(output_dir / "README_manual_review.md"),
        "limitations": sorted(set(limitations)),
        "safety": {
            "live_trading_enabled": False,
            "telegram_enabled": False,
            "broker_execution_enabled": False,
            "order_execution_enabled": False,
            "strategy_2_touched": False,
            "strategy_3_touched": False,
            "data_modified": False,
        },
        "warning": RESEARCH_WARNING,
    }
    _write_summary(summary, output_dir)
    _write_index(samples, summary, output_dir)
    _write_readme(samples, summary, output_dir)
    return summary


__all__ = [
    "MANUAL_LABEL_COLUMNS",
    "INSUFFICIENT_EXECUTION_DATA",
    "RESEARCH_WARNING",
    "REVIEWABLE_M1_M5",
    "REVIEWABLE_M5_ONLY",
    "VisualReviewPackConfig",
    "VisualReviewSample",
    "WEAK_M1_ONLY",
    "create_visual_review_pack",
    "is_near_number_theory_level",
    "nearest_number_theory_level",
]
