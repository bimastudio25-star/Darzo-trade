from __future__ import annotations

import csv
import importlib
import json
from pathlib import Path

from scripts.create_adelin_v2_manual_screenshot_concept_audit import (
    ALLOWED_MEASURABILITY,
    CONCEPTS,
    DEFAULT_OUTPUT_DIR,
    write_audit,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / DEFAULT_OUTPUT_DIR
MANDATORY_CONCEPTS = {
    "PRE_DECISION_SWEEP_HIGH_LOW",
    "FAST_M1_REACTION_AFTER_SWEEP",
    "TIGHT_SL_BEHIND_SPIKE_OR_SWING",
    "SWING_HIGH_LOW_ZONE_PROXIMITY",
    "HTF_LTF_LEVEL_CONFLUENCE",
    "VOLUME_PROFILE_ZONE_PROXIMITY",
    "PRICE_INSIDE_REACTION_ZONE",
    "CLEAN_TARGET_SPACE_TO_NEXT_ZONE",
    "DIRTY_REACTION_CHOP_AFTER_ENTRY",
    "ZONE_RETEST_OR_RECLAIM",
    "ROUND_OR_NUMERIC_LEVEL_CONFLUENCE",
    "SESSION_CONTEXT_ASIA_TO_NY_WINDOW",
}


def _load_json(name: str):
    return json.loads((OUTPUT_DIR / name).read_text(encoding="utf-8"))


def _load_csv(name: str):
    with (OUTPUT_DIR / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_module_import_is_safe():
    module = importlib.import_module("scripts.create_adelin_v2_manual_screenshot_concept_audit")
    assert hasattr(module, "write_audit")


def test_write_audit_creates_required_files(tmp_path: Path):
    summary = write_audit(tmp_path)
    assert summary["audit_only"] is True
    for name in [
        "manual_screenshot_concept_taxonomy.json",
        "concept_measurability_audit.csv",
        "concept_measurability_audit.json",
        "current_feature_coverage_map.csv",
        "missing_feature_candidates.json",
        "future_research_tasks.json",
        "summary.json",
    ]:
        assert (tmp_path / name).exists()


def test_output_files_exist():
    for name in [
        "manual_screenshot_concept_taxonomy.json",
        "concept_measurability_audit.csv",
        "concept_measurability_audit.json",
        "current_feature_coverage_map.csv",
        "missing_feature_candidates.json",
        "future_research_tasks.json",
        "summary.json",
    ]:
        assert (OUTPUT_DIR / name).exists()


def test_all_mandatory_concepts_included():
    taxonomy = _load_json("manual_screenshot_concept_taxonomy.json")
    audit = _load_json("concept_measurability_audit.json")
    assert set(taxonomy["concept_ids"]) == MANDATORY_CONCEPTS
    assert {row["concept_id"] for row in audit} == MANDATORY_CONCEPTS
    assert {row["concept_id"] for row in CONCEPTS} == MANDATORY_CONCEPTS


def test_allowed_measurability_statuses_only():
    audit = _load_json("concept_measurability_audit.json")
    assert all(row["measurability_status"] in ALLOWED_MEASURABILITY for row in audit)
    csv_rows = _load_csv("concept_measurability_audit.csv")
    assert all(row["measurability_status"] in ALLOWED_MEASURABILITY for row in csv_rows)


def test_summary_safety_flags():
    summary = _load_json("summary.json")
    assert summary["audit_only"] is True
    assert summary["screenshots_auto_labeled"] is False
    assert summary["screenshots_used_as_validation"] is False
    assert summary["ohlc_read"] is False
    assert summary["replay_run"] is False
    assert summary["matched_control_replay_run"] is False
    assert summary["phase_4_blocked"] is True
    assert summary["runtime_logic_modified"] is False
    assert summary["live_trading_enabled"] is False
    assert summary["telegram_enabled"] is False
    assert summary["broker_execution_enabled"] is False
    assert summary["profitability_claim_made"] is False


def test_volume_profile_not_marked_measurable_now():
    audit = {row["concept_id"]: row for row in _load_json("concept_measurability_audit.json")}
    volume = audit["VOLUME_PROFILE_ZONE_PROXIMITY"]
    assert volume["measurability_status"] != "MEASURABLE_NOW"
    assert volume["measurability_status"] == "MEASURABLE_WITH_NEW_DATA"
    assert "volume" in volume["required_data"].lower()


def test_dirty_reaction_not_clean_pre_entry_feature():
    audit = {row["concept_id"]: row for row in _load_json("concept_measurability_audit.json")}
    dirty = audit["DIRTY_REACTION_CHOP_AFTER_ENTRY"]
    assert dirty["measurability_status"] == "HEURISTIC_ONLY"
    assert dirty["runtime_safe_now"] == "NO"
    assert dirty["leakage_risk"] == "HIGH"
    assert "not an entry feature" in dirty["notes"].lower()


def test_feature_coverage_map_has_required_rows():
    rows = _load_csv("current_feature_coverage_map.csv")
    assert {row["concept_id"] for row in rows} == MANDATORY_CONCEPTS
    coverage = {row["concept_id"]: row for row in rows}
    assert coverage["ROUND_OR_NUMERIC_LEVEL_CONFLUENCE"]["coverage_status"] == "COVERED"
    assert coverage["TIGHT_SL_BEHIND_SPIKE_OR_SWING"]["coverage_status"] == "MISSING"
    assert coverage["DIRTY_REACTION_CHOP_AFTER_ENTRY"]["coverage_status"] == "PARTIAL"


def test_summary_counts_match_audit_rows():
    summary = _load_json("summary.json")
    audit = _load_json("concept_measurability_audit.json")
    assert summary["total_concepts"] == len(audit) == 12
    assert summary["measurable_now_count"] == 3
    assert summary["existing_ohlc_proxy_count"] == 7
    assert summary["new_data_required_count"] == 1
    assert summary["heuristic_only_count"] == 1
    assert summary["not_reliably_measurable_count"] == 0
