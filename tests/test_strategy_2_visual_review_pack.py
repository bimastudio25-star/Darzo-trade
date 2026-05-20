from __future__ import annotations

import csv
import importlib
from pathlib import Path

import pandas as pd

from dazro_trade.analysis.strategy_2_manual_sample_labels import MANUAL_LABEL_FIELDS
from dazro_trade.analysis.strategy_2_visual_review_pack import (
    annotate_hypothesis_flags,
    create_review_pack,
    hypothesis_thresholds,
    prefilled_manual_row,
    select_review_samples,
)
from dazro_trade.analytics.strategy_2_auto_filter_hypothesis import enrich_samples, valid_sample_frame


def _row(sample_id: str, manipulation: float, expansion: float, **updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "sample_id": sample_id,
        "symbol": "XAUUSD",
        "direction": "LONG",
        "h1_context_timestamp": "2026-05-11T10:00:00+00:00",
        "h1_reference_type": "previous_h1",
        "h1_reference_timestamp": "2026-05-11T09:00:00+00:00",
        "h1_reference_high": 2405.0,
        "h1_reference_low": 2395.0,
        "h1_reference_range": 10.0,
        "h1_liquidity_level": 2395.0,
        "m15_x45_timestamp": "2026-05-11T10:45:00+00:00",
        "m15_x45_high": 2403.0,
        "m15_x45_low": 2394.0,
        "m15_x45_sequence_valid": True,
        "h1_sweep_timestamp": "2026-05-11T10:15:00+00:00",
        "distribution_timestamp": "2026-05-11T11:00:00+00:00",
        "reaction_confirmed": True,
        "distribution_confirmed": True,
        "distribution_distance_usd": expansion,
        "distribution_distance_pips": expansion * 10,
        "manipulation_depth_usd": manipulation,
        "manipulation_depth_pips": manipulation * 10,
        "sample_status": "VALID_SAMPLE_TRADE_TRIGGERED",
        "valid_for_mae_dataset": True,
        "session": "London",
        "hour": 10,
    }
    row.update(updates)
    return row


def _valid_samples() -> pd.DataFrame:
    raw = pd.DataFrame(
        [
            _row("body_kept_1", 4.0, 24.0),
            _row("body_kept_2", 7.0, 21.0, direction="SHORT"),
            _row("body_removed_1", 6.0, 6.0),
            _row("body_removed_2", 11.0, 15.0),
            _row("tail_removed_1", 13.0, 14.0, h1_reference_type="dominant_h1"),
            _row("tail_removed_2", 18.0, 20.0, reaction_confirmed=False),
            _row("extreme_1", 25.0, 30.0, h1_reference_type="dominant_h1", reaction_confirmed=False),
            _row("extreme_2", 63.0, 64.0, direction="SHORT", h1_reference_type="dominant_h1"),
            _row("low_target_1", 5.0, 6.5),
            _row("missing_reaction_1", 8.0, 18.0, reaction_confirmed=False),
        ]
    )
    enriched, _ = enrich_samples(raw)
    return valid_sample_frame(enriched)


def _annotated() -> pd.DataFrame:
    thresholds = {"hyp_002_ratio_p25": 2.0, "hyp_006_target_space_p25": 3.0}
    return annotate_hypothesis_flags(_valid_samples(), thresholds)


def test_balanced_sample_selection_includes_body_and_tail_samples_when_available():
    selected = select_review_samples(_annotated(), max_samples=10)
    assert "body_kept" in set(selected["sample_type"])
    assert any(selected["manipulation_depth_usd"] <= 12)
    assert any(selected["manipulation_depth_usd"] > 12)


def test_hyp_002_false_positive_body_samples_can_be_selected():
    selected = select_review_samples(_annotated(), max_samples=10)
    body_removed = selected[selected["sample_type"].eq("body_removed_by_hyp2")]
    assert not body_removed.empty
    assert body_removed["manipulation_depth_usd"].le(12).all()
    assert body_removed["hyp_002_removed"].all()


def test_extreme_tail_samples_are_included_when_available():
    selected = select_review_samples(_annotated(), max_samples=10)
    assert any(selected["sample_type"].eq("extreme_tail"))
    assert selected["manipulation_depth_usd"].max() == 63.0


def test_prefilled_csv_row_contains_required_manual_label_fields_and_empty_grade():
    selected = select_review_samples(_annotated(), max_samples=1)
    row = prefilled_manual_row(selected.iloc[0], chart_ref="charts/S2_REVIEW_001_context.png")
    assert set(MANUAL_LABEL_FIELDS) == set(row.keys())
    assert row["manual_sample_id"] == "S2_REVIEW_001"
    assert row["source_type"] == "replay_label"
    assert row["user_grade"] == ""
    assert row["screenshot_ref"] == "charts/S2_REVIEW_001_context.png"


def test_missing_optional_hypothesis_files_do_not_crash_generation(tmp_path: Path):
    thresholds = hypothesis_thresholds(_valid_samples(), tmp_path / "missing_hypotheses")
    assert thresholds["hyp_002_ratio_p25"] is not None
    assert thresholds["hyp_006_target_space_p25"] is not None


def test_create_review_pack_outputs_stay_under_requested_output_dir(tmp_path: Path):
    samples_path = tmp_path / "h1_liquidity_samples.csv"
    pd.DataFrame([_row("body", 4.0, 24.0), _row("tail", 24.0, 25.0)]).to_csv(samples_path, index=False)
    output_dir = tmp_path / "review_pack"
    result = create_review_pack(
        symbol="XAUUSD",
        data_dir=tmp_path / "data",
        auto_samples_path=samples_path,
        hypotheses_dir=tmp_path / "hypotheses",
        output_dir=output_dir,
        max_samples=2,
        dry_run=True,
    )
    resolved_output = output_dir.resolve()
    assert result.samples_selected == 2
    assert (output_dir / "index.html").exists()
    assert (output_dir / "manual_samples_prefilled.csv").exists()
    assert all(Path(path).resolve().is_relative_to(resolved_output) for path in result.paths.values())
    with (output_dir / "manual_samples_prefilled.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["user_grade"] == ""


def test_importing_script_does_not_execute_generation_automatically():
    module = importlib.import_module("scripts.create_strategy_2_visual_review_pack")
    assert hasattr(module, "main")
    assert hasattr(module, "run")


def test_new_visual_review_code_does_not_import_forbidden_modules_or_write_market_data():
    paths = [
        Path("dazro_trade/analysis/strategy_2_visual_review_pack.py"),
        Path("scripts/create_strategy_2_visual_review_pack.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden = "strategy" + "_3"
    assert forbidden not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "open(\"data/xauusd" not in combined
    assert "order_send(" not in combined
    assert "telegram" not in combined or "telegram_enabled" in combined

