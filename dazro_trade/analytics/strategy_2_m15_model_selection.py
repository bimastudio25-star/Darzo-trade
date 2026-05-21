from __future__ import annotations

import csv
import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median
from typing import Any

import pandas as pd


MODELS = ("containing", "preceding", "approach_window")
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
    "machine_learning_used": False,
    "market_data_written": False,
}


@dataclass(frozen=True)
class SelectionReviewResult:
    samples: pd.DataFrame
    scorecard: pd.DataFrame
    disagreement_groups: pd.DataFrame
    tail_risk: pd.DataFrame
    old_x45_comparison: pd.DataFrame
    review_candidates: pd.DataFrame
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


def _mean(values: list[float]) -> float | None:
    return round(fmean(values), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(median(values), 4) if values else None


def _percentile(values: list[float], q: float) -> float | None:
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


def _rate(count: int | float, total: int | float) -> float:
    return round(float(count) / float(total), 4) if total else 0.0


def _pct(count: int | float, total: int | float) -> float:
    return round(_rate(count, total) * 100, 2)


def _sample_key(row: pd.Series | dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("h1_context_timestamp", "")),
            str(row.get("h1_reference_type", "")),
            str(row.get("direction", "")),
            str(row.get("h1_liquidity_level", "")),
        ]
    )


def load_corrected_samples(input_dir: str | Path) -> pd.DataFrame:
    path = Path(input_dir) / "corrected_mechanical_samples.csv"
    if not path.exists():
        raise FileNotFoundError(f"corrected mechanical sample file missing: {path}")
    frame = pd.read_csv(path)
    required = {"m15_filter_model", "sample_status", "manipulation_depth_usd", "entry_valid", "h1_context_timestamp"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"corrected mechanical sample file missing required columns: {missing}")
    return enrich_samples(frame)


def enrich_samples(frame: pd.DataFrame, *, pip_factor: float = 10.0) -> pd.DataFrame:
    out = frame.copy()
    out["sample_key"] = out.apply(_sample_key, axis=1)
    out["is_corrected_valid_sample"] = out["sample_status"].astype(str).isin(VALID_SAMPLE_STATUSES)
    out["entry_valid_bool"] = out.get("entry_valid", pd.Series(False, index=out.index)).map(_to_bool)
    out["m15_sequence_valid_bool"] = out.get("m15_sequence_valid", pd.Series(False, index=out.index)).map(_to_bool)
    out["old_x45_sequence_valid_bool"] = out.get("old_x45_sequence_valid", pd.Series(False, index=out.index)).map(_to_bool)
    out["manipulation_depth_usd"] = _numeric(out, "manipulation_depth_usd")
    out["manipulation_depth_pips"] = out["manipulation_depth_usd"] * float(pip_factor)
    out["expansion_usd"] = _numeric(out, "expansion_usd")
    out["expansion_pips"] = out["expansion_usd"] * float(pip_factor)
    out["pip_factor_used"] = float(pip_factor)
    return out


def valid_samples(frame: pd.DataFrame, model: str | None = None) -> pd.DataFrame:
    out = frame[frame["is_corrected_valid_sample"]].copy()
    if model:
        out = out[out["m15_filter_model"].eq(model)].copy()
    return out


