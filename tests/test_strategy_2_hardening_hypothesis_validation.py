from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

from dazro_trade.analytics.strategy_2_hardening_hypothesis_validation import (
    EX_POST_UPPER_BOUND_NAME,
    build_hypothesis_validation,
    enrich_samples,
    leakage_audit,
    load_validation_samples,
    proxy_validation_results,
    r_profile_for_samples,
    write_hypothesis_validation_outputs,
)


def _row(key: str, mae: float, expansion: float, *, model: str = "containing", entry: bool = True) -> dict[str, object]:
    minute = min(5 + int(key[-1]) * 5, 55)
    return {
        "sample_id": f"{key}_{model}",
        "symbol": "XAUUSD",
        "m15_filter_model": model,
        "h1_context_timestamp": "2026-05-19T10:00:00+00:00",
        "h1_context_end": "2026-05-19T11:00:00+00:00",
        "h1_reference_type": "dominant_h1" if key in {"k5", "k6"} else "previous_h1",
        "direction": "LONG" if int(key[-1]) % 2 else "SHORT",
        "h1_liquidity_level": 2400 + int(key[-1]),
        "h1_reference_range": 10 + int(key[-1]) * 6,
        "dominant_contains_internal_count": 2 if key in {"k5", "k6"} else 0,
        "session": "NY" if int(key[-1]) >= 5 else "London",
        "hour": 14 if key in {"k5", "k6"} else 4 if key == "k4" else 10,
        "h1_level_take_timestamp": f"2026-05-19T10:{minute:02d}:00+00:00",
        "mae_reached_timestamp": f"2026-05-19T10:{min(minute + 2, 58):02d}:00+00:00",
        "range_reentry_timestamp": f"2026-05-19T10:{min(minute + 4, 59):02d}:00+00:00",
        "entry_valid": entry,
        "sample_status": "VALID_SAMPLE_TRADE_TRIGGERED" if entry else "VALID_SAMPLE_NO_ENTRY_MAE_NOT_REACHED",
        "sample_reason_codes": "ENTRY_TRIGGERED_MAE_AND_RANGE_REENTRY" if entry else "NO_ENTRY_MAE_NOT_REACHED",
        "manipulation_depth_usd": mae,
        "expansion_usd": expansion,
    }


def _samples() -> pd.DataFrame:
    rows = [
        _row("k1", 4.0, 20.0),
        _row("k2", 7.0, 28.0),
        _row("k3", 10.0, 30.0),
        _row("k4", 14.0, 7.0),
        _row("k5", 30.0, 6.0),
        _row("k6", 80.0, 8.0),
        _row("k7", 18.0, 36.0),
        _row("k8", 24.0, 12.0),
    ]
    rows.append(_row("k1", 4.0, 20.0, model="preceding"))
    return enrich_samples(pd.DataFrame(rows), pip_factor=10)


def _write_fixture(path: Path) -> None:
    path.mkdir()
    _samples().to_csv(path / "corrected_mechanical_samples.csv", index=False)


def test_expost_ratio_is_marked_non_deployable_upper_bound():
    samples = _samples().query("m15_filter_model == 'containing' and is_valid_sample == True")
    results = proxy_validation_results(samples, pip_factor=10)
    upper = results[results["proxy_name"].eq(EX_POST_UPPER_BOUND_NAME)].iloc[0]
    assert upper["leakage_flag"] == "LEAKAGE_FEATURE"
    assert bool(upper["uses_only_pre_entry_data"]) is False
    assert upper["verdict"] == "REJECTED_LEAKAGE"


def test_leakage_features_are_excluded_from_proxy_validation():
    audit = leakage_audit().set_index("feature")
    assert audit.loc["expansion_mae_ratio", "leakage_flag"] == "LEAKAGE_FEATURE"
    assert audit.loc["expansion_usd", "uses_only_pre_entry_data"] is False or audit.loc["expansion_usd", "uses_only_pre_entry_data"] == False
    samples = _samples().query("m15_filter_model == 'containing' and is_valid_sample == True")
    clean = proxy_validation_results(samples).query("leakage_flag == ''")
    assert EX_POST_UPPER_BOUND_NAME not in set(clean["proxy_name"])


