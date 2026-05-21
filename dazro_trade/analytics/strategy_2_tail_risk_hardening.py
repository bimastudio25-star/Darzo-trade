from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median
from typing import Any, Callable

import pandas as pd


PRIMARY_MODEL = "containing"
VALID_SAMPLE_STATUSES = {
    "VALID_SAMPLE_TRADE_TRIGGERED",
    "VALID_SAMPLE_NO_ENTRY_MAE_NOT_REACHED",
    "VALID_SAMPLE_NO_ENTRY_NO_RANGE_REENTRY",
}

SAFETY = {
    "research_only": True,
    "dry_run": True,
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "broker_called": False,
    "order_sent": False,
    "order_send_called": False,
    "signals_generated": False,
    "runtime_registration": False,
    "parameters_optimized": False,
    "grid_search_used": False,
    "machine_learning_used": False,
    "market_data_written": False,
    "profit_or_pf_used": False,
}


@dataclass(frozen=True)
class TailRiskHardeningResult:
    samples: pd.DataFrame
    bucket_profile: pd.DataFrame
    driver_breakdown: pd.DataFrame
    hypotheses: pd.DataFrame
    r_profile: pd.DataFrame
    top_tail_cases: pd.DataFrame
    summary: dict[str, Any]
    report_markdown: str


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([pd.NA] * len(frame), index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _values(frame: pd.DataFrame, column: str) -> list[float]:
    return [float(value) for value in _numeric(frame, column).dropna().tolist()]


def _mean(values: list[float]) -> float | None:
    return round(fmean(values), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(median(values), 4) if values else None


def percentile(values: list[float], q: float) -> float | None:
    vals = sorted(values)
    if not vals:
        return None
    if len(vals) == 1:
        return round(vals[0], 4)
    pos = (len(vals) - 1) * q
    low = int(pos)
    high = min(low + 1, len(vals) - 1)
    weight = pos - low
    return round(vals[low] * (1 - weight) + vals[high] * weight, 4)


def _pct(count: int | float, total: int | float) -> float:
    return round(float(count) / float(total) * 100.0, 2) if total else 0.0


def price_to_pips(distance: float | None, pip_factor: float) -> float | None:
    return None if distance is None else round(float(distance) * float(pip_factor), 4)


def conservative_sl_distance(max_excursion: float | None) -> float | None:
    return None if max_excursion is None else round(float(max_excursion) * 1.25, 4)


def tp_quartiles(max_expansion: float | None) -> dict[str, float | None]:
    if max_expansion is None:
        return {"tp1": None, "tp2": None, "tp3": None, "tp4": None}
    value = max(0.0, float(max_expansion))
    return {
        "tp1": round(value * 0.25, 4),
        "tp2": round(value * 0.50, 4),
        "tp3": round(value * 0.75, 4),
        "tp4": round(value, 4),
    }


def _sample_key(row: pd.Series | dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("h1_context_timestamp", "")),
            str(row.get("h1_reference_type", "")),
            str(row.get("direction", "")),
            str(row.get("h1_liquidity_level", "")),
        ]
    )


def _parse_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=True)


def _minutes_between(later: pd.Series, earlier: pd.Series) -> pd.Series:
    return (later - earlier).dt.total_seconds() / 60.0


def _bucket_by_thresholds(value: Any, thresholds: list[tuple[str, float]]) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "UNKNOWN"
    for label, threshold in thresholds:
        if numeric <= threshold:
            return label
    return f">{thresholds[-1][0].replace('<=', '')}"


def load_containing_samples(mechanical_dir: str | Path, *, pip_factor: float = 10.0) -> pd.DataFrame:
    path = Path(mechanical_dir) / "corrected_mechanical_samples.csv"
    if not path.exists():
        raise FileNotFoundError(f"corrected mechanical sample file missing: {path}")
    frame = pd.read_csv(path)
    required = {"m15_filter_model", "sample_status", "manipulation_depth_usd", "expansion_usd", "entry_valid"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"corrected mechanical sample file missing required columns: {missing}")
    return enrich_samples(frame, pip_factor=pip_factor)


