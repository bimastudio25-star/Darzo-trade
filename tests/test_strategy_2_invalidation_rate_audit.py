from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.strategy_2_invalidation_rate_audit import (
    audit_directionality,
    build_h1_context_audit,
    build_invalidation_rate_audit,
    build_reason_distribution,
    build_sticky_audit,
    critical_assessment_text,
    reason_groups,
    write_invalidation_rate_outputs,
)


def _row(
    sample_id: str,
    *,
    context: str | None = None,
    direction: str = "LONG",
    final_state: str = "VALID_LONG",
    reason: str = "",
    long_invalidated: bool = False,
    short_invalidated: bool = False,
    attempted: bool = False,
    blocked: bool = False,
) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "h1_context_id": context or sample_id.split("_previous")[0],
        "direction_candidate": direction,
        "initial_state": "PENDING",
        "first_m15_side_taken": "M15_HIGH" if "HIGH" in reason else "M15_LOW" if "LOW" in reason else "UNKNOWN",
        "long_invalidated": long_invalidated,
        "short_invalidated": short_invalidated,
        "invalidation_reason": reason,
        "invalidation_timestamp": "",
        "final_state": final_state,
        "valid_until_timestamp": "",
        "opposite_side_taken_first": bool("OPPOSITE_M15" in reason),
        "same_h1_reactivation_attempted": attempted,
        "reactivation_blocked": blocked,
        "state_transition_log": f"PENDING -> {final_state}",
    }


def _fixture_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row("XAUUSD_20260520090000+0000_previous_h1_containing_LONG", final_state="VALID_LONG"),
            _row(
                "XAUUSD_20260520100000+0000_previous_h1_containing_LONG",
                final_state="INVALIDATED_LONG",
                reason="OPPOSITE_M15_HIGH_TAKEN_FIRST_FOR_LONG",
                long_invalidated=True,
                attempted=True,
                blocked=True,
            ),
            _row(
                "XAUUSD_20260520110000+0000_previous_h1_containing_SHORT",
                direction="SHORT",
                final_state="INVALIDATED_SHORT",
                reason="OPPOSITE_M15_LOW_TAKEN_FIRST_FOR_SHORT;MAE_NOT_REACHED",
                short_invalidated=True,
                attempted=True,
                blocked=True,
            ),
            _row(
                "XAUUSD_20260520120000+0000_previous_h1_containing_LONG",
                context="CTX_BOTH",
                final_state="FULLY_INVALIDATED",
                reason="OPPOSITE_M15_HIGH_TAKEN_FIRST_FOR_LONG;FULLY_INVALIDATED_H1_CONTEXT",
                long_invalidated=True,
                short_invalidated=True,
                attempted=True,
                blocked=True,
            ),
            _row(
                "XAUUSD_20260520120000+0000_dominant_h1_containing_SHORT",
                context="CTX_BOTH",
                direction="SHORT",
                final_state="FULLY_INVALIDATED",
                reason="OPPOSITE_M15_LOW_TAKEN_FIRST_FOR_SHORT;FULLY_INVALIDATED_H1_CONTEXT",
                long_invalidated=True,
                short_invalidated=True,
                attempted=True,
                blocked=True,
            ),
            _row(
                "XAUUSD_20260520130000+0000_previous_h1_containing_NO_LEVEL",
                direction="NO_LEVEL",
                final_state="FULLY_INVALIDATED",
                reason="H1_REFERENCE_ALREADY_CONSUMED",
                blocked=True,
            ),
        ]
    )


def test_invalidation_reason_grouping_works():
    assert reason_groups("OPPOSITE_M15_HIGH_TAKEN_FIRST_FOR_LONG;MAE_NOT_REACHED") == [
        "OPPOSITE_M15_HIGH_TAKEN_FIRST_FOR_LONG",
        "MAE_NOT_REACHED",
    ]
    assert reason_groups("") == ["UNKNOWN_OR_NONE"]
    assert reason_groups("SOMETHING_NEW") == ["OTHER"]


def test_directionality_for_long_and_short_is_correct():
    audit = audit_directionality(_fixture_frame())
    assert audit["long_m15_high_first_count"] == 2
    assert audit["short_m15_low_first_count"] == 2
    assert audit["long_direction_violation_count"] == 0
    assert audit["short_direction_violation_count"] == 0
    assert audit["directionality_confirmed"] is True


