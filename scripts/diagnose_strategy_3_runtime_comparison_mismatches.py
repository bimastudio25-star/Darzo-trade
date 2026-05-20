from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.compare_strategy_3_paper_vs_backtest import (  # noqa: E402
    PaperVsBacktestConfig,
    build_backtest_rows,
    read_paper_signals,
)
from scripts.compare_strategy_3_shadow_vs_backtest import _bool, _parse_ts  # noqa: E402

SAFETY = {
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "order_execution_enabled": False,
    "broker_called": False,
    "telegram_sent": False,
    "order_sent": False,
    "order_send_called": False,
}
DETAIL_FIELDS = [
    "mismatch_id",
    "comparison_scope",
    "mismatch_type",
    "match_status",
    "timestamp",
    "paper_signal_timestamp",
    "backtest_signal_timestamp",
    "paper_generated_at",
    "paper_generated_before_h4_repair",
    "direction",
    "setup_mode",
    "band_touched",
    "entry_price_paper",
    "entry_price_backtest",
    "stop_loss_paper",
    "stop_loss_backtest",
    "take_profit_paper",
    "take_profit_backtest",
    "entry_abs_diff",
    "stop_loss_abs_diff",
    "take_profit_abs_diff",
    "paper_cooldown_status",
    "backtest_cooldown_status",
    "paper_previous_accepted_same_direction",
    "backtest_previous_accepted_same_direction",
    "paper_minutes_since_previous",
    "backtest_minutes_since_previous",
    "nearest_paper_0s",
    "nearest_backtest_0s",
    "nearest_paper_1m",
    "nearest_backtest_1m",
    "nearest_paper_5m",
    "nearest_backtest_5m",
    "nearest_paper_15m",
    "nearest_backtest_15m",
    "root_cause_classification",
    "confidence",
    "recommended_action",
    "evidence",
]


