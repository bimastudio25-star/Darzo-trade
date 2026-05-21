from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median
from typing import Any

import pandas as pd


PRIMARY_MODEL = "containing"
SENSITIVITY_MODEL = "approach_window"
REJECTED_MODEL = "preceding"
DIAGNOSTIC_MODELS = (PRIMARY_MODEL, SENSITIVITY_MODEL)
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
class ContainingDiagnosticResult:
    samples: pd.DataFrame
    entry_diagnostics: pd.DataFrame
    risk_profile: pd.DataFrame
    tp_r_profile: pd.DataFrame
    model_comparison: pd.DataFrame
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


def _percentile(values: list[float], q: float) -> float | None:
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
    return round((float(count) / float(total) * 100.0), 2) if total else 0.0


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


def load_mechanical_samples(input_dir: str | Path, *, pip_factor: float = 10.0) -> pd.DataFrame:
    path = Path(input_dir) / "corrected_mechanical_samples.csv"
    if not path.exists():
        raise FileNotFoundError(f"corrected mechanical sample file missing: {path}")
    frame = pd.read_csv(path)
    required = {"m15_filter_model", "sample_status", "entry_valid", "manipulation_depth_usd", "expansion_usd"}
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
    out["m15_sequence_valid_bool"] = out.get("m15_sequence_valid", pd.Series(False, index=out.index)).map(_to_bool)
    out["manipulation_depth_usd"] = _numeric(out, "manipulation_depth_usd")
    out["manipulation_depth_pips"] = out["manipulation_depth_usd"] * float(pip_factor)
    out["expansion_usd"] = _numeric(out, "expansion_usd")
    out["expansion_pips"] = out["expansion_usd"] * float(pip_factor)
    out["pip_factor_used"] = float(pip_factor)
    return out


def model_rows(frame: pd.DataFrame, model: str) -> pd.DataFrame:
    return frame[frame["m15_filter_model"].astype(str).eq(model)].copy()


def valid_samples(frame: pd.DataFrame, model: str) -> pd.DataFrame:
    rows = model_rows(frame, model)
    return rows[rows["is_valid_sample"]].copy()


def entry_diagnostics_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model in DIAGNOSTIC_MODELS:
        data = model_rows(frame, model)
        valid = data[data["is_valid_sample"]]
        invalid = data[~data["is_valid_sample"]]
        h1_taken = data.get("h1_level_take_timestamp", pd.Series("", index=data.index)).fillna("").astype(str).str.strip().ne("")
        entry_reasons = valid.get("entry_status", pd.Series("", index=valid.index)).fillna("").astype(str)
        rows.append(
            {
                "m15_filter_model": model,
                "role": "primary" if model == PRIMARY_MODEL else "sensitivity",
                "rows_loaded": int(len(data)),
                "sample_count": int(len(data)),
                "valid_count": int(len(valid)),
                "entry_count": int(valid["entry_valid_bool"].sum()),
                "no_entry_count": int((~valid["entry_valid_bool"]).sum()),
                "invalid_count": int(len(invalid)),
                "h1_level_take_count": int(h1_taken.sum()),
                "mae_reached_count": int(data["mae_reached_bool"].sum()),
                "range_reentry_count": int(data["range_reentry_reached_bool"].sum()),
                "no_entry_mae_not_reached": int(entry_reasons.eq("NO_ENTRY_MAE_NOT_REACHED").sum()),
                "no_entry_no_range_reentry": int(entry_reasons.eq("NO_ENTRY_NO_RANGE_REENTRY").sum()),
                "invalid_reason_counts": json.dumps(
                    Counter(invalid.get("sample_reason_codes", pd.Series(dtype=str)).fillna("").astype(str)),
                    sort_keys=True,
                ),
                "status_counts": json.dumps(Counter(data.get("sample_status", pd.Series(dtype=str)).fillna("").astype(str)), sort_keys=True),
            }
        )
    return pd.DataFrame(rows)