def enrich_samples(frame: pd.DataFrame, *, pip_factor: float = 10.0) -> pd.DataFrame:
    out = frame.copy()
    out["sample_key"] = out.apply(_sample_key, axis=1)
    out["is_valid_sample"] = out["sample_status"].astype(str).isin(VALID_SAMPLE_STATUSES)
    out["entry_valid_bool"] = out.get("entry_valid", pd.Series(False, index=out.index)).map(_to_bool)
    out["mae_reached_bool"] = out.get("mae_reached", pd.Series(False, index=out.index)).map(_to_bool)
    out["range_reentry_reached_bool"] = out.get("range_reentry_reached", pd.Series(False, index=out.index)).map(_to_bool)
    out["manipulation_depth_usd"] = _numeric(out, "manipulation_depth_usd")
    out["manipulation_depth_pips"] = out["manipulation_depth_usd"] * float(pip_factor)
    out["expansion_usd"] = _numeric(out, "expansion_usd")
    out["expansion_pips"] = out["expansion_usd"] * float(pip_factor)
    out["h1_reference_range"] = _numeric(out, "h1_reference_range")
    out["hour"] = _numeric(out, "hour")
    out["expansion_mae_ratio"] = out["expansion_usd"] / out["manipulation_depth_usd"].where(out["manipulation_depth_usd"] > 0)
    context_ts = _parse_utc(out.get("h1_context_timestamp", pd.Series(pd.NaT, index=out.index)))
    take_ts = _parse_utc(out.get("h1_level_take_timestamp", pd.Series(pd.NaT, index=out.index)))
    mae_ts = _parse_utc(out.get("mae_reached_timestamp", pd.Series(pd.NaT, index=out.index)))
    reentry_ts = _parse_utc(out.get("range_reentry_timestamp", pd.Series(pd.NaT, index=out.index)))
    out["level_take_minute_in_h1"] = _minutes_between(take_ts, context_ts)
    out["mae_reach_minute_in_h1"] = _minutes_between(mae_ts, context_ts)
    out["reentry_minute_in_h1"] = _minutes_between(reentry_ts, context_ts)
    out["time_from_take_to_mae_minutes"] = _minutes_between(mae_ts, take_ts)
    out["time_from_mae_to_reentry_minutes"] = _minutes_between(reentry_ts, mae_ts)
    out["pip_factor_used"] = float(pip_factor)
    return out


def containing_valid_samples(frame: pd.DataFrame) -> pd.DataFrame:
    rows = frame[frame["m15_filter_model"].astype(str).eq(PRIMARY_MODEL)].copy()
    return rows[rows["is_valid_sample"]].copy()


def r_profile_for_samples(samples: pd.DataFrame, *, label: str, pip_factor: float = 10.0) -> dict[str, Any]:
    mae = _values(samples, "manipulation_depth_usd")
    expansion = _values(samples, "expansion_usd")
    avg_mae = _mean(mae)
    max_excursion = round(max(mae), 4) if mae else None
    conservative_sl = conservative_sl_distance(max_excursion)
    effective_risk = None
    if conservative_sl is not None and avg_mae is not None:
        effective_risk = round(max(conservative_sl - avg_mae, 0.0), 4)
    max_expansion = round(max(expansion), 4) if expansion else None
    tps = tp_quartiles(max_expansion)

    def rr(tp_distance: float | None) -> float | None:
        if tp_distance is None or avg_mae is None or effective_risk is None or effective_risk <= 0:
            return None
        return round((avg_mae + tp_distance) / effective_risk, 4)

    return {
        "profile_label": label,
        "samples": int(len(samples)),
        "mae_avg_usd": avg_mae,
        "mae_median_usd": _median(mae),
        "mae_p90_usd": percentile(mae, 0.90),
        "mae_p95_usd": percentile(mae, 0.95),
        "max_excursion_usd": max_excursion,
        "conservative_sl_usd": conservative_sl,
        "max_excursion_pips": price_to_pips(max_excursion, pip_factor),
        "conservative_sl_pips": price_to_pips(conservative_sl, pip_factor),
        "avg_expansion_usd": _mean(expansion),
        "median_expansion_usd": _median(expansion),
        "max_expansion_usd": max_expansion,
        "tp1_distance_usd": tps["tp1"],
        "tp2_distance_usd": tps["tp2"],
        "tp3_distance_usd": tps["tp3"],
        "tp4_distance_usd": tps["tp4"],
        "tp1_R": rr(tps["tp1"]),
        "tp2_R": rr(tps["tp2"]),
        "tp3_R": rr(tps["tp3"]),
        "tp4_R": rr(tps["tp4"]),
        "pip_factor_used": float(pip_factor),
        "unit_note": "USD fields are XAUUSD price-distance/USD units; pips = USD * pip_factor.",
    }


