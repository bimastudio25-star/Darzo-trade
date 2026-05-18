from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


def _collector():
    return importlib.import_module("scripts.fetch_xauusd_mt5_candles")


class FakeMT5:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 60
    TIMEFRAME_H4 = 240
    TIMEFRAME_D1 = 1440

    def __init__(self, *, initialize_ok=True, symbol_ok=True, rates=None):
        self.initialize_ok = initialize_ok
        self.symbol_ok = symbol_ok
        self.rates = rates or {}
        self.shutdown_called = False
        self.selected_symbols = []
        self.copy_calls = []
        self.order_send_called = False

    def initialize(self):
        return self.initialize_ok

    def last_error(self):
        return (1, "fake error")

    def terminal_info(self):
        return SimpleNamespace(_asdict=lambda: {"name": "fake-terminal"})

    def symbol_select(self, symbol, enabled):
        self.selected_symbols.append((symbol, enabled))
        return self.symbol_ok

    def symbols_get(self):
        return [SimpleNamespace(name="XAUUSDm"), SimpleNamespace(name="GOLD#"), SimpleNamespace(name="EURUSD")]

    def copy_rates_range(self, symbol, timeframe, date_from, date_to):
        self.copy_calls.append((symbol, timeframe, date_from, date_to))
        return self.rates.get(timeframe, [])

    def shutdown(self):
        self.shutdown_called = True

    def order_send(self, *args, **kwargs):
        self.order_send_called = True
        raise AssertionError("order_send must never be called")


def _rates(base: datetime, count: int = 3):
    rows = []
    for idx in range(count):
        ts = int((base + timedelta(minutes=idx)).timestamp())
        rows.append({"time": ts, "open": 100 + idx, "high": 101 + idx, "low": 99 + idx, "close": 100.5 + idx, "tick_volume": 10, "spread": 1})
    return rows


def _cfg(module, tmp_path: Path, *, dry_run=True, write=False, overwrite=False, days_back=7, allow_large_fetch=False):
    return module.CollectorConfig(
        symbol="XAUUSD",
        symbol_broker="XAUUSDm",
        timeframes=["M1", "M5", "M15", "H1", "H4", "D1"],
        output_dir=tmp_path / "incoming",
        data_dir=tmp_path / "data",
        days_back=days_back,
        date_from=None,
        date_to=datetime(2026, 5, 19, tzinfo=timezone.utc),
        dry_run=dry_run,
        write=write,
        overwrite=overwrite,
        allow_large_fetch=allow_large_fetch,
        allow_timezone_warning=False,
        allow_overlap_mismatch=False,
        overlap_price_tolerance_usd=0.10,
        report_dir=tmp_path / "reports",
    )


def test_import_safe_without_metatrader5_package():
    module = _collector()
    assert hasattr(module, "run_collector")


def test_missing_metatrader5_package_is_reported(monkeypatch, tmp_path):
    module = _collector()
    monkeypatch.setattr(module, "import_mt5", lambda: None)

    summary = module.run_collector(_cfg(module, tmp_path))

    assert "MT5_PACKAGE_MISSING" in summary["verdict_flags"]
    assert (tmp_path / "reports" / "mt5_fetch_summary.json").exists()


def test_initialize_failure_is_reported_and_shutdown_not_required(tmp_path):
    module = _collector()
    fake = FakeMT5(initialize_ok=False)

    summary = module.run_collector(_cfg(module, tmp_path), mt5_module=fake)

    assert "MT5_INITIALIZE_FAILED" in summary["verdict_flags"]
    assert fake.shutdown_called is False


def test_symbol_select_failure_reports_suggestions_and_custom_broker_symbol(tmp_path):
    module = _collector()
    fake = FakeMT5(symbol_ok=False)

    summary = module.run_collector(_cfg(module, tmp_path), mt5_module=fake)

    assert ("XAUUSDm", True) in fake.selected_symbols
    assert "MT5_SYMBOL_SELECT_FAILED" in summary["verdict_flags"]
    assert summary["suggested_symbols"] == ["GOLD#", "XAUUSDm"]
    assert fake.shutdown_called is True


