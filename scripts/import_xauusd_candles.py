from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_xauusd_data import (
    CANONICAL_SCHEMA,
    SUPPORTED_TIMEFRAMES,
    build_audit,
    read_candle_csv,
    validate_frame,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely import/merge XAUUSD candle CSV updates")
    parser.add_argument("--source-dir", default="incoming_data/XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframes", default=",".join(SUPPORTED_TIMEFRAMES))
    parser.add_argument("--output-dir", default="backtests/reports/strategy_3_data_ingestion")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--backup", action="store_true", default=False)
    parser.add_argument("--no-backup", action="store_true", default=False)
    parser.add_argument("--prefer-incoming", action="store_true", default=False)
    parser.add_argument("--strict", action="store_true", default=False)
    parser.add_argument("--run-paper-scanner-after-ingest", action="store_true", default=False)
    return parser.parse_args(argv)


def _split_timeframes(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _find_incoming_file(source_dir: Path, symbol: str, timeframe: str) -> Path | None:
    for name in (f"{timeframe}.csv", f"{symbol}_{timeframe}.csv", f"{symbol.lower()}_{timeframe.lower()}.csv"):
        path = source_dir / name
        if path.exists():
            return path
    return None


def _ensure_schema(df: pd.DataFrame, schema: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in schema:
        if col not in out.columns:
            out[col] = pd.NA
    return out[schema]


def _format_time(value: Any, has_time: bool) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.strftime("%Y.%m.%d %H:%M" if has_time else "%Y.%m.%d")


def write_project_csv(df: pd.DataFrame, path: Path, schema: list[str], *, timestamp_has_time: bool) -> None:
    out = _ensure_schema(df, schema).copy()
    out["time"] = out["time"].map(lambda value: _format_time(value, timestamp_has_time))
    tmp = path.with_suffix(path.suffix + ".tmp")
    out.to_csv(tmp, index=False, header=False, encoding="utf-16", lineterminator="\n")
    tmp.replace(path)


def merge_frames(existing: pd.DataFrame, incoming: pd.DataFrame, *, prefer_incoming: bool) -> tuple[pd.DataFrame, dict[str, int]]:
    existing = existing.copy()
    incoming = incoming.copy()
    existing["__source_order"] = range(len(existing))
    incoming["__source_order"] = range(len(incoming))
    existing["__source"] = "existing"
    incoming["__source"] = "incoming"
    combined = pd.concat([existing, incoming], ignore_index=True, sort=False)
    before = len(combined)
    if prefer_incoming:
        combined = combined.sort_values(["time", "__source"], ascending=[True, True])
        deduped = combined.drop_duplicates(subset=["time"], keep="last")
    else:
        combined = combined.sort_values(["time", "__source"], ascending=[True, True])
        deduped = combined.drop_duplicates(subset=["time"], keep="first")
    duplicate_rows_skipped = before - len(deduped)
    existing_times = set(pd.to_datetime(existing["time"], utc=True).dropna())
    incoming_times = set(pd.to_datetime(incoming["time"], utc=True).dropna())
    overlap = existing_times & incoming_times
    new_rows = len(incoming_times - existing_times)
    rows_replaced = len(overlap) if prefer_incoming else 0
    deduped = deduped.drop(columns=["__source_order", "__source"], errors="ignore")
    deduped = deduped.sort_values("time").reset_index(drop=True)
    return deduped, {
        "new_rows_added": int(new_rows),
        "duplicate_rows_skipped": int(duplicate_rows_skipped),
        "rows_replaced": int(rows_replaced),
    }


def _summary_times(df: pd.DataFrame) -> dict[str, str | None]:
    if df.empty or "time" not in df.columns:
        return {"first": None, "last": None}
    times = pd.to_datetime(df["time"], utc=True, errors="coerce").dropna()
    return {
        "first": times.min().isoformat() if not times.empty else None,
        "last": times.max().isoformat() if not times.empty else None,
    }


def _backup_file(path: Path, backup_root: Path, symbol: str, stamp: str) -> Path:
    dest_dir = backup_root / symbol / stamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    shutil.copy2(path, dest)
    return dest


def process_timeframe(
    *,
    source_dir: Path,
    data_dir: Path,
    symbol: str,
    timeframe: str,
    prefer_incoming: bool,
) -> dict[str, Any]:
    existing_path = data_dir / symbol / f"{timeframe}.csv"
    incoming_path = _find_incoming_file(source_dir, symbol, timeframe)
    item: dict[str, Any] = {
        "timeframe": timeframe,
        "existing_path": str(existing_path),
        "incoming_path": str(incoming_path) if incoming_path else None,
        "incoming_exists": incoming_path is not None,
    }
    if not existing_path.exists():
        item["verdict_flags"] = ["FILE_MISSING"]
        return item
    existing_read = read_candle_csv(existing_path)
    existing = existing_read.frame
    item["existing_rows"] = int(len(existing))
    item["existing_schema"] = existing_read.schema
    item["timestamp_has_time"] = existing_read.timestamp_has_time
    item["before"] = _summary_times(existing)
    if incoming_path is None:
        item["incoming_rows"] = 0
        item["merged_rows"] = int(len(existing))
        item["new_rows_added"] = 0
        item["duplicate_rows_skipped"] = 0
        item["rows_replaced"] = 0
        item["verdict_flags"] = ["INCOMING_DATA_MISSING", "DATA_UNCHANGED"]
        return item
    incoming_read = read_candle_csv(incoming_path)
    incoming = _ensure_schema(incoming_read.frame, existing_read.schema)
    item["incoming_rows"] = int(len(incoming))
    incoming_validation = validate_frame(incoming, timeframe)
    item["incoming_validation"] = incoming_validation
    if incoming_validation.get("invalid_ohlc_rows", 0) or incoming_validation.get("missing_ohlc_values", 0):
        item["merged_rows"] = int(len(existing))
        item["new_rows_added"] = 0
        item["duplicate_rows_skipped"] = 0
        item["rows_replaced"] = 0
        item["verdict_flags"] = ["INCOMING_SCHEMA_INVALID"]
        return item
    merged, counts = merge_frames(existing, incoming, prefer_incoming=prefer_incoming)
    final_validation = validate_frame(merged, timeframe)
    item.update(counts)
    item["merged_rows"] = int(len(merged))
    item["after"] = _summary_times(merged)
    item["gaps_before"] = validate_frame(existing, timeframe).get("gaps", 0)
    item["gaps_after"] = final_validation.get("gaps", 0)
    item["final_validation"] = final_validation
    item["_merged_frame"] = merged
    flags: list[str] = []
    if final_validation.get("invalid_ohlc_rows", 0) or final_validation.get("non_monotonic_timestamps", 0):
        flags.append("FINAL_VALIDATION_FAILED")
    if counts["new_rows_added"] > 0 or counts["rows_replaced"] > 0:
        flags.append("DATA_UPDATED")
    else:
        flags.extend(["NO_NEW_ROWS_FOUND", "DATA_UNCHANGED"])
    item["verdict_flags"] = flags
    return item


def build_ingestion(
    *,
    source_dir: Path,
    data_dir: Path,
    symbol: str,
    timeframes: list[str],
    dry_run: bool,
    apply: bool,
    backup: bool,
    no_backup: bool,
    prefer_incoming: bool,
    strict: bool,
    run_paper_scanner_after_ingest: bool,
) -> dict[str, Any]:
    if apply and dry_run:
        raise ValueError("choose either --dry-run or --apply, not both")
    apply_mode = bool(apply)
    backup_enabled = apply_mode and not no_backup
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    items = [
        process_timeframe(
            source_dir=source_dir,
            data_dir=data_dir,
            symbol=symbol,
            timeframe=tf,
            prefer_incoming=prefer_incoming,
        )
        for tf in timeframes
    ]
    all_flags = sorted({flag for item in items for flag in item.get("verdict_flags", [])})
    if strict and any("INCOMING_DATA_MISSING" in item.get("verdict_flags", []) for item in items):
        all_flags.append("STRICT_INCOMING_DATA_MISSING")
    failed = any(flag in all_flags for flag in ("FINAL_VALIDATION_FAILED", "INCOMING_SCHEMA_INVALID", "FILE_MISSING", "STRICT_INCOMING_DATA_MISSING"))
    backups: list[str] = []
    updated_files: list[str] = []
    if apply_mode and not failed:
        for item in items:
            merged = item.pop("_merged_frame", None)
            if merged is None or "DATA_UPDATED" not in item.get("verdict_flags", []):
                continue
            existing_path = Path(item["existing_path"])
            if backup_enabled:
                backups.append(str(_backup_file(existing_path, data_dir.parent / "data_backups", symbol, stamp)))
            write_project_csv(
                merged,
                existing_path,
                item["existing_schema"],
                timestamp_has_time=bool(item["timestamp_has_time"]),
            )
            updated_files.append(str(existing_path))
    else:
        for item in items:
            item.pop("_merged_frame", None)
    total_new = sum(int(item.get("new_rows_added", 0)) for item in items)
    verdict = "INGESTION_APPLIED" if apply_mode and not failed else "INGESTION_DRY_RUN_OK"
    if failed:
        verdict = "FINAL_VALIDATION_FAILED"
    flags = [verdict] + all_flags
    if backup_enabled and backups:
        flags.append("BACKUP_CREATED")
    if total_new == 0:
        flags.append("NO_NEW_ROWS_FOUND")
    if updated_files:
        flags.append("DATA_UPDATED")
    if not source_dir.exists():
        flags.append("INCOMING_DATA_MISSING")
    scanner_ran = False
    if run_paper_scanner_after_ingest and apply_mode and updated_files and not failed:
        subprocess.run(
            [
                sys.executable,
                "scripts/run_strategy_3_paper_shadow_scanner.py",
                "--symbol",
                symbol,
                "--timeframes",
                ",".join(timeframes),
                "--data-dir",
                str(data_dir),
                "--output-dir",
                "backtests/reports/strategy_3_paper_shadow_scanner",
                "--cooldown-minutes",
                "120",
                "--dry-run",
            ],
            check=True,
        )
        scanner_ran = True
    return {
        "symbol": symbol,
        "source_dir": str(source_dir),
        "data_dir": str(data_dir),
        "dry_run": not apply_mode,
        "apply": apply_mode,
        "backup_enabled": backup_enabled,
        "prefer_incoming": prefer_incoming,
        "strict": strict,
        "timeframes": items,
        "total_new_rows_added": int(total_new),
        "backups": backups,
        "updated_files": updated_files,
        "paper_scanner_ran": scanner_ran,
        "verdict_flags": list(dict.fromkeys(flags)),
        "safety": {
            "live_trading_enabled": False,
            "telegram_enabled": False,
            "order_execution_enabled": False,
            "broker_called": False,
            "telegram_sent": False,
            "order_sent": False,
        },
    }


def write_ingestion_report(summary: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ingestion_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    lines = [
        "# XAUUSD Candle Ingestion",
        "",
        f"- symbol: `{summary['symbol']}`",
        f"- source_dir: `{summary['source_dir']}`",
        f"- dry_run: `{summary['dry_run']}`",
        f"- apply: `{summary['apply']}`",
        f"- backup_enabled: `{summary['backup_enabled']}`",
        f"- total_new_rows_added: `{summary['total_new_rows_added']}`",
        f"- verdict_flags: `{', '.join(summary['verdict_flags'])}`",
        "",
        "| TF | existing | incoming | new | dup skipped | replaced | before last | after last | flags |",
        "|---|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for item in summary["timeframes"]:
        lines.append(
            f"| {item['timeframe']} | {item.get('existing_rows', 0)} | {item.get('incoming_rows', 0)} | "
            f"{item.get('new_rows_added', 0)} | {item.get('duplicate_rows_skipped', 0)} | {item.get('rows_replaced', 0)} | "
            f"{(item.get('before') or {}).get('last')} | {(item.get('after') or item.get('before') or {}).get('last')} | "
            f"{', '.join(item.get('verdict_flags', []))} |"
        )
    lines.extend(["", "Default mode is dry-run. Real data files are modified only with explicit `--apply`.", ""])
    (output_dir / "ingestion_report.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = perf_counter()
    summary = build_ingestion(
        source_dir=Path(args.source_dir),
        data_dir=Path(args.data_dir),
        symbol=args.symbol,
        timeframes=_split_timeframes(args.timeframes),
        dry_run=bool(args.dry_run or not args.apply),
        apply=bool(args.apply),
        backup=bool(args.backup),
        no_backup=bool(args.no_backup),
        prefer_incoming=bool(args.prefer_incoming),
        strict=bool(args.strict),
        run_paper_scanner_after_ingest=bool(args.run_paper_scanner_after_ingest),
    )
    summary["runtime_seconds"] = round(perf_counter() - started, 4)
    summary["output_dir"] = args.output_dir
    summary["post_ingest_audit"] = build_audit(Path(args.data_dir), args.symbol, _split_timeframes(args.timeframes))
    write_ingestion_report(summary, Path(args.output_dir))
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0 if "FINAL_VALIDATION_FAILED" not in summary["verdict_flags"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
