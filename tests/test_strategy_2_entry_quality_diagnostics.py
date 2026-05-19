from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.strategy_2_entry_quality_diagnostics import (
    build_entry_quality_diagnostic,
    classify_entry_quality_label,
    enrich_trade_entry_quality,
    read_executed_trades,
    slice_m5_after_entry,
    write_outputs,
)


def _trade(**updates: object) -> dict[str, str]:
    row = {
        "timestamp": "2026-05-19T14:00:00+00:00",
        "symbol": "XAUUSD",
        "strategy": "strategy_2_liquidity_expansion",
        "direction": "LONG",
        "entry": "100",
        "stop": "95",
        "tp1": "105",
        "tp2": "110",
        "outcome": "TP2",
        "r_multiple": "2",
        "session": "New York",
        "mfe": "12",
        "mae": "1",
        "bars_held": "20",
    }
    row.update({key: str(value) for key, value in updates.items()})
    return row


def _m5() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": "2026-05-19T13:55:00+00:00", "open": 99, "high": 100, "low": 98, "close": 99.5},
            {"time": "2026-05-19T14:00:00+00:00", "open": 100, "high": 105, "low": 99, "close": 104.5},
            {"time": "2026-05-19T14:05:00+00:00", "open": 104, "high": 105, "low": 99, "close": 100},
            {"time": "2026-05-19T14:10:00+00:00", "open": 100, "high": 101, "low": 94, "close": 94.5},
            {"time": "2026-05-19T14:15:00+00:00", "open": 94.5, "high": 99, "low": 94, "close": 98},
            {"time": "2026-05-19T14:20:00+00:00", "open": 98, "high": 102, "low": 97, "close": 101},
        ]
    )


def test_read_executed_trades_loads_csv(tmp_path):
    path = tmp_path / "executed_trades.csv"
    rows = [_trade()]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    loaded, columns = read_executed_trades(path)
    assert len(loaded) == 1
    assert "timestamp" in columns
    assert loaded[0]["strategy"] == "strategy_2_liquidity_expansion"


def test_m5_path_lookup_returns_first_closed_sequence_after_entry():
    window = slice_m5_after_entry(_m5(), "2026-05-19T14:00:00+00:00", count=3)
    assert len(window) == 3
    assert str(window.iloc[0]["time"]).startswith("2026-05-19 14:00:00")


def test_first_second_third_m5_close_diagnostics_are_exported():
    record = enrich_trade_entry_quality(_trade(), m5=_m5(), row_index=1)
    assert record["first_m5_close_quality"] == "GOOD_CLOSE"
    assert record["second_m5_close_quality"] == "BAD_CLOSE"
    assert record["third_m5_close_quality"] == "INVALIDATING_CLOSE"
    assert record["first_m5_close_reason_codes"]


def test_reaction_window_diagnostics_are_exported():
    record = enrich_trade_entry_quality(_trade(), m5=_m5(), row_index=1)
    assert record["reaction_state_3_m5"] in {"REACTION_ALIVE", "REACTION_WEAK", "REACTION_DEAD"}
    assert record["reaction_state_5_m5"] in {"REACTION_ALIVE", "REACTION_WEAK", "REACTION_DEAD"}
    assert record["mfe_3_m5_R"] is not None
    assert record["mae_5_m5_R"] is not None


def test_entry_quality_label_classification_prioritizes_reaction_dead():
    label, reasons, primary, secondary = classify_entry_quality_label(
        first_quality="BAD_CLOSE",
        reaction_state_3="REACTION_DEAD",
        target_space_R=2.0,
        price_escaped=False,
        retest_quality="NO_RETEST",
    )
    assert label == "NO_TRADE_REACTION_ALREADY_DEAD"
    assert "reaction_dead_within_3_m5" in reasons
    assert primary == "reaction_dead"
    assert secondary == "bad_first_m5_close"


def test_timeout_root_cause_classification_marks_no_follow_through():
    record = enrich_trade_entry_quality(
        _trade(outcome="TIMEOUT_CLOSE", r_multiple="-0.2", mfe="8", mae="6"),
        m5=_m5(),
        row_index=1,
    )
    assert record["timeout_root_cause"] in {"TIMEOUT_NO_FOLLOW_THROUGH", "TIMEOUT_TARGET_TOO_FAR", "TIMEOUT_CHOP", "TIMEOUT_UNKNOWN"}
    assert record["timeout_mfe_R"] is not None
    assert record["timeout_reason_codes"]


def test_output_file_creation(tmp_path):
    report = build_entry_quality_diagnostic(
        [_trade(), _trade(outcome="SL", r_multiple="-1")],
        market_data={"M5": _m5(), "M1": pd.DataFrame()},
        source_path="executed.csv",
    )
    paths = write_outputs(report, tmp_path, tmp_path / "doc.md")
    for value in paths.values():
        assert Path(value).exists()
    summary = json.loads((tmp_path / "strategy_2_entry_quality_summary.json").read_text(encoding="utf-8"))
    assert summary["source"]["trades_analyzed"] == 2
    assert summary["safety"]["order_send_called"] is False


def test_entry_quality_module_and_script_have_no_live_order_or_telegram_calls():
    paths = [
        Path("dazro_trade/analytics/strategy_2_entry_quality_diagnostics.py"),
        Path("scripts/analyze_strategy_2_entry_quality.py"),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    forbidden = [
        "order_send(",
        ".order_send",
        "send_message(",
        ".send_message",
        "send_signal(",
        ".send_signal",
        "send_text(",
        ".send_text",
        "run_telegram_polling(",
    ]
    for pattern in forbidden:
        assert pattern not in text
