from __future__ import annotations

import csv
import importlib
import json
from pathlib import Path


def _module():
    return importlib.import_module("scripts.diagnose_strategy_3_runtime_comparison_mismatches")


def _paper(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "signal_timestamp": "2026-05-20T10:00:00+00:00",
        "generated_at": "2026-05-20T10:01:00+00:00",
        "direction": "LONG",
        "setup_mode": "trend_following",
        "band_touched": "vwap",
        "entry_price": "4500.00",
        "stop_loss": "4499.00",
        "take_profit": "4501.00",
        "cooldown_accepted": "True",
        "cooldown_status": "accepted",
        "order_sent": "False",
        "telegram_sent": "False",
        "broker_called": "False",
    }
    row.update(updates)
    return row


def _backtest(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "signal_timestamp": "2026-05-20T10:00:00+00:00",
        "direction": "LONG",
        "setup_mode": "trend_following",
        "band_touched": "vwap",
        "entry_price": 4500.00,
        "stop_loss": 4499.00,
        "take_profit": 4501.00,
        "cooldown_accepted": True,
        "cooldown_status": "accepted",
    }
    row.update(updates)
    return row


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fieldnames or list(dict.fromkeys(key for row in rows for key in row.keys()))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_fixture(tmp_path: Path, mismatch_rows: list[dict[str, object]], paper_rows: list[dict[str, object]]):
    comparison_dir = tmp_path / "comparison"
    paper_path = tmp_path / "paper" / "paper_signals.csv"
    scanner = tmp_path / "paper" / "scanner_summary.json"
    pipeline = tmp_path / "pipeline" / "pipeline_summary.json"
    repair = tmp_path / "h4" / "h4_repair_report.json"
    post = tmp_path / "h4post" / "h4_data_source_diagnostic.json"
    comparison_dir.mkdir(parents=True, exist_ok=True)
    (comparison_dir / "comparison_summary.json").write_text(
        json.dumps(
            {
                "match_rate_all_detected": 0.93,
                "match_rate_accepted_only": 0.93,
                "symbol": "XAUUSD",
                "cooldown_minutes": 120,
                "comparison_window": {
                    "comparison_start": "2026-05-20T09:00:00+00:00",
                    "comparison_end": "2026-05-20T12:00:00+00:00",
                    "backtest_signal_scan_start": "2026-05-20T08:00:00+00:00",
                    "backtest_signal_scan_end": "2026-05-20T12:05:00+00:00",
                    "earliest_paper_signal_timestamp": "2026-05-20T10:00:00+00:00",
                    "latest_paper_signal_timestamp": "2026-05-20T10:00:00+00:00",
                },
                "paper_signals_clean_for_validation": True,
            }
        ),
        encoding="utf-8",
    )
    _write_csv(comparison_dir / "mismatch_details.csv", mismatch_rows)
    _write_csv(paper_path, paper_rows)
    scanner.parent.mkdir(parents=True, exist_ok=True)
    pipeline.parent.mkdir(parents=True, exist_ok=True)
    repair.parent.mkdir(parents=True, exist_ok=True)
    post.parent.mkdir(parents=True, exist_ok=True)
    scanner.write_text(json.dumps({"new_last_processed_timestamp": "2026-05-20T12:00:00+00:00"}), encoding="utf-8")
    pipeline.write_text(
        json.dumps({"h4_quarantine_status": "fresh", "h4_stale_by_bars": 0}),
        encoding="utf-8",
    )
    repair.write_text(json.dumps({"run_finished_at": "2026-05-20T09:00:00+00:00"}), encoding="utf-8")
    post.write_text(json.dumps({}), encoding="utf-8")
    return comparison_dir, paper_path, scanner, pipeline, repair, post