def test_timeframe_mapping_and_normalization_sort_dedupe(tmp_path):
    module = _collector()
    fake = FakeMT5()
    assert module.timeframe_mapping(fake)["H4"] == fake.TIMEFRAME_H4
    base = datetime(2026, 5, 18, tzinfo=timezone.utc)
    raw = [_rates(base, 1)[0], _rates(base + timedelta(minutes=2), 1)[0], _rates(base, 1)[0]]

    frame = module.normalize_rates(raw)

    assert list(frame.columns) == ["time", "open", "high", "low", "close", "tick_volume", "spread"]
    assert len(frame) == 2
    assert pd.to_datetime(frame["time"], utc=True).is_monotonic_increasing


def test_dry_run_does_not_write_and_write_requires_overwrite_for_existing(tmp_path):
    module = _collector()
    base = datetime(2026, 5, 18, tzinfo=timezone.utc)
    fake = FakeMT5(rates={1: _rates(base), 5: _rates(base), 15: _rates(base), 60: _rates(base), 240: _rates(base), 1440: _rates(base)})

    dry = module.run_collector(_cfg(module, tmp_path, dry_run=True, write=False), mt5_module=fake)
    assert "MT5_WRITE_DISABLED_DRY_RUN" in dry["verdict_flags"]
    assert not (tmp_path / "incoming" / "M1.csv").exists()

    existing = tmp_path / "incoming"
    existing.mkdir(parents=True)
    (existing / "M1.csv").write_text("keep\n", encoding="utf-8")
    write = module.run_collector(_cfg(module, tmp_path, dry_run=False, write=True, overwrite=False), mt5_module=fake)
    assert "MT5_OUTPUT_EXISTS_OVERWRITE_REQUIRED" in write["verdict_flags"]
    assert (existing / "M5.csv").exists()
    assert fake.order_send_called is False


def test_write_creates_csvs_and_safety_fields_false(tmp_path):
    module = _collector()
    base = datetime(2026, 5, 18, tzinfo=timezone.utc)
    fake = FakeMT5(rates={1: _rates(base), 5: _rates(base), 15: _rates(base), 60: _rates(base), 240: _rates(base), 1440: _rates(base)})

    summary = module.run_collector(_cfg(module, tmp_path, dry_run=False, write=True, overwrite=True), mt5_module=fake)

    assert "MT5_INCOMING_CSVS_WRITTEN" in summary["verdict_flags"]
    assert (tmp_path / "incoming" / "M1.csv").exists()
    assert summary["safety"]["order_send_called"] is False
    assert fake.shutdown_called is True


def test_days_back_safety_rules():
    module = _collector()
    assert module.days_back_safety(7, False) == ("low", [], False)
    assert module.days_back_safety(31, False)[1] == ["MT5_FETCH_RANGE_WARNING"]
    assert module.days_back_safety(91, False)[1] == ["MT5_FETCH_RANGE_REQUIRES_CONFIRMATION"]
    assert module.days_back_safety(91, True)[2] is False
    assert module.days_back_safety(366, True)[1] == ["MT5_FETCH_RANGE_TOO_LARGE"]


def test_future_timestamp_triggers_timezone_warning():
    module = _collector()
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    warnings, latest = module.validate_timezone({"M1": pd.DataFrame([{"time": future}])}, datetime.now(timezone.utc))

    assert warnings
    assert latest["M1"] is not None


def test_overlap_validation_verdicts():
    module = _collector()
    base = pd.Timestamp("2026-05-18T00:00:00Z")
    existing = pd.DataFrame(
        [{"time": base + pd.Timedelta(minutes=i), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0} for i in range(100)]
    )
    fetched = existing.copy()
    assert module._existing_overlap(existing, fetched, "M1", 0.10)["verdict"] == "OVERLAP_MATCH_100"
    fetched_97 = fetched.copy()
    fetched_97.loc[:2, "close"] = 110.0
    assert module._existing_overlap(existing, fetched_97, "M1", 0.10)["verdict"] == "OVERLAP_MATCH_GT_95"
    fetched_bad = fetched.copy()
    fetched_bad.loc[:20, "close"] = 110.0
    assert module._existing_overlap(existing, fetched_bad, "M1", 0.10)["verdict"] == "OVERLAP_MATCH_LT_95"
    assert module._existing_overlap(existing.iloc[0:0], fetched, "M1", 0.10)["verdict"] == "OVERLAP_NO_DATA"
