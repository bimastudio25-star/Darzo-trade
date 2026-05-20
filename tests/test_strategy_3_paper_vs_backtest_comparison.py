from __future__ import annotations

import csv
import importlib
import json
from pathlib import Path


def _module():
    return importlib.import_module("scripts.compare_strategy_3_paper_vs_backtest")


def _paper_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "signal_timestamp": "2026-05-20T10:00:00+00:00",
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
        "cooldown_accepted": "True",
        "cooldown_status": "accepted",
        "order_sent": "False",
        "telegram_sent": "False",
        "broker_called": "False",
    }
    row.update(updates)
    return row


def _backtest_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "signal_timestamp": "2026-05-20T10:00:00+00:00",
        "symbol": "XAUUSD",
        "strategy": "strategy_3_vwap_1r",
        "direction": "LONG",
        "entry_price": 4500.00,
        "stop_loss": 4498.00,
        "take_profit": 4502.00,
        "setup_mode": "trend_following",
        "band_touched": "vwap",
        "cooldown_accepted": True,
    }
    row.update(updates)
    return row


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
                "first_timestamp": "2026-05-20T00:00:00+00:00",
                "latest_timestamp": "2026-05-20T10:00:00+00:00",
                "detected_encoding": "utf-8",
                "header_present": True,
            }
            for tf in ["M1", "M5", "M15", "H1", "H4", "D1"]
        },
    }


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = list(dict.fromkeys(_module().REQUIRED_FIELDS + list(_paper_row().keys())))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_context(tmp_path: Path, *, paper_clean: bool = True, h4_clean: bool = True) -> tuple[Path, Path, Path, Path, Path]:
    paper_path = tmp_path / "paper" / "paper_signals.csv"
    scanner_summary = tmp_path / "paper" / "scanner_summary.json"
    pipeline_summary = tmp_path / "pipeline" / "pipeline_summary.json"
    repair_report = tmp_path / "h4" / "h4_repair_report.json"
    post_diag = tmp_path / "h4post" / "h4_data_source_diagnostic.json"
    scanner_summary.parent.mkdir(parents=True, exist_ok=True)
    pipeline_summary.parent.mkdir(parents=True, exist_ok=True)
    repair_report.parent.mkdir(parents=True, exist_ok=True)
    post_diag.parent.mkdir(parents=True, exist_ok=True)
    scanner_summary.write_text(json.dumps({"paper_signals_clean_for_validation": paper_clean, "data_context": _data_context()}), encoding="utf-8")
    pipeline_summary.write_text(
        json.dumps(
            {
                "paper_signals_clean_for_validation": paper_clean,
                "h4_quarantine_status": "fresh" if h4_clean else "stale_blocking",
                "h4_stale_by_bars": 0 if h4_clean else 3,
                "h4_latest_existing_timestamp": "2026-05-20T16:00:00+00:00",
                "h4_expected_latest_closed_timestamp": "2026-05-20T16:00:00+00:00",
                "verdict_flags": ["LOCAL_PIPELINE_OK"],
            }
        ),
        encoding="utf-8",
    )
    repair_report.write_text(
        json.dumps(
            {
                "backup_path": "data/XAUUSD/H4.csv.backup.test",
                "post_repair_freshness_status": "fresh" if h4_clean else "stale_blocking",
                "post_repair_overlap_match_rate": 1.0,
            }
        ),
        encoding="utf-8",
    )
    post_diag.write_text(
        json.dumps({"overlap": {"match_rate_ohlc": 1.0, "match_rate_ohlcv": 0.04, "mismatch_type": "volume_only"}}),
        encoding="utf-8",
    )
    return paper_path, scanner_summary, pipeline_summary, repair_report, post_diag


def _config(tmp_path: Path, *, paper_clean: bool = True, h4_clean: bool = True):
    module = _module()
    paper, scanner, pipeline, repair, post = _write_context(tmp_path, paper_clean=paper_clean, h4_clean=h4_clean)
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
        h4_repair_report_path=repair,
        h4_post_repair_diagnostic_path=post,
    )


def test_import_safe_and_cli_defaults():
    module = _module()
    args = module.parse_args([])
    assert args.price_tolerance == 0.01
    assert args.timestamp_tolerance_seconds == 0
    assert hasattr(module, "main")


