from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

from dazro_trade.analytics.strategy_2_layer_b_manual_validation_pack import (
    PACK_COLUMNS,
    build_layer_b_manual_validation_pack,
    write_manual_validation_pack_outputs,
)


def _feature_row(
    sample_id: str,
    *,
    state: str = "VALID_LONG",
    descriptor: str = "FAST_REENTRY",
    decision_time: str = "2026-05-01T10:05:00+00:00",
    funnel_state: str = "MEASURABLE_REACTION_WINDOW",
) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "h1_context_id": f"CTX_{sample_id}",
        "direction_candidate": "LONG" if state != "VALID_SHORT" else "SHORT",
        "layer_a_state": state,
        "layer_a_valid": state in {"VALID_LONG", "VALID_SHORT"},
        "layer_b_eligible": funnel_state == "MEASURABLE_REACTION_WINDOW",
        "layer_b_measurable": funnel_state == "MEASURABLE_REACTION_WINDOW",
        "layer_b_funnel_state": funnel_state,
        "entry_status_audit": "ENTRY_TRIGGERED_MAE_AND_RANGE_REENTRY",
        "sweep_timestamp": "2026-05-01T10:00:00+00:00",
        "decision_time": decision_time,
        "feature_time_boundary": decision_time,
        "data_window_start": "2026-05-01T10:00:00+00:00",
        "data_window_end": decision_time,
        "range_reentry_detected": "TRUE",
        "time_to_reentry_seconds": 300,
        "reentry_distance_usd": 1.2,
        "reentry_distance_pips": 12.0,
        "rejection_wick_ratio": 0.4,
        "body_displacement_usd": 0.8,
        "body_displacement_pips": 8.0,
        "post_sweep_compression_seconds": 60,
        "micro_range_size_usd": 2.0,
        "micro_range_size_pips": 20.0,
        "acceleration_after_reentry_usd": 0.5,
        "acceleration_after_reentry_pips": 5.0,
        "clean_vs_dirty_path_candidate": "CLEAN",
        "reaction_descriptor": descriptor,
        "layer_b_candidate_label": "STRONG_REACTION_CANDIDATE",
        "uses_future_data": True,
        "diagnostic_only": True,
        "missing_required_data": False,
        "null_feature_reasons": "",
        "feature_warnings": "",
        "pip_factor_used": 10.0,
    }


def _mechanical_row(sample_id: str) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "symbol": "XAUUSD",
        "m15_filter_model": "containing",
        "h1_context_timestamp": "2026-05-01T10:00:00+00:00",
        "h1_liquidity_level": 2400.5,
        "h1_level_take_timestamp": "2026-05-01T10:00:00+00:00",
        "range_reentry_timestamp": "2026-05-01T10:05:00+00:00",
        "entry_timestamp": "2026-05-01T10:05:00+00:00",
        "entry_status": "ENTRY_TRIGGERED_MAE_AND_RANGE_REENTRY",
        "manipulation_depth_usd": 4.2,
        "manipulation_depth_pips": 42.0,
        "mae_avg_used_usd": 6.5,
    }


def _write_inputs(tmp_path: Path, rows: list[dict[str, object]]) -> tuple[Path, Path]:
    input_path = tmp_path / "layer_b_reaction_features_per_sample.csv"
    pd.DataFrame(rows).to_csv(input_path, index=False)
    mechanical_path = tmp_path / "corrected_mechanical_samples.csv"
    pd.DataFrame([_mechanical_row(str(row["sample_id"])) for row in rows]).to_csv(mechanical_path, index=False)
    return input_path, mechanical_path


def test_reentry_not_reached_rows_are_excluded_from_pack(tmp_path: Path):
    rows = [
        _feature_row("FAST_001", descriptor="FAST_REENTRY"),
        _feature_row(
            "NO_REENTRY_001",
            descriptor="NO_ENTRY_REENTRY_NOT_REACHED",
            decision_time="",
            funnel_state="REENTRY_NOT_REACHED",
        ),
    ]
    input_path, mechanical_path = _write_inputs(tmp_path, rows)
    result = build_layer_b_manual_validation_pack(
        input_path,
        mechanical_path=mechanical_path,
        expected_count=1,
        expected_descriptor_counts={"FAST_REENTRY": 1, "CHOP_AFTER_SWEEP_CANDIDATE": 0},
    )
    assert result.summary["pack_row_count"] == 1
    assert result.summary["excluded_reentry_not_reached_count"] == 1
    assert "NO_ENTRY_REENTRY_NOT_REACHED" not in set(result.pack["reaction_descriptor"])


def test_rows_without_decision_time_are_excluded_or_fail_gate(tmp_path: Path):
    rows = [
        _feature_row("FAST_001", descriptor="FAST_REENTRY"),
        _feature_row("FAST_MISSING_DECISION", descriptor="FAST_REENTRY", decision_time=""),
    ]
    input_path, mechanical_path = _write_inputs(tmp_path, rows)
    with pytest.raises(ValueError, match="pack count 1 differs"):
        build_layer_b_manual_validation_pack(
            input_path,
            mechanical_path=mechanical_path,
            expected_count=2,
            expected_descriptor_counts={"FAST_REENTRY": 2, "CHOP_AFTER_SWEEP_CANDIDATE": 0},
        )
    result = build_layer_b_manual_validation_pack(
        input_path,
        mechanical_path=mechanical_path,
        expected_count=1,
        expected_descriptor_counts={"FAST_REENTRY": 1, "CHOP_AFTER_SWEEP_CANDIDATE": 0},
    )
    assert result.pack["decision_time"].ne("").all()


