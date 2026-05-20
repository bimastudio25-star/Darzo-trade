from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1"]
TIME_COLUMNS = ("time", "timestamp", "datetime", "date")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def detect_encoding(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for encoding in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "unknown"


def _split_first_line(text: str) -> list[str]:
    first = text.splitlines()[0] if text.splitlines() else ""
    return [part.strip().strip('"') for part in first.split(",")]


def header_present(text: str) -> bool:
    first = _split_first_line(text)
    if not first:
        return False
    lowered = {item.lower() for item in first}
    return bool(lowered & set(TIME_COLUMNS)) or {"open", "high", "low", "close"}.issubset(lowered)


def _read_parseable_frame(path: Path, encoding: str, has_header: bool) -> tuple[pd.DataFrame | None, str | None]:
    try:
        if has_header:
            return pd.read_csv(path, encoding=encoding), None
        return pd.read_csv(
            path,
            encoding=encoding,
            header=None,
            names=["time", "open", "high", "low", "close", "tick_volume", "spread"],
        ), None
    except Exception as exc:  # pragma: no cover - exact pandas parser exception varies
        return None, str(exc)


def summarize_timeframe_file(path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "file_size": 0,
        "sha256": None,
        "row_count": None,
        "first_timestamp": None,
        "latest_timestamp": None,
        "detected_encoding": None,
        "header_present": None,
        "parse_warning": None,
    }
    if not path.exists():
        summary["parse_warning"] = "file_missing"
        return summary
    raw = path.read_bytes()
    summary["file_size"] = len(raw)
    summary["sha256"] = sha256_bytes(raw)
    encoding = detect_encoding(raw)
    summary["detected_encoding"] = encoding
    if encoding == "unknown":
        summary["parse_warning"] = "encoding_unknown"
        return summary
    try:
        text = raw.decode(encoding)
    except UnicodeError as exc:
        summary["parse_warning"] = f"decode_failed: {exc}"
        return summary
    has_header = header_present(text)
    summary["header_present"] = has_header
    frame, warning = _read_parseable_frame(path, encoding, has_header)
    if warning or frame is None:
        summary["parse_warning"] = warning or "csv_parse_failed"
        return summary
    summary["row_count"] = int(len(frame))
    time_col = next((col for col in TIME_COLUMNS if col in frame.columns), None)
    if time_col is None:
        summary["parse_warning"] = "time_column_missing"
        return summary
    timestamps = pd.to_datetime(frame[time_col], utc=True, errors="coerce").dropna()
    if timestamps.empty:
        summary["parse_warning"] = "timestamps_not_parseable"
        return summary
    summary["first_timestamp"] = timestamps.min().isoformat()
    summary["latest_timestamp"] = timestamps.max().isoformat()
    return summary


def compute_data_context(
    *,
    symbol: str = "XAUUSD",
    data_dir: str | Path = "data",
    timeframes: list[str] | tuple[str, ...] = DEFAULT_TIMEFRAMES,
) -> dict[str, Any]:
    root = Path(data_dir)
    files: dict[str, Any] = {}
    for timeframe in timeframes:
        files[timeframe] = summarize_timeframe_file(root / symbol / f"{timeframe}.csv")
    hash_payload = {
        "symbol": symbol,
        "timeframes": list(timeframes),
        "files": {
            timeframe: {
                "exists": item["exists"],
                "sha256": item["sha256"],
                "file_size": item["file_size"],
                "row_count": item["row_count"],
                "first_timestamp": item["first_timestamp"],
                "latest_timestamp": item["latest_timestamp"],
                "detected_encoding": item["detected_encoding"],
                "header_present": item["header_present"],
            }
            for timeframe, item in files.items()
        },
    }
    combined_hash = sha256_bytes(json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return {
        "data_context_created_at": utc_now_iso(),
        "symbol": symbol,
        "data_dir": str(root),
        "timeframes_included": list(timeframes),
        "combined_data_context_hash": combined_hash,
        "files": files,
    }


def compact_context(context: dict[str, Any]) -> dict[str, Any]:
    files = context.get("files", {}) if isinstance(context.get("files"), dict) else {}
    return {
        "combined_data_context_hash": context.get("combined_data_context_hash"),
        "data_context_created_at": context.get("data_context_created_at"),
        "symbol": context.get("symbol"),
        "timeframes_included": context.get("timeframes_included", []),
        "latest_timestamp_by_timeframe": {
            timeframe: item.get("latest_timestamp") for timeframe, item in files.items() if isinstance(item, dict)
        },
        "sha256_by_timeframe": {
            timeframe: item.get("sha256") for timeframe, item in files.items() if isinstance(item, dict)
        },
    }


def diff_contexts(paper_context: dict[str, Any] | None, backtest_context: dict[str, Any]) -> dict[str, Any]:
    if not paper_context:
        return {
            "data_context_match": False,
            "data_context_missing": True,
            "mismatched_timeframes": [],
            "missing_timeframes": [],
            "paper_data_context_hash": None,
            "backtest_data_context_hash": backtest_context.get("combined_data_context_hash"),
            "verdict_flags": ["DATA_CONTEXT_MISSING", "COMPARISON_NOT_CLEAN_VALIDATION"],
        }
    paper_files = paper_context.get("files", {}) if isinstance(paper_context.get("files"), dict) else {}
    backtest_files = backtest_context.get("files", {}) if isinstance(backtest_context.get("files"), dict) else {}
    mismatched: list[str] = []
    missing: list[str] = []
    for timeframe, backtest_item in backtest_files.items():
        paper_item = paper_files.get(timeframe)
        if not isinstance(paper_item, dict):
            missing.append(str(timeframe))
            continue
        if paper_item.get("sha256") != backtest_item.get("sha256"):
            mismatched.append(str(timeframe))
    hash_match = paper_context.get("combined_data_context_hash") == backtest_context.get("combined_data_context_hash")
    verdict = ["DATA_CONTEXT_MATCH"] if hash_match and not mismatched and not missing else [
        "DATA_CONTEXT_MISMATCH",
        "COMPARISON_NOT_CLEAN_VALIDATION",
        "PRE_REPAIR_DATA_CONTEXT_CONTAMINATION_POSSIBLE",
    ]
    return {
        "data_context_match": bool(hash_match and not mismatched and not missing),
        "data_context_missing": False,
        "mismatched_timeframes": mismatched,
        "missing_timeframes": missing,
        "paper_data_context_hash": paper_context.get("combined_data_context_hash"),
        "backtest_data_context_hash": backtest_context.get("combined_data_context_hash"),
        "verdict_flags": verdict,
    }


def write_context(path: Path, context: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context, indent=2, sort_keys=True, default=str), encoding="utf-8")
