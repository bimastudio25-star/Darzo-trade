from __future__ import annotations

import csv
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_DIR = REPO_ROOT / "backtests" / "reports" / "adelin_v2_confidence3_forward_collection_batches"
DOC_PATH = REPO_ROOT / "docs" / "research" / "adelin_v2_confidence3_forward_collection_batch_template.md"


def _load_json(name: str):
    return json.loads((BATCH_DIR / name).read_text(encoding="utf-8"))


def _csv_header(name: str) -> list[str]:
    with (BATCH_DIR / name).open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def _csv_rows(name: str) -> list[dict[str, str]]:
    with (BATCH_DIR / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_template_files_exist_and_parse():
    assert (BATCH_DIR / "batch_template.csv").exists()
    assert isinstance(_load_json("batch_template.json"), dict)
    assert isinstance(_load_json("progress_summary_template.json"), dict)
    assert (BATCH_DIR / "rejection_log_template.csv").exists()
    assert DOC_PATH.exists()


def test_batch_csv_headers_match_required_fields():
    headers = _csv_header("batch_template.csv")
    expected = [
        "sample_id",
        "batch_id",
        "source_artifact",
        "collector",
        "collection_timestamp",
        "decision_timestamp",
        "symbol",
        "direction",
        "direction_source",
        "direction_confidence",
        "evidence_capture_mode",
        "collection_pipeline_relationship",
        "reference_price",
        "entry_reference",
        "source_lineage",
        "eligibility_schema_version",
        "eligibility_schema_commit",
        "collected_pre_decision_only",
        "post_entry_data_used_for_inclusion",
        "h3_h4_state_known_at_collection",
        "outcome_used_for_inclusion",
        "is_primary_eligible",
        "rejection_reason",
        "reviewer_notes",
    ]
    assert headers == expected


def test_batch_json_template_keeps_target_and_eligibility_rules():
    template = _load_json("batch_template.json")
    assert template["template_only"] is True
    assert template["samples_collected"] is False
    assert template["eligibility_schema_freeze_classification"] == "PROCEDURAL_AND_TEST_GUARDED"
    assert template["collection_pipeline_relationship"] == "HYBRID"
    assert template["cumulative_existing_confidence_3_count"] == 21
    assert template["remaining_to_target_60"] == 39
    assert template["abandon_threshold_weeks_without_minimum_progress"] == 12
    assert set(template["allowed_batch_decisions"]) == {
        "FORWARD_COLLECTION_BATCH_ACCEPTED",
        "FORWARD_COLLECTION_BATCH_NEEDS_REVIEW",
        "FORWARD_COLLECTION_BATCH_REJECTED",
    }

    eligibility = template["primary_eligibility_expectations"]
    assert eligibility["direction_source"] == "EXISTING_METADATA"
    assert eligibility["direction_confidence"] == 3
    assert eligibility["evidence_capture_mode"] == "FULL_REVIEW"
    assert eligibility["rapid_capture_primary_eligible"] is False
    assert eligibility["collected_pre_decision_only"] is True
    assert eligibility["post_entry_data_used_for_inclusion"] is False
    assert eligibility["h3_h4_state_known_at_collection"] is False
    assert eligibility["outcome_used_for_inclusion"] is False


def test_progress_summary_template_blocks_proxy_phase4_and_live_paths():
    progress = _load_json("progress_summary_template.json")
    assert progress["template_only"] is True
    assert progress["samples_collected"] is False
    assert progress["existing_confidence_3_count"] == 21
    assert progress["target_total_confidence_3_count"] == 60
    assert progress["required_additional_confidence_3_count"] == 39
    assert progress["remaining_to_target"] == 39
    assert progress["status"] == "FORWARD_COLLECTION_NOT_STARTED"
    assert progress["abandon_threshold_weeks_without_minimum_progress"] == 12
    assert progress["proxy_execution_allowed"] is False
    assert progress["phase_4_unlocked"] is False
    assert progress["live_signals_allowed"] is False
    assert progress["order_send_allowed"] is False
    assert progress["matched_control_allowed"] is False
    assert progress["h3_h4_proxy_computation_allowed"] is False
    assert progress["ohlc_read_allowed"] is False


def test_rejection_log_template_headers_and_reason_catalog():
    headers = _csv_header("rejection_log_template.csv")
    assert headers == [
        "sample_id",
        "batch_id",
        "source_artifact",
        "rejection_reason",
        "rejection_category",
        "rejection_detail",
        "reviewer_notes",
    ]

    reasons = {row["rejection_reason"] for row in _csv_rows("rejection_log_template.csv")}
    expected = {
        "DIRECTION_SOURCE_FIELD_ABSENT",
        "DIRECTION_CONFIDENCE_FIELD_ABSENT",
        "NON_PRIMARY_DIRECTION_SOURCE",
        "NON_PRIMARY_DIRECTION_CONFIDENCE",
        "DECISION_TIMESTAMP_MISSING",
        "DECISION_TIMESTAMP_AMBIGUOUS",
        "SAMPLE_ID_MISSING",
        "ID_RESOLUTION_AMBIGUOUS",
        "DUPLICATE_SAMPLE",
        "RAPID_CAPTURE_NOT_PRIMARY_ELIGIBLE",
        "SOURCE_LINEAGE_MISSING",
        "REFERENCE_PRICE_MISSING",
        "POST_ENTRY_DATA_USED_FOR_INCLUSION",
        "OUTCOME_USED_FOR_INCLUSION",
        "H3_H4_STATE_USED_FOR_SELECTION",
        "VISUAL_HINDSIGHT_SELECTION",
        "SCHEMA_VERSION_MISMATCH",
        "SCHEMA_RULE_CHANGED_WITHOUT_NEW_PLAN",
        "UNKNOWN_REJECTION_REASON",
    }
    assert expected <= reasons
    assert all(row["batch_id"] == "REJECTION_REASON_CATALOG" for row in _csv_rows("rejection_log_template.csv"))


def test_doc_records_template_only_safety_and_next_step():
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "This branch creates templates only" in text
    assert "Existing confidence-3 / EXISTING_METADATA samples: 21" in text
    assert "Additional required confidence-3 samples: 39" in text
    assert "RAPID_CAPTURE rows are not primary-eligible" in text
    assert "does not read OHLC" in text
    assert "does not run matched-control" in text
    assert "does not unlock Phase 4" in text
    assert "Proxy execution remains blocked" in text
