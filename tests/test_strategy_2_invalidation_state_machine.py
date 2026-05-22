from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.strategy_2_invalidation_state_machine import (
    STATE_FULLY_INVALIDATED,
    STATE_H1_CONTEXT_ALREADY_CONSUMED,
    STATE_INVALIDATED_LONG,
    STATE_INVALIDATED_SHORT,
    STATE_MAE_NOT_REACHED,
    STATE_STRUCTURE_INVALID,
    STATE_TRUE_DUAL_DIRECTION_INVALIDATED,
    STATE_UNKNOWN_INVALIDATION_STATE,
    STATE_VALID_LONG,
    STATE_VALID_SHORT,
    apply_state_machine,
    build_invalidation_state_machine,
    parse_direction,
    parse_h1_context_id,
    write_state_machine_outputs,
)


def _row(sample_id: str, *, skip: str = "", take: str = "H1_REFERENCE_VALID;H1_SWEEP_CONFIRMED;RANGE_REENTRY_REACHED", uncertain: str = "") -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "rulebook_v0_label": "SKIP" if skip else "UNCERTAIN",
        "skip_rules_triggered": skip,
        "take_rules_passed": take,
        "uncertain_rules_triggered": uncertain,
    }


def test_long_invalidates_if_m15_high_taken_first():
    frame = pd.DataFrame([_row("XAUUSD_20260520090000+0000_previous_h1_containing_LONG", skip="INVALID_CURRENT_M15_HIGH_TAKEN_FIRST_FOR_LONG")])
    result = apply_state_machine(frame).iloc[0]
    assert result["final_state"] == STATE_INVALIDATED_LONG
    assert result["first_m15_side_taken"] == "M15_HIGH"
    assert bool(result["long_invalidated"]) is True
    assert "OPPOSITE_M15_HIGH_TAKEN_FIRST_FOR_LONG" in result["invalidation_reason"]


def test_short_invalidates_if_m15_low_taken_first():
    frame = pd.DataFrame([_row("XAUUSD_20260520100000+0000_previous_h1_containing_SHORT", skip="INVALID_CURRENT_M15_LOW_TAKEN_FIRST_FOR_SHORT")])
    result = apply_state_machine(frame).iloc[0]
    assert result["final_state"] == STATE_INVALIDATED_SHORT
    assert result["first_m15_side_taken"] == "M15_LOW"
    assert bool(result["short_invalidated"]) is True
    assert "OPPOSITE_M15_LOW_TAKEN_FIRST_FOR_SHORT" in result["invalidation_reason"]


def test_invalidation_is_sticky_and_reactivation_blocked():
    frame = pd.DataFrame(
        [
            _row(
                "XAUUSD_20260520110000+0000_previous_h1_containing_LONG",
                skip="INVALID_CURRENT_M15_HIGH_TAKEN_FIRST_FOR_LONG",
                take="H1_REFERENCE_VALID;H1_SWEEP_CONFIRMED;M15_SEQUENCE_VALID;RANGE_REENTRY_REACHED;MAE_REACHED_IN_ALLOWED_ZONE",
            )
        ]
    )
    result = apply_state_machine(frame).iloc[0]
    assert bool(result["same_h1_reactivation_attempted"]) is True
    assert bool(result["reactivation_blocked"]) is True
    assert result["final_state"] == STATE_INVALIDATED_LONG


def test_valid_states_do_not_reactivate_invalidated_direction():
    frame = pd.DataFrame(
        [
            _row("XAUUSD_20260520120000+0000_previous_h1_containing_LONG", skip=""),
            _row("XAUUSD_20260520130000+0000_previous_h1_containing_SHORT", skip=""),
        ]
    )
    result = apply_state_machine(frame).set_index("direction_candidate")
    assert result.loc["LONG", "final_state"] == STATE_VALID_LONG
    assert result.loc["SHORT", "final_state"] == STATE_VALID_SHORT
    assert result["reactivation_blocked"].eq(False).all()


def test_fully_invalidated_state_works_for_same_h1_context():
    frame = pd.DataFrame(
        [
            _row("XAUUSD_20260520140000+0000_previous_h1_containing_LONG", skip="INVALID_CURRENT_M15_HIGH_TAKEN_FIRST_FOR_LONG"),
            _row("XAUUSD_20260520140000+0000_dominant_h1_containing_SHORT", skip="INVALID_CURRENT_M15_LOW_TAKEN_FIRST_FOR_SHORT"),
        ]
    )
    result = apply_state_machine(frame)
    assert set(result["final_state"]) == {STATE_TRUE_DUAL_DIRECTION_INVALIDATED}
    assert result["long_invalidated"].all()
    assert result["short_invalidated"].all()
    assert result["reactivation_blocked"].all()
    assert STATE_FULLY_INVALIDATED not in set(result["final_state"])


