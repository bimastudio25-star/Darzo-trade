from __future__ import annotations

import csv
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_DIR = REPO_ROOT / "backtests" / "reports" / "adelin_v2_confidence3_forward_collection_batches"
DOC_PATH = REPO_ROOT / "docs" / "research" / "adelin_v2_confidence3_forward_collection_batch_001_manual_shell.md"


def _load_json(name: str):
    return json.loads((BATCH_DIR / name).read_text(encoding="utf-8"))


def _csv_rows(name: str) -> list[list[str]]:
    with (BATCH_DIR / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


def test_batch_001_files_exist_and_parse():
    assert (BATCH_DIR / "batch_001_manual.csv").exists()
    assert isinstance(_load_json("batch_001_manual.json"), dict)
    assert isinstance(_load_json("batch_001_progress_summary.json"), dict)
    assert (BATCH_DIR / "batch_001_rejection_log.csv").exists()
    assert (BATCH_DIR / "README_batch_001_manual.md").exists()
    assert DOC_PATH.exists()


def test_batch_001_manual_csv_is_header_only_and_matches_template():
    template_rows = _csv_rows("batch_template.csv")
    batch_rows = _csv_rows("batch_001_manual.csv")
    assert len(template_rows) == 1
    assert len(batch_rows) == 1
    assert batch_rows[0] == template_rows[0]
    assert "direction_source" in batch_rows[0]
    assert "direction_confidence" in batch_rows[0]
    assert "evidence_capture_mode" in batch_rows[0]
    assert "is_primary_eligible" in batch_rows[0]


def test_batch_001_json_is_manual_shell_and_fail_closed():
    batch = _load_json("batch_001_manual.json")
    assert batch["batch_id"] == "batch_001_manual"
    assert batch["manual_shell_only"] is True
    assert batch["samples_collected"] is False
    assert batch["manual_rows_provided"] is False
    assert batch["status"] == "BATCH_001_MANUAL_ROWS_NOT_PROVIDED_YET"
    assert batch["validation_status"] == "NO_NEW_CONFIDENCE3_SAMPLES_VALIDATED_YET"
    assert batch["eligible_confidence_3_count"] == 0
    assert batch["cumulative_existing_confidence_3_count"] == 21
    assert batch["cumulative_new_confidence_3_count"] == 0
    assert batch["cumulative_total_confidence_3_count"] == 21
    assert batch["remaining_to_target_60"] == 39

    fail_closed = batch["fail_closed_validation"]
    assert fail_closed["empty_batch_counts_as_primary_eligible"] is False
    assert fail_closed["incomplete_rows_count_as_primary_eligible"] is False
    assert fail_closed["rapid_capture_counts_as_primary_eligible"] is False
    assert fail_closed["outcome_or_post_entry_selection_rejects_batch"] is True
    assert fail_closed["h3_h4_state_selection_rejects_batch"] is True


def test_batch_001_eligibility_rules_are_frozen_and_primary_only():
    rules = _load_json("batch_001_manual.json")["primary_eligibility_rules"]
    assert rules["direction_source"] == "EXISTING_METADATA"
    assert rules["direction_confidence"] == 3
    assert rules["review_mode"] == "FULL_REVIEW"
    assert rules["evidence_capture_mode"] == "FULL_REVIEW"
    assert rules["collection_pipeline_relationship"] == "HYBRID"
    assert rules["decision_timestamp"] == "DIRECT_METADATA_REQUIRED"
    assert rules["collected_pre_decision_only"] is True
    assert rules["post_entry_data_used_for_inclusion"] is False
    assert rules["h3_h4_state_known_at_collection"] is False
    assert rules["outcome_used_for_inclusion"] is False
    assert rules["rapid_capture_primary_eligible"] is False


def test_batch_001_progress_summary_reports_zero_new_samples_and_blocks_execution():
    progress = _load_json("batch_001_progress_summary.json")
    assert progress["manual_shell_only"] is True
    assert progress["samples_collected"] is False
    assert progress["manual_rows_provided"] is False
    assert progress["status"] == "NO_NEW_CONFIDENCE3_SAMPLES_VALIDATED_YET"
    assert progress["existing_confidence_3_count"] == 21
    assert progress["target_total_confidence_3_count"] == 60
    assert progress["required_additional_confidence_3_count"] == 39
    assert progress["batch_001_new_confidence_3_count"] == 0
    assert progress["total_confidence_3_count"] == 21
    assert progress["remaining_to_target"] == 39
    assert progress["proxy_execution_allowed"] is False
    assert progress["phase_4_unlocked"] is False
    assert progress["live_signals_allowed"] is False
    assert progress["order_send_allowed"] is False
    assert progress["matched_control_allowed"] is False
    assert progress["h3_h4_proxy_computation_allowed"] is False
    assert progress["ohlc_read_allowed"] is False


def test_batch_001_rejection_log_is_header_only():
    rows = _csv_rows("batch_001_rejection_log.csv")
    assert rows == [[
        "sample_id",
        "batch_id",
        "source_artifact",
        "rejection_reason",
        "rejection_category",
        "rejection_detail",
        "reviewer_notes",
    ]]


def test_batch_001_forbidden_selection_and_blocked_actions():
    batch = _load_json("batch_001_manual.json")
    forbidden = set(batch["forbidden_selection_criteria"])
    assert "H3 state" in forbidden
    assert "H4 state" in forbidden
    assert "GOOD/FAST result" in forbidden
    assert "PnL" in forbidden
    assert "future MFE" in forbidden
    assert "post-entry behavior" in forbidden
    assert "visual hindsight" in forbidden

    blocked = batch["blocked_actions"]
    assert blocked["ohlc_read"] is False
    assert blocked["data_xauusd_csv_modified"] is False
    assert blocked["h3_h4_proxy_computation"] is False
    assert blocked["replay_run"] is False
    assert blocked["backtest_run"] is False
    assert blocked["matched_control_run"] is False
    assert blocked["phase_4_unlocked"] is False
    assert blocked["runtime_logic_modified"] is False
    assert blocked["strategy_2_modified"] is False
    assert blocked["strategy_3_modified"] is False
    assert blocked["live_trading_enabled"] is False
    assert blocked["broker_execution_enabled"] is False
    assert blocked["order_send_used"] is False
    assert blocked["secrets_added"] is False


def test_docs_explain_manual_shell_and_safety():
    readme = (BATCH_DIR / "README_batch_001_manual.md").read_text(encoding="utf-8")
    doc = DOC_PATH.read_text(encoding="utf-8")
    for text in [readme, doc]:
        assert "does not read OHLC" in text
        assert "does not compute H3/H4" in text
        assert "does not run matched-control" in text
        assert "does not unlock Phase 4" in text
        assert "RAPID_CAPTURE" in text
        assert "FULL_REVIEW" in text
        assert "NO_NEW_CONFIDENCE3_SAMPLES_VALIDATED_YET" in text
        assert "Proxy execution remains blocked" in text
