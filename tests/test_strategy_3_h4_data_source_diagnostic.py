from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


class FakeMT5:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 60
    TIMEFRAME_H4 = 240
    TIMEFRAME_D1 = 1440

    def __init__(self, rates=None, *, initialize_ok=True, select_ok=True):
        self.rates = rates or []
        self.initialize_ok = initialize_ok
        self.select_ok = select_ok
        self.shutdown_called = False
        self.selected_symbol = None

    def initialize(self):
        return self.initialize_ok

    def shutdown(self):
        self.shutdown_called = True

    def symbol_select(self, symbol, enabled):
        self.selected_symbol = symbol
        return self.select_ok

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        return self.rates[:count]

    def last_error(self):
        return (1, "fake")


def _module():
    return importlib.import_module("scripts.diagnose_strategy_3_h4_data_source")


def _rate_at(ts: datetime, price: float = 100.0, volume: int = 10, spread: int = 1):
    return {
        "time": int(ts.timestamp()),
        "open": price,
        "high": price + 1.0,
        "low": price - 1.0,
        "close": price + 0.5,
        "tick_volume": volume,
        "spread": spread,
    }


def _frame(base: datetime, rows: int, *, price: float = 100.0, volume: int = 10) -> pd.DataFrame:
    return pd.DataFrame([_rate_at(base + timedelta(hours=4 * i), price + i, volume) for i in range(rows)]).assign(
        time=lambda df: pd.to_datetime(df["time"], unit="s", utc=True)
    )


def _write_project_h4(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], utc=True).dt.strftime("%Y.%m.%d %H:%M")
    out.to_csv(path, index=False, encoding="utf-8")


def _cfg(module, tmp_path: Path, *, apply_rebuild=False, dry_run=True):
    return module.H4DiagnosticConfig(
        symbol="XAUUSD",
        symbol_broker="XAUUSD",
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "reports",
        lookback_bars=300,
        dry_run=dry_run,
        include_forming_candles=False,
        closed_candle_grace_seconds=5,
        candidate_rebuild_output=True,
        apply_rebuild=apply_rebuild,
    )


def test_import_safe_and_cli_parse_does_not_run(tmp_path):
    module = _module()
    args = module.parse_args([])
    assert args.symbol == "XAUUSD"
    assert not (tmp_path / "reports").exists()


def test_ohlc_match_but_volume_mismatch_classifies_volume_only():
    module = _module()
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    local = _frame(base, 20, volume=10)
    mt5 = _frame(base, 20, volume=99)
    comparison = module.compare_h4_frames(local, mt5, 0.10)
    rec = module.classify_recommendation(
        local_meta={"duplicate_count": 0, "invalid_ohlc_rows": 0, "non_monotonic_timestamps": 0},
        mt5_meta={"row_count": 20, "verdict_flags": []},
        comparison=comparison,
        timezone_diag={"timezone_shift_suspected": False},
        append_diag={"can_append_safely": False},
    )

    assert comparison["match_rate_ohlc"] == 1.0
    assert comparison["match_rate_ohlcv"] == 0.0
    assert rec == "VOLUME_ONLY_MISMATCH_RELAX_VOLUME_OVERLAP"


def test_material_ohlc_mismatch_classifies_manual_review():
    module = _module()
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    local = _frame(base, 20, price=100.0)
    mt5 = _frame(base, 20, price=120.0)
    comparison = module.compare_h4_frames(local, mt5, 0.10)
    rec = module.classify_recommendation(
        local_meta={"duplicate_count": 0, "invalid_ohlc_rows": 0, "non_monotonic_timestamps": 0},
        mt5_meta={"row_count": 20, "verdict_flags": []},
        comparison=comparison,
        timezone_diag={"timezone_shift_suspected": False},
        append_diag={"can_append_safely": False},
    )

    assert comparison["mismatch_type"] == "ohlc_material"
    assert rec == "MT5_H4_SOURCE_MISMATCH_MANUAL_REVIEW"


def test_local_stale_overlap_matching_h4_is_append_safe():
    module = _module()
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    local = _frame(base, 10)
    mt5 = _frame(base, 15)
    comparison = module.compare_h4_frames(local, mt5, 0.10)
    append = module.append_rebuild_diagnostic(local, mt5, comparison)
    rec = module.classify_recommendation(
        local_meta={"duplicate_count": 0, "invalid_ohlc_rows": 0, "non_monotonic_timestamps": 0},
        mt5_meta={"row_count": 20, "verdict_flags": []},
        comparison=comparison,
        timezone_diag={"timezone_shift_suspected": False},
        append_diag=append,
    )

    assert append["missing_closed_bars_after_local_latest"] == 5
    assert append["can_append_safely"] is True
    assert rec == "LOCAL_H4_STALE_APPEND_SAFE"