def test_only_fast_and_chop_descriptors_enter_pack(tmp_path: Path):
    rows = [
        _feature_row("FAST_001", descriptor="FAST_REENTRY"),
        _feature_row("CHOP_001", descriptor="CHOP_AFTER_SWEEP_CANDIDATE"),
        _feature_row("UNKNOWN_001", descriptor="UNKNOWN"),
        _feature_row("INVALID_001", state="INVALIDATED_LONG", descriptor="FAST_REENTRY"),
    ]
    input_path, mechanical_path = _write_inputs(tmp_path, rows)
    result = build_layer_b_manual_validation_pack(
        input_path,
        mechanical_path=mechanical_path,
        expected_count=2,
        expected_descriptor_counts={"FAST_REENTRY": 1, "CHOP_AFTER_SWEEP_CANDIDATE": 1},
    )
    assert set(result.pack["reaction_descriptor"]) == {"FAST_REENTRY", "CHOP_AFTER_SWEEP_CANDIDATE"}
    assert set(result.pack["layer_a_state"]) <= {"VALID_LONG", "VALID_SHORT"}


def test_manual_label_columns_are_blank_by_default(tmp_path: Path):
    input_path, mechanical_path = _write_inputs(tmp_path, [_feature_row("FAST_001")])
    result = build_layer_b_manual_validation_pack(
        input_path,
        mechanical_path=mechanical_path,
        expected_count=1,
        expected_descriptor_counts={"FAST_REENTRY": 1, "CHOP_AFTER_SWEEP_CANDIDATE": 0},
    )
    for column in ["label_take_skip_uncertain", "manual_notes", "reviewer", "reviewed_at"]:
        assert column in result.pack.columns
        assert result.pack[column].eq("").all()
    assert result.pack.columns.tolist() == PACK_COLUMNS


def test_summary_reports_reentry_not_reached_separately_from_not_enough_data(tmp_path: Path):
    rows = [
        _feature_row("FAST_001", descriptor="FAST_REENTRY"),
        _feature_row("NO_REENTRY_001", descriptor="NO_ENTRY_REENTRY_NOT_REACHED", decision_time="", funnel_state="REENTRY_NOT_REACHED"),
        _feature_row("NED_001", descriptor="NOT_ENOUGH_DATA", funnel_state="NOT_ENOUGH_DATA"),
        _feature_row("BUG_001", descriptor="MISSING_DECISION_TIME_BUG", funnel_state="MISSING_DECISION_TIME_BUG"),
    ]
    input_path, mechanical_path = _write_inputs(tmp_path, rows)
    result = build_layer_b_manual_validation_pack(
        input_path,
        mechanical_path=mechanical_path,
        expected_count=1,
        expected_descriptor_counts={"FAST_REENTRY": 1, "CHOP_AFTER_SWEEP_CANDIDATE": 0},
    )
    assert result.summary["excluded_reentry_not_reached_count"] == 1
    assert result.summary["excluded_not_enough_data_count"] == 1
    assert result.summary["excluded_missing_decision_time_bug_count"] == 1


def test_outputs_are_written_without_prefilling_manual_labels(tmp_path: Path):
    input_path, mechanical_path = _write_inputs(tmp_path, [_feature_row("FAST_001")])
    result = build_layer_b_manual_validation_pack(
        input_path,
        mechanical_path=mechanical_path,
        expected_count=1,
        expected_descriptor_counts={"FAST_REENTRY": 1, "CHOP_AFTER_SWEEP_CANDIDATE": 0},
    )
    paths = write_manual_validation_pack_outputs(result, tmp_path / "out")
    assert Path(paths["manual_validation_pack_csv"]).exists()
    assert Path(paths["summary_json"]).exists()
    assert Path(paths["readme_md"]).exists()
    written = pd.read_csv(paths["manual_validation_pack_csv"], keep_default_na=False)
    assert written["label_take_skip_uncertain"].eq("").all()


def test_no_forbidden_imports_or_runtime_paths_are_added():
    paths = [
        Path("dazro_trade/analytics/strategy_2_layer_b_manual_validation_pack.py"),
        Path("scripts/analyze_strategy_2_layer_b_manual_validation_pack.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden_strategy = "strategy" + "_3"
    forbidden_adelin = "dazro_trade." + "adelin"
    assert forbidden_strategy not in combined
    assert forbidden_adelin not in combined
    assert "order_send(" not in combined
    assert "telegram" not in combined or "telegram_operational_signals_sent" in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "profit_factor" not in combined
    assert "win_rate" not in combined


def test_import_safe_script():
    module = importlib.import_module("scripts.analyze_strategy_2_layer_b_manual_validation_pack")
    assert hasattr(module, "main")
    assert hasattr(module, "run")