def tail_bucket_profile(samples: pd.DataFrame, *, pip_factor: float = 10.0) -> pd.DataFrame:
    buckets: list[tuple[str, Callable[[pd.DataFrame], pd.Series]]] = [
        ("BODY_MAE_LE_8", lambda df: df["manipulation_depth_usd"] <= 8),
        ("BODY_MAE_LE_10", lambda df: df["manipulation_depth_usd"] <= 10),
        ("BODY_MAE_LE_12", lambda df: df["manipulation_depth_usd"] <= 12),
        ("TAIL_MAE_GT_12", lambda df: df["manipulation_depth_usd"] > 12),
        ("TAIL_MAE_GT_20", lambda df: df["manipulation_depth_usd"] > 20),
        ("TAIL_MAE_GT_40", lambda df: df["manipulation_depth_usd"] > 40),
        ("TAIL_MAE_GT_100", lambda df: df["manipulation_depth_usd"] > 100),
    ]
    rows: list[dict[str, Any]] = []
    total = len(samples)
    for label, predicate in buckets:
        subset = samples[predicate(samples)].copy()
        mae = _values(subset, "manipulation_depth_usd")
        expansion = _values(subset, "expansion_usd")
        ratio = _values(subset, "expansion_mae_ratio")
        r_profile = r_profile_for_samples(subset, label=label, pip_factor=pip_factor)
        rows.append(
            {
                "bucket": label,
                "count": len(subset),
                "pct_of_samples": _pct(len(subset), total),
                "avg_mae_usd": _mean(mae),
                "median_mae_usd": _median(mae),
                "p90_mae_usd": percentile(mae, 0.90),
                "p95_mae_usd": percentile(mae, 0.95),
                "max_mae_usd": round(max(mae), 4) if mae else None,
                "avg_expansion_usd": _mean(expansion),
                "median_expansion_usd": _median(expansion),
                "max_expansion_usd": round(max(expansion), 4) if expansion else None,
                "avg_expansion_mae_ratio": _mean(ratio),
                "median_expansion_mae_ratio": _median(ratio),
                "tp1_R": r_profile["tp1_R"],
                "tp2_R": r_profile["tp2_R"],
                "tp3_R": r_profile["tp3_R"],
                "tp4_R": r_profile["tp4_R"],
                "h1_reference_type_distribution": json.dumps(Counter(subset.get("h1_reference_type", pd.Series(dtype=str)).fillna("").astype(str)), sort_keys=True),
                "direction_distribution": json.dumps(Counter(subset.get("direction", pd.Series(dtype=str)).fillna("").astype(str)), sort_keys=True),
                "session_distribution": json.dumps(Counter(subset.get("session", pd.Series(dtype=str)).fillna("").astype(str)), sort_keys=True),
                "hour_distribution": json.dumps(Counter(subset.get("hour", pd.Series(dtype=str)).fillna("").astype(str)), sort_keys=True),
                "avg_level_take_minute_in_h1": _mean(_values(subset, "level_take_minute_in_h1")),
                "avg_mae_reach_minute_in_h1": _mean(_values(subset, "mae_reach_minute_in_h1")),
                "avg_reentry_minute_in_h1": _mean(_values(subset, "reentry_minute_in_h1")),
                "pip_factor_used": float(pip_factor),
            }
        )
    return pd.DataFrame(rows)


def _add_quantile_bucket(samples: pd.DataFrame, field: str, output: str) -> None:
    values = _values(samples, field)
    p50 = percentile(values, 0.50)
    p75 = percentile(values, 0.75)
    p90 = percentile(values, 0.90)
    if p50 is None or p75 is None or p90 is None:
        samples[output] = "UNKNOWN"
        return
    samples[output] = samples[field].map(
        lambda value: _bucket_by_thresholds(
            value,
            [
                ("<=p50", float(p50)),
                ("<=p75", float(p75)),
                ("<=p90", float(p90)),
            ],
        )
    )


def tail_driver_breakdown(samples: pd.DataFrame) -> pd.DataFrame:
    data = samples.copy()
    _add_quantile_bucket(data, "h1_reference_range", "h1_range_bucket")
    _add_quantile_bucket(data, "level_take_minute_in_h1", "level_take_minute_bucket")
    _add_quantile_bucket(data, "mae_reach_minute_in_h1", "mae_reach_minute_bucket")
    _add_quantile_bucket(data, "reentry_minute_in_h1", "reentry_minute_bucket")
    _add_quantile_bucket(data, "expansion_mae_ratio", "expansion_mae_ratio_bucket")
    dimensions = [
        ("h1_reference_type", "h1_reference_type"),
        ("direction", "direction"),
        ("session", "session"),
        ("hour", "hour"),
        ("h1_range_bucket", "h1_range_bucket"),
        ("level_take_minute_bucket", "level_take_minute_bucket"),
        ("mae_reach_minute_bucket", "mae_reach_minute_bucket"),
        ("reentry_minute_bucket", "reentry_minute_bucket"),
        ("expansion_mae_ratio_bucket", "expansion_mae_ratio_bucket"),
    ]
    rows: list[dict[str, Any]] = []
    for dimension, column in dimensions:
        if column not in data.columns:
            continue
        for value, group in data.groupby(column, dropna=False):
            mae = _values(group, "manipulation_depth_usd")
            expansion = _values(group, "expansion_usd")
            ratio = _values(group, "expansion_mae_ratio")
            rows.append(
                {
                    "dimension": dimension,
                    "bucket": str(value if value == value else "UNKNOWN"),
                    "count": len(group),
                    "sample_pct": _pct(len(group), len(data)),
                    "tail_gt_12_count": sum(1 for item in mae if item > 12),
                    "tail_gt_12_pct": _pct(sum(1 for item in mae if item > 12), len(mae)),
                    "tail_gt_20_count": sum(1 for item in mae if item > 20),
                    "tail_gt_20_pct": _pct(sum(1 for item in mae if item > 20), len(mae)),
                    "mae_avg_usd": _mean(mae),
                    "mae_p95_usd": percentile(mae, 0.95),
                    "mae_max_usd": round(max(mae), 4) if mae else None,
                    "avg_expansion_usd": _mean(expansion),
                    "avg_expansion_mae_ratio": _mean(ratio),
                }
            )
    return pd.DataFrame(rows)