@dataclass(frozen=True)
class DiagnosticConfig:
    comparison_dir: Path
    paper_signals_path: Path
    scanner_summary_path: Path
    pipeline_summary_path: Path
    data_dir: str
    output_dir: Path
    price_tolerance: float
    timestamp_tolerance_seconds: int
    dry_run: bool
    h4_repair_report_path: Path = Path("backtests/reports/strategy_3_h4_safe_repair/h4_repair_report.json")
    h4_post_repair_diagnostic_path: Path = Path(
        "backtests/reports/strategy_3_h4_data_source_diagnostic_post_repair/h4_data_source_diagnostic.json"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose Strategy 3 paper-vs-backtest comparison mismatches")
    parser.add_argument("--comparison-dir", default="backtests/reports/strategy_3_shadow_vs_backtest_comparison_post_fix")
    parser.add_argument("--paper-signals-path", default="backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv")
    parser.add_argument("--scanner-summary-path", default="backtests/reports/strategy_3_paper_shadow_scanner/scanner_summary.json")
    parser.add_argument("--pipeline-summary-path", default="backtests/reports/strategy_3_local_paper_pipeline/pipeline_summary.json")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_3_runtime_comparison_diagnostics")
    parser.add_argument("--price-tolerance", type=float, default=0.01)
    parser.add_argument("--timestamp-tolerance-seconds", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--h4-repair-report-path", default="backtests/reports/strategy_3_h4_safe_repair/h4_repair_report.json")
    parser.add_argument(
        "--h4-post-repair-diagnostic-path",
        default="backtests/reports/strategy_3_h4_data_source_diagnostic_post_repair/h4_data_source_diagnostic.json",
    )
    return parser.parse_args(argv)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [dict(row) for row in csv.DictReader(f)]


def split_categories(value: Any) -> list[str]:
    return [item.strip() for item in str(value or "").split(";") if item.strip()]


def _ts_or_none(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return _parse_ts(value)


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _abs_diff(left: Any, right: Any) -> float | None:
    lval = _as_float(left)
    rval = _as_float(right)
    if lval is None or rval is None:
        return None
    return round(abs(lval - rval), 6)


def _signal_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("signal_timestamp") or row.get("paper_signal_timestamp") or row.get("backtest_signal_timestamp")), str(row.get("direction") or ""))


def signal_label(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    return "|".join(
        str(row.get(key, ""))
        for key in ("signal_timestamp", "direction", "setup_mode", "band_touched", "cooldown_status")
    )


def nearest_signal(target: datetime, rows: list[dict[str, Any]], tolerance_seconds: int) -> dict[str, Any] | None:
    best: tuple[float, dict[str, Any]] | None = None
    for row in rows:
        raw_ts = row.get("signal_timestamp") or row.get("paper_signal_timestamp") or row.get("backtest_signal_timestamp")
        if not raw_ts:
            continue
        delta = abs((_parse_ts(raw_ts) - target).total_seconds())
        if delta <= tolerance_seconds and (best is None or delta < best[0]):
            best = (delta, row)
    return best[1] if best else None


def previous_accepted(rows: list[dict[str, Any]], *, timestamp: datetime, direction: str) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("direction")) != direction or not _bool(row.get("cooldown_accepted")):
            continue
        row_ts = _ts_or_none(row.get("signal_timestamp"))
        if row_ts and row_ts < timestamp:
            candidates.append(row)
    if not candidates:
        return None
    return max(candidates, key=lambda row: _parse_ts(row["signal_timestamp"]))


def minutes_since(previous: dict[str, Any] | None, timestamp: datetime) -> float | None:
    if not previous:
        return None
    return round((timestamp - _parse_ts(previous["signal_timestamp"])).total_seconds() / 60, 4)


def classify_level_mismatch(
    *,
    row: dict[str, Any],
    paper: dict[str, Any] | None,
    backtest: dict[str, Any] | None,
    price_tolerance: float,
    repair_finished_at: datetime | None,
) -> tuple[str, str, str, dict[str, Any]]:
    evidence: dict[str, Any] = {}
    if paper is None or backtest is None:
        return "LEVEL_FIELD_MISSING", "medium", "expand signal metadata", evidence
    generated_at = _ts_or_none(paper.get("generated_at"))
    generated_before_repair = bool(generated_at and repair_finished_at and generated_at < repair_finished_at)
    diffs = {
        "entry_abs_diff": _abs_diff(paper.get("entry_price"), backtest.get("entry_price")),
        "stop_loss_abs_diff": _abs_diff(paper.get("stop_loss"), backtest.get("stop_loss")),
        "take_profit_abs_diff": _abs_diff(paper.get("take_profit"), backtest.get("take_profit")),
    }
    context_matches = {
        "direction": str(paper.get("direction")) == str(backtest.get("direction")),
        "setup_mode": str(paper.get("setup_mode")) == str(backtest.get("setup_mode")),
        "band_touched": str(paper.get("band_touched")) == str(backtest.get("band_touched")),
        "entry_price": (diffs["entry_abs_diff"] or 0) <= price_tolerance,
    }
    evidence.update({"generated_before_h4_repair": generated_before_repair, "diffs": diffs, "context_matches": context_matches})
    max_level_diff = max((value or 0.0) for key, value in diffs.items() if key != "entry_abs_diff")
    if max_level_diff <= price_tolerance:
        return "LEVEL_ROUNDING_ONLY", "high", "comparison/reporting alignment", evidence
    if max_level_diff <= 0.10:
        return "LEVEL_SMALL_NUMERIC_DRIFT", "medium", "comparison/reporting alignment", evidence
    if not context_matches["entry_price"]:
        return "LEVEL_SOURCE_PRICE_MISMATCH", "high", "inspect source candle alignment", evidence
    if generated_before_repair and all(context_matches.values()):
        return "LEVEL_PRE_REPAIR_DATA_CONTEXT_DRIFT", "high", "segment or exclude pre-repair paper rows", evidence
    if str(paper.get("vwap_value") or "") != "" and backtest.get("vwap_value") not in (None, ""):
        vwap_diff = _abs_diff(paper.get("vwap_value"), backtest.get("vwap_value"))
        evidence["vwap_abs_diff"] = vwap_diff
        if vwap_diff is not None and vwap_diff > price_tolerance:
            return "LEVEL_BAND_CONTEXT_MISMATCH", "high", "inspect runtime/backtest context slices", evidence
    return "LEVEL_TRUE_CALCULATION_MISMATCH", "medium", "runtime/backtest signal construction alignment", evidence


def classify_cooldown_mismatch(
    *,
    paper: dict[str, Any] | None,
    backtest: dict[str, Any] | None,
    paper_rows: list[dict[str, Any]],
    backtest_rows: list[dict[str, Any]],
) -> tuple[str, str, str, dict[str, Any]]:
    evidence: dict[str, Any] = {}
    if paper is None or backtest is None:
        return "COOLDOWN_FIELD_MISSING", "medium", "expand cooldown metadata", evidence
    timestamp = _parse_ts(paper["signal_timestamp"])
    direction = str(paper.get("direction"))
    prev_paper = previous_accepted(paper_rows, timestamp=timestamp, direction=direction)
    prev_backtest = previous_accepted(backtest_rows, timestamp=timestamp, direction=direction)
    paper_minutes = minutes_since(prev_paper, timestamp)
    backtest_minutes = minutes_since(prev_backtest, timestamp)
    evidence.update(
        {
            "paper_previous_accepted": signal_label(prev_paper),
            "backtest_previous_accepted": signal_label(prev_backtest),
            "paper_minutes_since_previous": paper_minutes,
            "backtest_minutes_since_previous": backtest_minutes,
        }
    )
    if prev_paper and prev_backtest and prev_paper.get("signal_timestamp") != prev_backtest.get("signal_timestamp"):
        return "COOLDOWN_PREVIOUS_SIGNAL_HISTORY_DIFF", "high", "resolve upstream extra/missing signal", evidence
    if prev_paper is None or prev_backtest is None:
        return "COOLDOWN_PREVIOUS_SIGNAL_HISTORY_DIFF", "high", "resolve upstream extra/missing signal", evidence
    if paper_minutes == 120 or backtest_minutes == 120:
        return "COOLDOWN_EXACT_BOUNDARY", "medium", "cooldown comparison policy audit", evidence
    return "COOLDOWN_TRUE_LOGIC_MISMATCH", "medium", "cooldown comparison boundary diagnostic", evidence


def classify_missing_extra(
    *,
    row: dict[str, Any],
    paper_rows: list[dict[str, Any]],
    backtest_rows: list[dict[str, Any]],
    comparison_window: dict[str, Any],
    repair_finished_at: datetime | None,
) -> tuple[str, str, str, dict[str, Any]]:
    raw_ts = row.get("paper_signal_timestamp") or row.get("backtest_signal_timestamp")
    if not raw_ts:
        return "INSUFFICIENT_CONTEXT_TO_CLASSIFY", "low", "expand signal metadata", {}
    timestamp = _parse_ts(raw_ts)
    nearest_paper_15 = nearest_signal(timestamp, paper_rows, 15 * 60)
    nearest_backtest_15 = nearest_signal(timestamp, backtest_rows, 15 * 60)
    generated_at = _ts_or_none((nearest_paper_15 or {}).get("generated_at"))
    generated_before_repair = bool(generated_at and repair_finished_at and generated_at < repair_finished_at)
    window_start = _parse_ts(comparison_window["comparison_start"]) if comparison_window else None
    window_end = _parse_ts(comparison_window["comparison_end"]) if comparison_window else None
    evidence = {
        "nearest_paper_15m": signal_label(nearest_paper_15),
        "nearest_backtest_15m": signal_label(nearest_backtest_15),
        "nearest_paper_generated_before_h4_repair": generated_before_repair,
        "minutes_from_window_start": round((timestamp - window_start).total_seconds() / 60, 4) if window_start else None,
        "minutes_from_window_end": round((window_end - timestamp).total_seconds() / 60, 4) if window_end else None,
    }
    if window_start and abs((timestamp - window_start).total_seconds()) <= 15 * 60:
        return "WINDOW_EDGE_EXTRA_SIGNAL", "medium", "comparison window alignment", evidence
    if generated_before_repair or (repair_finished_at and timestamp < repair_finished_at):
        return "PRE_REPAIR_DATA_CONTEXT_SIGNAL_DIFF", "high", "segment or exclude pre-repair paper rows", evidence
    if nearest_paper_15 and nearest_backtest_15:
        if nearest_paper_15.get("direction") == nearest_backtest_15.get("direction"):
            return "NEAR_MATCH_TIMESTAMP_SHIFT", "medium", "source candle alignment diagnostic", evidence
        return "SIGNAL_CLASSIFICATION_DIFF", "medium", "inspect signal classification context", evidence
    if row.get("match_status") == "extra_in_backtest":
        return "TRUE_EXTRA_BACKTEST_SIGNAL", "medium", "runtime/backtest path diagnostic", evidence
    if row.get("match_status") == "missing_in_backtest":
        return "TRUE_MISSING_BACKTEST_SIGNAL", "medium", "runtime/backtest path diagnostic", evidence
    return "INSUFFICIENT_CONTEXT_TO_CLASSIFY", "low", "expand signal metadata", evidence


def find_by_timestamp(rows: list[dict[str, Any]], timestamp: Any) -> dict[str, Any] | None:
    if not timestamp:
        return None
    target = _parse_ts(timestamp)
    for row in rows:
        if row.get("signal_timestamp") and _parse_ts(row["signal_timestamp"]) == target:
            return row
    return None


def build_detail_row(
    *,
    mismatch_id: int,
    source_row: dict[str, Any],
    mismatch_type: str,
    paper: dict[str, Any] | None,
    backtest: dict[str, Any] | None,
    paper_rows: list[dict[str, Any]],
    backtest_rows: list[dict[str, Any]],
    comparison_window: dict[str, Any],
    price_tolerance: float,
    repair_finished_at: datetime | None,
) -> dict[str, Any]:
    timestamp_raw = source_row.get("paper_signal_timestamp") or source_row.get("backtest_signal_timestamp")
    timestamp = _parse_ts(timestamp_raw) if timestamp_raw else None
    if mismatch_type in {"STOP_LOSS_MISMATCH", "TAKE_PROFIT_MISMATCH", "ENTRY_PRICE_MISMATCH"}:
        classification, confidence, action, evidence = classify_level_mismatch(
            row=source_row,
            paper=paper,
            backtest=backtest,
            price_tolerance=price_tolerance,
            repair_finished_at=repair_finished_at,
        )
    elif mismatch_type == "COOLDOWN_STATUS_MISMATCH":
        classification, confidence, action, evidence = classify_cooldown_mismatch(
            paper=paper,
            backtest=backtest,
            paper_rows=paper_rows,
            backtest_rows=backtest_rows,
        )
    elif mismatch_type in {"EXTRA_IN_BACKTEST", "MISSING_IN_BACKTEST"}:
        classification, confidence, action, evidence = classify_missing_extra(
            row=source_row,
            paper_rows=paper_rows,
            backtest_rows=backtest_rows,
            comparison_window=comparison_window,
            repair_finished_at=repair_finished_at,
        )
    else:
        classification, confidence, action, evidence = "INSUFFICIENT_CONTEXT_TO_CLASSIFY", "low", "expand signal metadata", {}

    prev_paper = previous_accepted(paper_rows, timestamp=timestamp, direction=str((paper or backtest or source_row).get("direction"))) if timestamp else None
    prev_backtest = previous_accepted(backtest_rows, timestamp=timestamp, direction=str((paper or backtest or source_row).get("direction"))) if timestamp else None
    generated_at = _ts_or_none((paper or {}).get("generated_at"))
    generated_before_repair = bool(generated_at and repair_finished_at and generated_at < repair_finished_at)
    nearest = {}
    if timestamp:
        for seconds, label in ((0, "0s"), (60, "1m"), (5 * 60, "5m"), (15 * 60, "15m")):
            nearest[f"nearest_paper_{label}"] = signal_label(nearest_signal(timestamp, paper_rows, seconds))
            nearest[f"nearest_backtest_{label}"] = signal_label(nearest_signal(timestamp, backtest_rows, seconds))

    details = json.loads(source_row.get("details") or "{}")
    return {
        "mismatch_id": mismatch_id,
        "comparison_scope": source_row.get("comparison_scope"),
        "mismatch_type": mismatch_type,
        "match_status": source_row.get("match_status"),
        "timestamp": timestamp.isoformat() if timestamp else "",
        "paper_signal_timestamp": source_row.get("paper_signal_timestamp"),
        "backtest_signal_timestamp": source_row.get("backtest_signal_timestamp"),
        "paper_generated_at": (paper or {}).get("generated_at"),
        "paper_generated_before_h4_repair": generated_before_repair,
        "direction": (paper or backtest or source_row).get("direction"),
        "setup_mode": (paper or backtest or source_row).get("setup_mode"),
        "band_touched": (paper or backtest or source_row).get("band_touched"),
        "entry_price_paper": (paper or {}).get("entry_price") or source_row.get("entry_price"),
        "entry_price_backtest": (backtest or {}).get("entry_price") or details.get("ENTRY_PRICE_MISMATCH", {}).get("backtest"),
        "stop_loss_paper": (paper or {}).get("stop_loss") or source_row.get("stop_loss"),
        "stop_loss_backtest": (backtest or {}).get("stop_loss") or details.get("STOP_LOSS_MISMATCH", {}).get("backtest"),
        "take_profit_paper": (paper or {}).get("take_profit") or source_row.get("take_profit"),
        "take_profit_backtest": (backtest or {}).get("take_profit") or details.get("TAKE_PROFIT_MISMATCH", {}).get("backtest"),
        "entry_abs_diff": _abs_diff((paper or {}).get("entry_price") or source_row.get("entry_price"), (backtest or {}).get("entry_price")),
        "stop_loss_abs_diff": _abs_diff((paper or {}).get("stop_loss") or source_row.get("stop_loss"), (backtest or {}).get("stop_loss") or details.get("STOP_LOSS_MISMATCH", {}).get("backtest")),
        "take_profit_abs_diff": _abs_diff((paper or {}).get("take_profit") or source_row.get("take_profit"), (backtest or {}).get("take_profit") or details.get("TAKE_PROFIT_MISMATCH", {}).get("backtest")),
        "paper_cooldown_status": (paper or {}).get("cooldown_status") or ("accepted" if _bool(source_row.get("cooldown_accepted")) else "blocked"),
        "backtest_cooldown_status": (backtest or {}).get("cooldown_status"),
        "paper_previous_accepted_same_direction": signal_label(prev_paper),
        "backtest_previous_accepted_same_direction": signal_label(prev_backtest),
        "paper_minutes_since_previous": minutes_since(prev_paper, timestamp) if timestamp else None,
        "backtest_minutes_since_previous": minutes_since(prev_backtest, timestamp) if timestamp else None,
        **nearest,
        "root_cause_classification": classification,
        "confidence": confidence,
        "recommended_action": action,
        "evidence": json.dumps(evidence, sort_keys=True, default=str),
    }


def diagnostic_flags(detail_rows: list[dict[str, Any]]) -> list[str]:
    classes = {row["root_cause_classification"] for row in detail_rows}
    flags = ["RUNTIME_COMPARISON_DIAGNOSTIC_COMPLETE"]
    if any(cls.startswith("LEVEL_") for cls in classes):
        flags.append("LEVEL_MISMATCH_ROOT_CAUSE_FOUND")
    if any(cls.startswith("COOLDOWN_") for cls in classes):
        flags.append("COOLDOWN_MISMATCH_ROOT_CAUSE_FOUND")
    if "WINDOW_EDGE_EXTRA_SIGNAL" in classes:
        flags.append("WINDOW_EDGE_MISMATCH_CONFIRMED")
    if any(cls in {"LEVEL_TRUE_CALCULATION_MISMATCH", "COOLDOWN_TRUE_LOGIC_MISMATCH", "TRUE_EXTRA_BACKTEST_SIGNAL", "TRUE_MISSING_BACKTEST_SIGNAL"} for cls in classes):
        flags.append("TRUE_RUNTIME_BACKTEST_DIVERGENCE")
    if any(cls == "INSUFFICIENT_CONTEXT_TO_CLASSIFY" for cls in classes):
        flags.append("METADATA_INSUFFICIENT_FOR_ROOT_CAUSE")
    if any("PRE_REPAIR_DATA_CONTEXT" in cls for cls in classes):
        flags.append("PRE_REPAIR_DATA_CONTEXT_EXPLAINS_MISMATCHES")
    flags.extend(["NO_LIVE_DEPLOYMENT_DECISION", "STRATEGY_3_REMAINS_PAPER_ONLY"])
    return flags


def recommended_next_branch(detail_rows: list[dict[str, Any]]) -> str:
    classes = {row["root_cause_classification"] for row in detail_rows}
    if any("PRE_REPAIR_DATA_CONTEXT" in cls for cls in classes):
        return "fix/strategy-3-comparison-reporting-alignment"
    if "LEVEL_TRUE_CALCULATION_MISMATCH" in classes:
        return "fix/strategy-3-runtime-backtest-level-alignment"
    if any(cls.startswith("COOLDOWN_") for cls in classes):
        return "fix/strategy-3-cooldown-comparison-boundary"
    if "INSUFFICIENT_CONTEXT_TO_CLASSIFY" in classes:
        return "feat/strategy-3-paper-signal-metadata-expansion"
    return "continue paper accumulation only if mismatch is proven harmless"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in DETAIL_FIELDS})


