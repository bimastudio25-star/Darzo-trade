from __future__ import annotations

import csv
import importlib
import json
from pathlib import Path


def _module():
    return importlib.import_module("scripts.compare_strategy_3_paper_vs_backtest")


def _row(timestamp: str, *, accepted: bool = True, context_hash: str | None = "ctx") -> dict[str, object]:
    return {
        "signal_timestamp": timestamp,
        "symbol": "XAUUSD",
        "strategy": "strategy_3_vwap_1r",
        "mode": "paper_shadow",
        "dry_run": "True",
        "cooldown_minutes": "120",
        "direction": "LONG",
        "entry_price": "4500.00",
        "stop_loss": "4498.00",
        "take_profit": "4502.00",
        "setup_mode": "trend_following",
        "band_touched": "vwap",
        "cooldown_accepted": str(accepted),
        "cooldown_status": "accepted" if accepted else "blocked",
        "data_context_hash": context_hash or "",
        "order_sent": "False",
        "telegram_sent": "False",
        "broker_called": "False",
    }


def _backtest(timestamp: str, *, accepted: bool = True) -> dict[str, object]:
    return {
        "signal_timestamp": timestamp,
        "symbol": "XAUUSD",
        "strategy": "strategy_3_vwap_1r",
        "direction": "LONG",
        "entry_price": 4500.00,
        "stop_loss": 4498.00,
        "take_profit": 4502.00,
        "setup_mode": "trend_following",
        "band_touched": "vwap",
        "cooldown_accepted": accepted,
    }


def _data_context(hash_value: str = "ctx") -> dict[str, object]:
    return {
        "combined_data_context_hash": hash_value,
        "symbol": "XAUUSD",
        "timeframes_included": ["M1", "M5", "M15", "H1", "H4", "D1"],
        "files": {
            tf: {
                "exists": True,
                "sha256": f"{hash_value}-{tf}",
                "file_size": 10,
                "row_count": 1,
                "first_timestamp": "2026-05-21T00:00:00+00:00",
                "latest_timestamp": "2026-05-22T22:00:00+00:00",
                "detected_encoding": "utf-8",
                "header_present": True,
            }
            for tf in ["M1", "M5", "M15", "H1", "H4", "D1"]
        },
    }


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    module = _module()
    fields = list(dict.fromkeys(module.REQUIRED_FIELDS + ["data_context_hash"] + list(_row("2026-05-21T02:30:00+00:00").keys())))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _config(tmp_path: Path, *, scanner_context: str | None = "ctx"):
    module = _module()
    paper = tmp_path / "paper" / "paper_signals.csv"
    scanner = tmp_path / "paper" / "scanner_summary.json"
    pipeline = tmp_path / "pipeline" / "pipeline_summary.json"
    repair = tmp_path / "h4" / "h4_repair_report.json"
    post = tmp_path / "h4post" / "h4_data_source_diagnostic.json"
    scanner.parent.mkdir(parents=True, exist_ok=True)
    pipeline.parent.mkdir(parents=True, exist_ok=True)
    repair.parent.mkdir(parents=True, exist_ok=True)
    post.parent.mkdir(parents=True, exist_ok=True)
    scanner_payload = {"paper_signals_clean_for_validation": True}
    if scanner_context is not None:
        scanner_payload["data_context"] = _data_context(scanner_context)
    scanner.write_text(json.dumps(scanner_payload), encoding="utf-8")
    pipeline.write_text(
        json.dumps(
            {
                "paper_signals_clean_for_validation": True,
                "summary_consistency_status": "consistent",
                "h4_quarantine_status": "fresh",
                "h4_stale_by_bars": 0,
                "verdict_flags": ["LOCAL_PIPELINE_OK"],
            }
        ),
        encoding="utf-8",
    )
    repair.write_text(json.dumps({"post_repair_freshness_status": "fresh", "post_repair_overlap_match_rate": 1.0}), encoding="utf-8")
    post.write_text(json.dumps({"overlap": {"match_rate_ohlc": 1.0, "match_rate_ohlcv": 0.04}}), encoding="utf-8")
    return module.PaperVsBacktestConfig(
        symbol="XAUUSD",
        data_dir="data",
        paper_signals_path=paper,
        scanner_summary_path=scanner,
        pipeline_summary_path=pipeline,
        output_dir=tmp_path / "out",
        cooldown_minutes=120,
        timestamp_tolerance_seconds=0,
        price_tolerance=0.01,
        dry_run=True,
        require_data_context=True,
        exclude_legacy_without_context=True,
        clean_context_only=True,
        h4_repair_report_path=repair,
        h4_post_repair_diagnostic_path=post,
    )


def test_legacy_rows_without_data_context_are_excluded(monkeypatch, tmp_path):
    module = _module()
    cfg = _config(tmp_path)
    _write_csv(
        cfg.paper_signals_path,
        [
            _row("2026-05-19T02:00:00+00:00", context_hash=None),
            _row("2026-05-21T02:30:00+00:00", context_hash="ctx"),
        ],
    )
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context("ctx"))
    monkeypatch.setattr(module, "build_backtest_comparable_signals", lambda _cfg, _window: [_backtest("2026-05-21T02:30:00+00:00")])

    summary = module.run_comparison(cfg)

    assert summary["total_paper_rows"] == 2
    assert summary["legacy_without_context_rows"] == 1
    assert summary["context_tagged_rows"] == 1
    assert summary["paper_detected_count"] == 1
    assert (cfg.output_dir / "clean_context_excluded_legacy_rows.csv").exists()


