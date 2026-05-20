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

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_xauusd_data import CANONICAL_SCHEMA, read_candle_csv, validate_frame
from scripts.import_xauusd_candles import write_project_csv
from scripts.strategy_3_htf_freshness import analyze_htf_freshness, write_h4_quarantine_report

DEFAULT_CONFLICT_TS = "2026-05-19T00:00:00+00:00"
SAFETY = {
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "order_execution_enabled": False,
    "broker_execution_enabled": False,
    "broker_order_functions_called": False,
    "order_send_called": False,
}


@dataclass(frozen=True)
class RepairConfig:
    symbol: str
    data_dir: Path
    diagnostic_dir: Path
    output_dir: Path
    dry_run: bool
    apply: bool
    max_material_mismatches: int
    required_ohlc_match_rate: float
    expected_conflict_timestamp: str
    preserve_existing_format: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely repair Strategy 3 local XAUUSD H4 data")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--diagnostic-dir", default="backtests/reports/strategy_3_h4_data_source_diagnostic")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_3_h4_safe_repair")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--max-material-mismatches", type=int, default=1)
    parser.add_argument("--required-ohlc-match-rate", type=float, default=0.99)
    parser.add_argument("--expected-conflict-timestamp", default=DEFAULT_CONFLICT_TS)
    parser.add_argument("--preserve-existing-format", action="store_true", default=True)
    return parser.parse_args(argv)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat()