def test_exact_timestamp_matching_and_zero_tolerance():
    module = _module()
    exact = module.compare_signals([_paper_row()], [_backtest_row()], timestamp_tolerance_seconds=0)
    shifted = module.compare_signals(
        [_paper_row()],
        [_backtest_row(signal_timestamp="2026-05-20T10:00:01+00:00")],
        timestamp_tolerance_seconds=0,
    )
    assert exact["match_rate"] == 1.0
    assert shifted["match_rate"] == 0.0
    assert shifted["mismatch_categories"]["MISSING_IN_BACKTEST"] == 1
    assert shifted["mismatch_categories"]["EXTRA_IN_BACKTEST"] == 1


def test_price_tolerance_accepts_small_and_rejects_large():
    module = _module()
    small = module.compare_signals([_paper_row(entry_price="4500.00")], [_backtest_row(entry_price=4500.009)], price_tolerance_usd=0.01)
    large = module.compare_signals([_paper_row(entry_price="4500.00")], [_backtest_row(entry_price=4500.02)], price_tolerance_usd=0.01)
    assert small["match_rate"] == 1.0
    assert large["mismatch_categories"]["ENTRY_PRICE_MISMATCH"] == 1


def test_accepted_only_excludes_blocked_signals(monkeypatch, tmp_path):
    module = _module()
    cfg = _config(tmp_path)
    _write_csv(
        cfg.paper_signals_path,
        [_paper_row(cooldown_accepted="True"), _paper_row(signal_timestamp="2026-05-20T10:15:00+00:00", cooldown_accepted="False")],
    )
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context())
    monkeypatch.setattr(
        module,
        "build_backtest_comparable_signals",
        lambda _cfg, _window: [_backtest_row(cooldown_accepted=True), _backtest_row(signal_timestamp="2026-05-20T10:15:00+00:00", cooldown_accepted=False)],
    )
    summary = module.run_comparison(cfg)
    assert summary["paper_detected_count"] == 2
    assert summary["paper_accepted_count"] == 1
    assert summary["accepted_only"]["matched_count"] == 1


def test_cooldown_status_mismatch_is_detected():
    module = _module()
    result = module.compare_signals([_paper_row(cooldown_accepted="True")], [_backtest_row(cooldown_accepted=False)])
    assert result["mismatch_categories"]["COOLDOWN_STATUS_MISMATCH"] == 1


def test_missing_fields_are_reported_without_crash(tmp_path):
    module = _module()
    cfg = _config(tmp_path)
    cfg.paper_signals_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg.paper_signals_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["signal_timestamp"])
        writer.writeheader()
        writer.writerow({"signal_timestamp": "2026-05-20T10:00:00+00:00"})
    summary = module.run_comparison(cfg)
    assert "direction" in summary["missing_fields"]["missing_schema_fields"]
    assert (cfg.output_dir / "missing_fields_summary.json").exists()


def test_h4_not_clean_blocks_clean_verdict(monkeypatch, tmp_path):
    module = _module()
    cfg = _config(tmp_path, h4_clean=False)
    _write_csv(cfg.paper_signals_path, [_paper_row()])
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context())
    monkeypatch.setattr(module, "build_backtest_comparable_signals", lambda _cfg, _window: [_backtest_row()])
    summary = module.run_comparison(cfg)
    assert "HTF_CONTEXT_CAVEAT_REQUIRES_DATA_DIAGNOSTIC" in summary["verdict_flags"]
    assert "SHADOW_BACKTEST_ACCEPTED_MATCH_OK" not in summary["verdict_flags"]


def test_paper_not_clean_blocks_clean_verdict(monkeypatch, tmp_path):
    module = _module()
    cfg = _config(tmp_path, paper_clean=False)
    _write_csv(cfg.paper_signals_path, [_paper_row()])
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context())
    monkeypatch.setattr(module, "build_backtest_comparable_signals", lambda _cfg, _window: [_backtest_row()])
    summary = module.run_comparison(cfg)
    assert "PAPER_SIGNALS_NOT_CLEAN_FOR_VALIDATION" in summary["verdict_flags"]
    assert "SHADOW_BACKTEST_ACCEPTED_MATCH_OK" not in summary["verdict_flags"]


