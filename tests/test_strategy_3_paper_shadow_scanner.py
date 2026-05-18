from __future__ import annotations

import csv
import importlib
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from dazro_trade.analysis.strategy_3_vwap_1r import Strategy3Signal


def _scanner_module():
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
            }
            for i in range(rows)
        ]
    )


def _market() -> dict[str, pd.DataFrame]:
    base = datetime(2026, 5, 14, 20, 0, tzinfo=timezone.utc)
    return {
        "M1": _frame(base, 180, 1),
        "M5": _frame(base, 36, 5),
        "M15": _frame(base, 12, 15),
        "H1": _frame(base - timedelta(days=10), 12, 60),
        "H4": _frame(base - timedelta(days=20), 12, 240),
        "D1": _frame(base - timedelta(days=30), 12, 1440),
    }


def _signal(when: datetime, direction: str = "LONG") -> Strategy3Signal:
    return Strategy3Signal(
        symbol="XAUUSD",
        direction=direction,  # type: ignore[arg-type]
        setup_mode="trend_following",
        entry=100.0,
        stop=99.0,
        tp1=101.0,
        rr_tp1=1.0,
        timestamp_utc=when,
        reason_codes=["liquidity_sweep", "vwap_band_vwap", "setup_trend_following", "target_1r"],
        confluences={"vwap": {"vwap": 100.0, "upper_1": 101.0, "lower_1": 99.0, "upper_2": 102.0, "lower_2": 98.0}},
        vwap_distance_pips=0.0,
        band_touched="vwap",
        liquidity_context={"level": 99.0, "distance_pips": 10.0},
        fvg_ifvg_context={"has_fvg": False, "has_ifvg": False},
        number_theory_context={"confluence": False},
    )


def _config(module, tmp_path, *, scan_driver_bars: int = 1):
    return module.ShadowScannerConfig(
        symbol="XAUUSD",
        timeframes=["M1", "M5", "M15", "H1", "H4", "D1"],
        data_dir="data",
        output_dir=tmp_path,
        cooldown_minutes=120,
        dry_run=True,
        scan_driver_bars=scan_driver_bars,
    )


def test_import_safe_does_not_start_scan(tmp_path):
    module = _scanner_module()
    assert hasattr(module, "main")
    assert not (tmp_path / "scanner_summary.json").exists()


def test_no_signal_writes_summary_and_empty_outputs(monkeypatch, tmp_path):
    module = _scanner_module()
    monkeypatch.setattr(module, "load_csv_timeframes", lambda *a, **kw: _market())
    monkeypatch.setattr(module, "evaluate_strategy_3_vwap_1r", lambda *a, **kw: None)

    summary = module.run_scanner(_config(module, tmp_path))

    assert summary["signals_detected"] == 0
    assert summary["no_signal_reason"] == "no_strategy_3_signal_on_latest_driver_candle"
    assert (tmp_path / "scanner_summary.json").exists()
    assert (tmp_path / "paper_signals.csv").exists()
    assert (tmp_path / "paper_signals.jsonl").exists()
    assert (tmp_path / "scanner_run.md").exists()
    with (tmp_path / "paper_signals.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows and "scanner_run_id" in rows[0]


def test_signal_export_contains_required_safety_metadata(monkeypatch, tmp_path):
    module = _scanner_module()
    monkeypatch.setattr(module, "load_csv_timeframes", lambda *a, **kw: _market())
    monkeypatch.setattr(module, "evaluate_strategy_3_vwap_1r", lambda market, *, now_utc, **kw: _signal(now_utc))

    summary = module.run_scanner(_config(module, tmp_path))
    row = next(csv.DictReader((tmp_path / "paper_signals.csv").open(newline="", encoding="utf-8")))

    assert summary["signals_detected"] == 1
    assert summary["signals_accepted"] == 1
    assert summary["cooldown_minutes"] == 120
    assert row["mode"] == "paper_shadow"
    assert row["strategy"] == "strategy_3_vwap_1r"
    assert row["dry_run"] == "True"
    assert row["order_sent"] == "False"
    assert row["telegram_sent"] == "False"
    assert row["broker_called"] == "False"
    assert row["live_trading_enabled"] == "False"
    assert row["order_execution_enabled"] == "False"
    assert row["telegram_enabled"] == "False"
    assert row["vwap_value"] == "100.0"
    assert json.loads(row["reason_codes"]) == ["liquidity_sweep", "vwap_band_vwap", "setup_trend_following", "target_1r"]


def test_cooldown_blocks_second_same_symbol_direction(monkeypatch, tmp_path):
    module = _scanner_module()
    monkeypatch.setattr(module, "load_csv_timeframes", lambda *a, **kw: _market())
    monkeypatch.setattr(module, "evaluate_strategy_3_vwap_1r", lambda market, *, now_utc, **kw: _signal(now_utc, "LONG"))

    summary = module.run_scanner(_config(module, tmp_path, scan_driver_bars=2))
    rows = list(csv.DictReader((tmp_path / "paper_signals.csv").open(newline="", encoding="utf-8")))

    assert summary["signals_detected"] == 2
    assert summary["signals_accepted"] == 1
    assert summary["signals_blocked_by_cooldown"] == 1
    assert rows[0]["cooldown_status"] == "accepted"
    assert rows[1]["cooldown_status"] == "blocked"
    assert rows[1]["cooldown_block_reason"] == "STRATEGY_3_COOLDOWN_BLOCKED"


def test_scanner_rejects_non_dry_run_non_xauusd_or_wrong_cooldown(tmp_path):
    module = _scanner_module()
    cfg = _config(module, tmp_path)
    with pytest.raises(ValueError, match="requires_dry_run"):
        module.run_scanner(module.ShadowScannerConfig(**{**cfg.__dict__, "dry_run": False}))
    with pytest.raises(ValueError, match="xauusd_only"):
        module.run_scanner(module.ShadowScannerConfig(**{**cfg.__dict__, "symbol": "EURUSD"}))
    with pytest.raises(ValueError, match="cooldown_must_be_120"):
        module.run_scanner(module.ShadowScannerConfig(**{**cfg.__dict__, "cooldown_minutes": 60}))


def test_parse_args_defaults_to_safe_dry_run_and_strategy_3_constants():
    module = _scanner_module()
    args = module.parse_args([])
    assert args.dry_run is True
    assert args.symbol == "XAUUSD"
    assert args.cooldown_minutes == 120
    assert module.STRATEGY_NAME == "strategy_3_vwap_1r"