def _rule_result(
    samples: pd.DataFrame,
    *,
    rule_name: str,
    description: str,
    remove_mask: pd.Series,
    category: str,
    pip_factor: float,
) -> dict[str, Any]:
    remove_mask = remove_mask.reindex(samples.index).fillna(False)
    kept = samples[~remove_mask].copy()
    removed = samples[remove_mask].copy()
    body_total = int((samples["manipulation_depth_usd"] <= 12).sum())
    tail_total = int((samples["manipulation_depth_usd"] > 12).sum())
    tail20_total = int((samples["manipulation_depth_usd"] > 20).sum())
    body_removed = int((removed["manipulation_depth_usd"] <= 12).sum())
    tail_removed = int((removed["manipulation_depth_usd"] > 12).sum())
    tail20_removed = int((removed["manipulation_depth_usd"] > 20).sum())
    before = r_profile_for_samples(samples, label="raw_containing", pip_factor=pip_factor)
    after = r_profile_for_samples(kept, label=rule_name, pip_factor=pip_factor)
    body_removed_pct = _pct(body_removed, body_total)
    tail_removed_pct = _pct(tail_removed, tail_total)
    tail20_removed_pct = _pct(tail20_removed, tail20_total)
    if len(kept) < 30:
        verdict = "INSUFFICIENT_DATA"
    elif body_removed_pct > 35:
        verdict = "REJECTED_TOO_BROAD"
    elif tail_removed_pct >= 50 and body_removed_pct <= 25:
        verdict = "PROMISING_DIAGNOSTIC"
    elif tail_removed_pct < 25:
        verdict = "WEAK_DIAGNOSTIC"
    else:
        verdict = "WEAK_DIAGNOSTIC"
    return {
        "rule_name": rule_name,
        "category": category,
        "rule_description": description,
        "samples_before": len(samples),
        "samples_kept": len(kept),
        "samples_removed": len(removed),
        "body_kept_pct": _pct(body_total - body_removed, body_total),
        "body_removed_pct": body_removed_pct,
        "tail_removed_pct": tail_removed_pct,
        "tail_gt_20_removed_pct": tail20_removed_pct,
        "max_mae_before": before["max_excursion_usd"],
        "max_mae_after": after["max_excursion_usd"],
        "p95_mae_before": before["mae_p95_usd"],
        "p95_mae_after": after["mae_p95_usd"],
        "conservative_sl_before": before["conservative_sl_usd"],
        "conservative_sl_after": after["conservative_sl_usd"],
        "tp4_R_before": before["tp4_R"],
        "tp4_R_after": after["tp4_R"],
        "verdict": verdict,
        "profit_or_pf_used": False,
        "threshold_source": "descriptive_percentile_or_fixed_diagnostic_bucket",
        "pip_factor_used": float(pip_factor),
    }


