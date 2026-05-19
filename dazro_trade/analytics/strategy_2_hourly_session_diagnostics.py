from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from dazro_trade.analysis.human_trade_management import metric_block_from_r


STRATEGY_2_NAMES = {"strategy_2_liquidity_expansion", "strategy_2_0", "Strategy 2.0"}
HUMAN_BENCHMARK_HYPOTHESIS = {
    "average_RR": 3.36,
    "win_rate": 0.62,
    "best_window_local_hypothesis": "14:00-16:00",
    "status": "unverified_benchmark_hypothesis",
}
VARIANT_RESULT_FIELDS = {
    "baseline": "result_baseline_R",
    "hard_be_10": "result_hard_be_R",
    "m5_confirmed_be_10": "result_m5_confirmed_be_R",
    "structural_be": "result_structural_be_R",
    "partial_15": "result_partial15_R",
    "partial_20": "result_partial20_R",
    "exit_bad_m5": "result_exit_bad_m5_R",
    "hold_healthy_retest": "result_hold_healthy_retest_R",
    "runner_liquidity": "result_runner_liquidity_R",
}
OUTCOME_COUNT_FIELDS = {
    "TP count": ("outcome", "TP", "TP1", "TP2", "TP3", "TP4"),
    "SL count": ("outcome", "SL"),
    "BE count": ("outcome", "BE"),
    "TIMEOUT/END_OF_DATA count": ("outcome", "TIMEOUT_CLOSE", "END_OF_DATA_CLOSE", "STILL_OPEN"),
}


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y.%m.%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def _trade_timestamp(row: dict[str, Any]) -> datetime | None:
    for field in ("entry_timestamp", "signal_timestamp", "timestamp", "time", "exit_time"):
        ts = _parse_timestamp(row.get(field))
        if ts is not None:
            return ts
    return None


def extract_trade_hour(row: dict[str, Any]) -> int | None:
    ts = _trade_timestamp(row)
    return ts.hour if ts is not None else None


def derived_session_from_hour(hour: int | None) -> str:
    if hour is None:
        return "UNKNOWN"
    if 0 <= hour < 7:
        return "Asia"
    if 7 <= hour < 13:
        return "London"
    if 13 <= hour < 21:
        return "NewYork"
    return "LateUS"


def in_14_16_window(row: dict[str, Any]) -> bool:
    hour = extract_trade_hour(row)
    return hour in {14, 15}


def _strategy_2_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        strategy = str(row.get("strategy") or row.get("strategy_name") or "")
        if not strategy or strategy in STRATEGY_2_NAMES:
            out.append(row)
    return out


def _r_value(row: dict[str, Any], field: str | None = None) -> float | None:
    if field:
        return _to_float(row.get(field))
    for candidate in ("r_multiple", "result_baseline_R", "trade_r_multiple"):
        value = _to_float(row.get(candidate))
        if value is not None:
            return value
    return None


def _metric_block(rows: list[dict[str, Any]], *, r_field: str | None = None) -> dict[str, Any]:
    values = [value for row in rows if (value := _r_value(row, r_field)) is not None]
    metrics = metric_block_from_r(values)
    metrics["TP_count"] = _count_outcomes(rows, {"TP", "TP1", "TP2", "TP3", "TP4"})
    metrics["SL_count"] = _count_outcomes(rows, {"SL"})
    metrics["BE_count"] = _count_outcomes(rows, {"BE"})
    metrics["partial_hit_count"] = sum(1 for row in rows if _truthy(row.get("hit_partial_15")) or _truthy(row.get("hit_partial_20")))
    metrics["runner_hit_count"] = sum(1 for row in rows if str(row.get("runner_opportunity") or "") != "STANDARD_TP" and row.get("runner_opportunity") not in (None, ""))
    metrics["TIMEOUT_END_OF_DATA_count"] = _count_outcomes(rows, {"TIMEOUT_CLOSE", "END_OF_DATA_CLOSE", "STILL_OPEN"})
    mfe_values = [value for row in rows if (value := _to_float(row.get("mfe_R") or row.get("mfe"))) is not None]
    mae_values = [value for row in rows if (value := _to_float(row.get("mae_R") or row.get("mae"))) is not None]
    metrics["average_MFE"] = round(sum(mfe_values) / len(mfe_values), 4) if mfe_values else None
    metrics["average_MAE"] = round(sum(mae_values) / len(mae_values), 4) if mae_values else None
    return metrics


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _count_outcomes(rows: list[dict[str, Any]], names: set[str]) -> int:
    return sum(1 for row in rows if str(row.get("outcome") or "").upper() in names)


