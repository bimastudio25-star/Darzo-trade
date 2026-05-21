from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

from dazro_trade.analytics.strategy_2_containing_model_diagnostic import (
    build_containing_diagnostic,
    conservative_sl_distance,
    containing_vs_approach_table,
    enrich_samples,
    load_mechanical_samples,
    risk_profile_table,
    tp_quartiles,
    tp_r_profile_table,
    write_containing_diagnostic_outputs,
)


def _row(model: str, key: str, valid: bool, mae: float, expansion: float, *, entry: bool = False) -> dict[str, object]:
    status = "VALID_SAMPLE_TRADE_TRIGGERED" if entry else "VALID_SAMPLE_NO_ENTRY_MAE_NOT_REACHED"
    if not valid:
        status = "INVALID_CURRENT_M15_SEQUENCE"
    return {
        "sample_id": f"{key}_{model}",
        "symbol": "XAUUSD",
        "m15_filter_model": model,
        "h1_context_timestamp": f"2026-05-19T{10 + int(key[-1])}:00:00+00:00",
        "h1_reference_type": "previous_h1",
        "direction": "LONG" if int(key[-1]) % 2 else "SHORT",
        "h1_liquidity_level": 2400 + int(key[-1]),
        "h1_level_take_timestamp": "2026-05-19T10:05:00+00:00" if valid else "",
        "mae_reached": entry,
        "range_reentry_reached": entry,
        "m15_sequence_valid": valid,
        "entry_valid": entry,
        "entry_status": "ENTRY_TRIGGERED_MAE_AND_RANGE_REENTRY" if entry else "NO_ENTRY_MAE_NOT_REACHED",
        "sample_status": status,
        "sample_reason_codes": status,
        "manipulation_depth_usd": mae,
        "expansion_usd": expansion,
    }


def _samples() -> pd.DataFrame:
    rows = []
    fixtures = [
        ("k1", {"containing", "approach_window", "preceding"}, 4.0, 20.0, True),
        ("k2", {"containing", "approach_window"}, 12.0, 40.0, False),
        ("k3", {"containing"}, 24.0, 60.0, True),
        ("k4", {"preceding"}, 35.0, 25.0, True),
    ]
    for key, valid_models, mae, expansion, entry in fixtures:
        for model in ("containing", "approach_window", "preceding"):
            rows.append(_row(model, key, model in valid_models, mae, expansion, entry=(model in valid_models and entry)))
    return enrich_samples(pd.DataFrame(rows), pip_factor=10)


def test_loads_containing_and_approach_window_rows(tmp_path: Path):
    _samples().to_csv(tmp_path / "corrected_mechanical_samples.csv", index=False)
    loaded = load_mechanical_samples(tmp_path)
    assert set(loaded["m15_filter_model"]) == {"containing", "approach_window", "preceding"}
    result = build_containing_diagnostic(tmp_path, pip_factor=10)
    assert result.summary["containing_samples_loaded"] == 4
    assert result.summary["approach_window_samples_loaded"] == 4


def test_excludes_preceding_from_primary_decision_but_reports_rejection():
    result = build_containing_diagnostic_from_frame(_samples())
    assert result.summary["primary_model"] == "containing"
    assert result.summary["sensitivity_model"] == "approach_window"
    assert result.summary["rejected_model_summary"]["m15_filter_model"] == "preceding"
    assert result.summary["rejected_model_summary"]["status"] == "rejected_for_now_as_too_permissive"


def test_computes_risk_buckets_and_conservative_sl():
    risk = risk_profile_table(_samples(), pip_factor=10).set_index("m15_filter_model")
    assert risk.loc["containing", "count_le_8_usd"] == 1
    assert risk.loc["containing", "count_le_12_usd"] == 2
    assert risk.loc["containing", "count_gt_20_usd"] == 1
    assert risk.loc["containing", "max_excursion_usd"] == 24
    assert risk.loc["containing", "conservative_sl_usd"] == 30
    assert conservative_sl_distance(98.8) == 123.5


def test_tp_distances_are_h1_anchored_and_unit_conversion_is_explicit():
    tp = tp_r_profile_table(_samples(), pip_factor=10).set_index("m15_filter_model")
    assert tp.loc["containing", "tp_anchor"] == "H1_LIQUIDITY_LEVEL"
    assert bool(tp.loc["containing", "tp_anchor_is_entry"]) is False
    assert tp.loc["containing", "tp1_distance_usd"] == 15
    assert tp.loc["containing", "tp4_distance_usd"] == 60
    assert tp.loc["containing", "tp1_distance_pips"] == 150
    assert tp.loc["containing", "pip_factor_used"] == 10
    assert tp_quartiles(80) == {"tp1": 20, "tp2": 40, "tp3": 60, "tp4": 80}


def test_containing_vs_approach_window_comparison():
    samples = _samples()
    risk = risk_profile_table(samples)
    tp_r = tp_r_profile_table(samples)
    comparison = containing_vs_approach_table(samples, risk, tp_r).iloc[0]
    assert comparison["overlap_valid"] == 2
    assert comparison["containing_only_valid"] == 1
    assert comparison["approach_window_only_valid"] == 0
    assert comparison["shared_entries"] == 1


def test_output_verdict_does_not_claim_live_readiness(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _samples().to_csv(input_dir / "corrected_mechanical_samples.csv", index=False)
    result = build_containing_diagnostic(input_dir)
    assert "STRATEGY_2_REMAINS_RESEARCH_ONLY" in result.summary["verdict_flags"]
    assert "NO_LIVE_DEPLOYMENT_DECISION" in result.summary["verdict_flags"]
    text = result.report_markdown.lower()
    assert "live ready" not in text
    assert "deployable" not in text


def test_build_and_write_outputs(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _samples().to_csv(input_dir / "corrected_mechanical_samples.csv", index=False)
    result = build_containing_diagnostic(input_dir)
    paths = write_containing_diagnostic_outputs(result, tmp_path / "output", docs_path=tmp_path / "doc.md")
    assert Path(paths["summary"]).exists()
    assert Path(paths["entry_diagnostics"]).exists()
    assert Path(paths["risk_profile"]).exists()
    assert Path(paths["tp_r_profile"]).exists()
    assert Path(paths["comparison"]).exists()
    assert Path(paths["docs"]).exists()


def test_missing_required_input_file_is_handled_clearly(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_mechanical_samples(tmp_path)


def test_new_containing_diagnostic_code_does_not_import_forbidden_modules_or_write_market_data():
    paths = [
        Path("dazro_trade/analytics/strategy_2_containing_model_diagnostic.py"),
        Path("scripts/analyze_strategy_2_containing_model_diagnostic.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden = "strategy" + "_3"
    assert forbidden not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "open(\"data/xauusd" not in combined
    assert "order_send(" not in combined


def test_importing_script_does_not_execute_analysis_automatically():
    module = importlib.import_module("scripts.analyze_strategy_2_containing_model_diagnostic")
    assert hasattr(module, "main")
    assert hasattr(module, "run")


def build_containing_diagnostic_from_frame(frame: pd.DataFrame):
    tmp = Path.cwd() / ".pytest_tmp_containing_diagnostic"
    tmp.mkdir(exist_ok=True)
    try:
        frame.to_csv(tmp / "corrected_mechanical_samples.csv", index=False)
        return build_containing_diagnostic(tmp)
    finally:
        target = tmp / "corrected_mechanical_samples.csv"
        if target.exists():
            target.unlink()
        try:
            tmp.rmdir()
        except OSError:
            pass
