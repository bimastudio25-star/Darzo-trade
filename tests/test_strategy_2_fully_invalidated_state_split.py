from __future__ import annotations

import importlib
import json
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.strategy_2_fully_invalidated_state_split import (
    build_fully_invalidated_state_split,
    critical_conclusion,
    write_state_split_outputs,
)
from dazro_trade.analytics.strategy_2_invalidation_state_machine import (
    STATE_H1_CONTEXT_ALREADY_CONSUMED,
    STATE_MAE_NOT_REACHED,
    STATE_STRUCTURE_INVALID,
    STATE_TRUE_DUAL_DIRECTION_INVALIDATED,
    STATE_UNKNOWN_INVALIDATION_STATE,
    STATE_FULLY_INVALIDATED,
)


def _row(sample_id: str, *, skip: str = "", take: str = "H1_REFERENCE_VALID;H1_SWEEP_CONFIRMED", uncertain: str = "") -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "rulebook_v0_label": "SKIP" if skip else "UNCERTAIN",
        "skip_rules_triggered": skip,
        "take_rules_passed": take,
        "uncertain_rules_triggered": uncertain,
    }


def _split_fixture(tmp_path: Path) -> tuple[Path, Path]:
    rulebook = tmp_path / "rulebook_v0_per_sample.csv"
    pd.DataFrame(
        [
            _row("XAUUSD_20260520140000+0000_previous_h1_containing_LONG", skip="INVALID_CURRENT_M15_HIGH_TAKEN_FIRST_FOR_LONG"),
            _row("XAUUSD_20260520140000+0000_dominant_h1_containing_SHORT", skip="INVALID_CURRENT_M15_LOW_TAKEN_FIRST_FOR_SHORT"),
            _row("XAUUSD_20260520150000+0000_previous_h1_containing_NO_LEVEL", skip="H1_REFERENCE_ALREADY_CONSUMED"),
            _row("XAUUSD_20260520160000+0000_previous_h1_containing_LONG", uncertain="MAE_NOT_REACHED"),
            _row("XAUUSD_20260520170000+0000_previous_h1_containing_SHORT", skip="DOUBLE_SWEEP_DEGRADATION"),
            _row("MALFORMED_SAMPLE_ID", take=""),
        ]
    ).to_csv(rulebook, index=False)
    input_dir = tmp_path / "state_machine"
    input_dir.mkdir()
    (input_dir / "invalidation_state_machine_summary.json").write_text(
        json.dumps({"input_path": str(rulebook), "fully_invalidated_count": 256}),
        encoding="utf-8",
    )
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    (audit_dir / "invalidation_rate_summary.json").write_text(json.dumps({"fully_invalidated_count": 256}), encoding="utf-8")
    return input_dir, audit_dir


def test_state_split_separates_true_dual_h1_mae_structure_and_unknown(tmp_path: Path):
    input_dir, audit_dir = _split_fixture(tmp_path)
    result = build_fully_invalidated_state_split(input_dir, audit_dir)
    counts = result.per_sample["final_state"].value_counts().to_dict()
    assert counts[STATE_TRUE_DUAL_DIRECTION_INVALIDATED] == 2
    assert counts[STATE_H1_CONTEXT_ALREADY_CONSUMED] == 1
    assert counts[STATE_MAE_NOT_REACHED] == 1
    assert counts[STATE_STRUCTURE_INVALID] == 1
    assert counts[STATE_UNKNOWN_INVALIDATION_STATE] == 1
    assert STATE_FULLY_INVALIDATED not in counts


def test_true_dual_requires_both_directional_invalidations(tmp_path: Path):
    input_dir, audit_dir = _split_fixture(tmp_path)
    result = build_fully_invalidated_state_split(input_dir, audit_dir)
    true_dual = result.per_sample[result.per_sample["final_state"].eq(STATE_TRUE_DUAL_DIRECTION_INVALIDATED)]
    assert true_dual["long_invalidated"].all()
    assert true_dual["short_invalidated"].all()
    assert true_dual["invalidation_reason"].str.contains("TRUE_DUAL_DIRECTION_INVALIDATION").all()


def test_h1_consumed_and_mae_not_reached_do_not_count_as_true_dual(tmp_path: Path):
    input_dir, audit_dir = _split_fixture(tmp_path)
    result = build_fully_invalidated_state_split(input_dir, audit_dir)
    subset = result.per_sample[result.per_sample["final_state"].isin({STATE_H1_CONTEXT_ALREADY_CONSUMED, STATE_MAE_NOT_REACHED})]
    assert not subset.empty
    assert subset["long_invalidated"].eq(False).all()
    assert subset["short_invalidated"].eq(False).all()


def test_sticky_cross_h1_and_directionality_audits_remain_clean(tmp_path: Path):
    input_dir, audit_dir = _split_fixture(tmp_path)
    result = build_fully_invalidated_state_split(input_dir, audit_dir)
    assert result.summary["sticky_violations"] == 0
    assert result.summary["cross_h1_contamination_flags"] == 0
    assert result.summary["direction_violations"] == 0


def test_critical_conclusion_reports_overload_resolved_when_true_dual_drops():
    assert (
        critical_conclusion(
            old_fully_count=256,
            true_dual_count=2,
            sticky_violations=0,
            cross_h1_flags=0,
            direction_violations=0,
        )
        == "FULLY_INVALIDATED_OVERLOAD_RESOLVED_LAYER_A_TAXONOMY_CLEARER"
    )


def test_write_outputs_creates_required_files(tmp_path: Path):
    input_dir, audit_dir = _split_fixture(tmp_path)
    result = build_fully_invalidated_state_split(input_dir, audit_dir)
    paths = write_state_split_outputs(result, tmp_path / "output", docs_path=tmp_path / "doc.md")
    for key in [
        "per_sample",
        "distribution",
        "true_dual_direction_examples",
        "h1_consumed_examples",
        "mae_not_reached_examples",
        "structure_invalid_examples",
        "summary",
        "report",
        "docs",
    ]:
        assert Path(paths[key]).exists()


def test_no_forbidden_imports_no_data_writes_no_signals_or_performance_metrics():
    paths = [
        Path("dazro_trade/analytics/strategy_2_fully_invalidated_state_split.py"),
        Path("scripts/analyze_strategy_2_fully_invalidated_state_split.py"),
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
    assert "profit_factor" not in combined
    assert "r_multiple" not in combined


def test_import_safe_script():
    module = importlib.import_module("scripts.analyze_strategy_2_fully_invalidated_state_split")
    assert hasattr(module, "main")
    assert hasattr(module, "run")
