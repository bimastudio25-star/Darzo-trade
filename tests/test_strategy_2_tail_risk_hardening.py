from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

from dazro_trade.analytics.strategy_2_tail_risk_hardening import (
    build_tail_risk_hardening,
    conservative_sl_distance,
    enrich_samples,
    hardening_hypotheses,
    load_containing_samples,
    r_profile_for_samples,
    r_profiles_for_hypotheses,
    tail_bucket_profile,
    write_tail_risk_outputs,
)


def _row(model: str, key: str, mae: float, expansion: float, *, valid: bool = True, entry: bool = False, include_timing: bool = True) -> dict[str, object]:
    status = "VALID_SAMPLE_TRADE_TRIGGERED" if entry else "VALID_SAMPLE_NO_ENTRY_MAE_NOT_REACHED"
    if not valid:
        status = "INVALID_CURRENT_M15_SEQUENCE"
    row: dict[str, object] = {
        "sample_id": f"{key}_{model}",
        "symbol": "XAUUSD",
        "m15_filter_model": model,
        "h1_context_timestamp": "2026-05-19T10:00:00+00:00",
        "h1_context_end": "2026-05-19T11:00:00+00:00",
        "h1_reference_type": "dominant_h1" if key in {"k5", "k6"} else "previous_h1",
        "direction": "LONG" if int(key[-1]) % 2 else "SHORT",
        "h1_liquidity_level": 2400 + int(key[-1]),
        "h1_reference_range": 12 + int(key[-1]) * 3,
        "session": "London" if int(key[-1]) < 5 else "NY",
        "hour": 10 + int(key[-1]),
        "entry_valid": entry,
        "sample_status": status,
        "sample_reason_codes": status,
        "mae_reached": valid,
        "range_reentry_reached": entry,
        "manipulation_depth_usd": mae,
        "expansion_usd": expansion,
    }
    if include_timing:
        row.update(
            {
                "h1_level_take_timestamp": f"2026-05-19T10:{min(5 + int(key[-1]) * 5, 55):02d}:00+00:00",
                "mae_reached_timestamp": f"2026-05-19T10:{min(10 + int(key[-1]) * 5, 58):02d}:00+00:00",
                "range_reentry_timestamp": f"2026-05-19T10:{min(12 + int(key[-1]) * 5, 59):02d}:00+00:00",
            }
        )
    return row


def _samples(*, include_timing: bool = True) -> pd.DataFrame:
    fixtures = [
        ("k1", 4.0, 18.0, True),
        ("k2", 7.0, 21.0, False),
        ("k3", 10.0, 28.0, True),
        ("k4", 13.0, 26.0, False),
        ("k5", 24.0, 20.0, True),
        ("k6", 80.0, 30.0, True),
    ]
    rows = [_row("containing", key, mae, expansion, entry=entry, include_timing=include_timing) for key, mae, expansion, entry in fixtures]
    rows.extend(_row("approach_window", key, mae, expansion, entry=entry, include_timing=include_timing) for key, mae, expansion, entry in fixtures[:4])
    rows.append(_row("preceding", "k7", 120.0, 30.0, entry=True, include_timing=include_timing))
    return enrich_samples(pd.DataFrame(rows), pip_factor=10)


def test_tail_buckets_are_computed_correctly():
    valid = _samples().query("m15_filter_model == 'containing' and is_valid_sample == True")
    buckets = tail_bucket_profile(valid, pip_factor=10).set_index("bucket")
    assert buckets.loc["BODY_MAE_LE_8", "count"] == 2
    assert buckets.loc["BODY_MAE_LE_12", "count"] == 3
    assert buckets.loc["TAIL_MAE_GT_12", "count"] == 3
    assert buckets.loc["TAIL_MAE_GT_20", "count"] == 2
    assert buckets.loc["TAIL_MAE_GT_40", "count"] == 1


def test_hardening_hypotheses_report_kept_removed_body_tail_metrics():
    valid = _samples().query("m15_filter_model == 'containing' and is_valid_sample == True")
    hypotheses = hardening_hypotheses(valid, pip_factor=10)
    assert {"samples_kept", "samples_removed", "body_removed_pct", "tail_removed_pct", "tail_gt_20_removed_pct"}.issubset(hypotheses.columns)
    assert hypotheses["profit_or_pf_used"].eq(False).all()
    assert "NO_TRADE_IF_MAE_ABOVE_P90" in set(hypotheses["rule_name"])