def test_outputs_and_safety_fields(monkeypatch, tmp_path):
    module = _module()
    cfg = _config(tmp_path)
    _write_csv(cfg.paper_signals_path, [_paper_row()])
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context())
    monkeypatch.setattr(module, "build_backtest_comparable_signals", lambda _cfg, _window: [_backtest_row()])
    summary = module.run_comparison(cfg)
    assert (cfg.output_dir / "comparison_summary.json").exists()
    assert (cfg.output_dir / "comparison_all_detected.csv").exists()
    assert (cfg.output_dir / "comparison_accepted_only.csv").exists()
    assert (cfg.output_dir / "mismatch_details.csv").exists()
    assert summary["safety"]["order_sent"] is False
    assert summary["safety"]["telegram_sent"] is False
    assert summary["safety"]["broker_called"] is False
    assert "SHADOW_BACKTEST_ACCEPTED_MATCH_OK" in summary["verdict_flags"]


def test_comparison_detects_matching_data_context(monkeypatch, tmp_path):
    module = _module()
    cfg = _config(tmp_path)
    _write_csv(cfg.paper_signals_path, [_paper_row()])
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context())
    monkeypatch.setattr(module, "build_backtest_comparable_signals", lambda _cfg, _window: [_backtest_row()])
    summary = module.run_comparison(cfg)
    assert summary["data_context_match"] is True
    assert "DATA_CONTEXT_MATCH" in summary["verdict_flags"]
    assert "SHADOW_BACKTEST_ACCEPTED_MATCH_OK" in summary["verdict_flags"]


def test_comparison_detects_mismatched_data_context(monkeypatch, tmp_path):
    module = _module()
    cfg = _config(tmp_path)
    _write_csv(cfg.paper_signals_path, [_paper_row()])
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context("other"))
    monkeypatch.setattr(module, "build_backtest_comparable_signals", lambda _cfg, _window: [_backtest_row()])
    summary = module.run_comparison(cfg)
    assert summary["data_context_match"] is False
    assert "DATA_CONTEXT_MISMATCH" in summary["verdict_flags"]
    assert "COMPARISON_NOT_CLEAN_VALIDATION" in summary["verdict_flags"]
    assert "SHADOW_BACKTEST_ACCEPTED_MATCH_OK" not in summary["verdict_flags"]


def test_missing_data_context_blocks_clean_verdict(monkeypatch, tmp_path):
    module = _module()
    cfg = _config(tmp_path)
    scanner_summary = json.loads(cfg.scanner_summary_path.read_text(encoding="utf-8"))
    scanner_summary.pop("data_context", None)
    cfg.scanner_summary_path.write_text(json.dumps(scanner_summary), encoding="utf-8")
    _write_csv(cfg.paper_signals_path, [_paper_row()])
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context())
    monkeypatch.setattr(module, "build_backtest_comparable_signals", lambda _cfg, _window: [_backtest_row()])
    summary = module.run_comparison(cfg)
    assert summary["data_context_missing"] is True
    assert "DATA_CONTEXT_MISSING" in summary["verdict_flags"]
    assert "PAPER_SIGNALS_CLEAN_FOR_VALIDATION" not in summary["verdict_flags"]


def test_allow_data_context_mismatch_is_still_diagnostic(monkeypatch, tmp_path):
    module = _module()
    cfg = module.PaperVsBacktestConfig(**{**_config(tmp_path).__dict__, "allow_data_context_mismatch": True})
    _write_csv(cfg.paper_signals_path, [_paper_row()])
    monkeypatch.setattr(module, "compute_data_context", lambda **kwargs: _data_context("other"))
    monkeypatch.setattr(module, "build_backtest_comparable_signals", lambda _cfg, _window: [_backtest_row()])
    summary = module.run_comparison(cfg)
    assert "DATA_CONTEXT_MISMATCH_ALLOWED_DIAGNOSTIC" in summary["verdict_flags"]
    assert "COMPARISON_NOT_CLEAN_VALIDATION" in summary["verdict_flags"]
    assert "SHADOW_BACKTEST_ACCEPTED_MATCH_OK" not in summary["verdict_flags"]
