from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median
from typing import Any

import pandas as pd


MANUAL_BENCHMARK_FIELDS = [
    "sample_id",
    "symbol",
    "session",
    "h1_open_time",
    "decision_time",
    "direction",
    "h1_reference_mode",
    "h1_liquidity_level_type",
    "h1_liquidity_level_price",
    "h1_range_high",
    "h1_range_low",
    "h1_range_size",
    "first_m15_open_time",
    "first_m15_high",
    "first_m15_low",
    "opposite_m15_level_taken_first",
    "liquidity_level_taken",
    "m15_sequence_valid",
    "sweep_depth_usd",
    "sweep_depth_pips",
    "reaction_type",
    "reclaim_detected",
    "rejection_detected",
    "price_reentered_range",
    "reaction_speed_label",
    "mae_reference_used",
    "entry_price",
    "stop_loss",
    "sl_distance_usd",
    "sl_distance_warning",
    "risk_notes",
    "tp1",
    "tp2",
    "tp3",
    "tp4",
    "tp_anchor_level",
    "tp_anchor_valid",
    "be_after_tp1",
    "expected_management",
    "user_decision",
    "user_quality",
    "user_reason_text",
    "measurable_reason_tags",
    "discretionary_reason_tags",
    "actual_outcome",
    "final_r_multiple",
    "gross_win_flag",
    "decisive_win_flag",
    "be_flag",
    "screenshot_before_path",
    "screenshot_after_path",
    "notes",
]

PRE_ENTRY_FIELDS = [
    field
    for field in MANUAL_BENCHMARK_FIELDS
    if field
    not in {
        "actual_outcome",
        "final_r_multiple",
        "gross_win_flag",
        "decisive_win_flag",
        "be_flag",
    }
]

USER_DECISIONS = {"TAKE", "SKIP", "UNCERTAIN", ""}
USER_QUALITIES = {"A_PLUS", "A", "B", "C", "INVALID", ""}
OUTCOMES = {"TP1", "TP2", "TP3", "TP4", "BE", "SL", "MANUAL_CLOSE", "TIMEOUT", "UNKNOWN", ""}
TRI_STATE = {"TRUE", "FALSE", "UNKNOWN", ""}
TAKE_REQUIRED_FIELDS = [
    "entry_price",
    "stop_loss",
    "tp1",
    "direction",
    "h1_liquidity_level_price",
    "decision_time",
    "user_reason_text",
]
SKIP_REQUIRED_FIELDS = ["user_reason_text"]
ALWAYS_REQUIRED_FIELDS = ["sample_id", "symbol", "user_decision", "user_reason_text"]
SAFETY = {
    "research_only": True,
    "live_trading_enabled": False,
    "telegram_trade_alerts_sent": False,
    "broker_execution_called": False,
    "orders_sent": False,
    "signals_generated": False,
    "runtime_registration": False,
    "parameters_optimized": False,
    "market_data_written": False,
}


@dataclass(frozen=True)
class ManualBenchmarkResult:
    validation: dict[str, Any]
    summary: dict[str, Any]
    take_samples: pd.DataFrame
    skip_samples: pd.DataFrame
    feature_distribution: pd.DataFrame
    reason_tags_summary: pd.DataFrame
    report_markdown: str


def to_pips(price_distance: float | None, pip_factor: float = 10.0) -> float | None:
    if price_distance is None:
        return None
    return round(float(price_distance) * float(pip_factor), 6)


def to_price_distance(pips: float | None, pip_factor: float = 10.0) -> float | None:
    if pips is None:
        return None
    return round(float(pips) / float(pip_factor), 6)


def write_manual_benchmark_template(output_dir: str | Path) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = output / "manual_labels_template.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANUAL_BENCHMARK_FIELDS)
        writer.writeheader()
    return {"manual_labels_template_csv": str(path)}


