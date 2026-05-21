from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.strategy_2_rulebook_v0_labeling import (
    build_rulebook_v0_labeling,
    label_sample,
    load_containing_samples,
    manipulation_zone,
    pips_to_usd,
    risk_zone,
    usd_to_pips,
    write_rulebook_v0_outputs,
)


def _row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "sample_id": "S2_001_containing",
        "symbol": "XAUUSD",
        "m15_filter_model": "containing",
        "direction": "LONG",
        "h1_reference_type": "previous_h1",
        "h1_liquidity_level": 2400.0,
        "h1_liquidity_side": "LOW",
        "dominant_contains_internal_count": 0,
        "dominant_high_taken": False,
        "dominant_low_taken": True,
        "opposite_h1_side_taken_first": False,
        "h1_level_take_timestamp": "2026-05-20T09:05:00+00:00",
        "m15_sequence_valid": True,
        "m15_invalid_reason": "",
        "mae_reached": True,
        "range_reentry_reached": True,
        "manipulation_depth_usd": 4.5,
        "manipulation_depth_pips": 45.0,
        "sample_status": "VALID_SAMPLE_TRADE_TRIGGERED",
        "valid_for_mae_dataset": True,
    }
    row.update(updates)
    return row


def test_loads_only_containing_model_samples(tmp_path: Path):
    pd.DataFrame([_row(sample_id="C", m15_filter_model="containing"), _row(sample_id="P", m15_filter_model="preceding")]).to_csv(
        tmp_path / "corrected_mechanical_samples.csv", index=False
    )
    loaded = load_containing_samples(tmp_path)
    assert len(loaded) == 1
    assert loaded.iloc[0]["sample_id"] == "C"


def test_risk_zone_boundary_logic():
    assert risk_zone(12)[0] == "STANDARD"
    assert risk_zone(12.01)[0] == "LARGE"
    assert risk_zone(20)[0] == "LARGE"
    assert risk_zone(20.01)[0] == "DEEP_TAIL"
    assert risk_zone(30.01)[0] == "EXTREME_TAIL"


def test_manipulation_zone_boundary_logic():
    assert manipulation_zone(1.99)[0] == "SHALLOW"
    assert manipulation_zone(2)[0] == "IDEAL"
    assert manipulation_zone(6)[0] == "IDEAL"
    assert manipulation_zone(6.01)[0] == "ACCEPTABLE"
    assert manipulation_zone(12.01)[0] == "DEEP"
    assert manipulation_zone(20.01)[0] == "VERY_DEEP"
    assert manipulation_zone(30.01)[0] == "EXTREME"


def test_manipulation_depth_is_separate_from_sl_distance_and_pips_conversion():
    label = label_sample(_row(manipulation_depth_usd=4.5, manipulation_depth_pips=45), pip_factor=10)
    assert pips_to_usd(226, 10) == 22.6
    assert usd_to_pips(22.6, 10) == 226
    assert label["manipulation_depth_usd"] == 4.5
    assert label["manipulation_depth_pips"] == 45
    assert label["sl_distance_usd"] == 5.625
    assert label["sl_distance_pips"] == 56.25


def test_reaction_quality_defaults_to_not_computed_and_uncertain():
    label = label_sample(_row(), pip_factor=10)
    assert label["reaction_quality_tag"] == "NOT_COMPUTED"
    assert label["rulebook_v0_label"] == "UNCERTAIN"
    assert "REACTION_QUALITY_NOT_COMPUTED" in label["uncertain_rules_triggered"]


def test_take_requires_all_take_rules():
    label = label_sample(
        _row(
            reaction_quality_tag="RECLAIM",
            reaction_observable_at_decision_time=True,
            manipulation_depth_usd=4.5,
            manipulation_depth_pips=45,
        ),
        pip_factor=10,
    )
    assert label["rulebook_v0_label"] == "UNCERTAIN"
    assert "EXPANSION_POTENTIAL_USER_TBD" in label["uncertain_rules_triggered"]
    assert "H1_REFERENCE_VALID" in label["take_rules_passed"]
    assert "REACTION_QUALITY_TAKE_READY" in label["take_rules_passed"]


