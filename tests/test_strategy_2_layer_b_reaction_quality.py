from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.strategy_2_layer_b_reaction_quality import (
    VALID_LAYER_A_STATES,
    build_layer_b_reaction_quality,
    build_future_data_audit,
    candidate_label_for_descriptor,
    classify_reaction_descriptor,
    usd_to_pips,
    write_layer_b_outputs,
)


def _state_row(sample_id: str, *, state: str, direction: str = "LONG") -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "h1_context_id": sample_id.split("_previous")[0],
        "direction_candidate": direction,
        "initial_state": "PENDING",
        "first_m15_side_taken": "UNKNOWN",
        "long_invalidated": False,
        "short_invalidated": False,
        "invalidation_reason": "",
        "invalidation_timestamp": "",
        "final_state": state,
        "valid_until_timestamp": "",
        "opposite_side_taken_first": False,
        "same_h1_reactivation_attempted": False,
        "reactivation_blocked": state not in VALID_LAYER_A_STATES,
        "state_transition_log": f"PENDING -> {state}",
    }


def _mechanical_row(
    sample_id: str,
    *,
    model: str = "containing",
    direction: str = "LONG",
    sweep: str = "2026-01-01T00:00:00+00:00",
    reentry: str | None = "2026-01-01T00:02:00+00:00",
) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "m15_filter_model": model,
        "direction": direction,
        "h1_context_timestamp": "2026-01-01T00:00:00+00:00",
        "h1_level_take_timestamp": sweep,
        "range_reentry_timestamp": reentry or "",
        "entry_timestamp": reentry or "",
        "h1_liquidity_level": 100.0,
        "range_reentry_reached": bool(reentry),
    }


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    valid_long = "XAUUSD_20260101000000+0000_previous_h1_containing_LONG"
    valid_short = "XAUUSD_20260101010000+0000_previous_h1_containing_SHORT"
    invalid = "XAUUSD_20260101020000+0000_previous_h1_containing_LONG"
    mae_missing = "XAUUSD_20260101030000+0000_previous_h1_containing_LONG"
    state_path = tmp_path / "state_split_per_sample.csv"
    pd.DataFrame(
        [
            _state_row(valid_long, state="VALID_LONG", direction="LONG"),
            _state_row(valid_short, state="VALID_SHORT", direction="SHORT"),
            _state_row(invalid, state="INVALIDATED_LONG", direction="LONG"),
            _state_row(mae_missing, state="MAE_NOT_REACHED", direction="LONG"),
        ]
    ).to_csv(state_path, index=False)
    mechanical_path = tmp_path / "corrected_mechanical_samples.csv"
    pd.DataFrame(
        [
            _mechanical_row(valid_long, direction="LONG"),
            _mechanical_row(valid_short, direction="SHORT", sweep="2026-01-01T01:00:00+00:00", reentry="2026-01-01T01:02:00+00:00"),
            _mechanical_row(invalid, direction="LONG", sweep="2026-01-01T02:00:00+00:00", reentry="2026-01-01T02:02:00+00:00"),
            _mechanical_row(mae_missing, direction="LONG", sweep="2026-01-01T03:00:00+00:00", reentry=None),
        ]
    ).to_csv(mechanical_path, index=False)
    data_dir = tmp_path / "data"
    symbol_dir = data_dir / "XAUUSD"
    symbol_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            ["2026.01.01 00:00", 100.0, 100.2, 99.4, 99.7, 1, 0],
            ["2026.01.01 00:01", 99.7, 100.4, 99.6, 100.1, 1, 0],
            ["2026.01.01 00:02", 100.1, 101.1, 100.0, 100.9, 1, 0],
            ["2026.01.01 00:03", 100.9, 101.4, 100.8, 101.2, 1, 0],
            ["2026.01.01 01:00", 100.0, 100.6, 99.7, 100.3, 1, 0],
            ["2026.01.01 01:01", 100.3, 100.4, 99.3, 99.8, 1, 0],
            ["2026.01.01 01:02", 99.8, 100.1, 98.8, 99.0, 1, 0],
            ["2026.01.01 01:03", 99.0, 99.2, 98.5, 98.7, 1, 0],
        ]
    ).to_csv(symbol_dir / "M1.csv", index=False, header=False)
    return state_path, mechanical_path, data_dir


def test_only_valid_long_and_valid_short_are_layer_b_eligible(tmp_path: Path):
    state_path, mechanical_path, data_dir = _write_fixture(tmp_path)
    result = build_layer_b_reaction_quality(state_path, data_dir=data_dir, mechanical_path=mechanical_path)
    eligible_states = set(result.per_sample[result.per_sample["layer_b_eligible"]]["layer_a_state"])
    assert eligible_states == {"VALID_LONG", "VALID_SHORT"}
    assert result.summary["eligible_valid_long_count"] == 1
    assert result.summary["eligible_valid_short_count"] == 1


def test_excluded_and_mae_not_reached_states_are_not_processed(tmp_path: Path):
    state_path, mechanical_path, data_dir = _write_fixture(tmp_path)
    result = build_layer_b_reaction_quality(state_path, data_dir=data_dir, mechanical_path=mechanical_path)
    excluded = result.per_sample[~result.per_sample["layer_b_eligible"]]
    assert set(excluded["layer_a_state"]) == {"INVALIDATED_LONG", "MAE_NOT_REACHED"}
    assert result.summary["mae_not_reached_count"] == 1
    assert excluded["reaction_descriptor"].eq("UNKNOWN").all()


