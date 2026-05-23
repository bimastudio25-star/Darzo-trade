from __future__ import annotations

import csv
import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from dazro_trade.analysis.strategy_3_vwap_1r import Strategy3Signal


def _freshness():
    return importlib.import_module("scripts.strategy_3_htf_freshness")


def _scanner():
    return importlib.import_module("scripts.run_strategy_3_paper_shadow_scanner")


def _frame(base: datetime, rows: int, step_minutes: int, price: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "time": base + timedelta(minutes=i * step_minutes),
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price,
                "tick_volume": 100,
                "spread": 1,
            }
            for i in range(rows)
        ]
    )


def _market_with_stale_h4() -> dict[str, pd.DataFrame]:
    latest_m15_base = datetime(2026, 5, 20, 18, 0, tzinfo=timezone.utc)
    return {
        "M1": _frame(datetime(2026, 5, 20, 18, 0, tzinfo=timezone.utc), 136, 1),
        "M5": _frame(datetime(2026, 5, 20, 18, 0, tzinfo=timezone.utc), 28, 5),
        "M15": _frame(latest_m15_base, 10, 15),
        "H1": _frame(datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc), 10, 60),
        "H4": _frame(datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc), 4, 240),
        "D1": _frame(datetime(2026, 5, 18, 0, tzinfo=timezone.utc), 2, 1440),
    }


def _market_friday_close_with_fresh_h4_h1() -> dict[str, pd.DataFrame]:
    return {
        "M1": _frame(datetime(2026, 5, 22, 22, 55, tzinfo=timezone.utc), 5, 1),
        "M5": _frame(datetime(2026, 5, 22, 22, 45, tzinfo=timezone.utc), 3, 5),
        "M15": _frame(datetime(2026, 5, 22, 22, 30, tzinfo=timezone.utc), 2, 15),
        "H1": _frame(datetime(2026, 5, 22, 22, 0, tzinfo=timezone.utc), 1, 60),
        "H4": _frame(datetime(2026, 5, 22, 20, 0, tzinfo=timezone.utc), 1, 240),
        "D1": _frame(datetime(2026, 5, 19, 0, tzinfo=timezone.utc), 1, 1440),
    }


def _signal(when: datetime) -> Strategy3Signal:
    return Strategy3Signal(
        symbol="XAUUSD",
        direction="LONG",  # type: ignore[arg-type]
        setup_mode="trend_following",
        entry=100.0,
        stop=99.0,
        tp1=101.0,
        rr_tp1=1.0,
        timestamp_utc=when,
        reason_codes=["target_1r"],
        confluences={"vwap": {"vwap": 100.0, "upper_1": 101.0, "lower_1": 99.0, "upper_2": 102.0, "lower_2": 98.0}},
        vwap_distance_pips=0.0,
        band_touched="vwap",
        liquidity_context={},
        fvg_ifvg_context={},
        number_theory_context={},
    )


def test_d1_previous_day_is_acceptable_when_current_daily_candle_is_forming():
    module = _freshness()
    market = _market_with_stale_h4()
    diagnostic = module.analyze_htf_freshness(
        data_dir=Path("data"),
        symbol="XAUUSD",
        market_data=market,
        now_utc=datetime(2026, 5, 20, 20, 15, tzinfo=timezone.utc),
    )
    d1 = next(item for item in diagnostic["timeframes"] if item["timeframe"] == "D1")

    assert d1["latest_existing_timestamp"] == "2026-05-19T00:00:00+00:00"
    assert d1["expected_latest_closed_timestamp"] == "2026-05-19T00:00:00+00:00"
    assert d1["closed_candle_lag_expected"] is True
    assert "D1" not in diagnostic["stale_timeframes"]


def test_h4_multiple_closed_bars_stale_is_blocking():
    module = _freshness()
    diagnostic = module.analyze_htf_freshness(
        data_dir=Path("data"),
        symbol="XAUUSD",
        market_data=_market_with_stale_h4(),
        now_utc=datetime(2026, 5, 20, 20, 15, tzinfo=timezone.utc),
    )
    h4 = next(item for item in diagnostic["timeframes"] if item["timeframe"] == "H4")

    assert h4["latest_existing_timestamp"] == "2026-05-19T00:00:00+00:00"
    assert h4["expected_latest_closed_timestamp"] == "2026-05-20T16:00:00+00:00"
    assert h4["stale_by_bars"] == 10
    assert h4["freshness_status"] == "stale_blocking"
    assert diagnostic["scanner_blocked_due_to_stale_htf"] is True