def test_conservative_sl_and_r_profile_recompute_after_filtering():
    valid = _samples().query("m15_filter_model == 'containing' and is_valid_sample == True")
    raw = r_profile_for_samples(valid, label="RAW", pip_factor=10)
    filtered = valid[valid["manipulation_depth_usd"] <= 24]
    after = r_profile_for_samples(filtered, label="FILTERED", pip_factor=10)
    assert conservative_sl_distance(98.8) == 123.5
    assert raw["conservative_sl_usd"] == 100.0
    assert after["conservative_sl_usd"] == 30.0
    assert after["tp4_R"] != raw["tp4_R"]


def test_unit_conversion_usd_pips_is_explicit():
    valid = _samples().query("m15_filter_model == 'containing' and is_valid_sample == True")
    raw = r_profile_for_samples(valid, label="RAW", pip_factor=10)
    assert raw["max_excursion_usd"] == 80
    assert raw["max_excursion_pips"] == 800
    assert raw["pip_factor_used"] == 10


def test_r_profiles_for_hypotheses_include_raw_and_rules():
    valid = _samples().query("m15_filter_model == 'containing' and is_valid_sample == True")
    hypotheses = hardening_hypotheses(valid, pip_factor=10)
    profiles = r_profiles_for_hypotheses(valid, hypotheses, pip_factor=10)
    assert "RAW_CONTAINING" in set(profiles["profile_label"])
    assert "NO_TRADE_IF_MAE_ABOVE_P90" in set(profiles["profile_label"])


def test_missing_optional_timing_fields_are_handled_safely(tmp_path: Path):
    input_dir = tmp_path / "mechanical"
    input_dir.mkdir()
    _samples(include_timing=False).to_csv(input_dir / "corrected_mechanical_samples.csv", index=False)
    result = build_tail_risk_hardening(tmp_path / "containing", input_dir, pip_factor=10)
    assert result.summary["samples_loaded"] == 6
    assert not result.driver_breakdown.empty


def test_build_and_write_outputs(tmp_path: Path):
    mechanical = tmp_path / "mechanical"
    mechanical.mkdir()
    _samples().to_csv(mechanical / "corrected_mechanical_samples.csv", index=False)
    result = build_tail_risk_hardening(tmp_path / "containing", mechanical, pip_factor=10)
    paths = write_tail_risk_outputs(result, tmp_path / "output", docs_path=tmp_path / "doc.md")
    assert Path(paths["tail_bucket_profile"]).exists()
    assert Path(paths["hardening_hypotheses"]).exists()
    assert Path(paths["hardening_r_profile"]).exists()
    assert Path(paths["top_tail_cases"]).exists()
    assert Path(paths["docs"]).exists()


def test_missing_required_input_file_is_handled_clearly(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_containing_samples(tmp_path)


def test_verdict_does_not_claim_live_readiness(tmp_path: Path):
    mechanical = tmp_path / "mechanical"
    mechanical.mkdir()
    _samples().to_csv(mechanical / "corrected_mechanical_samples.csv", index=False)
    result = build_tail_risk_hardening(tmp_path / "containing", mechanical, pip_factor=10)
    assert "STRATEGY_2_REMAINS_RESEARCH_ONLY" in result.summary["verdict_flags"]
    assert "NO_LIVE_DEPLOYMENT_DECISION" in result.summary["verdict_flags"]
    text = result.report_markdown.lower()
    assert "live-ready" not in text
    assert "claim edge" not in text


def test_new_tail_risk_code_does_not_import_forbidden_modules_or_write_market_data():
    paths = [
        Path("dazro_trade/analytics/strategy_2_tail_risk_hardening.py"),
        Path("scripts/analyze_strategy_2_tail_risk_hardening.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden = "strategy" + "_3"
    assert forbidden not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "open(\"data/xauusd" not in combined
    assert "order_send(" not in combined


def test_importing_script_does_not_execute_analysis_automatically():
    module = importlib.import_module("scripts.analyze_strategy_2_tail_risk_hardening")
    assert hasattr(module, "main")
    assert hasattr(module, "run")
