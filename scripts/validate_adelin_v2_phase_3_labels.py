"""Validate Adelin v2 Phase 3 manual visual review labels.

This script is research/planning infrastructure only. It validates a manual
label CSV against a schema generated from the pre-registered Phase 2 feature
specs. It does not import or execute Adelin detectors, strategy runtime,
broker/order code, or Telegram code.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_SPECS_PATH = Path(
    "backtests/reports/adelin_v2_pre_registered_context_feature_test_plan/feature_test_specs.json"
)
DEFAULT_VISUAL_TEMPLATE_PATH = Path(
    "backtests/reports/adelin_v2_visual_review_pack/manual_labels_template.csv"
)
DEFAULT_OUTPUT_DIR = Path("backtests/reports/adelin_v2_phase_3_visual_review_labels")
DEFAULT_SCHEMA_PATH = DEFAULT_OUTPUT_DIR / "phase_3_label_schema.json"
DEFAULT_TEMPLATE_PATH = DEFAULT_OUTPUT_DIR / "manual_labels_template.csv"
DEFAULT_VALIDATION_SUMMARY_PATH = DEFAULT_OUTPUT_DIR / "manual_labels_validation_summary.json"
DEFAULT_PHASE_3_SUMMARY_PATH = DEFAULT_OUTPUT_DIR / "phase_3_summary.json"

VISIBLE_VALUES = {"", "YES", "NO", "UNCLEAR", "NOT_VISIBLE"}
LABEL_VALUES = {"", "PRESENT", "ABSENT", "UNCLEAR", "NOT_APPLICABLE"}
CONFIDENCE_VALUES = {"", "0", "1", "2", "3"}
YES_NO_UNCLEAR = {"", "YES", "NO", "UNCLEAR"}
YES_NO = {"", "YES", "NO"}
TIGHT_BAND_VALUES = {"", "0-10_PIPS", "10-20_PIPS", "GT_20_PIPS", "UNCLEAR", "NOT_APPLICABLE"}

FORBIDDEN_OUTCOME_COLUMNS = {
    "outcome",
    "outcome_r",
    "pnl",
    "pnl_usd",
    "r_multiple",
    "tp_hit",
    "sl_hit",
    "result",
    "win_loss",
    "future_return",
    "future_mfe",
    "future_mae",
    "mfe",
    "mae",
}

GLOBAL_IDENTITY_FIELDS = [
    "sample_id",
    "candidate_id",
    "source_mode",
    "symbol",
    "candidate_timestamp",
    "decision_timestamp",
    "anchor_timeframe",
    "chart_path",
    "chart_url",
    "index_anchor",
    "execution_data_status",
    "m1_candles_count",
    "m5_candles_count",
    "m15_candles_count",
    "reviewer",
    "review_date",
]

GLOBAL_REVIEW_FIELDS = [
    "overall_reviewable",
    "pre_entry_only_confirmed",
    "leakage_risk_detected",
    "exclude_from_phase_4",
    "exclude_reason",
    "reviewer_notes",
]


@dataclass(frozen=True)
class Phase3Schema:
    schema: dict[str, Any]

    @property
    def required_columns(self) -> list[str]:
        return list(self.schema["required_columns"])

    @property
    def enum_columns(self) -> dict[str, list[str]]:
        return dict(self.schema["enum_columns"])

    @property
    def primary_feature_fields(self) -> list[dict[str, Any]]:
        return list(self.schema["primary_feature_fields"])


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip()).strip("_").lower()
    return cleaned or "unknown"


def load_feature_specs(specs_path: Path | str = DEFAULT_SPECS_PATH) -> list[dict[str, Any]]:
    payload = json.loads(Path(specs_path).read_text(encoding="utf-8"))
    specs = list(payload["feature_test_specs"])
    total = len(specs)
    primary = sum(1 for spec in specs if spec.get("role") == "PRIMARY_TEST")
    strat = sum(1 for spec in specs if spec.get("role") == "STRATIFICATION_METADATA_ONLY")
    if total != 10 or primary != 9 or strat != 1:
        raise ValueError(
            f"Expected 10 total specs, 9 PRIMARY_TEST, 1 STRATIFICATION_METADATA_ONLY; "
            f"got total={total}, primary={primary}, stratification={strat}"
        )
    spec_005 = next((spec for spec in specs if str(spec.get("test_id")) == "005"), None)
    if not spec_005 or spec_005.get("role") != "STRATIFICATION_METADATA_ONLY":
        raise ValueError("Spec 005 must be STRATIFICATION_METADATA_ONLY")
    return specs


def _feature_field_group(spec: Mapping[str, Any]) -> dict[str, Any]:
    test_id = safe_name(str(spec["test_id"]))
    feature_name = safe_name(str(spec["feature_name"]))
    prefix = f"feature_{test_id}_{feature_name}"
    return {
        "test_id": spec["test_id"],
        "feature_name": spec["feature_name"],
        "concept_name": spec["concept_name"],
        "prefix": prefix,
        "visible_pre_entry": f"{prefix}_visible_pre_entry",
        "label": f"{prefix}_label",
        "confidence": f"{prefix}_confidence",
        "notes": f"{prefix}_notes",
    }


def build_phase_3_schema(specs: Sequence[Mapping[str, Any]]) -> Phase3Schema:
    primary_specs = [spec for spec in specs if spec.get("role") == "PRIMARY_TEST"]
    strat_specs = [spec for spec in specs if spec.get("role") == "STRATIFICATION_METADATA_ONLY"]
    if len(primary_specs) != 9 or len(strat_specs) != 1:
        raise ValueError("Phase 3 schema requires 9 primary specs and 1 stratification spec")

    feature_groups = [_feature_field_group(spec) for spec in primary_specs]
    primary_columns: list[str] = []
    enum_columns: dict[str, list[str]] = {
        "overall_reviewable": sorted(YES_NO_UNCLEAR - {""}),
        "pre_entry_only_confirmed": sorted(YES_NO - {""}),
        "leakage_risk_detected": sorted(YES_NO_UNCLEAR - {""}),
        "exclude_from_phase_4": sorted(YES_NO - {""}),
    }

    for group in feature_groups:
        primary_columns.extend(
            [group["visible_pre_entry"], group["label"], group["confidence"], group["notes"]]
        )
        enum_columns[group["visible_pre_entry"]] = sorted(VISIBLE_VALUES - {""})
        enum_columns[group["label"]] = sorted(LABEL_VALUES - {""})
        enum_columns[group["confidence"]] = ["0", "1", "2", "3"]

    metadata_columns = [
        "metadata_005_tight_numeric_level_touch_band",
        "metadata_005_tight_numeric_level_touch_band_notes",
    ]
    enum_columns["metadata_005_tight_numeric_level_touch_band"] = sorted(
        TIGHT_BAND_VALUES - {""}
    )

    required_columns = GLOBAL_IDENTITY_FIELDS + GLOBAL_REVIEW_FIELDS + primary_columns + metadata_columns

    forbidden_present = [
        column for column in required_columns if column.lower() in FORBIDDEN_OUTCOME_COLUMNS
    ]
    if forbidden_present:
        raise ValueError(f"Schema includes forbidden outcome columns: {forbidden_present}")

    return Phase3Schema(
        {
            "schema_name": "ADELIN_V2_PHASE_3_VISUAL_REVIEW_LABEL_SCHEMA",
            "schema_version": 1,
            "planning_only": True,
            "labeling_purpose": "Manual pre-entry visual recognizability labels for primary Phase 2 features.",
            "total_specs": len(specs),
            "primary_test_count": len(primary_specs),
            "stratification_metadata_spec_count": len(strat_specs),
            "primary_feature_fields": feature_groups,
            "stratification_metadata_fields": [
                {
                    "test_id": "005",
                    "feature_name": "tight_numeric_level_touch_band",
                    "role": "STRATIFICATION_METADATA_ONLY",
                    "columns": metadata_columns,
                    "allowed_band_values": sorted(TIGHT_BAND_VALUES - {""}),
                    "forbidden_interpretation": (
                        "tight_numeric_level_touch_band must not be interpreted as an "
                        "independent edge or standalone entry feature."
                    ),
                }
            ],
            "required_columns": required_columns,
            "enum_columns": enum_columns,
            "free_text_columns": [
                "exclude_reason",
                "reviewer_notes",
                "metadata_005_tight_numeric_level_touch_band_notes",
            ]
            + [group["notes"] for group in feature_groups],
            "forbidden_outcome_columns": sorted(FORBIDDEN_OUTCOME_COLUMNS),
            "forbidden_label_information": [
                "final result",
                "TP hit",
                "SL hit",
                "pnl",
                "R multiple",
                "future bars after entry",
                "whether setup later worked",
                "replay outcome",
                "matched-control result",
                "future MFE/MAE",
                "future liquidity behavior after decision",
            ],
            "leakage_guard": (
                "Reviewer must label only what is visible before entry / before decision. "
                "If future candles are visible in the visual pack, pre_entry_only_confirmed=YES "
                "means the reviewer consciously ignored that future information."
            ),
            "safety": {
                "backtest_run": False,
                "candidate_pack_generated": False,
                "matched_control_replay_run": False,
                "detector_executed": False,
                "runtime_logic_modified": False,
                "strategy_2_touched": False,
                "strategy_3_touched": False,
                "data_modified": False,
                "live_trading_enabled": False,
                "telegram_trade_alerts_enabled": False,
                "broker_execution_enabled": False,
                "order_execution_enabled": False,
            },
        }
    )


def write_json(path: Path | str, payload: Mapping[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_visual_review_metadata(
    visual_template_path: Path | str = DEFAULT_VISUAL_TEMPLATE_PATH,
) -> tuple[list[dict[str, str]], bool]:
    path = Path(visual_template_path)
    if not path.exists():
        return [], False
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return rows, True


def build_blank_template_rows(
    schema: Phase3Schema,
    visual_rows: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    required_columns = schema.required_columns
    if not visual_rows:
        return []

    rows: list[dict[str, str]] = []
    for source in visual_rows:
        row = {column: "" for column in required_columns}
        row["sample_id"] = source.get("sample_id", "")
        row["candidate_id"] = source.get("candidate_id", "")
        row["source_mode"] = source.get("source_mode", "")
        row["symbol"] = source.get("symbol", "")
        row["candidate_timestamp"] = source.get("anchor_timestamp", "") or source.get(
            "candidate_timestamp", ""
        )
        row["decision_timestamp"] = source.get("anchor_timestamp", "") or source.get(
            "decision_timestamp", ""
        )
        row["anchor_timeframe"] = source.get("anchor_timeframe", "")
        row["chart_path"] = source.get("chart_path", "")
        row["chart_url"] = ""
        row["index_anchor"] = source.get("html_path", "")
        row["execution_data_status"] = source.get("execution_data_status", "")
        row["m1_candles_count"] = source.get("m1_candles_count", "")
        row["m5_candles_count"] = source.get("m5_candles_count", "")
        row["m15_candles_count"] = source.get("m15_candles_count", "")
        rows.append(row)
    return rows


def write_label_template(path: Path | str, schema: Phase3Schema, rows: Sequence[Mapping[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=schema.required_columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in schema.required_columns})


def has_forbidden_outcome_columns(columns: Iterable[str]) -> list[str]:
    bad: list[str] = []
    for column in columns:
        lowered = column.strip().lower()
        if lowered in FORBIDDEN_OUTCOME_COLUMNS:
            bad.append(column)
    return bad


def validate_label_rows(
    rows: Sequence[Mapping[str, str]],
    columns: Sequence[str],
    schema: Phase3Schema,
    allow_empty: bool = False,
) -> dict[str, Any]:
    required_columns = schema.required_columns
    missing_required = [column for column in required_columns if column not in columns]
    forbidden_columns = has_forbidden_outcome_columns(columns)

    primary_groups = schema.primary_feature_fields
    missing_primary_groups: list[str] = []
    for group in primary_groups:
        for column in [group["visible_pre_entry"], group["label"], group["confidence"], group["notes"]]:
            if column not in columns:
                missing_primary_groups.append(f"{group['test_id']}:{column}")

    spec_005_primary_columns = [column for column in columns if column.startswith("feature_005_")]

    invalid_enum_values: list[dict[str, Any]] = []
    enum_columns = schema.enum_columns
    for row_index, row in enumerate(rows, start=2):
        for column, allowed_values in enum_columns.items():
            if column not in row:
                continue
            value = (row.get(column) or "").strip()
            if value == "" and allow_empty:
                continue
            if value == "" and column in GLOBAL_IDENTITY_FIELDS:
                continue
            if value not in set(allowed_values):
                invalid_enum_values.append(
                    {"row": row_index, "column": column, "value": value, "allowed": allowed_values}
                )

    completed_rows = 0
    incomplete_rows = 0
    rows_with_leakage_risk = 0
    rows_excluded_from_phase_4 = 0
    feature_required_columns = [
        column
        for group in primary_groups
        for column in [group["visible_pre_entry"], group["label"], group["confidence"]]
    ]
    global_required_for_completion = [
        "overall_reviewable",
        "pre_entry_only_confirmed",
        "leakage_risk_detected",
        "exclude_from_phase_4",
    ]

    for row in rows:
        if (row.get("leakage_risk_detected") or "").strip() == "YES":
            rows_with_leakage_risk += 1
        if (row.get("exclude_from_phase_4") or "").strip() == "YES":
            rows_excluded_from_phase_4 += 1
        completion_values = [
            (row.get(column) or "").strip()
            for column in global_required_for_completion + feature_required_columns
        ]
        if completion_values and all(value != "" for value in completion_values):
            completed_rows += 1
        else:
            incomplete_rows += 1

    errors = []
    if missing_required:
        errors.append("MISSING_REQUIRED_COLUMNS")
    if missing_primary_groups:
        errors.append("MISSING_PRIMARY_FEATURE_GROUPS")
    if spec_005_primary_columns:
        errors.append("SPEC_005_INCLUDED_AS_PRIMARY_FEATURE")
    if forbidden_columns:
        errors.append("FORBIDDEN_OUTCOME_COLUMNS_PRESENT")
    if invalid_enum_values:
        errors.append("INVALID_ENUM_VALUES")

    valid = not errors
    if not rows and not allow_empty:
        errors.append("NO_ROWS")
        valid = False

    return {
        "valid": valid,
        "allow_empty": allow_empty,
        "errors": errors,
        "total_rows": len(rows),
        "completed_rows": completed_rows,
        "incomplete_rows": incomplete_rows,
        "rows_with_leakage_risk": rows_with_leakage_risk,
        "rows_excluded_from_phase_4": rows_excluded_from_phase_4,
        "missing_required_fields": missing_required,
        "missing_primary_feature_groups": missing_primary_groups,
        "spec_005_primary_columns": spec_005_primary_columns,
        "forbidden_outcome_columns": forbidden_columns,
        "invalid_enum_values": invalid_enum_values,
        "primary_feature_group_count": len(primary_groups),
    }


def validate_labels_file(
    labels_path: Path | str,
    schema_path: Path | str,
    output_path: Path | str | None = None,
    allow_empty: bool = False,
) -> dict[str, Any]:
    schema = Phase3Schema(json.loads(Path(schema_path).read_text(encoding="utf-8")))
    with Path(labels_path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        columns = reader.fieldnames or []
    summary = validate_label_rows(rows, columns, schema, allow_empty=allow_empty)
    summary["labels_path"] = str(labels_path)
    summary["schema_path"] = str(schema_path)
    if output_path:
        write_json(output_path, summary)
    return summary


def write_phase_3_outputs(
    specs_path: Path | str = DEFAULT_SPECS_PATH,
    visual_template_path: Path | str = DEFAULT_VISUAL_TEMPLATE_PATH,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    output = Path(output_dir)
    specs = load_feature_specs(specs_path)
    schema = build_phase_3_schema(specs)
    visual_rows, visual_found = read_visual_review_metadata(visual_template_path)
    template_rows = build_blank_template_rows(schema, visual_rows)

    schema_path = output / "phase_3_label_schema.json"
    template_path = output / "manual_labels_template.csv"
    validation_summary_path = output / "manual_labels_validation_summary.json"
    phase_3_summary_path = output / "phase_3_summary.json"

    write_json(schema_path, schema.schema)
    write_label_template(template_path, schema, template_rows)
    validation_summary = validate_labels_file(
        template_path, schema_path, validation_summary_path, allow_empty=True
    )

    phase_3_summary = {
        "phase": "ADELIN_V2_PHASE_3_VISUAL_REVIEW_LABELS",
        "planning_and_labeling_infrastructure_only": True,
        "visual_review_pack_found": visual_found,
        "visual_review_template_path": str(visual_template_path),
        "sample_rows_loaded_from_visual_pack": len(visual_rows),
        "total_specs": len(specs),
        "primary_test_count": schema.schema["primary_test_count"],
        "stratification_metadata_spec_count": schema.schema["stratification_metadata_spec_count"],
        "spec_005_excluded_from_primary_labels": True,
        "schema_path": str(schema_path),
        "manual_labels_template_path": str(template_path),
        "manual_labels_validation_summary_path": str(validation_summary_path),
        "validation_result": validation_summary["valid"],
        "limitations": [
            (
                "Existing visual review pack may show future candles; reviewer must label only "
                "pre-entry/pre-decision information and set pre_entry_only_confirmed accordingly."
            ),
        ]
        if visual_found
        else [
            "PHASE_3_VISUAL_PACK_NOT_FOUND",
            "No existing visual review pack template was found; schema was still generated.",
        ],
        "safety": schema.schema["safety"],
    }
    write_json(phase_3_summary_path, phase_3_summary)
    return phase_3_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Adelin v2 Phase 3 manual labels.")
    parser.add_argument("--labels-path", required=True)
    parser.add_argument("--schema-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--allow-empty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = validate_labels_file(
        labels_path=args.labels_path,
        schema_path=args.schema_path,
        output_path=args.output_path,
        allow_empty=args.allow_empty,
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
