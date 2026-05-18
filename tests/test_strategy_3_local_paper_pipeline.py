from __future__ import annotations

import importlib
from pathlib import Path


def _pipeline():
    return importlib.import_module("scripts.run_strategy_3_local_paper_pipeline")


def _cfg(module, tmp_path: Path, *, apply=False, loop=False, once=True, run_scanner=True):
    return module.PipelineConfig(
        symbol="XAUUSD",
        symbol_broker="XAUUSD",
        timeframes=["M1", "M5", "M15", "H1", "H4", "D1"],
        days_back=7,
        interval_minutes=15,
        loop=loop,
        once=once,
        apply=apply,
        allow_large_fetch=False,
        allow_overlap_mismatch=False,
        run_scanner=run_scanner,
        from_timestamp="2026-05-19T00:00:00+00:00",
        max_loops=1,
        data_dir=tmp_path / "data",
        incoming_dir=tmp_path / "incoming",
        reports_dir=tmp_path / "reports",
    )


def _fetch(flags=None):
    return {
        "verdict_flags": flags or ["MT5_INCOMING_CSVS_WRITTEN", "MT5_FETCH_OK"],
        "rows_fetched_by_timeframe": {"M1": 1},
    }


def _dry(new_rows=1, flags=None):
    return {
        "verdict_flags": flags or ["INGESTION_DRY_RUN_OK", "DATA_UPDATED"],
        "total_new_rows_added": new_rows,
        "timeframes": [{"timeframe": "M1", "new_rows_added": new_rows}],
    }


def _applied():
    return {
        "verdict_flags": ["INGESTION_APPLIED", "DATA_UPDATED", "BACKUP_CREATED"],
        "total_new_rows_added": 1,
        "timeframes": [{"timeframe": "M1", "new_rows_added": 1}],
    }


def _audit(flags=None):
    return {
        "verdict_flags": flags or ["DATA_AUDIT_OK"],
        "timeframes": [{"timeframe": "M1", "last_timestamp": "2026-05-19T00:00:00+00:00"}],
    }


def _scanner():
    return {
        "signals_detected": 0,
        "signals_accepted": 0,
        "signals_blocked_by_cooldown": 0,
        "new_paper_signals_this_run": 0,
        "paper_signals_total_after_run": 0,
        "no_signal_reason": "no_new_driver_candles_to_process",
    }


def _patch_reports(monkeypatch, module):
    monkeypatch.setattr(module, "write_ingestion_report", lambda *a, **kw: None)
    monkeypatch.setattr(module, "write_audit_report", lambda *a, **kw: None)


def test_no_apply_never_applies(monkeypatch, tmp_path):
    module = _pipeline()
    _patch_reports(monkeypatch, module)
    calls = []
    monkeypatch.setattr(module, "run_collector", lambda *a, **kw: _fetch())

    def fake_ingestion(**kwargs):
        calls.append(kwargs)
        return _dry(new_rows=2)

    monkeypatch.setattr(module, "build_ingestion", fake_ingestion)
    monkeypatch.setattr(module, "build_audit", lambda *a, **kw: _audit())
    monkeypatch.setattr(module, "run_scanner", lambda *a, **kw: _scanner())

    summary = module.run_pipeline_once(_cfg(module, tmp_path, apply=False))

    assert len(calls) == 1
    assert calls[0]["dry_run"] is True
    assert "LOCAL_PIPELINE_NO_APPLY_DRY_RUN_ONLY" in summary["verdict_flags"]
    assert summary["safety"]["order_send_called"] is False


def test_apply_runs_only_after_sane_dry_run_and_then_scanner(monkeypatch, tmp_path):
    module = _pipeline()
    _patch_reports(monkeypatch, module)
    calls = []
    monkeypatch.setattr(module, "run_collector", lambda *a, **kw: _fetch())

    def fake_ingestion(**kwargs):
        calls.append(kwargs)
        return _dry(new_rows=1) if kwargs["dry_run"] else _applied()

    seen_scanner = {}
    monkeypatch.setattr(module, "build_ingestion", fake_ingestion)
    monkeypatch.setattr(module, "build_audit", lambda *a, **kw: _audit())
    def fake_scanner(cfg):
        seen_scanner["cfg"] = cfg
        return _scanner()

    monkeypatch.setattr(module, "run_scanner", fake_scanner)

    summary = module.run_pipeline_once(_cfg(module, tmp_path, apply=True))

    assert [call["apply"] for call in calls] == [False, True]
    assert summary["import_apply_status"] == ["INGESTION_APPLIED", "DATA_UPDATED", "BACKUP_CREATED"]
    assert seen_scanner["cfg"].dry_run is True
    assert seen_scanner["cfg"].incremental is True


