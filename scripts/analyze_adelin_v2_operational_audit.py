from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.adelin_v2_operational_audit import (
    AdelinV2AuditConfig,
    audit_trade_row,
    build_audit_summary,
    diagnostic_to_row,
    filter_adelin_trade_rows,
    output_fieldnames,
)


COMMON_TRADE_PATHS = (
    Path("backtests/reports/final/executed_trades.csv"),
    Path("backtests/reports/candle_profile_full/executed_trades.csv"),
)
OUTPUT_CSV = "adelin_v2_trade_audit.csv"
OUTPUT_JSON = "adelin_v2_audit_summary.json"
OUTPUT_MD = "adelin_v2_operational_audit.md"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only structural audit of old Adelin exports against the Adelin v2 operational spec."
    )
    parser.add_argument("--trades-path", default=None, help="Existing executed_trades.csv or Adelin export to audit")
    parser.add_argument("--data-dir", default="data", help="Market data root. Read-only metadata only in this first audit.")
    parser.add_argument("--output-dir", default="backtests/reports/adelin_v2_operational_audit")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--number-theory-threshold-pips", type=float, default=5.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Keep the audit structural only. Output reports are still written; no market data enrichment is attempted.",
    )
    return parser.parse_args(argv)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _discover_trade_path(explicit: str | None) -> tuple[Path | None, dict[str, Any]]:
    if explicit:
        path = Path(explicit)
        return path, {
            "source_selection": "explicit_trades_path",
            "candidate_paths": [str(path)],
            "source_exists": path.exists(),
        }
    for path in COMMON_TRADE_PATHS:
        if path.exists():
            return path, {
                "source_selection": "default_common_path",
                "candidate_paths": [str(item) for item in COMMON_TRADE_PATHS],
                "source_exists": True,
            }
    report_root = Path("backtests/reports")
    discovered = sorted(report_root.glob("**/*adelin*trade*.csv")) if report_root.exists() else []
    if discovered:
        return discovered[0], {
            "source_selection": "discovered_adelin_named_report",
            "candidate_paths": [str(item) for item in discovered],
            "source_exists": True,
        }
    return None, {
        "source_selection": "no_trade_export_found",
        "candidate_paths": [str(item) for item in COMMON_TRADE_PATHS],
        "source_exists": False,
    }


def _read_csv_rows(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [dict(row) for row in reader]
        return rows, list(reader.fieldnames or [])


def _write_audit_csv(records: list[Any], output_dir: Path) -> None:
    with (output_dir / OUTPUT_CSV).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=output_fieldnames())
        writer.writeheader()
        for record in records:
            writer.writerow(diagnostic_to_row(record))


