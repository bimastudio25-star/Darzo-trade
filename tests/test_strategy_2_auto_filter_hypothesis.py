from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.strategy_2_auto_filter_hypothesis import (
    build_body_tail_comparison,
    enrich_samples,
    generate_filter_hypotheses,
    top_tail_samples,
    valid_sample_frame,
    write_outputs,
    AnalysisResult,
    build_summary,
)


def _samples() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sample_id": "body_1",
                "direction": "LONG",
                "sample_status": "VALID_SAMPLE_NO_ENTRY_MANIPULATED_LESS",
                "valid_for_mae_dataset": True,
                "manipulation_depth_usd": 4.0,
                "distribution_distance_usd": 20.0,
                "h1_reference_range": 10.0,
                "h1_reference_type": "previous_h1",
                "m15_x45_sequence_valid": True,
                "reaction_confirmed": True,
                "session": "London",
                "hour": 8,
            },
            {
                "sample_id": "body_2",
                "direction": "SHORT",
                "sample_status": "VALID_SAMPLE_TRADE_TRIGGERED",
                "valid_for_mae_dataset": True,
                "manipulation_depth_usd": 9.5,
                "distribution_distance_usd": 18.0,
                "h1_reference_range": 12.0,
                "h1_reference_type": "previous_h1",
                "m15_x45_sequence_valid": True,
                "reaction_confirmed": True,
                "session": "London",
                "hour": 9,
            },
            {
                "sample_id": "tail_13",
                "direction": "LONG",
                "sample_status": "VALID_SAMPLE_TRADE_TRIGGERED",
                "valid_for_mae_dataset": True,
                "manipulation_depth_usd": 13.0,
                "distribution_distance_usd": 14.0,
                "h1_reference_range": 30.0,
                "h1_reference_type": "dominant_h1",
                "m15_x45_sequence_valid": True,
                "reaction_confirmed": False,
                "session": "Asia",
                "hour": 2,
            },
            {
                "sample_id": "tail_16",
                "direction": "SHORT",
                "sample_status": "VALID_SAMPLE_NO_ENTRY_MANIPULATED_LESS",
                "valid_for_mae_dataset": True,
                "manipulation_depth_usd": 16.0,
                "distribution_distance_usd": 10.0,
                "h1_reference_range": 40.0,
                "h1_reference_type": "dominant_h1",
                "m15_x45_sequence_valid": True,
                "reaction_confirmed": False,
                "session": "Asia",
                "hour": 3,
            },
            {
                "sample_id": "tail_25",
                "direction": "LONG",
                "sample_status": "VALID_SAMPLE_TRADE_TRIGGERED",
                "valid_for_mae_dataset": True,
                "manipulation_depth_usd": 25.0,
                "distribution_distance_usd": 8.0,
                "h1_reference_range": 60.0,
                "h1_reference_type": "dominant_h1",
                "m15_x45_sequence_valid": True,
                "reaction_confirmed": False,
                "session": "Asia",
                "hour": 4,
            },
        ]
    )


def test_strategy_2_auto_filter_body_tail_subsets_are_computed_correctly():
    enriched, _ = enrich_samples(_samples())
    valid = valid_sample_frame(enriched)
    assert int(valid["is_body_le_8"].sum()) == 1
    assert int(valid["is_body_le_10"].sum()) == 2
    assert int(valid["is_body_le_12"].sum()) == 2


def test_auto_filter_hypothesis_deep_tail_thresholds_work():
    enriched, _ = enrich_samples(_samples())
    valid = valid_sample_frame(enriched)
    assert int(valid["is_tail_gt_12"].sum()) == 3
    assert int(valid["is_tail_gt_15"].sum()) == 2
    assert int(valid["is_tail_gt_20"].sum()) == 1


def test_body_tail_top_max_tail_samples_are_selected_correctly():
    enriched, _ = enrich_samples(_samples())
    valid = valid_sample_frame(enriched)
    top = top_tail_samples(valid, n=2)
    assert top["sample_id"].tolist() == ["tail_25", "tail_16"]


def test_strategy_2_auto_filter_missing_optional_fields_do_not_crash():
    minimal = pd.DataFrame(
        [
            {"sample_id": "a", "sample_status": "VALID_SAMPLE_TRADE_TRIGGERED", "manipulation_depth_usd": 1.0},
            {"sample_id": "b", "sample_status": "VALID_SAMPLE_TRADE_TRIGGERED", "manipulation_depth_usd": 21.0},
        ]
    )
    enriched, missing = enrich_samples(minimal)
    valid = valid_sample_frame(enriched)
    comparison = build_body_tail_comparison(valid)
    hypotheses = generate_filter_hypotheses(valid)
    assert not comparison.empty
    assert not hypotheses.empty
    assert "session" in missing


def test_auto_filter_hypothesis_output_includes_kept_removed_metrics():
    enriched, _ = enrich_samples(_samples())
    valid = valid_sample_frame(enriched)
    hypotheses = generate_filter_hypotheses(valid)
    required = {"samples_kept", "samples_removed", "body_removed_pct", "tail_removed_pct", "optimization_used", "trading_signal_generated"}
    assert required.issubset(set(hypotheses.columns))
    assert hypotheses["optimization_used"].eq(False).all()
    assert hypotheses["trading_signal_generated"].eq(False).all()


def test_auto_filter_hypotheses_are_descriptive_not_profit_optimized():
    enriched, _ = enrich_samples(_samples())
    valid = valid_sample_frame(enriched)
    hypotheses = generate_filter_hypotheses(valid)
    combined_columns = " ".join(hypotheses.columns).lower()
    combined_rules = " ".join(hypotheses["rule_description"].astype(str).tolist()).lower()
    assert "profit" not in combined_columns
    assert "pf" not in combined_columns
    assert "profit factor" not in combined_rules
    assert "grid" not in combined_rules


def test_strategy_2_auto_filter_imports_do_not_reference_forbidden_modules_or_market_writes():
    paths = [
        Path("dazro_trade/analytics/strategy_2_auto_filter_hypothesis.py"),
        Path("scripts/analyze_strategy_2_auto_filter_hypotheses.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    assert "strategy_3" not in combined
    assert "data/xauusd" not in combined
    assert "order_send(" not in combined
    assert "telegram_send(" not in combined


def test_importing_script_does_not_execute_analysis_automatically():
    module = importlib.import_module("scripts.analyze_strategy_2_auto_filter_hypotheses")
    assert hasattr(module, "main")
    assert hasattr(module, "run")


def test_auto_filter_write_outputs_stays_in_requested_output_dir(tmp_path: Path):
    enriched, missing = enrich_samples(_samples())
    valid = valid_sample_frame(enriched)
    hypotheses = generate_filter_hypotheses(valid)
    result = AnalysisResult(
        samples=enriched,
        valid_samples=valid,
        body_tail_comparison=build_body_tail_comparison(valid),
        top_tail_samples=top_tail_samples(valid),
        hypotheses=hypotheses,
        summary=build_summary(enriched, valid, hypotheses, missing, 0.1),
        missing_features=missing,
        runtime_seconds=0.1,
    )
    paths = write_outputs(result, tmp_path)
    assert all(str(path).startswith(str(tmp_path)) for path in paths.values())
    assert (tmp_path / "filter_hypotheses.csv").exists()
