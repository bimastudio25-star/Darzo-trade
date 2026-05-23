from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from dazro_trade.analytics.strategy_2_human_trade_alignment import HUMAN_TRADE_FIELDS


DEFAULT_INPUT_DIR = Path("backtests/reports/strategy_2_human_trade_alignment/raw_human_trade_exports")
DEFAULT_OUTPUT_DIR = Path("backtests/reports/strategy_2_human_trade_alignment")
NORMALIZED_OUTPUT = "human_trades_filled_normalized.csv"
IMPORT_SUMMARY = "human_trade_import_summary.json"
IMPORT_ERRORS = "human_trade_import_errors.csv"
COLUMN_MAPPING_AUDIT = "human_trade_import_column_mapping.csv"
IMPORT_README = "README_human_trade_import.md"
SUPPORTED_SUFFIXES = {".csv", ".tsv", ".txt"}
ENCODINGS = ["utf-8-sig", "utf-8", "utf-16", "utf-16-le", "utf-16-be"]
DELIMITERS = [",", ";", "\t"]
VALID_DIRECTIONS = {"LONG", "SHORT"}
SOURCE_OPTIONAL_COLUMNS = [
    "source_file_optional",
    "source_row_optional",
    "source_ticket_optional",
    "source_order_id_optional",
    "source_position_id_optional",
    "open_time_raw",
    "close_time_raw",
    "open_time_normalized",
    "close_time_normalized",
    "timezone_assumption",
    "import_warning_flags",
]
NORMALIZED_COLUMNS = HUMAN_TRADE_FIELDS + SOURCE_OPTIONAL_COLUMNS
ERROR_COLUMNS = [
    "input_file",
    "source_row_optional",
    "source_position_id_optional",
    "human_trade_id",
    "error_code",
    "error_message",
    "raw_payload",
]
SYMBOL_VARIANTS = {
    "XAUUSD": "XAUUSD",
    "XAUUSD.": "XAUUSD",
    "XAUUSDM": "XAUUSD",
}
SAFETY = {
    "strategy_2_only": True,
    "layer_b_pipeline_rerun": False,
    "alignment_run": False,
    "live_trading_enabled": False,
    "order_send_called": False,
    "broker_execution_called": False,
    "telegram_operational_signals_sent": False,
    "signals_generated": False,
    "parameters_optimized": False,
    "ml_used": False,
    "backtest_executed": False,
    "performance_claim_made": False,
    "wr_pf_r_claim_made": False,
    "automatic_rule_created": False,
    "market_data_written": False,
    "fabricated_human_trades": False,
}

SYNONYMS = {
    "symbol": ["Symbol", "Instrument", "Market"],
    "direction": ["Type", "Direction", "Side", "Buy/Sell"],
    "open_time": ["Open Time", "Time", "OpenTime", "Entry Time"],
    "close_time": ["Close Time", "CloseTime", "Exit Time"],
    "entry_price": ["Price", "Open Price", "Entry Price"],
    "exit_price": ["Close Price", "Exit Price"],
    "stop_loss": ["S/L", "SL", "Stop Loss"],
    "take_profit": ["T/P", "TP", "Take Profit"],
    "volume": ["Volume", "Lots", "Size"],
    "result_optional": ["Profit", "PnL", "Result"],
    "notes": ["Comment", "Notes", "Reason"],
    "source_ticket_optional": ["Ticket", "Deal"],
    "source_order_id_optional": ["Order", "Order ID"],
    "source_position_id_optional": ["Position", "Position ID", "PositionID"],
    "deal_entry_marker": ["Entry"],
    "commission_optional": ["Commission"],
    "swap_optional": ["Swap"],
}


@dataclass(frozen=True)
class RawFileRead:
    path: Path
    frame: pd.DataFrame
    encoding: str
    delimiter: str


@dataclass(frozen=True)
class ImportResult:
    normalized: pd.DataFrame
    errors: pd.DataFrame
    column_mapping: pd.DataFrame
    summary: dict[str, Any]
    readme_markdown: str


