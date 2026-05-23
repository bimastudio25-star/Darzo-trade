from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

from dazro_trade.analytics.strategy_2_layer_b_blinded_manual_validation_pack import (
    DEFAULT_SHUFFLE_SEED,
    DESCRIPTOR_REVEALING_VALUES,
    INDIRECT_LEAK_COLUMNS,
    build_strict_blinded_manual_validation_pack,
    write_strict_blinded_outputs,
)


def _source_row(index: int, descriptor: str) -> dict[str, object]:
    return {
        "pack_row_id": f"S2_LAYER_B_{index:04d}",
        "sample_id": f"S2_SAMPLE_{index:04d}",
        "symbol": "XAUUSD",
        "direction_candidate": "LONG" if index % 2 else "SHORT",
        "layer_a_state": "VALID_LONG" if index % 2 else "VALID_SHORT",
        "reaction_descriptor": descriptor,
        "entry_status_audit": "ENTRY_TRIGGERED_MAE_AND_RANGE_REENTRY",
        "h1_context_id": f"H1_CTX_{index:04d}",
        "h1_context_timestamp": "2026-05-01T10:00:00+00:00",
        "h1_liquidity_level": 2400.0 + index,
        "h1_level_take_timestamp": "2026-05-01T10:02:00+00:00",
        "range_reentry_timestamp": "2026-05-01T10:05:00+00:00",
        "entry_timestamp": "2026-05-01T10:05:00+00:00",
        "decision_time": f"2026-05-01T{10 + (index % 8):02d}:05:00+00:00",
        "data_window_start": "2026-05-01T10:02:00+00:00",
        "data_window_end": "2026-05-01T10:05:00+00:00",
        "time_to_reentry_seconds": 180 if descriptor == "FAST_REENTRY" else 720,
        "reentry_distance_usd": 1.2,
        "reentry_distance_pips": 12.0,
        "rejection_wick_ratio": 0.4,
        "body_displacement_usd": 0.7,
        "body_displacement_pips": 7.0,
        "micro_range_size_usd": 2.0,
        "micro_range_size_pips": 20.0,
        "clean_vs_dirty_path_candidate": "CLEAN" if descriptor == "FAST_REENTRY" else "DIRTY",
        "manipulation_depth_usd": 4.5,
        "manipulation_depth_pips": 45.0,
        "mae_avg_used_usd": 6.5,
        "mae_avg_used_pips": 65.0,
        "pip_factor_used": 10.0,
        "label_take_skip_uncertain": "",
        "manual_notes": "",
        "reviewer": "",
        "reviewed_at": "",
    }


def _valid_source_frame() -> pd.DataFrame:
    rows = [_source_row(index, "FAST_REENTRY") for index in range(1, 57)]
    rows.extend(_source_row(index, "CHOP_AFTER_SWEEP_CANDIDATE") for index in range(57, 136))
    return pd.DataFrame(rows)


def _write_source(tmp_path: Path, frame: pd.DataFrame | None = None) -> Path:
    path = tmp_path / "manual_validation_pack.csv"
    (frame if frame is not None else _valid_source_frame()).to_csv(path, index=False)
    return path


def _build(tmp_path: Path):
    return build_strict_blinded_manual_validation_pack(_write_source(tmp_path))


def test_blinded_and_answer_key_have_exactly_135_rows(tmp_path: Path):
    result = _build(tmp_path)
    assert len(result.blinded) == 135
    assert len(result.answer_key) == 135
    assert result.summary["blinded_row_count"] == 135
    assert result.summary["answer_key_row_count"] == 135


def test_sample_ids_match_between_blinded_and_answer_key(tmp_path: Path):
    result = _build(tmp_path)
    assert set(result.blinded["sample_id"]) == set(result.answer_key["sample_id"])


def test_original_and_shuffled_indices_present_in_both_outputs(tmp_path: Path):
    result = _build(tmp_path)
    for frame in [result.blinded, result.answer_key]:
        assert {"original_index", "shuffled_order_index"}.issubset(frame.columns)
    assert result.blinded["shuffled_order_index"].tolist() == sorted(result.blinded["shuffled_order_index"].tolist())


def test_blinded_order_differs_from_original_order(tmp_path: Path):
    source = _valid_source_frame()
    result = build_strict_blinded_manual_validation_pack(_write_source(tmp_path, source), shuffle_seed=DEFAULT_SHUFFLE_SEED)
    assert result.summary["row_order_changed"] is True
    assert result.blinded["sample_id"].tolist() != source["sample_id"].tolist()


