from __future__ import annotations

from dazro_trade.analytics.strategy_2_still_open_diagnostic import (
    SMOKE_RECOMMENDED,
    build_diagnostic,
    classify_still_open_policy_effect,
    render_markdown,
)


BASE_COLUMNS = [
    "timestamp",
    "symbol",
    "strategy",
    "direction",
    "entry",
    "stop",
    "sl_distance",
    "tp1",
    "outcome",
    "exit_price",
    "r_multiple",
    "mae",
    "mfe",
    "bars_held",
    "session",
]


def _row(strategy: str, outcome: str, **updates: object) -> dict[str, str]:
    row = {
        "timestamp": "2026-05-13T09:00:00+00:00",
        "symbol": "XAUUSD",
        "strategy": strategy,
        "direction": "LONG",
        "entry": "100",
        "stop": "95",
        "sl_distance": "5",
        "tp1": "110",
        "outcome": outcome,
        "exit_price": "110" if outcome == "TP1" else "",
        "r_multiple": "2" if outcome == "TP1" else "0",
        "mae": "2",
        "mfe": "8",
        "bars_held": "480",
        "session": "London",
    }
    row.update({key: str(value) for key, value in updates.items()})
    return row


def test_parsing_minimal_rows_and_outcome_distribution():
    report, _ = build_diagnostic(
        [
            _row("strategy_2_liquidity_expansion", "STILL_OPEN"),
            _row("strategy_2_liquidity_expansion", "TP1"),
        ],
        BASE_COLUMNS,
        {},
        executed_trades_path="executed.csv",
        summary_path="summary.json",
    )
    assert report["strategy_2"]["total_trades"] == 2
    assert report["strategy_2"]["outcome_distribution"] == {"STILL_OPEN": 1, "TP1": 1}
    assert report["strategy_2"]["still_open_percentage"] == 0.5


def test_missing_fields_produce_field_not_available_skip():
    columns = [col for col in BASE_COLUMNS if col not in {"setup_mode"}]
    report, _ = build_diagnostic(
        [_row("strategy_2_liquidity_expansion", "STILL_OPEN")],
        columns,
        {},
        executed_trades_path="executed.csv",
        summary_path="summary.json",
    )
    assert report["strategy_2"]["breakdowns"]["setup_mode"] == "field_not_available_skip"


def test_policy_effect_does_not_invent_missing_final_price():
    row = _row("strategy_2_liquidity_expansion", "STILL_OPEN", exit_price="")
    assert classify_still_open_policy_effect(row, set(BASE_COLUMNS)) == "cannot_reclassify_missing_final_price"


def test_metric_revision_flags_present_in_json_and_markdown():
    report, _ = build_diagnostic(
        [_row("strategy_2_liquidity_expansion", "STILL_OPEN")],
        BASE_COLUMNS,
        {},
        executed_trades_path="executed.csv",
        summary_path="summary.json",
    )
    md = render_markdown(report)
    assert report["metric_revision_due_to_still_open_policy"] is True
    assert "metric_revision_due_to_still_open_policy: true" in md


def test_cross_strategy_audit_distinguishes_policy_and_effective_impact():
    report, _ = build_diagnostic(
        [
            _row("strategy_1_adelin_scalp", "TP1"),
            _row("strategy_2_liquidity_expansion", "STILL_OPEN"),
        ],
        BASE_COLUMNS,
        {},
        executed_trades_path="executed.csv",
        summary_path="summary.json",
    )
    audit = {row["strategy"]: row for row in report["cross_strategy_still_open_audit"]}
    assert report["metric_revision_due_to_still_open_policy"] is True
    assert audit["strategy_1_adelin_scalp"]["metric_revision_effective_for_strategy"] is False
    assert audit["strategy_2_liquidity_expansion"]["metric_revision_effective_for_strategy"] is True


def test_mfe_mae_estimate_normalizes_price_units_and_negative_mae():
    report, estimates = build_diagnostic(
        [_row("strategy_2_liquidity_expansion", "STILL_OPEN", mae="-2", mfe="8", sl_distance="4")],
        BASE_COLUMNS,
        {},
        executed_trades_path="executed.csv",
        summary_path="summary.json",
    )
    assert estimates[0]["r_estimate_optimistic"] == 2.0
    assert estimates[0]["r_estimate_pessimistic"] == -0.5
    assert estimates[0]["r_estimate_midpoint"] == 0.75
    assert estimates[0]["r_estimate_range_width"] == 2.5
    assert report["mfe_mae_estimate"]["range_width_gt_1_5r_count"] == 1


def test_mfe_mae_missing_risk_does_not_crash():
    report, estimates = build_diagnostic(
        [_row("strategy_2_liquidity_expansion", "STILL_OPEN", sl_distance="")],
        BASE_COLUMNS,
        {},
        executed_trades_path="executed.csv",
        summary_path="summary.json",
    )
    assert estimates == []
    assert report["mfe_mae_estimate"]["count_without_mfe_mae"] == 1


def test_smoke_decision_triggers_for_still_open_rate_gt_10pct():
    report, _ = build_diagnostic(
        [
            _row("strategy_2_liquidity_expansion", "STILL_OPEN"),
            _row("strategy_2_liquidity_expansion", "TP1"),
        ],
        BASE_COLUMNS,
        {},
        executed_trades_path="executed.csv",
        summary_path="summary.json",
    )
    assert report["smoke_decision"]["decision"] == SMOKE_RECOMMENDED
    assert "strategy_2_still_open_rate_gt_10pct" in report["smoke_decision"]["triggers"]


def test_smoke_decision_triggers_for_missing_required_fields_gt_20pct():
    report, _ = build_diagnostic(
        [_row("strategy_2_liquidity_expansion", "STILL_OPEN", entry="")],
        BASE_COLUMNS,
        {},
        executed_trades_path="executed.csv",
        summary_path="summary.json",
    )
    assert "missing_required_fields_gt_20pct" in report["smoke_decision"]["triggers"]


def test_smoke_decision_triggers_for_wide_mfe_mae_ranges():
    report, _ = build_diagnostic(
        [
            _row("strategy_2_liquidity_expansion", "STILL_OPEN", mae="5", mfe="5", sl_distance="5"),
            _row("strategy_2_liquidity_expansion", "STILL_OPEN", mae="6", mfe="6", sl_distance="5"),
        ],
        BASE_COLUMNS,
        {},
        executed_trades_path="executed.csv",
        summary_path="summary.json",
    )
    assert "mfe_mae_range_width_gt_1_5r_for_gt_50pct" in report["smoke_decision"]["triggers"]