def hardening_hypotheses(samples: pd.DataFrame, *, pip_factor: float = 10.0) -> pd.DataFrame:
    rules: list[dict[str, Any]] = []
    h1_ranges = _values(samples, "h1_reference_range")
    take_minutes = _values(samples, "level_take_minute_in_h1")
    mae_minutes = _values(samples, "mae_reach_minute_in_h1")
    reentry_minutes = _values(samples, "reentry_minute_in_h1")
    ratios = _values(samples, "expansion_mae_ratio")
    mae_values = _values(samples, "manipulation_depth_usd")
    threshold_specs = [
        ("NO_TRADE_IF_H1_RANGE_ABOVE_P90", "H1 range above p90", "h1_range", "h1_reference_range", percentile(h1_ranges, 0.90), lambda s, t: s["h1_reference_range"] > t),
        ("NO_TRADE_IF_H1_RANGE_ABOVE_P95", "H1 range above p95", "h1_range", "h1_reference_range", percentile(h1_ranges, 0.95), lambda s, t: s["h1_reference_range"] > t),
        ("NO_TRADE_IF_LEVEL_TAKE_AFTER_P75_MINUTE", "H1 level take minute after p75", "entry_timing", "level_take_minute_in_h1", percentile(take_minutes, 0.75), lambda s, t: s["level_take_minute_in_h1"] > t),
        ("NO_TRADE_IF_LEVEL_TAKE_AFTER_P90_MINUTE", "H1 level take minute after p90", "entry_timing", "level_take_minute_in_h1", percentile(take_minutes, 0.90), lambda s, t: s["level_take_minute_in_h1"] > t),
        ("NO_TRADE_IF_MAE_REACH_AFTER_P75_MINUTE", "MAE reach minute after p75", "entry_timing", "mae_reach_minute_in_h1", percentile(mae_minutes, 0.75), lambda s, t: s["mae_reach_minute_in_h1"] > t),
        ("NO_TRADE_IF_REENTRY_AFTER_P75_MINUTE", "Range re-entry minute after p75", "entry_timing", "reentry_minute_in_h1", percentile(reentry_minutes, 0.75), lambda s, t: s["reentry_minute_in_h1"] > t),
        ("NO_TRADE_IF_EXPANSION_MAE_RATIO_BELOW_P25", "Expansion/MAE ratio below p25", "expansion_mae_ratio", "expansion_mae_ratio", percentile(ratios, 0.25), lambda s, t: s["expansion_mae_ratio"] < t),
        ("NO_TRADE_IF_MAE_ABOVE_P90", "Ex-post MAE above p90 diagnostic only", "mechanical_no_trade_diagnostic", "manipulation_depth_usd", percentile(mae_values, 0.90), lambda s, t: s["manipulation_depth_usd"] > t),
    ]
    for name, description, category, field, threshold, mask_fn in threshold_specs:
        if threshold is None or field not in samples.columns:
            rules.append(
                {
                    "rule_name": name,
                    "category": category,
                    "rule_description": f"{description}: insufficient data",
                    "samples_before": len(samples),
                    "samples_kept": len(samples),
                    "samples_removed": 0,
                    "body_kept_pct": 100.0,
                    "body_removed_pct": 0.0,
                    "tail_removed_pct": 0.0,
                    "tail_gt_20_removed_pct": 0.0,
                    "verdict": "INSUFFICIENT_DATA",
                    "profit_or_pf_used": False,
                    "threshold_source": "descriptive_percentile_or_fixed_diagnostic_bucket",
                    "pip_factor_used": float(pip_factor),
                }
            )
            continue
        rules.append(
            _rule_result(
                samples,
                rule_name=name,
                description=f"{description} ({field} > {threshold})" if "BELOW" not in name else f"{description} ({field} < {threshold})",
                remove_mask=mask_fn(samples, float(threshold)),
                category=category,
                pip_factor=pip_factor,
            )
        )
    rules.append(
        _rule_result(
            samples,
            rule_name="NO_TRADE_IF_DOMINANT_H1",
            description="Dominant H1 reference removed as a structural diagnostic",
            remove_mask=samples.get("h1_reference_type", pd.Series("", index=samples.index)).astype(str).eq("dominant_h1"),
            category="dominant_h1",
            pip_factor=pip_factor,
        )
    )
    for direction in sorted(str(item) for item in samples.get("direction", pd.Series(dtype=str)).dropna().unique()):
        rules.append(
            _rule_result(
                samples,
                rule_name=f"NO_TRADE_IF_DIRECTION_{direction}",
                description=f"Remove {direction} samples as directional asymmetry diagnostic",
                remove_mask=samples.get("direction", pd.Series("", index=samples.index)).astype(str).eq(direction),
                category="direction",
                pip_factor=pip_factor,
            )
        )
    return pd.DataFrame(rules)


def r_profiles_for_hypotheses(samples: pd.DataFrame, hypotheses: pd.DataFrame, *, pip_factor: float = 10.0) -> pd.DataFrame:
    rows = [r_profile_for_samples(samples, label="RAW_CONTAINING", pip_factor=pip_factor)]
    for _, rule in hypotheses.iterrows():
        if rule.get("rule_name") == "RAW_CONTAINING":
            continue
        # Rebuild masks from the rule name rather than using optimized state.
        name = str(rule.get("rule_name"))
        mask = pd.Series(False, index=samples.index)
        if name == "NO_TRADE_IF_DOMINANT_H1":
            mask = samples.get("h1_reference_type", pd.Series("", index=samples.index)).astype(str).eq("dominant_h1")
        elif name.startswith("NO_TRADE_IF_DIRECTION_"):
            direction = name.replace("NO_TRADE_IF_DIRECTION_", "")
            mask = samples.get("direction", pd.Series("", index=samples.index)).astype(str).eq(direction)
        else:
            threshold = _extract_threshold(rule.get("rule_description"))
            if threshold is not None:
                if name == "NO_TRADE_IF_H1_RANGE_ABOVE_P90" or name == "NO_TRADE_IF_H1_RANGE_ABOVE_P95":
                    mask = samples["h1_reference_range"] > threshold
                elif name.startswith("NO_TRADE_IF_LEVEL_TAKE"):
                    mask = samples["level_take_minute_in_h1"] > threshold
                elif name.startswith("NO_TRADE_IF_MAE_REACH"):
                    mask = samples["mae_reach_minute_in_h1"] > threshold
                elif name.startswith("NO_TRADE_IF_REENTRY"):
                    mask = samples["reentry_minute_in_h1"] > threshold
                elif name == "NO_TRADE_IF_EXPANSION_MAE_RATIO_BELOW_P25":
                    mask = samples["expansion_mae_ratio"] < threshold
                elif name == "NO_TRADE_IF_MAE_ABOVE_P90":
                    mask = samples["manipulation_depth_usd"] > threshold
        rows.append(r_profile_for_samples(samples[~mask], label=name, pip_factor=pip_factor))
    return pd.DataFrame(rows)


