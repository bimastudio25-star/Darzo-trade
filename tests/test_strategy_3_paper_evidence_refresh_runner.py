from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path


def _module():
    return importlib.import_module("scripts.run_strategy_3_paper_evidence_refresh")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _dashboard_summary() -> dict[str, object]:
    return {
        "paper_rows": {
            "total_paper_rows": 135,
            "legacy_without_context_rows": 64,
            "clean_context_rows": 71,
            "clean_accepted_rows": 26,
            "clean_blocked_rows": 45,
            "clean_acceptance_rate": 0.3662,
        },
        "context": {
            "context_gate_passed": True,
            "prefix_compatible_rows": 71,
            "prefix_incompatible_rows": 0,
            "paper_signals_clean_for_validation": True,
            "pipeline_summary_consistency_status": "consistent",
        },
        "cooldown": {
            "cooldown_blocked_count": 45,
            "cooldown_accepted_count": 26,
            "cooldown_policy_changed": False,
            "block_reason_distribution": [
                {
                    "block_reason": "STRATEGY_3_COOLDOWN_BLOCKED",
                    "blocked_rows": 45,
                    "pct_blocked_rows": 1.0,
                    "decision_policy_changed": False,
                }
            ],
        },
        "sample_size": {"sample_size_status": "INSUFFICIENT_N", "accepted_rows": 26},
        "accumulation_projection": {
            "first_clean_signal_timestamp": "2026-05-21T02:30:00+00:00",
            "latest_clean_signal_timestamp": "2026-05-22T22:30:00+00:00",
            "days_since_first_clean_signal": 1.8333,
            "clean_rows_per_day": 38.7273,
            "accepted_rows_per_day": 14.1818,
            "projected_days_to_exploratory_n": 5.22,
            "projected_days_to_pre_registered_diagnostic_n": 12.27,
        },
        "risk_distance": {
            "pip_convention": "PROJECT_PIP_CONVENTION: 1 USD = 10 pips",
            "summary_rows": [
                {
                    "group": "all_clean_rows",
                    "usd_median": 0.96,
                    "usd_p90": 3.46,
                    "usd_max": 6.27,
                    "pips_median": 9.6,
                    "pips_p90": 34.6,
                    "pips_max": 62.7,
                },
                {
                    "group": "accepted_rows",
                    "usd_median": 1.35,
                    "usd_p90": 4.705,
                    "usd_max": 6.27,
                    "pips_median": 13.5,
                    "pips_p90": 47.05,
                    "pips_max": 62.7,
                },
            ],
        },
    }


def _comparison_summary() -> dict[str, object]:
    return {
        "total_paper_rows": 135,
        "legacy_without_context_rows": 64,
        "context_tagged_rows": 71,
        "context_tagged_accepted": 26,
        "context_tagged_blocked": 45,
        "prefix_compatible_rows": 71,
        "prefix_incompatible_rows": 0,
        "insufficient_context_rows": 0,
        "paper_detected_count": 71,
        "paper_accepted_count": 26,
        "paper_blocked_count": 45,
        "backtest_detected_count": 71,
        "backtest_accepted_count": 26,
        "backtest_blocked_count": 45,
        "all_detected": {"match_rate": 1.0},
        "accepted_only": {"match_rate": 1.0},
        "verdict_flags": [
            "PAPER_BACKTEST_RUNTIME_CONSISTENCY_OK",
            "CLEAN_CONTEXT_ACCEPTED_MATCH_OK",
            "STRATEGY_3_REMAINS_PAPER_ONLY",
        ],
    }


def _regime_summary() -> dict[str, object]:
    return {
        "context_gate": {"context_gate_passed": True},
        "comparison_context": {
            "prefix_compatible_rows": 71,
            "prefix_incompatible_rows": 0,
            "insufficient_context_rows": 0,
            "match_rate_all_detected": 1.0,
            "match_rate_accepted_only": 1.0,
        },
    }


def _fixture(tmp_path: Path):
    module = _module()
    dashboard_dir = tmp_path / "dashboard"
    comparison_dir = tmp_path / "comparison"
    regime_dir = tmp_path / "regime"
    data_file = tmp_path / "data" / "XAUUSD" / "M15.csv"
    _write_json(dashboard_dir / "paper_accumulation_summary.json", _dashboard_summary())
    _write_json(comparison_dir / "segmented_comparison_summary.json", _comparison_summary())
    _write_json(regime_dir / "regime_summary.json", _regime_summary())
    data_file.parent.mkdir(parents=True)
    data_file.write_text("time,open,high,low,close\n2026-05-21T00:00:00+00:00,1,2,0,1\n", encoding="utf-8")
    cfg = module.EvidenceRefreshConfig(
        paper_signals_path=tmp_path / "paper_signals.csv",
        scanner_summary_path=tmp_path / "scanner_summary.json",
        pipeline_summary_path=tmp_path / "pipeline_summary.json",
        comparison_dir=comparison_dir,
        regime_dir=regime_dir,
        dashboard_dir=dashboard_dir,
        output_dir=tmp_path / "refresh",
        docs_path=tmp_path / "docs" / "paper_evidence_refresh.md",
        dashboard_docs_path=tmp_path / "docs" / "dashboard.md",
        data_dir=tmp_path / "data",
        refresh_dashboard=False,
        refresh_regime_diagnostics=False,
        target_accepted_n_exploratory=100,
        target_accepted_n_pre_registered_diagnostic=200,
        dry_run=True,
    )
    return module, cfg, data_file


