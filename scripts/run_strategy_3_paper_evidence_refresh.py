from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STRATEGY_NAME = "strategy_3_vwap_1r"
DEFAULT_COMPARISON_DIR = Path("backtests/reports/strategy_3_clean_context_shadow_vs_backtest_comparison_segmented")
DEFAULT_REGIME_DIR = Path("backtests/reports/strategy_3_vwap_trend_regime_diagnostics")
DEFAULT_DASHBOARD_DIR = Path("backtests/reports/strategy_3_paper_accumulation_dashboard")
DEFAULT_OUTPUT_DIR = Path("backtests/reports/strategy_3_paper_evidence_refresh")
DEFAULT_DOCS_PATH = Path("docs/research/strategy_3_paper_evidence_refresh_runner.md")
DEFAULT_DASHBOARD_DOCS_PATH = Path("docs/research/strategy_3_paper_accumulation_evidence_dashboard.md")

SAFETY = {
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "order_execution_enabled": False,
    "broker_execution_enabled": False,
    "order_send_called": False,
    "strategy_3_runtime_logic_changed": False,
    "vwap_sigma_cooldown_logic_changed": False,
    "strategy_2_touched": False,
    "adelin_touched": False,
    "data_xauusd_mutated": False,
    "cooldown_policy_changed": False,
    "filters_changed": False,
    "deployment_recommendation_emitted": False,
}