def read_manual_labels(path: str | Path) -> list[dict[str, Any]]:
    label_path = Path(path)
    if not label_path.exists():
        raise FileNotFoundError(f"manual labels file not found: {label_path}")
    with label_path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def validate_manual_benchmark_rows(rows: list[dict[str, Any]], *, pip_factor: float = 10.0) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    normalized_rows: list[dict[str, Any]] = []

    missing_columns = [field for field in MANUAL_BENCHMARK_FIELDS if rows and field not in rows[0]]
    for field in missing_columns:
        errors.append({"sample_id": "", "field": field, "message": "missing required schema column"})

    for index, raw in enumerate(rows, start=1):
        row = normalize_manual_benchmark_row(raw, pip_factor=pip_factor)
        normalized_rows.append(row)
        sample_id = row.get("sample_id") or f"ROW_{index}"
        decision = row.get("user_decision", "")
        quality = row.get("user_quality", "")
        outcome = row.get("actual_outcome", "")

        if decision not in USER_DECISIONS:
            errors.append({"sample_id": sample_id, "field": "user_decision", "message": "invalid decision"})
        if quality not in USER_QUALITIES:
            errors.append({"sample_id": sample_id, "field": "user_quality", "message": "invalid quality"})
        if outcome not in OUTCOMES:
            errors.append({"sample_id": sample_id, "field": "actual_outcome", "message": "invalid outcome"})

        for field in ALWAYS_REQUIRED_FIELDS:
            if not _clean(row.get(field)):
                errors.append({"sample_id": sample_id, "field": field, "message": "required field missing"})

        if decision == "TAKE":
            for field in TAKE_REQUIRED_FIELDS:
                if not _clean(row.get(field)):
                    errors.append({"sample_id": sample_id, "field": field, "message": "TAKE sample requires this field"})
        elif decision == "SKIP":
            for field in SKIP_REQUIRED_FIELDS:
                if not _clean(row.get(field)):
                    errors.append({"sample_id": sample_id, "field": field, "message": "SKIP sample requires this field"})
            if not _clean(row.get("measurable_reason_tags")) and not _clean(row.get("discretionary_reason_tags")):
                warnings.append({"sample_id": sample_id, "field": "reason_tags", "message": "SKIP sample should tag the skip reason if possible"})

        if row.get("be_after_tp1", "") not in TRI_STATE:
            errors.append({"sample_id": sample_id, "field": "be_after_tp1", "message": "must be TRUE, FALSE, or UNKNOWN"})
        if not _clean(row.get("be_after_tp1")):
            warnings.append({"sample_id": sample_id, "field": "be_after_tp1", "message": "BE after TP1 should be explicitly TRUE, FALSE, or UNKNOWN"})

        if row.get("sl_distance_warning") == "TRUE":
            warnings.append({"sample_id": sample_id, "field": "sl_distance_usd", "message": "SL distance is above 12 XAUUSD price units"})

        if row.get("tp_anchor_valid") == "FALSE":
            warnings.append({"sample_id": sample_id, "field": "tp_anchor_level", "message": "TP anchor does not match H1 liquidity level"})

    return {
        "valid": not errors,
        "rows_loaded": len(rows),
        "errors": errors,
        "warnings": warnings,
        "normalized_rows": normalized_rows,
        "pre_entry_fields": PRE_ENTRY_FIELDS,
        "outcome_fields": ["actual_outcome", "final_r_multiple", "gross_win_flag", "decisive_win_flag", "be_flag"],
        "future_outcome_not_required_for_pre_entry_validation": True,
        "safety": SAFETY,
    }


def normalize_manual_benchmark_row(raw: dict[str, Any], *, pip_factor: float = 10.0) -> dict[str, Any]:
    row = {field: _clean(raw.get(field)) for field in MANUAL_BENCHMARK_FIELDS}
    row["symbol"] = row["symbol"].upper()
    row["direction"] = row["direction"].upper()
    row["user_decision"] = row["user_decision"].upper()
    row["user_quality"] = row["user_quality"].upper()
    row["actual_outcome"] = row["actual_outcome"].upper() if row["actual_outcome"] else "UNKNOWN"

    for field in [
        "opposite_m15_level_taken_first",
        "liquidity_level_taken",
        "m15_sequence_valid",
        "reclaim_detected",
        "rejection_detected",
        "price_reentered_range",
        "sl_distance_warning",
        "tp_anchor_valid",
        "be_after_tp1",
        "gross_win_flag",
        "decisive_win_flag",
        "be_flag",
    ]:
        row[field] = _tri_state(row.get(field))

    _fill_distance_pair(row, "sweep_depth", pip_factor)
    _fill_sl_distance(row)
    _fill_sl_warning(row)
    _fill_tp_anchor(row)
    _fill_outcome_flags(row)
    return row