def test_duplicate_and_gap_detection_from_local_h4(tmp_path):
    module = _module()
    h4_path = tmp_path / "data" / "XAUUSD" / "H4.csv"
    h4_path.parent.mkdir(parents=True)
    h4_path.write_text(
        "time,open,high,low,close,tick_volume,spread\n"
        "2026.05.01 00:00,100,101,99,100,10,1\n"
        "2026.05.01 00:00,100,101,99,100,10,1\n"
        "2026.05.01 12:00,100,101,99,100,10,1\n",
        encoding="utf-8",
    )

    _, meta, _, _ = module.load_local_h4(tmp_path / "data", "XAUUSD")

    assert meta["duplicate_count"] == 2
    assert meta["gap_count"] >= 1


def test_timezone_shift_detection():
    module = _module()
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    local = _frame(base, 20)
    mt5 = _frame(base - timedelta(hours=1), 20)
    diag = module.timezone_shift_diagnostic(local, mt5, 0.10)

    assert diag["best_shift_by_match_rate"] == 1
    assert diag["best_shift_match_rate"] == 1.0
    assert diag["timezone_shift_suspected"] is True


def test_candidate_files_are_written_only_under_output_dir_in_dry_run(tmp_path):
    module = _module()
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    local = _frame(base, 10)
    mt5 = _frame(base, 15)
    _write_project_h4(tmp_path / "data" / "XAUUSD" / "H4.csv", local)
    fake = FakeMT5([_rate_at(base + timedelta(hours=4 * i), 100.0 + i) for i in range(25)])

    summary = module.build_diagnostic(
        _cfg(module, tmp_path),
        mt5_module=fake,
        now_utc=base + timedelta(hours=4 * 16),
    )

    assert summary["data_h4_modified"] is False
    assert summary["candidate_files"]
    assert all(str(tmp_path / "reports") in path for path in summary["candidate_files"])
    assert (tmp_path / "reports" / "h4_mt5_candidate.csv").exists()


def test_apply_rebuild_creates_backup_before_modifying_h4(tmp_path):
    module = _module()
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    local = _frame(base, 10)
    _write_project_h4(tmp_path / "data" / "XAUUSD" / "H4.csv", local)
    fake = FakeMT5([_rate_at(base + timedelta(hours=4 * i), 100.0 + i) for i in range(25)])

    summary = module.build_diagnostic(
        _cfg(module, tmp_path, apply_rebuild=True, dry_run=False),
        mt5_module=fake,
        now_utc=base + timedelta(hours=4 * 30),
    )

    assert summary["recommendation"] == "LOCAL_H4_STALE_APPEND_SAFE"
    assert summary["backup_created"] is True
    assert Path(summary["backup_path"]).exists()
    assert summary["data_h4_modified"] is True


def test_dry_run_apply_rebuild_does_not_modify_h4(tmp_path):
    module = _module()
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    local = _frame(base, 10)
    h4_path = tmp_path / "data" / "XAUUSD" / "H4.csv"
    _write_project_h4(h4_path, local)
    before = h4_path.read_text(encoding="utf-8")
    fake = FakeMT5([_rate_at(base + timedelta(hours=4 * i)) for i in range(15)])

    summary = module.build_diagnostic(
        _cfg(module, tmp_path, apply_rebuild=True, dry_run=True),
        mt5_module=fake,
        now_utc=base + timedelta(hours=4 * 16),
    )

    assert summary["apply_rebuild_block_reason"] == "dry_run_enabled"
    assert h4_path.read_text(encoding="utf-8") == before


def test_scanner_remains_blocked_if_h4_is_not_repaired(tmp_path):
    module = _module()
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    local = _frame(base, 20, price=100.0)
    _write_project_h4(tmp_path / "data" / "XAUUSD" / "H4.csv", local)
    fake = FakeMT5([_rate_at(base + timedelta(hours=4 * i), 120.0) for i in range(20)])

    summary = module.build_diagnostic(
        _cfg(module, tmp_path),
        mt5_module=fake,
        now_utc=base + timedelta(hours=4 * 21),
    )

    assert summary["recommendation"] == "MT5_H4_SOURCE_MISMATCH_MANUAL_REVIEW"
    assert summary["scanner_should_remain_blocked"] is True
    assert summary["paper_signals_clean_for_validation"] is False
    assert json.loads((tmp_path / "reports" / "h4_data_source_diagnostic.json").read_text(encoding="utf-8"))["recommendation"] == summary["recommendation"]