def _extract_threshold(description: Any) -> float | None:
    if not isinstance(description, str):
        return None
    for token in description.replace(")", "").split():
        try:
            return float(token)
        except ValueError:
            continue
    return None


def top_tail_cases(samples: pd.DataFrame, *, limit: int = 20) -> pd.DataFrame:
    columns = [
        "sample_id",
        "h1_context_timestamp",
        "direction",
        "h1_reference_type",
        "h1_reference_range",
        "session",
        "hour",
        "level_take_minute_in_h1",
        "mae_reach_minute_in_h1",
        "reentry_minute_in_h1",
        "time_from_take_to_mae_minutes",
        "time_from_mae_to_reentry_minutes",
        "manipulation_depth_usd",
        "manipulation_depth_pips",
        "expansion_usd",
        "expansion_mae_ratio",
        "entry_valid_bool",
        "sample_status",
    ]
    available = [column for column in columns if column in samples.columns]
    return samples.sort_values("manipulation_depth_usd", ascending=False).head(limit)[available].copy()


def strongest_tail_drivers(driver_breakdown: pd.DataFrame, *, min_count: int = 10) -> list[dict[str, Any]]:
    if driver_breakdown.empty:
        return []
    candidates = driver_breakdown[driver_breakdown["count"] >= min_count].copy()
    if candidates.empty:
        return []
    candidates = candidates.sort_values(["tail_gt_20_pct", "tail_gt_12_pct", "count"], ascending=[False, False, False])
    return candidates.head(5).to_dict(orient="records")


def verdict_flags_for(hypotheses: pd.DataFrame, drivers: list[dict[str, Any]], r_profiles: pd.DataFrame) -> list[str]:
    flags = [
        "TAIL_RISK_HARDENING_COMPLETE",
        "TAIL_RISK_REMAINS_STRUCTURAL",
        "R_PROFILE_STILL_STRUCTURALLY_WEAK",
        "STRATEGY_2_REMAINS_RESEARCH_ONLY",
        "NO_LIVE_DEPLOYMENT_DECISION",
    ]
    driver_dims = {str(driver.get("dimension")) for driver in drivers if float(driver.get("tail_gt_20_pct") or 0.0) >= 30.0}
    if "h1_range_bucket" in driver_dims:
        flags.append("H1_RANGE_TAIL_DRIVER")
    if {"level_take_minute_bucket", "mae_reach_minute_bucket", "reentry_minute_bucket"} & driver_dims:
        flags.append("ENTRY_TIMING_TAIL_DRIVER")
    if "h1_reference_type" in driver_dims:
        flags.append("DOMINANT_H1_TAIL_DRIVER")
    if "direction" in driver_dims:
        flags.append("DIRECTIONAL_TAIL_ASYMMETRY")
    if "expansion_mae_ratio_bucket" in driver_dims:
        flags.append("EXPANSION_MAE_RATIO_TAIL_DRIVER")
    promising = hypotheses[hypotheses["verdict"].eq("PROMISING_DIAGNOSTIC")]
    too_broad = hypotheses[hypotheses["verdict"].eq("REJECTED_TOO_BROAD")]
    if not promising[promising["category"].eq("expansion_mae_ratio")].empty:
        flags.append("EXPANSION_MAE_RATIO_TAIL_DRIVER")
    if promising.empty:
        flags.append("NO_SIMPLE_HARDENING_FOUND")
    if promising.empty and not too_broad.empty:
        flags.append("HARDENING_REDUCES_TAIL_BUT_TOO_BROAD")
    raw = r_profiles[r_profiles["profile_label"].eq("RAW_CONTAINING")]
    best = r_profiles[~r_profiles["profile_label"].eq("RAW_CONTAINING")].copy()
    if not raw.empty and not best.empty:
        raw_tp4 = float(raw.iloc[0].get("tp4_R") or 0.0)
        best_tp4 = float(best["tp4_R"].fillna(0.0).max())
        if best_tp4 > raw_tp4 and best_tp4 >= 1.0:
            flags.append("R_PROFILE_IMPROVES_DIAGNOSTICALLY")
        elif best_tp4 > raw_tp4:
            flags.append("R_PROFILE_IMPROVES_BUT_LOW_SAMPLE")
    if promising.empty and too_broad.empty:
        flags.append("TAIL_RISK_NOT_REDUCED")
    return flags