def build_strategy_2_hourly_session_diagnostics(
    rows: Iterable[dict[str, Any]],
    columns: Iterable[str] | None = None,
    *,
    source_path: str = "",
) -> dict[str, Any]:
    rows = list(rows)
    columns = list(columns or (list(rows[0].keys()) if rows else []))
    s2_rows = _strategy_2_rows(rows)
    warnings: list[str] = []
    if not rows:
        warnings.append("NO_TRADE_ROWS_AVAILABLE")
    if not s2_rows and rows:
        warnings.append("NO_STRATEGY_2_ROWS_FOUND")
    if not any(field in columns for field in ("entry_timestamp", "signal_timestamp", "timestamp", "time")):
        warnings.append("TIMESTAMP_FIELD_MISSING")

    breakdown_rows: list[dict[str, Any]] = []
    breakdown_rows.append({"scope": "full_day", "category": "ALL", **_metric_block(s2_rows)})
    for hour in range(24):
        sub = [row for row in s2_rows if extract_trade_hour(row) == hour]
        breakdown_rows.append({"scope": "hour", "category": f"{hour:02d}:00", **_metric_block(sub)})

    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in s2_rows:
        session = str(row.get("session") or "").strip() or derived_session_from_hour(extract_trade_hour(row))
        by_session[session].append(row)
    for session in sorted(set(by_session) | {"Asia", "London", "NewYork", "LateUS"}):
        breakdown_rows.append({"scope": "session", "category": session, **_metric_block(by_session.get(session, []))})

    window_rows = [row for row in s2_rows if in_14_16_window(row)]
    breakdown_rows.append({"scope": "dedicated_window", "category": "14:00-16:00", **_metric_block(window_rows)})

    variant_rows = []
    for variant, field in VARIANT_RESULT_FIELDS.items():
        variant_rows.append({"variant": variant, **_metric_block(s2_rows, r_field=field)})

    summary = {
        "research_only": True,
        "live_filter_activated": False,
        "source_path": source_path,
        "columns_available": columns,
        "warnings": warnings,
        "human_benchmark_hypothesis": HUMAN_BENCHMARK_HYPOTHESIS,
        "total_rows": len(rows),
        "strategy_2_rows": len(s2_rows),
        "full_day": _metric_block(s2_rows),
        "window_14_16": _metric_block(window_rows),
        "window_14_16_trade_ids": [row.get("trade_id") for row in window_rows if row.get("trade_id")],
        "hourly_trade_counts": {f"{hour:02d}:00": sum(1 for row in s2_rows if extract_trade_hour(row) == hour) for hour in range(24)},
        "session_trade_counts": {session: len(group) for session, group in sorted(by_session.items())},
        "management_variants": {row["variant"]: {k: v for k, v in row.items() if k != "variant"} for row in variant_rows},
        "notes": [
            "This diagnostic is report-only and does not activate 14:00-16:00 as a live filter.",
            "The 3.36 average RR / 62% WR human benchmark is treated as an unverified hypothesis.",
            "Management variants depend on exported path fields when available; missing path data is reported as a limitation.",
        ],
    }
    return {
        "breakdown_rows": breakdown_rows,
        "summary": summary,
        "variant_rows": variant_rows,
        "variant_summary": summary["management_variants"],
        "report_markdown": render_14_16_report(summary),
    }


def render_14_16_report(summary: dict[str, Any]) -> str:
    full = summary["full_day"]
    window = summary["window_14_16"]
    hypo = summary["human_benchmark_hypothesis"]
    lines = [
        "# Strategy 2.0 14:00-16:00 Human Benchmark Diagnostic",
        "",
        "Status: research-only report. No live session filter was activated.",
        "",
        "## Benchmark Hypothesis",
        "",
        f"- reported average RR: `{hypo['average_RR']}`",
        f"- reported win rate: `{hypo['win_rate']:.2%}`",
        f"- reported best current window: `{hypo['best_window_local_hypothesis']}`",
        f"- validation status: `{hypo['status']}`",
        "",
        "## Full Day vs 14:00-16:00",
        "",
        "| scope | trades | PF | WR | AvgR | MedianR | total_R | MaxDD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        _metric_md_row("full_day", full),
        _metric_md_row("14:00-16:00", window),
        "",
        "## Interpretation",
        "",
        "- This report can show whether the window deserves a future controlled diagnostic.",
        "- It does not prove the window is tradable and does not alter live behavior.",
        "- BE, partial, M5-close, retest, and runner overlays are compared as report variants only.",
        "",
        "## Warnings",
        "",
    ]
    warnings = summary.get("warnings") or ["none"]
    for warning in warnings:
        lines.append(f"- {warning}")
    return "\n".join(lines) + "\n"


def _metric_md_row(label: str, metrics: dict[str, Any]) -> str:
    return (
        f"| {label} | {metrics.get('trades')} | {metrics.get('PF')} | {metrics.get('WR')} | "
        f"{metrics.get('AvgR')} | {metrics.get('MedianR')} | {metrics.get('total_R')} | {metrics.get('MaxDD')} |"
    )


def write_strategy_2_hourly_session_outputs(report: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "breakdown_csv": str(output_dir / "strategy_2_hourly_session_breakdown.csv"),
        "summary_json": str(output_dir / "strategy_2_hourly_session_summary.json"),
        "report_md": str(output_dir / "strategy_2_14_16_report.md"),
        "variants_csv": str(output_dir / "strategy_2_management_variants.csv"),
        "variants_summary_json": str(output_dir / "strategy_2_management_variants_summary.json"),
    }
    _write_csv(Path(paths["breakdown_csv"]), report["breakdown_rows"])
    Path(paths["summary_json"]).write_text(json.dumps(report["summary"], indent=2), encoding="utf-8")
    Path(paths["report_md"]).write_text(report["report_markdown"], encoding="utf-8")
    _write_csv(Path(paths["variants_csv"]), report["variant_rows"])
    Path(paths["variants_summary_json"]).write_text(json.dumps(report["variant_summary"], indent=2), encoding="utf-8")
    return paths


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def outcome_distribution(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(row.get("outcome") or "UNKNOWN") for row in rows))


__all__ = [
    "HUMAN_BENCHMARK_HYPOTHESIS",
    "STRATEGY_2_NAMES",
    "VARIANT_RESULT_FIELDS",
    "build_strategy_2_hourly_session_diagnostics",
    "derived_session_from_hour",
    "extract_trade_hour",
    "in_14_16_window",
    "outcome_distribution",
    "render_14_16_report",
    "write_strategy_2_hourly_session_outputs",
]