def test_clean_window_uses_only_context_tagged_rows(monkeypatch, tmp_path):
    module = _module()
    cfg = _config(tmp_path)
    _write_csv(
        cfg.paper_signals_path,
        [
            _row("2026-05-19T02:00:00+00:00", context_hash=None),
            _row("2026-05-21T02:30:00+00:00", context_hash="ctx"),
            _row("2026-05-22T22:30:00+00:00", context_hash="ctx", accepted=False),
        ],
    )
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context("ctx"))
    monkeypatch.setattr(
        module,
        "build_backtest_comparable_signals",
        lambda _cfg, _window: [_backtest("2026-05-21T02:30:00+00:00"), _backtest("2026-05-22T22:30:00+00:00", accepted=False)],
    )

    summary = module.run_comparison(cfg)

    assert summary["comparison_window"]["earliest_paper_signal_timestamp"] == "2026-05-21T02:30:00+00:00"
    assert summary["comparison_window"]["latest_paper_signal_timestamp"] == "2026-05-22T22:30:00+00:00"
    assert summary["context_tagged_accepted"] == 1
    assert summary["context_tagged_blocked"] == 1


def test_multiple_data_context_hashes_are_detected_and_block_clean_verdict(monkeypatch, tmp_path):
    module = _module()
    cfg = _config(tmp_path)
    _write_csv(
        cfg.paper_signals_path,
        [
            _row("2026-05-21T02:30:00+00:00", context_hash="ctx-a"),
            _row("2026-05-21T03:00:00+00:00", context_hash="ctx-b"),
        ],
    )
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context("ctx"))
    monkeypatch.setattr(
        module,
        "build_backtest_comparable_signals",
        lambda _cfg, _window: [_backtest("2026-05-21T02:30:00+00:00"), _backtest("2026-05-21T03:00:00+00:00")],
    )

    summary = module.run_comparison(cfg)

    assert summary["unique_data_context_hashes"] == 2
    assert "MULTIPLE_DATA_CONTEXTS_REQUIRE_SEGMENTATION" in summary["verdict_flags"]
    assert "CLEAN_CONTEXT_ACCEPTED_MATCH_OK" not in summary["verdict_flags"]


def test_data_context_missing_blocks_clean_validation(monkeypatch, tmp_path):
    module = _module()
    cfg = _config(tmp_path, scanner_context=None)
    _write_csv(cfg.paper_signals_path, [_row("2026-05-21T02:30:00+00:00", context_hash="ctx")])
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context("ctx"))
    monkeypatch.setattr(module, "build_backtest_comparable_signals", lambda _cfg, _window: [_backtest("2026-05-21T02:30:00+00:00")])

    summary = module.run_comparison(cfg)

    assert "DATA_CONTEXT_MISSING" in summary["verdict_flags"]
    assert "CLEAN_CONTEXT_ACCEPTED_MATCH_OK" not in summary["verdict_flags"]


def test_data_context_mismatch_blocks_clean_validation(monkeypatch, tmp_path):
    module = _module()
    cfg = _config(tmp_path, scanner_context="ctx")
    _write_csv(cfg.paper_signals_path, [_row("2026-05-21T02:30:00+00:00", context_hash="ctx")])
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context("other"))
    monkeypatch.setattr(module, "build_backtest_comparable_signals", lambda _cfg, _window: [_backtest("2026-05-21T02:30:00+00:00")])

    summary = module.run_comparison(cfg)

    assert "DATA_CONTEXT_MISMATCH" in summary["verdict_flags"]
    assert "COMPARISON_NOT_CLEAN_VALIDATION" in summary["verdict_flags"]


def test_context_match_allows_clean_verdict_when_accepted_match_rate_passes(monkeypatch, tmp_path):
    module = _module()
    cfg = _config(tmp_path, scanner_context="ctx")
    _write_csv(cfg.paper_signals_path, [_row("2026-05-21T02:30:00+00:00", context_hash="ctx")])
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context("ctx"))
    monkeypatch.setattr(module, "build_backtest_comparable_signals", lambda _cfg, _window: [_backtest("2026-05-21T02:30:00+00:00")])

    summary = module.run_comparison(cfg)

    assert "CLEAN_CONTEXT_ACCEPTED_MATCH_OK" in summary["verdict_flags"]
    assert "PAPER_BACKTEST_CONTEXT_MATCH" in summary["verdict_flags"]


def test_clean_verdict_not_emitted_when_accepted_match_rate_below_gate(monkeypatch, tmp_path):
    module = _module()
    cfg = _config(tmp_path, scanner_context="ctx")
    _write_csv(
        cfg.paper_signals_path,
        [
            _row("2026-05-21T02:30:00+00:00", context_hash="ctx"),
            _row("2026-05-21T03:00:00+00:00", context_hash="ctx"),
        ],
    )
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context("ctx"))
    monkeypatch.setattr(module, "build_backtest_comparable_signals", lambda _cfg, _window: [_backtest("2026-05-21T02:30:00+00:00")])

    summary = module.run_comparison(cfg)

    assert summary["match_rate_accepted_only"] == 0.5
    assert "CLEAN_CONTEXT_ACCEPTED_MATCH_OK" not in summary["verdict_flags"]
    assert "CLEAN_CONTEXT_MINOR_MISMATCHES" not in summary["verdict_flags"]