def build_tail_risk_hardening(
    input_dir: str | Path,
    mechanical_dir: str | Path,
    *,
    pip_factor: float = 10.0,
) -> TailRiskHardeningResult:
    started = time.perf_counter()
    all_rows = load_containing_samples(mechanical_dir, pip_factor=pip_factor)
    samples = containing_valid_samples(all_rows)
    buckets = tail_bucket_profile(samples, pip_factor=pip_factor)
    drivers = tail_driver_breakdown(samples)
    hypotheses = hardening_hypotheses(samples, pip_factor=pip_factor)
    r_profiles = r_profiles_for_hypotheses(samples, hypotheses, pip_factor=pip_factor)
    top_cases = top_tail_cases(samples)
    strongest_drivers = strongest_tail_drivers(drivers)
    promising = hypotheses[hypotheses["verdict"].eq("PROMISING_DIAGNOSTIC")].sort_values(
        ["tail_gt_20_removed_pct", "tail_removed_pct", "body_removed_pct"],
        ascending=[False, False, True],
    )
    best_hypothesis = promising.iloc[0].to_dict() if not promising.empty else None
    if best_hypothesis is None and not hypotheses.empty:
        ranked = hypotheses.sort_values(["tail_gt_20_removed_pct", "tail_removed_pct", "body_removed_pct"], ascending=[False, False, True])
        best_hypothesis = ranked.iloc[0].to_dict()
        best_hypothesis["best_is_promising"] = False
    raw_r = r_profiles[r_profiles["profile_label"].eq("RAW_CONTAINING")].iloc[0].to_dict() if not r_profiles.empty else {}
    best_r = {}
    if best_hypothesis:
        row = r_profiles[r_profiles["profile_label"].eq(best_hypothesis["rule_name"])]
        if not row.empty:
            best_r = row.iloc[0].to_dict()
    runtime = round(time.perf_counter() - started, 4)
    flags = verdict_flags_for(hypotheses, strongest_drivers, r_profiles)
    summary = {
        "runtime_seconds": runtime,
        "source_input_dir": str(input_dir),
        "mechanical_dir": str(mechanical_dir),
        "primary_model": PRIMARY_MODEL,
        "samples_loaded": int(len(samples)),
        "tail_bucket_counts": buckets[["bucket", "count", "pct_of_samples"]].to_dict(orient="records"),
        "strongest_tail_drivers": strongest_drivers,
        "hardening_hypotheses_summary": hypotheses.to_dict(orient="records"),
        "best_diagnostic_hypothesis": best_hypothesis,
        "r_profile_before": raw_r,
        "r_profile_after_best_hypothesis": best_r,
        "pip_factor_used": float(pip_factor),
        "unit_note": "USD fields are XAUUSD price-distance/USD units; pips = USD * pip_factor.",
        "safety": SAFETY,
        "verdict_flags": flags,
    }
    return TailRiskHardeningResult(
        samples=samples,
        bucket_profile=buckets,
        driver_breakdown=drivers,
        hypotheses=hypotheses,
        r_profile=r_profiles,
        top_tail_cases=top_cases,
        summary=summary,
        report_markdown=tail_risk_report_markdown(summary, buckets, drivers, hypotheses, r_profiles, top_cases),
    )


def write_tail_risk_outputs(
    result: TailRiskHardeningResult,
    output_dir: str | Path,
    *,
    docs_path: str | Path | None = None,
) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "tail_bucket_profile": output / "tail_bucket_profile.csv",
        "tail_driver_breakdown": output / "tail_driver_breakdown.csv",
        "hardening_hypotheses": output / "hardening_hypotheses.csv",
        "hardening_r_profile": output / "hardening_r_profile.csv",
        "top_tail_cases": output / "top_tail_cases.csv",
        "summary": output / "tail_risk_hardening_summary.json",
        "report": output / "tail_risk_hardening_report.md",
    }
    result.bucket_profile.to_csv(paths["tail_bucket_profile"], index=False)
    result.driver_breakdown.to_csv(paths["tail_driver_breakdown"], index=False)
    result.hypotheses.to_csv(paths["hardening_hypotheses"], index=False)
    result.r_profile.to_csv(paths["hardening_r_profile"], index=False)
    result.top_tail_cases.to_csv(paths["top_tail_cases"], index=False)
    paths["summary"].write_text(json.dumps(result.summary, indent=2, sort_keys=True), encoding="utf-8")
    paths["report"].write_text(result.report_markdown, encoding="utf-8")
    if docs_path:
        docs = Path(docs_path)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(result.report_markdown, encoding="utf-8")
        paths["docs"] = docs
    return {key: str(path) for key, path in paths.items()}