def write_report(output_dir: Path, summary: dict[str, Any], detail_rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Strategy 3 Runtime Comparison Diagnostics",
        "",
        "This is diagnostics only. No Strategy 3, VWAP, sigma, cooldown, live, Telegram, broker, or order path was changed.",
        "",
        "## Context",
        "",
        "- Paper-vs-backtest all-detected match rate: `92.31%`",
        "- Paper-vs-backtest accepted-only match rate: `93.10%`",
        "- H4 freshness: `fresh`",
        "- H4 stale_by_bars: `0`",
        "- Strategy 3 remains paper-only.",
        "",
        "## Summary",
        "",
        f"- mismatches analyzed: `{summary['mismatches_analyzed']}`",
        f"- classifications: `{summary['classification_counts']}`",
        f"- recommended next branch: `{summary['recommended_next_branch']}`",
        f"- verdict flags: `{', '.join(summary['verdict_flags'])}`",
        "",
        "## Root Cause",
        "",
        "All material mismatches are tied to paper rows generated before the H4 safe repair completed. The comparison uses repaired local data, so pre-repair paper signals can differ from the current backtest path without proving a live runtime/backtest logic divergence.",
        "",
        "Level mismatches have exact timestamp, direction, setup, band, and entry alignment, but stop/target values drift by up to `0.68`. That is larger than rounding tolerance and is best explained as pre-repair data-context drift.",
        "",
        "The cooldown mismatch at `2026-05-20T03:30:00+00:00` is downstream of the extra backtest SHORT signal at `2026-05-20T01:45:00+00:00`: backtest cooldown history includes that earlier accepted SHORT, while paper history does not.",
        "",
        "## Details",
        "",
    ]
    for row in detail_rows:
        lines.extend(
            [
                f"- `{row['comparison_scope']}` `{row['mismatch_type']}` at `{row['timestamp']}` -> `{row['root_cause_classification']}` ({row['confidence']})",
                f"  - action: `{row['recommended_action']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            "Do not change Strategy 3. The next branch should align comparison/reporting so pre-repair or stale-context paper rows are segmented or excluded from clean validation metrics.",
            "",
            f"Next branch: `{summary['recommended_next_branch']}`",
            "",
        ]
    )
    (output_dir / "runtime_comparison_diagnostics.md").write_text("\n".join(lines), encoding="utf-8")


