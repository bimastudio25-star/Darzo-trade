from __future__ import annotations

import csv
import json
from pathlib import Path

from dazro_trade.analysis.strategy_2_manual_sample_labels import (
    build_manual_label_analysis,
    build_manual_subset_profiles,
    deep_tail_analysis,
    match_manual_to_auto_samples,
    normalize_manual_row,
    profile_label_subset,
    validate_manual_labels,
    write_template,
)


def _manual_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "manual_sample_id": "USER_001",
        "source_type": "manual_trade",
        "symbol": "XAUUSD",
        "h1_timestamp": "2026-05-19T14:00:00+00:00",
        "direction": "long",
        "user_grade": "A_PLUS",
        "manual_trade_taken": "true",
        "notes": "real user label",
        "user_reasoning": "clean reclaim",
        "manipulation_depth_usd": "4.5",
        "expansion_usd": "20",
        "session": "NewYork",
        "h1_reference_type": "previous_h1",
        "liquidity_level": "2400",
    }
    row.update(updates)
    return row


def _auto_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "sample_id": "AUTO_001",
        "symbol": "XAUUSD",
        "direction": "LONG",
        "h1_context_timestamp": "2026-05-19T14:00:00+00:00",
        "h1_liquidity_level": "2400",
        "session": "NewYork",
        "h1_reference_type": "previous_h1",
        "sample_status": "VALID_SAMPLE_TRADE_TRIGGERED",
        "manipulation_depth_usd": "4.5",
        "manipulation_depth_pips": "45",
        "distribution_distance_usd": "20",
        "distribution_distance_pips": "200",
    }
    row.update(updates)
    return row


def test_manual_label_schema_accepts_required_and_partial_optional_fields():
    validation = validate_manual_labels([_manual_row()])
    assert validation["valid"] is True
    assert validation["real_label_rows"] == 1
    normalized = validation["normalized_rows"][0]
    assert normalized["manipulation_depth_pips"] == "45.0"


def test_invalid_grades_are_rejected():
    validation = validate_manual_labels([_manual_row(user_grade="GOLD")])
    assert validation["valid"] is False
    assert any(err["field"] == "user_grade" for err in validation["errors"])


def test_template_generation_creates_csv_and_jsonl(tmp_path: Path):
    paths = write_template(tmp_path, output_format="both")
    assert Path(paths["csv"]).exists()
    assert Path(paths["jsonl"]).exists()
    with Path(paths["csv"]).open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["manual_sample_id"].startswith("EXAMPLE_")


def test_unit_conversion_is_explicit_and_correct():
    row = normalize_manual_row(_manual_row(manipulation_depth_usd="4.59", manipulation_depth_pips=""), pip_factor=10)
    assert row["manipulation_depth_pips"] == "45.9"
    row2 = normalize_manual_row(_manual_row(manipulation_depth_usd="", manipulation_depth_pips="98.8"), pip_factor=10)
    assert row2["manipulation_depth_usd"] == "9.88"


def test_manual_sample_matching_matched_and_ambiguous():
    manual = [normalize_manual_row(_manual_row())]
    matched = match_manual_to_auto_samples(manual, [_auto_row()])
    assert matched[0]["match_status"] == "matched"
    ambiguous = match_manual_to_auto_samples(
        manual,
        [
            _auto_row(sample_id="AUTO_001"),
            _auto_row(sample_id="AUTO_002", h1_context_timestamp="2026-05-19T14:05:00+00:00", h1_liquidity_level="2400.5"),
        ],
    )
    assert ambiguous[0]["match_status"] == "ambiguous_match"


def test_a_plus_and_no_trade_profiles_are_computed_separately():
    rows = [
        normalize_manual_row(_manual_row(manual_sample_id="USER_A", user_grade="A_PLUS", manipulation_depth_usd="4", expansion_usd="20")),
        normalize_manual_row(_manual_row(manual_sample_id="USER_N", user_grade="NO_TRADE", manipulation_depth_usd="18", expansion_usd="4")),
    ]
    profiles = build_manual_subset_profiles(rows)
    assert profiles["A_PLUS_only"]["count"] == 1
    assert profiles["NO_TRADE"]["count"] == 1
    assert profiles["A_PLUS_only"]["risky_sl_usd"] == 4
    assert profiles["NO_TRADE"]["conservative_sl_usd"] == 22.5


def test_risky_and_conservative_sl_and_risk_flags_for_subset():
    profile = profile_label_subset(
        [
            normalize_manual_row(_manual_row(manual_sample_id="A", manipulation_depth_usd="5", expansion_usd="20")),
            normalize_manual_row(_manual_row(manual_sample_id="B", manipulation_depth_usd="16", expansion_usd="30")),
        ],
        subset_name="test",
    )
    assert profile["risky_sl_usd"] == 16
    assert profile["conservative_sl_usd"] == 20
    assert profile["profile_risk_too_large"] is True


def test_deep_tail_subset_identifies_manipulation_above_12():
    rows = [_auto_row(sample_id="BODY", manipulation_depth_usd="8"), _auto_row(sample_id="TAIL", manipulation_depth_usd="13")]
    tail = {row["subset"]: row for row in deep_tail_analysis(rows)}
    assert tail["body_le_12_usd"]["count"] == 1
    assert tail["tail_gt_12_usd"]["count"] == 1


def test_analysis_with_template_examples_marks_manual_labels_missing(tmp_path: Path):
    template_paths = write_template(tmp_path, output_format="csv")
    auto_path = tmp_path / "auto.csv"
    with auto_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(_auto_row().keys()))
        writer.writeheader()
        writer.writerow(_auto_row())
    report = build_manual_label_analysis(labels_path=Path(template_paths["csv"]), auto_samples_path=auto_path)
    assert report["validation"]["manual_labels_not_provided_yet"] is True
    assert "MANUAL_LABELS_NOT_PROVIDED_YET" in report["verdict_flags"]


def test_new_code_does_not_import_forbidden_modules_or_write_market_data():
    paths = [
        Path("dazro_trade/analysis/strategy_2_manual_sample_labels.py"),
        Path("dazro_trade/analytics/strategy_2_manual_sample_label_audit.py"),
        Path("scripts/create_strategy_2_manual_label_template.py"),
        Path("scripts/analyze_strategy_2_manual_sample_labels.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden = "strategy" + "_3"
    assert forbidden not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "open(\"data/xauusd" not in combined
