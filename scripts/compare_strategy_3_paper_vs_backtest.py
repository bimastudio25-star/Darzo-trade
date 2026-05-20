from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.compare_strategy_3_shadow_vs_backtest import (  # noqa: E402
    CompareConfig as BacktestCompareConfig,
    _bool,
    _parse_ts,
    build_backtest_comparable_signals,
    compare_signals,
)
from scripts.strategy_3_data_context import compute_data_context, diff_contexts, write_context

STRATEGY_NAME = "strategy_3_vwap_1r"
DEFAULT_TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1"]
SAFETY = {
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "order_execution_enabled": False,
    "broker_called": False,
    "telegram_sent": False,
    "order_sent": False,
    "order_send_called": False,
}
REQUIRED_FIELDS = [
    "signal_timestamp",
    "symbol",
    "strategy",
    "direction",
    "entry_price",
    "stop_loss",
    "take_profit",
    "setup_mode",
    "band_touched",
    "cooldown_accepted",
    "order_sent",
    "telegram_sent",
    "broker_called",
]
MATCH_OUTPUT_FIELDS = [
    "comparison_scope",
    "match_status",
    "paper_signal_timestamp",
    "backtest_signal_timestamp",
    "direction",
    "entry_price",
    "stop_loss",
    "take_profit",
    "setup_mode",
    "band_touched",
    "cooldown_accepted",
    "mismatch_categories",
    "details",
]


@dataclass(frozen=True)
class PaperVsBacktestConfig:
    symbol: str
    data_dir: str
    paper_signals_path: Path
    scanner_summary_path: Path
    pipeline_summary_path: Path
    output_dir: Path
    cooldown_minutes: int
    timestamp_tolerance_seconds: int
    price_tolerance: float
    dry_run: bool
    allow_data_context_mismatch: bool = False
    h4_repair_report_path: Path = Path("backtests/reports/strategy_3_h4_safe_repair/h4_repair_report.json")
    h4_post_repair_diagnostic_path: Path = Path(
        "backtests/reports/strategy_3_h4_data_source_diagnostic_post_repair/h4_data_source_diagnostic.json"
    )
    signal_pre_buffer_minutes: int = 60
    post_signal_buffer_minutes: int = 5
    data_warmup_days: int = 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Strategy 3 paper signals against narrow backtest signals")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--paper-signals-path", default="backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv")
    parser.add_argument("--scanner-summary-path", default="backtests/reports/strategy_3_paper_shadow_scanner/scanner_summary.json")
    parser.add_argument("--pipeline-summary-path", default="backtests/reports/strategy_3_local_paper_pipeline/pipeline_summary.json")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_3_shadow_vs_backtest_comparison_post_fix")
    parser.add_argument("--cooldown-minutes", type=int, default=120)
    parser.add_argument("--timestamp-tolerance-seconds", type=int, default=0)
    parser.add_argument("--price-tolerance", type=float, default=0.01)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--allow-data-context-mismatch", action="store_true", default=False)
    parser.add_argument("--signal-pre-buffer-minutes", type=int, default=60)
    parser.add_argument("--post-signal-buffer-minutes", type=int, default=5)
    parser.add_argument("--data-warmup-days", type=int, default=1)
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