def import_strategy_2_human_trades(
    *,
    input_path: str | Path | None = None,
    input_dir: str | Path | None = None,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    symbol_filter: str = "XAUUSD",
    strategy_tag_filter: str | None = None,
    timezone_assumption: str | None = None,
    decimal_separator: str = "auto",
    overwrite: bool = True,
) -> ImportResult:
    started = time.perf_counter()
    output = Path(output_dir)
    validate_input_choice(input_path=input_path, input_dir=input_dir)
    validate_overwrite(output, overwrite=overwrite)
    files = discover_input_files(input_path=input_path, input_dir=input_dir)
    if not files:
        raise FileNotFoundError(f"no supported human trade export files found in {input_dir or input_path}")

    normalized_frames: list[pd.DataFrame] = []
    error_rows: list[dict[str, Any]] = []
    mapping_frames: list[pd.DataFrame] = []
    file_summaries: list[dict[str, Any]] = []
    duplicate_exact_dropped = 0

    for file_path in files:
        raw = read_raw_export(file_path)
        mapping = build_column_mapping(raw.frame.columns)
        mapping["input_file"] = str(file_path)
        mapping_frames.append(mapping)
        mapped = apply_column_mapping(raw.frame, mapping)
        granularity = detect_export_granularity(mapped)
        normalized, errors = normalize_mapped_frame(
            mapped,
            input_file=file_path,
            granularity=granularity,
            decimal_separator=decimal_separator,
            symbol_filter=symbol_filter,
            strategy_tag_filter=strategy_tag_filter,
            timezone_assumption=timezone_assumption or "broker/server time unknown",
        )
        normalized_frames.append(normalized)
        error_rows.extend(errors)
        file_summaries.append(
            {
                "input_file": str(file_path),
                "encoding": raw.encoding,
                "delimiter": delimiter_name(raw.delimiter),
                "rows_loaded": int(len(raw.frame)),
                "rows_valid": int(len(normalized)),
                "rows_invalid": int(len(errors)),
                "detected_export_granularity": granularity,
                "decimal_style": detect_decimal_style(mapped, decimal_separator),
            }
        )

    normalized_all = (
        pd.concat(normalized_frames, ignore_index=True)
        if normalized_frames
        else pd.DataFrame(columns=NORMALIZED_COLUMNS)
    )
    normalized_all, duplicate_summary, duplicate_errors = deduplicate_normalized(normalized_all)
    duplicate_exact_dropped += int(duplicate_summary["duplicates_dropped_exact"])
    error_rows.extend(duplicate_errors)
    errors = pd.DataFrame(error_rows, columns=ERROR_COLUMNS)
    column_mapping = pd.concat(mapping_frames, ignore_index=True) if mapping_frames else pd.DataFrame(columns=mapping_columns())

    if normalized_all.empty and errors.empty:
        raise ValueError("no rows loaded from human trade export")
    if normalized_all.empty:
        raise ValueError("no valid human trades normalized; see human_trade_import_errors.csv")

    summary = {
        "runtime_seconds": round(time.perf_counter() - started, 4),
        "overwrite": bool(overwrite),
        "input_mode": "single_file" if input_path else "directory",
        "files_processed": [str(path) for path in files],
        "file_summaries": file_summaries,
        "rows_loaded_total": int(sum(item["rows_loaded"] for item in file_summaries)),
        "rows_valid": int(len(normalized_all)),
        "rows_invalid": int(len(errors)),
        "rows_warning_only": int(normalized_all["import_warning_flags"].astype(str).ne("").sum()) if not normalized_all.empty else 0,
        "duplicates_detected": int(duplicate_summary["duplicates_detected"]),
        "duplicates_dropped_exact": duplicate_exact_dropped,
        "conflicting_duplicate_ids": int(duplicate_summary["conflicting_duplicate_ids"]),
        "detected_encodings": sorted({item["encoding"] for item in file_summaries}),
        "detected_delimiters": sorted({item["delimiter"] for item in file_summaries}),
        "decimal_separator_mode": decimal_separator,
        "decimal_styles": sorted({item["decimal_style"] for item in file_summaries}),
        "detected_export_granularities": sorted({item["detected_export_granularity"] for item in file_summaries}),
        "timezone_assumption": timezone_assumption or "broker/server time unknown",
        "symbol_filter": symbol_filter,
        "strategy_tag_filter": strategy_tag_filter or "",
        "alignment_metrics_generated": False,
        "performance_claim_made": False,
        "no_fake_trades_created": True,
        "safety": SAFETY,
    }
    return ImportResult(
        normalized=normalized_all[NORMALIZED_COLUMNS].copy(),
        errors=errors,
        column_mapping=column_mapping[mapping_columns()].copy(),
        summary=summary,
        readme_markdown=render_import_readme(summary),
    )