def risk_profile_table(frame: pd.DataFrame, *, pip_factor: float = 10.0) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model in DIAGNOSTIC_MODELS:
        valid = valid_samples(frame, model)
        mae = _values(valid, "manipulation_depth_usd")
        max_excursion = round(max(mae), 4) if mae else None
        conservative_sl = conservative_sl_distance(max_excursion)
        rows.append(
            {
                "m15_filter_model": model,
                "role": "primary" if model == PRIMARY_MODEL else "sensitivity",
                "valid_samples": len(valid),
                "mae_avg_usd": _mean(mae),
                "mae_median_usd": _median(mae),
                "mae_p75_usd": _percentile(mae, 0.75),
                "mae_p90_usd": _percentile(mae, 0.90),
                "mae_p95_usd": _percentile(mae, 0.95),
                "max_excursion_usd": max_excursion,
                "conservative_sl_usd": conservative_sl,
                "mae_avg_pips": price_to_pips(_mean(mae), pip_factor),
                "mae_median_pips": price_to_pips(_median(mae), pip_factor),
                "mae_p75_pips": price_to_pips(_percentile(mae, 0.75), pip_factor),
                "mae_p90_pips": price_to_pips(_percentile(mae, 0.90), pip_factor),
                "mae_p95_pips": price_to_pips(_percentile(mae, 0.95), pip_factor),
                "max_excursion_pips": price_to_pips(max_excursion, pip_factor),
                "conservative_sl_pips": price_to_pips(conservative_sl, pip_factor),
                "count_le_8_usd": sum(1 for value in mae if value <= 8),
                "count_le_10_usd": sum(1 for value in mae if value <= 10),
                "count_le_12_usd": sum(1 for value in mae if value <= 12),
                "count_gt_12_usd": sum(1 for value in mae if value > 12),
                "count_gt_20_usd": sum(1 for value in mae if value > 20),
                "count_gt_40_usd": sum(1 for value in mae if value > 40),
                "count_gt_100_usd": sum(1 for value in mae if value > 100),
                "tail_gt_12_rate_pct": _pct(sum(1 for value in mae if value > 12), len(mae)),
                "tail_gt_20_rate_pct": _pct(sum(1 for value in mae if value > 20), len(mae)),
                "tail_gt_40_rate_pct": _pct(sum(1 for value in mae if value > 40), len(mae)),
                "tail_gt_100_rate_pct": _pct(sum(1 for value in mae if value > 100), len(mae)),
                "pip_factor_used": float(pip_factor),
                "unit_note": "USD fields are XAUUSD price-distance/USD units; pips = USD * pip_factor.",
            }
        )
    return pd.DataFrame(rows)


