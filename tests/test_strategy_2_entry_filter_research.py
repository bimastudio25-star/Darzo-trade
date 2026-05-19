from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.strategy_2_entry_filter_research import (
    audit_feature_timestamp,
    build_entry_filter_research,
    build_pre_entry_feature_rows,
    build_taxonomy_calibration,
    calibration_verdict_from_counts,
    run_simple_filter_tests,
    write_outputs,
)


def _executed_trade(**updates: object) -> dict[str, str]:
    row = {
        "timestamp": "2026-05-19T14:00:00+00:00",
        "symbol": "XAUUSD",
        "strategy": "strategy_2_liquidity_expansion",
        "direction": "LONG",
        "entry": "100",
        "stop": "95",
        "tp1": "105",
        "tp2": "110",
        "rr": "2",
        "outcome": "TP2",
        "r_multiple": "2",
        "session": "New York",
        "risk_label": "normal",
    }
    row.update({key: str(value) for key, value in updates.items()})
    return row


def _diagnostic(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "trade_id": "0",
        "entry_timestamp": "2026-05-19T14:00:00+00:00",
        "entry_quality_label": "TRADE_NOW",
        "reaction_state_5_m5": "REACTION_ALIVE",
        "target_space_proxy": 2.0,
        "r_multiple": 2.0,
        "outcome": "TP2",
    }
    row.update(updates)
    return row


def _m5() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": "2026-05-19T13:50:00+00:00", "open": 98, "high": 100, "low": 97, "close": 99},
            {"time": "2026-05-19T13:55:00+00:00", "open": 99, "high": 100, "low": 98, "close": 99.5},
            {"time": "2026-05-19T14:00:00+00:00", "open": 100, "high": 104, "low": 99, "close": 103},
            {"time": "2026-05-19T14:05:00+00:00", "open": 103, "high": 106, "low": 102, "close": 105},
            {"time": "2026-05-19T14:10:00+00:00", "open": 105, "high": 111, "low": 104, "close": 110},
            {"time": "2026-05-19T14:15:00+00:00", "open": 110, "high": 112, "low": 109, "close": 111},
            {"time": "2026-05-19T14:20:00+00:00", "open": 111, "high": 113, "low": 110, "close": 112},
        ]
    )


def _m15() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": "2026-05-19T13:15:00+00:00", "open": 97, "high": 99, "low": 96, "close": 98},
            {"time": "2026-05-19T13:30:00+00:00", "open": 98, "high": 99, "low": 97, "close": 98.5},
            {"time": "2026-05-19T13:45:00+00:00", "open": 98.5, "high": 100.5, "low": 98, "close": 99.5},
            {"time": "2026-05-19T14:00:00+00:00", "open": 100, "high": 105, "low": 99, "close": 104},
        ]
    )


def _market() -> dict[str, pd.DataFrame]:
    return {"M1": pd.DataFrame(), "M5": _m5(), "M15": _m15()}


def test_taxonomy_calibration_missing_data_behavior():
    calibration = build_taxonomy_calibration(
        strategy2_diagnostic_rows=[_diagnostic(entry_quality_label="NO_TRADE_DIRTY_SETUP")],
        strategy3_rows=None,
        strategy3_source_path=None,
        market_data=_market(),
    )
    assert calibration["verdict"] == "TAXONOMY_CALIBRATION_DATA_MISSING"
    assert "TAXONOMY_CALIBRATION_DATA_MISSING" in calibration["flags"]


def test_taxonomy_verdicts_too_strict_and_discriminating():
    too_strict = calibration_verdict_from_counts(
        strategy2_trade_now=1,
        strategy2_no_trade=56,
        strategy2_sample_size=57,
        strategy3_trade_now=2,
        strategy3_no_trade=28,
        strategy3_sample_size=30,
    )
    assert too_strict["verdict"] == "TAXONOMY_TOO_STRICT"
    discriminating = calibration_verdict_from_counts(
        strategy2_trade_now=1,
        strategy2_no_trade=56,
        strategy2_sample_size=57,
        strategy3_trade_now=10,
        strategy3_no_trade=15,
        strategy3_sample_size=30,
    )
    assert discriminating["verdict"] == "TAXONOMY_DISCRIMINATING"


