from __future__ import annotations

import csv
import hashlib
import importlib
import json
from pathlib import Path


def _module():
    return importlib.import_module("scripts.analyze_strategy_3_vwap_trend_regime_diagnostics")


def _write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _paper_row(timestamp: str, *, context: bool = True, accepted: bool = True) -> dict[str, object]:
    return {
        "signal_timestamp": timestamp,
        "symbol": "XAUUSD",
        "strategy": "strategy_3_vwap_1r",
        "direction": "LONG",
        "entry_price": "4500.00",
        "stop_loss": "4498.00",
        "take_profit": "4502.00",
        "setup_mode": "reversal",
        "band_touched": "sigma_1_lower",
        "reason_codes": "[\"liquidity_sweep\"]",
        "vwap_value": "4500.00",
        "sigma_1_upper": "4502.00",
        "sigma_1_lower": "4498.00",
        "sigma_2_upper": "4504.00",
        "sigma_2_lower": "4496.00",
        "distance_to_vwap": "1.0",
        "distance_to_band": "1.0",
        "current_price": "4499.00",
        "session": "London",
        "data_context_hash": "ctx" if context else "",
        "cooldown_accepted": str(accepted),
        "cooldown_block_reason": "" if accepted else "STRATEGY_3_COOLDOWN_BLOCKED",
        "cooldown_status": "accepted" if accepted else "blocked",
        "order_sent": "False",
        "telegram_sent": "False",
        "broker_called": "False",
    }


def _write_market(path: Path, timeframe: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        "time,open,high,low,close,tick_volume,spread",
        "2026-05-21T01:00:00+00:00,4498,4500,4497,4499,10,4",
        "2026-05-21T01:15:00+00:00,4499,4501,4498,4500,10,4",
        "2026-05-21T01:30:00+00:00,4500,4502,4499,4501,10,4",
        "2026-05-21T02:30:00+00:00,4501,4503,4499,4502,10,4",
        "2026-05-21T03:30:00+00:00,9999,9999,9999,9999,10,4",
    ]
    if timeframe == "H4":
        rows = [
            "time,open,high,low,close,tick_volume,spread",
            "2026-05-20T12:00:00+00:00,4480,4490,4470,4485,10,4",
            "2026-05-20T16:00:00+00:00,4485,4495,4480,4490,10,4",
            "2026-05-21T00:00:00+00:00,4490,4500,4485,4495,10,4",
            "2026-05-21T04:00:00+00:00,9999,9999,9999,9999,10,4",
        ]
    if timeframe == "H1":
        rows = [
            "time,open,high,low,close,tick_volume,spread",
            "2026-05-20T23:00:00+00:00,4480,4490,4470,4485,10,4",
            "2026-05-21T00:00:00+00:00,4485,4495,4480,4490,10,4",
            "2026-05-21T01:00:00+00:00,4490,4500,4485,4495,10,4",
            "2026-05-21T03:00:00+00:00,9999,9999,9999,9999,10,4",
        ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path, *, prefix_bad: int = 0) -> tuple[object, object]:
    module = _module()
    comparison_dir = tmp_path / "comparison"
    comparison_dir.mkdir()
    summary = {
        "total_paper_rows": 2,
        "legacy_without_context_rows": 1,
        "context_tagged_rows": 1,
        "prefix_compatible_rows": 1 if prefix_bad == 0 else 0,
        "prefix_incompatible_rows": prefix_bad,
        "insufficient_context_rows": 0,
        "match_rate_all_detected": 1.0,
        "match_rate_accepted_only": 1.0,
        "verdict_flags": ["CLEAN_CONTEXT_ACCEPTED_MATCH_OK", "PAPER_BACKTEST_RUNTIME_CONSISTENCY_OK"],
        "comparison_window": {
            "comparison_start": "2026-05-21T02:30:00+00:00",
            "comparison_end": "2026-05-21T02:30:00+00:00",
        },
    }
    (comparison_dir / "segmented_comparison_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (comparison_dir / "segmented_data_context_report.json").write_text(
        json.dumps({"details": [{"signal_timestamp": "2026-05-21T02:30:00+00:00", "data_context_hash": "ctx", "prefix_compatible": prefix_bad == 0, "prefix_insufficient": False}]}),
        encoding="utf-8",
    )
    paper = tmp_path / "paper_signals.csv"
    fields = list(_paper_row("2026-05-21T02:30:00+00:00").keys())
    _write_csv(paper, [_paper_row("2026-05-20T02:30:00+00:00", context=False), _paper_row("2026-05-21T02:30:00+00:00", accepted=False)], fields)
    data_dir = tmp_path / "data"
    for tf in ("M15", "H1", "H4"):
        _write_market(data_dir / "XAUUSD" / f"{tf}.csv", tf)
    cfg = module.DiagnosticsConfig(
        comparison_dir=comparison_dir,
        paper_signals_path=paper,
        data_dir=data_dir,
        output_dir=tmp_path / "out",
        docs_path=tmp_path / "docs" / "report.md",
        symbol="XAUUSD",
        min_bucket_size=10,
        dry_run=True,
    )
    return module, cfg


def test_import_safe_and_cli_does_not_execute():
    module = _module()
    args = module.parse_args([])
    assert args.symbol == "XAUUSD"
    assert hasattr(module, "run_diagnostics")


def test_legacy_rows_are_excluded_and_prefix_required(tmp_path):
    module, cfg = _fixture(tmp_path)
    summary = module.run_diagnostics(cfg)

    assert summary["legacy_rows_excluded"] == 1
    assert summary["diagnostic_rows"] == 1
    assert summary["context_gate"]["context_gate_passed"] is True
    assert summary["blocked_rows"] == 1


def test_prefix_mismatch_blocks_clean_diagnostics(tmp_path):
    module, cfg = _fixture(tmp_path, prefix_bad=1)
    summary = module.run_diagnostics(cfg)

    assert summary["context_gate"]["context_gate_passed"] is False
    assert summary["diagnostic_rows"] == 0
    assert "CONTEXT_CONSISTENCY_GATE_NOT_PASSED" in summary["verdict_flags"]


def test_regime_features_use_pre_decision_data_only(tmp_path):
    module, cfg = _fixture(tmp_path)
    module.run_diagnostics(cfg)
    with (cfg.output_dir / "regime_diagnostics_per_signal.csv").open(newline="", encoding="utf-8") as f:
        row = next(csv.DictReader(f))

    assert row["m15_latest_timestamp_used"] == "2026-05-21T02:30:00+00:00"
    assert row["h1_latest_timestamp_used"] == "2026-05-21T01:00:00+00:00"
    assert row["h4_latest_timestamp_used"] == "2026-05-21T00:00:00+00:00"
    assert "9999" not in row["h1_bias_value"]


def test_small_n_buckets_marked_insufficient_and_no_deployment_instruction(tmp_path):
    module, cfg = _fixture(tmp_path)
    summary = module.run_diagnostics(cfg)
    assert summary["small_n"]["small_n_buckets"] > 0
    assert summary["deployment_instruction_emitted"] is False
    assert "deploy" not in summary["recommendation"].lower()


def test_diagnostics_do_not_mutate_data_files(tmp_path):
    module, cfg = _fixture(tmp_path)
    data_file = cfg.data_dir / "XAUUSD" / "M15.csv"
    before = hashlib.sha256(data_file.read_bytes()).hexdigest()
    module.run_diagnostics(cfg)
    after = hashlib.sha256(data_file.read_bytes()).hexdigest()
    assert before == after