def validate_input_choice(*, input_path: str | Path | None, input_dir: str | Path | None) -> None:
    if bool(input_path) == bool(input_dir):
        raise ValueError("exactly one of --input or --input-dir must be provided")


def validate_overwrite(output_dir: Path, *, overwrite: bool) -> None:
    if overwrite:
        return
    existing = [
        output_dir / NORMALIZED_OUTPUT,
        output_dir / IMPORT_SUMMARY,
        output_dir / IMPORT_ERRORS,
        output_dir / COLUMN_MAPPING_AUDIT,
        output_dir / IMPORT_README,
    ]
    present = [str(path) for path in existing if path.exists()]
    if present:
        raise FileExistsError(f"--overwrite false and output files already exist: {present}")


def discover_input_files(*, input_path: str | Path | None, input_dir: str | Path | None) -> list[Path]:
    if input_path:
        path = Path(input_path)
        if not path.exists():
            raise FileNotFoundError(f"input file missing: {path}")
        return [path]
    directory = Path(input_dir) if input_dir else DEFAULT_INPUT_DIR
    if not directory.exists():
        raise FileNotFoundError(f"input directory missing: {directory}")
    return sorted(
        [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES],
        key=lambda path: path.name.lower(),
    )


def read_raw_export(path: str | Path) -> RawFileRead:
    file_path = Path(path)
    raw = file_path.read_bytes()
    errors: list[str] = []
    for encoding in ENCODINGS:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}: {exc}")
            continue
        delimiter = detect_delimiter(text, file_path)
        try:
            frame = pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str, keep_default_na=False)
        except Exception as exc:  # pragma: no cover - defensive, surfaced in error message
            errors.append(f"{encoding}/{delimiter_name(delimiter)}: {exc}")
            continue
        if len(frame.columns) == 1 and delimiter != "\t":
            # Try tab as a safe fallback if delimiter count was misleading.
            try:
                tab_frame = pd.read_csv(io.StringIO(text), sep="\t", dtype=str, keep_default_na=False)
                if len(tab_frame.columns) > len(frame.columns):
                    frame = tab_frame
                    delimiter = "\t"
            except Exception:
                pass
        return RawFileRead(file_path, frame, encoding, delimiter)
    raise UnicodeDecodeError("human_trade_import", raw, 0, len(raw), "failed decoding attempts: " + "; ".join(errors))


def detect_delimiter(text: str, path: Path) -> str:
    if path.suffix.lower() == ".tsv":
        return "\t"
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    if not first_line:
        return ","
    counts = {delimiter: first_line.count(delimiter) for delimiter in DELIMITERS}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def delimiter_name(delimiter: str) -> str:
    return "tab" if delimiter == "\t" else delimiter


def build_column_mapping(columns: list[str] | pd.Index) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for column in columns:
        normalized, method, confidence, notes = map_column(column)
        rows.append(
            {
                "input_file": "",
                "original_column_name": str(column),
                "normalized_column_name": normalized,
                "match_method": method,
                "confidence": confidence,
                "notes": notes,
            }
        )
    return pd.DataFrame(rows, columns=mapping_columns())


def mapping_columns() -> list[str]:
    return ["input_file", "original_column_name", "normalized_column_name", "match_method", "confidence", "notes"]


