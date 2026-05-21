from __future__ import annotations

import csv
import importlib
import json
from pathlib import Path

from scripts.validate_adelin_v2_phase_3_labels import (
    DEFAULT_SPECS_PATH,
    build_blank_template_rows,
    build_phase_3_schema,
    load_feature_specs,
    validate_label_rows,
    validate_labels_file,
    write_json,
    write_label_template,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_import_is_safe():
    module = importlib.import_module("scripts.validate_adelin_v2_phase_3_labels")
    assert hasattr(module, "validate_labels_file")
    assert hasattr(module, "write_phase_3_outputs")


def test_feature_spec_role_parsing_counts():
    specs = load_feature_specs(DEFAULT_SPECS_PATH)
    assert len(specs) == 10
    assert sum(spec["role"] == "PRIMARY_TEST" for spec in specs) == 9
    assert sum(spec["role"] == "STRATIFICATION_METADATA_ONLY" for spec in specs) == 1


def test_spec_005_is_excluded_from_primary_label_groups():
    specs = load_feature_specs(DEFAULT_SPECS_PATH)
    schema = build_phase_3_schema(specs)
    primary_ids = [group["test_id"] for group in schema.primary_feature_fields]
    assert "005" not in primary_ids
    assert not any(column.startswith("feature_005_") for column in schema.required_columns)
    assert "metadata_005_tight_numeric_level_touch_band" in schema.required_columns


def test_schema_generation_has_global_and_feature_fields_without_outcomes():
    specs = load_feature_specs(DEFAULT_SPECS_PATH)
    schema = build_phase_3_schema(specs)
    columns = schema.required_columns

    for required in [
        "sample_id",
        "reviewer",
        "review_date",
        "overall_reviewable",
        "pre_entry_only_confirmed",
        "leakage_risk_detected",
        "exclude_from_phase_4",
    ]:
        assert required in columns

    assert schema.schema["primary_test_count"] == 9
    assert schema.schema["stratification_metadata_spec_count"] == 1
    forbidden = {"outcome", "pnl", "r_multiple", "tp_hit", "sl_hit", "win_loss", "future_return"}
    lowered = {column.lower() for column in columns}
    assert forbidden.isdisjoint(lowered)


def test_validator_rejects_forbidden_outcome_columns(tmp_path: Path):
    specs = load_feature_specs(DEFAULT_SPECS_PATH)
    schema = build_phase_3_schema(specs)
    schema_path = tmp_path / "schema.json"
    labels_path = tmp_path / "labels.csv"
    output_path = tmp_path / "summary.json"
    write_json(schema_path, schema.schema)

    fieldnames = schema.required_columns + ["pnl"]
    with labels_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({column: "" for column in fieldnames})

    summary = validate_labels_file(labels_path, schema_path, output_path, allow_empty=True)
    assert summary["valid"] is False
    assert "FORBIDDEN_OUTCOME_COLUMNS_PRESENT" in summary["errors"]
    assert "pnl" in summary["forbidden_outcome_columns"]


def test_validator_rejects_invalid_enum_values():
    specs = load_feature_specs(DEFAULT_SPECS_PATH)
    schema = build_phase_3_schema(specs)
    row = {column: "" for column in schema.required_columns}
    row["overall_reviewable"] = "MAYBE"
    summary = validate_label_rows([row], schema.required_columns, schema, allow_empty=True)
    assert summary["valid"] is False
    assert "INVALID_ENUM_VALUES" in summary["errors"]


def test_blank_template_passes_with_allow_empty(tmp_path: Path):
    specs = load_feature_specs(DEFAULT_SPECS_PATH)
    schema = build_phase_3_schema(specs)
    schema_path = tmp_path / "schema.json"
    labels_path = tmp_path / "labels.csv"
    output_path = tmp_path / "summary.json"
    write_json(schema_path, schema.schema)

    rows = build_blank_template_rows(
        schema,
        [
            {
                "sample_id": "sample_001",
                "source_mode": "CANDIDATE_WINDOW_MODE",
                "symbol": "XAUUSD",
                "anchor_timestamp": "2026-05-19T17:15:00+00:00",
                "chart_path": "charts/sample_001.svg",
                "html_path": "examples/sample_001.html",
            }
        ],
    )
    write_label_template(labels_path, schema, rows)

    summary = validate_labels_file(labels_path, schema_path, output_path, allow_empty=True)
    assert summary["valid"] is True
    assert summary["total_rows"] == 1
    assert summary["completed_rows"] == 0
    assert summary["incomplete_rows"] == 1


def test_generated_phase_3_outputs_are_valid():
    output_dir = REPO_ROOT / "backtests" / "reports" / "adelin_v2_phase_3_visual_review_labels"
    schema = json.loads((output_dir / "phase_3_label_schema.json").read_text(encoding="utf-8"))
    validation = json.loads(
        (output_dir / "manual_labels_validation_summary.json").read_text(encoding="utf-8")
    )
    summary = json.loads((output_dir / "phase_3_summary.json").read_text(encoding="utf-8"))

    assert schema["total_specs"] == 10
    assert schema["primary_test_count"] == 9
    assert schema["stratification_metadata_spec_count"] == 1
    assert validation["valid"] is True
    assert validation["primary_feature_group_count"] == 9
    assert validation["spec_005_primary_columns"] == []
    assert summary["visual_review_pack_found"] is True
    assert summary["sample_rows_loaded_from_visual_pack"] == 40
    assert summary["spec_005_excluded_from_primary_labels"] is True