def test_blinded_csv_contains_no_direct_descriptor_columns(tmp_path: Path):
    result = _build(tmp_path)
    lower_columns = {column.lower() for column in result.blinded.columns}
    assert "reaction_descriptor" not in lower_columns
    assert "descriptor" not in lower_columns
    assert "descriptor_category" not in lower_columns


def test_blinded_csv_contains_no_indirect_descriptor_leak_columns(tmp_path: Path):
    result = _build(tmp_path)
    lower_columns = {column.lower() for column in result.blinded.columns}
    assert lower_columns.isdisjoint(INDIRECT_LEAK_COLUMNS)
    assert not any("reentry_distance" in column for column in lower_columns)
    assert "time_to_reentry_seconds" not in lower_columns


def test_blinded_csv_contains_no_descriptor_revealing_values(tmp_path: Path):
    result = _build(tmp_path)
    combined = "\n".join(
        str(value).upper()
        for column in result.blinded.columns
        for value in result.blinded[column].astype(str).tolist()
    )
    for token in DESCRIPTOR_REVEALING_VALUES:
        assert token not in combined


def test_answer_key_contains_hidden_descriptor_mapping(tmp_path: Path):
    result = _build(tmp_path)
    assert {"reaction_descriptor", "layer_b_candidate_label", "clean_vs_dirty_path_candidate"}.issubset(result.answer_key.columns)
    assert result.answer_key["reaction_descriptor"].value_counts().to_dict() == {
        "CHOP_AFTER_SWEEP_CANDIDATE": 79,
        "FAST_REENTRY": 56,
    }


def test_manual_label_fields_are_blank(tmp_path: Path):
    result = _build(tmp_path)
    for column in ["label_take_skip_uncertain", "manual_notes", "reviewer", "reviewed_at"]:
        assert result.blinded[column].eq("").all()


def test_reentry_not_reached_rows_are_absent_and_source_would_fail(tmp_path: Path):
    result = _build(tmp_path)
    assert result.summary["reentry_not_reached_count_inside_blinded_csv"] == 0
    bad = _valid_source_frame()
    bad.loc[0, "reaction_descriptor"] = "NO_ENTRY_REENTRY_NOT_REACHED"
    with pytest.raises(ValueError, match="unexpected descriptors|REENTRY_NOT_REACHED"):
        build_strict_blinded_manual_validation_pack(_write_source(tmp_path, bad))


def test_missing_decision_time_rows_are_absent_and_source_would_fail(tmp_path: Path):
    result = _build(tmp_path)
    assert result.summary["missing_decision_time_count_inside_blinded_csv"] == 0
    bad = _valid_source_frame()
    bad.loc[0, "decision_time"] = ""
    with pytest.raises(ValueError, match="missing or unparseable decision_time"):
        build_strict_blinded_manual_validation_pack(_write_source(tmp_path, bad))


def test_readme_warns_adelin_not_to_open_answer_key_or_unblinded_pack(tmp_path: Path):
    result = _build(tmp_path)
    text = result.blinded_readme.lower()
    assert "open only `manual_validation_pack_blinded.csv`" in text
    assert "do not open the answer key" in text
    assert "do not open the unblinded pack" in text


def test_outputs_written_to_blind_and_answer_key_directories(tmp_path: Path):
    result = _build(tmp_path)
    paths = write_strict_blinded_outputs(result, tmp_path / "out")
    for path in paths.values():
        assert Path(path).exists()
    blinded = pd.read_csv(paths["blinded_csv"], keep_default_na=False)
    assert len(blinded) == 135
    assert blinded["label_take_skip_uncertain"].eq("").all()
    assert "reaction_descriptor" not in blinded.columns


def test_no_forbidden_imports_or_runtime_paths_are_added():
    paths = [
        Path("dazro_trade/analytics/strategy_2_layer_b_blinded_manual_validation_pack.py"),
        Path("scripts/create_strategy_2_layer_b_strict_blinded_manual_validation_pack.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden_strategy = "strategy" + "_3"
    forbidden_adelin = "dazro_trade." + "adelin"
    assert forbidden_strategy not in combined
    assert forbidden_adelin not in combined
    assert "order_send(" not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "profit_factor" not in combined
    assert "win_rate" not in combined
    assert "grid_search" not in combined


def test_import_safe_script():
    module = importlib.import_module("scripts.create_strategy_2_layer_b_strict_blinded_manual_validation_pack")
    assert hasattr(module, "main")
    assert hasattr(module, "run")