def _config(tmp_path: Path, mismatch_rows: list[dict[str, object]], paper_rows: list[dict[str, object]]):
    module = _module()
    comparison_dir, paper_path, scanner, pipeline, repair, post = _write_fixture(tmp_path, mismatch_rows, paper_rows)
    return module.DiagnosticConfig(
        comparison_dir=comparison_dir,
        paper_signals_path=paper_path,
        scanner_summary_path=scanner,
        pipeline_summary_path=pipeline,
        data_dir="data",
        output_dir=tmp_path / "out",
        price_tolerance=0.01,
        timestamp_tolerance_seconds=0,
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


def test_level_mismatch_rounding_and_true_drift():
    module = _module()
    rounding = module.classify_level_mismatch(
        row={},
        paper=_paper(stop_loss="4499.00"),
        backtest=_backtest(stop_loss=4499.005),
        price_tolerance=0.01,
        repair_finished_at=None,
    )
    drift = module.classify_level_mismatch(
        row={},
        paper=_paper(stop_loss="4499.00"),
        backtest=_backtest(stop_loss=4498.50),
        price_tolerance=0.01,
        repair_finished_at=None,
    )
    assert rounding[0] == "LEVEL_ROUNDING_ONLY"
    assert drift[0] == "LEVEL_TRUE_CALCULATION_MISMATCH"


def test_pre_repair_level_context_is_detected():
    module = _module()
    result = module.classify_level_mismatch(
        row={},
        paper=_paper(generated_at="2026-05-20T08:00:00+00:00", stop_loss="4499.00"),
        backtest=_backtest(stop_loss=4498.50),
        price_tolerance=0.01,
        repair_finished_at=module._parse_ts("2026-05-20T09:00:00+00:00"),
    )
    assert result[0] == "LEVEL_PRE_REPAIR_DATA_CONTEXT_DRIFT"


def test_cooldown_previous_signal_history_mismatch():
    module = _module()
    paper_rows = [
        _paper(signal_timestamp="2026-05-20T08:00:00+00:00", direction="SHORT"),
        _paper(signal_timestamp="2026-05-20T10:00:00+00:00", direction="SHORT", cooldown_accepted="True"),
    ]
    backtest_rows = [
        _backtest(signal_timestamp="2026-05-20T09:00:00+00:00", direction="SHORT", cooldown_accepted=True),
        _backtest(signal_timestamp="2026-05-20T10:00:00+00:00", direction="SHORT", cooldown_accepted=False),
    ]
    result = module.classify_cooldown_mismatch(
        paper=paper_rows[1],
        backtest=backtest_rows[1],
        paper_rows=paper_rows,
        backtest_rows=backtest_rows,
    )
    assert result[0] == "COOLDOWN_PREVIOUS_SIGNAL_HISTORY_DIFF"


def test_cooldown_exact_boundary_classification():
    module = _module()
    paper_rows = [
        _paper(signal_timestamp="2026-05-20T08:00:00+00:00", direction="SHORT"),
        _paper(signal_timestamp="2026-05-20T10:00:00+00:00", direction="SHORT"),
    ]
    backtest_rows = [
        _backtest(signal_timestamp="2026-05-20T08:00:00+00:00", direction="SHORT", cooldown_accepted=True),
        _backtest(signal_timestamp="2026-05-20T10:00:00+00:00", direction="SHORT", cooldown_accepted=False),
    ]
    result = module.classify_cooldown_mismatch(
        paper=paper_rows[1],
        backtest=backtest_rows[1],
        paper_rows=paper_rows,
        backtest_rows=backtest_rows,
    )
    assert result[0] == "COOLDOWN_EXACT_BOUNDARY"


def test_extra_missing_near_match_and_window_edge():
    module = _module()
    near = module.classify_missing_extra(
        row={"match_status": "extra_in_backtest", "backtest_signal_timestamp": "2026-05-20T10:05:00+00:00"},
        paper_rows=[_paper(signal_timestamp="2026-05-20T10:00:00+00:00", direction="LONG")],
        backtest_rows=[_backtest(signal_timestamp="2026-05-20T10:05:00+00:00", direction="LONG")],
        comparison_window={"comparison_start": "2026-05-20T09:00:00+00:00", "comparison_end": "2026-05-20T12:00:00+00:00"},
        repair_finished_at=None,
    )
    edge = module.classify_missing_extra(
        row={"match_status": "extra_in_backtest", "backtest_signal_timestamp": "2026-05-20T09:05:00+00:00"},
        paper_rows=[],
        backtest_rows=[],
        comparison_window={"comparison_start": "2026-05-20T09:00:00+00:00", "comparison_end": "2026-05-20T12:00:00+00:00"},
        repair_finished_at=None,
    )
    assert near[0] == "NEAR_MATCH_TIMESTAMP_SHIFT"
    assert edge[0] == "WINDOW_EDGE_EXTRA_SIGNAL"


def test_run_diagnostics_writes_outputs_and_reports_h4(monkeypatch, tmp_path):
    module = _module()
    mismatch_rows = [
        {
            "comparison_scope": "all_detected",
            "match_status": "field_mismatch",
            "paper_signal_timestamp": "2026-05-20T10:00:00+00:00",
            "backtest_signal_timestamp": "2026-05-20T10:00:00+00:00",
            "direction": "LONG",
            "entry_price": "4500.00",
            "stop_loss": "4499.00",
            "take_profit": "4501.00",
            "setup_mode": "trend_following",
            "band_touched": "vwap",
            "cooldown_accepted": "True",
            "mismatch_categories": "STOP_LOSS_MISMATCH",
            "details": '{"STOP_LOSS_MISMATCH":{"paper":"4499.00","backtest":4498.50}}',
        }
    ]
    cfg = _config(tmp_path, mismatch_rows, [_paper(generated_at="2026-05-20T08:00:00+00:00")])
    monkeypatch.setattr(module, "build_backtest_rows", lambda _cfg, _window: ([], [_backtest(stop_loss=4498.50)]))
    summary = module.run_diagnostics(cfg)
    assert summary["h4_status"]["freshness"] == "fresh"
    assert summary["classification_counts"]["LEVEL_PRE_REPAIR_DATA_CONTEXT_DRIFT"] == 1
    assert (cfg.output_dir / "runtime_comparison_diagnostics_summary.json").exists()
    assert (cfg.output_dir / "mismatch_root_cause_details.csv").exists()
    assert summary["safety"]["order_send_called"] is False


def test_missing_fields_do_not_crash(monkeypatch, tmp_path):
    module = _module()
    mismatch_rows = [
        {
            "comparison_scope": "all_detected",
            "match_status": "field_mismatch",
            "paper_signal_timestamp": "2026-05-20T10:00:00+00:00",
            "backtest_signal_timestamp": "2026-05-20T10:00:00+00:00",
            "mismatch_categories": "STOP_LOSS_MISMATCH",
            "details": "",
        }
    ]
    cfg = _config(tmp_path, mismatch_rows, [{"signal_timestamp": "2026-05-20T10:00:00+00:00"}])
    monkeypatch.setattr(module, "build_backtest_rows", lambda _cfg, _window: ([], []))
    summary = module.run_diagnostics(cfg)
    assert summary["mismatches_analyzed"] == 1
