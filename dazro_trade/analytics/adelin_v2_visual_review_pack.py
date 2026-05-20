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
from dazro_trade.backtest.data_loader import load_csv_timeframes


RESEARCH_WARNING = "Candidate windows are for visual labeling only and are not trade signals."
DEFAULT_OUTPUT_DIR = Path("backtests/reports/adelin_v2_visual_review_pack")
DEFAULT_AUDIT_PATH = Path("backtests/reports/adelin_v2_operational_audit/adelin_v2_trade_audit.csv")
DEFAULT_TRADES_PATH = Path("backtests/reports/final/executed_trades.csv")
SUPPORTED_TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1"]

MANUAL_LABEL_COLUMNS = [
    "sample_id",
    "source_mode",
    "symbol",
    "direction_guess",
    "window_start",
    "window_end",
    "anchor_timestamp",
    "anchor_timeframe",
    "chart_path",
    "html_path",
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
    max_samples: int = 40
    include_candidate_windows: bool = True
    include_trade_review: bool = True
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
                "window_start": self.window_start.isoformat(),
                "window_end": self.window_end.isoformat(),
                "anchor_timestamp": self.anchor_timestamp.isoformat(),
                "anchor_timeframe": self.anchor_timeframe,
                "chart_path": self.chart_path,
                "html_path": self.html_path,
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
    for sample in candidates:
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
    return _dedupe_round_robin(candidates, cfg.max_samples)


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
    add_level(sample.old_entry_price, "old entry", "entry-line")
    add_level(sample.old_stop_loss, "old SL", "sl-line")
    add_level(sample.old_take_profit, "old TP", "tp-line")
    lines.append(f'<text x="{x0}" y="{y0 + chart_h + 18}" class="axis-label">{df.iloc[0]["time"]} to {df.iloc[-1]["time"]}</text>')
    lines.append(f'<text x="{x0 + chart_w}" y="{y0 + chart_h + 18}" text-anchor="end" class="axis-label">{p_min:.2f} - {p_max:.2f}</text>')
    return "\n".join(lines)


def _render_svg_chart(sample: VisualReviewSample, frames: dict[str, pd.DataFrame], chart_path: Path) -> None:
    width = 1120
    panel_h = 250
    height = panel_h * 3 + 54
    h1 = _slice_frame(frames.get("H1", pd.DataFrame()), sample.anchor_timestamp - timedelta(days=3), sample.anchor_timestamp + timedelta(days=1), 96)
    m15 = _slice_frame(frames.get("M15", pd.DataFrame()), sample.anchor_timestamp - timedelta(hours=12), sample.anchor_timestamp + timedelta(hours=6), 96)
    execution_tf = "M1" if "M1" in frames else "M5"
    execution = _slice_frame(
        frames.get(execution_tf, pd.DataFrame()),
        sample.anchor_timestamp - timedelta(minutes=90),
        sample.anchor_timestamp + timedelta(minutes=180),
        220,
    )
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
        _panel_svg(title=f"{execution_tf} execution window", df=execution, y_offset=62 + panel_h * 2, width=width, height=panel_h, sample=sample),
        "</svg>",
    ]
    chart_path.write_text("\n".join(svg), encoding="utf-8")


