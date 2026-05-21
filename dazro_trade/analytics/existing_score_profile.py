"""Profile the existing Adelin score using already generated reports.

This module is intentionally read-only: it consumes exported profiling
CSVs/JSONs and writes an offline report. It does not touch strategy
execution, live filters, or the backtest runner.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, median, pstdev
from typing import Any, Iterable, Sequence


SCORE_BUCKETS: tuple[tuple[str, float | None, float | None], ...] = (
    ("UNKNOWN", None, None),
    ("<60", float("-inf"), 60.0),
    ("60-64", 60.0, 65.0),
    ("65-69", 65.0, 70.0),
    ("70-74", 70.0, 75.0),
    ("75-79", 75.0, 80.0),
    ("80-84", 80.0, 85.0),
    ("85-89", 85.0, 90.0),
    ("90+", 90.0, float("inf")),
)

DISTANCE_BUCKETS: tuple[tuple[str, float | None, float | None], ...] = (
    ("UNKNOWN", None, None),
    ("0-10 pips", 0.0, 10.0),
    ("10-20 pips", 10.0, 20.0),
    ("20-40 pips", 20.0, 40.0),
    ("40-80 pips", 40.0, 80.0),
    ("80-150 pips", 80.0, 150.0),
    ("150+ pips", 150.0, float("inf")),
)


@dataclass(frozen=True)
class ScoreProfileRecord:
    signal_timestamp: datetime | None
    score: float | None
    r_multiple: float
    setup_mode: str | None = None
    continuation: bool | None = None
    rejection: bool | None = None
    swept_high: bool | None = None
    swept_low: bool | None = None
    reclaim_after_sweep: bool | None = None
    fvg_created: bool | None = None
    ifvg_created: bool | None = None
    distance_to_liquidity_pips: float | None = None
    liquidity_timeframe: str | None = None
    symbol: str | None = None
    side: str | None = None


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
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
    if math.isnan(out):
        return None
    return out


def _parse_bool(value: Any) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text in {"nan", "none", "null"}:
        return None
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def score_bucket(score: float | int | None) -> str:
    if score is None:
        return "UNKNOWN"
    value = float(score)
    for label, low, high in SCORE_BUCKETS:
        if label == "UNKNOWN":
            continue
        if low is not None and high is not None and low <= value < high:
            return label
    return "UNKNOWN"


def distance_bucket(distance_pips: float | int | None) -> str:
    if distance_pips is None:
        return "UNKNOWN"
    value = float(distance_pips)
    for label, low, high in DISTANCE_BUCKETS:
        if label == "UNKNOWN":
            continue
        if low is not None and high is not None and low <= value < high:
            return label
    return "UNKNOWN"


def load_records_from_profile_csv(path: str | Path) -> tuple[list[ScoreProfileRecord], dict[str, Any]]:
    """Load one row per linked trade from profile_candle_records.csv.

    The source CSV has one row per candle/touch and can contain multiple
    rows for the same nearest signal. We mirror trade_linked_edge_report:
    keep the closest record per signal, then build the profile record.
    """
    csv_path = Path(path)
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    required = {
        "nearest_signal_timestamp",
        "nearest_signal_score",
        "nearest_signal_setup_mode",
        "nearest_signal_direction",
        "trade_outcome",
        "trade_r_multiple",
        "distance_to_signal_bars",
        "record_index",
    }
    missing_required = sorted(required - set(fieldnames))
    chosen: dict[str, dict[str, Any]] = {}
    for row in rows:
        ts = str(row.get("nearest_signal_timestamp") or "").strip()
        outcome = str(row.get("trade_outcome") or "").strip()
        if not ts or not outcome or outcome == "NO_DATA":
            continue
        current = chosen.get(ts)
        distance = _parse_float(row.get("distance_to_signal_bars"))
        current_distance = _parse_float(current.get("distance_to_signal_bars")) if current else None
        record_index = _parse_float(row.get("record_index")) or 0.0
        current_index = _parse_float(current.get("record_index")) if current else None
        if (
            current is None
            or (distance if distance is not None else float("inf")) < (current_distance if current_distance is not None else float("inf"))
            or (
                distance == current_distance
                and record_index < (current_index if current_index is not None else float("inf"))
            )
        ):
            chosen[ts] = row

    distance_field_present = "distance_to_liquidity_pips" in fieldnames
    records: list[ScoreProfileRecord] = []
    for row in chosen.values():
        r_multiple = _parse_float(row.get("trade_r_multiple"))
        if r_multiple is None:
            continue
        records.append(ScoreProfileRecord(
            signal_timestamp=_parse_dt(row.get("nearest_signal_timestamp")),
            score=_parse_float(row.get("nearest_signal_score")),
            r_multiple=float(r_multiple),
            setup_mode=(str(row.get("nearest_signal_setup_mode") or "").strip() or None),
            continuation=_parse_bool(row.get("feature_continuation_candidate")),
            rejection=_parse_bool(row.get("feature_rejection_candidate")),
            swept_high=_parse_bool(row.get("feature_swept_high")),
            swept_low=_parse_bool(row.get("feature_swept_low")),
            reclaim_after_sweep=_parse_bool(row.get("feature_reclaim_after_sweep")),
            fvg_created=_parse_bool(row.get("feature_fvg_created")),
            ifvg_created=_parse_bool(row.get("feature_ifvg_created")),
            distance_to_liquidity_pips=_parse_float(row.get("distance_to_liquidity_pips")) if distance_field_present else None,
            liquidity_timeframe=(str(row.get("liquidity_timeframe") or row.get("zone_timeframe") or "").strip() or None),
            symbol=(str(row.get("symbol") or "").strip() or None),
            side=(str(row.get("nearest_signal_direction") or "").strip() or None),
        ))

    metadata = {
        "source_csv": str(csv_path),
        "source_columns": fieldnames,
        "missing_required_columns": missing_required,
        "distance_to_liquidity_pips_available": distance_field_present,
        "loaded_linked_trades": len(records),
    }
    return records, metadata


def _ensure_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def split_period(records: Sequence[ScoreProfileRecord], train_end: datetime | None) -> tuple[list[ScoreProfileRecord], list[ScoreProfileRecord]]:
    if train_end is None:
        return list(records), []
    cutoff = _ensure_utc(train_end)
    in_sample: list[ScoreProfileRecord] = []
    out_of_sample: list[ScoreProfileRecord] = []
    for record in records:
        ts = _ensure_utc(record.signal_timestamp)
        if ts is None or cutoff is None or ts <= cutoff:
            in_sample.append(record)
        else:
            out_of_sample.append(record)
    return in_sample, out_of_sample


def _max_drawdown_r(values: Sequence[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return round(max_dd, 4)


def _longest_loss_streak(values: Sequence[float]) -> int:
    longest = 0
    current = 0
    for value in values:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def stats(records: Sequence[ScoreProfileRecord]) -> dict[str, Any]:
    values = [float(r.r_multiple) for r in records]
    if not values:
        return {
            "count": 0,
            "wins": 0,
            "losses": 0,
            "be": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_r": 0.0,
            "median_r": 0.0,
            "max_drawdown_r": 0.0,
            "longest_loss_streak": 0,
            "total_r": 0.0,
        }
    wins = sum(1 for value in values if value > 0)
    losses = sum(1 for value in values if value < 0)
    be = sum(1 for value in values if value == 0)
    win_r = sum(value for value in values if value > 0)
    loss_r = sum(-value for value in values if value < 0)
    if loss_r > 0:
        profit_factor = round(win_r / loss_r, 4)
    elif win_r > 0:
        profit_factor = 999.0
    else:
        profit_factor = 0.0
    return {
        "count": len(values),
        "wins": wins,
        "losses": losses,
        "be": be,
        "win_rate": round(wins / (wins + losses), 4) if wins + losses else 0.0,
        "profit_factor": profit_factor,
        "avg_r": round(fmean(values), 4),
        "median_r": round(median(values), 4),
        "max_drawdown_r": _max_drawdown_r(values),
        "longest_loss_streak": _longest_loss_streak(values),
        "total_r": round(sum(values), 4),
    }


def _period_stats(records: Sequence[ScoreProfileRecord], train_end: datetime | None) -> dict[str, Any]:
    in_sample, out_of_sample = split_period(records, train_end)
    return {
        "full": stats(records),
        "in_sample": stats(in_sample),
        "out_of_sample": stats(out_of_sample),
    }


def _group_by(records: Sequence[ScoreProfileRecord], key_fn, *, ordered_keys: Sequence[str] | None = None) -> dict[str, list[ScoreProfileRecord]]:
    groups = {key: [] for key in (ordered_keys or [])}
    for record in records:
        key = str(key_fn(record))
        groups.setdefault(key, []).append(record)
    return groups


def _profile_groups(records: Sequence[ScoreProfileRecord], key_fn, train_end: datetime | None, *, ordered_keys: Sequence[str] | None = None) -> dict[str, dict[str, Any]]:
    groups = _group_by(records, key_fn, ordered_keys=ordered_keys)
    return {key: _period_stats(group, train_end) for key, group in groups.items()}


def _rank(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def pearson(x_values: Sequence[float], y_values: Sequence[float]) -> float | None:
    if len(x_values) < 2 or len(y_values) < 2 or len(x_values) != len(y_values):
        return None
    mean_x = fmean(x_values)
    mean_y = fmean(y_values)
    dx = [x - mean_x for x in x_values]
    dy = [y - mean_y for y in y_values]
    denom_x = math.sqrt(sum(x * x for x in dx))
    denom_y = math.sqrt(sum(y * y for y in dy))
    if denom_x == 0 or denom_y == 0:
        return None
    return round(sum(a * b for a, b in zip(dx, dy)) / (denom_x * denom_y), 6)


def spearman(x_values: Sequence[float], y_values: Sequence[float]) -> float | None:
    if len(x_values) < 2 or len(y_values) < 2 or len(x_values) != len(y_values):
        return None
    return pearson(_rank(x_values), _rank(y_values))


def _correlation(records: Sequence[ScoreProfileRecord]) -> dict[str, Any]:
    paired = [(float(r.score), float(r.r_multiple)) for r in records if r.score is not None]
    if not paired:
        return {"count": 0, "pearson": None, "spearman": None}
    scores = [item[0] for item in paired]
    outcomes = [item[1] for item in paired]
    return {
        "count": len(paired),
        "pearson": pearson(scores, outcomes),
        "spearman": spearman(scores, outcomes),
    }


def _score_distribution(records: Sequence[ScoreProfileRecord]) -> dict[str, Any]:
    scores = [float(r.score) for r in records if r.score is not None]
    bucket_counts = {label: 0 for label, *_ in SCORE_BUCKETS}
    five_point_counts: dict[str, int] = {}
    for score in scores:
        bucket_counts[score_bucket(score)] += 1
        low = int(math.floor(score / 5.0) * 5)
        label = f"{low}-{low + 4}"
        five_point_counts[label] = five_point_counts.get(label, 0) + 1
    if not scores:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "std": None,
            "percentiles": {},
            "bucket_counts": bucket_counts,
            "five_point_bucket_counts": five_point_counts,
        }
    sorted_scores = sorted(scores)
    return {
        "count": len(scores),
        "min": min(scores),
        "max": max(scores),
        "mean": round(fmean(scores), 4),
        "median": round(median(scores), 4),
        "std": round(pstdev(scores), 4) if len(scores) > 1 else 0.0,
        "percentiles": {str(p): round(_percentile(sorted_scores, p), 4) for p in (10, 25, 50, 75, 90)},
        "bucket_counts": bucket_counts,
        "five_point_bucket_counts": dict(sorted(five_point_counts.items())),
    }


def _percentile(sorted_values: Sequence[float], percentile: int) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * percentile / 100.0
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[int(rank)]
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def preliminary_verdict(correlations: dict[str, dict[str, Any]]) -> str:
    full = correlations.get("full", {}).get("spearman")
    oos = correlations.get("out_of_sample", {}).get("spearman")
    full_abs = abs(float(full)) if full is not None else 0.0
    oos_abs = abs(float(oos)) if oos is not None else 0.0
    if oos_abs < 0.05 and full_abs < 0.05:
        return "EXISTING_SCORE_NOT_PREDICTIVE_PRECHECK"
    if 0.05 <= oos_abs < 0.15:
        return "EXISTING_SCORE_WEAK_SIGNAL_PRECHECK"
    if oos_abs >= 0.15:
        return "EXISTING_SCORE_HAS_POTENTIAL_SIGNAL_PRECHECK"
    return "EXISTING_SCORE_NOT_PREDICTIVE_PRECHECK"


def _best_bucket(bucket_profile: dict[str, dict[str, Any]], period: str) -> tuple[str | None, dict[str, Any] | None]:
    candidates = [
        (key, data.get(period, {}))
        for key, data in bucket_profile.items()
        if key != "UNKNOWN" and data.get(period, {}).get("count", 0) > 0
    ]
    if not candidates:
        return None, None
    return max(candidates, key=lambda item: (item[1].get("profit_factor", 0.0), item[1].get("avg_r", 0.0), item[1].get("count", 0)))


def _score_bucket_order(label: str) -> int:
    labels = [item[0] for item in SCORE_BUCKETS]
    return labels.index(label) if label in labels else -1


def _bucket_monotonic_signal(bucket_profile: dict[str, dict[str, Any]]) -> bool:
    buckets = [
        (key, data["out_of_sample"])
        for key, data in bucket_profile.items()
        if key != "UNKNOWN" and data["out_of_sample"].get("count", 0) > 0
    ]
    buckets.sort(key=lambda item: _score_bucket_order(item[0]))
    if len(buckets) < 2:
        return False
    return buckets[-1][1].get("profit_factor", 0.0) >= buckets[0][1].get("profit_factor", 0.0) and buckets[-1][1].get("avg_r", 0.0) >= buckets[0][1].get("avg_r", 0.0)


def _score_distribution_warnings(distribution: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    total = int(distribution.get("count", 0) or 0)
    counts = distribution.get("five_point_bucket_counts") or {}
    if total <= 0:
        return warnings
    max_count = max(counts.values(), default=0)
    if max_count / total > 0.90:
        warnings.append("LOW_SCORE_VARIANCE_DETECTED")
    ordered = sorted((int(label.split("-", 1)[0]), count) for label, count in counts.items())
    for idx, (_, count) in enumerate(ordered):
        adjacent_total = count
        if idx + 1 < len(ordered) and ordered[idx + 1][0] == ordered[idx][0] + 5:
            adjacent_total += ordered[idx + 1][1]
        if adjacent_total / total > 0.80:
            warnings.append("NARROW_SCORE_DISTRIBUTION")
            break
    return list(dict.fromkeys(warnings))


def _continuation_toxic_warning(continuation: dict[str, Any], records: Sequence[ScoreProfileRecord]) -> bool:
    true_stats = continuation.get("continuation=true", {}).get("full", {})
    false_stats = continuation.get("continuation=false", {}).get("full", {})
    cont_scores = [r.score for r in records if r.continuation is True and r.score is not None]
    non_scores = [r.score for r in records if r.continuation is not True and r.score is not None]
    if not true_stats or not cont_scores or not non_scores:
        return False
    continuation_is_bad = true_stats.get("profit_factor", 0.0) < false_stats.get("profit_factor", 0.0) and true_stats.get("avg_r", 0.0) < 0
    continuation_not_penalized = fmean(cont_scores) >= fmean(non_scores)
    return bool(continuation_is_bad and continuation_not_penalized)


def _build_continuation_damage(records: Sequence[ScoreProfileRecord], train_end: datetime | None) -> dict[str, Any]:
    profile = _profile_groups(
        records,
        lambda r: "continuation=true" if r.continuation is True else "continuation=false",
        train_end,
        ordered_keys=("continuation=true", "continuation=false"),
    )
    extra = {
        "continuation_only": _period_stats([r for r in records if r.continuation is True and r.rejection is not True and r.fvg_created is not True and r.swept_high is not True and r.swept_low is not True], train_end),
        "continuation+fvg_created": _period_stats([r for r in records if r.continuation is True and r.fvg_created is True], train_end),
        "continuation+swept_high": _period_stats([r for r in records if r.continuation is True and r.swept_high is True], train_end),
        "continuation+swept_low": _period_stats([r for r in records if r.continuation is True and r.swept_low is True], train_end),
        "continuation_by_score_bucket": _profile_groups([r for r in records if r.continuation is True], lambda r: score_bucket(r.score), train_end, ordered_keys=[b[0] for b in SCORE_BUCKETS]),
        "continuation_by_setup_mode": _profile_groups([r for r in records if r.continuation is True], lambda r: r.setup_mode or "UNKNOWN", train_end),
    }
    return {**profile, **extra}


def _build_rejection_sanity(records: Sequence[ScoreProfileRecord], train_end: datetime | None) -> dict[str, Any]:
    return {
        "rejection=true": _period_stats([r for r in records if r.rejection is True], train_end),
        "rejection=false": _period_stats([r for r in records if r.rejection is not True], train_end),
        "rejection_by_score_bucket": _profile_groups([r for r in records if r.rejection is True], lambda r: score_bucket(r.score), train_end, ordered_keys=[b[0] for b in SCORE_BUCKETS]),
        "rejection_by_setup_mode": _profile_groups([r for r in records if r.rejection is True], lambda r: r.setup_mode or "UNKNOWN", train_end),
    }


def _final_verdict(
    bucket_profile: dict[str, dict[str, Any]],
    correlations: dict[str, dict[str, Any]],
    warnings: Sequence[str],
) -> str:
    top_oos_label, top_oos = _best_bucket(bucket_profile, "out_of_sample")
    top_full_label, top_full = _best_bucket(bucket_profile, "full")
    top_is_label, top_is = _best_bucket(bucket_profile, "in_sample")
    oos_spearman = correlations.get("out_of_sample", {}).get("spearman")
    if top_oos and top_oos.get("count", 0) >= 20 and top_oos.get("profit_factor", 0.0) > 1.15 and top_oos.get("avg_r", 0.0) > 0:
        if top_full and top_full.get("count", 0) >= 30:
            return "HAS_SIGNAL_IN_EXTREME_BUCKETS"
    if oos_spearman is not None and float(oos_spearman) >= 0.15 and _bucket_monotonic_signal(bucket_profile):
        return "HAS_SIGNAL_MONOTONIC"
    if (
        top_full
        and top_is
        and top_oos
        and top_full.get("profit_factor", 0.0) > 1.0
        and top_is.get("profit_factor", 0.0) > 1.0
        and (top_oos.get("profit_factor", 0.0) <= 1.0 or top_oos.get("avg_r", 0.0) <= 0)
    ):
        return "OVERFIT_RISK"
    oos_abs = abs(float(oos_spearman)) if oos_spearman is not None else 0.0
    if 0.05 <= oos_abs < 0.15:
        return "WEAK_SIGNAL"
    if top_oos and top_oos.get("count", 0) < 20 and top_full and top_full.get("profit_factor", 0.0) > 1.0:
        return "WEAK_SIGNAL"
    return "NOT_PREDICTIVE"


def build_existing_score_profile(
    records: Sequence[ScoreProfileRecord],
    *,
    train_end: datetime | None,
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records = list(records)
    in_sample, out_of_sample = split_period(records, train_end)
    correlations = {
        "full": _correlation(records),
        "in_sample": _correlation(in_sample),
        "out_of_sample": _correlation(out_of_sample),
    }
    distribution = _score_distribution(records)
    bucket_profile = _profile_groups(records, lambda r: score_bucket(r.score), train_end, ordered_keys=[b[0] for b in SCORE_BUCKETS])
    setup_mode_profile = _profile_groups(records, lambda r: r.setup_mode or "UNKNOWN", train_end)
    continuation_damage = _build_continuation_damage(records, train_end)
    rejection_sanity = _build_rejection_sanity(records, train_end)

    warnings = _score_distribution_warnings(distribution)
    if not (source_metadata or {}).get("distance_to_liquidity_pips_available", False):
        warnings.append("DISTANCE_FIELD_NOT_AVAILABLE")
        distance_profile: dict[str, Any] = {
            "status": "field_not_available_skip",
            "next_step_required": "Add distance_to_liquidity_pips to LinkedTrade/report in a small follow-up commit.",
        }
    else:
        distance_profile = _profile_groups(records, lambda r: distance_bucket(r.distance_to_liquidity_pips), train_end, ordered_keys=[b[0] for b in DISTANCE_BUCKETS])
    if out_of_sample and max((data["out_of_sample"].get("count", 0) for data in bucket_profile.values()), default=0) < 20:
        warnings.append("INSUFFICIENT_OOS_SAMPLE")
    if _continuation_toxic_warning(continuation_damage, records):
        warnings.append("SCORE_REWARDS_TOXIC_CONTINUATION")
    warnings = list(dict.fromkeys(warnings))

    prelim = preliminary_verdict(correlations)
    final = _final_verdict(bucket_profile, correlations, warnings)

    return {
        "config": {
            "walk_forward_train_end": train_end.isoformat() if train_end else None,
            "score_buckets": [item[0] for item in SCORE_BUCKETS],
            "distance_buckets": [item[0] for item in DISTANCE_BUCKETS],
        },
        "source": source_metadata or {},
        "record_count": len(records),
        "overall": _period_stats(records, train_end),
        "score_distribution": distribution,
        "correlations": correlations,
        "preliminary_verdict_from_correlation": prelim,
        "score_bucket_profile": bucket_profile,
        "setup_mode_breakdown": setup_mode_profile,
        "continuation_damage": continuation_damage,
        "rejection_sanity_check": rejection_sanity,
        "distance_bucket_profile": distance_profile,
        "warnings": warnings,
        "final_verdict_from_bucket_analysis": final,
        "reasoning": _reasoning(final, prelim, warnings, bucket_profile, setup_mode_profile, continuation_damage, rejection_sanity),
        "next_step_required": _next_steps(source_metadata or {}),
    }


def _next_steps(source_metadata: dict[str, Any]) -> list[str]:
    steps: list[str] = []
    if not source_metadata.get("distance_to_liquidity_pips_available", False):
        steps.append("Add distance_to_liquidity_pips to LinkedTrade/report in a small follow-up commit; do not rerun full backtest unless explicitly approved.")
    steps.append("Skip score sub-component profiling until total score shows useful OOS signal.")
    return steps


def _reasoning(
    final: str,
    prelim: str,
    warnings: Sequence[str],
    bucket_profile: dict[str, dict[str, Any]],
    setup_mode_profile: dict[str, dict[str, Any]],
    continuation_damage: dict[str, Any],
    rejection_sanity: dict[str, Any],
) -> str:
    top_full_label, top_full = _best_bucket(bucket_profile, "full")
    top_oos_label, top_oos = _best_bucket(bucket_profile, "out_of_sample")
    setup_label, setup = _best_bucket(setup_mode_profile, "full")
    cont = continuation_damage.get("continuation=true", {}).get("full", {})
    rej = rejection_sanity.get("rejection=true", {}).get("full", {})
    return (
        f"Pre-check={prelim}; bucket verdict={final}. "
        f"Best full score bucket={top_full_label} PF={(top_full or {}).get('profit_factor')} AvgR={(top_full or {}).get('avg_r')}; "
        f"best OOS score bucket={top_oos_label} PF={(top_oos or {}).get('profit_factor')} AvgR={(top_oos or {}).get('avg_r')}. "
        f"Best setup_mode={setup_label} PF={(setup or {}).get('profit_factor')}. "
        f"Continuation full PF={cont.get('profit_factor')} AvgR={cont.get('avg_r')}; "
        f"rejection full PF={rej.get('profit_factor')} AvgR={rej.get('avg_r')}. "
        f"Warnings={', '.join(warnings) if warnings else 'none'}."
    )


def render_markdown(report: dict[str, Any]) -> str:
    def fmt(value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value)

    lines: list[str] = []
    lines.append("# Existing Adelin Score Profile\n")
    lines.append("## Verdicts\n")
    lines.append(f"- preliminary_verdict_from_correlation: `{report.get('preliminary_verdict_from_correlation')}`")
    lines.append(f"- final_verdict_from_bucket_analysis: `{report.get('final_verdict_from_bucket_analysis')}`")
    lines.append(f"- warnings: {', '.join(report.get('warnings') or []) or 'none'}")
    lines.append(f"- reasoning: {report.get('reasoning')}\n")

    dist = report.get("score_distribution") or {}
    lines.append("## Score Distribution\n")
    lines.append(f"- count: {dist.get('count')}")
    lines.append(f"- min / max: {fmt(dist.get('min'))} / {fmt(dist.get('max'))}")
    lines.append(f"- mean / median / std: {fmt(dist.get('mean'))} / {fmt(dist.get('median'))} / {fmt(dist.get('std'))}")
    lines.append(f"- percentiles: {dist.get('percentiles')}")
    lines.append(f"- bucket_counts: {dist.get('bucket_counts')}")
    lines.append(f"- five_point_bucket_counts: {dist.get('five_point_bucket_counts')}\n")

    lines.append("## Correlations\n")
    lines.append("| period | n | Pearson | Spearman |")
    lines.append("|---|---|---|---|")
    for period in ("full", "in_sample", "out_of_sample"):
        row = (report.get("correlations") or {}).get(period) or {}
        lines.append(f"| {period} | {row.get('count')} | {fmt(row.get('pearson'))} | {fmt(row.get('spearman'))} |")
    lines.append("")

    def table(title: str, data: dict[str, Any]) -> None:
        lines.append(f"## {title}\n")
        lines.append("| bucket | Full n | Full WR | Full PF | Full AvgR | Full MaxDD | IS n | IS PF | IS AvgR | OOS n | OOS PF | OOS AvgR |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for key, periods in data.items():
            if not isinstance(periods, dict) or "full" not in periods:
                continue
            full = periods.get("full") or {}
            ins = periods.get("in_sample") or {}
            oos = periods.get("out_of_sample") or {}
            lines.append(
                f"| {key} | {full.get('count')} | {fmt(full.get('win_rate'))} | {fmt(full.get('profit_factor'))} | "
                f"{fmt(full.get('avg_r'))} | {fmt(full.get('max_drawdown_r'))} | {ins.get('count')} | "
                f"{fmt(ins.get('profit_factor'))} | {fmt(ins.get('avg_r'))} | {oos.get('count')} | "
                f"{fmt(oos.get('profit_factor'))} | {fmt(oos.get('avg_r'))} |"
            )
        lines.append("")

    table("Score Bucket Profile", report.get("score_bucket_profile") or {})
    table("Setup Mode Breakdown", report.get("setup_mode_breakdown") or {})

    lines.append("## Does existing score reward toxic continuation?\n")
    table("Continuation Damage", {k: v for k, v in (report.get("continuation_damage") or {}).items() if isinstance(v, dict) and "full" in v})
    table("Continuation by Score Bucket", (report.get("continuation_damage") or {}).get("continuation_by_score_bucket") or {})
    table("Continuation by Setup Mode", (report.get("continuation_damage") or {}).get("continuation_by_setup_mode") or {})

    lines.append("## Rejection Sanity Check\n")
    table("Rejection Split", {k: v for k, v in (report.get("rejection_sanity_check") or {}).items() if isinstance(v, dict) and "full" in v})
    table("Rejection by Score Bucket", (report.get("rejection_sanity_check") or {}).get("rejection_by_score_bucket") or {})
    table("Rejection by Setup Mode", (report.get("rejection_sanity_check") or {}).get("rejection_by_setup_mode") or {})

    lines.append("## Distance Bucket Profile\n")
    distance_profile = report.get("distance_bucket_profile") or {}
    if distance_profile.get("status") == "field_not_available_skip":
        lines.append("- field_not_available_skip")
        lines.append(f"- next_step_required: {distance_profile.get('next_step_required')}\n")
    else:
        table("Distance Buckets", distance_profile)

    lines.append("## Next Step Required\n")
    for step in report.get("next_step_required") or []:
        lines.append(f"- {step}")
    lines.append("")
    return "\n".join(lines)


def write_report_files(*, output_dir: str | Path, report: dict[str, Any], records: Sequence[ScoreProfileRecord] = ()) -> dict[str, str]:
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    json_path = out_root / "existing_score_profile.json"
    md_path = out_root / "existing_score_profile.md"
    csv_path = out_root / "existing_score_profile.csv"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    _write_records_csv(csv_path, records)
    return {
        "json": str(json_path),
        "markdown": str(md_path),
        "csv": str(csv_path),
    }


def _write_records_csv(path: Path, records: Sequence[ScoreProfileRecord]) -> None:
    fieldnames = [
        "signal_timestamp",
        "score",
        "score_bucket",
        "r_multiple",
        "setup_mode",
        "continuation",
        "rejection",
        "swept_high",
        "swept_low",
        "reclaim_after_sweep",
        "fvg_created",
        "ifvg_created",
        "distance_to_liquidity_pips",
        "distance_bucket",
        "liquidity_timeframe",
        "symbol",
        "side",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({
                "signal_timestamp": record.signal_timestamp.isoformat() if record.signal_timestamp else "",
                "score": record.score if record.score is not None else "",
                "score_bucket": score_bucket(record.score),
                "r_multiple": record.r_multiple,
                "setup_mode": record.setup_mode or "",
                "continuation": record.continuation,
                "rejection": record.rejection,
                "swept_high": record.swept_high,
                "swept_low": record.swept_low,
                "reclaim_after_sweep": record.reclaim_after_sweep,
                "fvg_created": record.fvg_created,
                "ifvg_created": record.ifvg_created,
                "distance_to_liquidity_pips": record.distance_to_liquidity_pips if record.distance_to_liquidity_pips is not None else "",
                "distance_bucket": distance_bucket(record.distance_to_liquidity_pips),
                "liquidity_timeframe": record.liquidity_timeframe or "",
                "symbol": record.symbol or "",
                "side": record.side or "",
            })


def build_from_profile_csv(*, profile_csv: str | Path, train_end: datetime | None) -> tuple[dict[str, Any], list[ScoreProfileRecord]]:
    records, metadata = load_records_from_profile_csv(profile_csv)
    return build_existing_score_profile(records, train_end=train_end, source_metadata=metadata), records


__all__ = [
    "ScoreProfileRecord",
    "build_existing_score_profile",
    "build_from_profile_csv",
    "distance_bucket",
    "load_records_from_profile_csv",
    "pearson",
    "preliminary_verdict",
    "render_markdown",
    "score_bucket",
    "spearman",
    "stats",
    "write_report_files",
]
