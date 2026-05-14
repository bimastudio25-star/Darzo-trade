from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from dazro_trade.backtest.data_validator import (
    format_validation_report,
    validate_csv_timeframes,
)


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _clean_h1_rows(n: int, start: datetime | None = None) -> list[dict]:
    base = start or datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        t = base + timedelta(hours=i)
        rows.append({
            "time": t.isoformat(),
            "open": 4700.0 + i * 0.1,
            "high": 4702.0 + i * 0.1,
            "low": 4698.0 + i * 0.1,
            "close": 4701.0 + i * 0.1,
            "tick_volume": 100,
        })
    return rows


def test_clean_csv_passes_validation(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    _write_csv(path, _clean_h1_rows(50))
    report = validate_csv_timeframes("XAUUSD", ["H1"], data_dir=str(tmp_path))
    assert report.ok is True
    v = report.per_timeframe["H1"]
    assert v.rows == 50
    assert v.duplicate_timestamps == 0
    assert v.non_monotonic_rows == 0
    assert v.high_lt_low_rows == 0
    assert v.suspected_gaps == []


def test_missing_file_flagged(tmp_path):
    report = validate_csv_timeframes("XAUUSD", ["H1"], data_dir=str(tmp_path))
    v = report.per_timeframe["H1"]
    assert v.ok is False
    assert any("csv_missing" in e for e in v.errors)


def test_duplicate_timestamps_detected(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    rows = _clean_h1_rows(10)
    rows.append(rows[5].copy())  # duplicate
    _write_csv(path, rows)
    report = validate_csv_timeframes("XAUUSD", ["H1"], data_dir=str(tmp_path))
    v = report.per_timeframe["H1"]
    assert v.duplicate_timestamps >= 1
    assert v.ok is False
    assert any("duplicate" in e for e in v.errors)


def test_high_lt_low_flagged(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    rows = _clean_h1_rows(10)
    rows[3]["high"] = 4690.0
    rows[3]["low"] = 4700.0
    _write_csv(path, rows)
    report = validate_csv_timeframes("XAUUSD", ["H1"], data_dir=str(tmp_path))
    v = report.per_timeframe["H1"]
    assert v.high_lt_low_rows >= 1
    assert v.ok is False


def test_missing_required_column_flagged(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    rows = _clean_h1_rows(5)
    for r in rows:
        del r["close"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    report = validate_csv_timeframes("XAUUSD", ["H1"], data_dir=str(tmp_path))
    v = report.per_timeframe["H1"]
    assert v.ok is False
    assert "csv_load_failed" in v.errors[0] or any("missing" in e for e in v.errors)


def test_gap_detected_when_candle_missing(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    rows = _clean_h1_rows(20)
    rows.pop(10)
    _write_csv(path, rows)
    report = validate_csv_timeframes("XAUUSD", ["H1"], data_dir=str(tmp_path))
    v = report.per_timeframe["H1"]
    assert len(v.suspected_gaps) >= 1


def test_format_validation_report_contains_summary(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    _write_csv(path, _clean_h1_rows(20))
    report = validate_csv_timeframes("XAUUSD", ["H1", "M15"], data_dir=str(tmp_path))
    text = format_validation_report(report)
    assert "DATA VALIDATION REPORT" in text
    assert "[H1]" in text
    assert "[M15]" in text


def test_validate_only_cli(tmp_path, monkeypatch):
    import backtest as cli_module

    data_dir = tmp_path / "data"
    _write_csv(data_dir / "XAUUSD" / "H1.csv", _clean_h1_rows(15))

    out_dir = tmp_path / "out"
    rc = cli_module.main([
        "--symbol", "XAUUSD",
        "--timeframes", "H1",
        "--data-dir", str(data_dir),
        "--output-dir", str(out_dir),
        "--validate-only",
    ])
    assert rc == 0
    assert (out_dir / "data_validation.json").exists()
    assert (out_dir / "data_validation.txt").exists()


def test_validate_only_cli_returns_1_when_invalid(tmp_path):
    import backtest as cli_module

    data_dir = tmp_path / "data"
    out_dir = tmp_path / "out"
    rc = cli_module.main([
        "--symbol", "XAUUSD",
        "--timeframes", "H1",
        "--data-dir", str(data_dir),
        "--output-dir", str(out_dir),
        "--validate-only",
    ])
    assert rc == 1