def tail_risk_report_markdown(
    summary: dict[str, Any],
    buckets: pd.DataFrame,
    drivers: pd.DataFrame,
    hypotheses: pd.DataFrame,
    r_profiles: pd.DataFrame,
    top_cases: pd.DataFrame,
) -> str:
    lines = [
        "# Strategy 2 Tail Risk Hardening Diagnostics",
        "",
        "## Context",
        "",
        "`containing` is selected only as the next Strategy 2 diagnostic model. The prior containing diagnostic showed a structurally weak R-profile and a very large Max Excursion tail. This branch asks whether simple mechanical diagnostics can reduce that tail without changing the base strategy.",
        "",
        "## Safety",
        "",
        "- Strategy 3 untouched.",
        "- data/XAUUSD/*.csv untouched.",
        "- No live trading, Telegram, broker execution, orders, optimization, signal generation, grid search, ML, or runtime registration.",
        "",
        "## Method",
        "",
        "- Primary model: containing.",
        "- Tail buckets: <=8, <=10, <=12, >12, >20, >40, >100 USD.",
        "- Hypotheses are one-factor diagnostic probes using fixed buckets or descriptive percentiles only.",
        "- No PnL/PF, no parameter optimization, no final filter deployment.",
        f"- Unit conversion: pips = USD/price distance * {summary.get('pip_factor_used')}. Do not call USD values pips.",
        "",
        "## Body vs Tail Profile",
        "",
        "| Bucket | Count | % | Avg MAE | Median MAE | p95 MAE | Max MAE | Avg expansion | TP4_R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in buckets.iterrows():
        lines.append(
            f"| {row['bucket']} | {row['count']} | {row['pct_of_samples']} | {row['avg_mae_usd']} | {row['median_mae_usd']} | {row['p95_mae_usd']} | {row['max_mae_usd']} | {row['avg_expansion_usd']} | {row['tp4_R']} |"
        )
    lines.extend(["", "## Strongest Tail Drivers", "", "| Dimension | Bucket | Count | >12 % | >20 % | p95 MAE | Max MAE |"])
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for driver in summary.get("strongest_tail_drivers", []):
        lines.append(
            f"| {driver.get('dimension')} | {driver.get('bucket')} | {driver.get('count')} | {driver.get('tail_gt_12_pct')} | {driver.get('tail_gt_20_pct')} | {driver.get('mae_p95_usd')} | {driver.get('mae_max_usd')} |"
        )
    lines.extend(["", "## Hardening Hypotheses", "", "| Rule | Kept | Removed | Body removed % | Tail removed % | >20 removed % | SL after | TP4_R after | Verdict |"])
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for _, row in hypotheses.iterrows():
        lines.append(
            f"| {row['rule_name']} | {row['samples_kept']} | {row['samples_removed']} | {row['body_removed_pct']} | {row['tail_removed_pct']} | {row['tail_gt_20_removed_pct']} | {row.get('conservative_sl_after')} | {row.get('tp4_R_after')} | {row['verdict']} |"
        )
    raw = summary.get("r_profile_before", {})
    after = summary.get("r_profile_after_best_hypothesis", {})
    lines.extend(
        [
            "",
            "## R-Profile Impact",
            "",
            f"- Raw containing Max Excursion / Conservative SL: {raw.get('max_excursion_usd')} / {raw.get('conservative_sl_usd')} USD.",
            f"- Raw TP4_R: {raw.get('tp4_R')}.",
            f"- Best diagnostic hypothesis: `{summary.get('best_diagnostic_hypothesis', {}).get('rule_name') if summary.get('best_diagnostic_hypothesis') else None}`.",
            "- Important: expansion/MAE ratio is a diagnostic/ex-post tail driver here, not a deployable pre-entry filter.",
            f"- After-hypothesis Max Excursion / Conservative SL: {after.get('max_excursion_usd')} / {after.get('conservative_sl_usd')} USD.",
            f"- After-hypothesis TP4_R: {after.get('tp4_R')}.",
            "",
            "## Top Tail Cases",
            "",
            "| Sample | Direction | H1 ref | Session | Hour | MAE USD | Expansion USD | Ratio |",
            "|---|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for _, row in top_cases.head(10).iterrows():
        lines.append(
            f"| {row.get('sample_id')} | {row.get('direction')} | {row.get('h1_reference_type')} | {row.get('session')} | {row.get('hour')} | {row.get('manipulation_depth_usd')} | {row.get('expansion_usd')} | {row.get('expansion_mae_ratio')} |"
        )
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            "This diagnostic does not prove edge and does not create a filter. If the only meaningful tail reduction comes from broad or ex-post rules, Strategy 2 should remain research-only or be paused rather than forced.",
            "",
            "## Verdict Flags",
            "",
            *[f"- {flag}" for flag in summary.get("verdict_flags", [])],
            "",
            "## Next Strategy 2-Only Step",
            "",
            "- If one simple hypothesis is promising: feat/strategy-2-hardening-hypothesis-validation",
            "- If no simple hypothesis helps: feat/strategy-2-research-pause-summary",
            "- If H1 dominant is main cause: feat/strategy-2-dominant-h1-hardening",
            "- If entry timing is main cause: feat/strategy-2-entry-timing-diagnostic",
        ]
    )
    return "\n".join(lines) + "\n"
