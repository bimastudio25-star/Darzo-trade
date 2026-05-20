from __future__ import annotations

import csv
import html
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from dazro_trade.analysis.strategy_2_manual_sample_labels import MANUAL_LABEL_FIELDS
from dazro_trade.analytics.strategy_2_auto_filter_hypothesis import load_samples, valid_sample_frame
from dazro_trade.backtest.data_loader import load_csv_timeframes


SAFETY = {
    "research_only": True,
    "visual_review_only": True,
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "broker_called": False,
    "order_sent": False,
    "order_send_called": False,
    "signals_generated": False,
    "parameters_optimized": False,
    "machine_learning_used": False,
    "market_data_written": False,
}

REVIEW_SAMPLE_TARGETS = {
    "body_kept": 8,
    "body_removed_by_hyp2": 5,
    "tail_removed_by_hyp2": 8,
    "extreme_tail": 5,
    "low_target_space": 5,
    "dominant_h1_case": 5,
    "missing_reaction_case": 4,
}


@dataclass(frozen=True)
class ReviewPackResult:
    output_dir: Path
    samples_selected: int
    body_samples_count: int
    tail_samples_count: int
    extreme_tail_count: int
    hyp_002_false_positive_body_count: int
    hyp_006_examples_count: int
    hyp_004_examples_count: int
    chart_pngs_created: int
    chart_pngs_failed: int
    index_created: bool
    manual_samples_prefilled_created: bool
    runtime_seconds: float
    paths: dict[str, str]
    selected_sample_types: dict[str, int]
    hypothesis_thresholds: dict[str, float | None]
    missing_features: list[str]

    def to_summary(self) -> dict[str, Any]:
        return {
            "dry_run": True,
            "research_only": True,
            "output_dir": str(self.output_dir),
            "samples_selected": self.samples_selected,
            "body_samples_count": self.body_samples_count,
            "tail_samples_count": self.tail_samples_count,
            "extreme_tail_count": self.extreme_tail_count,
            "hyp_002_false_positive_body_count": self.hyp_002_false_positive_body_count,
            "hyp_006_examples_count": self.hyp_006_examples_count,
            "hyp_004_examples_count": self.hyp_004_examples_count,
            "chart_pngs_created": self.chart_pngs_created,
            "chart_pngs_failed": self.chart_pngs_failed,
            "index_created": self.index_created,
            "manual_samples_prefilled_created": self.manual_samples_prefilled_created,
            "selected_sample_types": self.selected_sample_types,
            "hypothesis_thresholds": self.hypothesis_thresholds,
            "missing_features": self.missing_features,
            "runtime_seconds": self.runtime_seconds,
            "safety": SAFETY,
            "paths": self.paths,
            "verdict_flags": [
                "MANUAL_VISUAL_REVIEW_PACK_BUILT",
                "AUTO_FILTER_HYPOTHESIS_REVIEW_PACK_CREATED",
                "PREFILLED_MANUAL_LABEL_CSV_CREATED",
                "STRATEGY_2_REMAINS_RESEARCH_ONLY",
                "NO_LIVE_DEPLOYMENT_DECISION",
            ],
        }


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) else out


def _fmt(value: Any, *, digits: int = 4) -> str:
    number = _to_float(value)
    if number is not None:
        return f"{number:.{digits}f}".rstrip("0").rstrip(".")
    if value is None:
        return ""
    text = str(value)
    return "" if text.lower() == "nan" else text


def _ts(value: Any) -> pd.Timestamp | None:
    if value is None or str(value).strip() == "":
        return None
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _html(value: Any) -> str:
    return html.escape(_fmt(value))