def read_paper_signals(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.exists():
        return [], list(REQUIRED_FIELDS)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    missing = [field for field in REQUIRED_FIELDS if field not in fieldnames]
    return rows, missing


def load_paper_data_context(scanner_summary_path: Path, paper_signals_path: Path) -> dict[str, Any] | None:
    scanner_summary = read_json(scanner_summary_path)
    context = scanner_summary.get("data_context")
    if isinstance(context, dict) and context.get("combined_data_context_hash"):
        return context
    sidecar = paper_signals_path.parent / "paper_signals_data_context.json"
    sidecar_context = read_json(sidecar)
    if sidecar_context.get("combined_data_context_hash"):
        return sidecar_context
    return None


def derive_comparison_window(rows: list[dict[str, Any]], cfg: PaperVsBacktestConfig) -> dict[str, str] | None:
    if not rows:
        return None
    timestamps = [_parse_ts(row["signal_timestamp"]) for row in rows]
    earliest = min(timestamps)
    latest = max(timestamps)
    signal_scan_start = earliest - timedelta(minutes=cfg.signal_pre_buffer_minutes)
    signal_scan_end = latest + timedelta(minutes=cfg.post_signal_buffer_minutes)
    data_warmup_start = earliest - timedelta(days=cfg.data_warmup_days)
    return {
        "earliest_paper_signal_timestamp": earliest.isoformat(),
        "latest_paper_signal_timestamp": latest.isoformat(),
        "comparison_start": earliest.isoformat(),
        "comparison_end": latest.isoformat(),
        "backtest_signal_scan_start": signal_scan_start.isoformat(),
        "backtest_signal_scan_end": signal_scan_end.isoformat(),
        "data_warmup_start": data_warmup_start.isoformat(),
        "window_source": "paper_signal_bounds_with_signal_prebuffer",
    }


def build_backtest_rows(cfg: PaperVsBacktestConfig, window: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    compare_cfg = BacktestCompareConfig(
        paper_dir=cfg.paper_signals_path.parent,
        data_dir=cfg.data_dir,
        output_dir=cfg.output_dir,
        symbol=cfg.symbol,
        strategy=STRATEGY_NAME,
        cooldown_minutes=cfg.cooldown_minutes,
        price_tolerance_usd=cfg.price_tolerance,
        timestamp_tolerance_seconds=cfg.timestamp_tolerance_seconds,
    )
    scan_window = {
        "backtest_from": window["backtest_signal_scan_start"],
        "backtest_to": window["backtest_signal_scan_end"],
        "earliest_paper_signal_timestamp": window["earliest_paper_signal_timestamp"],
        "latest_paper_signal_timestamp": window["latest_paper_signal_timestamp"],
    }
    context_rows = build_backtest_comparable_signals(compare_cfg, scan_window)
    start = _parse_ts(window["comparison_start"])
    end = _parse_ts(window["comparison_end"])
    comparable = [
        row
        for row in context_rows
        if start <= _parse_ts(row["signal_timestamp"]) <= end
    ]
    return context_rows, comparable


def field_match_rates(result: dict[str, Any]) -> dict[str, float | None]:
    paired_count = len(result.get("matched", [])) + len(result.get("mismatched", []))
    if paired_count == 0:
        return {
            "direction": None,
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
            "setup_mode": None,
            "band_touched": None,
            "cooldown_status": None,
        }
    categories = result.get("mismatch_categories", {})

    def rate(category: str) -> float:
        return round((paired_count - int(categories.get(category, 0))) / paired_count, 6)

    return {
        "direction": rate("DIRECTION_MISMATCH"),
        "entry_price": rate("ENTRY_PRICE_MISMATCH"),
        "stop_loss": rate("STOP_LOSS_MISMATCH"),
        "take_profit": rate("TAKE_PROFIT_MISMATCH"),
        "setup_mode": rate("SETUP_MODE_MISMATCH"),
        "band_touched": rate("BAND_TOUCHED_MISMATCH"),
        "cooldown_status": rate("COOLDOWN_STATUS_MISMATCH"),
    }


def price_diff_stats(result: dict[str, Any]) -> dict[str, float | None]:
    diffs: list[float] = []
    for row in result.get("mismatched", []):
        raw = row.get("details")
        if not raw:
            continue
        details = json.loads(raw) if isinstance(raw, str) else raw
        for category in ("ENTRY_PRICE_MISMATCH", "STOP_LOSS_MISMATCH", "TAKE_PROFIT_MISMATCH"):
            values = details.get(category)
            if not values:
                continue
            try:
                diffs.append(abs(float(values["paper"]) - float(values["backtest"])))
            except (TypeError, ValueError, KeyError):
                continue
    if not diffs:
        return {"max_abs_diff": 0.0, "mean_abs_diff": 0.0, "median_abs_diff": 0.0}
    return {
        "max_abs_diff": round(max(diffs), 6),
        "mean_abs_diff": round(statistics.fmean(diffs), 6),
        "median_abs_diff": round(statistics.median(diffs), 6),
    }


def _output_rows(result: dict[str, Any], scope: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in result.get("matched", []):
        rows.append({**row, "comparison_scope": scope, "match_status": "matched", "mismatch_categories": "", "details": ""})
    for row in result.get("mismatched", []):
        rows.append({**row, "comparison_scope": scope, "match_status": "field_mismatch"})
    for row in result.get("missing", []):
        rows.append(
            {
                "comparison_scope": scope,
                "match_status": "missing_in_backtest",
                "paper_signal_timestamp": row.get("signal_timestamp"),
                "backtest_signal_timestamp": "",
                "direction": row.get("direction"),
                "entry_price": row.get("entry_price"),
                "stop_loss": row.get("stop_loss"),
                "take_profit": row.get("take_profit"),
                "setup_mode": row.get("setup_mode"),
                "band_touched": row.get("band_touched"),
                "cooldown_accepted": row.get("cooldown_accepted"),
                "mismatch_categories": "MISSING_IN_BACKTEST",
                "details": "",
            }
        )
    for row in result.get("extra", []):
        rows.append(
            {
                "comparison_scope": scope,
                "match_status": "extra_in_backtest",
                "paper_signal_timestamp": "",
                "backtest_signal_timestamp": row.get("signal_timestamp"),
                "direction": row.get("direction"),
                "entry_price": row.get("entry_price"),
                "stop_loss": row.get("stop_loss"),
                "take_profit": row.get("take_profit"),
                "setup_mode": row.get("setup_mode"),
                "band_touched": row.get("band_touched"),
                "cooldown_accepted": row.get("cooldown_accepted"),
                "mismatch_categories": "EXTRA_IN_BACKTEST",
                "details": "",
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def h4_integrity(scanner_summary: dict[str, Any], pipeline_summary: dict[str, Any], repair_report: dict[str, Any], post_diag: dict[str, Any]) -> dict[str, Any]:
    overlap = post_diag.get("overlap", {}) if isinstance(post_diag.get("overlap"), dict) else {}
    local_h4 = post_diag.get("local_h4", {}) if isinstance(post_diag.get("local_h4"), dict) else {}
    mt5_h4 = post_diag.get("mt5_h4", {}) if isinstance(post_diag.get("mt5_h4"), dict) else {}
    h4_status = pipeline_summary.get("h4_quarantine_status") or repair_report.get("post_repair_freshness_status")
    stale_by_bars = pipeline_summary.get("h4_stale_by_bars")
    h4_clean = (
        h4_status == "fresh"
        and int(stale_by_bars or 0) == 0
        and bool(pipeline_summary.get("paper_signals_clean_for_validation", scanner_summary.get("paper_signals_clean_for_validation", False)))
    )
    return {
        "h4_freshness_status": h4_status,
        "h4_stale_by_bars": stale_by_bars,
        "h4_latest_existing_timestamp": pipeline_summary.get("h4_latest_existing_timestamp") or local_h4.get("latest_timestamp"),
        "h4_expected_latest_closed_timestamp": pipeline_summary.get("h4_expected_latest_closed_timestamp") or mt5_h4.get("latest_closed_timestamp"),
        "post_repair_ohlc_match_rate": overlap.get("match_rate_ohlc") or repair_report.get("post_repair_overlap_match_rate"),
        "post_repair_ohlcv_match_rate": overlap.get("match_rate_ohlcv"),
        "post_repair_mismatch_type": overlap.get("mismatch_type"),
        "backup_path": repair_report.get("backup_path"),
        "paper_signals_clean_for_validation": bool(
            pipeline_summary.get("paper_signals_clean_for_validation", scanner_summary.get("paper_signals_clean_for_validation", False))
        ),
        "h4_clean_for_comparison": h4_clean,
        "volume_mismatch_note": "OHLC is clean; remaining OHLCV mismatch is volume-only and non-blocking for Strategy 3 price-level comparison.",
    }


def verdict_flags(summary: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    accepted_rate = summary.get("match_rate_accepted_only")
    all_rate = summary.get("match_rate_all_detected")
    critical_categories = {
        "MISSING_IN_BACKTEST",
        "EXTRA_IN_BACKTEST",
        "ENTRY_PRICE_MISMATCH",
        "STOP_LOSS_MISMATCH",
        "TAKE_PROFIT_MISMATCH",
        "COOLDOWN_STATUS_MISMATCH",
    }
    accepted_categories = summary.get("accepted_only", {}).get("mismatch_categories", {})
    critical = any(int(accepted_categories.get(name, 0)) > 0 for name in critical_categories)
    h4_clean = summary.get("data_integrity", {}).get("h4_clean_for_comparison", False)
    paper_clean = summary.get("paper_signals_clean_for_validation", False)
    data_context = summary.get("data_context", {})
    data_context_match = bool(data_context.get("data_context_match"))
    data_context_missing = bool(data_context.get("data_context_missing"))

    if not h4_clean:
        flags.append("HTF_CONTEXT_CAVEAT_REQUIRES_DATA_DIAGNOSTIC")
    flags.extend(data_context.get("data_context_verdict_flags", []))
    if data_context_missing or not data_context_match:
        flags.append("COMPARISON_NOT_CLEAN_VALIDATION")
    if paper_clean and data_context_match:
        flags.append("PAPER_SIGNALS_CLEAN_FOR_VALIDATION")
    else:
        flags.append("PAPER_SIGNALS_NOT_CLEAN_FOR_VALIDATION")

    if accepted_rate is not None and accepted_rate >= 0.95 and not critical and h4_clean and paper_clean and data_context_match:
        flags.append("SHADOW_BACKTEST_ACCEPTED_MATCH_OK")
    elif accepted_rate is not None and accepted_rate >= 0.80:
        flags.append("SHADOW_BACKTEST_MINOR_MISMATCHES")
    else:
        flags.append("SHADOW_BACKTEST_RUNTIME_MISMATCH")

    if all_rate is not None and all_rate >= 0.95:
        flags.append("SHADOW_BACKTEST_ALL_DETECTED_MATCH_OK")
    elif all_rate is not None and all_rate >= 0.80 and "SHADOW_BACKTEST_MINOR_MISMATCHES" not in flags:
        flags.append("SHADOW_BACKTEST_MINOR_MISMATCHES")

    flags.extend(["NO_LIVE_DEPLOYMENT_DECISION", "STRATEGY_3_REMAINS_PAPER_ONLY"])
    return list(dict.fromkeys(flags))


def write_report(output_dir: Path, summary: dict[str, Any]) -> None:
    flags = ", ".join(summary["verdict_flags"])
    mismatch = summary["mismatch_summary"]
    lines = [
        "# Strategy 3 Shadow vs Backtest Comparison - Post H4 Repair",
        "",
        "This is runtime/backtest consistency validation only. It is not profitability validation and it does not approve live trading.",
        "",
        "## Safety",
        "",
        "- no live trading",
        "- no Telegram",
        "- no orders",
        "- no broker execution",
        "- no Strategy 3, VWAP, sigma, or cooldown changes",
        "",
        "## Inputs",
        "",
        f"- paper_signals.csv: `{summary['inputs']['paper_signals_path']}`",
        f"- scanner_summary.json: `{summary['inputs']['scanner_summary_path']}`",
        f"- pipeline_summary.json: `{summary['inputs']['pipeline_summary_path']}`",
        f"- data_dir: `{summary['data_dir']}`",
        "",
        "## Window",
        "",
        f"- earliest_paper_signal_timestamp: `{summary['comparison_window']['earliest_paper_signal_timestamp']}`",
        f"- latest_paper_signal_timestamp: `{summary['comparison_window']['latest_paper_signal_timestamp']}`",
        f"- backtest_signal_scan_start: `{summary['comparison_window']['backtest_signal_scan_start']}`",
        f"- backtest_signal_scan_end: `{summary['comparison_window']['backtest_signal_scan_end']}`",
        f"- data_warmup_start: `{summary['comparison_window']['data_warmup_start']}`",
        "",
        "## Data Integrity",
        "",
        f"- H4 freshness: `{summary['data_integrity']['h4_freshness_status']}`",
        f"- H4 stale_by_bars: `{summary['data_integrity']['h4_stale_by_bars']}`",
        f"- post-repair OHLC match rate: `{summary['data_integrity']['post_repair_ohlc_match_rate']}`",
        f"- post-repair OHLCV match rate: `{summary['data_integrity']['post_repair_ohlcv_match_rate']}`",
        f"- H4 backup path: `{summary['data_integrity']['backup_path']}`",
        f"- paper_signals_clean_for_validation: `{summary['paper_signals_clean_for_validation']}`",
        "",
        "## Data Context Integrity",
        "",
        f"- paper_data_context_hash: `{summary['data_context']['paper_data_context_hash']}`",
        f"- backtest_data_context_hash: `{summary['data_context']['backtest_data_context_hash']}`",
        f"- data_context_match: `{summary['data_context']['data_context_match']}`",
        f"- data_context_missing: `{summary['data_context']['data_context_missing']}`",
        f"- mismatched_timeframes: `{summary['data_context']['mismatched_timeframes']}`",
        f"- data_context_verdict_flags: `{summary['data_context']['data_context_verdict_flags']}`",
        "",
        "## Results",
        "",
        f"- paper_detected_count: `{summary['paper_detected_count']}`",
        f"- paper_accepted_count: `{summary['paper_accepted_count']}`",
        f"- paper_blocked_count: `{summary['paper_blocked_count']}`",
        f"- backtest_detected_count: `{summary['backtest_detected_count']}`",
        f"- backtest_accepted_count: `{summary['backtest_accepted_count']}`",
        f"- backtest_blocked_count: `{summary['backtest_blocked_count']}`",
        f"- match_rate_all_detected: `{summary['match_rate_all_detected']}`",
        f"- match_rate_accepted_only: `{summary['match_rate_accepted_only']}`",
        f"- verdict_flags: `{flags}`",
        "",
        "## Mismatch Summary",
        "",
        f"- all_detected: `{mismatch['all_detected']}`",
        f"- accepted_only: `{mismatch['accepted_only']}`",
        f"- price_diff_stats_all_detected: `{summary['price_diff_stats_all_detected']}`",
        f"- price_diff_stats_accepted_only: `{summary['price_diff_stats_accepted_only']}`",
        "",
        "## Interpretation",
        "",
        "The comparison checks whether the paper scanner path and the backtest evaluation path agree on the same repaired local data. Match success is operational consistency evidence only; it is not edge validation, profitability evidence, or a live deployment decision.",
        "",
        "## Next Step",
        "",
        "Because the accepted-only match rate is below 95%, diagnose the runtime/backtest mismatches before moving to spread/slippage modeling.",
        "",
    ]
    (output_dir / "strategy_3_shadow_vs_backtest_comparison_post_fix.md").write_text("\n".join(lines), encoding="utf-8")


def write_outputs(output_dir: Path, summary: dict[str, Any], all_detected: dict[str, Any], accepted_only: dict[str, Any], missing_fields: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for legacy_name in (
        "comparison_matches.csv",
        "comparison_mismatches.csv",
        "comparison_report.md",
        "matched_signals.csv",
        "mismatched_signals.csv",
        "missing_in_backtest.csv",
        "extra_in_backtest.csv",
    ):
        legacy_path = output_dir / legacy_name
        if legacy_path.exists():
            legacy_path.unlink()
    (output_dir / "comparison_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    (output_dir / "missing_fields_summary.json").write_text(json.dumps(missing_fields, indent=2, sort_keys=True), encoding="utf-8")
    if isinstance(summary.get("paper_data_context"), dict) and summary["paper_data_context"]:
        write_context(output_dir / "data_context_paper.json", summary["paper_data_context"])
    write_context(output_dir / "data_context_backtest.json", summary["backtest_data_context"])
    (output_dir / "data_context_diff.json").write_text(json.dumps(summary["data_context"], indent=2, sort_keys=True), encoding="utf-8")
    all_rows = _output_rows(all_detected, "all_detected")
    accepted_rows = _output_rows(accepted_only, "accepted_only")
    write_csv(output_dir / "comparison_all_detected.csv", all_rows, MATCH_OUTPUT_FIELDS)
    write_csv(output_dir / "comparison_accepted_only.csv", accepted_rows, MATCH_OUTPUT_FIELDS)
    write_csv(output_dir / "mismatch_details.csv", all_rows + accepted_rows, MATCH_OUTPUT_FIELDS)
    write_report(output_dir, summary)


def run_comparison(cfg: PaperVsBacktestConfig) -> dict[str, Any]:
    started_perf = perf_counter()
    run_started_at = _utc_now()
    paper_rows, missing_schema = read_paper_signals(cfg.paper_signals_path)
    scanner_summary = read_json(cfg.scanner_summary_path)
    pipeline_summary = read_json(cfg.pipeline_summary_path)
    repair_report = read_json(cfg.h4_repair_report_path)
    post_diag = read_json(cfg.h4_post_repair_diagnostic_path)
    paper_data_context = load_paper_data_context(cfg.scanner_summary_path, cfg.paper_signals_path)
    backtest_data_context = compute_data_context(symbol=cfg.symbol, data_dir=cfg.data_dir, timeframes=DEFAULT_TIMEFRAMES)
    data_context_diff = diff_contexts(paper_data_context, backtest_data_context)
    if cfg.allow_data_context_mismatch and not data_context_diff["data_context_match"]:
        data_context_diff["verdict_flags"] = list(
            dict.fromkeys([*data_context_diff["verdict_flags"], "DATA_CONTEXT_MISMATCH_ALLOWED_DIAGNOSTIC"])
        )
    window = derive_comparison_window(paper_rows, cfg)
    backtest_context_rows: list[dict[str, Any]] = []
    backtest_rows: list[dict[str, Any]] = []
    if window and not missing_schema:
        backtest_context_rows, backtest_rows = build_backtest_rows(cfg, window)

    all_detected = compare_signals(
        paper_rows,
        backtest_rows,
        price_tolerance_usd=cfg.price_tolerance,
        timestamp_tolerance_seconds=cfg.timestamp_tolerance_seconds,
    )
    accepted_paper = [row for row in paper_rows if _bool(row.get("cooldown_accepted"))]
    accepted_backtest = [row for row in backtest_rows if _bool(row.get("cooldown_accepted"))]
    accepted_only = compare_signals(
        accepted_paper,
        accepted_backtest,
        price_tolerance_usd=cfg.price_tolerance,
        timestamp_tolerance_seconds=cfg.timestamp_tolerance_seconds,
    )
    data_integrity = h4_integrity(scanner_summary, pipeline_summary, repair_report, post_diag)
    missing_fields = {
        "missing_schema_fields": missing_schema,
        "paper_signals_path": str(cfg.paper_signals_path),
        "missing_optional_context_files": [
            str(path)
            for path in (cfg.scanner_summary_path, cfg.pipeline_summary_path, cfg.h4_repair_report_path, cfg.h4_post_repair_diagnostic_path)
            if not path.exists()
        ],
    }
    summary: dict[str, Any] = {
        "run_started_at": run_started_at,
        "run_finished_at": _utc_now(),
        "runtime_seconds": round(perf_counter() - started_perf, 4),
        "dry_run": cfg.dry_run,
        "allow_data_context_mismatch": cfg.allow_data_context_mismatch,
        "symbol": cfg.symbol,
        "strategy": STRATEGY_NAME,
        "data_dir": cfg.data_dir,
        "cooldown_minutes": cfg.cooldown_minutes,
        "timestamp_tolerance_seconds": cfg.timestamp_tolerance_seconds,
        "price_tolerance": cfg.price_tolerance,
        "inputs": {
            "paper_signals_path": str(cfg.paper_signals_path),
            "scanner_summary_path": str(cfg.scanner_summary_path),
            "pipeline_summary_path": str(cfg.pipeline_summary_path),
            "h4_repair_report_path": str(cfg.h4_repair_report_path),
            "h4_post_repair_diagnostic_path": str(cfg.h4_post_repair_diagnostic_path),
        },
        "comparison_window": window,
        "backtest_context_detected_count": len(backtest_context_rows),
        "paper_signals_count": len(paper_rows),
        "paper_detected_count": len(paper_rows),
        "paper_accepted_count": len(accepted_paper),
        "paper_blocked_count": len(paper_rows) - len(accepted_paper),
        "backtest_detected_count": len(backtest_rows),
        "backtest_accepted_count": len(accepted_backtest),
        "backtest_blocked_count": len(backtest_rows) - len(accepted_backtest),
        "match_rate_all_detected": all_detected["match_rate"],
        "match_rate_accepted_only": accepted_only["match_rate"],
        "all_detected": {
            "matched_count": len(all_detected["matched"]),
            "mismatched_count": len(all_detected["mismatched"]),
            "unmatched_paper_count": len(all_detected["missing"]),
            "unmatched_backtest_count": len(all_detected["extra"]),
            "match_rate": all_detected["match_rate"],
            "field_match_rates": field_match_rates(all_detected),
            "mismatch_categories": all_detected["mismatch_categories"],
        },
        "accepted_only": {
            "matched_count": len(accepted_only["matched"]),
            "mismatched_count": len(accepted_only["mismatched"]),
            "unmatched_paper_count": len(accepted_only["missing"]),
            "unmatched_backtest_count": len(accepted_only["extra"]),
            "match_rate": accepted_only["match_rate"],
            "field_match_rates": field_match_rates(accepted_only),
            "mismatch_categories": accepted_only["mismatch_categories"],
        },
        "mismatch_summary": {
            "all_detected": all_detected["mismatch_categories"],
            "accepted_only": accepted_only["mismatch_categories"],
        },
        "price_diff_stats_all_detected": price_diff_stats(all_detected),
        "price_diff_stats_accepted_only": price_diff_stats(accepted_only),
        "data_integrity": data_integrity,
        "paper_data_context": paper_data_context or {},
        "backtest_data_context": backtest_data_context,
        "data_context": {
            **data_context_diff,
            "data_context_verdict_flags": data_context_diff.get("verdict_flags", []),
        },
        "paper_data_context_hash": data_context_diff.get("paper_data_context_hash"),
        "backtest_data_context_hash": data_context_diff.get("backtest_data_context_hash"),
        "data_context_match": data_context_diff.get("data_context_match"),
        "data_context_missing": data_context_diff.get("data_context_missing"),
        "mismatched_timeframes": data_context_diff.get("mismatched_timeframes", []),
        "data_context_verdict_flags": data_context_diff.get("verdict_flags", []),
        "h4_freshness_status": data_integrity["h4_freshness_status"],
        "paper_signals_clean_for_validation": data_integrity["paper_signals_clean_for_validation"],
        "pipeline_verdict_flags": pipeline_summary.get("verdict_flags", []),
        "scanner_summary_latest_processed_timestamp": scanner_summary.get("new_last_processed_timestamp"),
        "scanner_summary_signals_detected_last_run": scanner_summary.get("signals_detected"),
        "missing_fields": missing_fields,
        "safety": dict(SAFETY),
    }
    summary["verdict_flags"] = verdict_flags(summary)
    write_outputs(cfg.output_dir, summary, all_detected, accepted_only, missing_fields)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = PaperVsBacktestConfig(
        symbol=str(args.symbol),
        data_dir=str(args.data_dir),
        paper_signals_path=Path(args.paper_signals_path),
        scanner_summary_path=Path(args.scanner_summary_path),
        pipeline_summary_path=Path(args.pipeline_summary_path),
        output_dir=Path(args.output_dir),
        cooldown_minutes=int(args.cooldown_minutes),
        timestamp_tolerance_seconds=int(args.timestamp_tolerance_seconds),
        price_tolerance=float(args.price_tolerance),
        dry_run=bool(args.dry_run),
        allow_data_context_mismatch=bool(args.allow_data_context_mismatch),
        h4_repair_report_path=Path(args.h4_repair_report_path),
        h4_post_repair_diagnostic_path=Path(args.h4_post_repair_diagnostic_path),
        signal_pre_buffer_minutes=int(args.signal_pre_buffer_minutes),
        post_signal_buffer_minutes=int(args.post_signal_buffer_minutes),
        data_warmup_days=int(args.data_warmup_days),
    )
    summary = run_comparison(cfg)
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
