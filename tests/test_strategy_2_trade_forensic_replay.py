from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.strategy_2_trade_forensic_replay import (
    build_trade_forensics,
    calculate_path_metrics,
    calculate_tp_sl,
    classify_timeout_root_cause,
    enrich_trade_forensics,
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
        "tp2": "110",
        "outcome": "TIMEOUT_CLOSE",
        "exit_time": "2026-05-19T14:05:00+00:00",
        "exit_price": "106",
        "r_multiple": "1.2",
        "mfe": "9.6",
        "mae": "1.0",
        "bars_held": "5",
    }
    row.update({key: str(value) for key, value in updates.items()})
    return row


def _diagnostics() -> dict[str, dict[str, object]]:
    return {
        "0": {
            "trade_id": "0",
            "first_m5_close_quality": "BAD_CLOSE",
            "reaction_state_3_m5": "REACTION_WEAK",
            "reaction_state_5_m5": "REACTION_WEAK",
            "retest_quality": "NO_RETEST",
            "entry_quality_label": "NO_TRADE_DIRTY_SETUP",
            "primary_blocker": "dirty_m5_context",
        }
    }


def _m1() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": "2026-05-19T14:00:00+00:00", "open": 100, "high": 104, "low": 99, "close": 103},
            {"time": "2026-05-19T14:01:00+00:00", "open": 103, "high": 108, "low": 102, "close": 107},
            {"time": "2026-05-19T14:02:00+00:00", "open": 107, "high": 109.5, "low": 106, "close": 108},
            {"time": "2026-05-19T14:03:00+00:00", "open": 108, "high": 108.5, "low": 98, "close": 99},
            {"time": "2026-05-19T14:04:00+00:00", "open": 99, "high": 101, "low": 96, "close": 100},
            {"time": "2026-05-19T14:05:00+00:00", "open": 100, "high": 106, "low": 99, "close": 106},
        ]
    )


def _m15() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": "2026-05-19T13:00:00+00:00", "open": 98, "high": 103, "low": 94, "close": 99},
            {"time": "2026-05-19T13:15:00+00:00", "open": 99, "high": 104, "low": 96, "close": 100},
            {"time": "2026-05-19T13:30:00+00:00", "open": 100, "high": 105, "low": 97, "close": 101},
            {"time": "2026-05-19T13:45:00+00:00", "open": 101, "high": 106, "low": 98, "close": 102},
        ]
    )


def test_tp_sl_distance_and_planned_rr_calculation():
    values = calculate_tp_sl(100, 95, 110, "LONG")
    assert values["sl_distance_usd"] == 5
    assert values["tp_distance_usd"] == 10
    assert values["planned_rr"] == 2
    assert values["tp_sl_ratio_label"] == "RR_GE_2"


def test_path_metrics_mfe_mae_thresholds_and_almost_hit_detection():
    metrics = calculate_path_metrics(
        path=_m1(),
        direction="LONG",
        entry=100,
        stop=95,
        target=110,
        exit_ts="2026-05-19T14:05:00+00:00",
    )
    assert metrics["mfe_usd"] == 9.5
    assert metrics["mae_usd"] == 4.0
    assert metrics["mfe_R"] == 1.9
    assert metrics["reached_1R"] is True
    assert metrics["reached_be_plus_10"] is False
    assert metrics["almost_hit_tp"] is True
    assert metrics["almost_hit_sl"] is False


def test_plus_10_15_20_detection_from_path():
    frame = pd.DataFrame(
        [
            {"time": "2026-05-19T14:00:00+00:00", "open": 100, "high": 121, "low": 99, "close": 118},
        ]
    )
    metrics = calculate_path_metrics(path=frame, direction="LONG", entry=100, stop=90, target=130, exit_ts="2026-05-19T14:00:00+00:00")
    assert metrics["reached_be_plus_10"] is True
    assert metrics["reached_partial_plus_15"] is True
    assert metrics["reached_partial_plus_20"] is True
    assert metrics["reached_2R"] is True


def test_timeout_root_cause_classification_target_too_far():
    record = {
        "outcome": "TIMEOUT_CLOSE",
        "entry_quality_label": "TRADE_NOW",
        "reaction_state_5_m5": "REACTION_WEAK",
        "mfe_R": 0.8,
        "mae_R": 0.2,
        "tp_realism_label": "TP_TOO_FAR",
        "almost_hit_tp": False,
    }
    assert classify_timeout_root_cause(record) == "TIMEOUT_TARGET_TOO_FAR"


def test_enrich_trade_forensics_exports_human_label_fields():
    record = enrich_trade_forensics(_trade(), row_index=0, m1=_m1(), m15=_m15(), diagnostics=_diagnostics())
    assert record["planned_rr"] == 2
    assert record["mfe_R"] == 1.9
    assert record["human_review_required"] is True
    assert "human_would_skip" in record
    assert record["screenshot_before_entry_path"] is None


def test_output_file_creation(tmp_path):
    report = build_trade_forensics(
        [_trade(), _trade(outcome="SL", r_multiple="-1", exit_price="95")],
        market_data={"M1": _m1(), "M15": _m15()},
        source_path="executed.csv",
    )
    paths = write_outputs(report, tmp_path, tmp_path / "doc.md")
    for value in paths.values():
        assert Path(value).exists()
    summary = json.loads((tmp_path / "strategy_2_trade_forensics_summary.json").read_text(encoding="utf-8"))
    assert summary["safety"]["order_send_called"] is False
    assert summary["source"]["trades_analyzed"] == 2
    assert (tmp_path / "strategy_2_human_label_pack.csv").exists()


def test_trade_forensic_module_and_script_have_no_live_order_or_telegram_calls():
    paths = [
        Path("dazro_trade/analytics/strategy_2_trade_forensic_replay.py"),
        Path("scripts/analyze_strategy_2_trade_forensics.py"),
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
