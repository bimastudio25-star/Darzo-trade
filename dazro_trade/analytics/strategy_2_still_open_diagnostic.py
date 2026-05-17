from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable


REQUIRED_COLUMNS = {
    "strategy",
    "outcome",
    "r_multiple",
    "entry",
    "direction",
    "sl_distance",
    "mae",
    "mfe",
    "bars_held",
}
OPTIONAL_COLUMNS = {
    "symbol",
    "session",
    "setup_mode",
    "exit_price",
    "close_price",
    "final_price",
    "last_price",
    "max_bars",
    "max_sim_bars",
}
AFFECTED_STRATEGIES = [
    "strategy_1_adelin_scalp",
    "strategy_2_liquidity_expansion",
    "any_strategy_using_shared_simulator",
]
SMOKE_RECOMMENDED = "SMOKE_BACKTEST_RECOMMENDED"
CSV_SUFFICIENT = "CSV_DIAGNOSTIC_SUFFICIENT_FOR_PRELIMINARY_IMPACT_ESTIMATE"


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def _read_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return round(fmean(values), 4) if values else None


def _median(values: Iterable[float]) -> float | None:
    values = list(values)
    return round(median(values), 4) if values else None


def _pct(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def _candidate_final_price(row: dict[str, str]) -> tuple[float | None, str | None]:
    for field in ("final_price", "last_price", "close_price", "exit_price"):
        value = _to_float(row.get(field))
        if value is not None:
            return value, field
    return None, None


def classify_still_open_policy_effect(row: dict[str, str], columns: set[str]) -> str:
    missing: list[str] = []
    final_price, _ = _candidate_final_price(row)
    if final_price is None:
        missing.append("final_price")
    if _to_float(row.get("entry")) is None:
        missing.append("entry_price")
    if not row.get("direction"):
        missing.append("side")
    if _to_float(row.get("sl_distance")) in (None, 0.0):
        missing.append("risk")
    if missing:
        if len(missing) == 1:
            return f"cannot_reclassify_missing_{missing[0]}"
        return "cannot_reclassify_missing_required_fields"
    if not ({"max_bars", "max_sim_bars"} & columns):
        return "would_close_with_new_policy_unknown_close_reason"
    bars_held = _to_float(row.get("bars_held"))
    max_bars = _to_float(row.get("max_bars") or row.get("max_sim_bars"))
    if bars_held is not None and max_bars is not None and bars_held >= max_bars:
        return "would_timeout_close"
    return "would_end_of_data_close"


def _r_values(rows: list[dict[str, str]]) -> list[float]:
    return [value for row in rows if (value := _to_float(row.get("r_multiple"))) is not None]


def _outcome_distribution(rows: list[dict[str, str]]) -> dict[str, int]:
    return dict(Counter(row.get("outcome") or "UNKNOWN" for row in rows))


def _bucket_bars(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "UNKNOWN"
    if number < 60:
        return "0-59"
    if number < 240:
        return "60-239"
    if number < 480:
        return "240-479"
    return "480+"


def _breakdown(rows: list[dict[str, str]], field: str, columns: set[str]) -> dict[str, int] | str:
    if field not in columns:
        return "field_not_available_skip"
    return dict(Counter((row.get(field) or "UNKNOWN") for row in rows))


def _mfe_mae_estimates(still_rows: list[dict[str, str]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    estimate_rows: list[dict[str, Any]] = []
    missing = 0
    for idx, row in enumerate(still_rows):
        mfe = _to_float(row.get("mfe"))
        mae = _to_float(row.get("mae"))
        risk = _to_float(row.get("sl_distance"))
        if mfe is None or mae is None or risk in (None, 0.0):
            missing += 1
            continue
        optimistic = round(float(mfe) / float(risk), 4)
        pessimistic = round(-abs(float(mae)) / float(risk), 4)
        midpoint = round((optimistic + pessimistic) / 2, 4)
        width = round(optimistic - pessimistic, 4)
        estimate_rows.append(
            {
                "row_index": idx,
                "strategy": row.get("strategy"),
                "timestamp": row.get("timestamp"),
                "r_estimate_optimistic": optimistic,
                "r_estimate_pessimistic": pessimistic,
                "r_estimate_midpoint": midpoint,
                "r_estimate_range_width": width,
            }
        )
    optimistic = [row["r_estimate_optimistic"] for row in estimate_rows]
    pessimistic = [row["r_estimate_pessimistic"] for row in estimate_rows]
    midpoint = [row["r_estimate_midpoint"] for row in estimate_rows]
    width = [row["r_estimate_range_width"] for row in estimate_rows]
    wide = [value for value in width if value > 1.5]
    return (
        {
            "note": "estimate from MFE/MAE, not actual reclassification. True r_multiple requires running the simulator with the new TIMEOUT_CLOSE / END_OF_DATA_CLOSE policy on candle data. This lightweight diagnostic does not claim actual historical exits.",
            "count_with_mfe_mae": len(estimate_rows),
            "count_without_mfe_mae": missing,
            "r_estimate_optimistic_mean": _mean(optimistic),
            "r_estimate_optimistic_median": _median(optimistic),
            "r_estimate_pessimistic_mean": _mean(pessimistic),
            "r_estimate_pessimistic_median": _median(pessimistic),
            "r_estimate_midpoint_mean": _mean(midpoint),
            "r_estimate_midpoint_median": _median(midpoint),
            "range_width_mean": _mean(width),
            "range_width_median": _median(width),
            "range_width_gt_1_5r_count": len(wide),
            "range_width_gt_1_5r_pct": _pct(len(wide), len(estimate_rows)),
        },
        estimate_rows,
    )


def _strategy_audit(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for strategy in sorted({row.get("strategy") or "UNKNOWN" for row in rows}):
        sub = [row for row in rows if (row.get("strategy") or "UNKNOWN") == strategy]
        still = [row for row in sub if row.get("outcome") == "STILL_OPEN"]
        still_r = _r_values(still)
        out.append(
            {
                "strategy": strategy,
                "total_trades": len(sub),
                "still_open_count": len(still),
                "still_open_rate": _pct(len(still), len(sub)),
                "still_open_average_r": _mean(still_r),
                "metric_revision_effective_for_strategy": bool(still),
            }
        )
    return out


def _smoke_decision(strategy_2: dict[str, Any], policy_counts: dict[str, int], mfe_mae: dict[str, Any], columns: set[str]) -> dict[str, Any]:
    still_count = int(strategy_2["still_open_count"])
    triggers: list[str] = []
    cannot = sum(count for key, count in policy_counts.items() if key.startswith("cannot_reclassify_missing"))
    if still_count and cannot / still_count > 0.2:
        triggers.append("missing_required_fields_gt_20pct")
    width_count = int(mfe_mae.get("range_width_gt_1_5r_count") or 0)
    estimate_count = int(mfe_mae.get("count_with_mfe_mae") or 0)
    if estimate_count and width_count / estimate_count > 0.5:
        triggers.append("mfe_mae_range_width_gt_1_5r_for_gt_50pct")
    if float(strategy_2["still_open_rate"]) > 0.10:
        triggers.append("strategy_2_still_open_rate_gt_10pct")
    if not ({"max_bars", "max_sim_bars"} & columns) or not ({"final_price", "last_price", "close_price", "exit_price"} & columns):
        triggers.append("close_reason_or_actual_close_not_reliable_from_csv")
    return {
        "decision": SMOKE_RECOMMENDED if triggers else CSV_SUFFICIENT,
        "triggers": triggers,
        "recommended_follow_up": (
            "If executed later, use a maximum 3-5 day, single-symbol, Strategy 2.0 only, report-only smoke backtest. Do not run a full 3-month backtest for this diagnostic."
            if triggers
            else None
        ),
    }


def build_diagnostic(
    rows: list[dict[str, str]],
    columns: list[str],
    summary: dict[str, Any],
    *,
    executed_trades_path: str,
    summary_path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    column_set = set(columns)
    missing_columns = sorted((REQUIRED_COLUMNS | OPTIONAL_COLUMNS) - column_set)
    strategy_2_rows = [row for row in rows if row.get("strategy") == "strategy_2_liquidity_expansion"]
    strategy_2_still = [row for row in strategy_2_rows if row.get("outcome") == "STILL_OPEN"]
    policy_counts = dict(Counter(classify_still_open_policy_effect(row, column_set) for row in strategy_2_still))
    r_values = _r_values(strategy_2_rows)
    still_r = _r_values(strategy_2_still)
    neutral = [row for row in strategy_2_still if _to_float(row.get("r_multiple")) == 0.0]
    positive = [row for row in strategy_2_still if (_to_float(row.get("r_multiple")) or 0.0) > 0.0]
    negative = [row for row in strategy_2_still if (_to_float(row.get("r_multiple")) or 0.0) < 0.0]
    mfe_mae, estimate_rows = _mfe_mae_estimates(strategy_2_still)
    strategy_2 = {
        "total_trades": len(strategy_2_rows),
        "closed_trades": len(strategy_2_rows) - len(strategy_2_still),
        "still_open_count": len(strategy_2_still),
        "still_open_percentage": _pct(len(strategy_2_still), len(strategy_2_rows)),
        "still_open_rate": _pct(len(strategy_2_still), len(strategy_2_rows)),
        "outcome_distribution": _outcome_distribution(strategy_2_rows),
        "average_r_all_trades": _mean(r_values),
        "average_r_still_open": _mean(still_r),
        "still_open_r_multiple_zero_count": len(neutral),
        "still_open_r_multiple_positive_count": len(positive),
        "still_open_r_multiple_negative_count": len(negative),
        "still_open_r_multiple_non_null_count": len(still_r),
        "breakdowns": {
            "setup_mode": _breakdown(strategy_2_still, "setup_mode", column_set),
            "symbol": _breakdown(strategy_2_still, "symbol", column_set),
            "direction": _breakdown(strategy_2_still, "direction", column_set),
            "session": _breakdown(strategy_2_still, "session", column_set),
            "bars_held_bucket": dict(Counter(_bucket_bars(row.get("bars_held")) for row in strategy_2_still)),
            "max_sim_bars_bucket": "field_not_available_skip" if not ({"max_bars", "max_sim_bars"} & column_set) else {},
        },
        "policy_effect_classification": policy_counts,
        "reclassifiable_without_full_backtest_count": sum(
            count for key, count in policy_counts.items() if key.startswith("would_")
        ),
        "not_reclassifiable_count": sum(
            count for key, count in policy_counts.items() if key.startswith("cannot_")
        ),
    }
    smoke = _smoke_decision(strategy_2, policy_counts, mfe_mae, column_set)
    return (
        {
            "metric_revision_due_to_still_open_policy": True,
            "affected_strategies": AFFECTED_STRATEGIES,
            "source_data": {
                "executed_trades_csv": executed_trades_path,
                "summary_json": summary_path,
                "rows_read": len(rows),
                "columns_available": columns,
                "columns_missing_relevant": missing_columns,
                "summary_keys": list(summary.keys()),
            },
            "strategy_2": strategy_2,
            "cross_strategy_still_open_audit": _strategy_audit(rows),
            "mfe_mae_estimate": mfe_mae,
            "smoke_decision": smoke,
            "warnings": [
                "CLOSE_REASON_FIELD_NOT_AVAILABLE" if not ({"max_bars", "max_sim_bars"} & column_set) else None,
                "FINAL_CLOSE_FIELD_NOT_AVAILABLE_FOR_STILL_OPEN"
                if strategy_2_still and all(_candidate_final_price(row)[0] is None for row in strategy_2_still)
                else None,
                "FULL_BACKTEST_NOT_RUN",
            ],
        },
        estimate_rows,
    )


def render_markdown(report: dict[str, Any]) -> str:
    s2 = report["strategy_2"]
    mfe = report["mfe_mae_estimate"]
    smoke = report["smoke_decision"]
    lines = [
        "# Strategy 2.0 STILL_OPEN Diagnostic",
        "",
        "This is a lightweight CSV/JSON diagnostic only. No full backtest was run.",
        "",
        "## Source Data",
        "",
        f"- executed_trades.csv: `{report['source_data']['executed_trades_csv']}`",
        f"- summary.json: `{report['source_data']['summary_json']}`",
        f"- rows read: {report['source_data']['rows_read']}",
        f"- columns available: {', '.join(report['source_data']['columns_available'])}",
        f"- relevant columns missing: {', '.join(report['source_data']['columns_missing_relevant']) or 'none'}",
        "",
        "## Metric Revision Warning",
        "",
        "- metric_revision_due_to_still_open_policy: true",
        f"- affected_strategies: {', '.join(report['affected_strategies'])}",
        "- Old reports could treat STILL_OPEN with r_multiple=0 as metric-neutral.",
        "- Future reports may change PF / WR / AvgR / MaxDD because unresolved trades close at available close.",
        "- This does not mean Strategy 2.0 improved; it means metrics are more honest.",
        "- This does not re-open Adelin edge interpretation; Adelin remains lockdown/research-only.",
        "",
        "## Strategy 2.0 Totals",
        "",
        f"- total trades: {s2['total_trades']}",
        f"- closed trades: {s2['closed_trades']}",
        f"- STILL_OPEN trades: {s2['still_open_count']}",
        f"- STILL_OPEN percentage: {s2['still_open_percentage']:.2%}",
        f"- outcome distribution: `{json.dumps(s2['outcome_distribution'], sort_keys=True)}`",
        f"- average R all trades: {s2['average_r_all_trades']}",
        f"- average R STILL_OPEN: {s2['average_r_still_open']}",
        f"- STILL_OPEN r_multiple = 0: {s2['still_open_r_multiple_zero_count']}",
        "",
        "## Simulated Policy Effect From CSV",
        "",
        f"- classification counts: `{json.dumps(s2['policy_effect_classification'], sort_keys=True)}`",
        f"- reclassifiable without full backtest: {s2['reclassifiable_without_full_backtest_count']}",
        f"- not reclassifiable: {s2['not_reclassifiable_count']}",
        "",
        "## Cross-strategy STILL_OPEN Audit",
        "",
        "| strategy | total | STILL_OPEN | rate | avg R STILL_OPEN | metric revision effective |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in report["cross_strategy_still_open_audit"]:
        lines.append(
            f"| {row['strategy']} | {row['total_trades']} | {row['still_open_count']} | {row['still_open_rate']:.2%} | {row['still_open_average_r']} | {str(row['metric_revision_effective_for_strategy']).lower()} |"
        )
    lines.extend(
        [
            "",
            "## MFE/MAE Range Estimate",
            "",
            mfe["note"],
            "",
            f"- count with MFE/MAE: {mfe['count_with_mfe_mae']}",
            f"- count without MFE/MAE: {mfe['count_without_mfe_mae']}",
            f"- optimistic mean/median: {mfe['r_estimate_optimistic_mean']} / {mfe['r_estimate_optimistic_median']}",
            f"- pessimistic mean/median: {mfe['r_estimate_pessimistic_mean']} / {mfe['r_estimate_pessimistic_median']}",
            f"- midpoint mean/median: {mfe['r_estimate_midpoint_mean']} / {mfe['r_estimate_midpoint_median']}",
            f"- range width mean/median: {mfe['range_width_mean']} / {mfe['range_width_median']}",
            f"- range width > 1.5R: {mfe['range_width_gt_1_5r_count']} ({mfe['range_width_gt_1_5r_pct']:.2%})",
            "",
            "## Smoke Decision",
            "",
            f"- decision: `{smoke['decision']}`",
            f"- numeric triggers: {', '.join(smoke['triggers']) or 'none'}",
            f"- recommendation: {smoke['recommended_follow_up'] or 'No immediate smoke backtest recommended from these criteria.'}",
            "",
            "## Warnings",
            "",
        ]
    )
    for warning in [w for w in report.get("warnings", []) if w]:
        lines.append(f"- {warning}")
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], estimate_rows: list[dict[str, Any]], output_dir: Path, docs_path: Path | None = None) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "strategy_2_still_open_diagnostic.json"
    md_path = output_dir / "strategy_2_still_open_diagnostic.md"
    csv_path = output_dir / "strategy_2_still_open_diagnostic.csv"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = render_markdown(report)
    md_path.write_text(md, encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "row_index",
            "strategy",
            "timestamp",
            "r_estimate_optimistic",
            "r_estimate_pessimistic",
            "r_estimate_midpoint",
            "r_estimate_range_width",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(estimate_rows)
    paths = {"json": str(json_path), "markdown": str(md_path), "csv": str(csv_path)}
    if docs_path is not None:
        docs_path.parent.mkdir(parents=True, exist_ok=True)
        docs_path.write_text(md, encoding="utf-8")
        paths["docs_markdown"] = str(docs_path)
    return paths


def build_from_files(executed_trades: Path, summary_json: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows, columns = _read_csv(executed_trades)
    summary = _read_summary(summary_json)
    return build_diagnostic(
        rows,
        columns,
        summary,
        executed_trades_path=str(executed_trades),
        summary_path=str(summary_json),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Strategy 2.0 STILL_OPEN diagnostic from existing reports.")
    parser.add_argument("--executed-trades", default="backtests/reports/final/executed_trades.csv")
    parser.add_argument("--summary-json", default="backtests/reports/final/summary.json")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_still_open_diagnostic")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_still_open_diagnostic.md")
    args = parser.parse_args(argv)
    report, estimate_rows = build_from_files(Path(args.executed_trades), Path(args.summary_json))
    paths = write_report(report, estimate_rows, Path(args.output_dir), Path(args.docs_path))
    print(json.dumps(paths, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CSV_SUFFICIENT",
    "SMOKE_RECOMMENDED",
    "build_diagnostic",
    "build_from_files",
    "classify_still_open_policy_effect",
    "render_markdown",
    "write_report",
]
