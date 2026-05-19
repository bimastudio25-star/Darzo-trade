from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_xauusd_data import build_audit, write_audit_report
from scripts.fetch_xauusd_mt5_candles import CollectorConfig, run_collector
from scripts.import_xauusd_candles import build_ingestion, write_ingestion_report
from scripts.run_strategy_3_paper_shadow_scanner import ShadowScannerConfig, run_scanner

SAFETY = {
    "live_trading_enabled": False,
    "order_execution_enabled": False,
    "telegram_enabled": False,
    "broker_order_functions_called": False,
    "order_send_called": False,
}


@dataclass(frozen=True)
class PipelineConfig:
    symbol: str
    symbol_broker: str
    timeframes: list[str]
    days_back: int
    interval_minutes: int
    loop: bool
    once: bool
    apply: bool
    allow_large_fetch: bool
    allow_overlap_mismatch: bool
    run_scanner: bool
    from_timestamp: str | None
    max_loops: int | None
    data_dir: Path = Path("data")
    incoming_dir: Path = Path("incoming_data/XAUUSD")
    reports_dir: Path = Path("backtests/reports/strategy_3_local_paper_pipeline")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Strategy 3 local MT5 paper accumulation pipeline")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--symbol-broker", default=None)
    parser.add_argument("--timeframes", default="M1,M5,M15,H1,H4,D1")
    parser.add_argument("--days-back", type=int, default=7)
    parser.add_argument("--interval-minutes", type=int, default=15)
    parser.add_argument("--loop", action="store_true", default=False)
    parser.add_argument("--once", action="store_true", default=False)
    parser.add_argument("--no-apply", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--allow-large-fetch", action="store_true", default=False)
    parser.add_argument("--allow-overlap-mismatch", action="store_true", default=False)
    parser.add_argument("--run-scanner", action="store_true", default=True)
    parser.add_argument("--skip-scanner", action="store_true", default=False)
    parser.add_argument("--from-timestamp", default=None)
    parser.add_argument("--max-loops", type=int, default=None)
    return parser.parse_args(argv)


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _write_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True, default=str) + "\n")


def _has_blocker(flags: list[str]) -> bool:
    effective_flags = set(flags)
    if "HTF_OVERLAP_MISMATCH_QUARANTINED" in effective_flags:
        effective_flags.discard("OVERLAP_MATCH_LT_95")
    blockers = {
        "MT5_TIMEZONE_MISMATCH_DETECTED",
        "OVERLAP_MATCH_LT_95",
        "MT5_FETCH_RANGE_TOO_LARGE",
        "MT5_FETCH_RANGE_REQUIRES_CONFIRMATION",
        "MT5_PACKAGE_MISSING",
        "MT5_INITIALIZE_FAILED",
        "MT5_SYMBOL_SELECT_FAILED",
        "FINAL_VALIDATION_FAILED",
        "INCOMING_SCHEMA_INVALID",
        "DATA_AUDIT_FAILED",
        "DUPLICATE_TIMESTAMPS_DETECTED",
        "NON_MONOTONIC_TIMESTAMPS_DETECTED",
        "INVALID_OHLC_DETECTED",
        "MISSING_OHLC_VALUES_DETECTED",
    }
    return bool(blockers & effective_flags)


def _audit_structurally_clean(audit: dict[str, Any]) -> bool:
    flags = set(audit.get("verdict_flags", []))
    return not bool(flags & {"DATA_AUDIT_FAILED", "DUPLICATE_TIMESTAMPS_DETECTED", "NON_MONOTONIC_TIMESTAMPS_DETECTED", "INVALID_OHLC_DETECTED", "MISSING_OHLC_VALUES_DETECTED"})