def test_feature_timestamp_leakage_audit_rejects_post_entry_feature():
    safe = audit_feature_timestamp(
        "last_m5_close_quality_pre_entry",
        "2026-05-19T13:55:00+00:00",
        "2026-05-19T14:00:00+00:00",
    )
    unsafe = audit_feature_timestamp(
        "reaction_state_5_m5",
        "2026-05-19T14:25:00+00:00",
        "2026-05-19T14:00:00+00:00",
    )
    assert safe["is_pre_entry_safe"] is True
    assert unsafe["is_pre_entry_safe"] is False


def test_build_pre_entry_feature_rows_marks_m5_and_reaction_audit():
    features, audits = build_pre_entry_feature_rows(
        [_executed_trade()],
        [_diagnostic()],
        market_data=_market(),
    )
    assert features[0]["last_m5_close_quality_pre_entry"] in {"GOOD_CLOSE", "ACCEPTABLE_CLOSE", "BAD_CLOSE", "INVALIDATING_CLOSE"}
    assert any(row["feature_name"] == "reaction_state_5_m5" and row["is_pre_entry_safe"] is False for row in audits)
    assert any(row["feature_name"] == "last_m5_close_quality_pre_entry" and row["is_pre_entry_safe"] is True for row in audits)


def test_simple_filter_metrics_and_reaction_leakage_rejection():
    rows = [
        {"r_multiple": 1.0, "price_escape_pre_entry_proxy": False, "dirty_context_pre_entry_proxy": False, "target_space_lt_1R": False, "recent_m15_dead_context_proxy": False, "overextension_proxy": False, "too_close_to_obstacle_proxy": False, "entry_hour": 14, "reaction_state_5_m5": "REACTION_ALIVE"},
        {"r_multiple": -1.0, "price_escape_pre_entry_proxy": True, "dirty_context_pre_entry_proxy": True, "target_space_lt_1R": True, "recent_m15_dead_context_proxy": True, "overextension_proxy": True, "too_close_to_obstacle_proxy": True, "entry_hour": 9, "reaction_state_5_m5": "REACTION_DEAD"},
    ]
    results = run_simple_filter_tests(rows)
    price_escape = next(row for row in results if row["filter_name"] == "reject_price_escape_pre_entry")
    unsafe = next(row for row in results if row["filter_name"] == "rejected_post_entry_reaction_alive_filter")
    assert price_escape["n_kept"] == 1
    assert price_escape["kept_sample_label"] == "insufficient"
    assert unsafe["rejected_for_leakage"] is True
    assert unsafe["feature_safety_status"] == "unsafe_future_data_rejected"


def test_output_file_creation(tmp_path):
    report = build_entry_filter_research(
        strategy2_executed_rows=[_executed_trade(), _executed_trade(timestamp="2026-05-19T14:05:00+00:00", r_multiple="-1", outcome="SL")],
        strategy2_diagnostic_rows=[
            _diagnostic(trade_id="0", r_multiple=2.0, reaction_state_5_m5="REACTION_ALIVE"),
            _diagnostic(trade_id="1", entry_timestamp="2026-05-19T14:05:00+00:00", r_multiple=-1.0, outcome="SL", entry_quality_label="NO_TRADE_DIRTY_SETUP", reaction_state_5_m5="REACTION_DEAD"),
        ],
        strategy3_rows=None,
        strategy3_source_path=None,
        market_data=_market(),
        symbol="XAUUSD",
        source={"test": True},
    )
    paths = write_outputs(report, tmp_path, tmp_path / "doc.md")
    for value in paths.values():
        assert Path(value).exists()
    summary = json.loads((tmp_path / "strategy_2_entry_filter_summary.json").read_text(encoding="utf-8"))
    assert summary["safety"]["order_send_called"] is False
    assert "LEAKAGE_ATTEMPT_REJECTED" in summary["decision_matrix"]["verdict_flags"]


def test_entry_filter_script_and_module_have_no_live_order_or_telegram_calls():
    paths = [
        Path("dazro_trade/analytics/strategy_2_entry_filter_research.py"),
        Path("scripts/analyze_strategy_2_entry_filter_research.py"),
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


def test_script_import_safety_csv_loading(tmp_path):
    trades_path = tmp_path / "executed_trades.csv"
    with trades_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(_executed_trade().keys()))
        writer.writeheader()
        writer.writerow(_executed_trade())
    rows = list(csv.DictReader(trades_path.open(newline="", encoding="utf-8")))
    assert rows[0]["symbol"] == "XAUUSD"