def map_column(column: str) -> tuple[str, str, str, str]:
    text = str(column).strip()
    compact = compact_name(text)
    for target in HUMAN_TRADE_FIELDS + SOURCE_OPTIONAL_COLUMNS + ["deal_entry_marker", "commission_optional", "swap_optional"]:
        if text == target:
            return target, "exact", "high", ""
        if text.lower() == target.lower():
            return target, "case_insensitive", "high", ""
    for target, names in SYNONYMS.items():
        for name in names:
            if compact == compact_name(name):
                return target, "synonym", "high", f"matched synonym {name}"
    if "open" in compact and "time" in compact:
        return "open_time", "heuristic", "medium", "contains open/time"
    if "close" in compact and "time" in compact:
        return "close_time", "heuristic", "medium", "contains close/time"
    if "price" in compact and "open" in compact:
        return "entry_price", "heuristic", "medium", "contains open/price"
    if "price" in compact and "close" in compact:
        return "exit_price", "heuristic", "medium", "contains close/price"
    return "", "unmapped", "low", ""


def compact_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def apply_column_mapping(frame: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    output = pd.DataFrame(index=frame.index)
    for _, row in mapping.iterrows():
        target = str(row["normalized_column_name"])
        if not target:
            continue
        source = str(row["original_column_name"])
        if target not in output.columns:
            output[target] = frame[source]
    output["_raw_payload"] = frame.apply(lambda raw: json.dumps(raw.to_dict(), sort_keys=True, ensure_ascii=False), axis=1)
    output["_source_row_number"] = range(1, len(frame) + 1)
    return output


def detect_export_granularity(mapped: pd.DataFrame) -> str:
    if "deal_entry_marker" in mapped.columns:
        if "source_position_id_optional" in mapped.columns:
            return "DEAL_LEVEL_GROUPED"
        return "DEAL_LEVEL_UNSUPPORTED"
    required_position_columns = {"open_time", "entry_price", "symbol", "direction"}
    if required_position_columns.issubset(mapped.columns):
        return "POSITION_LEVEL"
    return "UNKNOWN"


def normalize_mapped_frame(
    mapped: pd.DataFrame,
    *,
    input_file: Path,
    granularity: str,
    decimal_separator: str,
    symbol_filter: str,
    strategy_tag_filter: str | None,
    timezone_assumption: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    if granularity == "DEAL_LEVEL_GROUPED":
        return normalize_deal_level_groups(
            mapped,
            input_file=input_file,
            decimal_separator=decimal_separator,
            symbol_filter=symbol_filter,
            strategy_tag_filter=strategy_tag_filter,
            timezone_assumption=timezone_assumption,
        )
    if granularity == "DEAL_LEVEL_UNSUPPORTED":
        errors = [
            error_row(input_file, row, "DEAL_LEVEL_GROUPING_UNSUPPORTED", "deal-level export lacks reliable Position ID grouping")
            for _, row in mapped.iterrows()
        ]
        return pd.DataFrame(columns=NORMALIZED_COLUMNS), errors
    return normalize_position_rows(
        mapped,
        input_file=input_file,
        decimal_separator=decimal_separator,
        symbol_filter=symbol_filter,
        strategy_tag_filter=strategy_tag_filter,
        timezone_assumption=timezone_assumption,
    )


def normalize_position_rows(
    mapped: pd.DataFrame,
    *,
    input_file: Path,
    decimal_separator: str,
    symbol_filter: str,
    strategy_tag_filter: str | None,
    timezone_assumption: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for _, raw in mapped.iterrows():
        normalized, error = normalize_trade_row(
            raw,
            input_file=input_file,
            decimal_separator=decimal_separator,
            symbol_filter=symbol_filter,
            strategy_tag_filter=strategy_tag_filter,
            timezone_assumption=timezone_assumption,
        )
        if error:
            errors.append(error)
        elif normalized:
            rows.append(normalized)
    return pd.DataFrame(rows, columns=NORMALIZED_COLUMNS), errors


def normalize_deal_level_groups(
    mapped: pd.DataFrame,
    *,
    input_file: Path,
    decimal_separator: str,
    symbol_filter: str,
    strategy_tag_filter: str | None,
    timezone_assumption: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for position_id, group in mapped.groupby("source_position_id_optional", dropna=False):
        position_text = str(position_id).strip()
        if not position_text:
            for _, raw in group.iterrows():
                errors.append(error_row(input_file, raw, "DEAL_LEVEL_GROUPING_UNSUPPORTED", "missing Position ID"))
            continue
        entry_rows = group[group["deal_entry_marker"].astype(str).str.upper().isin({"IN", "INOUT"})].copy()
        exit_rows = group[group["deal_entry_marker"].astype(str).str.upper().eq("OUT")].copy()
        if len(entry_rows) != 1 or len(exit_rows) != 1:
            errors.append(
                {
                    "input_file": str(input_file),
                    "source_row_optional": ";".join(group["_source_row_number"].astype(str).tolist()),
                    "source_position_id_optional": position_text,
                    "human_trade_id": "",
                    "error_code": "AMBIGUOUS_DEAL_GROUP",
                    "error_message": "deal group does not have exactly one IN and one OUT row",
                    "raw_payload": "[" + ",".join(group["_raw_payload"].astype(str).tolist()) + "]",
                }
            )
            continue
        entry = entry_rows.iloc[0].copy()
        exit_row = exit_rows.iloc[0].copy()
        combined = entry.copy()
        combined["close_time"] = exit_row.get("open_time", "")
        combined["exit_price"] = exit_row.get("entry_price", "")
        combined["source_position_id_optional"] = position_text
        combined["source_row_optional"] = ";".join(group["_source_row_number"].astype(str).tolist())
        combined["_raw_payload"] = "[" + ",".join(group["_raw_payload"].astype(str).tolist()) + "]"
        result_values = [
            parse_number(value, decimal_separator=decimal_separator)[0]
            for value in [
                *group.get("result_optional", pd.Series(dtype=str)).tolist(),
                *group.get("commission_optional", pd.Series(dtype=str)).tolist(),
                *group.get("swap_optional", pd.Series(dtype=str)).tolist(),
            ]
        ]
        numeric_result = sum(value for value in result_values if value is not None)
        combined["result_optional"] = _format_number(numeric_result) if result_values else ""
        normalized, error = normalize_trade_row(
            combined,
            input_file=input_file,
            decimal_separator=decimal_separator,
            symbol_filter=symbol_filter,
            strategy_tag_filter=strategy_tag_filter,
            timezone_assumption=timezone_assumption,
            export_granularity="DEAL_LEVEL_GROUPED",
        )
        if error:
            errors.append(error)
        elif normalized:
            rows.append(normalized)
    return pd.DataFrame(rows, columns=NORMALIZED_COLUMNS), errors


def normalize_trade_row(
    raw: pd.Series,
    *,
    input_file: Path,
    decimal_separator: str,
    symbol_filter: str,
    strategy_tag_filter: str | None,
    timezone_assumption: str,
    export_granularity: str = "POSITION_LEVEL",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    warnings: list[str] = []
    symbol_raw = _clean(raw.get("symbol"))
    symbol = normalize_symbol(symbol_raw)
    direction = normalize_direction(raw.get("direction"))
    entry_price, entry_error = parse_number(raw.get("entry_price"), decimal_separator=decimal_separator)
    optional_numbers = {}
    for field in ["exit_price", "stop_loss", "take_profit", "volume", "result_optional"]:
        value, error = parse_number(raw.get(field), decimal_separator=decimal_separator, allow_blank=True)
        optional_numbers[field] = value
        if error:
            warnings.append(f"{field}:{error}")
    open_raw = _clean(raw.get("open_time"))
    close_raw = _clean(raw.get("close_time"))
    open_normalized = normalize_timestamp(open_raw)
    close_normalized = normalize_timestamp(close_raw)
    strategy_tag = _clean(raw.get("strategy_tag_optional"))
    if strategy_tag_filter and strategy_tag.lower() != strategy_tag_filter.lower():
        return None, error_row(input_file, raw, "STRATEGY_TAG_FILTER_EXCLUDED", "strategy tag does not match filter")
    if symbol_filter and symbol and symbol != symbol_filter:
        return None, error_row(input_file, raw, "SYMBOL_FILTER_EXCLUDED", f"symbol {symbol} does not match {symbol_filter}")

    errors: list[str] = []
    if not symbol:
        errors.append("MISSING_OR_UNKNOWN_SYMBOL")
    if not direction:
        errors.append("MISSING_OR_UNKNOWN_DIRECTION")
    if not open_raw or not open_normalized:
        errors.append("MISSING_OR_INVALID_OPEN_TIME")
    if entry_price is None:
        errors.append(entry_error or "MISSING_OR_INVALID_ENTRY_PRICE")
    if errors:
        return None, error_row(input_file, raw, ";".join(errors), "critical required field validation failed")

    for optional_field, warning_code in [
        ("close_time", "MISSING_CLOSE_TIME"),
        ("exit_price", "MISSING_EXIT_PRICE"),
        ("stop_loss", "MISSING_STOP_LOSS"),
        ("take_profit", "MISSING_TAKE_PROFIT"),
        ("volume", "MISSING_VOLUME"),
        ("notes", "MISSING_NOTES"),
    ]:
        if optional_field == "close_time":
            missing = not close_raw
        elif optional_field in optional_numbers:
            missing = optional_numbers[optional_field] is None
        else:
            missing = not _clean(raw.get(optional_field))
        if missing:
            warnings.append(warning_code)
    if timezone_assumption.lower().startswith("broker/server"):
        warnings.append("UNKNOWN_TIMEZONE")
    if not strategy_tag:
        warnings.append("STRATEGY_TAG_BLANK")

    trade_id, id_warning = build_human_trade_id(raw, symbol=symbol, direction=direction, entry_price=entry_price, source=input_file.stem)
    if id_warning:
        warnings.append(id_warning)
    return {
        "human_trade_id": trade_id,
        "source": input_file.stem,
        "symbol": symbol,
        "direction": direction,
        "open_time": open_normalized,
        "close_time": close_normalized,
        "entry_price": _format_number(entry_price),
        "exit_price": _format_optional_number(optional_numbers["exit_price"]),
        "stop_loss": _format_optional_number(optional_numbers["stop_loss"]),
        "take_profit": _format_optional_number(optional_numbers["take_profit"]),
        "volume": _format_optional_number(optional_numbers["volume"]),
        "result_optional": _format_optional_number(optional_numbers["result_optional"]),
        "screenshot_path_optional": _clean(raw.get("screenshot_path_optional")),
        "notes": _clean(raw.get("notes")),
        "strategy_tag_optional": strategy_tag,
        "source_file_optional": str(input_file),
        "source_row_optional": _clean(raw.get("source_row_optional")) or _clean(raw.get("_source_row_number")),
        "source_ticket_optional": _clean(raw.get("source_ticket_optional")),
        "source_order_id_optional": _clean(raw.get("source_order_id_optional")),
        "source_position_id_optional": _clean(raw.get("source_position_id_optional")),
        "open_time_raw": open_raw,
        "close_time_raw": close_raw,
        "open_time_normalized": open_normalized,
        "close_time_normalized": close_normalized,
        "timezone_assumption": timezone_assumption,
        "import_warning_flags": ";".join(sorted(set(warnings))),
    }, None


def normalize_symbol(value: str) -> str:
    text = str(value).strip().upper()
    if not text:
        return ""
    return SYMBOL_VARIANTS.get(text, "")


def normalize_direction(value: Any) -> str:
    text = str(value).strip().upper()
    if text in {"BUY", "LONG"}:
        return "LONG"
    if text in {"SELL", "SHORT"}:
        return "SHORT"
    return ""


def parse_number(value: Any, *, decimal_separator: str = "auto", allow_blank: bool = False) -> tuple[float | None, str]:
    text = _clean(value)
    if not text:
        return None, "" if allow_blank else "MISSING_NUMERIC_VALUE"
    text = text.replace(" ", "").replace("\u00a0", "")
    if decimal_separator == "dot":
        candidate = text.replace(",", "")
    elif decimal_separator == "comma":
        candidate = text.replace(".", "").replace(",", ".")
    else:
        candidate, error = normalize_auto_number_text(text)
        if error:
            return None, error
    try:
        return float(candidate), ""
    except ValueError:
        return None, "UNPARSEABLE_NUMERIC_VALUE"


def normalize_auto_number_text(text: str) -> tuple[str, str]:
    has_dot = "." in text
    has_comma = "," in text
    if has_dot and has_comma:
        if text.rfind(",") > text.rfind("."):
            return text.replace(".", "").replace(",", "."), ""
        return text.replace(",", ""), ""
    if has_comma:
        parts = text.split(",")
        if len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 3:
            return "", "AMBIGUOUS_NUMERIC_FORMAT"
        return text.replace(",", "."), ""
    if has_dot:
        return text, ""
    return text, ""


def normalize_timestamp(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    parsed = pd.to_datetime(text, errors="coerce", dayfirst=False)
    if pd.isna(parsed):
        parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return ""
    return parsed.isoformat()


def build_human_trade_id(raw: pd.Series, *, symbol: str, direction: str, entry_price: float, source: str) -> tuple[str, str]:
    position_id = _clean(raw.get("source_position_id_optional"))
    ticket = _clean(raw.get("source_ticket_optional"))
    order = _clean(raw.get("source_order_id_optional"))
    source_clean = re.sub(r"[^A-Za-z0-9]+", "_", source).strip("_").upper() or "IMPORT"
    if position_id:
        return f"HUMAN_{source_clean}_{position_id}", ""
    if ticket:
        return f"HUMAN_{source_clean}_{ticket}", ""
    if order:
        return f"HUMAN_{source_clean}_{order}", ""
    seed_parts = [
        symbol,
        direction,
        _clean(raw.get("open_time")),
        _format_number(entry_price),
        _clean(raw.get("volume")),
    ]
    digest = hashlib.sha1("|".join(seed_parts).encode("utf-8")).hexdigest()[:12].upper()
    return f"HUMAN_{source_clean}_{digest}", ""


def error_row(input_file: Path, raw: pd.Series, code: str, message: str) -> dict[str, Any]:
    return {
        "input_file": str(input_file),
        "source_row_optional": _clean(raw.get("source_row_optional")) or _clean(raw.get("_source_row_number")),
        "source_position_id_optional": _clean(raw.get("source_position_id_optional")),
        "human_trade_id": "",
        "error_code": code,
        "error_message": message,
        "raw_payload": _clean(raw.get("_raw_payload")) or json.dumps(raw.to_dict(), sort_keys=True, default=str),
    }


def deduplicate_normalized(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int], list[dict[str, Any]]]:
    if frame.empty:
        return frame, {"duplicates_detected": 0, "duplicates_dropped_exact": 0, "conflicting_duplicate_ids": 0}, []
    output_rows: list[pd.Series] = []
    errors: list[dict[str, Any]] = []
    duplicates_detected = 0
    duplicates_dropped_exact = 0
    conflicts = 0
    for trade_id, group in frame.groupby("human_trade_id", sort=False):
        if len(group) == 1:
            output_rows.append(group.iloc[0])
            continue
        duplicates_detected += len(group) - 1
        comparable = group[NORMALIZED_COLUMNS].drop(columns=["source_file_optional", "source_row_optional"], errors="ignore").astype(str)
        if comparable.drop_duplicates().shape[0] == 1:
            duplicates_dropped_exact += len(group) - 1
            output_rows.append(group.iloc[0])
            continue
        conflicts += 1
        errors.append(
            {
                "input_file": ";".join(group["source_file_optional"].astype(str).tolist()),
                "source_row_optional": ";".join(group["source_row_optional"].astype(str).tolist()),
                "source_position_id_optional": ";".join(group["source_position_id_optional"].astype(str).tolist()),
                "human_trade_id": trade_id,
                "error_code": "DUPLICATE_HUMAN_TRADE_ID_CONFLICT",
                "error_message": "duplicate human_trade_id has conflicting row content",
                "raw_payload": group.to_json(orient="records"),
            }
        )
    if conflicts:
        raise ValueError("conflicting duplicate human_trade_id detected; see human_trade_import_errors.csv")
    output = pd.DataFrame(output_rows, columns=frame.columns).reset_index(drop=True)
    return output, {
        "duplicates_detected": duplicates_detected,
        "duplicates_dropped_exact": duplicates_dropped_exact,
        "conflicting_duplicate_ids": conflicts,
    }, errors


def detect_decimal_style(mapped: pd.DataFrame, mode: str) -> str:
    if mode != "auto":
        return mode
    sample_values: list[str] = []
    for column in ["entry_price", "exit_price", "stop_loss", "take_profit", "volume", "result_optional"]:
        if column in mapped.columns:
            sample_values.extend([_clean(value) for value in mapped[column].tolist() if _clean(value)])
    if any("," in value and "." in value and value.rfind(",") > value.rfind(".") for value in sample_values):
        return "comma_decimal_with_thousands"
    if any("," in value and "." not in value for value in sample_values):
        return "comma_decimal"
    if any("," in value and "." in value for value in sample_values):
        return "dot_decimal_with_thousands"
    return "dot_decimal_or_integer"


def write_import_outputs(result: ImportResult, output_dir: str | Path = DEFAULT_OUTPUT_DIR, *, overwrite: bool = True) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    validate_overwrite(output, overwrite=overwrite)
    paths = {
        "normalized_csv": output / NORMALIZED_OUTPUT,
        "summary_json": output / IMPORT_SUMMARY,
        "column_mapping_csv": output / COLUMN_MAPPING_AUDIT,
        "readme_md": output / IMPORT_README,
    }
    result.normalized.to_csv(paths["normalized_csv"], index=False)
    result.summary["output_files"] = {key: str(path) for key, path in paths.items()}
    paths["summary_json"].write_text(json.dumps(result.summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    result.column_mapping.to_csv(paths["column_mapping_csv"], index=False)
    paths["readme_md"].write_text(result.readme_markdown, encoding="utf-8")
    if not result.errors.empty:
        paths["errors_csv"] = output / IMPORT_ERRORS
        result.errors.to_csv(paths["errors_csv"], index=False)
    return {key: str(path) for key, path in paths.items()}


def render_import_readme(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Strategy 2 Human Trade Import Normalizer",
            "",
            "This importer converts raw MT5/broker history exports into `human_trades_filled_normalized.csv` for Strategy 2 human-trade alignment.",
            "",
            "It does not run Layer B, run alignment, generate signals, optimize, or make performance claims.",
            "",
            "## Input Folder",
            "",
            "`backtests/reports/strategy_2_human_trade_alignment/raw_human_trade_exports`",
            "",
            "Place real MT5/broker export files there, or pass a single file with `--input`.",
            "",
            "## Current Import Summary",
            "",
            f"- Files processed: {len(summary['files_processed'])}",
            f"- Rows loaded: {summary['rows_loaded_total']}",
            f"- Rows valid: {summary['rows_valid']}",
            f"- Rows invalid: {summary['rows_invalid']}",
            f"- Alignment metrics generated: {summary['alignment_metrics_generated']}",
            "",
            "Unmatched, losing, BE, and ugly trades must remain in the import if they are valid export rows. Do not filter to winners.",
        ]
    ) + "\n"


def _format_number(value: float) -> str:
    return f"{float(value):.10f}".rstrip("0").rstrip(".")


def _format_optional_number(value: float | None) -> str:
    return "" if value is None else _format_number(value)


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()