def run_pipeline_once(cfg: PipelineConfig) -> dict[str, Any]:
    started = perf_counter()
    run_started_at = datetime.now(timezone.utc).isoformat()
    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    events_path = cfg.reports_dir / "pipeline_events.jsonl"
    flags: list[str] = []
    fetch = run_collector(
        CollectorConfig(
            symbol=cfg.symbol,
            symbol_broker=cfg.symbol_broker,
            timeframes=cfg.timeframes,
            output_dir=cfg.incoming_dir,
            data_dir=cfg.data_dir,
            days_back=cfg.days_back,
            date_from=None,
            date_to=datetime.now(timezone.utc),
            dry_run=False,
            write=True,
            overwrite=True,
            allow_large_fetch=cfg.allow_large_fetch,
            allow_timezone_warning=False,
            allow_overlap_mismatch=cfg.allow_overlap_mismatch,
            include_forming_candles=False,
            closed_candle_grace_seconds=5,
            overlap_price_tolerance_usd=0.10,
            report_dir=Path("backtests/reports/strategy_3_mt5_data_collector"),
        )
    )
    _write_event(events_path, {"step": "fetch", "verdict_flags": fetch.get("verdict_flags", [])})
    fetch_flags = list(fetch.get("verdict_flags", []))
    fetch_ok = not _has_blocker(fetch_flags) and "MT5_INCOMING_CSVS_WRITTEN" in fetch_flags

    dry_summary: dict[str, Any] | None = None
    apply_summary: dict[str, Any] | None = None
    audit: dict[str, Any] | None = None
    scanner: dict[str, Any] | None = None

    if fetch_ok:
        dry_summary = build_ingestion(
            source_dir=cfg.incoming_dir,
            data_dir=cfg.data_dir,
            symbol=cfg.symbol,
            timeframes=cfg.timeframes,
            dry_run=True,
            apply=False,
            backup=True,
            no_backup=False,
            prefer_incoming=False,
            strict=False,
            run_paper_scanner_after_ingest=False,
        )
        write_ingestion_report(dry_summary, Path("backtests/reports/strategy_3_data_ingestion"))
        _write_event(events_path, {"step": "import_dry_run", "verdict_flags": dry_summary.get("verdict_flags", [])})
        dry_flags = list(dry_summary.get("verdict_flags", []))
        dry_ok = not _has_blocker(dry_flags)
        new_rows = int(dry_summary.get("total_new_rows_added", 0))
        if cfg.apply and dry_ok and new_rows > 0:
            apply_summary = build_ingestion(
                source_dir=cfg.incoming_dir,
                data_dir=cfg.data_dir,
                symbol=cfg.symbol,
                timeframes=cfg.timeframes,
                dry_run=False,
                apply=True,
                backup=True,
                no_backup=False,
                prefer_incoming=False,
                strict=False,
                run_paper_scanner_after_ingest=False,
            )
            write_ingestion_report(apply_summary, Path("backtests/reports/strategy_3_data_ingestion"))
            _write_event(events_path, {"step": "import_apply", "verdict_flags": apply_summary.get("verdict_flags", [])})
        elif new_rows == 0:
            flags.append("LOCAL_PIPELINE_NO_NEW_ROWS")
        elif not cfg.apply:
            flags.append("LOCAL_PIPELINE_NO_APPLY_DRY_RUN_ONLY")

    audit = build_audit(cfg.data_dir, cfg.symbol, cfg.timeframes)
    write_audit_report(audit, Path("backtests/reports/strategy_3_data_ingestion"))
    _write_event(events_path, {"step": "audit", "verdict_flags": audit.get("verdict_flags", [])})

    audit_ok = _audit_structurally_clean(audit)
    data_ready_for_scanner = audit_ok and (apply_summary is not None or (dry_summary is not None and int(dry_summary.get("total_new_rows_added", 0)) == 0))
    if cfg.run_scanner and data_ready_for_scanner:
        scanner = run_scanner(
            ShadowScannerConfig(
                symbol=cfg.symbol,
                timeframes=cfg.timeframes,
                data_dir=str(cfg.data_dir),
                output_dir=Path("backtests/reports/strategy_3_paper_shadow_scanner"),
                cooldown_minutes=120,
                dry_run=True,
                incremental=True,
                from_timestamp=cfg.from_timestamp,
                append=True,
            )
        )
        _write_event(events_path, {"step": "scanner", "signals_detected": scanner.get("signals_detected", 0)})

    if _has_blocker(fetch_flags):
        flags.append("LOCAL_PIPELINE_FETCH_FAILED")
    if dry_summary and _has_blocker(list(dry_summary.get("verdict_flags", []))):
        flags.append("LOCAL_PIPELINE_IMPORT_DRY_RUN_FAILED")
    if apply_summary and _has_blocker(list(apply_summary.get("verdict_flags", []))):
        flags.append("LOCAL_PIPELINE_IMPORT_APPLY_FAILED")
    if not audit_ok:
        flags.append("LOCAL_PIPELINE_AUDIT_FAILED")
    if cfg.run_scanner and data_ready_for_scanner and scanner is None:
        flags.append("LOCAL_PIPELINE_SCANNER_FAILED")
    if not flags:
        flags.append("LOCAL_PIPELINE_OK")
    elif all(flag in {"LOCAL_PIPELINE_NO_NEW_ROWS", "LOCAL_PIPELINE_NO_APPLY_DRY_RUN_ONLY"} for flag in flags):
        flags.insert(0, "LOCAL_PIPELINE_WARNINGS")
    elif not any(flag.endswith("FAILED") or flag == "LOCAL_PIPELINE_BLOCKED" for flag in flags):
        flags.insert(0, "LOCAL_PIPELINE_WARNINGS")
    else:
        flags.insert(0, "LOCAL_PIPELINE_BLOCKED")

    rows_added: dict[str, int] = {}
    source = apply_summary or dry_summary or {}
    for item in source.get("timeframes", []) if isinstance(source, dict) else []:
        rows_added[item["timeframe"]] = int(item.get("new_rows_added", 0))
    latest_by_tf = {
        item["timeframe"]: item.get("last_timestamp")
        for item in audit.get("timeframes", [])
    }
    summary = {
        "run_started_at": run_started_at,
        "run_finished_at": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": round(perf_counter() - started, 4),
        "loop_mode": cfg.loop,
        "interval_minutes": cfg.interval_minutes,
        "loops_completed": 1,
        "symbol": cfg.symbol,
        "symbol_broker": cfg.symbol_broker,
        "apply_enabled": cfg.apply,
        "fetch_status": fetch_flags,
        "fetch_blocking_error": bool(fetch.get("blocking_fetch_error")),
        "forming_candles_skipped_by_timeframe": fetch.get("forming_candles_skipped_by_timeframe"),
        "import_dry_run_status": dry_summary.get("verdict_flags") if dry_summary else None,
        "import_apply_status": apply_summary.get("verdict_flags") if apply_summary else None,
        "audit_status": audit.get("verdict_flags"),
        "scanner_status": scanner.get("no_signal_reason") if scanner else None,
        "rows_added_by_timeframe": rows_added,
        "latest_timestamp_by_timeframe": latest_by_tf,
        "paper_signals_total_after_run": scanner.get("paper_signals_total_after_run") if scanner else None,
        "new_paper_signals_this_run": scanner.get("new_paper_signals_this_run") if scanner else 0,
        "verdict_flags": list(dict.fromkeys(flags)),
        "safety": dict(SAFETY),
    }
    (cfg.reports_dir / "pipeline_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    (cfg.reports_dir / "pipeline_run.md").write_text(_pipeline_markdown(summary), encoding="utf-8")
    return summary


def _pipeline_markdown(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Strategy 3 Local Paper Pipeline",
            "",
            "This is data/paper infrastructure only. No live trading, Telegram trade signals, broker execution, or orders were enabled.",
            "",
            f"- symbol: `{summary['symbol']}`",
            f"- broker symbol: `{summary['symbol_broker']}`",
            f"- apply_enabled: `{summary['apply_enabled']}`",
            f"- verdict_flags: `{', '.join(summary['verdict_flags'])}`",
            f"- new_paper_signals_this_run: `{summary['new_paper_signals_this_run']}`",
            f"- paper_signals_total_after_run: `{summary['paper_signals_total_after_run']}`",
            "",
        ]
    )


