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


def _data_context() -> dict[str, object]:
    return {
        "combined_data_context_hash": "ctx",
        "files": {
            "H4": {"sha256": "h4hash", "latest_timestamp": "2026-05-14T20:00:00+00:00"},
            "M15": {"sha256": "m15hash", "latest_timestamp": "2026-05-14T22:45:00+00:00"},
        },
    }


def _config(module, tmp_path, *, scan_driver_bars: int = 1):
    return module.ShadowScannerConfig(
        symbol="XAUUSD",
        timeframes=["M1", "M5", "M15", "H1", "H4", "D1"],
        data_dir="data",
        output_dir=tmp_path,
        cooldown_minutes=120,
        dry_run=True,
        scan_driver_bars=scan_driver_bars,
        enforce_htf_freshness=False,
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
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context())

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
    assert row["data_context_hash"] == "ctx"
    assert row["h4_hash"] == "h4hash"
    assert row["h4_latest_timestamp"] == "2026-05-14T20:00:00+00:00"
    assert row["m15_hash"] == "m15hash"
    assert row["m15_latest_timestamp"] == "2026-05-14T22:45:00+00:00"
    assert summary["data_context"]["combined_data_context_hash"] == "ctx"
    assert (tmp_path / "paper_signals_data_context.json").exists()
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


def test_incremental_mode_creates_state_and_processes_after_from_timestamp(monkeypatch, tmp_path):
    module = _scanner_module()
    market = _market()
    monkeypatch.setattr(module, "load_csv_timeframes", lambda *a, **kw: market)
    monkeypatch.setattr(module, "evaluate_strategy_3_vwap_1r", lambda market, *, now_utc, **kw: _signal(now_utc, "LONG"))
    cfg = module.ShadowScannerConfig(
        **{
            **_config(module, tmp_path).__dict__,
            "incremental": True,
            "from_timestamp": "2026-05-14T22:00:00+00:00",
            "max_candles_per_run": 2,
        }
    )

    summary = module.run_scanner(cfg)
    state = json.loads((tmp_path / "scanner_state.json").read_text(encoding="utf-8"))

    assert summary["incremental"] is True
    assert summary["driver_candles_processed"] == 2
    assert summary["previous_last_processed_timestamp"] == "2026-05-14T22:00:00+00:00"
    assert state["last_processed_timestamp"] == summary["new_last_processed_timestamp"]
    assert state["total_incremental_runs"] == 1


def test_incremental_mode_uses_state_to_skip_old_candles(monkeypatch, tmp_path):
    module = _scanner_module()
    monkeypatch.setattr(module, "load_csv_timeframes", lambda *a, **kw: _market())
    monkeypatch.setattr(module, "evaluate_strategy_3_vwap_1r", lambda market, *, now_utc, **kw: None)
    (tmp_path / "scanner_state.json").write_text(
        json.dumps({"last_processed_timestamp": "2026-05-14T22:30:00+00:00", "total_incremental_runs": 4}),
        encoding="utf-8",
    )
    cfg = module.ShadowScannerConfig(**{**_config(module, tmp_path).__dict__, "incremental": True})

    summary = module.run_scanner(cfg)

    assert summary["previous_last_processed_timestamp"] == "2026-05-14T22:30:00+00:00"
    assert summary["driver_candles_processed"] == 1
    assert json.loads((tmp_path / "scanner_state.json").read_text(encoding="utf-8"))["total_incremental_runs"] == 5


def test_incremental_mode_appends_and_deduplicates_signals(monkeypatch, tmp_path):
    module = _scanner_module()
    monkeypatch.setattr(module, "load_csv_timeframes", lambda *a, **kw: _market())
    monkeypatch.setattr(module, "evaluate_strategy_3_vwap_1r", lambda market, *, now_utc, **kw: _signal(now_utc, "SHORT"))
    cfg = module.ShadowScannerConfig(**{**_config(module, tmp_path).__dict__, "incremental": True, "from_timestamp": "2026-05-14T22:30:00+00:00"})

    first = module.run_scanner(cfg)
    second = module.run_scanner(cfg)
    rows = list(csv.DictReader((tmp_path / "paper_signals.csv").open(newline="", encoding="utf-8")))

    assert first["paper_signals_total_after_run"] == 1
    assert second["duplicates_skipped"] == 1
    assert len(rows) == 1


def test_incremental_no_signal_writes_summary_and_state(monkeypatch, tmp_path):
    module = _scanner_module()
    monkeypatch.setattr(module, "load_csv_timeframes", lambda *a, **kw: _market())
    monkeypatch.setattr(module, "evaluate_strategy_3_vwap_1r", lambda *a, **kw: None)
    cfg = module.ShadowScannerConfig(**{**_config(module, tmp_path).__dict__, "incremental": True, "from_timestamp": "2026-05-14T22:45:00+00:00"})

    summary = module.run_scanner(cfg)

    assert summary["driver_candles_processed"] == 0
    assert summary["no_signal_reason"] == "no_new_driver_candles_to_process"
    assert (tmp_path / "scanner_state.json").exists()


def test_incremental_scanner_slices_without_future_candles(monkeypatch, tmp_path):
    module = _scanner_module()
    monkeypatch.setattr(module, "load_csv_timeframes", lambda *a, **kw: _market())

    def evaluator(market, *, now_utc, **kwargs):
        latest_m15 = pd.to_datetime(market["M15"]["time"], utc=True).max().to_pydatetime()
        assert latest_m15 <= now_utc
        return None

    monkeypatch.setattr(module, "evaluate_strategy_3_vwap_1r", evaluator)
    cfg = module.ShadowScannerConfig(**{**_config(module, tmp_path).__dict__, "incremental": True, "from_timestamp": "2026-05-14T22:00:00+00:00"})

    summary = module.run_scanner(cfg)

    assert summary["driver_candles_processed"] == 3