def _write_summary_json(summary: dict[str, Any], output_dir: Path) -> None:
    (output_dir / OUTPUT_JSON).write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _write_markdown_report(
    *,
    summary: dict[str, Any],
    output_dir: Path,
    source_metadata: dict[str, Any],
    records: list[Any],
) -> None:
    limitation_lines = [f"- `{item}`" for item in summary.get("data_limitations", [])] or ["- none recorded"]
    sample_rows = records[:25]
    lines = [
        "# Adelin v2 Operational Audit",
        "",
        "Status: research-only structural gap analysis.",
        "",
        (
            "Existing historical Adelin exports do not contain enough context to fully classify Adelin v2 logic. "
            "This audit is a structural gap analysis, not final validation."
        ),
        "",
        "## Scope",
        "",
        "- No live strategy was created.",
        "- No broker/order execution path was called.",
        "- No Telegram signal path was called.",
        "- Strategy 2, Strategy 3, VWAP, and market data are not modified by this script.",
        "- `--dry-run` keeps this first version structural and disables any market-data enrichment.",
        "",
        "## Source",
        "",
        f"- source_path: `{summary.get('source_path')}`",
        f"- source_selection: `{source_metadata.get('source_selection')}`",
        f"- source_exists: `{source_metadata.get('source_exists')}`",
        f"- source_rows_loaded: `{summary.get('source_rows_loaded')}`",
        "",
        "## Summary",
        "",
        f"- total_old_adelin_trades_loaded: `{summary.get('total_old_adelin_trades_loaded')}`",
        f"- trades_audited: `{summary.get('trades_audited')}`",
        f"- continuation_blocked_count: `{summary.get('continuation_blocked_count')}`",
        f"- unknown_insufficient_data_count: `{summary.get('unknown_insufficient_data_count')}`",
        f"- possible_reversal_count: `{summary.get('possible_reversal_count')}`",
        f"- dirty_reversal_count: `{summary.get('dirty_reversal_count')}`",
        f"- number_theory_confluence_count: `{summary.get('number_theory_confluence_count')}`",
        f"- reaction_zone_available_count: `{summary.get('reaction_zone_available_count')}`",
        "",
        "## Data Limitations",
        "",
        *limitation_lines,
        "",
        "## Sample Classifications",
        "",
        "| trade_id | time | direction | label | reasons | limitations |",
        "|---|---|---|---|---|---|",
    ]
    if sample_rows:
        for record in sample_rows:
            reasons = ", ".join(record.reason_codes) if record.reason_codes else ""
            limitations = ", ".join(record.limitations) if record.limitations else ""
            lines.append(
                f"| {record.trade_id or ''} | {record.signal_timestamp or record.entry_timestamp or ''} | "
                f"{record.direction or ''} | {record.final_adelin_v2_label.value} | {reasons} | {limitations} |"
            )
    else:
        lines.append("| | | | no Adelin rows audited | | |")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This output should be used to decide what evidence is missing from historical exports and visual-review packs. "
            "It is not a profitability claim and it does not make Adelin deployable.",
        ]
    )
    (output_dir / OUTPUT_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_path, source_metadata = _discover_trade_path(args.trades_path)
    rows: list[dict[str, Any]] = []
    fieldnames: list[str] = []
    data_limitations: list[str] = []
    if source_path is None:
        data_limitations.append("NO_TRADE_EXPORT_FOUND")
    elif not source_path.exists():
        data_limitations.append("TRADE_EXPORT_PATH_MISSING")
    else:
        rows, fieldnames = _read_csv_rows(source_path)

    if rows:
        adelin_rows, filter_metadata = filter_adelin_trade_rows(rows)
    else:
        adelin_rows, filter_metadata = [], {"filter_mode": "no_rows_loaded", "filter_limitation": None}
    if filter_metadata.get("filter_limitation"):
        data_limitations.append(str(filter_metadata["filter_limitation"]))
    if rows and not adelin_rows:
        data_limitations.append("NO_ADELIN_ROWS_FOUND_AFTER_STRATEGY_FILTER")

    cfg = AdelinV2AuditConfig(
        symbol=args.symbol,
        number_theory_threshold_pips=args.number_theory_threshold_pips,
    )
    records = [audit_trade_row(row, cfg) for row in adelin_rows]
    summary = build_audit_summary(
        records,
        source_rows_loaded=len(rows),
        source_path=str(source_path) if source_path is not None else None,
        data_limitations=data_limitations,
    )
    summary.update(
        {
            "generated_at": _utc_now(),
            "symbol": args.symbol,
            "data_dir": args.data_dir,
            "dry_run": bool(args.dry_run),
            "market_data_modified": False,
            "fieldnames": fieldnames,
            "filter_metadata": filter_metadata,
            "output_files": {
                "csv": str(output_dir / OUTPUT_CSV),
                "json": str(output_dir / OUTPUT_JSON),
                "markdown": str(output_dir / OUTPUT_MD),
            },
        }
    )
    _write_audit_csv(records, output_dir)
    _write_summary_json(summary, output_dir)
    _write_markdown_report(summary=summary, output_dir=output_dir, source_metadata=source_metadata, records=records)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_audit(args)
    print(json.dumps({
        "trades_audited": summary["trades_audited"],
        "continuation_blocked_count": summary["continuation_blocked_count"],
        "unknown_insufficient_data_count": summary["unknown_insufficient_data_count"],
        "output_dir": args.output_dir,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
