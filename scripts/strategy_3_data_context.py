from __future__ import annotations

import hashlib
import json
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1"]
TIME_COLUMNS = ("time", "timestamp", "datetime", "date")
RECORDED_PREFIX_FIELDS = {
    "M1": ("m1_hash", "m1_latest_timestamp"),
    "M5": ("m5_hash", "m5_latest_timestamp"),
    "M15": ("m15_hash", "m15_latest_timestamp"),
    "H1": ("h1_hash", "h1_latest_timestamp"),
    "H4": ("h4_hash", "h4_latest_timestamp"),
    "D1": ("d1_hash", "d1_latest_timestamp"),
}


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


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip().strip('"')
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    for candidate in (normalized, normalized.replace(" ", "T", 1)):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    for fmt in ("%Y.%m.%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = pd.to_datetime(raw, utc=True, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _first_csv_value(line: str) -> str:
    try:
        row = next(csv.reader([line]))
    except (csv.Error, StopIteration):
        return line.split(",", 1)[0].strip().strip('"')
    return str(row[0]).strip() if row else ""


def _timestamp_sort_key(value: Any) -> str | None:
    raw = str(value or "").strip().strip('"')
    if len(raw) >= 16 and raw[4] == "." and raw[7] == ".":
        second = raw[17:19] if len(raw) >= 19 and raw[16] == ":" else "00"
        return f"{raw[0:4]}{raw[5:7]}{raw[8:10]}{raw[11:13]}{raw[14:16]}{second}"
    if len(raw) >= 16 and raw[4] == "-" and raw[7] == "-":
        hour_index = 11 if len(raw) > 10 and raw[10] in ("T", " ") else None
        if hour_index is not None:
            second = raw[17:19] if len(raw) >= 19 and raw[16] == ":" else "00"
            return f"{raw[0:4]}{raw[5:7]}{raw[8:10]}{raw[hour_index:hour_index+2]}{raw[14:16]}{second}"
    parsed = _parse_timestamp(raw)
    return parsed.strftime("%Y%m%d%H%M%S") if parsed else None


def _timestamp_key_to_iso(key: str | None) -> str | None:
    if not key or len(key) != 14:
        return None
    return f"{key[0:4]}-{key[4:6]}-{key[6:8]}T{key[8:10]}:{key[10:12]}:{key[12:14]}+00:00"


def _canonical_csv_row(line: str) -> str | None:
    try:
        row = next(csv.reader([line]))
    except (csv.Error, StopIteration):
        return None
    if not row:
        return None
    timestamp_key = _timestamp_sort_key(row[0])
    if timestamp_key is None:
        return None
    normalized = [_timestamp_key_to_iso(timestamp_key) or timestamp_key]
    for item in row[1:]:
        value = str(item).strip()
        try:
            normalized.append(f"{float(value):.10g}")
        except (TypeError, ValueError):
            normalized.append(value)
    return "|".join(normalized)


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


def summarize_timeframe_prefix(path: Path, cutoff_timestamp: Any | None) -> dict[str, Any]:
    """Summarize and hash the file prefix up to cutoff_timestamp.

    The raw prefix hash preserves the file's existing encoding/header/newlines so it
    can prove append-only compatibility with scanner rows that recorded full-file
    raw hashes at signal time. The canonical prefix hash is encoding-neutral and is
    useful for future scanner metadata.
    """
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "cutoff_timestamp": None,
        "raw_prefix_hash": None,
        "canonical_prefix_hash": None,
        "row_count_in_prefix": 0,
        "first_timestamp_in_prefix": None,
        "latest_timestamp_in_prefix": None,
        "detected_encoding": None,
        "header_present": None,
        "parse_warning": None,
    }
    cutoff = _parse_timestamp(cutoff_timestamp) if cutoff_timestamp is not None else None
    if cutoff_timestamp is not None:
        summary["cutoff_timestamp"] = cutoff.isoformat() if cutoff else str(cutoff_timestamp)
    if not path.exists():
        summary["parse_warning"] = "file_missing"
        return summary
    raw = path.read_bytes()
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
    lines = text.splitlines(keepends=True)
    selected_lines: list[str] = []
    selected_canonical_rows: list[str] = []
    timestamp_keys: list[str] = []
    cutoff_key = cutoff.strftime("%Y%m%d%H%M%S") if cutoff is not None else None
    start_index = 0
    if has_header and lines:
        selected_lines.append(lines[0])
        start_index = 1
    for line in lines[start_index:]:
        if not line.strip():
            continue
        timestamp_key = _timestamp_sort_key(_first_csv_value(line))
        if timestamp_key is None:
            continue
        if cutoff_key is not None and timestamp_key > cutoff_key:
            break
        selected_lines.append(line)
        canonical = _canonical_csv_row(line)
        if canonical is not None:
            selected_canonical_rows.append(canonical)
        timestamp_keys.append(timestamp_key)

    try:
        raw_prefix = "".join(selected_lines).encode(encoding)
    except UnicodeError as exc:
        summary["parse_warning"] = f"prefix_encode_failed: {exc}"
        return summary
    summary["raw_prefix_hash"] = sha256_bytes(raw_prefix)
    summary["canonical_prefix_hash"] = sha256_bytes("\n".join(selected_canonical_rows).encode("utf-8"))
    summary["row_count_in_prefix"] = len(timestamp_keys)
    if timestamp_keys:
        summary["first_timestamp_in_prefix"] = _timestamp_key_to_iso(min(timestamp_keys))
        summary["latest_timestamp_in_prefix"] = _timestamp_key_to_iso(max(timestamp_keys))
    return summary