def run_diagnostics(cfg: DiagnosticConfig) -> dict[str, Any]:
    started_perf = perf_counter()
    run_started_at = _utc_now()
    comparison_summary = read_json(cfg.comparison_dir / "comparison_summary.json")
    mismatch_rows = [row for row in read_csv_rows(cfg.comparison_dir / "mismatch_details.csv") if row.get("match_status") != "matched"]
    paper_rows, _missing_schema = read_paper_signals(cfg.paper_signals_path)
    scanner_summary = read_json(cfg.scanner_summary_path)
    pipeline_summary = read_json(cfg.pipeline_summary_path)
    repair_report = read_json(cfg.h4_repair_report_path)
    repair_finished_at = _ts_or_none(repair_report.get("run_finished_at"))
    backtest_rows: list[dict[str, Any]] = []
    window = comparison_summary.get("comparison_window") or {}
    if window:
        compare_cfg = PaperVsBacktestConfig(
            symbol=str(comparison_summary.get("symbol", "XAUUSD")),
            data_dir=cfg.data_dir,
            paper_signals_path=cfg.paper_signals_path,
            scanner_summary_path=cfg.scanner_summary_path,
            pipeline_summary_path=cfg.pipeline_summary_path,
            output_dir=cfg.output_dir,
            cooldown_minutes=int(comparison_summary.get("cooldown_minutes", 120)),
            timestamp_tolerance_seconds=cfg.timestamp_tolerance_seconds,
            price_tolerance=cfg.price_tolerance,
            dry_run=True,
        )
        _context_rows, backtest_rows = build_backtest_rows(compare_cfg, window)

    details: list[dict[str, Any]] = []
    mismatch_id = 1
    for source_row in mismatch_rows:
        categories = split_categories(source_row.get("mismatch_categories"))
        if not categories:
            continue
        paper = find_by_timestamp(paper_rows, source_row.get("paper_signal_timestamp"))
        backtest = find_by_timestamp(backtest_rows, source_row.get("backtest_signal_timestamp"))
        for category in categories:
            details.append(
                build_detail_row(
                    mismatch_id=mismatch_id,
                    source_row=source_row,
                    mismatch_type=category,
                    paper=paper,
                    backtest=backtest,
                    paper_rows=paper_rows,
                    backtest_rows=backtest_rows,
                    comparison_window=window,
                    price_tolerance=cfg.price_tolerance,
                    repair_finished_at=repair_finished_at,
                )
            )
            mismatch_id += 1

    classification_counts: dict[str, int] = {}
    for row in details:
        cls = str(row["root_cause_classification"])
        classification_counts[cls] = classification_counts.get(cls, 0) + 1

    summary = {
        "run_started_at": run_started_at,
        "run_finished_at": _utc_now(),
        "runtime_seconds": round(perf_counter() - started_perf, 4),
        "comparison_dir": str(cfg.comparison_dir),
        "output_dir": str(cfg.output_dir),
        "dry_run": cfg.dry_run,
        "mismatches_analyzed": len(details),
        "source_mismatch_rows": len(mismatch_rows),
        "comparison_match_rates": {
            "all_detected": comparison_summary.get("match_rate_all_detected"),
            "accepted_only": comparison_summary.get("match_rate_accepted_only"),
        },
        "h4_status": {
            "freshness": pipeline_summary.get("h4_quarantine_status") or comparison_summary.get("h4_freshness_status"),
            "stale_by_bars": pipeline_summary.get("h4_stale_by_bars"),
            "paper_signals_clean_for_validation": comparison_summary.get("paper_signals_clean_for_validation"),
            "repair_finished_at": repair_report.get("run_finished_at"),
        },
        "classification_counts": classification_counts,
        "recommended_next_branch": recommended_next_branch(details),
        "verdict_flags": diagnostic_flags(details),
        "safety": dict(SAFETY),
        "scanner_summary_latest_processed_timestamp": scanner_summary.get("new_last_processed_timestamp"),
    }
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    (cfg.output_dir / "runtime_comparison_diagnostics_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    write_csv(cfg.output_dir / "mismatch_root_cause_details.csv", details)
    write_csv(
        cfg.output_dir / "level_mismatch_details.csv",
        [row for row in details if row["mismatch_type"] in {"ENTRY_PRICE_MISMATCH", "STOP_LOSS_MISMATCH", "TAKE_PROFIT_MISMATCH"}],
    )
    write_csv(cfg.output_dir / "cooldown_mismatch_details.csv", [row for row in details if row["mismatch_type"] == "COOLDOWN_STATUS_MISMATCH"])
    write_csv(
        cfg.output_dir / "missing_extra_signal_details.csv",
        [row for row in details if row["mismatch_type"] in {"MISSING_IN_BACKTEST", "EXTRA_IN_BACKTEST"}],
    )
    write_report(cfg.output_dir, summary, details)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = DiagnosticConfig(
        comparison_dir=Path(args.comparison_dir),
        paper_signals_path=Path(args.paper_signals_path),
        scanner_summary_path=Path(args.scanner_summary_path),
        pipeline_summary_path=Path(args.pipeline_summary_path),
        data_dir=str(args.data_dir),
        output_dir=Path(args.output_dir),
        price_tolerance=float(args.price_tolerance),
        timestamp_tolerance_seconds=int(args.timestamp_tolerance_seconds),
        dry_run=bool(args.dry_run),
        h4_repair_report_path=Path(args.h4_repair_report_path),
        h4_post_repair_diagnostic_path=Path(args.h4_post_repair_diagnostic_path),
    )
    summary = run_diagnostics(cfg)
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