def tp_r_profile_table(frame: pd.DataFrame, *, pip_factor: float = 10.0) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model in DIAGNOSTIC_MODELS:
        valid = valid_samples(frame, model)
        mae = _values(valid, "manipulation_depth_usd")
        expansions = _values(valid, "expansion_usd")
        avg_mae = _mean(mae)
        max_excursion = round(max(mae), 4) if mae else None
        conservative_sl = conservative_sl_distance(max_excursion)
        effective_risk = None
        if conservative_sl is not None and avg_mae is not None:
            effective_risk = round(max(conservative_sl - avg_mae, 0.0), 4)
        max_expansion = round(max(expansions), 4) if expansions else None
        p90_expansion = _percentile(expansions, 0.90)
        p95_expansion = _percentile(expansions, 0.95)
        max_tps = tp_quartiles(max_expansion)
        p90_tps = tp_quartiles(p90_expansion)
        p95_tps = tp_quartiles(p95_expansion)

        def rr(tp_distance: float | None) -> float | None:
            if tp_distance is None or avg_mae is None or effective_risk is None or effective_risk <= 0:
                return None
            return round((avg_mae + tp_distance) / effective_risk, 4)

        rows.append(
            {
                "m15_filter_model": model,
                "role": "primary" if model == PRIMARY_MODEL else "sensitivity",
                "valid_samples": len(valid),
                "avg_expansion_usd": _mean(expansions),
                "median_expansion_usd": _median(expansions),
                "p75_expansion_usd": _percentile(expansions, 0.75),
                "p90_expansion_usd": p90_expansion,
                "p95_expansion_usd": p95_expansion,
                "max_expansion_usd": max_expansion,
                "tp1_distance_usd": max_tps["tp1"],
                "tp2_distance_usd": max_tps["tp2"],
                "tp3_distance_usd": max_tps["tp3"],
                "tp4_distance_usd": max_tps["tp4"],
                "tp1_distance_pips": price_to_pips(max_tps["tp1"], pip_factor),
                "tp2_distance_pips": price_to_pips(max_tps["tp2"], pip_factor),
                "tp3_distance_pips": price_to_pips(max_tps["tp3"], pip_factor),
                "tp4_distance_pips": price_to_pips(max_tps["tp4"], pip_factor),
                "p90_tp1_distance_usd": p90_tps["tp1"],
                "p90_tp2_distance_usd": p90_tps["tp2"],
                "p90_tp3_distance_usd": p90_tps["tp3"],
                "p90_tp4_distance_usd": p90_tps["tp4"],
                "p95_tp1_distance_usd": p95_tps["tp1"],
                "p95_tp2_distance_usd": p95_tps["tp2"],
                "p95_tp3_distance_usd": p95_tps["tp3"],
                "p95_tp4_distance_usd": p95_tps["tp4"],
                "mae_entry_distance_usd": avg_mae,
                "conservative_sl_from_h1_usd": conservative_sl,
                "effective_entry_to_sl_risk_usd": effective_risk,
                "tp1_R": rr(max_tps["tp1"]),
                "tp2_R": rr(max_tps["tp2"]),
                "tp3_R": rr(max_tps["tp3"]),
                "tp4_R": rr(max_tps["tp4"]),
                "tp1_partial_pct": 25,
                "be_at_tp1_rule": "descriptive_only_not_simulated",
                "h1_close_be_rule_available": False,
                "h1_close_positive_be_count": None,
                "h1_close_negative_original_sl_count": None,
                "tp_anchor": "H1_LIQUIDITY_LEVEL",
                "tp_anchor_is_entry": False,
                "standard_tp1_fallback_used_as_gate": False,
                "pip_factor_used": float(pip_factor),
                "unit_note": "USD fields are XAUUSD price-distance/USD units; pips = USD * pip_factor.",
            }
        )
    return pd.DataFrame(rows)


def containing_vs_approach_table(frame: pd.DataFrame, risk: pd.DataFrame, tp_r: pd.DataFrame) -> pd.DataFrame:
    containing_valid = set(valid_samples(frame, PRIMARY_MODEL)["sample_key"].astype(str).tolist())
    approach_valid = set(valid_samples(frame, SENSITIVITY_MODEL)["sample_key"].astype(str).tolist())
    containing_entries = set(valid_samples(frame, PRIMARY_MODEL).query("entry_valid_bool == True")["sample_key"].astype(str).tolist())
    approach_entries = set(valid_samples(frame, SENSITIVITY_MODEL).query("entry_valid_bool == True")["sample_key"].astype(str).tolist())
    risk_by_model = {row["m15_filter_model"]: row for _, row in risk.iterrows()}
    tp_by_model = {row["m15_filter_model"]: row for _, row in tp_r.iterrows()}
    return pd.DataFrame(
        [
            {
                "comparison": "containing_vs_approach_window",
                "containing_valid": len(containing_valid),
                "approach_window_valid": len(approach_valid),
                "overlap_valid": len(containing_valid & approach_valid),
                "containing_only_valid": len(containing_valid - approach_valid),
                "approach_window_only_valid": len(approach_valid - containing_valid),
                "shared_entries": len(containing_entries & approach_entries),
                "containing_only_entries": len(containing_entries - approach_entries),
                "approach_window_only_entries": len(approach_entries - containing_entries),
                "containing_tail_gt_20": int(risk_by_model[PRIMARY_MODEL]["count_gt_20_usd"]),
                "approach_window_tail_gt_20": int(risk_by_model[SENSITIVITY_MODEL]["count_gt_20_usd"]),
                "tail_gt_20_delta_containing_minus_approach": int(risk_by_model[PRIMARY_MODEL]["count_gt_20_usd"])
                - int(risk_by_model[SENSITIVITY_MODEL]["count_gt_20_usd"]),
                "containing_tp2_R": tp_by_model[PRIMARY_MODEL]["tp2_R"],
                "approach_window_tp2_R": tp_by_model[SENSITIVITY_MODEL]["tp2_R"],
                "conclusion": "approach_window does not materially change primary containing conclusions",
            }
        ]
    )


