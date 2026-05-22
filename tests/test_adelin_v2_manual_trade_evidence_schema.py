from __future__ import annotations

import csv
import importlib
import json
from pathlib import Path

from scripts.validate_adelin_v2_manual_trade_evidence import (
    validate_file,
    validate_rows,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "backtests/reports/adelin_v2_manual_trade_evidence_schema"
SCHEMA_PATH = OUTPUT_DIR / "manual_trade_evidence_schema.json"
TEMPLATE_PATH = OUTPUT_DIR / "manual_trade_evidence_template.csv"
EXAMPLE_PATH = OUTPUT_DIR / "manual_trade_evidence_example_rows.csv"
SUMMARY_PATH = OUTPUT_DIR / "summary.json"
VALIDATION_SUMMARY_PATH = OUTPUT_DIR / "manual_trade_evidence_validation_summary.json"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _csv_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def test_module_import_is_safe():
    module = importlib.import_module("scripts.validate_adelin_v2_manual_trade_evidence")
    assert hasattr(module, "validate_file")


def test_schema_and_templates_exist():
    assert SCHEMA_PATH.exists()
    assert TEMPLATE_PATH.exists()
    assert EXAMPLE_PATH.exists()
    assert SUMMARY_PATH.exists()


def test_required_columns_exist_in_template():
    schema = _load_json(SCHEMA_PATH)
    fieldnames, _ = _csv_rows(TEMPLATE_PATH)
    required = [field["name"] for field in schema["fields"] if field["required_column"]]
    assert required
    assert all(column in fieldnames for column in required)
    assert "direction" in fieldnames
    assert "result_label" in fieldnames
    assert "confidence_human_label" in fieldnames


def test_example_rows_are_marked_example_only():
    _, rows = _csv_rows(EXAMPLE_PATH)
    assert len(rows) >= 2
    assert all(row["evidence_id"].startswith("EXAMPLE_") for row in rows)
    assert all(row["example_only"] == "true" for row in rows)


def test_blank_template_passes_with_allow_empty(tmp_path: Path):
    output = tmp_path / "validation.json"
    summary = validate_file(TEMPLATE_PATH, SCHEMA_PATH, output, allow_empty=True)
    assert summary["validation_passed"] is True
    assert summary["rows_nonblank"] == 0
    assert output.exists()


def test_invalid_enum_fails():
    schema = _load_json(SCHEMA_PATH)
    fieldnames, rows = _csv_rows(EXAMPLE_PATH)
    bad = dict(rows[0])
    bad["direction"] = "SIDEWAYS"
    summary = validate_rows(fieldnames, [bad], schema, allow_empty=False)
    assert summary["validation_passed"] is False
    assert any(error["type"] == "invalid_enum" and error["column"] == "direction" for error in summary["errors"])


def test_forbidden_validation_claims_are_rejected():
    schema = _load_json(SCHEMA_PATH)
    fieldnames, rows = _csv_rows(EXAMPLE_PATH)
    bad = dict(rows[0])
    bad["human_notes"] = "edge_confirmed"
    summary = validate_rows(fieldnames, [bad], schema, allow_empty=False)
    assert summary["validation_passed"] is False
    assert any(error["type"] == "forbidden_validation_claim" for error in summary["errors"])


def test_duplicate_evidence_id_fails():
    schema = _load_json(SCHEMA_PATH)
    fieldnames, rows = _csv_rows(EXAMPLE_PATH)
    first = dict(rows[0])
    duplicate = dict(rows[1])
    duplicate["evidence_id"] = first["evidence_id"]
    summary = validate_rows(fieldnames, [first, duplicate], schema, allow_empty=False)
    assert summary["validation_passed"] is False
    assert first["evidence_id"] in summary["duplicate_evidence_ids"]


def test_example_rows_missing_marker_fail():
    schema = _load_json(SCHEMA_PATH)
    fieldnames, rows = _csv_rows(EXAMPLE_PATH)
    bad = dict(rows[0])
    bad["example_only"] = "false"
    summary = validate_rows(fieldnames, [bad], schema, allow_empty=False)
    assert summary["validation_passed"] is False
    assert any(error["type"] == "example_row_not_marked_example_only" for error in summary["errors"])


def test_summary_confirms_schema_only_and_safety_flags():
    summary = _load_json(SUMMARY_PATH)
    assert summary["schema_only"] is True
    assert summary["manual_examples_analyzed"] is False
    assert summary["screenshots_auto_labeled"] is False
    assert summary["ohlc_read"] is False
    assert summary["replay_run"] is False
    assert summary["matched_control_replay_run"] is False
    assert summary["phase_4_blocked"] is True
    assert summary["live_trading_enabled"] is False
    assert summary["telegram_enabled"] is False
    assert summary["broker_execution_enabled"] is False
    assert summary["profitability_claim_made"] is False
    assert summary["strategy_validated"] is False


def test_generated_validation_summary_is_safe():
    summary = _load_json(VALIDATION_SUMMARY_PATH)
    assert summary["validation_passed"] is True
    assert summary["schema_only"] is True
    assert summary["ohlc_read"] is False
    assert summary["screenshots_auto_labeled"] is False
    assert summary["replay_run"] is False
    assert summary["matched_control_replay_run"] is False
    assert summary["phase_4_blocked"] is True
