from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.audit_xauusd_data import build_audit, read_candle_csv, validate_frame, write_audit_report
from scripts.import_xauusd_candles import build_ingestion


def _write_mt5(path: Path, rows: list[tuple[str, float, float, float, float, int, int]] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = rows or [
        ("2026.05.14 22:55", 100, 101, 99, 100.5, 10, 0),
        ("2026.05.14 23:00", 101, 102, 100, 101.5, 11, 0),
    ]
    content = "\n".join(",".join(str(value) for value in row) for row in data) + "\n"
    path.write_text(content, encoding="utf-16")


def _seed_data(base: Path, timeframes: list[str] | None = None) -> None:
    for tf in timeframes or ["M1", "M5", "M15", "H1", "H4", "D1"]:
        _write_mt5(base / "data" / "XAUUSD" / f"{tf}.csv")


def test_audit_detects_duplicate_non_monotonic_gaps_and_invalid_ohlc(tmp_path):
    path = tmp_path / "bad.csv"
    _write_mt5(
        path,
        [
            ("2026.05.14 22:55", 100, 101, 99, 100, 1, 0),
            ("2026.05.14 22:55", 100, 101, 99, 100, 1, 0),
            ("2026.05.14 22:50", 100, 101, 99, 100, 1, 0),
            ("2026.05.14 23:20", 105, 104, 106, 105, 1, 0),
        ],
    )
    frame = read_candle_csv(path).frame
    validation = validate_frame(frame, "M5")

    assert validation["duplicate_timestamps"] == 2
    assert validation["non_monotonic_timestamps"] >= 1
    assert validation["gaps"] >= 1
    assert validation["invalid_ohlc_rows"] == 1


def test_audit_writes_summary_and_report_without_modifying_source(tmp_path):
    _seed_data(tmp_path)
    source = tmp_path / "data" / "XAUUSD" / "M1.csv"
    before = source.read_bytes()
    audit = build_audit(tmp_path / "data", "XAUUSD", ["M1"])
    write_audit_report(audit, tmp_path / "reports")

    assert (tmp_path / "reports" / "audit_summary.json").exists()
    assert (tmp_path / "reports" / "audit_report.md").exists()
    assert source.read_bytes() == before


def test_dry_run_does_not_modify_existing_data(tmp_path):
    _seed_data(tmp_path, ["M1"])
    _write_mt5(
        tmp_path / "incoming" / "M1.csv",
        [
            ("2026.05.14 23:05", 102, 103, 101, 102, 1, 0),
        ],
    )
    existing = tmp_path / "data" / "XAUUSD" / "M1.csv"
    before = existing.read_bytes()

    summary = build_ingestion(
        source_dir=tmp_path / "incoming",
        data_dir=tmp_path / "data",
        symbol="XAUUSD",
        timeframes=["M1"],
        dry_run=True,
        apply=False,
        backup=True,
        no_backup=False,
        prefer_incoming=False,
        strict=False,
        run_paper_scanner_after_ingest=False,
    )

    assert summary["dry_run"] is True
    assert summary["total_new_rows_added"] == 1
    assert existing.read_bytes() == before


def test_apply_requires_explicit_apply_and_creates_backup(tmp_path):
    _seed_data(tmp_path, ["M1"])
    _write_mt5(tmp_path / "incoming" / "M1.csv", [("2026.05.14 23:05", 102, 103, 101, 102, 1, 0)])

    dry = build_ingestion(
        source_dir=tmp_path / "incoming",
        data_dir=tmp_path / "data",
        symbol="XAUUSD",
        timeframes=["M1"],
        dry_run=True,
        apply=False,
        backup=True,
        no_backup=False,
        prefer_incoming=False,
        strict=False,
        run_paper_scanner_after_ingest=False,
    )
    assert dry["updated_files"] == []

    applied = build_ingestion(
        source_dir=tmp_path / "incoming",
        data_dir=tmp_path / "data",
        symbol="XAUUSD",
        timeframes=["M1"],
        dry_run=False,
        apply=True,
        backup=True,
        no_backup=False,
        prefer_incoming=False,
        strict=False,
        run_paper_scanner_after_ingest=False,
    )

    assert applied["updated_files"]
    assert applied["backups"]
    assert Path(applied["backups"][0]).exists()
    merged = read_candle_csv(tmp_path / "data" / "XAUUSD" / "M1.csv").frame
    assert len(merged) == 3
    assert list(merged.columns) == ["time", "open", "high", "low", "close", "tick_volume", "spread"]


def test_merge_skips_duplicate_by_default_and_prefer_incoming_replaces(tmp_path):
    _seed_data(tmp_path, ["M1"])
    _write_mt5(tmp_path / "incoming" / "M1.csv", [("2026.05.14 23:00", 200, 201, 199, 200, 1, 0)])

    default = build_ingestion(
        source_dir=tmp_path / "incoming",
        data_dir=tmp_path / "data",
        symbol="XAUUSD",
        timeframes=["M1"],
        dry_run=False,
        apply=True,
        backup=True,
        no_backup=False,
        prefer_incoming=False,
        strict=False,
        run_paper_scanner_after_ingest=False,
    )
    frame = read_candle_csv(tmp_path / "data" / "XAUUSD" / "M1.csv").frame
    assert default["timeframes"][0]["duplicate_rows_skipped"] == 1
    assert float(frame.loc[frame["time"] == pd.Timestamp("2026-05-14 23:00", tz="UTC"), "open"].iloc[0]) == 101.0

    _write_mt5(tmp_path / "incoming" / "M1.csv", [("2026.05.14 23:00", 200, 201, 199, 200, 1, 0)])
    prefer = build_ingestion(
        source_dir=tmp_path / "incoming",
        data_dir=tmp_path / "data",
        symbol="XAUUSD",
        timeframes=["M1"],
        dry_run=False,
        apply=True,
        backup=True,
        no_backup=False,
        prefer_incoming=True,
        strict=False,
        run_paper_scanner_after_ingest=False,
    )
    frame = read_candle_csv(tmp_path / "data" / "XAUUSD" / "M1.csv").frame
    assert prefer["timeframes"][0]["rows_replaced"] == 1
    assert float(frame.loc[frame["time"] == pd.Timestamp("2026-05-14 23:00", tz="UTC"), "open"].iloc[0]) == 200.0


def test_incoming_schema_mapping_and_sorted_output(tmp_path):
    _seed_data(tmp_path, ["M1"])
    incoming = tmp_path / "incoming" / "XAUUSD_M1.csv"
    incoming.parent.mkdir(parents=True)
    incoming.write_text(
        "Timestamp,Open,High,Low,Close,Volume,Spread\n"
        "2026-05-14 23:10,103,104,102,103.5,12,0\n"
        "2026-05-14 23:05,102,103,101,102.5,11,0\n",
        encoding="utf-8",
    )
    summary = build_ingestion(
        source_dir=tmp_path / "incoming",
        data_dir=tmp_path / "data",
        symbol="XAUUSD",
        timeframes=["M1"],
        dry_run=False,
        apply=True,
        backup=True,
        no_backup=False,
        prefer_incoming=False,
        strict=False,
        run_paper_scanner_after_ingest=False,
    )
    frame = read_candle_csv(tmp_path / "data" / "XAUUSD" / "M1.csv").frame
    assert summary["total_new_rows_added"] == 2
    assert frame["time"].is_monotonic_increasing
    assert "tick_volume" in frame.columns


def test_missing_incoming_timeframe_reported_not_fatal(tmp_path):
    _seed_data(tmp_path, ["M1", "M5"])
    _write_mt5(tmp_path / "incoming" / "M1.csv", [("2026.05.14 23:05", 102, 103, 101, 102, 1, 0)])
    summary = build_ingestion(
        source_dir=tmp_path / "incoming",
        data_dir=tmp_path / "data",
        symbol="XAUUSD",
        timeframes=["M1", "M5"],
        dry_run=True,
        apply=False,
        backup=True,
        no_backup=False,
        prefer_incoming=False,
        strict=False,
        run_paper_scanner_after_ingest=False,
    )
    assert "INCOMING_DATA_MISSING" in summary["timeframes"][1]["verdict_flags"]


def test_invalid_incoming_ohlc_fails_validation(tmp_path):
    _seed_data(tmp_path, ["M1"])
    _write_mt5(tmp_path / "incoming" / "M1.csv", [("2026.05.14 23:05", 105, 104, 106, 105, 1, 0)])
    summary = build_ingestion(
        source_dir=tmp_path / "incoming",
        data_dir=tmp_path / "data",
        symbol="XAUUSD",
        timeframes=["M1"],
        dry_run=True,
        apply=False,
        backup=True,
        no_backup=False,
        prefer_incoming=False,
        strict=False,
        run_paper_scanner_after_ingest=False,
    )
    assert "INCOMING_SCHEMA_INVALID" in summary["verdict_flags"]
    assert "FINAL_VALIDATION_FAILED" in summary["verdict_flags"]


def test_ingestion_report_files_written(tmp_path):
    from scripts.import_xauusd_candles import write_ingestion_report

    summary = {
        "symbol": "XAUUSD",
        "source_dir": "incoming",
        "dry_run": True,
        "apply": False,
        "backup_enabled": False,
        "total_new_rows_added": 0,
        "verdict_flags": ["INGESTION_DRY_RUN_OK"],
        "timeframes": [],
    }
    write_ingestion_report(summary, tmp_path)
    assert (tmp_path / "ingestion_summary.json").exists()
    assert (tmp_path / "ingestion_report.md").exists()
    assert json.loads((tmp_path / "ingestion_summary.json").read_text())["symbol"] == "XAUUSD"


def test_scripts_are_import_safe_and_no_live_modules_imported():
    import scripts.audit_xauusd_data as audit
    import scripts.import_xauusd_candles as ingest

    assert hasattr(audit, "main")
    assert hasattr(ingest, "main")
    source = Path(ingest.__file__).read_text().lower()
    assert "import telegram" not in source
    assert "metatrader5" not in source


def test_paper_scanner_rerun_only_when_explicit(monkeypatch, tmp_path):
    _seed_data(tmp_path, ["M1"])
    _write_mt5(tmp_path / "incoming" / "M1.csv", [("2026.05.14 23:05", 102, 103, 101, 102, 1, 0)])
    calls = []
    monkeypatch.setattr("scripts.import_xauusd_candles.subprocess.run", lambda *a, **kw: calls.append((a, kw)))

    build_ingestion(
        source_dir=tmp_path / "incoming",
        data_dir=tmp_path / "data",
        symbol="XAUUSD",
        timeframes=["M1"],
        dry_run=False,
        apply=True,
        backup=True,
        no_backup=False,
        prefer_incoming=False,
        strict=False,
        run_paper_scanner_after_ingest=False,
    )
    assert calls == []

    build_ingestion(
        source_dir=tmp_path / "incoming",
        data_dir=tmp_path / "data",
        symbol="XAUUSD",
        timeframes=["M1"],
        dry_run=False,
        apply=True,
        backup=True,
        no_backup=False,
        prefer_incoming=True,
        strict=False,
        run_paper_scanner_after_ingest=True,
    )
    assert calls
