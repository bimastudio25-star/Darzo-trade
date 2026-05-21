from __future__ import annotations

import importlib
import json
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.strategy_2_unit_distance_audit import (
    build_unit_distance_audit,
    pips_to_price,
    price_to_pips,
    write_unit_distance_outputs,
)


def _write_distance_fixture(root: Path) -> Path:
    root.mkdir()
    frame = pd.DataFrame(
        [
            {
                "max_excursion_usd": 180.93,
                "max_excursion_pips": 1809.3,
                "conservative_sl_usd": 226.1625,
                "conservative_sl_pips": 2261.625,
                "p90_tp4_distance_usd": 30.918,
                "p90_tp4_distance_pips": 309.18,
                "tp4_distance_usd": 67.19,
                "tp4_distance_pips": 671.9,
                "mae_avg_usd": 12.798,
                "mae_avg_pips": 127.98,
                "tp4_R": 0.3749,
            }
        ]
    )
    path = root / "containing_risk_profile.csv"
    frame.to_csv(path, index=False)
    return path


def test_pip_conversion_rule_is_explicit():
    assert price_to_pips(9.88, 10) == 98.8
    assert pips_to_price(98.8, 10) == 9.88
    assert price_to_pips(180.93, 10) == 1809.3
    assert pips_to_price(1809.3, 10) == 180.93


def test_usd_fields_are_audited_as_xauusd_price_distance_when_paired(tmp_path: Path):
    input_dir = tmp_path / "input"
    _write_distance_fixture(input_dir)
    result = build_unit_distance_audit([input_dir], pip_factor=10)
    audit = result.audit_rows.set_index("field")

    max_excursion = audit.loc["max_excursion_usd"]
    assert max_excursion["interpreted_as"] == "xauusd_price_distance"
    assert max_excursion["price_distance_usd"] == 180.93
    assert max_excursion["pips"] == 1809.3
    assert "equals max_excursion_usd * pip_factor" in max_excursion["pair_evidence"]

    tp4 = audit.loc["tp4_distance_usd"]
    assert tp4["price_distance_usd"] == 67.19
    assert tp4["pips"] == 671.9
    assert tp4["corrected_label"] == "XAUUSD price-distance units; pips = price_distance * pip_factor"


def test_r_profile_is_dimensionless_and_does_not_change_after_unit_correction(tmp_path: Path):
    input_dir = tmp_path / "input"
    _write_distance_fixture(input_dir)
    result = build_unit_distance_audit([input_dir], pip_factor=10)
    audit = result.audit_rows.set_index("field")

    tp4_r = audit.loc["tp4_R"]
    assert tp4_r["interpreted_as"] == "dimensionless_ratio"
    assert pd.isna(tp4_r["price_distance_usd"])
    assert tp4_r["r_profile_changes_after_correction"] == "NO"
    assert result.summary["r_profile_changes_after_correction"].startswith("NO;")


def test_corrected_summary_reports_key_values_and_follow_up(tmp_path: Path):
    input_dir = tmp_path / "input"
    _write_distance_fixture(input_dir)
    result = build_unit_distance_audit([input_dir], pip_factor=10)

    corrected = result.summary["corrected_key_values"]
    assert corrected["max_excursion_usd"]["price_distance_usd"] == 180.93
    assert corrected["max_excursion_usd"]["pips"] == 1809.3
    assert corrected["conservative_sl_usd"]["pips"] == 2261.625
    assert corrected["tp4_distance_usd"]["pips"] == 671.9
    assert result.summary["unit_semantics_verdict"] == "RAW_DISTANCE_VALUES_ARE_XAUUSD_PRICE_DISTANCE_NOT_PIPS"
    assert result.summary["pips_mislabeled_as_usd_found"] is False
    assert result.summary["usd_label_ambiguity_found"] is True
    assert result.summary["recommended_follow_up_branch"] == "fix/strategy-2-distance-label-normalization"


def test_writes_required_audit_outputs(tmp_path: Path):
    input_dir = tmp_path / "input"
    _write_distance_fixture(input_dir)
    result = build_unit_distance_audit([input_dir], pip_factor=10)
    paths = write_unit_distance_outputs(result, tmp_path / "output", docs_path=tmp_path / "docs" / "audit.md")

    assert Path(paths["audit_csv"]).exists()
    assert Path(paths["summary"]).exists()
    assert Path(paths["report"]).exists()
    assert Path(paths["docs"]).exists()

    summary = json.loads(Path(paths["summary"]).read_text(encoding="utf-8"))
    assert summary["pair_mismatch_count"] == 0
    assert "strategy_2_unit_distance_audit" in paths["report"]


def test_new_unit_audit_code_does_not_import_forbidden_modules_or_write_market_data():
    paths = [
        Path("dazro_trade/analytics/strategy_2_unit_distance_audit.py"),
        Path("scripts/audit_strategy_2_distance_units.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden = "strategy" + "_3"
    assert forbidden not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "open(\"data/xauusd" not in combined
    assert "order_send(" not in combined


def test_importing_script_does_not_execute_analysis_automatically():
    module = importlib.import_module("scripts.audit_strategy_2_distance_units")
    assert hasattr(module, "main")
    assert hasattr(module, "run")