def _parse_ts(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _format_ts(value: Any) -> str:
    ts = _parse_ts(value).tz_localize(None)
    return ts.strftime("%Y.%m.%d %H:%M")


def _latest(df: pd.DataFrame) -> pd.Timestamp | None:
    if df.empty or "time" not in df.columns:
        return None
    times = pd.to_datetime(df["time"], utc=True, errors="coerce").dropna()
    return times.max() if not times.empty else None


def _row_payload(row: pd.Series | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out: dict[str, Any] = {}
    for col in CANONICAL_SCHEMA:
        if col not in row:
            continue
        value = row[col]
        if col == "time":
            out[col] = _iso(value)
        else:
            out[col] = None if pd.isna(value) else float(value)
    return out


def detect_h4_format(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    encoding = "utf-16" if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff") else "utf-8"
    text = path.read_text(encoding=encoding)
    first_line = text.splitlines()[0] if text.splitlines() else ""
    delimiter = "," if "," in first_line else ";"
    first_cells = next(csv.reader([first_line], delimiter=delimiter), [])
    first_cell = first_cells[0].strip().lower() if first_cells else ""
    header_present = first_cell in {"time", "timestamp", "datetime", "date"}
    timestamp_format = "yyyy.MM.dd HH:mm" if first_cells and "." in first_cells[0] and ":" in first_cells[0] else "unknown"
    return {
        "encoding": encoding,
        "delimiter": delimiter,
        "header_present": header_present,
        "column_order": list(CANONICAL_SCHEMA),
        "timestamp_format": timestamp_format,
        "row_count_text": len(text.splitlines()),
        "first_row": first_line,
        "last_row": text.splitlines()[-1] if text.splitlines() else None,
    }


def load_required_inputs(cfg: RepairConfig) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any], bool]:
    h4_path = cfg.data_dir / cfg.symbol / "H4.csv"
    diagnostic_path = cfg.diagnostic_dir / "h4_data_source_diagnostic.json"
    mt5_candidate_path = cfg.diagnostic_dir / "h4_mt5_candidate.csv"
    missing = [str(path) for path in (h4_path, diagnostic_path, mt5_candidate_path) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"required_files_missing={missing}")
    local_read = read_candle_csv(h4_path)
    mt5_read = read_candle_csv(mt5_candidate_path)
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    fmt = detect_h4_format(h4_path)
    return local_read.frame.copy(), mt5_read.frame.copy(), diagnostic, fmt, local_read.timestamp_has_time


def _material_mismatch_count(diagnostic: dict[str, Any]) -> int:
    overlap = diagnostic.get("overlap", {})
    overlap_count = int(overlap.get("overlap_count", 0) or 0)
    match_count = int(overlap.get("match_count_ohlc", 0) or 0)
    return max(0, overlap_count - match_count)


def run_safety_checks(
    *,
    cfg: RepairConfig,
    local: pd.DataFrame,
    mt5: pd.DataFrame,
    diagnostic: dict[str, Any],
) -> tuple[bool, list[str], dict[str, Any]]:
    failed: list[str] = []
    overlap = diagnostic.get("overlap", {})
    append = diagnostic.get("append_rebuild_diagnostic", {})
    timezone_diag = diagnostic.get("timezone_boundary_diagnostics", {})
    local_diag = diagnostic.get("local_h4", {})
    mt5_diag = diagnostic.get("mt5_h4", {})
    expected_ts = _iso(cfg.expected_conflict_timestamp)
    material_count = _material_mismatch_count(diagnostic)
    ohlc_rate = float(overlap.get("match_rate_ohlc") or 0.0)
    if ohlc_rate < cfg.required_ohlc_match_rate:
        failed.append("OHLC_MATCH_RATE_BELOW_REQUIRED")
    if material_count > cfg.max_material_mismatches:
        failed.append("TOO_MANY_MATERIAL_MISMATCHES")
    if _iso(overlap.get("first_ohlc_mismatch_timestamp")) != expected_ts or _iso(overlap.get("last_ohlc_mismatch_timestamp")) != expected_ts:
        failed.append("UNEXPECTED_CONFLICT_TIMESTAMP")
    if int(timezone_diag.get("best_shift_by_match_rate", 999)) != 0 or bool(timezone_diag.get("timezone_shift_suspected")):
        failed.append("TIMEZONE_SHIFT_SUSPECTED")
    if _parse_ts(mt5_diag.get("latest_closed_timestamp")) <= _parse_ts(local_diag.get("latest_timestamp")):
        failed.append("MT5_NOT_FRESHER_THAN_LOCAL")
    if diagnostic.get("recommendation") == "DO_NOT_RECOVER_UNSAFE":
        failed.append("DIAGNOSTIC_RECOMMENDS_DO_NOT_RECOVER")
    mt5_validation = validate_frame(mt5, "H4")
    local_validation = validate_frame(local, "H4")
    if mt5_validation.get("duplicate_timestamps", 0):
        failed.append("MT5_CANDIDATE_DUPLICATES")
    if mt5_validation.get("non_monotonic_timestamps", 0) or mt5_validation.get("invalid_ohlc_rows", 0):
        failed.append("MT5_CANDIDATE_INVALID")
    if local_validation.get("duplicate_timestamps", 0):
        failed.append("LOCAL_H4_DUPLICATES")
    if local_validation.get("non_monotonic_timestamps", 0) or local_validation.get("invalid_ohlc_rows", 0):
        failed.append("LOCAL_H4_INVALID")
    conflict_ts = _parse_ts(cfg.expected_conflict_timestamp)
    mt5_times = set(pd.to_datetime(mt5["time"], utc=True))
    if conflict_ts not in mt5_times:
        failed.append("MT5_CANDIDATE_MISSING_CONFLICT_TIMESTAMP")
    local_latest = _parse_ts(local_diag.get("latest_timestamp"))
    missing_after = mt5[pd.to_datetime(mt5["time"], utc=True) > local_latest]
    if missing_after.empty or int(append.get("missing_closed_bars_after_local_latest", 0) or 0) <= 0:
        failed.append("NO_MISSING_CLOSED_BARS_TO_APPEND")
    details = {
        "material_mismatch_count": material_count,
        "ohlc_match_rate": ohlc_rate,
        "local_validation": local_validation,
        "mt5_validation": mt5_validation,
        "missing_closed_bars_after_local_latest": int(len(missing_after)),
    }
    return not failed, failed, details


def build_repaired_h4(local: pd.DataFrame, mt5: pd.DataFrame, conflict_timestamp: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    local = local.copy()
    mt5 = mt5.copy()
    local["time"] = pd.to_datetime(local["time"], utc=True)
    mt5["time"] = pd.to_datetime(mt5["time"], utc=True)
    conflict_ts = _parse_ts(conflict_timestamp)
    local_conflict_rows = local[local["time"] == conflict_ts]
    mt5_conflict_rows = mt5[mt5["time"] == conflict_ts]
    if local_conflict_rows.empty or mt5_conflict_rows.empty:
        raise ValueError("conflict_timestamp_missing_in_local_or_mt5")
    local_conflict = local_conflict_rows.iloc[0].copy()
    mt5_conflict = mt5_conflict_rows.iloc[0].copy()
    out = local[local["time"] != conflict_ts].copy()
    out = pd.concat([out, mt5_conflict.to_frame().T], ignore_index=True, sort=False)
    old_latest = _latest(local)
    append = mt5[mt5["time"] > old_latest].copy() if old_latest is not None else mt5.iloc[0:0].copy()
    out = pd.concat([out, append], ignore_index=True, sort=False)
    out = out.drop_duplicates(subset=["time"], keep="last").sort_values("time").reset_index(drop=True)
    validation = validate_frame(out, "H4")
    if validation.get("duplicate_timestamps", 0) or validation.get("non_monotonic_timestamps", 0) or validation.get("invalid_ohlc_rows", 0):
        raise ValueError(f"repaired_h4_validation_failed={validation}")
    return out, {
        "local_conflict_row": _row_payload(local_conflict),
        "mt5_conflict_row": _row_payload(mt5_conflict),
        "rows_replaced_count": 1,
        "rows_appended_count": int(len(append)),
        "old_latest_timestamp": _iso(old_latest),
        "new_latest_timestamp": _iso(_latest(out)),
        "validation": validation,
    }


def write_repaired_candidate(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["time"] = out["time"].map(_format_ts)
    out.to_csv(path, index=False, header=False, encoding="utf-16", lineterminator="\n")


def write_diff_csv(repair_details: dict[str, Any], path: Path) -> None:
    rows = [
        {"kind": "local_conflict", **(repair_details.get("local_conflict_row") or {})},
        {"kind": "mt5_conflict", **(repair_details.get("mt5_conflict_row") or {})},
    ]
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")


def compare_repaired_to_mt5(repaired: pd.DataFrame, mt5: pd.DataFrame, tolerance: float = 0.10) -> dict[str, Any]:
    left = repaired.copy()
    right = mt5.copy()
    left["time"] = pd.to_datetime(left["time"], utc=True)
    right["time"] = pd.to_datetime(right["time"], utc=True)
    merged = left.merge(right, on="time", suffixes=("_repaired", "_mt5"))
    if merged.empty:
        return {"overlap_count": 0, "match_rate_ohlc": None}
    diffs = []
    for col in ("open", "high", "low", "close"):
        diffs.append((merged[f"{col}_repaired"].astype(float) - merged[f"{col}_mt5"].astype(float)).abs())
    max_diff = pd.concat(diffs, axis=1).max(axis=1)
    matched = max_diff <= tolerance
    return {
        "overlap_count": int(len(merged)),
        "match_count_ohlc": int(matched.sum()),
        "match_rate_ohlc": round(float(matched.mean()), 4),
        "worst_ohlc_diff": round(float(max_diff.max()), 5),
    }


def write_report(summary: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "h4_repair_report.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    lines = [
        "# Strategy 3 H4 Safe Repair",
        "",
        "This is a data repair report only. No Strategy 3, VWAP, sigma, cooldown, live, Telegram, broker, or order path was changed.",
        "",
        f"- dry_run: `{summary.get('dry_run')}`",
        f"- apply: `{summary.get('apply')}`",
        f"- repair_status: `{summary.get('repair_status')}`",
        f"- safety_checks_passed: `{summary.get('safety_checks_passed')}`",
        f"- failed_safety_checks: `{', '.join(summary.get('failed_safety_checks', []))}`",
        f"- backup_path: `{summary.get('backup_path')}`",
        f"- detected_encoding: `{summary.get('detected_encoding')}`",
        f"- detected_header_present: `{summary.get('detected_header_present')}`",
        f"- preserved_format: `{summary.get('preserved_format')}`",
        f"- conflict_timestamp: `{summary.get('conflict_timestamp')}`",
        f"- rows_replaced_count: `{summary.get('rows_replaced_count')}`",
        f"- rows_appended_count: `{summary.get('rows_appended_count')}`",
        f"- old_latest_timestamp: `{summary.get('old_latest_timestamp')}`",
        f"- new_latest_timestamp: `{summary.get('new_latest_timestamp')}`",
        f"- mt5_latest_closed_timestamp: `{summary.get('mt5_latest_closed_timestamp')}`",
        f"- post_repair_freshness_status: `{summary.get('post_repair_freshness_status')}`",
        f"- post_repair_overlap_match_rate: `{summary.get('post_repair_overlap_match_rate')}`",
        f"- scanner_should_remain_blocked: `{summary.get('scanner_should_remain_blocked')}`",
        f"- paper_signals_clean_for_validation: `{summary.get('paper_signals_clean_for_validation')}`",
        f"- recommendation: `{summary.get('recommendation')}`",
        "",
    ]
    (output_dir / "h4_repair_report.md").write_text("\n".join(lines), encoding="utf-8")


def _post_repair_freshness(data_dir: Path, symbol: str, expected_now: Any, output_dir: Path) -> dict[str, Any]:
    diagnostic = analyze_htf_freshness(
        data_dir=data_dir,
        symbol=symbol,
        now_utc=expected_now,
        timeframes=["D1", "H4", "H1"],
    )
    write_h4_quarantine_report(diagnostic, output_dir / "post_repair_h4_freshness")
    return diagnostic


def build_repair(cfg: RepairConfig) -> dict[str, Any]:
    started = perf_counter()
    h4_path = cfg.data_dir / cfg.symbol / "H4.csv"
    summary: dict[str, Any] = {
        "run_started_at": datetime.now(timezone.utc).isoformat(),
        "symbol": cfg.symbol,
        "dry_run": cfg.dry_run,
        "apply": cfg.apply,
        "local_h4_path": str(h4_path),
        "backup_path": None,
        "data_h4_modified": False,
        "safety_checks_passed": False,
        "failed_safety_checks": [],
        "repair_status": "REPAIR_ABORTED_SAFETY_CHECK_FAILED",
        "safety": dict(SAFETY),
    }
    try:
        local, mt5, diagnostic, fmt, timestamp_has_time = load_required_inputs(cfg)
        summary.update(
            {
                "detected_encoding": fmt["encoding"],
                "detected_delimiter": fmt["delimiter"],
                "detected_header_present": bool(fmt["header_present"]),
                "detected_timestamp_format": fmt["timestamp_format"],
                "first_row": fmt["first_row"],
                "last_row": fmt["last_row"],
                "output_encoding": fmt["encoding"] if cfg.preserve_existing_format else "utf-16",
                "output_header_present": bool(fmt["header_present"]) if cfg.preserve_existing_format else False,
                "preserved_format": bool(cfg.preserve_existing_format),
                "recommendation": diagnostic.get("recommendation"),
                "mt5_latest_closed_timestamp": diagnostic.get("mt5_h4", {}).get("latest_closed_timestamp"),
                "post_repair_overlap_match_rate": diagnostic.get("overlap", {}).get("match_rate_ohlc"),
            }
        )
        checks_ok, failed, check_details = run_safety_checks(cfg=cfg, local=local, mt5=mt5, diagnostic=diagnostic)
        summary["safety_checks_passed"] = checks_ok
        summary["failed_safety_checks"] = failed
        summary["safety_check_details"] = check_details
        if not checks_ok:
            summary["repair_status"] = "REPAIR_ABORTED_SAFETY_CHECK_FAILED"
            summary["scanner_should_remain_blocked"] = True
            summary["paper_signals_clean_for_validation"] = False
            return summary
        repaired, repair_details = build_repaired_h4(local, mt5, cfg.expected_conflict_timestamp)
        summary.update(
            {
                "conflict_timestamp": _iso(cfg.expected_conflict_timestamp),
                **repair_details,
            }
        )
        candidate_path = cfg.output_dir / "H4.repaired_candidate.csv"
        diff_path = cfg.output_dir / "h4_repair_diff.csv"
        write_repaired_candidate(repaired, candidate_path)
        write_diff_csv(repair_details, diff_path)
        summary["repaired_candidate_path"] = str(candidate_path)
        summary["repair_diff_path"] = str(diff_path)
        if not cfg.apply or cfg.dry_run:
            summary["repair_status"] = "DRY_RUN_REPAIR_CANDIDATE_CREATED"
            if cfg.apply and cfg.dry_run:
                summary["apply_block_reason"] = "dry_run_enabled"
            summary["scanner_should_remain_blocked"] = True
            summary["paper_signals_clean_for_validation"] = False
            return summary
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = h4_path.with_name(f"{h4_path.name}.backup.{stamp}")
        backup.write_bytes(h4_path.read_bytes())
        summary["backup_path"] = str(backup)
        write_project_csv(
            repaired,
            h4_path,
            CANONICAL_SCHEMA,
            timestamp_has_time=timestamp_has_time,
        )
        summary["data_h4_modified"] = True
        post_overlap = compare_repaired_to_mt5(repaired, mt5)
        summary["post_repair_overlap_match_rate"] = post_overlap.get("match_rate_ohlc")
        summary["post_repair_overlap"] = post_overlap
        post = _post_repair_freshness(cfg.data_dir, cfg.symbol, diagnostic.get("mt5_h4", {}).get("latest_closed_timestamp"), cfg.output_dir)
        summary["post_repair_freshness_status"] = post.get("h4_quarantine_status") or post.get("htf_freshness_status")
        clean = bool(post.get("paper_signals_clean_for_validation"))
        summary["scanner_should_remain_blocked"] = not clean
        summary["paper_signals_clean_for_validation"] = clean
        summary["repair_status"] = "REPAIR_APPLIED_H4_FRESH" if clean else "REPAIR_APPLIED_BUT_STILL_STALE"
        return summary
    except Exception as exc:
        summary["error"] = str(exc)
        summary["repair_status"] = "REPAIR_ABORTED_SAFETY_CHECK_FAILED"
        summary["scanner_should_remain_blocked"] = True
        summary["paper_signals_clean_for_validation"] = False
        return summary
    finally:
        summary["run_finished_at"] = datetime.now(timezone.utc).isoformat()
        summary["runtime_seconds"] = round(perf_counter() - started, 4)
        write_report(summary, cfg.output_dir)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = RepairConfig(
        symbol=args.symbol,
        data_dir=Path(args.data_dir),
        diagnostic_dir=Path(args.diagnostic_dir),
        output_dir=Path(args.output_dir),
        dry_run=bool(args.dry_run or not args.apply),
        apply=bool(args.apply),
        max_material_mismatches=int(args.max_material_mismatches),
        required_ohlc_match_rate=float(args.required_ohlc_match_rate),
        expected_conflict_timestamp=args.expected_conflict_timestamp,
        preserve_existing_format=bool(args.preserve_existing_format),
    )
    summary = build_repair(cfg)
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
