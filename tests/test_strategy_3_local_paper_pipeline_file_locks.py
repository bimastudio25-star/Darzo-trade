from __future__ import annotations

import importlib
import json
from pathlib import Path

import pandas as pd
import pytest


def _ingest():
    return importlib.import_module("scripts.import_xauusd_candles")


def _pipeline():
    return importlib.import_module("scripts.run_strategy_3_local_paper_pipeline")


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": pd.Timestamp("2026-05-19T01:00:00Z"), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "tick_volume": 10, "spread": 1},
            {"time": pd.Timestamp("2026-05-19T01:05:00Z"), "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.5, "tick_volume": 11, "spread": 1},
        ]
    )


def _seed_target(path: Path) -> bytes:
    original = "2026.05.19 01:00,1,2,0,1,1,0\n".encode("utf-16")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(original)
    return original


def test_write_project_csv_succeeds_and_uses_unique_temp_name(monkeypatch, tmp_path):
    module = _ingest()
    target = tmp_path / "M5.csv"
    _seed_target(target)
    original_replace = module.os.replace
    seen_sources: list[Path] = []

    def tracking_replace(src, dst):
        seen_sources.append(Path(src))
        original_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", tracking_replace)

    module.write_project_csv(_frame(), target, ["time", "open", "high", "low", "close", "tick_volume", "spread"], timestamp_has_time=True)

    assert target.exists()
    assert seen_sources
    assert seen_sources[0].name.startswith("M5.csv.")
    assert not seen_sources[0].name.endswith("M5.csv.tmp")


def test_permission_error_on_replace_is_retried_then_succeeds(monkeypatch, tmp_path):
    module = _ingest()
    target = tmp_path / "M5.csv"
    _seed_target(target)
    original_replace = module.os.replace
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError("locked")
        original_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", flaky_replace)
    monkeypatch.setattr(module, "sleep", lambda *_: None)

    module.write_project_csv(
        _frame(),
        target,
        ["time", "open", "high", "low", "close", "tick_volume", "spread"],
        timestamp_has_time=True,
        retry_count=4,
    )

    assert calls["count"] == 3
    assert "2026" in target.read_text(encoding="utf-16")


def test_persistent_permission_error_preserves_target_and_temp(monkeypatch, tmp_path):
    module = _ingest()
    target = tmp_path / "M5.csv"
    original = _seed_target(target)

    def locked_replace(src, dst):
        raise PermissionError("locked")

    monkeypatch.setattr(module.os, "replace", locked_replace)
    monkeypatch.setattr(module, "sleep", lambda *_: None)

    with pytest.raises(module.CsvReplacePermissionError) as exc_info:
        module.write_project_csv(
            _frame(),
            target,
            ["time", "open", "high", "low", "close", "tick_volume", "spread"],
            timestamp_has_time=True,
            retry_count=3,
        )

    err = exc_info.value
    assert err.attempts == 3
    assert target.read_bytes() == original
    assert err.temp_path.exists()
    assert err.to_dict()["target_path"] == str(target)


def test_build_ingestion_reports_partial_file_lock(monkeypatch, tmp_path):
    module = _ingest()
    data_dir = tmp_path / "data" / "XAUUSD"
    incoming_dir = tmp_path / "incoming"
    for tf in ("M1", "M5"):
        _seed_target(data_dir / f"{tf}.csv")
        _seed_target(incoming_dir / f"{tf}.csv")

    def fail_on_m5(df, path, schema, *, timestamp_has_time, **kwargs):
        if path.name == "M5.csv":
            tmp = path.with_name("M5.csv.locked.tmp")
            tmp.write_text("preserved", encoding="utf-8")
            raise module.CsvReplacePermissionError(target_path=path, temp_path=tmp, attempts=8, last_error=PermissionError("locked"))

    monkeypatch.setattr(module, "write_project_csv", fail_on_m5)

    summary = module.build_ingestion(
        source_dir=incoming_dir,
        data_dir=tmp_path / "data",
        symbol="XAUUSD",
        timeframes=["M1", "M5"],
        dry_run=False,
        apply=True,
        backup=True,
        no_backup=False,
        prefer_incoming=True,
        strict=False,
        run_paper_scanner_after_ingest=False,
    )

    assert "INGESTION_FILE_LOCKED" in summary["verdict_flags"]
    assert summary["ingestion_apply_status"] == "file_locked"
    assert summary["failed_timeframe"] == "M5"
    assert summary["replace_attempts"] == 8
    assert summary["scanner_skipped_due_to_ingestion_failure"] is True