def test_pre_entry_proxy_metrics_body_and_tail_are_computed():
    samples = _samples().query("m15_filter_model == 'containing' and is_valid_sample == True")
    results = proxy_validation_results(samples, pip_factor=10)
    row = results[results["proxy_name"].eq("H1_RANGE_GT_P75")].iloc[0]
    assert row["uses_only_pre_entry_data"] is True or row["uses_only_pre_entry_data"] == True
    assert row["samples_flagged"] > 0
    assert row["body_false_positive_pct"] >= 0
    assert row["tail_gt_20_caught_pct"] >= 0
    assert row["body_le_12_removed_pct"] == row["body_false_positive_pct"]


def test_r_profile_is_recomputed_after_proxy_filtering():
    samples = _samples().query("m15_filter_model == 'containing' and is_valid_sample == True")
    raw = r_profile_for_samples(samples, label="RAW")
    filtered = samples[samples["h1_reference_range"] <= samples["h1_reference_range"].quantile(0.50)]
    after = r_profile_for_samples(filtered, label="FILTERED")
    assert raw["max_excursion_usd"] == 80
    assert after["max_excursion_usd"] < raw["max_excursion_usd"]
    assert after["conservative_sl_usd"] < raw["conservative_sl_usd"]


def test_no_proxy_is_selected_by_pnl_or_pf():
    samples = _samples().query("m15_filter_model == 'containing' and is_valid_sample == True")
    results = proxy_validation_results(samples)
    assert results["profit_or_pf_used"].eq(False).all()


def test_build_and_write_outputs(tmp_path: Path):
    mechanical = tmp_path / "mechanical"
    _write_fixture(mechanical)
    result = build_hypothesis_validation(tmp_path / "tail", tmp_path / "containing", mechanical, pip_factor=10)
    paths = write_hypothesis_validation_outputs(result, tmp_path / "output", docs_path=tmp_path / "doc.md")
    assert result.summary["samples_loaded"] == 8
    assert Path(paths["feature_summary"]).exists()
    assert Path(paths["proxy_results"]).exists()
    assert Path(paths["r_profile_impact"]).exists()
    assert Path(paths["leakage_audit"]).exists()
    assert Path(paths["ex_post_upper_bound"]).exists()
    assert Path(paths["docs"]).exists()


def test_missing_required_input_file_is_handled_clearly(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_validation_samples(tmp_path)


def test_verdict_does_not_claim_live_readiness(tmp_path: Path):
    mechanical = tmp_path / "mechanical"
    _write_fixture(mechanical)
    result = build_hypothesis_validation(tmp_path / "tail", tmp_path / "containing", mechanical, pip_factor=10)
    text = result.report_markdown.lower()
    assert "STRATEGY_2_REMAINS_RESEARCH_ONLY" in result.summary["verdict_flags"]
    assert "NO_LIVE_DEPLOYMENT_DECISION" in result.summary["verdict_flags"]
    assert "live-ready" not in text
    assert "deployable filter" not in text


def test_new_validation_code_does_not_import_forbidden_modules_or_write_market_data():
    paths = [
        Path("dazro_trade/analytics/strategy_2_hardening_hypothesis_validation.py"),
        Path("scripts/analyze_strategy_2_hardening_hypothesis_validation.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden = "strategy" + "_3"
    assert forbidden not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "open(\"data/xauusd" not in combined
    assert "order_send(" not in combined


def test_importing_script_does_not_execute_analysis_automatically():
    module = importlib.import_module("scripts.analyze_strategy_2_hardening_hypothesis_validation")
    assert hasattr(module, "main")
    assert hasattr(module, "run")