def test_reaction_descriptors_are_candidate_descriptive_only(tmp_path: Path):
    state_path, mechanical_path, data_dir = _write_fixture(tmp_path)
    result = build_layer_b_reaction_quality(state_path, data_dir=data_dir, mechanical_path=mechanical_path)
    assert result.per_sample["layer_b_candidate_label"].str.endswith("_CANDIDATE").all()
    assert "draft_rule_label" not in result.per_sample.columns
    assert "user_decision" not in result.per_sample.columns
    assert result.summary["take_skip_decision_produced"] is False


def test_no_take_skip_decision_columns_are_produced_or_overwritten(tmp_path: Path):
    state_path, mechanical_path, data_dir = _write_fixture(tmp_path)
    state_frame = pd.read_csv(state_path)
    state_frame["draft_rule_label"] = "UNCHANGED"
    state_frame["user_decision"] = "UNCHANGED"
    state_frame.to_csv(state_path, index=False)
    result = build_layer_b_reaction_quality(state_path, data_dir=data_dir, mechanical_path=mechanical_path)
    assert "draft_rule_label" not in result.per_sample.columns
    assert "user_decision" not in result.per_sample.columns


def test_pip_conversion_usd_times_factor():
    assert usd_to_pips(12.8, 10) == 128.0


def test_every_feature_has_future_data_audit_flag():
    audit = build_future_data_audit()
    assert {"feature_name", "uses_future_data", "diagnostic_only"}.issubset(audit.columns)
    assert audit["uses_future_data"].notna().all()


def test_diagnostic_only_true_when_future_looking_data_is_used(tmp_path: Path):
    state_path, mechanical_path, data_dir = _write_fixture(tmp_path)
    result = build_layer_b_reaction_quality(state_path, data_dir=data_dir, mechanical_path=mechanical_path)
    future_rows = result.per_sample[result.per_sample["uses_future_data"]]
    assert not future_rows.empty
    assert future_rows["diagnostic_only"].all()
    audit_row = build_future_data_audit().set_index("feature_name").loc["acceleration_after_reentry_usd"]
    assert bool(audit_row["uses_future_data"]) is True
    assert bool(audit_row["diagnostic_only"]) is True
    assert bool(audit_row["allowed_for_candidate_label"]) is False


def test_no_outcome_columns_are_used_and_no_performance_metrics(tmp_path: Path):
    state_path, mechanical_path, data_dir = _write_fixture(tmp_path)
    state_frame = pd.read_csv(state_path)
    state_frame["actual_outcome"] = "TP1"
    state_frame["final_outcome_value"] = 1.0
    state_frame.to_csv(state_path, index=False)
    result = build_layer_b_reaction_quality(state_path, data_dir=data_dir, mechanical_path=mechanical_path)
    assert result.summary["outcome_columns_used"] is False
    assert result.summary["pnl_metrics_generated"] is False
    assert "actual_outcome" not in result.per_sample.columns
    assert "final_outcome_value" not in result.per_sample.columns


def test_descriptor_classifier_and_label_mapping():
    descriptor = classify_reaction_descriptor(
        range_reentry_detected="TRUE",
        time_to_reentry_seconds=120,
        reentry_distance_usd=1.0,
        rejection_wick_ratio=0.1,
        body_displacement_usd=0.2,
        micro_range_size_usd=2.0,
        clean_vs_dirty_path_candidate="CLEAN",
    )
    assert descriptor == "FAST_REENTRY"
    assert candidate_label_for_descriptor(descriptor) == "STRONG_REACTION_CANDIDATE"


def test_write_outputs_creates_required_files(tmp_path: Path):
    state_path, mechanical_path, data_dir = _write_fixture(tmp_path)
    result = build_layer_b_reaction_quality(state_path, data_dir=data_dir, mechanical_path=mechanical_path)
    paths = write_layer_b_outputs(result, tmp_path / "output", docs_path=tmp_path / "doc.md")
    for key in ["per_sample", "descriptor_distribution", "null_report", "future_data_audit", "summary", "report", "docs"]:
        assert Path(paths[key]).exists()


def test_no_forbidden_imports_no_data_writes_no_signal_generation_or_optimization():
    paths = [
        Path("dazro_trade/analytics/strategy_2_layer_b_reaction_quality.py"),
        Path("scripts/analyze_strategy_2_layer_b_reaction_quality.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden_strategy = "strategy" + "_3"
    forbidden_adelin = "dazro_trade." + "adelin"
    assert forbidden_strategy not in combined
    assert forbidden_adelin not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "open(\"data/xauusd" not in combined
    assert "order_send(" not in combined
    assert "generate_signal" not in combined
    assert "send_signal" not in combined
    assert "grid_search" not in combined
    assert "profit_factor" not in combined
    assert "win_rate" not in combined


def test_import_safe_script():
    module = importlib.import_module("scripts.analyze_strategy_2_layer_b_reaction_quality")
    assert hasattr(module, "main")
    assert hasattr(module, "run")