def build_manual_benchmark_analysis(
    labels_path: str | Path,
    *,
    pip_factor: float = 10.0,
) -> ManualBenchmarkResult:
    raw_rows = read_manual_labels(labels_path)
    validation = validate_manual_benchmark_rows(raw_rows, pip_factor=pip_factor)
    rows = validation["normalized_rows"]
    frame = pd.DataFrame(rows, columns=MANUAL_BENCHMARK_FIELDS)
    summary = summarize_manual_benchmark(rows, validation=validation, pip_factor=pip_factor)
    take_samples = frame[frame["user_decision"].eq("TAKE")].copy() if not frame.empty else pd.DataFrame(columns=MANUAL_BENCHMARK_FIELDS)
    skip_samples = frame[frame["user_decision"].eq("SKIP")].copy() if not frame.empty else pd.DataFrame(columns=MANUAL_BENCHMARK_FIELDS)
    feature_distribution = build_feature_distribution(rows)
    reason_tags = build_reason_tags_summary(rows)
    report = render_manual_benchmark_report(summary, validation)
    return ManualBenchmarkResult(
        validation={key: value for key, value in validation.items() if key != "normalized_rows"},
        summary=summary,
        take_samples=take_samples,
        skip_samples=skip_samples,
        feature_distribution=feature_distribution,
        reason_tags_summary=reason_tags,
        report_markdown=report,
    )


def summarize_manual_benchmark(rows: list[dict[str, Any]], *, validation: dict[str, Any], pip_factor: float = 10.0) -> dict[str, Any]:
    decisions = Counter(row.get("user_decision") or "BLANK" for row in rows)
    qualities = Counter(row.get("user_quality") or "BLANK" for row in rows)
    screenshots = sum(1 for row in rows if _clean(row.get("screenshot_before_path")) or _clean(row.get("screenshot_after_path")))
    sl_values = [_to_float(row.get("sl_distance_usd")) for row in rows]
    sl_values = [value for value in sl_values if value is not None]
    tp_anchor = Counter(row.get("tp_anchor_valid") or "UNKNOWN" for row in rows)
    be_after_tp1 = Counter(row.get("be_after_tp1") or "UNKNOWN" for row in rows)
    measurable_tags = _tag_counter(rows, "measurable_reason_tags")
    discretionary_tags = _tag_counter(rows, "discretionary_reason_tags")
    outcome_metrics = compute_outcome_metrics(rows)
    verdict_flags = build_verdict_flags(rows, measurable_tags, discretionary_tags, outcome_metrics)

    return {
        "total_samples": len(rows),
        "take_count": decisions.get("TAKE", 0),
        "skip_count": decisions.get("SKIP", 0),
        "uncertain_count": decisions.get("UNCERTAIN", 0),
        "decision_distribution": dict(sorted(decisions.items())),
        "quality_distribution": dict(sorted(qualities.items())),
        "samples_with_screenshots": screenshots,
        "average_sl_distance_usd": _mean(sl_values),
        "average_sl_distance_pips": to_pips(_mean(sl_values), pip_factor) if sl_values else None,
        "sl_gt_12_warning_count": sum(1 for row in rows if row.get("sl_distance_warning") == "TRUE"),
        "tp_anchor_valid_count": tp_anchor.get("TRUE", 0),
        "tp_anchor_invalid_count": tp_anchor.get("FALSE", 0),
        "tp_anchor_unknown_count": tp_anchor.get("UNKNOWN", 0) + tp_anchor.get("", 0),
        "be_after_tp1_coverage": dict(sorted(be_after_tp1.items())),
        "top_manual_reason_tags": _top_tags(measurable_tags + discretionary_tags),
        "measurable_reason_tags": _top_tags(measurable_tags),
        "discretionary_reason_tags": _top_tags(discretionary_tags),
        "outcome_metrics": outcome_metrics,
        "validation_valid": validation["valid"],
        "validation_error_count": len(validation["errors"]),
        "validation_warning_count": len(validation["warnings"]),
        "verdict_flags": verdict_flags,
        "pip_factor_used": float(pip_factor),
        "safety": SAFETY,
    }