def test_directionality_detects_wrong_opposite_side():
    bad = pd.DataFrame(
        [
            _row(
                "XAUUSD_20260520140000+0000_previous_h1_containing_LONG",
                final_state="INVALIDATED_LONG",
                reason="OPPOSITE_M15_LOW_TAKEN_FIRST_FOR_SHORT",
                long_invalidated=True,
            )
        ]
    )
    audit = audit_directionality(bad)
    assert audit["long_direction_violation_count"] == 1
    assert audit["directionality_confirmed"] is False


def test_sticky_invalidation_remains_enforced():
    sticky = build_sticky_audit(_fixture_frame())
    assert sticky["sticky_violation"].sum() == 0
    assert sticky["reactivation_blocked"].sum() == 5


def test_h1_context_reset_and_no_cross_h1_contamination():
    contexts = build_h1_context_audit(_fixture_frame())
    assert contexts["potential_cross_h1_contamination"].sum() == 0
    assert bool(contexts.loc[contexts["h1_context_id"].eq("CTX_BOTH"), "fully_invalidated_has_both_directional_invalidations"].iloc[0]) is True


def test_h1_context_audit_flags_cross_h1_collision():
    frame = pd.DataFrame(
        [
            _row("A_previous_h1_containing_LONG", context="CTX"),
            _row("B_previous_h1_containing_SHORT", context="CTX", direction="SHORT"),
            _row("C_previous_h1_containing_LONG", context="CTX"),
        ]
    )
    contexts = build_h1_context_audit(frame)
    assert bool(contexts["potential_cross_h1_contamination"].iloc[0]) is True


def test_fully_invalidated_requires_both_directions_for_strict_interpretation():
    contexts = build_h1_context_audit(_fixture_frame())
    consumed = contexts[contexts["final_states"].str.contains("FULLY_INVALIDATED") & ~contexts["fully_invalidated_has_both_directional_invalidations"]]
    assert not consumed.empty
    assessment = critical_assessment_text(
        invalidation_rate=0.829,
        fully_contexts_without_both=len(consumed),
        directionality_confirmed=True,
        sticky_violations=0,
        cross_h1_flags=0,
    )
    assert assessment == "LIKELY_TOO_AGGRESSIVE_FULLY_INVALIDATED_IS_OVERLOADED"


def test_reason_distribution_counts_multiple_causes():
    distribution = build_reason_distribution(_fixture_frame()).set_index("reason_group")
    assert distribution.loc["OPPOSITE_M15_HIGH_TAKEN_FIRST_FOR_LONG", "sample_count"] == 2
    assert distribution.loc["OPPOSITE_M15_LOW_TAKEN_FIRST_FOR_SHORT", "sample_count"] == 2
    assert distribution.loc["MAE_NOT_REACHED", "sample_count"] == 1
    assert distribution.loc["H1_REFERENCE_ALREADY_CONSUMED", "sample_count"] == 1


def test_build_and_write_outputs_without_pnl_metrics(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _fixture_frame().to_csv(input_dir / "invalidation_state_machine_per_sample.csv", index=False)
    result = build_invalidation_rate_audit(input_dir)
    assert result.summary["pnl_metrics_generated"] is False
    assert result.summary["reaction_quality_derived"] is False
    assert result.summary["sticky_invalidation_confirmed"] is True
    paths = write_invalidation_rate_outputs(result, tmp_path / "output", docs_path=tmp_path / "doc.md")
    assert Path(paths["reason_distribution"]).exists()
    assert Path(paths["transition_examples"]).exists()
    assert Path(paths["h1_context_audit"]).exists()
    assert Path(paths["fully_invalidated_examples"]).exists()
    assert Path(paths["sticky_invalidation_audit"]).exists()
    assert Path(paths["summary"]).exists()
    assert Path(paths["report"]).exists()
    assert Path(paths["docs"]).exists()


def test_no_forbidden_imports_no_data_writes_no_signals_no_pnl():
    paths = [
        Path("dazro_trade/analytics/strategy_2_invalidation_rate_audit.py"),
        Path("scripts/analyze_strategy_2_invalidation_rate_audit.py"),
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
    module = importlib.import_module("scripts.analyze_strategy_2_invalidation_rate_audit")
    assert hasattr(module, "main")
    assert hasattr(module, "run")
