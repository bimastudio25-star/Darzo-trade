"""Validate Adelin v2 manual trade evidence CSV files.

This helper validates human-entered screenshot/manual trade evidence rows. It is
schema-only tooling: it does not read OHLC, run replay, score trades, unlock
Phase 4, or touch runtime trading paths.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_SCHEMA_PATH = Path("backtests/reports/adelin_v2_manual_trade_evidence_schema/manual_trade_evidence_schema.json")
DEFAULT_INPUT_PATH = Path("backtests/reports/adelin_v2_manual_trade_evidence_schema/manual_trade_evidence_template.csv")
DEFAULT_OUTPUT_PATH = Path("backtests/reports/adelin_v2_manual_trade_evidence_schema/manual_trade_evidence_validation_summary.json")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def is_blank_row(row: Mapping[str, Any]) -> bool:
    return all(str(value or "").strip() == "" for value in row.values())


def normalize(value: Any) -> str:
    return str(value or "").strip()


def truthy(value: Any) -> bool:
    return normalize(value).lower() in {"true", "1", "yes", "y"}


def schema_fields(schema: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(schema.get("fields", []))


def required_columns(schema: Mapping[str, Any]) -> list[str]:
    return [field["name"] for field in schema_fields(schema) if field.get("required_column")]


def enum_fields(schema: Mapping[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for field in schema_fields(schema):
        allowed = field.get("allowed_values")
        if allowed:
            out[field["name"]] = {str(item) for item in allowed}
    return out


def row_text(row: Mapping[str, Any]) -> str:
    return " ".join(str(value or "") for value in row.values()).lower()


def required_fields_for_mode(schema: Mapping[str, Any], capture_mode: str) -> list[str]:
    if capture_mode == "RAPID_CAPTURE":
        return list(schema.get("required_minimal_fields", []))
    if capture_mode == "FULL_REVIEW":
        return list(schema.get("required_full_review_fields", []))
    return list(schema.get("required_minimal_fields", []))


def validate_rows(
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, str]],
    schema: Mapping[str, Any],
    allow_empty: bool = False,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    required = required_columns(schema)
    missing_columns = [column for column in required if column not in fieldnames]
    for column in missing_columns:
        errors.append({"type": "missing_required_column", "column": column})

    nonblank_rows = [(index, row) for index, row in enumerate(rows, start=2) if not is_blank_row(row)]
    if not nonblank_rows and not allow_empty:
        errors.append({"type": "empty_input_without_allow_empty"})

    enums = enum_fields(schema)
    ids: Counter[str] = Counter()
    forbidden_terms = [str(term).lower() for term in schema.get("forbidden_claim_terms", [])]
    forbidden_hits: list[dict[str, Any]] = []
    example_rows_checked = 0
    example_rows_missing_marker = 0

    full_review_fields = list(schema.get("required_full_review_fields", []))
    minimal_fields = list(schema.get("required_minimal_fields", []))

    for row_number, row in nonblank_rows:
        evidence_id = normalize(row.get("evidence_id"))
        if evidence_id:
            ids[evidence_id] += 1
        capture_mode = normalize(row.get("capture_mode"))
        mode_required = required_fields_for_mode(schema, capture_mode)
        if not capture_mode:
            errors.append({"type": "missing_capture_mode", "row": row_number})
        for column in mode_required:
            if normalize(row.get(column)) == "":
                errors.append({"type": "missing_required_value", "row": row_number, "column": column, "capture_mode": capture_mode or "MISSING"})

        if capture_mode == "RAPID_CAPTURE":
            missing_full_review = [
                column
                for column in full_review_fields
                if column not in minimal_fields and normalize(row.get(column)) == ""
            ]
            if missing_full_review:
                warnings.append(
                    {
                        "type": "rapid_capture_missing_full_review_fields",
                        "row": row_number,
                        "missing_fields": missing_full_review,
                    }
                )

        screenshot_path = normalize(row.get("screenshot_path"))
        if not screenshot_path:
            errors.append({"type": "missing_screenshot_path", "row": row_number})

        for column, allowed in enums.items():
            value = normalize(row.get(column))
            if value and value not in allowed:
                errors.append({"type": "invalid_enum", "row": row_number, "column": column, "value": value, "allowed": sorted(allowed)})

        confidence = normalize(row.get("confidence_human_label"))
        if confidence and confidence not in {"0", "1", "2", "3"}:
            errors.append({"type": "invalid_confidence_human_label", "row": row_number, "value": normalize(row.get("confidence_human_label"))})

        lower_text = row_text(row)
        for term in forbidden_terms:
            if term in lower_text:
                forbidden_hits.append({"row": row_number, "term": term})

        if evidence_id.startswith("EXAMPLE_"):
            example_rows_checked += 1
            if not truthy(row.get("example_only")):
                example_rows_missing_marker += 1
                errors.append({"type": "example_row_not_marked_example_only", "row": row_number, "evidence_id": evidence_id})

    duplicate_ids = sorted([item for item, count in ids.items() if count > 1])
    for evidence_id in duplicate_ids:
        errors.append({"type": "duplicate_evidence_id", "evidence_id": evidence_id})

    for hit in forbidden_hits:
        errors.append({"type": "forbidden_validation_claim", **hit})

    quality_counts = Counter(normalize(row.get("evidence_quality")) for _, row in nonblank_rows if normalize(row.get("evidence_quality")))
    result_label_counts = Counter(normalize(row.get("result_label")) for _, row in nonblank_rows if normalize(row.get("result_label")))
    capture_mode_counts = Counter(normalize(row.get("capture_mode")) for _, row in nonblank_rows if normalize(row.get("capture_mode")))

    return {
        "validation_passed": not errors,
        "schema_only": True,
        "rows_total": len(rows),
        "rows_nonblank": len(nonblank_rows),
        "allow_empty": allow_empty,
        "required_columns_count": len(required),
        "required_minimal_fields": minimal_fields,
        "required_full_review_fields": full_review_fields,
        "missing_required_columns": missing_columns,
        "errors": errors,
        "warnings": warnings,
        "duplicate_evidence_ids": duplicate_ids,
        "forbidden_validation_claims_found": forbidden_hits,
        "example_rows_checked": example_rows_checked,
        "example_rows_missing_marker": example_rows_missing_marker,
        "evidence_quality_counts": dict(quality_counts),
        "result_label_counts": dict(result_label_counts),
        "capture_mode_counts": dict(capture_mode_counts),
        "ohlc_read": False,
        "screenshots_auto_labeled": False,
        "replay_run": False,
        "matched_control_replay_run": False,
        "phase_4_blocked": True,
        "live_trading_enabled": False,
        "telegram_enabled": False,
        "broker_execution_enabled": False,
        "profitability_claim_made": False,
        "strategy_validated": False,
    }


def validate_file(input_path: Path, schema_path: Path, output_path: Path | None = None, allow_empty: bool = False) -> dict[str, Any]:
    schema = read_json(schema_path)
    fieldnames, rows = read_csv(input_path)
    summary = validate_rows(fieldnames, rows, schema, allow_empty=allow_empty)
    summary["input_path"] = str(input_path)
    summary["schema_path"] = str(schema_path)
    if output_path:
        write_json(output_path, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--schema-path", type=Path, default=DEFAULT_SCHEMA_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--allow-empty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = validate_file(args.input_path, args.schema_path, args.output_path, allow_empty=args.allow_empty)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