def test_import_safe_and_cli_defaults():
    module = _module()
    args = module.parse_args([])
    assert args.target_accepted_n_exploratory == 100
    assert args.target_accepted_n_pre_registered_diagnostic == 200
    assert args.skip_dashboard_refresh is False


def test_runner_creates_expected_output_files(tmp_path):
    module, cfg, _data_file = _fixture(tmp_path)
    summary = module.run_refresh(cfg)

    assert summary["paper_rows"]["clean_context_rows"] == 71
    assert (cfg.output_dir / "paper_evidence_refresh_summary.json").exists()
    assert (cfg.output_dir / "gate_status.json").exists()
    assert (cfg.output_dir / "paper_evidence_refresh.md").exists()
    assert (cfg.output_dir / "latest_dashboard_pointer.json").exists()
    assert cfg.docs_path.exists()


def test_gate_status_blocks_live_deployment_and_cooldown_changes(tmp_path):
    module, cfg, _data_file = _fixture(tmp_path)
    summary = module.run_refresh(cfg)
    gates = summary["gate_status"]

    assert gates["context_gate"] == "PASSED"
    assert gates["sample_gate"] == "INSUFFICIENT_N"
    assert gates["pre_registered_diagnostic_gate"] == "BLOCKED"
    assert gates["cooldown_change_gate"] == "BLOCKED"
    assert gates["live_gate"] == "BLOCKED"
    assert gates["deployment_gate"] == "BLOCKED"
    assert summary["live_readiness"] == "BLOCKED"
    assert summary["allowed_next_action"] == "PAPER_ACCUMULATION_ONLY"


def test_existing_dashboard_metrics_are_read_correctly(tmp_path):
    module, cfg, _data_file = _fixture(tmp_path)
    summary = module.run_refresh(cfg)

    assert summary["paper_rows"]["total_paper_rows"] == 135
    assert summary["paper_rows"]["legacy_without_context_rows"] == 64
    assert summary["paper_rows"]["clean_accepted_rows"] == 26
    assert summary["cooldown"]["cooldown_blocked_count"] == 45
    assert summary["accumulation_projection"]["projected_days_to_100_accepted"] == 5.22
    assert summary["accumulation_projection"]["projected_days_to_200_accepted"] == 12.27


def test_risk_distance_stats_are_propagated(tmp_path):
    module, cfg, _data_file = _fixture(tmp_path)
    summary = module.run_refresh(cfg)

    assert summary["risk_distance"]["accepted_median_usd"] == 1.35
    assert summary["risk_distance"]["accepted_p90_usd"] == 4.705
    assert summary["risk_distance"]["accepted_max_usd"] == 6.27
    assert summary["risk_distance"]["accepted_median_pips"] == 13.5
    assert summary["risk_distance"]["accepted_p90_pips"] == 47.05
    assert summary["risk_distance"]["accepted_max_pips"] == 62.7
    assert summary["risk_distance"]["descriptive_only"] is True


def test_missing_optional_diagnostics_warn_not_false_pass(tmp_path):
    module, cfg, _data_file = _fixture(tmp_path)
    (cfg.comparison_dir / "segmented_comparison_summary.json").unlink()

    summary = module.run_refresh(cfg)

    assert summary["gate_status"]["context_gate"] == "BLOCKED"
    assert "REFRESH_WARNINGS_PRESENT" in summary["verdict_flags"]
    assert any("SEGMENTED_COMPARISON_SUMMARY_MISSING" in warning for warning in summary["warnings"])
    assert "CONTEXT_GATE_PASSED" not in summary["verdict_flags"]


def test_no_strategy_runtime_or_data_mutation(tmp_path):
    module, cfg, data_file = _fixture(tmp_path)
    before = hashlib.sha256(data_file.read_bytes()).hexdigest()
    summary = module.run_refresh(cfg)
    after = hashlib.sha256(data_file.read_bytes()).hexdigest()

    assert before == after
    assert summary["safety"]["strategy_3_runtime_logic_changed"] is False
    assert summary["safety"]["vwap_sigma_cooldown_logic_changed"] is False
    assert summary["safety"]["cooldown_policy_changed"] is False
    assert summary["safety"]["strategy_2_touched"] is False
    assert summary["safety"]["adelin_touched"] is False
    assert summary["safety"]["data_xauusd_mutated"] is False


def test_markdown_contains_paper_only_warnings(tmp_path):
    module, cfg, _data_file = _fixture(tmp_path)
    module.run_refresh(cfg)
    text = cfg.docs_path.read_text(encoding="utf-8")

    assert "not a trading system" in text
    assert "does not emit trade instructions" in text
    assert "no Strategy 3 VWAP/sigma/cooldown/entry/TP/SL/filter changes" in text
    assert "Continue Strategy 3 paper accumulation only" in text