def rejected_preceding_summary(frame: pd.DataFrame) -> dict[str, Any]:
    valid = valid_samples(frame, REJECTED_MODEL)
    mae = _values(valid, "manipulation_depth_usd")
    return {
        "m15_filter_model": REJECTED_MODEL,
        "status": "rejected_for_now_as_too_permissive",
        "valid_count": len(valid),
        "entry_count": int(valid["entry_valid_bool"].sum()) if not valid.empty else 0,
        "tail_gt_12": sum(1 for value in mae if value > 12),
        "tail_gt_20": sum(1 for value in mae if value > 20),
        "mae_p95_usd": _percentile(mae, 0.95),
        "max_excursion_usd": round(max(mae), 4) if mae else None,
    }


def build_containing_diagnostic(
    input_dir: str | Path,
    selection_dir: str | Path | None = None,
    *,
    pip_factor: float = 10.0,
) -> ContainingDiagnosticResult:
    started = time.perf_counter()
    samples = load_mechanical_samples(input_dir, pip_factor=pip_factor)
    entry = entry_diagnostics_table(samples)
    risk = risk_profile_table(samples, pip_factor=pip_factor)
    tp_r = tp_r_profile_table(samples, pip_factor=pip_factor)
    comparison = containing_vs_approach_table(samples, risk, tp_r)
    runtime = round(time.perf_counter() - started, 4)
    containing_entry = int(entry[entry["m15_filter_model"].eq(PRIMARY_MODEL)]["entry_count"].iloc[0])
    approach_entry = int(entry[entry["m15_filter_model"].eq(SENSITIVITY_MODEL)]["entry_count"].iloc[0])
    containing_risk = risk[risk["m15_filter_model"].eq(PRIMARY_MODEL)].iloc[0].to_dict()
    containing_r = tp_r[tp_r["m15_filter_model"].eq(PRIMARY_MODEL)].iloc[0].to_dict()
    tail_risk_structural = bool((containing_risk.get("count_gt_20_usd") or 0) > 0 or (containing_risk.get("count_gt_40_usd") or 0) > 0)
    r_profile_weak = bool((containing_r.get("tp2_R") is None) or float(containing_r.get("tp2_R") or 0.0) < 1.0)
    verdict_flags = [
        "CONTAINING_SELECTED_FOR_NEXT_DIAGNOSTIC",
        "PRECEDING_REJECTED_AS_TOO_PERMISSIVE_FOR_NOW",
        "APPROACH_WINDOW_RETAINED_AS_SENSITIVITY_CHECK",
        "MECHANICAL_ENTRY_PROFILE_BUILT",
        "TP_FROM_H1_CONFIRMED",
        "STRATEGY_2_REMAINS_RESEARCH_ONLY",
        "NO_LIVE_DEPLOYMENT_DECISION",
    ]
    verdict_flags.append("TAIL_RISK_REMAINS_STRUCTURAL" if tail_risk_structural else "TAIL_RISK_NOT_STRUCTURAL_IN_THIS_SAMPLE")
    verdict_flags.append("R_PROFILE_STRUCTURALLY_WEAK" if r_profile_weak else "R_PROFILE_POTENTIALLY_ACCEPTABLE")
    summary = {
        "runtime_seconds": runtime,
        "source_input_dir": str(input_dir),
        "selection_dir": str(selection_dir) if selection_dir else None,
        "primary_model": PRIMARY_MODEL,
        "sensitivity_model": SENSITIVITY_MODEL,
        "rejected_model_summary": rejected_preceding_summary(samples),
        "rows_loaded": int(len(samples)),
        "containing_samples_loaded": int(len(model_rows(samples, PRIMARY_MODEL))),
        "approach_window_samples_loaded": int(len(model_rows(samples, SENSITIVITY_MODEL))),
        "containing_entry_count": containing_entry,
        "approach_window_entry_count": approach_entry,
        "entry_diagnostics": entry.to_dict(orient="records"),
        "risk_profile": risk.to_dict(orient="records"),
        "tp_r_profile": tp_r.to_dict(orient="records"),
        "containing_vs_approach_window": comparison.to_dict(orient="records"),
        "tail_risk_verdict": "TAIL_RISK_REMAINS_STRUCTURAL" if tail_risk_structural else "TAIL_RISK_NOT_STRUCTURAL_IN_THIS_SAMPLE",
        "r_profile_verdict": "R_PROFILE_STRUCTURALLY_WEAK" if r_profile_weak else "R_PROFILE_POTENTIALLY_ACCEPTABLE",
        "pip_factor_used": float(pip_factor),
        "unit_note": "USD fields are XAUUSD price-distance/USD units; pips = USD * pip_factor.",
        "safety": SAFETY,
        "verdict_flags": verdict_flags,
    }
    return ContainingDiagnosticResult(
        samples=samples,
        entry_diagnostics=entry,
        risk_profile=risk,
        tp_r_profile=tp_r,
        model_comparison=comparison,
        summary=summary,
        report_markdown=containing_report_markdown(summary),
    )


