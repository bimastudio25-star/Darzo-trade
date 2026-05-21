from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dazro_trade.analytics.strategy_3_overtrading_diagnostics import (
    build_overtrading_diagnostic,
    category_significance,
    cluster_impact,
    group_metrics,
    trade_density,
)
from dazro_trade.backtest.reports import _flatten_signal
from dazro_trade.backtest.simulator import BacktestSignal


COLUMNS = [
    "timestamp",
    "symbol",
    "strategy",
    "strategy_name",
    "direction",
    "entry",
    "stop",
    "tp1",
    "outcome",
    "r_multiple",
    "setup_mode",
    "band_touched",
    "vwap",
    "vwap_distance",
    "vwap_distance_pips",
    "session",
    "reason_codes",
    "confluences",
    "liquidity_context",
    "sweep_timeframe",
    "sweep_type",
    "sweep_price",
    "risk_distance",
    "rr",
]


def _row(i: int, **updates: object) -> dict[str, str]:
    ts = datetime(2026, 5, 11, 9, tzinfo=timezone.utc) + timedelta(minutes=5 * i)
    row = {
        "timestamp": ts.isoformat(),
        "symbol": "XAUUSD",
        "strategy": "strategy_3_vwap_1r",
        "strategy_name": "strategy_3_vwap_1r",
        "direction": "LONG" if i % 2 == 0 else "SHORT",
        "entry": "100",
        "stop": "99",
        "tp1": "101",
        "outcome": "TP1" if i % 2 == 0 else "SL",
        "r_multiple": "1" if i % 2 == 0 else "-1",
        "setup_mode": "reversal",
        "band_touched": "sigma_1_lower",
        "vwap": json.dumps({"vwap": 100.0}),
        "vwap_distance": "2.0",
        "vwap_distance_pips": "20.0",
        "session": "London",
        "reason_codes": "liquidity_sweep;vwap_band_sigma_1_lower;target_1r",
        "confluences": json.dumps({"vwap": {"band": "sigma_1_lower"}, "number_theory": False}),
        "liquidity_context": json.dumps({"scope": "internal", "sweep": {"side": "sell_side"}, "level": 99.0}),
        "sweep_timeframe": "M5",
        "sweep_type": "sell_side",
        "sweep_price": "99",
        "risk_distance": "1",
        "rr": "1",
    }
    row.update({key: str(value) for key, value in updates.items()})
    return row


def test_category_significance_thresholds():
    assert category_significance(9) == "insufficient"
    assert category_significance(10) == "weak"
    assert category_significance(30) == "moderate"
    assert category_significance(100) == "significant"


def test_group_metrics_wr_pf_avg_total_r():
    rows = [_row(0, r_multiple="1", outcome="TP1"), _row(1, r_multiple="-1", outcome="SL"), _row(2, r_multiple="1", outcome="TP1")]
    result = group_metrics(rows, "setup_mode", set(COLUMNS))
    assert isinstance(result, list)
    assert result[0]["trades"] == 3
    assert result[0]["WR"] == 0.6667
    assert result[0]["PF"] == 2.0
    assert result[0]["AvgR"] == 0.3333
    assert result[0]["total_R"] == 1.0


def test_trade_density_and_cluster_flags():
    rows = [_row(i) for i in range(8)]
    density = trade_density(rows)
    assert density["max_trades_in_one_hour"] == 8
    assert density["median_time_between_trades_minutes"] == 5.0
    assert density["OVERTRADING_DENSITY_CONFIRMED"] is True


def test_missing_columns_do_not_crash_and_are_reported():
    rows = [_row(0)]
    report = build_overtrading_diagnostic(rows, ["timestamp", "outcome", "r_multiple"], {}, source_path="x.csv", summary_path="s.json")
    assert "setup_mode" in report["source_data"]["columns_missing"]
    assert report["breakdowns"]["setup_mode"] == "field_not_available_skip"
    assert "DIAGNOSTIC_DATA_INSUFFICIENT" in report["diagnosis"]["secondary_verdicts"]


def test_no_trade_leakage_detected():
    rows = [_row(0, setup_mode="no_trade")]
    report = build_overtrading_diagnostic(rows, COLUMNS, {}, source_path="x.csv", summary_path="s.json")
    assert report["no_trade_leakage"]["no_trade_executed_count"] == 1
    assert report["no_trade_leakage"]["no_trade_leakage_detected"] is True
    assert report["diagnosis"]["primary_verdict"] == "NO_TRADE_LEAKAGE_BUG_FOUND"


def test_dedup_15m_60m_and_delta_pf():
    rows = [
        _row(0, direction="LONG", r_multiple="1", outcome="TP1"),
        _row(1, direction="LONG", r_multiple="1", outcome="TP1"),
        _row(2, direction="LONG", r_multiple="-1", outcome="SL"),
        _row(20, direction="LONG", r_multiple="-1", outcome="SL"),
    ]
    impact = cluster_impact(rows)
    assert impact["dedupped_15m"]["kept_trades"] == 2
    assert impact["dedupped_15m"]["removed_trades"] == 2
    assert impact["dedupped_60m"]["kept_trades"] == 2
    assert impact["dedupped_15m"]["delta_PF_vs_all"] is not None


def test_diagnostics_build_reason_confluence_distance_and_liquidity():
    rows = [_row(i) for i in range(12)]
    report = build_overtrading_diagnostic(rows, COLUMNS, {}, source_path="x.csv", summary_path="s.json")
    assert report["breakdowns"]["reason_codes"][0]["count"] == 12
    assert report["breakdowns"]["confluences"][0]["count"] == 12
    assert report["breakdowns"]["distance"]["buckets"][0]["category"] == "sigma_1_area"
    liquidity_categories = {row["category"] for row in report["breakdowns"]["liquidity_context"]}
    assert "swept_recent_low" in liquidity_categories
    assert "internal_liquidity" in liquidity_categories


def test_backtest_report_flattens_strategy_3_metadata_without_entry_changes():
    signal = BacktestSignal(
        timestamp=datetime(2026, 5, 11, tzinfo=timezone.utc),
        symbol="XAUUSD",
        strategy="strategy_3_vwap_1r",
        direction="LONG",
        entry=100.0,
        stop=99.0,
        tp1=101.0,
        rr_tp1=1.0,
        metadata={
            "setup_mode": "reversal",
            "reason_codes": ["liquidity_sweep", "target_1r"],
            "confluences": {"vwap": {"band": "sigma_1_lower"}},
            "vwap_distance_pips": 12.5,
            "band_touched": "sigma_1_lower",
            "liquidity_context": {"timeframe": "M5", "level": 99.0, "sweep": {"side": "sell_side"}},
            "target_model": "1R",
            "research_only": True,
        },
    )
    row = _flatten_signal(signal)
    assert row["setup_mode"] == "reversal"
    assert row["reason_codes"] == "liquidity_sweep;target_1r"
    assert row["band_touched"] == "sigma_1_lower"
    assert row["sweep_timeframe"] == "M5"
    assert row["sweep_type"] == "sell_side"
    assert row["risk_distance"] == 1.0
    assert row["reward_distance"] == 1.0


def test_diagnostics_module_does_not_import_live_telegram_or_strategy_modules():
    text = Path("dazro_trade/analytics/strategy_3_overtrading_diagnostics.py").read_text().lower()
    import_lines = "\n".join(line for line in text.splitlines() if line.startswith("import ") or line.startswith("from "))
    assert "telegram" not in import_lines
    assert "orders" not in import_lines
    assert "analysis.strategy_3_vwap_1r" not in text
    assert "liquidity_expansion" not in text
    assert "adelin" not in text
