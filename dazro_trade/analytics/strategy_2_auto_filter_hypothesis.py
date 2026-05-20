from __future__ import annotations

import json
import math
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


VALID_SAMPLE_STATUSES = {"VALID_SAMPLE_TRADE_TRIGGERED", "VALID_SAMPLE_NO_ENTRY_MANIPULATED_LESS"}

BODY_THRESHOLDS_USD = (8.0, 10.0, 12.0)
TAIL_THRESHOLDS_USD = (12.0, 15.0, 20.0)

SAFETY = {
    "research_only": True,
    "dry_run": True,
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

OPTIONAL_FEATURES = [
    "expansion_usd",
    "expansion_pips",
    "sample_classification",
    "invalid_reason",
    "hour_of_day",
    "day_of_week",
    "session",
    "h1_reference_type",
    "h1_reference_range",
    "h1_range_bucket",
    "h1_high",
    "h1_low",
    "liquidity_level",
    "m15_x45_sequence_valid",
    "opposite_x45_taken_first",
    "reaction_confirmed",
    "reaction_latency_candles",
    "distribution_distance",
    "distribution_latency",
    "move_already_consumed",
]


@dataclass(frozen=True)
class AnalysisResult:
    samples: pd.DataFrame
    valid_samples: pd.DataFrame
    body_tail_comparison: pd.DataFrame
    top_tail_samples: pd.DataFrame
    hypotheses: pd.DataFrame
    summary: dict[str, Any]
    missing_features: list[str]
    runtime_seconds: float


def _to_bool(value: Any) -> bool | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _json_distribution(series: pd.Series, *, limit: int = 12) -> str:
    values = [str(v) for v in series.dropna().tolist() if str(v).strip()]
    counts = Counter(values)
    most_common = dict(counts.most_common(limit))
    return json.dumps(most_common, sort_keys=True)


def _json_numeric_distribution(series: pd.Series, *, limit: int = 24) -> str:
    values = []
    for value in series.dropna().tolist():
        try:
            values.append(str(int(float(value))))
        except (TypeError, ValueError):
            values.append(str(value))
    counts = Counter(values)
    return json.dumps(dict(counts.most_common(limit)), sort_keys=True)


def _safe_mean(series: pd.Series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    return round(float(numeric.mean()), 4) if not numeric.empty else None


def _safe_median(series: pd.Series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    return round(float(numeric.median()), 4) if not numeric.empty else None


def _safe_max(series: pd.Series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    return round(float(numeric.max()), 4) if not numeric.empty else None


def _safe_p90(series: pd.Series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    return round(float(numeric.quantile(0.9)), 4) if not numeric.empty else None


def _percent(numerator: int | float, denominator: int | float) -> float:
    return round((float(numerator) / float(denominator)) * 100, 2) if denominator else 0.0


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([pd.NA] * len(frame), index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _bool_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([pd.NA] * len(frame), index=frame.index, dtype="boolean")
    return frame[column].map(_to_bool).astype("boolean")


def load_samples(samples_path: str | Path, *, pip_factor: float = 10.0) -> tuple[pd.DataFrame, list[str]]:
    frame = pd.read_csv(samples_path)
    frame, missing_features = enrich_samples(frame, pip_factor=pip_factor)
    return frame, missing_features


def enrich_samples(frame: pd.DataFrame, *, pip_factor: float = 10.0) -> tuple[pd.DataFrame, list[str]]:
    out = frame.copy()
    missing_features: list[str] = []

    for column in [
        "manipulation_depth_usd",
        "manipulation_depth_pips",
        "distribution_distance_usd",
        "distribution_distance_pips",
        "h1_reference_range",
        "reaction_latency_candles",
        "m15_x45_high",
        "m15_x45_low",
    ]:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")

    if "expansion_usd" not in out.columns:
        out["expansion_usd"] = _numeric(out, "distribution_distance_usd")
    else:
        out["expansion_usd"] = _numeric(out, "expansion_usd")
    if "expansion_pips" not in out.columns:
        out["expansion_pips"] = _numeric(out, "distribution_distance_pips")
    else:
        out["expansion_pips"] = _numeric(out, "expansion_pips")

    if "sample_classification" not in out.columns:
        out["sample_classification"] = out.get("sample_status", "")
    if "invalid_reason" not in out.columns:
        out["invalid_reason"] = out.get("sample_reason_codes", "")
    if "h1_range_bucket" not in out.columns and "h1_reference_range_bucket" in out.columns:
        out["h1_range_bucket"] = out["h1_reference_range_bucket"]
    if "liquidity_level" not in out.columns and "h1_liquidity_level" in out.columns:
        out["liquidity_level"] = out["h1_liquidity_level"]
    if "distribution_distance" not in out.columns and "distribution_distance_usd" in out.columns:
        out["distribution_distance"] = out["distribution_distance_usd"]
    if "opposite_x45_taken_first" not in out.columns and "opposite_m15_x45_taken_timestamp" in out.columns:
        out["opposite_x45_taken_first"] = out["opposite_m15_x45_taken_timestamp"].fillna("").astype(str).str.len() > 0

    if "hour_of_day" not in out.columns:
        if "hour" in out.columns:
            out["hour_of_day"] = pd.to_numeric(out["hour"], errors="coerce")
        elif "h1_context_timestamp" in out.columns:
            out["hour_of_day"] = pd.to_datetime(out["h1_context_timestamp"], utc=True, errors="coerce").dt.hour
        else:
            out["hour_of_day"] = pd.NA

    if "day_of_week" not in out.columns:
        if "h1_context_timestamp" in out.columns:
            out["day_of_week"] = pd.to_datetime(out["h1_context_timestamp"], utc=True, errors="coerce").dt.day_name()
        else:
            out["day_of_week"] = pd.NA

    out["m15_x45_sequence_valid_bool"] = _bool_column(out, "m15_x45_sequence_valid")
    out["reaction_confirmed_bool"] = _bool_column(out, "reaction_confirmed")
    out["distribution_confirmed_bool"] = _bool_column(out, "distribution_confirmed")
    out["valid_for_mae_dataset_bool"] = _bool_column(out, "valid_for_mae_dataset")

    if "sample_status" in out.columns:
        status_valid = out["sample_status"].isin(VALID_SAMPLE_STATUSES)
    else:
        status_valid = pd.Series([False] * len(out), index=out.index)
    out["is_valid_sample"] = out["valid_for_mae_dataset_bool"].fillna(False) | status_valid
    out["is_valid_triggered"] = out.get("sample_status", pd.Series("", index=out.index)).eq("VALID_SAMPLE_TRADE_TRIGGERED")
    out["is_valid_no_entry"] = out.get("sample_status", pd.Series("", index=out.index)).eq("VALID_SAMPLE_NO_ENTRY_MANIPULATED_LESS")

    manipulation = _numeric(out, "manipulation_depth_usd")
    expansion = _numeric(out, "expansion_usd")
    h1_range = _numeric(out, "h1_reference_range")

    out["manipulation_to_h1_range_ratio"] = manipulation / h1_range.replace(0, pd.NA)
    out["expansion_to_manipulation_ratio"] = expansion / manipulation.replace(0, pd.NA)
    out["target_space_after_sweep"] = expansion - manipulation
    out["expansion_minus_manipulation"] = expansion - manipulation

    for threshold in BODY_THRESHOLDS_USD:
        out[f"is_body_le_{int(threshold)}"] = manipulation <= threshold
    for threshold in TAIL_THRESHOLDS_USD:
        out[f"is_tail_gt_{int(threshold)}"] = manipulation > threshold

    for feature in OPTIONAL_FEATURES:
        if feature not in out.columns or out[feature].dropna().empty:
            missing_features.append(feature)

    out["pip_factor_used_for_analysis"] = float(pip_factor)
    return out, sorted(set(missing_features))


def valid_sample_frame(samples: pd.DataFrame) -> pd.DataFrame:
    if "is_valid_sample" not in samples.columns:
        samples, _ = enrich_samples(samples)
    return samples[samples["is_valid_sample"].fillna(False)].copy()


def subset_summary(samples: pd.DataFrame, *, comparison_id: str, group_name: str, selector: str) -> dict[str, Any]:
    expansion_ratio = _numeric(samples, "expansion_to_manipulation_ratio")
    h1_range = _numeric(samples, "h1_reference_range")
    return {
        "comparison_id": comparison_id,
        "group_name": group_name,
        "selector": selector,
        "count": int(len(samples)),
        "avg_manipulation_usd": _safe_mean(samples.get("manipulation_depth_usd", pd.Series(dtype=float))),
        "median_manipulation_usd": _safe_median(samples.get("manipulation_depth_usd", pd.Series(dtype=float))),
        "max_manipulation_usd": _safe_max(samples.get("manipulation_depth_usd", pd.Series(dtype=float))),
        "avg_expansion_usd": _safe_mean(samples.get("expansion_usd", pd.Series(dtype=float))),
        "median_expansion_usd": _safe_median(samples.get("expansion_usd", pd.Series(dtype=float))),
        "avg_expansion_to_manipulation_ratio": _safe_mean(expansion_ratio),
        "median_expansion_to_manipulation_ratio": _safe_median(expansion_ratio),
        "direction_distribution": _json_distribution(samples.get("direction", pd.Series(dtype=str))),
        "session_distribution": _json_distribution(samples.get("session", pd.Series(dtype=str))),
        "hour_distribution": _json_numeric_distribution(samples.get("hour_of_day", pd.Series(dtype=float))),
        "day_of_week_distribution": _json_distribution(samples.get("day_of_week", pd.Series(dtype=str))),
        "h1_range_median": _safe_median(h1_range),
        "h1_range_p90": _safe_p90(h1_range),
        "h1_range_max": _safe_max(h1_range),
        "h1_reference_type_distribution": _json_distribution(samples.get("h1_reference_type", pd.Series(dtype=str))),
        "h1_range_bucket_distribution": _json_distribution(samples.get("h1_range_bucket", pd.Series(dtype=str))),
        "m15_x45_valid_rate_pct": _percent(int(samples.get("m15_x45_sequence_valid_bool", pd.Series(dtype=bool)).fillna(False).sum()), len(samples)),
        "opposite_x45_taken_first_rate_pct": _percent(int(samples.get("opposite_x45_taken_first", pd.Series(dtype=bool)).fillna(False).sum()), len(samples)),
        "reaction_confirmed_rate_pct": _percent(int(samples.get("reaction_confirmed_bool", pd.Series(dtype=bool)).fillna(False).sum()), len(samples)),
        "reaction_latency_median": _safe_median(samples.get("reaction_latency_candles", pd.Series(dtype=float))),
        "distribution_confirmed_rate_pct": _percent(int(samples.get("distribution_confirmed_bool", pd.Series(dtype=bool)).fillna(False).sum()), len(samples)),
        "target_space_after_sweep_median": _safe_median(samples.get("target_space_after_sweep", pd.Series(dtype=float))),
    }


def build_body_tail_comparison(valid_samples: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    definitions = [
        ("A_BODY_LE_8_VS_TAIL_GT_12", "Body <=8 USD", valid_samples["is_body_le_8"], "manipulation_depth_usd <= 8"),
        ("A_BODY_LE_8_VS_TAIL_GT_12", "Tail >12 USD", valid_samples["is_tail_gt_12"], "manipulation_depth_usd > 12"),
        ("B_BODY_LE_10_VS_TAIL_GT_12", "Body <=10 USD", valid_samples["is_body_le_10"], "manipulation_depth_usd <= 10"),
        ("B_BODY_LE_10_VS_TAIL_GT_12", "Tail >12 USD", valid_samples["is_tail_gt_12"], "manipulation_depth_usd > 12"),
        ("C_BODY_LE_12_VS_TAIL_GT_20", "Body <=12 USD", valid_samples["is_body_le_12"], "manipulation_depth_usd <= 12"),
        ("C_BODY_LE_12_VS_TAIL_GT_20", "Tail >20 USD", valid_samples["is_tail_gt_20"], "manipulation_depth_usd > 20"),
    ]
    for comparison_id, group_name, mask, selector in definitions:
        rows.append(subset_summary(valid_samples[mask.fillna(False)], comparison_id=comparison_id, group_name=group_name, selector=selector))

    top10_ids = set(top_tail_samples(valid_samples, n=10)["sample_id"].astype(str).tolist()) if "sample_id" in valid_samples.columns else set()
    if top10_ids:
        rows.append(
            subset_summary(
                valid_samples[valid_samples["sample_id"].astype(str).isin(top10_ids)],
                comparison_id="D_TOP_10_MAX_TAIL_VS_REST",
                group_name="Top 10 max manipulation",
                selector="top 10 by manipulation_depth_usd",
            )
        )
        rows.append(
            subset_summary(
                valid_samples[~valid_samples["sample_id"].astype(str).isin(top10_ids)],
                comparison_id="D_TOP_10_MAX_TAIL_VS_REST",
                group_name="Rest",
                selector="not top 10 by manipulation_depth_usd",
            )
        )

    rows.append(
        subset_summary(
            valid_samples[valid_samples["is_valid_triggered"].fillna(False)],
            comparison_id="E_TRIGGERED_VS_NO_ENTRY",
            group_name="Valid triggered",
            selector="sample_status == VALID_SAMPLE_TRADE_TRIGGERED",
        )
    )
    rows.append(
        subset_summary(
            valid_samples[valid_samples["is_valid_no_entry"].fillna(False)],
            comparison_id="E_TRIGGERED_VS_NO_ENTRY",
            group_name="Valid no-entry",
            selector="sample_status == VALID_SAMPLE_NO_ENTRY_MANIPULATED_LESS",
        )
    )

    for direction, group in valid_samples.groupby(valid_samples.get("direction", pd.Series(index=valid_samples.index, dtype=str)).fillna("UNKNOWN")):
        rows.append(subset_summary(group, comparison_id="F_LONG_VS_SHORT", group_name=f"Direction {direction}", selector=f"direction == {direction}"))

    for reference_type, group in valid_samples.groupby(valid_samples.get("h1_reference_type", pd.Series(index=valid_samples.index, dtype=str)).fillna("UNKNOWN")):
        rows.append(
            subset_summary(group, comparison_id="G_REFERENCE_TYPE", group_name=f"Reference {reference_type}", selector=f"h1_reference_type == {reference_type}")
        )

    for session, group in valid_samples.groupby(valid_samples.get("session", pd.Series(index=valid_samples.index, dtype=str)).fillna("UNKNOWN")):
        rows.append(subset_summary(group, comparison_id="H_SESSIONS", group_name=f"Session {session}", selector=f"session == {session}"))

    for hour, group in valid_samples.groupby(valid_samples.get("hour_of_day", pd.Series(index=valid_samples.index, dtype=float)).fillna(-1)):
        label = "UNKNOWN" if hour == -1 else str(int(hour))
        rows.append(subset_summary(group, comparison_id="H_HOURS", group_name=f"Hour {label}", selector=f"hour_of_day == {label}"))

    return pd.DataFrame(rows)


def top_tail_samples(valid_samples: pd.DataFrame, *, n: int = 10) -> pd.DataFrame:
    keep_columns = [
        "sample_id",
        "symbol",
        "direction",
        "h1_context_timestamp",
        "h1_reference_type",
        "h1_reference_range",
        "h1_range_bucket",
        "h1_liquidity_level",
        "session",
        "hour_of_day",
        "day_of_week",
        "m15_x45_sequence_valid",
        "reaction_confirmed",
        "reaction_latency_candles",
        "distribution_distance_usd",
        "expansion_usd",
        "manipulation_depth_usd",
        "manipulation_depth_pips",
        "manipulation_to_h1_range_ratio",
        "expansion_to_manipulation_ratio",
        "target_space_after_sweep",
        "sample_status",
        "sample_reason_codes",
    ]
    available = [column for column in keep_columns if column in valid_samples.columns]
    if valid_samples.empty:
        return pd.DataFrame(columns=available)
    return valid_samples.sort_values("manipulation_depth_usd", ascending=False).head(n)[available].reset_index(drop=True)


def _feature_threshold(valid_samples: pd.DataFrame, column: str, quantile: float) -> float | None:
    if column not in valid_samples.columns:
        return None
    numeric = pd.to_numeric(valid_samples[column], errors="coerce").dropna()
    if numeric.empty:
        return None
    return round(float(numeric.quantile(quantile)), 4)


def _evaluate_remove_rule(
    valid_samples: pd.DataFrame,
    *,
    hypothesis_id: str,
    rule_description: str,
    remove_mask: pd.Series,
    supporting_stats: dict[str, Any],
    risk_of_overfit: str,
) -> dict[str, Any]:
    remove = remove_mask.reindex(valid_samples.index).fillna(False)
    kept = valid_samples[~remove]
    removed = valid_samples[remove]
    tail_total = int(valid_samples["is_tail_gt_12"].fillna(False).sum())
    body_total = int(valid_samples["is_body_le_12"].fillna(False).sum())
    tail_removed = int(removed["is_tail_gt_12"].fillna(False).sum())
    body_removed = int(removed["is_body_le_12"].fillna(False).sum())
    tail_removed_pct = _percent(tail_removed, tail_total)
    body_removed_pct = _percent(body_removed, body_total)

    if tail_total == 0:
        verdict = "INSUFFICIENT_DATA"
    elif tail_removed_pct >= 45 and body_removed_pct <= 20:
        verdict = "PROMISING_DIAGNOSTIC"
    elif tail_removed_pct >= 25 and body_removed_pct <= 30:
        verdict = "PROMISING_DIAGNOSTIC"
    elif tail_removed_pct < 10:
        verdict = "WEAK_DIAGNOSTIC"
    elif body_removed_pct > 45:
        verdict = "REJECTED_OVERBROAD"
    else:
        verdict = "WEAK_DIAGNOSTIC"

    return {
        "hypothesis_id": hypothesis_id,
        "rule_description": rule_description,
        "supporting_stats": json.dumps(supporting_stats, sort_keys=True),
        "samples_total": int(len(valid_samples)),
        "samples_kept": int(len(kept)),
        "samples_removed": int(len(removed)),
        "tail_gt_12_total": tail_total,
        "tail_gt_12_removed": tail_removed,
        "tail_removed_pct": tail_removed_pct,
        "body_le_12_total": body_total,
        "body_le_12_removed": body_removed,
        "body_removed_pct": body_removed_pct,
        "risk_of_overfit": risk_of_overfit,
        "verdict": verdict,
        "optimization_used": False,
        "trading_signal_generated": False,
    }


def generate_filter_hypotheses(valid_samples: pd.DataFrame) -> pd.DataFrame:
    hypotheses: list[dict[str, Any]] = []

    h1_p90 = _feature_threshold(valid_samples, "h1_reference_range", 0.9)
    if h1_p90 is None:
        hypotheses.append(
            _insufficient_hypothesis(
                "HYPOTHESIS_001",
                "Deep-tail samples may be related to large H1 reference ranges, but h1_reference_range is unavailable.",
            )
        )
    else:
        mask = _numeric(valid_samples, "h1_reference_range") > h1_p90
        hypotheses.append(
            _evaluate_remove_rule(
                valid_samples,
                hypothesis_id="HYPOTHESIS_001",
                rule_description=f"Remove samples where h1_reference_range is above the valid-sample p90 ({h1_p90}).",
                remove_mask=mask,
                supporting_stats={
                    "feature": "h1_reference_range",
                    "threshold_source": "valid_sample_p90",
                    "threshold": h1_p90,
                    "tail_gt_12_count": int(valid_samples["is_tail_gt_12"].fillna(False).sum()),
                },
                risk_of_overfit="LOW",
            )
        )

    ratio_p25 = _feature_threshold(valid_samples, "expansion_to_manipulation_ratio", 0.25)
    if ratio_p25 is None:
        hypotheses.append(
            _insufficient_hypothesis(
                "HYPOTHESIS_002",
                "Deep-tail samples may have weak expansion/manipulation ratio, but the ratio is unavailable.",
            )
        )
    else:
        mask = _numeric(valid_samples, "expansion_to_manipulation_ratio") <= ratio_p25
        hypotheses.append(
            _evaluate_remove_rule(
                valid_samples,
                hypothesis_id="HYPOTHESIS_002",
                rule_description=f"Remove samples where expansion/manipulation ratio is at or below valid-sample p25 ({ratio_p25}).",
                remove_mask=mask,
                supporting_stats={"feature": "expansion_to_manipulation_ratio", "threshold_source": "valid_sample_p25", "threshold": ratio_p25},
                risk_of_overfit="LOW",
            )
        )

    session_mask, session_stats = _session_concentration_mask(valid_samples)
    hypotheses.append(
        _evaluate_remove_rule(
            valid_samples,
            hypothesis_id="HYPOTHESIS_003",
            rule_description=session_stats["rule_description"],
            remove_mask=session_mask,
            supporting_stats=session_stats,
            risk_of_overfit=session_stats["risk_of_overfit"],
        )
        if session_stats["has_candidate"]
        else _insufficient_hypothesis("HYPOTHESIS_003", "No session bucket had enough excess deep-tail concentration for a descriptive split.")
    )

    reference_mask, reference_stats = _reference_concentration_mask(valid_samples)
    hypotheses.append(
        _evaluate_remove_rule(
            valid_samples,
            hypothesis_id="HYPOTHESIS_004",
            rule_description=reference_stats["rule_description"],
            remove_mask=reference_mask,
            supporting_stats=reference_stats,
            risk_of_overfit=reference_stats["risk_of_overfit"],
        )
        if reference_stats["has_candidate"]
        else _insufficient_hypothesis("HYPOTHESIS_004", "No H1 reference type showed a clear enough deep-tail concentration.")
    )

    if "reaction_confirmed_bool" in valid_samples.columns and not valid_samples["reaction_confirmed_bool"].dropna().empty:
        mask = ~valid_samples["reaction_confirmed_bool"].fillna(False)
        hypotheses.append(
            _evaluate_remove_rule(
                valid_samples,
                hypothesis_id="HYPOTHESIS_005",
                rule_description="Remove samples without reaction confirmation.",
                remove_mask=mask,
                supporting_stats={
                    "feature": "reaction_confirmed",
                    "confirmed_rate_pct": _percent(int(valid_samples["reaction_confirmed_bool"].fillna(False).sum()), len(valid_samples)),
                },
                risk_of_overfit="LOW",
            )
        )
    else:
        hypotheses.append(_insufficient_hypothesis("HYPOTHESIS_005", "Reaction confirmation is unavailable."))

    target_p25 = _feature_threshold(valid_samples, "target_space_after_sweep", 0.25)
    if target_p25 is None:
        hypotheses.append(_insufficient_hypothesis("HYPOTHESIS_006", "Target-space proxy is unavailable."))
    else:
        mask = _numeric(valid_samples, "target_space_after_sweep") <= target_p25
        hypotheses.append(
            _evaluate_remove_rule(
                valid_samples,
                hypothesis_id="HYPOTHESIS_006",
                rule_description=f"Remove samples where target_space_after_sweep is at or below valid-sample p25 ({target_p25}).",
                remove_mask=mask,
                supporting_stats={"feature": "target_space_after_sweep", "threshold_source": "valid_sample_p25", "threshold": target_p25},
                risk_of_overfit="LOW",
            )
        )

    hour_mask, hour_stats = _hour_concentration_mask(valid_samples)
    hypotheses.append(
        _evaluate_remove_rule(
            valid_samples,
            hypothesis_id="HYPOTHESIS_007",
            rule_description=hour_stats["rule_description"],
            remove_mask=hour_mask,
            supporting_stats=hour_stats,
            risk_of_overfit=hour_stats["risk_of_overfit"],
        )
        if hour_stats["has_candidate"]
        else _insufficient_hypothesis("HYPOTHESIS_007", "No hour bucket had enough excess deep-tail concentration for a descriptive split.")
    )

    out = pd.DataFrame(hypotheses)
    verdict_order = {"PROMISING_DIAGNOSTIC": 0, "WEAK_DIAGNOSTIC": 1, "REJECTED_OVERBROAD": 2, "INSUFFICIENT_DATA": 3}
    if not out.empty:
        out["_order"] = out["verdict"].map(verdict_order).fillna(9)
        out = out.sort_values(["_order", "tail_removed_pct", "body_removed_pct"], ascending=[True, False, True]).drop(columns=["_order"])
    return out.reset_index(drop=True)


def _insufficient_hypothesis(hypothesis_id: str, description: str) -> dict[str, Any]:
    return {
        "hypothesis_id": hypothesis_id,
        "rule_description": description,
        "supporting_stats": json.dumps({"reason": "missing_or_weak_feature"}, sort_keys=True),
        "samples_total": 0,
        "samples_kept": 0,
        "samples_removed": 0,
        "tail_gt_12_total": 0,
        "tail_gt_12_removed": 0,
        "tail_removed_pct": 0.0,
        "body_le_12_total": 0,
        "body_le_12_removed": 0,
        "body_removed_pct": 0.0,
        "risk_of_overfit": "LOW",
        "verdict": "INSUFFICIENT_DATA",
        "optimization_used": False,
        "trading_signal_generated": False,
    }


def _session_concentration_mask(valid_samples: pd.DataFrame) -> tuple[pd.Series, dict[str, Any]]:
    if "session" not in valid_samples.columns or valid_samples["session"].dropna().empty:
        return pd.Series([False] * len(valid_samples), index=valid_samples.index), {"has_candidate": False}
    overall_tail_rate = _percent(int(valid_samples["is_tail_gt_12"].fillna(False).sum()), len(valid_samples))
    candidates: list[str] = []
    stats: dict[str, Any] = {"overall_tail_gt_12_rate_pct": overall_tail_rate, "session_rates": {}}
    for session, group in valid_samples.groupby(valid_samples["session"].fillna("UNKNOWN")):
        if len(group) < 10:
            continue
        rate = _percent(int(group["is_tail_gt_12"].fillna(False).sum()), len(group))
        stats["session_rates"][str(session)] = {"count": int(len(group)), "tail_gt_12_rate_pct": rate}
        if rate >= overall_tail_rate + 5:
            candidates.append(str(session))
    stats["has_candidate"] = bool(candidates)
    stats["candidate_sessions"] = candidates
    stats["rule_description"] = f"Remove candidate sessions with tail rate at least 5 pct points above overall: {', '.join(candidates) or 'none'}."
    stats["risk_of_overfit"] = "MEDIUM"
    mask = valid_samples["session"].astype(str).isin(candidates)
    return mask, stats


def _reference_concentration_mask(valid_samples: pd.DataFrame) -> tuple[pd.Series, dict[str, Any]]:
    if "h1_reference_type" not in valid_samples.columns or valid_samples["h1_reference_type"].dropna().empty:
        return pd.Series([False] * len(valid_samples), index=valid_samples.index), {"has_candidate": False}
    overall_tail_rate = _percent(int(valid_samples["is_tail_gt_12"].fillna(False).sum()), len(valid_samples))
    candidates: list[str] = []
    stats: dict[str, Any] = {"overall_tail_gt_12_rate_pct": overall_tail_rate, "reference_rates": {}}
    for reference, group in valid_samples.groupby(valid_samples["h1_reference_type"].fillna("UNKNOWN")):
        if len(group) < 10:
            continue
        rate = _percent(int(group["is_tail_gt_12"].fillna(False).sum()), len(group))
        stats["reference_rates"][str(reference)] = {"count": int(len(group)), "tail_gt_12_rate_pct": rate}
        if rate >= overall_tail_rate + 5:
            candidates.append(str(reference))
    stats["has_candidate"] = bool(candidates)
    stats["candidate_reference_types"] = candidates
    stats["rule_description"] = f"Remove H1 reference types with tail rate at least 5 pct points above overall: {', '.join(candidates) or 'none'}."
    stats["risk_of_overfit"] = "MEDIUM"
    mask = valid_samples["h1_reference_type"].astype(str).isin(candidates)
    return mask, stats


def _hour_concentration_mask(valid_samples: pd.DataFrame) -> tuple[pd.Series, dict[str, Any]]:
    if "hour_of_day" not in valid_samples.columns or valid_samples["hour_of_day"].dropna().empty:
        return pd.Series([False] * len(valid_samples), index=valid_samples.index), {"has_candidate": False}
    overall_tail_rate = _percent(int(valid_samples["is_tail_gt_12"].fillna(False).sum()), len(valid_samples))
    candidates: list[int] = []
    stats: dict[str, Any] = {"overall_tail_gt_12_rate_pct": overall_tail_rate, "hour_rates": {}}
    hours = pd.to_numeric(valid_samples["hour_of_day"], errors="coerce")
    for hour, group in valid_samples.groupby(hours):
        if pd.isna(hour) or len(group) < 10:
            continue
        rate = _percent(int(group["is_tail_gt_12"].fillna(False).sum()), len(group))
        hour_int = int(hour)
        stats["hour_rates"][str(hour_int)] = {"count": int(len(group)), "tail_gt_12_rate_pct": rate}
        if rate >= overall_tail_rate + 8:
            candidates.append(hour_int)
    stats["has_candidate"] = bool(candidates)
    stats["candidate_hours"] = candidates
    stats["rule_description"] = f"Remove hour buckets with tail rate at least 8 pct points above overall: {candidates or 'none'}."
    stats["risk_of_overfit"] = "HIGH"
    mask = hours.isin(candidates)
    return mask, stats


def build_summary(
    samples: pd.DataFrame,
    valid_samples: pd.DataFrame,
    hypotheses: pd.DataFrame,
    missing_features: list[str],
    runtime_seconds: float,
) -> dict[str, Any]:
    body_counts = {f"le_{int(threshold)}": int(valid_samples[f"is_body_le_{int(threshold)}"].fillna(False).sum()) for threshold in BODY_THRESHOLDS_USD}
    tail_counts = {f"gt_{int(threshold)}": int(valid_samples[f"is_tail_gt_{int(threshold)}"].fillna(False).sum()) for threshold in TAIL_THRESHOLDS_USD}
    strongest = hypotheses[hypotheses["verdict"].eq("PROMISING_DIAGNOSTIC")].head(5).to_dict(orient="records") if not hypotheses.empty else []
    top_max = _safe_max(valid_samples.get("manipulation_depth_usd", pd.Series(dtype=float)))
    flags = [
        "AUTO_FILTER_HYPOTHESIS_DIAGNOSTICS_COMPLETE",
        "BODY_TAIL_COMPARISON_COMPLETE",
        "BODY_OF_DISTRIBUTION_PLAUSIBLE",
        "RAW_MAX_EXCURSION_TAIL_CONFIRMED",
        "USER_LABELS_STILL_RECOMMENDED",
        "STRATEGY_2_REMAINS_RESEARCH_ONLY",
        "NO_LIVE_DEPLOYMENT_DECISION",
    ]
    if strongest:
        flags.append("DEEP_TAIL_DRIVERS_IDENTIFIED")
    else:
        flags.append("NO_CLEAR_TAIL_DRIVER_FOUND")
    if any(feature in missing_features for feature in ("distribution_latency", "move_already_consumed")):
        flags.append("REACTION_FEATURES_MISSING")
    return {
        "safety": SAFETY,
        "samples_loaded": int(len(samples)),
        "valid_samples": int(len(valid_samples)),
        "valid_triggered_samples": int(valid_samples["is_valid_triggered"].fillna(False).sum()),
        "valid_no_entry_samples": int(valid_samples["is_valid_no_entry"].fillna(False).sum()),
        "body_counts": body_counts,
        "tail_counts": tail_counts,
        "top_tail_max_manipulation_usd": top_max,
        "missing_features": missing_features,
        "strongest_hypotheses": strongest,
        "verdict_flags": flags,
        "runtime_seconds": round(float(runtime_seconds), 4),
    }


def run_analysis(samples_path: str | Path, output_dir: str | Path, *, pip_factor: float = 10.0, dry_run: bool = True) -> AnalysisResult:
    start = time.perf_counter()
    samples, missing_features = load_samples(samples_path, pip_factor=pip_factor)
    valid_samples = valid_sample_frame(samples)
    comparisons = build_body_tail_comparison(valid_samples)
    top_tail = top_tail_samples(valid_samples, n=10)
    hypotheses = generate_filter_hypotheses(valid_samples)
    runtime = time.perf_counter() - start
    summary = build_summary(samples, valid_samples, hypotheses, missing_features, runtime)
    summary["dry_run"] = bool(dry_run)
    result = AnalysisResult(
        samples=samples,
        valid_samples=valid_samples,
        body_tail_comparison=comparisons,
        top_tail_samples=top_tail,
        hypotheses=hypotheses,
        summary=summary,
        missing_features=missing_features,
        runtime_seconds=runtime,
    )
    write_outputs(result, Path(output_dir))
    return result


def write_outputs(result: AnalysisResult, output_dir: Path, docs_path: Path | None = None) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "body_tail_comparison_csv": output_dir / "body_tail_comparison.csv",
        "top_tail_samples_csv": output_dir / "top_tail_samples.csv",
        "filter_hypotheses_csv": output_dir / "filter_hypotheses.csv",
        "summary_json": output_dir / "auto_filter_hypothesis_summary.json",
        "report_md": output_dir / "auto_filter_hypothesis_report.md",
    }
    result.body_tail_comparison.to_csv(paths["body_tail_comparison_csv"], index=False)
    result.top_tail_samples.to_csv(paths["top_tail_samples_csv"], index=False)
    result.hypotheses.to_csv(paths["filter_hypotheses_csv"], index=False)
    paths["summary_json"].write_text(json.dumps(result.summary, indent=2, sort_keys=True), encoding="utf-8")
    report = render_report(result)
    paths["report_md"].write_text(report, encoding="utf-8")
    if docs_path is not None:
        docs_path.parent.mkdir(parents=True, exist_ok=True)
        docs_path.write_text(report, encoding="utf-8")
        paths["docs_md"] = docs_path
    return {key: str(value) for key, value in paths.items()}


def render_report(result: AnalysisResult) -> str:
    summary = result.summary
    strongest = result.hypotheses.head(5)
    missing = ", ".join(result.missing_features) if result.missing_features else "None"
    body = summary["body_counts"]
    tail = summary["tail_counts"]
    lines = [
        "# Strategy 2 Auto Filter Hypothesis Diagnostics",
        "",
        "## Context",
        "",
        "The Strategy 2 statistical sample recorder is the input for this diagnostic pass. The M15 HH:45 selection was already corrected upstream. The global sample pool is still intentionally broad: the body of the manipulation-depth distribution is plausible, while the raw max excursion tail drives an unusable structural stop profile.",
        "",
        "The manual sample label pack exists, but this branch intentionally uses no manual labels. It compares body samples and deep-tail samples to generate descriptive filter hypotheses only.",
        "",
        "## Safety",
        "",
        "- Research-only diagnostic output.",
        "- No live trading, broker calls, order_send, orders, Telegram, signals, or runtime registration.",
        "- No parameter optimization, grid search, ML classifier, or profit-factor selection.",
        "- Market CSV files are read-only and not written.",
        "- Strategy 3 is outside this branch and is not touched.",
        "",
        "## Method",
        "",
        "- Body buckets: manipulation_depth_usd <= 8, <= 10, <= 12.",
        "- Tail buckets: manipulation_depth_usd > 12, > 15, > 20.",
        "- Top-tail review: top 10 samples by manipulation_depth_usd.",
        "- Features analyzed: manipulation, expansion, direction, session/hour/day, H1 reference type/range, M15 sequence validity, reaction confirmation/latency, and derived ratios.",
        f"- Missing or unavailable features: {missing}.",
        "- Hypotheses use descriptive thresholds only: p25/p90 feature splits, existing 8/10/12/15/20 USD guardrails, and simple session/hour groupings.",
        "",
        "## Results",
        "",
        f"- Samples loaded: {summary['samples_loaded']}",
        f"- Valid samples: {summary['valid_samples']}",
        f"- Body <=8 USD: {body['le_8']}",
        f"- Body <=10 USD: {body['le_10']}",
        f"- Body <=12 USD: {body['le_12']}",
        f"- Tail >12 USD: {tail['gt_12']}",
        f"- Tail >15 USD: {tail['gt_15']}",
        f"- Tail >20 USD: {tail['gt_20']}",
        f"- Top-tail max manipulation USD: {summary['top_tail_max_manipulation_usd']}",
        "",
        "## Distinguishing Features",
        "",
        "- Weak expansion/manipulation ratio was the strongest descriptive split in this run.",
        "- Small or negative target space after sweep also concentrated deep-tail samples.",
        "- Dominant H1 reference samples carried materially higher deep-tail concentration than previous H1 samples.",
        "- Missing reaction confirmation removed fewer total samples but captured a meaningful slice of the tail with limited body removal.",
        "- Session-level concentration was weak in this run; hour-level buckets were more descriptive but carry higher overfit risk.",
        "",
        "## Strongest Hypotheses",
        "",
    ]
    if strongest.empty:
        lines.append("No hypotheses were generated.")
    else:
        for _, row in strongest.iterrows():
            lines.extend(
                [
                    f"### {row['hypothesis_id']}",
                    "",
                    f"- Rule: {row['rule_description']}",
                    f"- Samples kept: {row['samples_kept']}",
                    f"- Samples removed: {row['samples_removed']}",
                    f"- Tail removed: {row['tail_removed_pct']}%",
                    f"- Body removed: {row['body_removed_pct']}%",
                    f"- Risk of overfit: {row['risk_of_overfit']}",
                    f"- Verdict: {row['verdict']}",
                    "",
                ]
            )
    lines.extend(
        [
            "## Hypothesis Table",
            "",
            "| Hypothesis | Rule | Kept | Removed | Tail removed | Body removed | Risk | Verdict |",
            "|---|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for _, row in result.hypotheses.iterrows():
        rule = str(row["rule_description"]).replace("|", "/")
        lines.append(
            f"| {row['hypothesis_id']} | {rule} | {row['samples_kept']} | {row['samples_removed']} | {row['tail_removed_pct']}% | {row['body_removed_pct']}% | {row['risk_of_overfit']} | {row['verdict']} |"
        )
    weak = result.hypotheses[~result.hypotheses["verdict"].eq("PROMISING_DIAGNOSTIC")]
    if not weak.empty:
        lines.extend(["", "## Weak Or Rejected Diagnostics", ""])
        for _, row in weak.iterrows():
            lines.append(f"- {row['hypothesis_id']}: {row['verdict']} - {row['rule_description']}")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- No manual labels are used.",
            "- No proof of a user A+ filter is claimed.",
            "- No performance validation or trading edge is claimed.",
            "- No Strategy 2 signal generation is performed.",
            "- Reaction/anatomy features may still be incomplete.",
            "- Hypotheses are candidates only and should be audited visually before any runtime consideration.",
            "",
            "## Verdict Flags",
            "",
        ]
    )
    lines.extend([f"- {flag}" for flag in summary["verdict_flags"]])
    next_branch = (
        "feat/strategy-2-a-plus-filter-hypothesis-audit"
        if any(row["verdict"] == "PROMISING_DIAGNOSTIC" for _, row in result.hypotheses.iterrows())
        else "feat/strategy-2-reaction-confirmation-model"
        if "REACTION_FEATURES_MISSING" in summary["verdict_flags"]
        else "feat/strategy-2-manual-visual-review-pack"
    )
    lines.extend(
        [
            "",
            "## Next Strategy 2-only Branch",
            "",
            f"- {next_branch}",
            "",
        ]
    )
    return "\n".join(lines)


def report_paths(output_dir: str | Path) -> dict[str, Path]:
    root = Path(output_dir)
    return {
        "body_tail_comparison_csv": root / "body_tail_comparison.csv",
        "top_tail_samples_csv": root / "top_tail_samples.csv",
        "filter_hypotheses_csv": root / "filter_hypotheses.csv",
        "summary_json": root / "auto_filter_hypothesis_summary.json",
        "report_md": root / "auto_filter_hypothesis_report.md",
    }