def test_h4_friday_20_not_stale_when_weekend_wall_clock_uses_latest_lower_tf():
    module = _freshness()
    diagnostic = module.analyze_htf_freshness(
        data_dir=Path("data"),
        symbol="XAUUSD",
        market_data=_market_friday_close_with_fresh_h4_h1(),
        now_utc=datetime(2026, 5, 23, 7, 29, tzinfo=timezone.utc),
    )
    h4 = next(item for item in diagnostic["timeframes"] if item["timeframe"] == "H4")

    assert diagnostic["freshness_reference_mode"] == "MARKET_CLOSED_LAST_AVAILABLE"
    assert diagnostic["market_reference_timestamp"] == "2026-05-22T22:59:00+00:00"
    assert h4["latest_existing_timestamp"] == "2026-05-22T20:00:00+00:00"
    assert h4["expected_latest_closed_timestamp"] == "2026-05-22T20:00:00+00:00"
    assert h4["stale_by_bars"] == 0
    assert h4["freshness_status"] == "fresh"
    assert diagnostic["scanner_blocked_due_to_stale_htf"] is False


def test_h1_friday_22_not_stale_when_weekend_wall_clock_uses_latest_lower_tf():
    module = _freshness()
    diagnostic = module.analyze_htf_freshness(
        data_dir=Path("data"),
        symbol="XAUUSD",
        market_data=_market_friday_close_with_fresh_h4_h1(),
        now_utc=datetime(2026, 5, 23, 7, 29, tzinfo=timezone.utc),
    )
    h1 = next(item for item in diagnostic["timeframes"] if item["timeframe"] == "H1")

    assert h1["latest_existing_timestamp"] == "2026-05-22T22:00:00+00:00"
    assert h1["expected_latest_closed_timestamp"] == "2026-05-22T22:00:00+00:00"
    assert h1["stale_by_bars"] == 0
    assert h1["freshness_status"] == "fresh"


def test_d1_stale_warning_is_non_blocking_under_weekend_reference():
    module = _freshness()
    diagnostic = module.analyze_htf_freshness(
        data_dir=Path("data"),
        symbol="XAUUSD",
        market_data=_market_friday_close_with_fresh_h4_h1(),
        now_utc=datetime(2026, 5, 23, 7, 29, tzinfo=timezone.utc),
    )
    d1 = next(item for item in diagnostic["timeframes"] if item["timeframe"] == "D1")

    assert d1["freshness_status"] == "stale_warning"
    assert "D1" in diagnostic["stale_timeframes"]
    assert diagnostic["scanner_blocked_due_to_stale_htf"] is False
    assert diagnostic["paper_signals_clean_for_validation"] is True


def test_h4_overlap_mismatch_report_includes_examples(tmp_path):
    module = _freshness()
    data_dir = tmp_path / "data" / "XAUUSD"
    incoming_dir = tmp_path / "incoming"
    data_dir.mkdir(parents=True)
    incoming_dir.mkdir()
    header = "time,open,high,low,close,tick_volume,spread\n"
    (data_dir / "H4.csv").write_text(
        header
        + "2026.05.19 00:00,100,101,99,100,10,1\n"
        + "2026.05.19 04:00,100,101,99,100,10,1\n",
        encoding="utf-8",
    )
    (incoming_dir / "H4.csv").write_text(
        header
        + "2026.05.19 00:00,120,121,119,120,10,1\n"
        + "2026.05.19 04:00,100,101,99,100,10,1\n",
        encoding="utf-8",
    )
    diagnostic = module.analyze_htf_freshness(
        data_dir=tmp_path / "data",
        symbol="XAUUSD",
        incoming_dir=incoming_dir,
        now_utc=datetime(2026, 5, 19, 8, 5, tzinfo=timezone.utc),
        timeframes=["H4"],
    )
    h4 = diagnostic["timeframes"][0]

    assert h4["overlap_verdict"] == "OVERLAP_MATCH_LT_95"
    assert h4["first_mismatch_timestamp"] == "2026-05-19T00:00:00+00:00"
    assert h4["mismatch_example_existing_ohlcv"]["open"] == 100.0
    assert h4["mismatch_example_incoming_ohlcv"]["open"] == 120.0


def test_h4_duplicate_and_gap_detection(tmp_path):
    module = _freshness()
    data_dir = tmp_path / "data" / "XAUUSD"
    data_dir.mkdir(parents=True)
    (data_dir / "H4.csv").write_text(
        "time,open,high,low,close,tick_volume,spread\n"
        "2026.05.18 00:00,100,101,99,100,10,1\n"
        "2026.05.18 00:00,100,101,99,100,10,1\n"
        "2026.05.18 12:00,100,101,99,100,10,1\n",
        encoding="utf-8",
    )
    diagnostic = module.analyze_htf_freshness(
        data_dir=tmp_path / "data",
        symbol="XAUUSD",
        now_utc=datetime(2026, 5, 18, 16, 5, tzinfo=timezone.utc),
        timeframes=["H4"],
    )
    h4 = diagnostic["timeframes"][0]

    assert h4["existing_validation"]["duplicate_timestamps"] == 2
    assert h4["existing_validation"]["gaps"] >= 1