@dataclass(frozen=True)
class EvidenceRefreshConfig:
    paper_signals_path: Path
    scanner_summary_path: Path
    pipeline_summary_path: Path
    comparison_dir: Path
    regime_dir: Path
    dashboard_dir: Path
    output_dir: Path
    docs_path: Path
    dashboard_docs_path: Path
    data_dir: Path
    refresh_dashboard: bool
    refresh_regime_diagnostics: bool
    target_accepted_n_exploratory: int
    target_accepted_n_pre_registered_diagnostic: int
    dry_run: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strategy 3 paper evidence refresh runner")
    parser.add_argument("--paper-signals-path", default="backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv")
    parser.add_argument("--scanner-summary-path", default="backtests/reports/strategy_3_paper_shadow_scanner/scanner_summary.json")
    parser.add_argument("--pipeline-summary-path", default="backtests/reports/strategy_3_local_paper_pipeline/pipeline_summary.json")
    parser.add_argument("--comparison-dir", default=str(DEFAULT_COMPARISON_DIR))
    parser.add_argument("--regime-dir", default=str(DEFAULT_REGIME_DIR))
    parser.add_argument("--dashboard-dir", default=str(DEFAULT_DASHBOARD_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--docs-path", default=str(DEFAULT_DOCS_PATH))
    parser.add_argument("--dashboard-docs-path", default=str(DEFAULT_DASHBOARD_DOCS_PATH))
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--skip-dashboard-refresh", action="store_true", help="Read the existing dashboard summary instead of refreshing it.")
    parser.add_argument("--refresh-regime-diagnostics", action="store_true", help="Refresh VWAP/trend/regime diagnostics before building the evidence summary.")
    parser.add_argument("--target-accepted-n-exploratory", type=int, default=100)
    parser.add_argument("--target-accepted-n-pre-registered-diagnostic", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _risk_row(summary: dict[str, Any], group: str) -> dict[str, Any]:
    for row in summary.get("risk_distance", {}).get("summary_rows", []):
        if row.get("group") == group:
            return dict(row)
    return {}


def maybe_refresh_dashboard(cfg: EvidenceRefreshConfig, warnings: list[str]) -> dict[str, Any]:
    summary_path = cfg.dashboard_dir / "paper_accumulation_summary.json"
    if not cfg.refresh_dashboard:
        summary = _read_json(summary_path)
        if not summary:
            warnings.append(f"DASHBOARD_SUMMARY_MISSING: {summary_path}")
        return summary

    try:
        from scripts.analyze_strategy_3_paper_accumulation_dashboard import DashboardConfig, run_dashboard

        dashboard_cfg = DashboardConfig(
            paper_signals_path=cfg.paper_signals_path,
            scanner_summary_path=cfg.scanner_summary_path,
            pipeline_summary_path=cfg.pipeline_summary_path,
            regime_dir=cfg.regime_dir,
            output_dir=cfg.dashboard_dir,
            docs_path=cfg.dashboard_docs_path,
            min_bucket_total=30,
            watchlist_accepted_threshold=cfg.target_accepted_n_exploratory,
            pre_registered_accepted_threshold=cfg.target_accepted_n_pre_registered_diagnostic,
            dry_run=cfg.dry_run,
        )
        return run_dashboard(dashboard_cfg)
    except Exception as exc:  # pragma: no cover - defensive reporting path
        warnings.append(f"DASHBOARD_REFRESH_FAILED: {exc}")
        return _read_json(summary_path)


def maybe_refresh_regime_diagnostics(cfg: EvidenceRefreshConfig, warnings: list[str]) -> dict[str, Any]:
    summary_path = cfg.regime_dir / "regime_summary.json"
    if not cfg.refresh_regime_diagnostics:
        summary = _read_json(summary_path)
        if not summary:
            warnings.append(f"REGIME_DIAGNOSTICS_MISSING: {summary_path}")
        return summary

    try:
        from scripts.analyze_strategy_3_vwap_trend_regime_diagnostics import DiagnosticsConfig, run_diagnostics

        diagnostics_cfg = DiagnosticsConfig(
            comparison_dir=cfg.comparison_dir,
            paper_signals_path=cfg.paper_signals_path,
            data_dir=cfg.data_dir,
            output_dir=cfg.regime_dir,
            docs_path=Path("docs/research/strategy_3_vwap_trend_regime_diagnostics.md"),
            symbol="XAUUSD",
            min_bucket_size=10,
            dry_run=cfg.dry_run,
        )
        return run_diagnostics(diagnostics_cfg)
    except Exception as exc:  # pragma: no cover - defensive reporting path
        warnings.append(f"REGIME_DIAGNOSTICS_REFRESH_FAILED: {exc}")
        return _read_json(summary_path)


def load_comparison_summary(cfg: EvidenceRefreshConfig, warnings: list[str]) -> dict[str, Any]:
    path = cfg.comparison_dir / "segmented_comparison_summary.json"
    summary = _read_json(path)
    if not summary:
        warnings.append(f"SEGMENTED_COMPARISON_SUMMARY_MISSING: {path}")
    return summary


def build_gate_status(
    *,
    dashboard_summary: dict[str, Any],
    comparison_summary: dict[str, Any],
    regime_summary: dict[str, Any],
    warnings: list[str],
    target_accepted_n_exploratory: int,
    target_accepted_n_pre_registered_diagnostic: int,
) -> dict[str, Any]:
    paper_rows = dashboard_summary.get("paper_rows", {})
    comparison_available = bool(comparison_summary)
    clean_rows = _int(comparison_summary.get("context_tagged_rows"), _int(paper_rows.get("clean_context_rows")))
    prefix_incompatible = _int(comparison_summary.get("prefix_incompatible_rows"), _int(dashboard_summary.get("context", {}).get("prefix_incompatible_rows")))
    insufficient = _int(comparison_summary.get("insufficient_context_rows"), 0)
    prefix_compatible = _int(comparison_summary.get("prefix_compatible_rows"), _int(dashboard_summary.get("context", {}).get("prefix_compatible_rows")))
    accepted_rows = _int(paper_rows.get("clean_accepted_rows"), _int(comparison_summary.get("paper_accepted_count")))

    context_gate_passed = comparison_available and clean_rows > 0 and prefix_incompatible == 0 and insufficient == 0
    sample_gate = "PASSED_EXPLORATORY_N" if accepted_rows >= target_accepted_n_exploratory else "INSUFFICIENT_N"
    pre_registered_gate = "PASSED" if accepted_rows >= target_accepted_n_pre_registered_diagnostic else "BLOCKED"

    if not comparison_available:
        context_reason = "missing segmented comparison summary"
    elif clean_rows <= 0:
        context_reason = "no clean context rows"
    elif prefix_incompatible > 0:
        context_reason = "prefix-incompatible rows present"
    elif insufficient > 0:
        context_reason = "insufficient context rows present"
    else:
        context_reason = "prefix-compatible clean context rows available"

    if context_gate_passed and accepted_rows >= target_accepted_n_pre_registered_diagnostic:
        allowed_next_action = "PRE_REGISTERED_DIAGNOSTIC_REVIEW_ONLY"
    elif context_gate_passed and accepted_rows >= target_accepted_n_exploratory:
        allowed_next_action = "EXPLORATORY_WATCHLIST_REVIEW_ONLY"
    else:
        allowed_next_action = "PAPER_ACCUMULATION_ONLY"

    return {
        "context_gate": "PASSED" if context_gate_passed else "BLOCKED",
        "context_gate_reason": context_reason,
        "prefix_compatible_rows": prefix_compatible,
        "prefix_incompatible_rows": prefix_incompatible,
        "insufficient_context_rows": insufficient,
        "clean_context_rows": clean_rows,
        "sample_gate": sample_gate,
        "sample_gate_reason": f"{accepted_rows} accepted clean rows; exploratory target is {target_accepted_n_exploratory}",
        "pre_registered_diagnostic_gate": pre_registered_gate,
        "pre_registered_diagnostic_gate_reason": f"{accepted_rows} accepted clean rows; pre-registered diagnostic target is {target_accepted_n_pre_registered_diagnostic}",
        "cooldown_change_gate": "BLOCKED",
        "cooldown_change_gate_reason": "Cooldown is summarized only; this runner cannot recommend or apply cooldown changes.",
        "live_gate": "BLOCKED",
        "deployment_gate": "BLOCKED",
        "live_readiness": "BLOCKED",
        "deployment_readiness": "BLOCKED",
        "allowed_next_action": allowed_next_action,
        "warnings_present": bool(warnings),
        "warnings": list(warnings),
    }


def build_summary(
    *,
    cfg: EvidenceRefreshConfig,
    dashboard_summary: dict[str, Any],
    comparison_summary: dict[str, Any],
    regime_summary: dict[str, Any],
    gate_status: dict[str, Any],
    warnings: list[str],
    runtime_seconds: float,
) -> dict[str, Any]:
    paper_rows = dashboard_summary.get("paper_rows", {})
    cooldown = dashboard_summary.get("cooldown", {})
    projection = dashboard_summary.get("accumulation_projection", {})
    sample_size = dashboard_summary.get("sample_size", {})
    accepted_risk = _risk_row(dashboard_summary, "accepted_rows")
    all_clean_risk = _risk_row(dashboard_summary, "all_clean_rows")

    accepted_rows = _int(paper_rows.get("clean_accepted_rows"))
    blocked_rows = _int(paper_rows.get("clean_blocked_rows"))
    clean_rows = _int(paper_rows.get("clean_context_rows"))
    acceptance_rate = _float(paper_rows.get("clean_acceptance_rate"))
    if acceptance_rate is None and clean_rows:
        acceptance_rate = round(accepted_rows / clean_rows, 4)

    comparison_flags = comparison_summary.get("verdict_flags", [])
    paper_backtest_match_status = "MATCHED" if "PAPER_BACKTEST_RUNTIME_CONSISTENCY_OK" in comparison_flags else "UNKNOWN_OR_NOT_PASSED"

    verdict_flags = [
        "PAPER_EVIDENCE_REFRESH_CREATED",
        "CONTEXT_GATE_PASSED" if gate_status["context_gate"] == "PASSED" else "CONTEXT_GATE_BLOCKED",
        "SAMPLE_GATE_INSUFFICIENT_N" if gate_status["sample_gate"] == "INSUFFICIENT_N" else "SAMPLE_GATE_EXPLORATORY_N_REACHED",
        "PRE_REGISTERED_DIAGNOSTIC_GATE_BLOCKED" if gate_status["pre_registered_diagnostic_gate"] == "BLOCKED" else "PRE_REGISTERED_DIAGNOSTIC_GATE_PASSED",
        "COOLDOWN_CHANGE_GATE_BLOCKED",
        "LIVE_GATE_BLOCKED",
        "DEPLOYMENT_GATE_BLOCKED",
        "DIAGNOSTICS_ONLY",
        "NO_PARAMETER_RECOMMENDATION",
        "NO_COOLDOWN_CHANGE_RECOMMENDATION",
        "NO_LIVE_DEPLOYMENT_DECISION",
        "STRATEGY_3_REMAINS_PAPER_ONLY",
    ]
    if warnings:
        verdict_flags.append("REFRESH_WARNINGS_PRESENT")

    return {
        "run_finished_at": _utc_now(),
        "runtime_seconds": round(runtime_seconds, 4),
        "dry_run": cfg.dry_run,
        "strategy": STRATEGY_NAME,
        "inputs": {
            "paper_signals_path": str(cfg.paper_signals_path),
            "scanner_summary_path": str(cfg.scanner_summary_path),
            "pipeline_summary_path": str(cfg.pipeline_summary_path),
            "comparison_dir": str(cfg.comparison_dir),
            "regime_dir": str(cfg.regime_dir),
            "dashboard_dir": str(cfg.dashboard_dir),
        },
        "refresh_steps": {
            "dashboard_refresh_requested": cfg.refresh_dashboard,
            "regime_diagnostics_refresh_requested": cfg.refresh_regime_diagnostics,
            "segmented_comparison_validated": bool(comparison_summary),
            "dashboard_summary_available": bool(dashboard_summary),
            "regime_summary_available": bool(regime_summary),
        },
        "paper_rows": {
            "total_paper_rows": _int(paper_rows.get("total_paper_rows")),
            "legacy_without_context_rows": _int(paper_rows.get("legacy_without_context_rows")),
            "clean_context_rows": clean_rows,
            "clean_accepted_rows": accepted_rows,
            "clean_blocked_rows": blocked_rows,
            "clean_acceptance_rate": acceptance_rate,
        },
        "context": {
            "context_gate_status": gate_status["context_gate"],
            "prefix_compatible_rows": gate_status["prefix_compatible_rows"],
            "prefix_incompatible_rows": gate_status["prefix_incompatible_rows"],
            "insufficient_context_rows": gate_status["insufficient_context_rows"],
            "paper_backtest_match_status": paper_backtest_match_status,
            "all_detected_match_rate": comparison_summary.get("all_detected", {}).get("match_rate"),
            "accepted_only_match_rate": comparison_summary.get("accepted_only", {}).get("match_rate"),
            "regime_context_gate_passed": regime_summary.get("context_gate", {}).get("context_gate_passed"),
        },
        "cooldown": {
            "cooldown_blocked_count": _int(cooldown.get("cooldown_blocked_count")),
            "cooldown_accepted_count": _int(cooldown.get("cooldown_accepted_count")),
            "cooldown_policy_changed": bool(cooldown.get("cooldown_policy_changed", False)),
            "block_reason_distribution": cooldown.get("block_reason_distribution", []),
        },
        "sample_size": {
            "sample_status": sample_size.get("sample_size_status") or gate_status["sample_gate"],
            "accepted_rows": accepted_rows,
            "target_accepted_n_exploratory": cfg.target_accepted_n_exploratory,
            "target_accepted_n_pre_registered_diagnostic": cfg.target_accepted_n_pre_registered_diagnostic,
        },
        "accumulation_projection": {
            "days_since_first_clean_signal": projection.get("days_since_first_clean_signal"),
            "first_clean_signal_timestamp": projection.get("first_clean_signal_timestamp"),
            "latest_clean_signal_timestamp": projection.get("latest_clean_signal_timestamp"),
            "clean_rows_per_day": projection.get("clean_rows_per_day"),
            "accepted_rows_per_day": projection.get("accepted_rows_per_day"),
            "projected_days_to_100_accepted": projection.get("projected_days_to_exploratory_n"),
            "projected_days_to_200_accepted": projection.get("projected_days_to_pre_registered_diagnostic_n"),
        },
        "risk_distance": {
            "pip_convention": dashboard_summary.get("risk_distance", {}).get("pip_convention", "PROJECT_PIP_CONVENTION: 1 USD = 10 pips"),
            "accepted_median_usd": accepted_risk.get("usd_median"),
            "accepted_p90_usd": accepted_risk.get("usd_p90"),
            "accepted_max_usd": accepted_risk.get("usd_max"),
            "accepted_median_pips": accepted_risk.get("pips_median"),
            "accepted_p90_pips": accepted_risk.get("pips_p90"),
            "accepted_max_pips": accepted_risk.get("pips_max"),
            "all_clean_median_usd": all_clean_risk.get("usd_median"),
            "all_clean_p90_usd": all_clean_risk.get("usd_p90"),
            "all_clean_max_usd": all_clean_risk.get("usd_max"),
            "descriptive_only": True,
        },
        "gate_status": gate_status,
        "live_readiness": gate_status["live_readiness"],
        "allowed_next_action": gate_status["allowed_next_action"],
        "warnings": warnings,
        "verdict_flags": verdict_flags,
        "safety": dict(SAFETY),
    }


def write_markdown_report(output_dir: Path, docs_path: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    paper = summary["paper_rows"]
    context = summary["context"]
    projection = summary["accumulation_projection"]
    risk = summary["risk_distance"]
    gates = summary["gate_status"]
    lines = [
        "# Strategy 3 Paper Evidence Refresh Runner",
        "",
        "This refresh runner is not a trading system. It does not emit trade instructions, authorize live trading, send Telegram alerts, place orders, change cooldown, or add filters.",
        "",
        "## Purpose",
        "",
        "The runner coordinates existing Strategy 3 paper evidence reports into a repeatable audit snapshot: clean-context comparison status, VWAP/regime diagnostics availability, paper accumulation dashboard metrics, risk-distance summaries, and final evidence gates.",
        "",
        "## Key Metrics",
        "",
        f"- total paper rows: `{paper['total_paper_rows']}`",
        f"- legacy rows excluded: `{paper['legacy_without_context_rows']}`",
        f"- clean context rows: `{paper['clean_context_rows']}`",
        f"- clean accepted/blocked: `{paper['clean_accepted_rows']}/{paper['clean_blocked_rows']}`",
        f"- clean acceptance rate: `{paper['clean_acceptance_rate']}`",
        f"- cooldown blocked count: `{summary['cooldown']['cooldown_blocked_count']}`",
        f"- sample status: `{summary['sample_size']['sample_status']}`",
        "",
        "## Context And Comparison",
        "",
        f"- context gate: `{gates['context_gate']}`",
        f"- context gate reason: `{gates['context_gate_reason']}`",
        f"- prefix compatible/incompatible: `{context['prefix_compatible_rows']}/{context['prefix_incompatible_rows']}`",
        f"- paper/backtest match status: `{context['paper_backtest_match_status']}`",
        f"- all-detected match rate: `{context['all_detected_match_rate']}`",
        f"- accepted-only match rate: `{context['accepted_only_match_rate']}`",
        "",
        "## Accumulation Projection",
        "",
        f"- first clean signal: `{projection['first_clean_signal_timestamp']}`",
        f"- latest clean signal: `{projection['latest_clean_signal_timestamp']}`",
        f"- days since first clean signal: `{projection['days_since_first_clean_signal']}`",
        f"- accepted rows/day: `{projection['accepted_rows_per_day']}`",
        f"- projected days to 100 accepted: `{projection['projected_days_to_100_accepted']}`",
        f"- projected days to 200 accepted: `{projection['projected_days_to_200_accepted']}`",
        "",
        "## Risk Distance",
        "",
        f"- pip convention: `{risk['pip_convention']}`",
        f"- accepted median: `{risk['accepted_median_usd']}` USD / `{risk['accepted_median_pips']}` pips",
        f"- accepted p90: `{risk['accepted_p90_usd']}` USD / `{risk['accepted_p90_pips']}` pips",
        f"- accepted max: `{risk['accepted_max_usd']}` USD / `{risk['accepted_max_pips']}` pips",
        "",
        "Risk distance statistics are descriptive only. Large SL outliers require review, not automatic parameter changes.",
        "",
        "## Gates",
        "",
        f"- sample gate: `{gates['sample_gate']}`",
        f"- pre-registered diagnostic gate: `{gates['pre_registered_diagnostic_gate']}`",
        f"- cooldown change gate: `{gates['cooldown_change_gate']}`",
        f"- live gate: `{gates['live_gate']}`",
        f"- deployment gate: `{gates['deployment_gate']}`",
        f"- live readiness: `{gates['live_readiness']}`",
        f"- allowed next action: `{gates['allowed_next_action']}`",
        "",
        "## Weekly Run",
        "",
        "```powershell",
        "python scripts/run_strategy_3_paper_evidence_refresh.py --dry-run",
        "```",
        "",
        "Use this after the paper pipeline has accumulated new Strategy 3 rows and after the clean-context comparison/regime reports have been refreshed when needed.",
        "",
        "## Warnings",
        "",
    ]
    if summary["warnings"]:
        lines.extend(f"- `{warning}`" for warning in summary["warnings"])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- no live trading",
            "- no Telegram operational alerts",
            "- no orders",
            "- no broker execution",
            "- no order_send",
            "- no Strategy 3 VWAP/sigma/cooldown/entry/TP/SL/filter changes",
            "- no Strategy 2 touch",
            "- no Adelin touch",
            "- no data/XAUUSD/*.csv mutation",
            "",
            "## Next Recommendation",
            "",
            "Continue Strategy 3 paper accumulation only. Re-run this refresh weekly or after meaningful new clean-context paper rows arrive; do not use it to change strategy parameters.",
            "",
        ]
    )
    rendered = "\n".join(lines)
    (output_dir / "paper_evidence_refresh.md").write_text(rendered, encoding="utf-8")
    docs_path.write_text(rendered, encoding="utf-8")


def write_latest_dashboard_pointer(cfg: EvidenceRefreshConfig, summary: dict[str, Any]) -> None:
    pointer = {
        "created_at": _utc_now(),
        "dashboard_summary_path": str(cfg.dashboard_dir / "paper_accumulation_summary.json"),
        "dashboard_markdown_path": str(cfg.dashboard_dir / "paper_accumulation_dashboard.md"),
        "risk_distance_summary_path": str(cfg.dashboard_dir / "risk_distance_summary.csv"),
        "refresh_summary_path": str(cfg.output_dir / "paper_evidence_refresh_summary.json"),
        "gate_status_path": str(cfg.output_dir / "gate_status.json"),
        "live_readiness": summary["live_readiness"],
        "allowed_next_action": summary["allowed_next_action"],
    }
    _write_json(cfg.output_dir / "latest_dashboard_pointer.json", pointer)


def run_refresh(cfg: EvidenceRefreshConfig) -> dict[str, Any]:
    started = perf_counter()
    warnings: list[str] = []
    comparison_summary = load_comparison_summary(cfg, warnings)
    regime_summary = maybe_refresh_regime_diagnostics(cfg, warnings)
    dashboard_summary = maybe_refresh_dashboard(cfg, warnings)
    gate_status = build_gate_status(
        dashboard_summary=dashboard_summary,
        comparison_summary=comparison_summary,
        regime_summary=regime_summary,
        warnings=warnings,
        target_accepted_n_exploratory=cfg.target_accepted_n_exploratory,
        target_accepted_n_pre_registered_diagnostic=cfg.target_accepted_n_pre_registered_diagnostic,
    )
    summary = build_summary(
        cfg=cfg,
        dashboard_summary=dashboard_summary,
        comparison_summary=comparison_summary,
        regime_summary=regime_summary,
        gate_status=gate_status,
        warnings=warnings,
        runtime_seconds=perf_counter() - started,
    )
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(cfg.output_dir / "paper_evidence_refresh_summary.json", summary)
    _write_json(cfg.output_dir / "gate_status.json", gate_status)
    write_latest_dashboard_pointer(cfg, summary)
    write_markdown_report(cfg.output_dir, cfg.docs_path, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = EvidenceRefreshConfig(
        paper_signals_path=Path(args.paper_signals_path),
        scanner_summary_path=Path(args.scanner_summary_path),
        pipeline_summary_path=Path(args.pipeline_summary_path),
        comparison_dir=Path(args.comparison_dir),
        regime_dir=Path(args.regime_dir),
        dashboard_dir=Path(args.dashboard_dir),
        output_dir=Path(args.output_dir),
        docs_path=Path(args.docs_path),
        dashboard_docs_path=Path(args.dashboard_docs_path),
        data_dir=Path(args.data_dir),
        refresh_dashboard=not bool(args.skip_dashboard_refresh),
        refresh_regime_diagnostics=bool(args.refresh_regime_diagnostics),
        target_accepted_n_exploratory=int(args.target_accepted_n_exploratory),
        target_accepted_n_pre_registered_diagnostic=int(args.target_accepted_n_pre_registered_diagnostic),
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(run_refresh(cfg), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