def _metadata_table(sample: VisualReviewSample) -> str:
    rows = {
        "sample_id": sample.sample_id,
        "source_mode": sample.source_mode,
        "symbol": sample.symbol,
        "direction_guess": sample.direction_guess,
        "anchor_timestamp": sample.anchor_timestamp.isoformat(),
        "anchor_timeframe": sample.anchor_timeframe,
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
    body = f"""
<p class="warning">{html.escape(RESEARCH_WARNING)} No live deployment, Telegram alert, broker call, or order path is involved.</p>
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
            f"<td>{html.escape(', '.join(sample.candidate_reason_codes))}</td>"
            f"<td><a href=\"{html.escape(sample.chart_path)}\">chart</a></td>"
            f"<td><a href=\"{html.escape(sample.html_path)}\">page</a></td>"
            "<td>Fill liquidity, reaction zone, target, SL, management, confidence, notes</td>"
            "</tr>"
        )
    table_body = "\n".join(rows) if rows else "<tr><td colspan=\"8\">No samples generated.</td></tr>"
    summary_boxes = "\n".join(
        f"<div><strong>{html.escape(key)}</strong><br>{html.escape(str(value))}</div>"
        for key, value in {
            "total_samples": summary.get("total_samples"),
            "source_modes_used": ", ".join(summary.get("source_modes_used", [])),
            "candidate_windows_generated": summary.get("candidate_windows_generated"),
            "charts_generated": summary.get("charts_generated"),
            "html_pages_generated": summary.get("html_pages_generated"),
        }.items()
    )
    body = f"""
<p class="warning">Research-only. {html.escape(RESEARCH_WARNING)} Adelin live remains disabled.</p>
<div class="summary">{summary_boxes}</div>
<p><a href="manual_labels_template.csv">manual_labels_template.csv</a> | <a href="README_manual_review.md">README_manual_review.md</a> | <a href="review_pack_summary.json">review_pack_summary.json</a></p>
<table>
  <thead>
    <tr><th>sample_id</th><th>source_mode</th><th>anchor timestamp</th><th>direction guess</th><th>candidate reason codes</th><th>chart</th><th>sample page</th><th>recommended manual labels to fill</th></tr>
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
        "",
        "## Summary",
        "",
        f"- total_samples: `{summary.get('total_samples')}`",
        f"- source_modes_used: `{', '.join(summary.get('source_modes_used', []))}`",
        f"- limitations: `{', '.join(summary.get('limitations', []))}`",
    ]
    (output_dir / "README_manual_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _assign_paths(samples: Sequence[VisualReviewSample], output_dir: Path) -> None:
    for index, sample in enumerate(samples, start=1):
        sample.sample_id = f"sample_{index:03d}"
        sample.chart_path = f"charts/{sample.sample_id}.svg"
        sample.html_path = f"examples/{sample.sample_id}.html"


def _write_summary(summary: Mapping[str, Any], output_dir: Path) -> None:
    (output_dir / "review_pack_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")


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
        include_candidate_windows=cfg.include_candidate_windows,
        include_trade_review=cfg.include_trade_review,
        dry_run=True if cfg.dry_run is None else bool(cfg.dry_run),
        number_theory_threshold_pips=cfg.number_theory_threshold_pips,
    )
    limitations: list[str] = ["MATPLOTLIB_UNAVAILABLE_USING_SVG_CHARTS"]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "examples").mkdir(parents=True, exist_ok=True)
    (output_dir / "charts").mkdir(parents=True, exist_ok=True)

    frames = _load_market_frames(normalized_cfg, limitations)
    samples: list[VisualReviewSample] = []
    trades_loaded = 0
    audit_rows_loaded = 0
    if normalized_cfg.include_trade_review:
        trade_samples, trades_loaded, audit_rows_loaded = _trade_review_samples(normalized_cfg, limitations)
        samples.extend(trade_samples)
    if normalized_cfg.include_candidate_windows and len(samples) < normalized_cfg.max_samples:
        remaining_cfg = VisualReviewPackConfig(
            symbol=normalized_cfg.symbol,
            data_dir=normalized_cfg.data_dir,
            output_dir=normalized_cfg.output_dir,
            trades_path=normalized_cfg.trades_path,
            audit_path=normalized_cfg.audit_path,
            from_date=normalized_cfg.from_date,
            to_date=normalized_cfg.to_date,
            max_samples=normalized_cfg.max_samples - len(samples),
            include_candidate_windows=True,
            include_trade_review=False,
            dry_run=normalized_cfg.dry_run,
            number_theory_threshold_pips=normalized_cfg.number_theory_threshold_pips,
        )
        samples.extend(_candidate_window_samples(remaining_cfg, frames, limitations))

    samples = samples[: normalized_cfg.max_samples]
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
        "source_modes_used": source_modes,
        "trades_path": str(discovered_trades_path) if discovered_trades_path is not None else None,
        "audit_path": str(discovered_audit_path) if discovered_audit_path is not None else None,
        "trades_loaded": trades_loaded,
        "audit_rows_loaded": audit_rows_loaded,
        "candidate_windows_generated": candidate_count,
        "total_samples": len(samples),
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
    "RESEARCH_WARNING",
    "VisualReviewPackConfig",
    "VisualReviewSample",
    "create_visual_review_pack",
    "is_near_number_theory_level",
    "nearest_number_theory_level",
]