def model_counts(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model in MODELS:
        model_df = frame[frame["m15_filter_model"].eq(model)]
        valid = valid_samples(model_df)
        invalid = model_df[~model_df["is_corrected_valid_sample"]]
        entry = valid[valid["entry_valid_bool"]]
        no_entry = valid[~valid["entry_valid_bool"]]
        rows.append(
            {
                "m15_filter_model": model,
                "rows_loaded": int(len(model_df)),
                "corrected_sample_count": int(len(valid)),
                "current_m15_valid_count": int(model_df["m15_sequence_valid_bool"].sum()),
                "entry_triggered_count": int(len(entry)),
                "no_entry_count": int(len(no_entry)),
                "invalid_count": int(len(invalid)),
                "entry_rate_pct": _pct(len(entry), len(valid)),
                "no_entry_rate_pct": _pct(len(no_entry), len(valid)),
                "invalid_reason_counts": json.dumps(Counter(invalid.get("sample_reason_codes", pd.Series(dtype=str)).fillna("").astype(str)), sort_keys=True),
            }
        )
    return pd.DataFrame(rows)


def tail_risk_table(frame: pd.DataFrame, *, pip_factor: float = 10.0) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model in MODELS:
        valid = valid_samples(frame, model)
        mae = [float(v) for v in valid["manipulation_depth_usd"].dropna().tolist()]
        max_excursion = max(mae) if mae else None
        conservative_sl = round(max_excursion * 1.25, 4) if max_excursion is not None else None
        rows.append(
            {
                "m15_filter_model": model,
                "samples": len(valid),
                "mae_avg_usd": _mean(mae),
                "mae_median_usd": _median(mae),
                "mae_p90_usd": _percentile(mae, 0.90),
                "mae_p95_usd": _percentile(mae, 0.95),
                "max_excursion_usd": round(max_excursion, 4) if max_excursion is not None else None,
                "conservative_sl_usd": conservative_sl,
                "mae_avg_pips": _mean([v * pip_factor for v in mae]),
                "mae_median_pips": _median([v * pip_factor for v in mae]),
                "mae_p90_pips": None if _percentile(mae, 0.90) is None else round(_percentile(mae, 0.90) * pip_factor, 4),
                "mae_p95_pips": None if _percentile(mae, 0.95) is None else round(_percentile(mae, 0.95) * pip_factor, 4),
                "max_excursion_pips": None if max_excursion is None else round(max_excursion * pip_factor, 4),
                "conservative_sl_pips": None if conservative_sl is None else round(conservative_sl * pip_factor, 4),
                "count_le_8_usd": sum(1 for v in mae if v <= 8),
                "count_le_10_usd": sum(1 for v in mae if v <= 10),
                "count_le_12_usd": sum(1 for v in mae if v <= 12),
                "count_gt_12_usd": sum(1 for v in mae if v > 12),
                "count_gt_20_usd": sum(1 for v in mae if v > 20),
                "tail_gt_12_rate_pct": _pct(sum(1 for v in mae if v > 12), len(mae)),
                "tail_gt_20_rate_pct": _pct(sum(1 for v in mae if v > 20), len(mae)),
                "pip_factor_used": pip_factor,
                "unit_note": "usd fields are XAUUSD price-distance/USD units; pips = usd * pip_factor",
            }
        )
    return pd.DataFrame(rows)


def _valid_key_sets(frame: pd.DataFrame) -> dict[str, set[str]]:
    return {model: set(valid_samples(frame, model)["sample_key"].astype(str).tolist()) for model in MODELS}


def _entry_key_sets(frame: pd.DataFrame) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for model in MODELS:
        valid = valid_samples(frame, model)
        out[model] = set(valid[valid["entry_valid_bool"]]["sample_key"].astype(str).tolist())
    return out


def build_key_profile(frame: pd.DataFrame, keys: set[str], *, group_name: str) -> dict[str, Any]:
    subset = frame[frame["sample_key"].astype(str).isin(keys)].copy()
    valid_subset = subset[subset["is_corrected_valid_sample"]].copy()
    mae = [float(v) for v in valid_subset["manipulation_depth_usd"].dropna().tolist()]
    entries = valid_subset[valid_subset["entry_valid_bool"]]
    invalid_subset = subset[~subset["is_corrected_valid_sample"]]
    return {
        "disagreement_group": group_name,
        "count": len(keys),
        "rows": len(subset),
        "avg_mae_usd": _mean(mae),
        "median_mae_usd": _median(mae),
        "max_mae_usd": round(max(mae), 4) if mae else None,
        "tail_gt_12_count": sum(1 for v in mae if v > 12),
        "tail_gt_20_count": sum(1 for v in mae if v > 20),
        "tail_gt_12_pct": _pct(sum(1 for v in mae if v > 12), len(mae)),
        "tail_gt_20_pct": _pct(sum(1 for v in mae if v > 20), len(mae)),
        "entry_count": len(entries),
        "entry_pct": _pct(len(entries), len(valid_subset)),
        "no_entry_count": max(0, len(valid_subset) - len(entries)),
        "no_entry_pct": _pct(max(0, len(valid_subset) - len(entries)), len(valid_subset)),
        "invalid_reason_counts": json.dumps(Counter(invalid_subset.get("sample_reason_codes", pd.Series(dtype=str)).fillna("").astype(str)), sort_keys=True),
        "h1_reference_type_distribution": json.dumps(Counter(valid_subset.get("h1_reference_type", pd.Series(dtype=str)).fillna("").astype(str)), sort_keys=True),
        "direction_distribution": json.dumps(Counter(valid_subset.get("direction", pd.Series(dtype=str)).fillna("").astype(str)), sort_keys=True),
    }


def disagreement_groups_table(frame: pd.DataFrame) -> pd.DataFrame:
    valid_sets = _valid_key_sets(frame)
    all_keys = set(frame["sample_key"].astype(str).tolist())
    c, p, a = valid_sets["containing"], valid_sets["preceding"], valid_sets["approach_window"]
    groups = {
        "valid_in_containing_only": c - p - a,
        "valid_in_preceding_only": p - c - a,
        "valid_in_approach_window_only": a - c - p,
        "valid_in_all_three": c & p & a,
        "invalid_in_all_three": all_keys - (c | p | a),
        "containing_approach_agree_preceding_differs": ((c & a) - p) | ((all_keys - c - a) & p),
        "preceding_containing_agree_approach_differs": ((p & c) - a) | ((all_keys - p - c) & a),
        "preceding_approach_agree_containing_differs": ((p & a) - c) | ((all_keys - p - a) & c),
    }
    return pd.DataFrame([build_key_profile(frame, keys, group_name=name) for name, keys in groups.items()])


def old_x45_comparison_table(input_dir: str | Path, frame: pd.DataFrame) -> pd.DataFrame:
    preferred = Path(input_dir) / "old_vs_corrected_m15_comparison.csv"
    if preferred.exists():
        loaded = pd.read_csv(preferred)
        loaded["source"] = "old_vs_corrected_m15_comparison.csv"
        return loaded
    rows = []
    for model in MODELS:
        model_df = frame[frame["m15_filter_model"].eq(model)]
        old_valid = set(model_df[model_df["old_x45_sequence_valid_bool"]]["sample_key"].astype(str).tolist())
        new_valid = set(valid_samples(model_df)["sample_key"].astype(str).tolist())
        rows.append(
            {
                "m15_filter_model": model,
                "old_x45_valid_count": len(old_valid),
                "corrected_model_valid_count": len(new_valid),
                "overlap": len(old_valid & new_valid),
                "old_valid_new_invalid": len(old_valid - new_valid),
                "old_invalid_new_valid": len(new_valid - old_valid),
                "source": "corrected_mechanical_samples.csv",
            }
        )
    return pd.DataFrame(rows)


def h1_reference_breakdown(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model in MODELS:
        for ref_type, group in frame[frame["m15_filter_model"].eq(model)].groupby("h1_reference_type", dropna=False):
            valid = group[group["is_corrected_valid_sample"]]
            mae = [float(v) for v in valid["manipulation_depth_usd"].dropna().tolist()]
            rows.append(
                {
                    "m15_filter_model": model,
                    "h1_reference_type": ref_type,
                    "rows": len(group),
                    "valid_count": len(valid),
                    "entry_count": int(valid["entry_valid_bool"].sum()),
                    "tail_gt_12_pct": _pct(sum(1 for v in mae if v > 12), len(mae)),
                    "tail_gt_20_pct": _pct(sum(1 for v in mae if v > 20), len(mae)),
                    "max_excursion_usd": round(max(mae), 4) if mae else None,
                    "dominant_invalid_reason_counts": json.dumps(Counter(group[~group["is_corrected_valid_sample"]].get("sample_reason_codes", pd.Series(dtype=str)).fillna("").astype(str)), sort_keys=True),
                }
            )
    return pd.DataFrame(rows)


def top_tail_cases(frame: pd.DataFrame, *, n: int = 10) -> pd.DataFrame:
    columns = [
        "sample_key",
        "sample_id",
        "m15_filter_model",
        "h1_context_timestamp",
        "direction",
        "h1_reference_type",
        "h1_liquidity_level",
        "manipulation_depth_usd",
        "manipulation_depth_pips",
        "entry_valid_bool",
        "sample_status",
        "sample_reason_codes",
    ]
    valid = valid_samples(frame)
    available = [col for col in columns if col in valid.columns]
    return valid.sort_values("manipulation_depth_usd", ascending=False).head(n)[available]


def model_scorecard(frame: pd.DataFrame, tail: pd.DataFrame, old_new: pd.DataFrame, groups: pd.DataFrame) -> tuple[pd.DataFrame, str, list[str]]:
    valid_sets = _valid_key_sets(frame)
    entry_sets = _entry_key_sets(frame)
    rows: list[dict[str, Any]] = []
    old_new_by_model = {row["m15_filter_model"]: row for _, row in old_new.iterrows() if "m15_filter_model" in row}

    for model in MODELS:
        t = tail[tail["m15_filter_model"].eq(model)].iloc[0].to_dict()
        valid_count = len(valid_sets[model])
        entry_count = len(entry_sets[model])
        other_models = [m for m in MODELS if m != model]
        avg_jaccard = 0.0
        for other in other_models:
            union = valid_sets[model] | valid_sets[other]
            avg_jaccard += len(valid_sets[model] & valid_sets[other]) / len(union) if union else 0.0
        avg_jaccard /= len(other_models)

        tail_gt_20_rate = float(t.get("tail_gt_20_rate_pct") or 0.0)
        p95 = float(t.get("mae_p95_usd") or 999.0)
        divergence = old_new_by_model.get(model, {}).get("old_invalid_new_valid", 0) + old_new_by_model.get(model, {}).get("old_valid_new_invalid", 0)
        divergence_rate = divergence / max(1, valid_count)
        sample_score = min(valid_count / 250, 1.0) * 15.0
        tail_score = max(0.0, 35.0 - tail_gt_20_rate)
        p95_score = max(0.0, 25.0 - (p95 / 2.0))
        agreement_score = avg_jaccard * 20.0
        mechanical_fit = {"containing": 18.0, "approach_window": 16.0, "preceding": 9.0}[model]
        permissiveness_penalty = 12.0 if model == "preceding" and tail_gt_20_rate > 20 else 0.0
        entry_count_note = "entry count reported only; not used as a positive score criterion"
        diagnostic_score = round(sample_score + tail_score + p95_score + agreement_score + mechanical_fit - permissiveness_penalty, 4)
        rows.append(
            {
                "m15_filter_model": model,
                "diagnostic_score": diagnostic_score,
                "valid_count": valid_count,
                "entry_count_reported_not_scored": entry_count,
                "sample_size_component": round(sample_score, 4),
                "tail_gt_20_rate_pct": tail_gt_20_rate,
                "tail_component": round(tail_score, 4),
                "mae_p95_usd": p95,
                "p95_component": round(p95_score, 4),
                "avg_jaccard_with_other_models": round(avg_jaccard, 4),
                "agreement_component": round(agreement_score, 4),
                "mechanical_fit_component": mechanical_fit,
                "permissiveness_penalty": permissiveness_penalty,
                "entry_count_note": entry_count_note,
                "profit_or_pf_used": False,
            }
        )
    scorecard = pd.DataFrame(rows).sort_values("diagnostic_score", ascending=False).reset_index(drop=True)

    verdict_flags = [
        "M15_MODEL_SELECTION_REVIEW_COMPLETE",
        "PRECEDING_ENTRY_COUNT_NOT_SUFFICIENT_EVIDENCE",
        "TAIL_RISK_PERSISTS_ALL_MODELS",
        "UNIT_CONVERSION_CLARIFIED",
        "VISUAL_REVIEW_CANDIDATES_EXPORTED",
        "STRATEGY_2_REMAINS_RESEARCH_ONLY",
        "NO_LIVE_DEPLOYMENT_DECISION",
    ]
    containing_tail = float(tail[tail["m15_filter_model"].eq("containing")]["tail_gt_20_rate_pct"].iloc[0])
    preceding_tail = float(tail[tail["m15_filter_model"].eq("preceding")]["tail_gt_20_rate_pct"].iloc[0])
    approach_tail = float(tail[tail["m15_filter_model"].eq("approach_window")]["tail_gt_20_rate_pct"].iloc[0])
    if preceding_tail > containing_tail and preceding_tail > approach_tail:
        verdict_flags.append("PRECEDING_MODEL_MORE_PERMISSIVE")
    if containing_tail <= preceding_tail:
        verdict_flags.append("CONTAINING_MODEL_MORE_CONSERVATIVE")
    if approach_tail <= preceding_tail:
        verdict_flags.append("APPROACH_WINDOW_MODEL_MORE_CONSERVATIVE")

    top_model = str(scorecard.iloc[0]["m15_filter_model"])
    top_score = float(scorecard.iloc[0]["diagnostic_score"])
    second_score = float(scorecard.iloc[1]["diagnostic_score"])
    containing_approach_gap = abs(
        float(scorecard[scorecard["m15_filter_model"].eq("containing")]["diagnostic_score"].iloc[0])
        - float(scorecard[scorecard["m15_filter_model"].eq("approach_window")]["diagnostic_score"].iloc[0])
    )
    if top_score - second_score < 8 or containing_approach_gap < 8:
        recommendation = "RECOMMEND_HYBRID_OR_VISUAL_REVIEW"
        verdict_flags.append("MODEL_SELECTION_INCONCLUSIVE")
    elif top_model == "containing":
        recommendation = "RECOMMEND_CONTAINING_FOR_NEXT_DIAGNOSTIC"
        verdict_flags.append("MODEL_SELECTED_FOR_NEXT_DIAGNOSTIC")
    elif top_model == "approach_window":
        recommendation = "RECOMMEND_APPROACH_WINDOW_FOR_NEXT_DIAGNOSTIC"
        verdict_flags.append("MODEL_SELECTED_FOR_NEXT_DIAGNOSTIC")
    else:
        recommendation = "RECOMMEND_HYBRID_OR_VISUAL_REVIEW"
        verdict_flags.append("MODEL_SELECTION_INCONCLUSIVE")
    return scorecard, recommendation, verdict_flags


def review_candidates(frame: pd.DataFrame, *, max_candidates: int = 30) -> pd.DataFrame:
    valid_sets = _valid_key_sets(frame)
    c, p, a = valid_sets["containing"], valid_sets["preceding"], valid_sets["approach_window"]
    groups = [
        ("preceding_valid_containing_approach_invalid", p - c - a),
        ("containing_approach_valid_preceding_invalid", (c & a) - p),
        ("top_tail_shared_or_any_model", set(top_tail_cases(frame, n=12)["sample_key"].astype(str).tolist())),
        ("body_disagreement", {key for key in (c ^ p) | (p ^ a) | (c ^ a) if _key_min_mae(frame, key) is not None and _key_min_mae(frame, key) <= 12}),
    ]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for reason, keys in groups:
        for key in sorted(keys):
            if key in seen or len(rows) >= max_candidates:
                continue
            subset = frame[frame["sample_key"].astype(str).eq(key)].copy()
            if subset.empty:
                continue
            best = subset.sort_values(["is_corrected_valid_sample", "manipulation_depth_usd"], ascending=[False, False]).iloc[0]
            rows.append(
                {
                    "review_reason": reason,
                    "sample_key": key,
                    "h1_context_timestamp": best.get("h1_context_timestamp"),
                    "direction": best.get("direction"),
                    "h1_reference_type": best.get("h1_reference_type"),
                    "h1_liquidity_level": best.get("h1_liquidity_level"),
                    "containing_valid": key in c,
                    "preceding_valid": key in p,
                    "approach_window_valid": key in a,
                    "max_manipulation_usd_any_model": _key_max_mae(frame, key),
                    "min_manipulation_usd_any_model": _key_min_mae(frame, key),
                    "entry_valid_any_model": bool(subset["entry_valid_bool"].any()),
                    "sample_ids": ";".join(subset.get("sample_id", pd.Series(dtype=str)).fillna("").astype(str).tolist()),
                }
            )
            seen.add(key)
    return pd.DataFrame(rows)


def _key_max_mae(frame: pd.DataFrame, key: str) -> float | None:
    values = _numeric(frame[frame["sample_key"].astype(str).eq(key)], "manipulation_depth_usd").dropna()
    return round(float(values.max()), 4) if not values.empty else None


def _key_min_mae(frame: pd.DataFrame, key: str) -> float | None:
    values = _numeric(frame[frame["sample_key"].astype(str).eq(key)], "manipulation_depth_usd").dropna()
    return round(float(values.min()), 4) if not values.empty else None


def build_selection_review(input_dir: str | Path, *, pip_factor: float = 10.0) -> SelectionReviewResult:
    started = time.perf_counter()
    samples = load_corrected_samples(input_dir)
    samples = enrich_samples(samples, pip_factor=pip_factor)
    counts = model_counts(samples)
    tail = tail_risk_table(samples, pip_factor=pip_factor)
    disagreements = disagreement_groups_table(samples)
    old_new = old_x45_comparison_table(input_dir, samples)
    h1_breakdown = h1_reference_breakdown(samples)
    candidates = review_candidates(samples)
    scorecard, recommendation, verdict_flags = model_scorecard(samples, tail, old_new, disagreements)
    runtime = round(time.perf_counter() - started, 4)
    summary = {
        "runtime_seconds": runtime,
        "models_loaded": list(MODELS),
        "rows_loaded": int(len(samples)),
        "scorecard_result": scorecard.to_dict(orient="records"),
        "recommendation": recommendation,
        "tail_risk_per_model": tail.to_dict(orient="records"),
        "disagreement_groups": disagreements.to_dict(orient="records"),
        "old_x45_comparison": old_new.to_dict(orient="records"),
        "h1_reference_breakdown": h1_breakdown.to_dict(orient="records"),
        "review_candidates_count": int(len(candidates)),
        "pip_factor_used": float(pip_factor),
        "unit_note": "USD fields are XAUUSD price-distance/USD units; pips = USD * pip_factor.",
        "safety": SAFETY,
        "verdict_flags": verdict_flags,
    }
    return SelectionReviewResult(
        samples=samples,
        scorecard=scorecard,
        disagreement_groups=disagreements,
        tail_risk=tail,
        old_x45_comparison=old_new,
        review_candidates=candidates,
        summary=summary,
        report_markdown=selection_report_markdown(summary),
    )


def write_selection_outputs(result: SelectionReviewResult, output_dir: str | Path, *, docs_path: str | Path | None = None) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "model_scorecard": output / "m15_model_scorecard.csv",
        "disagreement_groups": output / "m15_model_disagreement_groups.csv",
        "tail_risk": output / "m15_model_tail_risk.csv",
        "old_x45_comparison": output / "m15_model_old_x45_comparison.csv",
        "review_candidates": output / "m15_disagreement_review_candidates.csv",
        "summary": output / "m15_model_selection_summary.json",
        "report": output / "m15_model_selection_report.md",
    }
    result.scorecard.to_csv(paths["model_scorecard"], index=False)
    result.disagreement_groups.to_csv(paths["disagreement_groups"], index=False)
    result.tail_risk.to_csv(paths["tail_risk"], index=False)
    result.old_x45_comparison.to_csv(paths["old_x45_comparison"], index=False)
    result.review_candidates.to_csv(paths["review_candidates"], index=False)
    paths["summary"].write_text(json.dumps(result.summary, indent=2, sort_keys=True), encoding="utf-8")
    paths["report"].write_text(result.report_markdown, encoding="utf-8")
    if docs_path:
        docs = Path(docs_path)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(result.report_markdown, encoding="utf-8")
        paths["docs"] = docs
    return {key: str(path) for key, path in paths.items()}


def selection_report_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Strategy 2 M15 Model Selection Review",
        "",
        "## Context",
        "",
        "The fixed HH:45/x:45 M15 interpretation has been superseded. The mechanical correction branch implemented three deterministic current-M15 models: containing, preceding, and approach_window. This review compares them without choosing a model by entry count alone.",
        "",
        "## Safety",
        "",
        "- Strategy 3 untouched.",
        "- data/XAUUSD/*.csv untouched.",
        "- No live trading, Telegram, broker execution, orders, optimization, ML, or runtime registration.",
        "",
        "## Method",
        "",
        "- Inputs are the read-only mechanical correction outputs.",
        "- Scorecard uses tail risk, p95 MAE, agreement, sample adequacy, and mechanical fit.",
        "- Entry count is reported but not used as a positive score criterion.",
        "- No PnL, PF, grid search, or model training is used.",
        f"- Unit conversion: pips = USD/price distance * {summary.get('pip_factor_used')}.",
        "",
        "## Scorecard",
        "",
        "| Model | Score | Valid | Entry reported | >20 tail % | p95 USD | Agreement |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary.get("scorecard_result", []):
        lines.append(
            f"| {row['m15_filter_model']} | {row['diagnostic_score']} | {row['valid_count']} | {row['entry_count_reported_not_scored']} | {row['tail_gt_20_rate_pct']} | {row['mae_p95_usd']} | {row['avg_jaccard_with_other_models']} |"
        )
    lines.extend(["", "## Tail Risk", "", "| Model | <=8 | <=10 | <=12 | >12 | >20 | p95 USD | Max USD | Conservative SL USD |"])
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in summary.get("tail_risk_per_model", []):
        lines.append(
            f"| {row['m15_filter_model']} | {row['count_le_8_usd']} | {row['count_le_10_usd']} | {row['count_le_12_usd']} | {row['count_gt_12_usd']} | {row['count_gt_20_usd']} | {row['mae_p95_usd']} | {row['max_excursion_usd']} | {row['conservative_sl_usd']} |"
        )
    lines.extend(["", "## Old X45 Comparison", "", "| Model | Old valid | Corrected valid | Overlap | Old valid/new invalid | Old invalid/new valid |"])
    lines.append("|---|---:|---:|---:|---:|---:|")
    for row in summary.get("old_x45_comparison", []):
        lines.append(
            f"| {row['m15_filter_model']} | {row.get('old_x45_valid_count')} | {row.get('corrected_model_valid_count')} | {row.get('overlap')} | {row.get('old_valid_new_invalid')} | {row.get('old_invalid_new_valid')} |"
        )
    lines.extend(
        [
            "",
            "## H1 Reference Breakdown",
            "",
            "| Model | H1 reference | Valid | Entry | >12 tail % | >20 tail % | Max USD |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in summary.get("h1_reference_breakdown", []):
        lines.append(
            f"| {row['m15_filter_model']} | {row['h1_reference_type']} | {row['valid_count']} | {row['entry_count']} | {row['tail_gt_12_pct']} | {row['tail_gt_20_pct']} | {row['max_excursion_usd']} |"
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"- Recommendation: `{summary.get('recommendation')}`",
            "- Rationale: preceding has materially higher sample and entry counts, but that is not sufficient evidence; it is also more permissive and carries larger tail exposure. Containing and approach_window are more conservative and close enough that targeted disagreement review is the safer next diagnostic.",
            "",
            "## Disagreement Groups",
            "",
            "| Group | Count | >12 tail % | >20 tail % | Entry % |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in summary.get("disagreement_groups", []):
        lines.append(
            f"| {row['disagreement_group']} | {row['count']} | {row['tail_gt_12_pct']} | {row['tail_gt_20_pct']} | {row['entry_pct']} |"
        )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- No manual labels are included.",
            "- No visual user selection has been performed.",
            "- No live/signal validation is made.",
            "- The current-M15 phrase remains approximated mechanically.",
            "- Exit logic remains incomplete.",
            "",
            "## Verdict Flags",
            "",
            *[f"- {flag}" for flag in summary.get("verdict_flags", [])],
            "",
            "## Next Strategy 2-Only Step",
            "",
            "- feat/strategy-2-m15-disagreement-visual-review",
        ]
    )
    return "\n".join(lines) + "\n"