def compute_outcome_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    known = [row for row in rows if row.get("actual_outcome") not in {"", "UNKNOWN"}]
    complete_r = [_to_float(row.get("final_r_multiple")) for row in known]
    complete_r = [value for value in complete_r if value is not None]
    wins = [row for row in known if _is_gross_win(row)]
    be_rows = [row for row in known if _is_be(row)]
    decisive = [row for row in known if not _is_be(row)]
    decisive_wins = [row for row in decisive if _is_decisive_win(row)]
    losses_r = [value for value in complete_r if value < 0]
    wins_r = [value for value in complete_r if value > 0]
    enough_complete_r = len(complete_r) >= 10
    return {
        "outcome_rows": len(known),
        "outcome_data_complete": len(known) == len(rows) and len(rows) > 0,
        "gross_wr_including_be_timeout": _rate(len(wins), len(known)) if known else None,
        "decisive_wr_excluding_be": _rate(len(decisive_wins), len(decisive)) if decisive else None,
        "be_rate": _rate(len(be_rows), len(known)) if known else None,
        "pf": round(sum(wins_r) / abs(sum(losses_r)), 4) if enough_complete_r and losses_r else None,
        "avg_r": round(fmean(complete_r), 4) if enough_complete_r else None,
        "r_count": len(complete_r),
        "r_median": round(median(complete_r), 4) if complete_r else None,
        "r_min": round(min(complete_r), 4) if complete_r else None,
        "r_max": round(max(complete_r), 4) if complete_r else None,
        "performance_metrics_rule": "gross WR, decisive WR, and BE rate are reported separately when outcomes exist; BE is not collapsed into wins.",
    }


def build_feature_distribution(rows: list[dict[str, Any]]) -> pd.DataFrame:
    tracked = [
        "user_decision",
        "user_quality",
        "direction",
        "session",
        "h1_reference_mode",
        "h1_liquidity_level_type",
        "m15_sequence_valid",
        "opposite_m15_level_taken_first",
        "reaction_type",
        "reclaim_detected",
        "rejection_detected",
        "price_reentered_range",
        "reaction_speed_label",
        "sl_distance_warning",
        "tp_anchor_valid",
        "be_after_tp1",
        "actual_outcome",
    ]
    records: list[dict[str, Any]] = []
    total = len(rows)
    for field in tracked:
        counts = Counter((row.get(field) or "BLANK") for row in rows)
        for value, count in sorted(counts.items()):
            records.append({"feature": field, "value": value, "count": count, "rate": _rate(count, total)})
    return pd.DataFrame(records, columns=["feature", "value", "count", "rate"])


def build_reason_tags_summary(rows: list[dict[str, Any]]) -> pd.DataFrame:
    measurable = _tag_counter(rows, "measurable_reason_tags")
    discretionary = _tag_counter(rows, "discretionary_reason_tags")
    records: list[dict[str, Any]] = []
    for kind, counts in (("measurable", measurable), ("discretionary", discretionary)):
        total = sum(counts.values())
        for tag, count in counts.most_common():
            records.append({"tag_type": kind, "tag": tag, "count": count, "rate_within_type": _rate(count, total)})
    return pd.DataFrame(records, columns=["tag_type", "tag", "count", "rate_within_type"])