def test_overlap_and_timezone_block_apply(monkeypatch, tmp_path):
    module = _pipeline()
    _patch_reports(monkeypatch, module)
    dry_called = {"value": False}
    monkeypatch.setattr(module, "run_collector", lambda *a, **kw: _fetch(["MT5_INCOMING_CSVS_WRITTEN", "OVERLAP_MATCH_LT_95"]))
    monkeypatch.setattr(module, "build_ingestion", lambda **kw: dry_called.update(value=True) or _dry())
    monkeypatch.setattr(module, "build_audit", lambda *a, **kw: _audit())

    summary = module.run_pipeline_once(_cfg(module, tmp_path, apply=True))

    assert dry_called["value"] is False
    assert "LOCAL_PIPELINE_FETCH_FAILED" in summary["verdict_flags"]

    monkeypatch.setattr(module, "run_collector", lambda *a, **kw: _fetch(["MT5_INCOMING_CSVS_WRITTEN", "MT5_TIMEZONE_MISMATCH_DETECTED"]))
    summary = module.run_pipeline_once(_cfg(module, tmp_path, apply=True))
    assert "LOCAL_PIPELINE_FETCH_FAILED" in summary["verdict_flags"]


def test_audit_structural_failure_blocks_scanner_but_gaps_do_not(monkeypatch, tmp_path):
    module = _pipeline()
    _patch_reports(monkeypatch, module)
    scanner_calls = {"count": 0}
    monkeypatch.setattr(module, "run_collector", lambda *a, **kw: _fetch())
    monkeypatch.setattr(module, "build_ingestion", lambda **kw: _dry(new_rows=0))
    monkeypatch.setattr(module, "run_scanner", lambda *a, **kw: scanner_calls.update(count=scanner_calls["count"] + 1) or _scanner())

    monkeypatch.setattr(module, "build_audit", lambda *a, **kw: _audit(["DATA_AUDIT_FAILED", "INVALID_OHLC_DETECTED"]))
    failed = module.run_pipeline_once(_cfg(module, tmp_path, apply=False))
    assert "LOCAL_PIPELINE_AUDIT_FAILED" in failed["verdict_flags"]
    assert scanner_calls["count"] == 0

    monkeypatch.setattr(module, "build_audit", lambda *a, **kw: _audit(["DATA_AUDIT_WARNINGS", "GAPS_DETECTED"]))
    warning = module.run_pipeline_once(_cfg(module, tmp_path, apply=False))
    assert "LOCAL_PIPELINE_AUDIT_FAILED" not in warning["verdict_flags"]
    assert scanner_calls["count"] == 1


def test_no_new_rows_is_not_failure_and_reports_are_written(monkeypatch, tmp_path):
    module = _pipeline()
    _patch_reports(monkeypatch, module)
    monkeypatch.setattr(module, "run_collector", lambda *a, **kw: _fetch())
    monkeypatch.setattr(module, "build_ingestion", lambda **kw: _dry(new_rows=0, flags=["INGESTION_DRY_RUN_OK", "NO_NEW_ROWS_FOUND"]))
    monkeypatch.setattr(module, "build_audit", lambda *a, **kw: _audit())
    monkeypatch.setattr(module, "run_scanner", lambda *a, **kw: _scanner())

    summary = module.run_pipeline_once(_cfg(module, tmp_path, apply=False))

    assert "LOCAL_PIPELINE_NO_NEW_ROWS" in summary["verdict_flags"]
    assert (tmp_path / "reports" / "pipeline_summary.json").exists()
    assert (tmp_path / "reports" / "pipeline_run.md").exists()


def test_loop_mode_respects_max_loops_and_keyboard_interrupt(monkeypatch, tmp_path):
    module = _pipeline()
    calls = {"count": 0}

    def fake_once(cfg):
        calls["count"] += 1
        return {"verdict_flags": ["LOCAL_PIPELINE_OK"], "loops_completed": 1}

    monkeypatch.setattr(module, "run_pipeline_once", fake_once)
    monkeypatch.setattr(module.time, "sleep", lambda *a, **kw: None)

    summary = module.run_pipeline(_cfg(module, tmp_path, loop=True, once=False))
    assert calls["count"] == 1
    assert summary["loops_completed"] == 1

    def interrupt_once(cfg):
        raise KeyboardInterrupt

    monkeypatch.setattr(module, "run_pipeline_once", interrupt_once)
    stopped = module.run_pipeline(_cfg(module, tmp_path, loop=True, once=False))
    assert "LOCAL_PIPELINE_STOPPED_BY_USER" in stopped["verdict_flags"]