def write_containing_diagnostic_outputs(
    result: ContainingDiagnosticResult,
    output_dir: str | Path,
    *,
    docs_path: str | Path | None = None,
) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    containing_entries = model_rows(result.samples, PRIMARY_MODEL)
    paths = {
        "summary": output / "containing_diagnostic_summary.json",
        "entry_diagnostics": output / "containing_entry_diagnostics.csv",
        "risk_profile": output / "containing_risk_profile.csv",
        "tp_r_profile": output / "containing_tp_r_profile.csv",
        "comparison": output / "containing_vs_approach_window.csv",
        "report": output / "containing_diagnostic_report.md",
    }
    paths["summary"].write_text(json.dumps(result.summary, indent=2, sort_keys=True), encoding="utf-8")
    containing_entries.to_csv(paths["entry_diagnostics"], index=False)
    result.risk_profile.to_csv(paths["risk_profile"], index=False)
    result.tp_r_profile.to_csv(paths["tp_r_profile"], index=False)
    result.model_comparison.to_csv(paths["comparison"], index=False)
    paths["report"].write_text(result.report_markdown, encoding="utf-8")
    if docs_path:
        docs = Path(docs_path)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(result.report_markdown, encoding="utf-8")
        paths["docs"] = docs
    return {key: str(path) for key, path in paths.items()}