def test_skip_triggered_on_any_hard_skip():
    label = label_sample(_row(m15_sequence_valid=False, m15_invalid_reason="INVALID_CURRENT_M15_HIGH_TAKEN_FIRST_FOR_LONG"), pip_factor=10)
    assert label["rulebook_v0_label"] == "SKIP"
    assert "INVALID_CURRENT_M15_HIGH_TAKEN_FIRST_FOR_LONG" in label["skip_rules_triggered"]


def test_invalid_no_distribution_is_not_hard_skip_by_itself():
    label = label_sample(_row(sample_status="INVALID_NO_DISTRIBUTION"), pip_factor=10)
    assert label["rulebook_v0_label"] == "UNCERTAIN"
    assert "INVALID_NO_DISTRIBUTION" not in label["skip_rules_triggered"]
    assert "DIAGNOSTIC_ONLY" in label["diagnostic_only_reason"]


def test_uncertain_for_deep_very_deep_and_not_computed():
    deep = label_sample(_row(manipulation_depth_usd=13, manipulation_depth_pips=130), pip_factor=10)
    very_deep = label_sample(_row(manipulation_depth_usd=24, manipulation_depth_pips=240), pip_factor=10)
    assert deep["rulebook_v0_label"] == "UNCERTAIN"
    assert "MULTIPLE_WARNINGS_LARGE_PLUS_DEEP" in deep["uncertain_rules_triggered"]
    assert very_deep["rulebook_v0_label"] == "UNCERTAIN"
    assert "MANIPULATION_ZONE_VERY_DEEP" in very_deep["uncertain_rules_triggered"]


def test_threshold_status_user_tbd_and_user_decision_empty(tmp_path: Path):
    pd.DataFrame([_row(), _row(sample_id="S2_002", m15_sequence_valid=False)]).to_csv(tmp_path / "corrected_mechanical_samples.csv", index=False)
    result = build_rulebook_v0_labeling(tmp_path, pip_factor=10)
    assert set(result.per_sample["threshold_status"]) == {"USER_TBD"}
    assert result.per_sample["user_decision"].eq("").all()
    assert result.summary["performance_metrics_included"] is False
    assert result.summary["take_vs_skip_comparison_included"] is False


def test_outputs_are_written(tmp_path: Path):
    pd.DataFrame([_row(), _row(sample_id="S2_002", m15_sequence_valid=False)]).to_csv(tmp_path / "corrected_mechanical_samples.csv", index=False)
    result = build_rulebook_v0_labeling(tmp_path, pip_factor=10)
    paths = write_rulebook_v0_outputs(result, tmp_path / "output", docs_path=tmp_path / "doc.md")
    assert Path(paths["per_sample"]).exists()
    assert Path(paths["counters"]).exists()
    assert Path(paths["risk_zone_distribution"]).exists()
    assert Path(paths["manipulation_zone_distribution"]).exists()
    assert Path(paths["threshold_status"]).exists()
    assert Path(paths["summary"]).exists()
    assert Path(paths["report"]).exists()
    assert Path(paths["docs"]).exists()


def test_no_forbidden_imports_or_data_writes():
    paths = [
        Path("dazro_trade/analytics/strategy_2_rulebook_v0_labeling.py"),
        Path("scripts/analyze_strategy_2_rulebook_v0_labeling.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden = "strategy" + "_3"
    assert forbidden not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "open(\"data/xauusd" not in combined
    assert "order_send(" not in combined
    assert "telegram_bot" not in combined


def test_importing_module_does_not_auto_run_analysis():
    module = importlib.import_module("scripts.analyze_strategy_2_rulebook_v0_labeling")
    assert hasattr(module, "main")
    assert hasattr(module, "run")