def test_h1_consumed_is_not_true_dual_direction_invalidation():
    frame = pd.DataFrame([_row("XAUUSD_20260520141000+0000_previous_h1_containing_NO_LEVEL", skip="H1_REFERENCE_ALREADY_CONSUMED")])
    result = apply_state_machine(frame).iloc[0]
    assert result["final_state"] == STATE_H1_CONTEXT_ALREADY_CONSUMED
    assert bool(result["long_invalidated"]) is False
    assert bool(result["short_invalidated"]) is False


def test_mae_not_reached_is_separate_terminal_state():
    frame = pd.DataFrame([_row("XAUUSD_20260520142000+0000_previous_h1_containing_LONG", uncertain="MAE_NOT_REACHED")])
    result = apply_state_machine(frame).iloc[0]
    assert result["final_state"] == STATE_MAE_NOT_REACHED
    assert bool(result["long_invalidated"]) is False
    assert bool(result["short_invalidated"]) is False


def test_structure_invalid_is_separate_from_directional_and_h1_consumed():
    frame = pd.DataFrame([_row("XAUUSD_20260520143000+0000_previous_h1_containing_LONG", skip="DOUBLE_SWEEP_DEGRADATION")])
    result = apply_state_machine(frame).iloc[0]
    assert result["final_state"] == STATE_STRUCTURE_INVALID
    assert bool(result["long_invalidated"]) is False
    assert "DOUBLE_SWEEP_DEGRADATION" in result["invalidation_reason"]


def test_unknown_invalidation_state_fallback_works():
    frame = pd.DataFrame([_row("MALFORMED_SAMPLE_ID", skip="", take="", uncertain="")])
    result = apply_state_machine(frame).iloc[0]
    assert result["final_state"] == STATE_UNKNOWN_INVALIDATION_STATE


def test_state_transitions_logged_correctly():
    frame = pd.DataFrame([_row("XAUUSD_20260520150000+0000_previous_h1_containing_LONG", skip="INVALID_CURRENT_M15_HIGH_TAKEN_FIRST_FOR_LONG")])
    result = apply_state_machine(frame).iloc[0]
    assert result["state_transition_log"].startswith("PENDING -> VALID_LONG -> INVALIDATED_LONG")


def test_h1_context_and_direction_parsing():
    assert parse_direction("XAUUSD_20260520150000+0000_previous_h1_containing_LONG") == "LONG"
    assert parse_h1_context_id("XAUUSD_20260520150000+0000_previous_h1_containing_LONG") == "XAUUSD_20260520150000+0000"


def test_build_and_write_outputs(tmp_path: Path):
    input_path = tmp_path / "rulebook_v0_per_sample.csv"
    pd.DataFrame(
        [
            _row("XAUUSD_20260520160000+0000_previous_h1_containing_LONG", skip="INVALID_CURRENT_M15_HIGH_TAKEN_FIRST_FOR_LONG"),
            _row("XAUUSD_20260520170000+0000_previous_h1_containing_SHORT", skip=""),
        ]
    ).to_csv(input_path, index=False)
    result = build_invalidation_state_machine(input_path)
    assert result.summary["samples_processed"] == 2
    assert result.summary["pnl_metrics_generated"] is False
    paths = write_state_machine_outputs(result, tmp_path / "output", docs_path=tmp_path / "doc.md")
    assert Path(paths["per_sample"]).exists()
    assert Path(paths["distribution"]).exists()
    assert Path(paths["summary"]).exists()
    assert Path(paths["report"]).exists()
    assert Path(paths["docs"]).exists()


def test_no_strategy_3_imports_no_data_writes_no_signal_generation():
    paths = [
        Path("dazro_trade/analytics/strategy_2_invalidation_state_machine.py"),
        Path("scripts/analyze_strategy_2_invalidation_state_machine.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden = "strategy" + "_3"
    assert forbidden not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "open(\"data/xauusd" not in combined
    assert "order_send(" not in combined
    assert "telegram_bot" not in combined
    assert "generate_signal" not in combined
    assert "send_signal" not in combined


def test_importing_script_is_safe():
    module = importlib.import_module("scripts.analyze_strategy_2_invalidation_state_machine")
    assert hasattr(module, "main")
    assert hasattr(module, "run")