def test_scanner_blocks_and_preserves_existing_signals_when_h4_is_stale(monkeypatch, tmp_path):
    module = _scanner()
    market = _market_with_stale_h4()
    monkeypatch.setattr(module, "load_csv_timeframes", lambda *a, **kw: market)
    monkeypatch.setattr(module, "evaluate_strategy_3_vwap_1r", lambda market, *, now_utc, **kw: _signal(now_utc))
    existing = tmp_path / "paper_signals.csv"
    existing.write_text(",".join(module.CSV_FIELDS) + "\n", encoding="utf-8")
    cfg = module.ShadowScannerConfig(
        symbol="XAUUSD",
        timeframes=["M1", "M5", "M15", "H1", "H4", "D1"],
        data_dir=str(tmp_path / "data"),
        output_dir=tmp_path,
        cooldown_minutes=120,
        dry_run=True,
        incremental=True,
        from_timestamp="2026-05-20T19:00:00+00:00",
        htf_report_dir=tmp_path / "h4_report",
    )

    summary = module.run_scanner(cfg)

    assert summary["signals_detected"] == 0
    assert summary["driver_candles_processed"] == 0
    assert summary["scanner_blocked_due_to_stale_htf"] is True
    assert summary["paper_signals_clean_for_validation"] is False
    assert "STRATEGY_3_SCANNER_BLOCKED_STALE_HTF_CONTEXT" in summary["verdict_flags"]
    assert not (tmp_path / "scanner_state.json").exists()
    rows = list(csv.DictReader((tmp_path / "paper_signals.csv").open(newline="", encoding="utf-8")))
    assert rows == []


def test_missing_h4_data_is_clear_diagnostic(tmp_path):
    module = _freshness()
    diagnostic = module.analyze_htf_freshness(
        data_dir=tmp_path / "data",
        symbol="XAUUSD",
        now_utc=datetime(2026, 5, 20, 20, 15, tzinfo=timezone.utc),
        timeframes=["H4"],
    )
    h4 = diagnostic["timeframes"][0]

    assert h4["freshness_status"] == "missing"
    assert diagnostic["scanner_blocked_due_to_stale_htf"] is True


def test_h4_backup_created_before_recovery(tmp_path):
    module = _freshness()
    h4 = tmp_path / "H4.csv"
    h4.write_text("time,open,high,low,close\n2026.05.19 00:00,1,2,0,1\n", encoding="utf-8")

    backup = module.create_h4_backup_before_recovery(
        h4,
        timestamp=datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc),
    )

    assert backup.exists()
    assert backup.name == "H4.csv.backup.20260520T120000Z"
    assert backup.read_text(encoding="utf-8") == h4.read_text(encoding="utf-8")


def test_pipeline_summary_consistency_allows_no_new_driver_without_htf_block():
    module = importlib.import_module("scripts.run_strategy_3_local_paper_pipeline")

    status, issues = module._summary_consistency(
        {
            "scanner_status": "no_new_driver_candles_to_process",
            "scanner_blocked_due_to_stale_htf": False,
            "paper_signals_clean_for_validation": True,
            "htf_freshness_status_for_scanner": "stale_warning",
            "scanner_htf_blocking_status": "not_blocked",
            "h4_quarantine_status": "fresh",
        }
    )

    assert status == "consistent"
    assert issues == []


def test_pipeline_summary_consistency_blocks_contradictory_stale_htf_state():
    module = importlib.import_module("scripts.run_strategy_3_local_paper_pipeline")

    status, issues = module._summary_consistency(
        {
            "scanner_status": "no_new_driver_candles_to_process",
            "scanner_blocked_due_to_stale_htf": True,
            "paper_signals_clean_for_validation": True,
            "htf_freshness_status_for_scanner": "stale_blocking",
            "scanner_htf_blocking_status": "blocked",
            "h4_quarantine_status": "stale_blocking",
        }
    )

    assert status == "inconsistent_blocking"
    assert {issue["code"] for issue in issues} >= {
        "SCANNER_STATUS_CONTRADICTS_STALE_HTF_BLOCK",
        "CLEAN_VALIDATION_CONTRADICTS_STALE_BLOCKING_HTF",
    }