def containing_report_markdown(summary: dict[str, Any]) -> str:
    entry = {row["m15_filter_model"]: row for row in summary.get("entry_diagnostics", [])}
    risk = {row["m15_filter_model"]: row for row in summary.get("risk_profile", [])}
    tp = {row["m15_filter_model"]: row for row in summary.get("tp_r_profile", [])}
    comparison = summary.get("containing_vs_approach_window", [{}])[0]
    lines = [
        "# Strategy 2 M15 Containing Next Diagnostic",
        "",
        "## Context",
        "",
        "The M15 model selection review was intentionally inconclusive because static visual review could not reliably confirm the user's discretionary intent. For this next diagnostic, `containing` is selected as the primary research model because it is the closest deterministic match to the current M15 while price is taking the H1 liquidity level. `approach_window` remains a conservative sensitivity check. `preceding` is rejected for now as too permissive and tail-heavy.",
        "",
        "## Safety",
        "",
        "- Strategy 3 untouched.",
        "- data/XAUUSD/*.csv untouched.",
        "- No live trading, Telegram, broker execution, orders, optimization, signal generation, runtime registration, or ML.",
        "",
        "## Method",
        "",
        "- Primary model: `containing`.",
        "- Sensitivity model: `approach_window`.",
        "- Entry mechanics: H1 level taken, average MAE reached, and re-entry into the H1 range.",
        "- Risk mechanics: Max Excursion from valid samples, conservative SL = Max Excursion * 1.25.",
        "- TP mechanics: TP1/TP2/TP3/TP4 are quartiles of max expansion and are anchored to the H1 liquidity level, not entry.",
        f"- Unit conversion: pips = USD/price distance * {summary.get('pip_factor_used')}. Do not call USD values pips.",
        "",
        "## Counts And Entry Mechanics",
        "",
        "| Model | Role | Rows | Valid | Entry | No-entry | Invalid | H1 take | MAE reached | Re-entry |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model in DIAGNOSTIC_MODELS:
        row = entry.get(model, {})
        lines.append(
            f"| {model} | {row.get('role')} | {row.get('rows_loaded')} | {row.get('valid_count')} | {row.get('entry_count')} | {row.get('no_entry_count')} | {row.get('invalid_count')} | {row.get('h1_level_take_count')} | {row.get('mae_reached_count')} | {row.get('range_reentry_count')} |"
        )
    lines.extend(["", "## Risk / SL Profile", "", "| Model | Avg MAE USD | Median | p75 | p90 | p95 | Max Excursion | Conservative SL | >12 | >20 | >40 | >100 |"])
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for model in DIAGNOSTIC_MODELS:
        row = risk.get(model, {})
        lines.append(
            f"| {model} | {row.get('mae_avg_usd')} | {row.get('mae_median_usd')} | {row.get('mae_p75_usd')} | {row.get('mae_p90_usd')} | {row.get('mae_p95_usd')} | {row.get('max_excursion_usd')} | {row.get('conservative_sl_usd')} | {row.get('count_gt_12_usd')} | {row.get('count_gt_20_usd')} | {row.get('count_gt_40_usd')} | {row.get('count_gt_100_usd')} |"
        )
    lines.extend(["", "## TP / Theoretical R Profile", "", "| Model | Avg expansion | Median expansion | Max expansion | TP1 | TP2 | TP3 | TP4 | Effective risk | TP1_R | TP2_R | TP3_R | TP4_R |"])
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for model in DIAGNOSTIC_MODELS:
        row = tp.get(model, {})
        lines.append(
            f"| {model} | {row.get('avg_expansion_usd')} | {row.get('median_expansion_usd')} | {row.get('max_expansion_usd')} | {row.get('tp1_distance_usd')} | {row.get('tp2_distance_usd')} | {row.get('tp3_distance_usd')} | {row.get('tp4_distance_usd')} | {row.get('effective_entry_to_sl_risk_usd')} | {row.get('tp1_R')} | {row.get('tp2_R')} | {row.get('tp3_R')} | {row.get('tp4_R')} |"
        )
    lines.extend(
        [
            "",
            "## Containing vs Approach Window",
            "",
            f"- Valid overlap: {comparison.get('overlap_valid')}",
            f"- Containing-only valid samples: {comparison.get('containing_only_valid')}",
            f"- Approach-window-only valid samples: {comparison.get('approach_window_only_valid')}",
            f"- Shared entries: {comparison.get('shared_entries')}",
            f"- Conclusion: {comparison.get('conclusion')}",
            "",
            "## Verdict",
            "",
            f"- Tail risk verdict: `{summary.get('tail_risk_verdict')}`",
            f"- R profile verdict: `{summary.get('r_profile_verdict')}`",
            "- Containing is acceptable as the next research diagnostic model only, with no live/runtime decision.",
            "",
            "## Limitations",
            "",
            "- No manual labels.",
            "- No live validation.",
            "- No final deployment model selection.",
            "- Exit management remains simplified; BE-at-TP1 and H1-close BE are documented descriptively, not used as proof.",
            "- Tail risk may remain structural.",
            "",
            "## Verdict Flags",
            "",
            *[f"- {flag}" for flag in summary.get("verdict_flags", [])],
            "",
            "## Next Strategy 2-Only Step",
            "",
            "- feat/strategy-2-containing-mechanical-smoke",
        ]
    )
    return "\n".join(lines) + "\n"
