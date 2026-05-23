from __future__ import annotations

import csv
import hashlib
import importlib
import json
from pathlib import Path


def _module():
    return importlib.import_module("scripts.analyze_strategy_3_paper_accumulation_dashboard")


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
        "direction": "LONG",
        "session": "London",
        "data_context_hash": "ctx" if context else "",
        "cooldown_accepted": str(accepted),
        "cooldown_block_reason": "" if accepted else "STRATEGY_3_COOLDOWN_BLOCKED",
        "last_signal_timestamp_same_symbol_direction": "2026-05-21T01:00:00+00:00",
        "order_sent": "False",
        "telegram_sent": "False",
        "broker_called": "False",
    }


def _fixture(tmp_path: Path):
    module = _module()
    paper = tmp_path / "paper_signals.csv"
    fields = list(_paper_row("2026-05-21T02:30:00+00:00").keys())
    _write_csv(
        paper,
        [
            _paper_row("2026-05-20T02:30:00+00:00", context=False),
            _paper_row("2026-05-21T02:30:00+00:00", accepted=True),
            _paper_row("2026-05-21T03:00:00+00:00", accepted=False),
        ],
        fields,
    )
    scanner = tmp_path / "scanner_summary.json"
    scanner.write_text(json.dumps({"new_last_processed_timestamp": "2026-05-21T03:00:00+00:00"}), encoding="utf-8")
    pipeline = tmp_path / "pipeline_summary.json"
    pipeline.write_text(json.dumps({"summary_consistency_status": "consistent"}), encoding="utf-8")
    regime = tmp_path / "regime"
    regime.mkdir()
    (regime / "regime_summary.json").write_text(
        json.dumps(
            {
                "context_gate": {"context_gate_passed": True},
                "comparison_context": {
                    "prefix_compatible_rows": 2,
                    "prefix_incompatible_rows": 0,
                    "insufficient_context_rows": 0,
                    "match_rate_all_detected": 1.0,
                    "match_rate_accepted_only": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )
    _write_csv(
        regime / "accepted_vs_blocked_by_regime.csv",
        [
            {
                "regime_dimension": "direction",
                "regime_bucket": "LONG",
                "total_rows": 2,
                "accepted_rows": 1,
                "blocked_rows": 1,
                "accepted_rate": 0.5,
            }
        ],
        ["regime_dimension", "regime_bucket", "total_rows", "accepted_rows", "blocked_rows", "accepted_rate"],
    )
    _write_csv(
        regime / "blocked_reason_summary.csv",
        [{"block_reason": "STRATEGY_3_COOLDOWN_BLOCKED", "blocked_rows": 1, "pct_blocked_rows": 1.0}],
        ["block_reason", "blocked_rows", "pct_blocked_rows"],
    )
    data = tmp_path / "data" / "XAUUSD" / "M15.csv"
    data.parent.mkdir(parents=True)
    data.write_text("time,open,high,low,close,tick_volume,spread\n2026-05-21T02:30:00+00:00,1,2,0,1,10,4\n", encoding="utf-8")
    cfg = module.DashboardConfig(
        paper_signals_path=paper,
        scanner_summary_path=scanner,
        pipeline_summary_path=pipeline,
        regime_dir=regime,
        output_dir=tmp_path / "out",
        docs_path=tmp_path / "docs" / "dashboard.md",
        min_bucket_total=30,
        watchlist_accepted_threshold=100,
        pre_registered_accepted_threshold=300,
        dry_run=True,
    )
    return module, cfg, data


def test_import_safe_and_cli_defaults():
    module = _module()
    args = module.parse_args([])
    assert args.watchlist_accepted_threshold == 100
    assert hasattr(module, "run_dashboard")


def test_dashboard_generation_and_legacy_exclusion(tmp_path):
    module, cfg, _data = _fixture(tmp_path)
    summary = module.run_dashboard(cfg)

    assert summary["paper_rows"]["total_paper_rows"] == 3
    assert summary["paper_rows"]["legacy_without_context_rows"] == 1
    assert summary["paper_rows"]["clean_context_rows"] == 2
    assert (cfg.output_dir / "paper_accumulation_summary.json").exists()
    assert (cfg.output_dir / "accepted_sample_by_regime.csv").exists()


def test_cooldown_is_summarized_not_changed(tmp_path):
    module, cfg, _data = _fixture(tmp_path)
    summary = module.run_dashboard(cfg)
    assert summary["cooldown"]["cooldown_blocked_count"] == 1
    assert summary["cooldown"]["cooldown_policy_changed"] is False
    assert "NO_COOLDOWN_CHANGE_RECOMMENDATION" in summary["verdict_flags"]


def test_metadata_schema_is_documented_as_non_decision(tmp_path):
    module, cfg, _data = _fixture(tmp_path)
    summary = module.run_dashboard(cfg)
    docs = cfg.docs_path.read_text(encoding="utf-8")
    assert "metadata only" in docs.lower()
    assert "must not be used to accept, block, filter, or modify signals" in docs
    assert summary["metadata_fields_are_decision_fields"] is False
    assert "strategy_3_regime_schema_version" in summary["metadata_schema_fields"]


def test_small_n_marked_insufficient_and_no_deployment_recommendation(tmp_path):
    module, cfg, _data = _fixture(tmp_path)
    summary = module.run_dashboard(cfg)
    assert summary["sample_size"]["sample_size_status"] == "INSUFFICIENT_N"
    assert summary["deployment_recommendation_emitted"] is False
    assert summary["parameter_or_filter_recommendation_emitted"] is False
    with (cfg.output_dir / "regime_sample_size_status.csv").open(newline="", encoding="utf-8") as f:
        row = next(csv.DictReader(f))
    assert row["sample_size_status"] == "INSUFFICIENT_N"


def test_dashboard_does_not_mutate_data_files(tmp_path):
    module, cfg, data = _fixture(tmp_path)
    before = hashlib.sha256(data.read_bytes()).hexdigest()
    module.run_dashboard(cfg)
    after = hashlib.sha256(data.read_bytes()).hexdigest()
    assert before == after
    assert module.SAFETY["strategy_2_touched"] is False
    assert module.SAFETY["adelin_touched"] is False