def write_manual_benchmark_outputs(result: ManualBenchmarkResult, output_dir: str | Path, *, docs_path: str | Path | None = None) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "validation_json": output / "manual_label_validation.json",
        "summary_json": output / "manual_label_summary.json",
        "take_samples_csv": output / "manual_take_samples.csv",
        "skip_samples_csv": output / "manual_skip_samples.csv",
        "feature_distribution_csv": output / "manual_feature_distribution.csv",
        "reason_tags_summary_csv": output / "manual_reason_tags_summary.csv",
    }
    paths["validation_json"].write_text(json.dumps(result.validation, indent=2, sort_keys=True, default=str), encoding="utf-8")
    paths["summary_json"].write_text(json.dumps(result.summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    _write_frame(result.take_samples, paths["take_samples_csv"], MANUAL_BENCHMARK_FIELDS)
    _write_frame(result.skip_samples, paths["skip_samples_csv"], MANUAL_BENCHMARK_FIELDS)
    _write_frame(result.feature_distribution, paths["feature_distribution_csv"], ["feature", "value", "count", "rate"])
    _write_frame(result.reason_tags_summary, paths["reason_tags_summary_csv"], ["tag_type", "tag", "count", "rate_within_type"])
    if docs_path:
        docs = Path(docs_path)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(result.report_markdown, encoding="utf-8")
        paths["docs_md"] = docs
    return {key: str(path) for key, path in paths.items()}


def write_manual_benchmark_doc(path: str | Path) -> str:
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    summary = summarize_manual_benchmark([], validation={"valid": True, "errors": [], "warnings": []})
    path_obj.write_text(render_manual_benchmark_report(summary, {"valid": True, "errors": [], "warnings": [], "rows_loaded": 0}), encoding="utf-8")
    return str(path_obj)


def render_manual_benchmark_report(summary: dict[str, Any], validation: dict[str, Any]) -> str:
    outcome = summary.get("outcome_metrics", {})
    flags = summary.get("verdict_flags", [])
    lines = [
        "# Strategy 2 Manual Benchmark Pack",
        "",
        "## Context",
        "",
        "Strategy 2 Liquidity Expansion remains research-only. The automated implementation has not reproduced the user's discretionary TAKE/SKIP quality, and previous tail-risk separators were post-hoc diagnostics only. This pack records manual benchmark decisions without turning them into strategy logic.",
        "",
        "## Purpose",
        "",
        "Capture manual TAKE, SKIP, and UNCERTAIN labels with reasons, screenshots, pre-entry context, and optional outcomes. A later branch can attempt to mechanize measurable reasons without leakage.",
        "",
        "## Safety",
        "",
        "- Strategy 3 untouched.",
        "- Adelin untouched.",
        "- data/XAUUSD/*.csv untouched.",
        "- No live trading.",
        "- No Telegram trade alerts.",
        "- No broker execution.",
        "- No orders.",
        "- No signal generation.",
        "- No optimization or target win-rate objective.",
        "",
        "## Schema",
        "",
        "Required TAKE fields: entry_price, stop_loss, tp1, direction, h1_liquidity_level_price, decision_time, user_reason_text.",
        "",
        "Required SKIP fields: user_reason_text. Entry, SL, TP, and outcome fields are optional for SKIP samples.",
        "",
        "Pre-entry fields exclude actual_outcome, final_r_multiple, gross_win_flag, decisive_win_flag, and be_flag. Outcomes are report-only and are not required for validation.",
        "",
        "## How To Use",
        "",
        "1. Generate the template: `python scripts/create_strategy_2_manual_label_template.py --schema manual_benchmark --output-dir backtests/reports/strategy_2_manual_benchmark`",
        "2. Save a filled copy as `manual_labels.csv` in the same output directory.",
        "3. Include TAKE, SKIP, and UNCERTAIN examples. Do not include only winners.",
        "4. Run: `python scripts/analyze_strategy_2_manual_benchmark.py --labels-path backtests/reports/strategy_2_manual_benchmark/manual_labels.csv --output-dir backtests/reports/strategy_2_manual_benchmark --dry-run`",
        "",
        "## Current Results",
        "",
        f"- total samples: `{summary.get('total_samples', 0)}`",
        f"- TAKE count: `{summary.get('take_count', 0)}`",
        f"- SKIP count: `{summary.get('skip_count', 0)}`",
        f"- UNCERTAIN count: `{summary.get('uncertain_count', 0)}`",
        f"- quality distribution: `{json.dumps(summary.get('quality_distribution', {}), sort_keys=True)}`",
        f"- samples with screenshots: `{summary.get('samples_with_screenshots', 0)}`",
        f"- average SL distance: `{summary.get('average_sl_distance_usd')}` price units / `{summary.get('average_sl_distance_pips')}` pips",
        f"- SL >12 warnings: `{summary.get('sl_gt_12_warning_count', 0)}`",
        f"- TP anchor valid/invalid/unknown: `{summary.get('tp_anchor_valid_count', 0)}` / `{summary.get('tp_anchor_invalid_count', 0)}` / `{summary.get('tp_anchor_unknown_count', 0)}`",
        f"- BE-after-TP1 coverage: `{json.dumps(summary.get('be_after_tp1_coverage', {}), sort_keys=True)}`",
        f"- top measurable tags: `{json.dumps(summary.get('measurable_reason_tags', []), sort_keys=True)}`",
        f"- top discretionary tags: `{json.dumps(summary.get('discretionary_reason_tags', []), sort_keys=True)}`",
        "",
        "## Outcome Metrics",
        "",
        f"- gross WR including BE/timeouts: `{outcome.get('gross_wr_including_be_timeout')}`",
        f"- decisive WR excluding BE: `{outcome.get('decisive_wr_excluding_be')}`",
        f"- BE rate: `{outcome.get('be_rate')}`",
        f"- PF: `{outcome.get('pf')}`",
        f"- AvgR: `{outcome.get('avg_r')}`",
        "",
        "BE is reported separately and is not collapsed into wins.",
        "",
        "## Validation",
        "",
        f"- valid: `{validation.get('valid')}`",
        f"- rows loaded: `{validation.get('rows_loaded', summary.get('total_samples', 0))}`",
        f"- errors: `{len(validation.get('errors', []))}`",
        f"- warnings: `{len(validation.get('warnings', []))}`",
        "",
        "## Verdict Flags",
        "",
        "\n".join(f"- `{flag}`" for flag in flags),
        "",
        "## Next Step",
        "",
        "Strategy 2-only next branch: `feat/strategy-2-manual-benchmark-replay-check` after the user provides filled manual labels.",
    ]
    return "\n".join(lines) + "\n"


def build_verdict_flags(
    rows: list[dict[str, Any]],
    measurable_tags: Counter[str],
    discretionary_tags: Counter[str],
    outcome_metrics: dict[str, Any],
) -> list[str]:
    flags = ["STRATEGY_2_MANUAL_BENCHMARK_FOUNDATION_CREATED"]
    take_count = sum(1 for row in rows if row.get("user_decision") == "TAKE")
    skip_count = sum(1 for row in rows if row.get("user_decision") == "SKIP")
    if take_count < 30:
        flags.append("STRATEGY_2_MANUAL_SAMPLE_TOO_SMALL_FOR_EDGE")
    if skip_count == 0:
        flags.append("STRATEGY_2_NO_SKIP_CONTROL_GROUP")
    if not outcome_metrics.get("outcome_data_complete"):
        flags.append("STRATEGY_2_OUTCOME_DATA_INCOMPLETE")
    flags.append("STRATEGY_2_MANUAL_SELECTION_NEEDS_MECHANIZATION")
    if sum(discretionary_tags.values()) >= sum(measurable_tags.values()):
        flags.append("STRATEGY_2_MANUAL_SELECTION_NOT_YET_MECHANIZED")
    flags.extend(["STRATEGY_2_REMAINS_RESEARCH_ONLY", "NO_LIVE_DEPLOYMENT_DECISION"])
    return flags


def _write_frame(frame: pd.DataFrame, path: Path, columns: list[str]) -> None:
    if frame.empty:
        pd.DataFrame(columns=columns).to_csv(path, index=False)
        return
    frame.to_csv(path, index=False)


def _fill_distance_pair(row: dict[str, Any], prefix: str, pip_factor: float) -> None:
    usd_key = f"{prefix}_usd"
    pips_key = f"{prefix}_pips"
    usd = _to_float(row.get(usd_key))
    pips = _to_float(row.get(pips_key))
    if usd is not None and pips is None:
        row[pips_key] = _format_number(to_pips(usd, pip_factor))
    elif pips is not None and usd is None:
        row[usd_key] = _format_number(to_price_distance(pips, pip_factor))


def _fill_sl_distance(row: dict[str, Any]) -> None:
    current = _to_float(row.get("sl_distance_usd"))
    if current is not None:
        row["sl_distance_usd"] = _format_number(current)
        return
    entry = _to_float(row.get("entry_price"))
    stop = _to_float(row.get("stop_loss"))
    if entry is not None and stop is not None:
        row["sl_distance_usd"] = _format_number(abs(entry - stop))


def _fill_sl_warning(row: dict[str, Any]) -> None:
    sl = _to_float(row.get("sl_distance_usd"))
    if sl is None:
        row["sl_distance_warning"] = row["sl_distance_warning"] or "UNKNOWN"
    elif sl > 12:
        row["sl_distance_warning"] = "TRUE"
    elif row["sl_distance_warning"] in {"", "UNKNOWN"}:
        row["sl_distance_warning"] = "FALSE"


def _fill_tp_anchor(row: dict[str, Any]) -> None:
    provided = row.get("tp_anchor_valid")
    anchor = _to_float(row.get("tp_anchor_level"))
    h1_level = _to_float(row.get("h1_liquidity_level_price"))
    if anchor is None or h1_level is None:
        row["tp_anchor_valid"] = provided or "UNKNOWN"
        return
    row["tp_anchor_valid"] = "TRUE" if abs(anchor - h1_level) <= 1e-6 else "FALSE"


def _fill_outcome_flags(row: dict[str, Any]) -> None:
    outcome = row.get("actual_outcome", "UNKNOWN")
    final_r = _to_float(row.get("final_r_multiple"))
    if row.get("be_flag") in {"", "UNKNOWN"}:
        row["be_flag"] = "TRUE" if outcome == "BE" or (final_r is not None and abs(final_r) <= 1e-9) else "FALSE" if outcome not in {"", "UNKNOWN"} else "UNKNOWN"
    if row.get("gross_win_flag") in {"", "UNKNOWN"}:
        row["gross_win_flag"] = "TRUE" if outcome in {"TP1", "TP2", "TP3", "TP4"} or (final_r is not None and final_r > 0) else "FALSE" if outcome not in {"", "UNKNOWN"} else "UNKNOWN"
    if row.get("decisive_win_flag") in {"", "UNKNOWN"}:
        row["decisive_win_flag"] = row["gross_win_flag"] if row["be_flag"] != "TRUE" else "UNKNOWN"


def _is_gross_win(row: dict[str, Any]) -> bool:
    if row.get("gross_win_flag") == "TRUE":
        return True
    final_r = _to_float(row.get("final_r_multiple"))
    return row.get("actual_outcome") in {"TP1", "TP2", "TP3", "TP4"} or (final_r is not None and final_r > 0)


def _is_decisive_win(row: dict[str, Any]) -> bool:
    if row.get("decisive_win_flag") == "TRUE":
        return True
    return _is_gross_win(row)


def _is_be(row: dict[str, Any]) -> bool:
    if row.get("be_flag") == "TRUE" or row.get("actual_outcome") == "BE":
        return True
    final_r = _to_float(row.get("final_r_multiple"))
    return final_r is not None and abs(final_r) <= 1e-9


def _tag_counter(rows: list[dict[str, Any]], field: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        for tag in _split_tags(row.get(field)):
            counts[tag] += 1
    return counts


def _split_tags(value: Any) -> list[str]:
    text = _clean(value)
    if not text:
        return []
    normalized = text.replace("|", ";").replace(",", ";")
    return [part.strip().lower() for part in normalized.split(";") if part.strip()]


def _top_tags(counter: Counter[str], limit: int = 10) -> list[dict[str, Any]]:
    return [{"tag": tag, "count": count} for tag, count in counter.most_common(limit)]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _tri_state(value: Any) -> str:
    text = _clean(value).upper()
    if text in {"TRUE", "T", "YES", "Y", "1"}:
        return "TRUE"
    if text in {"FALSE", "F", "NO", "N", "0"}:
        return "FALSE"
    if text in {"UNKNOWN", "UNCLEAR", ""}:
        return "UNKNOWN" if text else ""
    return text


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _format_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{round(float(value), 6):g}"


def _mean(values: list[float]) -> float | None:
    return round(fmean(values), 4) if values else None


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


__all__ = [
    "MANUAL_BENCHMARK_FIELDS",
    "ManualBenchmarkResult",
    "build_manual_benchmark_analysis",
    "compute_outcome_metrics",
    "normalize_manual_benchmark_row",
    "render_manual_benchmark_report",
    "to_pips",
    "to_price_distance",
    "validate_manual_benchmark_rows",
    "write_manual_benchmark_doc",
    "write_manual_benchmark_outputs",
    "write_manual_benchmark_template",
]