def run_pipeline(cfg: PipelineConfig) -> dict[str, Any]:
    loops = 0
    last_summary: dict[str, Any] = {}
    try:
        while True:
            loops += 1
            last_summary = run_pipeline_once(cfg)
            last_summary["loops_completed"] = loops
            if cfg.once or not cfg.loop:
                break
            if cfg.max_loops is not None and loops >= cfg.max_loops:
                break
            time.sleep(max(1, int(cfg.interval_minutes)) * 60)
    except KeyboardInterrupt:
        last_summary = last_summary or {"verdict_flags": []}
        last_summary["verdict_flags"] = list(dict.fromkeys(list(last_summary.get("verdict_flags", [])) + ["LOCAL_PIPELINE_STOPPED_BY_USER"]))
    return last_summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = PipelineConfig(
        symbol=args.symbol,
        symbol_broker=args.symbol_broker or args.symbol,
        timeframes=_split(args.timeframes),
        days_back=int(args.days_back),
        interval_minutes=int(args.interval_minutes),
        loop=bool(args.loop),
        once=bool(args.once or not args.loop),
        apply=bool(args.apply),
        allow_large_fetch=bool(args.allow_large_fetch),
        allow_overlap_mismatch=bool(args.allow_overlap_mismatch),
        run_scanner=not bool(args.skip_scanner) and bool(args.run_scanner),
        from_timestamp=args.from_timestamp,
        max_loops=args.max_loops,
    )
    summary = run_pipeline(cfg)
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
