from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

from dazro_trade.analytics.strategy_2_m15_model_selection import (
    build_selection_review,
    disagreement_groups_table,
    enrich_samples,
    load_corrected_samples,
    model_counts,
    model_scorecard,
    review_candidates,
    tail_risk_table,
    write_selection_outputs,
)


def _row(model: str, key: str, valid: bool, mae: float, *, entry: bool = False, ref: str = "previous_h1") -> dict[str, object]:
    status = "VALID_SAMPLE_TRADE_TRIGGERED" if entry else "VALID_SAMPLE_NO_ENTRY_MAE_NOT_REACHED"
    if not valid:
        status = "INVALID_CURRENT_M15_SEQUENCE"
    return {
        "sample_id": f"{key}_{model}",
        "m15_filter_model": model,
        "h1_context_timestamp": f"2026-05-19T{10 + int(key[-1])}:00:00+00:00",
        "h1_reference_type": ref,
        "direction": "LONG" if int(key[-1]) % 2 else "SHORT",
        "h1_liquidity_level": 2400 + int(key[-1]),
        "m15_sequence_valid": valid,
        "old_x45_sequence_valid": key in {"k1", "k2", "k3"},
        "entry_valid": entry,
        "sample_status": status,
        "sample_reason_codes": status,
        "manipulation_depth_usd": mae,
        "expansion_usd": mae * 2,
    }


def _samples() -> pd.DataFrame:
    rows = []
    for key, valid_models, mae in [
        ("k1", {"containing", "preceding", "approach_window"}, 4.0),
        ("k2", {"preceding"}, 22.0),
        ("k3", {"containing", "approach_window"}, 9.0),
        ("k4", set(), 0.0),
        ("k5", {"containing"}, 13.0),
        ("k6", {"approach_window"}, 25.0),
    ]:
        for model in ("containing", "preceding", "approach_window"):
            rows.append(_row(model, key, model in valid_models, mae, entry=(model in valid_models and key in {"k1", "k2"}), ref="dominant_h1" if key == "k6" else "previous_h1"))
    return enrich_samples(pd.DataFrame(rows), pip_factor=10)


def test_loads_per_model_rows_from_corrected_samples(tmp_path: Path):
    path = tmp_path / "corrected_mechanical_samples.csv"
    _samples().to_csv(path, index=False)
    loaded = load_corrected_samples(tmp_path)
    assert set(loaded["m15_filter_model"]) == {"containing", "preceding", "approach_window"}
    assert len(loaded) == 18


def test_computes_model_counts_correctly():
    counts = model_counts(_samples()).set_index("m15_filter_model")
    assert counts.loc["containing", "corrected_sample_count"] == 3
    assert counts.loc["preceding", "corrected_sample_count"] == 2
    assert counts.loc["approach_window", "corrected_sample_count"] == 3
    assert counts.loc["preceding", "entry_triggered_count"] == 2


def test_tail_buckets_and_unit_conversion_are_correct():
    tail = tail_risk_table(_samples(), pip_factor=10).set_index("m15_filter_model")
    assert tail.loc["containing", "count_le_8_usd"] == 1
    assert tail.loc["containing", "count_gt_12_usd"] == 1
    assert tail.loc["approach_window", "count_gt_20_usd"] == 1
    assert tail.loc["approach_window", "max_excursion_pips"] == 250
    assert tail.loc["approach_window", "pip_factor_used"] == 10


def test_computes_disagreement_groups_correctly():
    groups = disagreement_groups_table(_samples()).set_index("disagreement_group")
    assert groups.loc["valid_in_all_three", "count"] == 1
    assert groups.loc["valid_in_preceding_only", "count"] == 1
    assert groups.loc["valid_in_containing_only", "count"] == 1
    assert groups.loc["valid_in_approach_window_only", "count"] == 1


def test_scorecard_does_not_select_model_based_only_on_entry_count():
    samples = _samples()
    tail = tail_risk_table(samples)
    groups = disagreement_groups_table(samples)
    old_new = pd.DataFrame(
        [
            {"m15_filter_model": "containing", "old_valid_new_invalid": 1, "old_invalid_new_valid": 1},
            {"m15_filter_model": "preceding", "old_valid_new_invalid": 1, "old_invalid_new_valid": 10},
            {"m15_filter_model": "approach_window", "old_valid_new_invalid": 1, "old_invalid_new_valid": 1},
        ]
    )
    scorecard, recommendation, flags = model_scorecard(samples, tail, old_new, groups)
    preceding = scorecard[scorecard["m15_filter_model"].eq("preceding")].iloc[0]
    assert preceding["entry_count_reported_not_scored"] == 2
    assert preceding["entry_count_note"]
    assert bool(preceding["profit_or_pf_used"]) is False
    assert recommendation != "RECOMMEND_PRECEDING_FOR_NEXT_DIAGNOSTIC"
    assert "PRECEDING_ENTRY_COUNT_NOT_SUFFICIENT_EVIDENCE" in flags


def test_review_candidates_are_exportable_for_disagreement_cases():
    candidates = review_candidates(_samples(), max_candidates=10)
    assert not candidates.empty
    assert "preceding_valid_containing_approach_invalid" in set(candidates["review_reason"])
    assert candidates["sample_key"].is_unique


def test_missing_required_input_file_is_handled_clearly(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_corrected_samples(tmp_path)


def test_build_review_and_write_outputs(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _samples().to_csv(input_dir / "corrected_mechanical_samples.csv", index=False)
    result = build_selection_review(input_dir, pip_factor=10)
    paths = write_selection_outputs(result, tmp_path / "output", docs_path=tmp_path / "doc.md")
    assert result.summary["rows_loaded"] == 18
    assert Path(paths["model_scorecard"]).exists()
    assert Path(paths["review_candidates"]).exists()
    assert Path(paths["docs"]).exists()


def test_new_m15_selection_code_does_not_import_forbidden_modules_or_write_market_data():
    paths = [
        Path("dazro_trade/analytics/strategy_2_m15_model_selection.py"),
        Path("scripts/analyze_strategy_2_m15_model_selection.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden = "strategy" + "_3"
    assert forbidden not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "open(\"data/xauusd" not in combined
    assert "order_send(" not in combined


def test_importing_script_does_not_execute_analysis_automatically():
    module = importlib.import_module("scripts.analyze_strategy_2_m15_model_selection")
    assert hasattr(module, "main")
    assert hasattr(module, "run")