def _truthy(value: Any) -> bool:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([pd.NA] * len(frame), index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _threshold_from_hypotheses_file(hypotheses_path: Path, hypothesis_id: str) -> float | None:
    if not hypotheses_path.exists():
        return None
    try:
        hypotheses = pd.read_csv(hypotheses_path)
    except Exception:
        return None
    if "hypothesis_id" not in hypotheses.columns or "supporting_stats" not in hypotheses.columns:
        return None
    row = hypotheses[hypotheses["hypothesis_id"].astype(str).eq(hypothesis_id)]
    if row.empty:
        return None
    try:
        stats = json.loads(str(row.iloc[0]["supporting_stats"]))
    except json.JSONDecodeError:
        return None
    return _to_float(stats.get("threshold"))


def hypothesis_thresholds(valid_samples: pd.DataFrame, hypotheses_dir: str | Path | None = None) -> dict[str, float | None]:
    hypotheses_path = Path(hypotheses_dir or "") / "filter_hypotheses.csv" if hypotheses_dir else Path("__missing__")
    ratio_threshold = _threshold_from_hypotheses_file(hypotheses_path, "HYPOTHESIS_002")
    target_threshold = _threshold_from_hypotheses_file(hypotheses_path, "HYPOTHESIS_006")

    if ratio_threshold is None:
        ratio_series = _numeric(valid_samples, "expansion_to_manipulation_ratio").dropna()
        ratio_threshold = round(float(ratio_series.quantile(0.25)), 4) if not ratio_series.empty else None
    if target_threshold is None:
        target_series = _numeric(valid_samples, "target_space_after_sweep").dropna()
        target_threshold = round(float(target_series.quantile(0.25)), 4) if not target_series.empty else None

    return {"hyp_002_ratio_p25": ratio_threshold, "hyp_006_target_space_p25": target_threshold}


def annotate_hypothesis_flags(valid_samples: pd.DataFrame, thresholds: dict[str, float | None]) -> pd.DataFrame:
    out = valid_samples.copy()
    ratio = _numeric(out, "expansion_to_manipulation_ratio")
    target_space = _numeric(out, "target_space_after_sweep")
    manipulation = _numeric(out, "manipulation_depth_usd")

    ratio_threshold = thresholds.get("hyp_002_ratio_p25")
    target_threshold = thresholds.get("hyp_006_target_space_p25")

    out["hyp_002_removed"] = ratio <= ratio_threshold if ratio_threshold is not None else False
    out["hyp_006_removed"] = target_space <= target_threshold if target_threshold is not None else False
    out["hyp_004_removed"] = out.get("h1_reference_type", pd.Series("", index=out.index)).astype(str).str.lower().eq("dominant_h1")
    if "reaction_confirmed_bool" in out.columns:
        out["hyp_005_removed"] = ~out["reaction_confirmed_bool"].fillna(False)
    else:
        out["hyp_005_removed"] = False

    out["is_body_review"] = manipulation <= 12.0
    out["is_tail_review"] = manipulation > 12.0
    out["is_extreme_tail_review"] = manipulation > 20.0
    return out


def select_review_samples(valid_samples: pd.DataFrame, *, max_samples: int = 40) -> pd.DataFrame:
    if valid_samples.empty:
        return valid_samples.copy()

    selected_indices: list[Any] = []
    sample_types: dict[Any, str] = {}

    def take(sample_type: str, frame: pd.DataFrame, count: int, sort_columns: list[str], ascending: list[bool]) -> None:
        nonlocal selected_indices
        if count <= 0 or frame.empty or len(selected_indices) >= max_samples:
            return
        candidates = frame[~frame.index.isin(selected_indices)].copy()
        if candidates.empty:
            return
        available_sort = [column for column in sort_columns if column in candidates.columns]
        if available_sort:
            candidates = candidates.sort_values(available_sort, ascending=ascending[: len(available_sort)], na_position="last")
        for idx in candidates.index.tolist():
            if len(selected_indices) >= max_samples:
                break
            selected_indices.append(idx)
            sample_types[idx] = sample_type
            if sum(1 for value in sample_types.values() if value == sample_type) >= count:
                break

    manipulation = _numeric(valid_samples, "manipulation_depth_usd")
    ratio = _numeric(valid_samples, "expansion_to_manipulation_ratio")
    target_space = _numeric(valid_samples, "target_space_after_sweep")

    take(
        "body_kept",
        valid_samples[(manipulation <= 8.0) & ~valid_samples["hyp_002_removed"].fillna(False)],
        REVIEW_SAMPLE_TARGETS["body_kept"],
        ["expansion_to_manipulation_ratio", "manipulation_depth_usd"],
        [False, True],
    )
    take(
        "body_removed_by_hyp2",
        valid_samples[(manipulation <= 12.0) & valid_samples["hyp_002_removed"].fillna(False)],
        REVIEW_SAMPLE_TARGETS["body_removed_by_hyp2"],
        ["expansion_to_manipulation_ratio", "manipulation_depth_usd"],
        [True, True],
    )
    take(
        "extreme_tail",
        valid_samples[manipulation > 20.0],
        REVIEW_SAMPLE_TARGETS["extreme_tail"],
        ["manipulation_depth_usd"],
        [False],
    )
    take(
        "tail_removed_by_hyp2",
        valid_samples[(manipulation > 12.0) & valid_samples["hyp_002_removed"].fillna(False)],
        REVIEW_SAMPLE_TARGETS["tail_removed_by_hyp2"],
        ["manipulation_depth_usd"],
        [False],
    )
    take(
        "low_target_space",
        valid_samples[valid_samples["hyp_006_removed"].fillna(False)],
        REVIEW_SAMPLE_TARGETS["low_target_space"],
        ["target_space_after_sweep", "manipulation_depth_usd"],
        [True, False],
    )
    take(
        "dominant_h1_case",
        valid_samples[valid_samples["hyp_004_removed"].fillna(False)],
        REVIEW_SAMPLE_TARGETS["dominant_h1_case"],
        ["manipulation_depth_usd", "expansion_to_manipulation_ratio"],
        [False, True],
    )
    take(
        "missing_reaction_case",
        valid_samples[valid_samples["hyp_005_removed"].fillna(False)],
        REVIEW_SAMPLE_TARGETS["missing_reaction_case"],
        ["manipulation_depth_usd"],
        [False],
    )

    if len(selected_indices) < max_samples:
        remainder = valid_samples[~valid_samples.index.isin(selected_indices)].copy()
        remainder["_body_priority"] = (_numeric(remainder, "manipulation_depth_usd") <= 12.0).astype(int)
        remainder["_ratio_rank"] = ratio.reindex(remainder.index)
        remainder["_target_space_rank"] = target_space.reindex(remainder.index)
        remainder = remainder.sort_values(["_body_priority", "_ratio_rank", "_target_space_rank"], ascending=[False, True, True], na_position="last")
        for idx in remainder.index.tolist():
            if len(selected_indices) >= max_samples:
                break
            selected_indices.append(idx)
            sample_types[idx] = "diversity_fill"

    selected = valid_samples.loc[selected_indices].copy()
    selected.insert(0, "review_id", [f"S2_REVIEW_{i:03d}" for i in range(1, len(selected) + 1)])
    selected.insert(1, "sample_type", [sample_types[idx] for idx in selected_indices])
    selected["ratio_for_review"] = ratio.reindex(selected.index)
    selected["target_space_for_review"] = target_space.reindex(selected.index)
    return selected.reset_index(drop=True)


def load_market_context(symbol: str, data_dir: str | Path) -> pd.DataFrame:
    frames = load_csv_timeframes(symbol, ["M5"], data_dir=str(data_dir))
    return frames.get("M5", pd.DataFrame())


def _chart_window(sample: pd.Series) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    h1_time = _ts(sample.get("h1_context_timestamp"))
    sweep_time = _ts(sample.get("h1_sweep_timestamp"))
    distribution_time = _ts(sample.get("distribution_timestamp"))
    anchor = h1_time or sweep_time or distribution_time
    if anchor is None:
        return None, None
    latest = max([ts for ts in (h1_time, sweep_time, distribution_time) if ts is not None], default=anchor)
    return anchor - pd.Timedelta(hours=2), latest + pd.Timedelta(hours=4)


def create_context_chart(sample: pd.Series, m5: pd.DataFrame, chart_path: str | Path) -> bool:
    if m5.empty or "time" not in m5.columns:
        return False
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return _create_pillow_context_chart(sample, m5, chart_path)

    start, end = _chart_window(sample)
    if start is None or end is None:
        return False

    frame = m5[(m5["time"] >= start) & (m5["time"] <= end)].copy()
    if frame.empty:
        return False

    chart_path = Path(chart_path)
    chart_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(13, 6))
    ax.vlines(frame["time"], frame["low"], frame["high"], color="#8a8a8a", alpha=0.35, linewidth=0.8)
    ax.plot(frame["time"], frame["close"], color="#222222", linewidth=1.2, label="M5 close")

    line_specs = [
        ("H1 high", sample.get("h1_reference_high"), "#2563eb", "--"),
        ("H1 low", sample.get("h1_reference_low"), "#2563eb", "--"),
        ("Liquidity", sample.get("h1_liquidity_level"), "#dc2626", "-"),
        ("M15 x:45 high", sample.get("m15_x45_high"), "#16a34a", ":"),
        ("M15 x:45 low", sample.get("m15_x45_low"), "#16a34a", ":"),
    ]
    for label, value, color, style in line_specs:
        price = _to_float(value)
        if price is not None:
            ax.axhline(price, color=color, linestyle=style, linewidth=1.0, alpha=0.8, label=f"{label} {_fmt(price, digits=2)}")

    vertical_specs = [
        ("H1 context", sample.get("h1_context_timestamp"), "#6b7280"),
        ("Sweep", sample.get("h1_sweep_timestamp"), "#dc2626"),
        ("Reaction", sample.get("reaction_timestamp"), "#9333ea"),
        ("Distribution", sample.get("distribution_timestamp"), "#059669"),
    ]
    for label, value, color in vertical_specs:
        timestamp = _ts(value)
        if timestamp is not None:
            ax.axvline(timestamp, color=color, linestyle="-", linewidth=0.9, alpha=0.55)
            ax.text(timestamp, ax.get_ylim()[1], label, rotation=90, va="top", ha="right", fontsize=8, color=color)

    title = (
        f"{sample.get('review_id', '')} | {sample.get('direction', '')} | {sample.get('sample_type', '')} | "
        f"manip {_fmt(sample.get('manipulation_depth_usd'))} USD | "
        f"ratio {_fmt(sample.get('expansion_to_manipulation_ratio'))} | "
        f"target {_fmt(sample.get('target_space_after_sweep'))}"
    )
    ax.set_title(title)
    ax.set_ylabel("XAUUSD price")
    ax.grid(True, alpha=0.2)
    ax.legend(loc="best", fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(chart_path, dpi=130)
    plt.close(fig)
    return True


def _create_pillow_context_chart(sample: pd.Series, m5: pd.DataFrame, chart_path: str | Path) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return False

    start, end = _chart_window(sample)
    if start is None or end is None:
        return False

    frame = m5[(m5["time"] >= start) & (m5["time"] <= end)].copy()
    if frame.empty:
        return False

    chart_path = Path(chart_path)
    chart_path.parent.mkdir(parents=True, exist_ok=True)

    width, height = 1400, 720
    left, right, top, bottom = 82, 260, 64, 70
    plot_w = width - left - right
    plot_h = height - top - bottom
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    prices = pd.concat([frame["high"], frame["low"], frame["close"]], ignore_index=True)
    for value in [
        sample.get("h1_reference_high"),
        sample.get("h1_reference_low"),
        sample.get("h1_liquidity_level"),
        sample.get("m15_x45_high"),
        sample.get("m15_x45_low"),
    ]:
        number = _to_float(value)
        if number is not None:
            prices = pd.concat([prices, pd.Series([number])], ignore_index=True)
    price_min = float(pd.to_numeric(prices, errors="coerce").min())
    price_max = float(pd.to_numeric(prices, errors="coerce").max())
    if price_max <= price_min:
        return False
    pad = max((price_max - price_min) * 0.08, 0.25)
    price_min -= pad
    price_max += pad

    start_ns = int(start.value)
    end_ns = int(end.value)
    time_span = max(end_ns - start_ns, 1)

    def x_at(timestamp: Any) -> int | None:
        ts = _ts(timestamp)
        if ts is None:
            return None
        return int(left + ((int(ts.value) - start_ns) / time_span) * plot_w)

    def y_at(price: Any) -> int | None:
        number = _to_float(price)
        if number is None:
            return None
        return int(top + ((price_max - number) / (price_max - price_min)) * plot_h)

    draw.rectangle([left, top, left + plot_w, top + plot_h], outline="#d1d5db", width=1)
    for i in range(6):
        y = top + int((plot_h / 5) * i)
        price = price_max - ((price_max - price_min) / 5) * i
        draw.line([left, y, left + plot_w, y], fill="#f3f4f6", width=1)
        draw.text((8, y - 6), _fmt(price, digits=2), fill="#374151", font=font)

    close_points: list[tuple[int, int]] = []
    for _, row in frame.iterrows():
        x = x_at(row["time"])
        y_high = y_at(row["high"])
        y_low = y_at(row["low"])
        y_close = y_at(row["close"])
        if x is None or y_high is None or y_low is None or y_close is None:
            continue
        draw.line([x, y_high, x, y_low], fill="#c4c4c4", width=1)
        close_points.append((x, y_close))
    if len(close_points) >= 2:
        draw.line(close_points, fill="#111827", width=2)

    line_specs = [
        ("H1 high", sample.get("h1_reference_high"), "#2563eb"),
        ("H1 low", sample.get("h1_reference_low"), "#2563eb"),
        ("Liquidity", sample.get("h1_liquidity_level"), "#dc2626"),
        ("M15 x45 high", sample.get("m15_x45_high"), "#16a34a"),
        ("M15 x45 low", sample.get("m15_x45_low"), "#16a34a"),
    ]
    legend_y = top
    for label, value, color in line_specs:
        y = y_at(value)
        if y is None:
            continue
        draw.line([left, y, left + plot_w, y], fill=color, width=2)
        draw.text((left + plot_w + 12, legend_y), f"{label}: {_fmt(value, digits=2)}", fill=color, font=font)
        legend_y += 18

    event_specs = [
        ("H1", sample.get("h1_context_timestamp"), "#6b7280"),
        ("Sweep", sample.get("h1_sweep_timestamp"), "#dc2626"),
        ("React", sample.get("reaction_timestamp"), "#9333ea"),
        ("Dist", sample.get("distribution_timestamp"), "#059669"),
    ]
    event_y = top + plot_h + 8
    for label, value, color in event_specs:
        x = x_at(value)
        if x is None:
            continue
        draw.line([x, top, x, top + plot_h], fill=color, width=1)
        draw.text((x - 14, event_y), label, fill=color, font=font)

    title = (
        f"{sample.get('review_id', '')} | {sample.get('direction', '')} | {sample.get('sample_type', '')} | "
        f"manip {_fmt(sample.get('manipulation_depth_usd'))} USD | "
        f"ratio {_fmt(sample.get('expansion_to_manipulation_ratio'))} | "
        f"target {_fmt(sample.get('target_space_after_sweep'))}"
    )
    draw.text((left, 22), title, fill="#111827", font=font)
    draw.text((left, height - 30), "Pillow fallback chart: M5 high-low bars, close line, H1/M15 levels, and event timestamps.", fill="#4b5563", font=font)
    image.save(chart_path)
    return True


def prefilled_manual_row(sample: pd.Series, *, chart_ref: str) -> dict[str, str]:
    row = {field: "" for field in MANUAL_LABEL_FIELDS}
    h1_time = _ts(sample.get("h1_context_timestamp"))
    direction = str(sample.get("direction", "")).strip().lower()
    opposite_taken = sample.get("opposite_x45_taken_first")
    if opposite_taken in (None, "") and sample.get("opposite_m15_x45_taken_timestamp"):
        opposite_taken = "true"

    notes = (
        f"auto_sample_id={sample.get('sample_id', '')}; "
        f"sample_type={sample.get('sample_type', '')}; "
        f"HYP_002_removed={bool(sample.get('hyp_002_removed', False))}; "
        f"HYP_006_removed={bool(sample.get('hyp_006_removed', False))}; "
        f"HYP_004_removed={bool(sample.get('hyp_004_removed', False))}; "
        f"HYP_005_removed={bool(sample.get('hyp_005_removed', False))}"
    )

    values = {
        "manual_sample_id": sample.get("review_id", ""),
        "source_type": "replay_label",
        "screenshot_ref": chart_ref,
        "notes": notes,
        "symbol": sample.get("symbol", "XAUUSD"),
        "date": h1_time.date().isoformat() if h1_time is not None else "",
        "h1_timestamp": h1_time.isoformat() if h1_time is not None else "",
        "timezone": "UTC",
        "session": sample.get("session", ""),
        "direction": direction,
        "h1_reference_type": sample.get("h1_reference_type", ""),
        "h1_reference_timestamp": sample.get("h1_reference_timestamp", ""),
        "h1_high": _fmt(sample.get("h1_reference_high")),
        "h1_low": _fmt(sample.get("h1_reference_low")),
        "liquidity_level": _fmt(sample.get("h1_liquidity_level")),
        "h1_range": _fmt(sample.get("h1_reference_range")),
        "m15_x45_timestamp": sample.get("m15_x45_timestamp", ""),
        "m15_x45_high": _fmt(sample.get("m15_x45_high")),
        "m15_x45_low": _fmt(sample.get("m15_x45_low")),
        "m15_x45_sequence_valid": str(sample.get("m15_x45_sequence_valid", "")).lower(),
        "opposite_x45_taken_first": str(opposite_taken).lower() if opposite_taken not in (None, "") else "",
        "sequence_notes": sample.get("m15_x45_sequence_reason", ""),
        "manipulation_depth_pips": _fmt(sample.get("manipulation_depth_pips")),
        "manipulation_depth_usd": _fmt(sample.get("manipulation_depth_usd")),
        "expansion_pips": _fmt(sample.get("distribution_distance_pips") or sample.get("expansion_pips")),
        "expansion_usd": _fmt(sample.get("distribution_distance_usd") or sample.get("expansion_usd")),
        "setup_model": sample.get("candle_development_model", ""),
        "reviewer_notes": "Fill user_grade, reaction_quality, candle_anatomy_quality, avoid_reason, user_reasoning, and manual_trade_taken.",
    }
    for key, value in values.items():
        if key in row:
            row[key] = str(value or "")
    return row


def _metadata_rows(sample: pd.Series) -> str:
    fields = [
        "review_id",
        "sample_id",
        "sample_type",
        "symbol",
        "direction",
        "h1_context_timestamp",
        "h1_reference_type",
        "h1_reference_timestamp",
        "h1_reference_high",
        "h1_reference_low",
        "h1_liquidity_level",
        "m15_x45_timestamp",
        "m15_x45_high",
        "m15_x45_low",
        "m15_x45_sequence_valid",
        "manipulation_depth_usd",
        "manipulation_depth_pips",
        "distribution_distance_usd",
        "expansion_to_manipulation_ratio",
        "target_space_after_sweep",
        "reaction_confirmed",
        "reaction_latency_candles",
        "sample_status",
        "sample_reason_codes",
        "hyp_002_removed",
        "hyp_006_removed",
        "hyp_004_removed",
        "hyp_005_removed",
    ]
    rows = []
    for field in fields:
        rows.append(f"<tr><th>{html.escape(field)}</th><td>{_html(sample.get(field, ''))}</td></tr>")
    return "\n".join(rows)


def _sample_page(sample: pd.Series, *, chart_rel: str, row_preview: dict[str, str]) -> str:
    preview_rows = "\n".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>" for k, v in row_preview.items())
    image = f'<img src="../{html.escape(chart_rel)}" alt="{_html(sample.get("review_id"))} chart" />' if chart_rel else "<p>Chart PNG was not available for this sample.</p>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{_html(sample.get("review_id"))} Strategy 2 Review</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2937; }}
    img {{ max-width: 100%; border: 1px solid #d1d5db; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border: 1px solid #d1d5db; padding: 6px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; width: 260px; }}
    .note {{ background: #fff7ed; border: 1px solid #fed7aa; padding: 12px; }}
  </style>
</head>
<body>
  <p><a href="../index.html">Back to index</a></p>
  <h1>{_html(sample.get("review_id"))}</h1>
  <div class="note">
    Fill only the manual label fields later: user_grade, reaction_quality, candle_anatomy_quality,
    avoid_reason, user_reasoning, and manual_trade_taken. This page is review-only and creates no signals.
  </div>
  {image}
  <h2>Metadata</h2>
  <table>{_metadata_rows(sample)}</table>
  <h2>Prefilled CSV Row Preview</h2>
  <table>{preview_rows}</table>
</body>
</html>
"""


def _index_page(selected: pd.DataFrame) -> str:
    rows = []
    for _, sample in selected.iterrows():
        review_id = sample.get("review_id", "")
        chart_link = f"charts/{review_id}_context.png"
        page_link = f"samples/{review_id}.html"
        rows.append(
            "<tr>"
            f"<td>{_html(review_id)}</td>"
            f"<td>{_html(sample.get('h1_context_timestamp'))}</td>"
            f"<td>{_html(sample.get('direction'))}</td>"
            f"<td>{_html(sample.get('manipulation_depth_usd'))}</td>"
            f"<td>{_html(sample.get('manipulation_depth_pips'))}</td>"
            f"<td>{_html(sample.get('distribution_distance_usd') or sample.get('expansion_usd'))}</td>"
            f"<td>{_html(sample.get('expansion_to_manipulation_ratio'))}</td>"
            f"<td>{_html(sample.get('target_space_after_sweep'))}</td>"
            f"<td>{_html(sample.get('h1_reference_type'))}</td>"
            f"<td>{_html(sample.get('sample_type'))}</td>"
            f"<td><a href=\"{html.escape(chart_link)}\">chart</a></td>"
            f"<td><a href=\"{html.escape(page_link)}\">page</a></td>"
            "<td>user_grade, reaction_quality, candle_anatomy_quality, avoid_reason, user_reasoning</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Strategy 2 Manual Visual Review Pack</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2937; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 6px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; position: sticky; top: 0; }}
    .note {{ background: #eef2ff; border: 1px solid #c7d2fe; padding: 12px; margin-bottom: 16px; }}
  </style>
</head>
<body>
  <h1>Strategy 2 Manual Visual Review Pack</h1>
  <div class="note">
    Research-only visual pack for reviewing auto-filter hypothesis samples. It does not create signals,
    orders, alerts, or runtime strategy behavior.
  </div>
  <table>
    <thead>
      <tr>
        <th>review_id</th><th>timestamp</th><th>direction</th><th>manipulation_usd</th>
        <th>manipulation_pips</th><th>expansion_usd</th><th>expansion/manipulation</th>
        <th>target_space</th><th>h1_reference_type</th><th>sample_type</th>
        <th>chart</th><th>sample page</th><th>fields to fill</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
</body>
</html>
"""


def _readme_text(result: ReviewPackResult) -> str:
    return f"""# Strategy 2 Manual Visual Review Pack

This folder is a research-only chart review pack for Strategy 2 auto-filter hypothesis validation.

Open `index.html`, inspect each sample chart/page, then fill `manual_samples_prefilled.csv`.

Fill these fields first:
- user_grade
- reaction_quality
- candle_anatomy_quality
- avoid_reason
- user_reasoning
- manual_trade_taken

Selected samples: {result.samples_selected}
Chart PNGs created: {result.chart_pngs_created}
Chart PNGs failed: {result.chart_pngs_failed}

Safety:
- Strategy 3 untouched.
- `data/XAUUSD/*.csv` is read-only input.
- No live trading.
- No Telegram.
- No broker execution.
- No orders.
- No signal generation.
"""


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANUAL_LABEL_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def create_review_pack(
    *,
    symbol: str,
    data_dir: str | Path,
    auto_samples_path: str | Path,
    hypotheses_dir: str | Path,
    output_dir: str | Path,
    max_samples: int = 40,
    pip_factor: float = 10.0,
    dry_run: bool = True,
) -> ReviewPackResult:
    start = time.perf_counter()
    output = Path(output_dir)
    samples_dir = output / "samples"
    charts_dir = output / "charts"
    samples_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)

    all_samples, missing_features = load_samples(auto_samples_path, pip_factor=pip_factor)
    valid = valid_sample_frame(all_samples)
    thresholds = hypothesis_thresholds(valid, hypotheses_dir)
    annotated = annotate_hypothesis_flags(valid, thresholds)
    selected = select_review_samples(annotated, max_samples=max_samples)

    m5 = load_market_context(symbol, data_dir)
    prefilled_rows: list[dict[str, str]] = []
    chart_success = 0
    chart_failure = 0

    for _, sample in selected.iterrows():
        review_id = str(sample["review_id"])
        chart_rel = f"charts/{review_id}_context.png"
        chart_path = output / chart_rel
        chart_created = create_context_chart(sample, m5, chart_path)
        if chart_created:
            chart_success += 1
        else:
            chart_failure += 1
            chart_rel = ""

        row = prefilled_manual_row(sample, chart_ref=chart_rel)
        prefilled_rows.append(row)
        sample_page = _sample_page(sample, chart_rel=chart_rel, row_preview=row)
        (samples_dir / f"{review_id}.html").write_text(sample_page, encoding="utf-8")

    index_path = output / "index.html"
    prefilled_path = output / "manual_samples_prefilled.csv"
    summary_path = output / "review_pack_summary.json"
    readme_path = output / "README_review_pack.md"

    index_path.write_text(_index_page(selected), encoding="utf-8")
    _write_csv(prefilled_path, prefilled_rows)

    manipulation = _numeric(selected, "manipulation_depth_usd")
    sample_type_counts = selected["sample_type"].value_counts().to_dict() if "sample_type" in selected.columns else {}
    result = ReviewPackResult(
        output_dir=output,
        samples_selected=int(len(selected)),
        body_samples_count=int((manipulation <= 12.0).sum()),
        tail_samples_count=int((manipulation > 12.0).sum()),
        extreme_tail_count=int((manipulation > 20.0).sum()),
        hyp_002_false_positive_body_count=int(((manipulation <= 12.0) & selected["hyp_002_removed"].fillna(False)).sum()),
        hyp_006_examples_count=int(selected["hyp_006_removed"].fillna(False).sum()),
        hyp_004_examples_count=int(selected["hyp_004_removed"].fillna(False).sum()),
        chart_pngs_created=chart_success,
        chart_pngs_failed=chart_failure,
        index_created=index_path.exists(),
        manual_samples_prefilled_created=prefilled_path.exists(),
        runtime_seconds=round(time.perf_counter() - start, 4),
        paths={
            "index": str(index_path),
            "manual_samples_prefilled": str(prefilled_path),
            "summary": str(summary_path),
            "readme": str(readme_path),
            "samples_dir": str(samples_dir),
            "charts_dir": str(charts_dir),
        },
        selected_sample_types={str(k): int(v) for k, v in sample_type_counts.items()},
        hypothesis_thresholds=thresholds,
        missing_features=missing_features,
    )

    summary_path.write_text(json.dumps(result.to_summary(), indent=2, sort_keys=True), encoding="utf-8")
    readme_path.write_text(_readme_text(result), encoding="utf-8")
    return result