def compute_context_prefix(
    *,
    symbol: str = "XAUUSD",
    data_dir: str | Path = "data",
    timeframes: list[str] | tuple[str, ...] = DEFAULT_TIMEFRAMES,
    cutoff_timestamp: Any | None = None,
) -> dict[str, Any]:
    root = Path(data_dir)
    files: dict[str, Any] = {}
    for timeframe in timeframes:
        files[timeframe] = summarize_timeframe_prefix(root / symbol / f"{timeframe}.csv", cutoff_timestamp)
    hash_payload = {
        "symbol": symbol,
        "timeframes": list(timeframes),
        "cutoff_timestamp": str(cutoff_timestamp) if cutoff_timestamp is not None else None,
        "files": {
            timeframe: {
                "canonical_prefix_hash": item["canonical_prefix_hash"],
                "row_count_in_prefix": item["row_count_in_prefix"],
                "latest_timestamp_in_prefix": item["latest_timestamp_in_prefix"],
            }
            for timeframe, item in files.items()
        },
    }
    return {
        "prefix_data_context_created_at": utc_now_iso(),
        "symbol": symbol,
        "data_dir": str(root),
        "timeframes_included": list(timeframes),
        "cutoff_timestamp": str(cutoff_timestamp) if cutoff_timestamp is not None else None,
        "prefix_data_context_hash": sha256_bytes(json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")),
        "files": files,
    }


def evaluate_recorded_prefix_compatibility(
    row: dict[str, Any],
    *,
    symbol: str = "XAUUSD",
    data_dir: str | Path = "data",
    timeframes: list[str] | tuple[str, ...] = DEFAULT_TIMEFRAMES,
    context_cutoff_policy: str = "paper_latest_per_timeframe",
    prefix_cache: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    signal_timestamp = row.get("signal_timestamp")
    checked: list[str] = []
    compatible: list[str] = []
    incompatible: list[str] = []
    insufficient: list[str] = []
    details: dict[str, Any] = {}
    root = Path(data_dir)
    for timeframe in timeframes:
        hash_field, latest_field = RECORDED_PREFIX_FIELDS.get(timeframe, (f"{timeframe.lower()}_hash", f"{timeframe.lower()}_latest_timestamp"))
        recorded_hash = str(row.get(hash_field) or "").strip()
        recorded_latest = str(row.get(latest_field) or "").strip()
        if not recorded_hash:
            continue
        cutoff = recorded_latest if context_cutoff_policy == "paper_latest_per_timeframe" and recorded_latest else signal_timestamp
        if not cutoff:
            insufficient.append(timeframe)
            details[timeframe] = {
                "recorded_hash": recorded_hash,
                "recorded_latest_timestamp": recorded_latest or None,
                "prefix_compatible": False,
                "status": "missing_cutoff_timestamp",
            }
            continue
        checked.append(timeframe)
        cache_key = (timeframe, str(cutoff))
        if prefix_cache is not None and cache_key in prefix_cache:
            prefix = prefix_cache[cache_key]
        else:
            prefix = summarize_timeframe_prefix(root / symbol / f"{timeframe}.csv", cutoff)
            if prefix_cache is not None:
                prefix_cache[cache_key] = prefix
        current_hash = prefix.get("raw_prefix_hash")
        status = "compatible" if current_hash == recorded_hash else "prefix_mismatch"
        if prefix.get("parse_warning"):
            status = str(prefix["parse_warning"])
            insufficient.append(timeframe)
        elif current_hash == recorded_hash:
            compatible.append(timeframe)
        else:
            incompatible.append(timeframe)
        details[timeframe] = {
            "recorded_hash": recorded_hash,
            "recorded_latest_timestamp": recorded_latest or None,
            "cutoff_timestamp": prefix.get("cutoff_timestamp"),
            "current_raw_prefix_hash": current_hash,
            "current_canonical_prefix_hash": prefix.get("canonical_prefix_hash"),
            "current_latest_timestamp_in_prefix": prefix.get("latest_timestamp_in_prefix"),
            "current_row_count_in_prefix": prefix.get("row_count_in_prefix"),
            "prefix_compatible": current_hash == recorded_hash and not prefix.get("parse_warning"),
            "status": status,
        }
    unverified = [timeframe for timeframe in timeframes if timeframe not in checked]
    prefix_compatible = bool(checked) and not incompatible and not insufficient and len(compatible) == len(checked)
    return {
        "signal_timestamp": signal_timestamp,
        "data_context_hash": row.get("data_context_hash"),
        "context_cutoff_policy": context_cutoff_policy,
        "checked_timeframes": checked,
        "compatible_timeframes": compatible,
        "incompatible_timeframes": incompatible,
        "insufficient_timeframes": insufficient,
        "unverified_timeframes": unverified,
        "prefix_compatible": prefix_compatible,
        "prefix_insufficient": not checked or bool(insufficient),
        "context_generation_mode": "PREFIX_COMPATIBLE_RECONSTRUCTED_FROM_RECORDED_TIMEFRAME_HASHES" if checked else "PREFIX_CONTEXT_INSUFFICIENT",
        "timeframes": details,
    }


def build_prefix_compatibility_report(
    rows: list[dict[str, Any]],
    *,
    symbol: str = "XAUUSD",
    data_dir: str | Path = "data",
    timeframes: list[str] | tuple[str, ...] = DEFAULT_TIMEFRAMES,
    context_cutoff_policy: str = "paper_latest_per_timeframe",
) -> dict[str, Any]:
    prefix_cache: dict[tuple[str, str], dict[str, Any]] = {}
    details = [
        evaluate_recorded_prefix_compatibility(
            row,
            symbol=symbol,
            data_dir=data_dir,
            timeframes=timeframes,
            context_cutoff_policy=context_cutoff_policy,
            prefix_cache=prefix_cache,
        )
        for row in rows
    ]
    compatible = [item for item in details if item["prefix_compatible"]]
    incompatible = [item for item in details if item["incompatible_timeframes"]]
    insufficient = [item for item in details if item["prefix_insufficient"]]
    context_hash_counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get("data_context_hash") or "").strip()
        if value:
            context_hash_counts[value] = context_hash_counts.get(value, 0) + 1
    all_compatible = bool(rows) and len(compatible) == len(rows) and not incompatible and not insufficient
    flags = ["DATA_CONTEXT_PREFIX_COMPATIBLE"] if all_compatible else []
    if len(context_hash_counts) > 1:
        flags.append("MULTIPLE_DATA_CONTEXTS_SEGMENTED")
    if all_compatible and len(context_hash_counts) > 1:
        flags.append("DATA_CONTEXT_FULL_HASH_DIFF_BUT_PREFIX_OK")
        flags.append("DATA_CONTEXT_SEGMENTED_COMPATIBLE")
    if incompatible:
        flags.append("DATA_CONTEXT_PREFIX_MISMATCH")
    if insufficient:
        flags.append("DATA_CONTEXT_PREFIX_INSUFFICIENT")
    return {
        "report_created_at": utc_now_iso(),
        "symbol": symbol,
        "data_dir": str(data_dir),
        "context_cutoff_policy": context_cutoff_policy,
        "total_rows": len(rows),
        "unique_full_data_contexts": len(context_hash_counts),
        "data_context_hash_counts": context_hash_counts,
        "prefix_compatible_rows": len(compatible),
        "prefix_incompatible_rows": len(incompatible),
        "insufficient_context_rows": len(insufficient),
        "all_required_rows_compatible": all_compatible,
        "verdict_flags": flags,
        "details": details,
    }


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