def test_pipeline_file_lock_summary_skips_scanner(monkeypatch, tmp_path):
    module = _pipeline()
    monkeypatch.setattr(module, "run_collector", lambda *a, **kw: {"verdict_flags": ["MT5_INCOMING_CSVS_WRITTEN", "MT5_FETCH_OK"]})
    monkeypatch.setattr(module, "write_ingestion_report", lambda *a, **kw: None)
    monkeypatch.setattr(module, "write_audit_report", lambda *a, **kw: None)
    monkeypatch.setattr(module, "build_audit", lambda *a, **kw: {"verdict_flags": ["DATA_AUDIT_OK"], "timeframes": []})
    scanner_called = {"value": False}
    monkeypatch.setattr(module, "run_scanner", lambda *a, **kw: scanner_called.update(value=True))

    def fake_ingestion(**kwargs):
        if kwargs["dry_run"]:
            return {"verdict_flags": ["INGESTION_DRY_RUN_OK", "DATA_UPDATED"], "total_new_rows_added": 1, "timeframes": [{"timeframe": "M5", "new_rows_added": 1}]}
        return {
            "verdict_flags": ["INGESTION_FILE_LOCKED", "FILE_LOCKED_DURING_REPLACE", "PARTIAL_APPLY_FAILED"],
            "ingestion_apply_status": "file_locked",
            "failed_timeframe": "M5",
            "failed_path": "data/XAUUSD/M5.csv",
            "temp_path_preserved": "data/XAUUSD/M5.csv.1.tmp",
            "replace_attempts": 8,
            "completed_timeframes": ["M1"],
            "skipped_timeframes_after_failure": ["M15"],
            "scanner_skipped_due_to_ingestion_failure": True,
            "timeframes": [{"timeframe": "M5", "new_rows_added": 1}],
            "total_new_rows_added": 1,
        }

    monkeypatch.setattr(module, "build_ingestion", fake_ingestion)
    cfg = module.PipelineConfig(
        symbol="XAUUSD",
        symbol_broker="XAUUSD",
        timeframes=["M1", "M5"],
        days_back=7,
        interval_minutes=15,
        loop=True,
        once=False,
        apply=True,
        allow_large_fetch=False,
        allow_overlap_mismatch=False,
        run_scanner=True,
        from_timestamp=None,
        max_loops=1,
        data_dir=tmp_path / "data",
        incoming_dir=tmp_path / "incoming",
        reports_dir=tmp_path / "reports",
    )

    summary = module.run_pipeline_once(cfg)

    assert "LOCAL_PIPELINE_FILE_LOCKED_RETRY_NEXT_LOOP" in summary["verdict_flags"]
    assert summary["scanner_skipped_due_to_ingestion_failure"] is True
    assert summary["loop_will_retry"] is True
    assert scanner_called["value"] is False


def test_onedrive_warning_and_duplicate_lock_summary(tmp_path):
    module = _pipeline()
    assert module._onedrive_warning(Path("C:/Users/user/OneDrive/repo"))
    cfg = module.PipelineConfig(
        symbol="XAUUSD",
        symbol_broker="XAUUSD",
        timeframes=["M1"],
        days_back=7,
        interval_minutes=15,
        loop=True,
        once=False,
        apply=True,
        allow_large_fetch=False,
        allow_overlap_mismatch=False,
        run_scanner=False,
        from_timestamp=None,
        max_loops=1,
        reports_dir=tmp_path / "reports",
    )
    cfg.reports_dir.mkdir(parents=True)
    (cfg.reports_dir / "pipeline.lock").write_text(json.dumps({"pid": 999999, "started_at": "now"}), encoding="utf-8")

    summary = module.run_pipeline(cfg)

    assert "DUPLICATE_PIPELINE_LOCK_DETECTED" in summary["verdict_flags"]
    assert summary["duplicate_pipeline_warning"]
