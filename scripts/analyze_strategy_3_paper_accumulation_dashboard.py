from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STRATEGY_NAME = "strategy_3_vwap_1r"
DEFAULT_OUTPUT_DIR = Path("backtests/reports/strategy_3_paper_accumulation_dashboard")
DEFAULT_REGIME_DIR = Path("backtests/reports/strategy_3_vwap_trend_regime_diagnostics")
DEFAULT_DOCS_PATH = Path("docs/research/strategy_3_paper_accumulation_evidence_dashboard.md")
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
}
REGIME_DIMENSIONS = [
    "direction",
    "session_bucket",
    "setup_mode",
    "band_touched",
    "price_vs_vwap",
    "vwap_distance_sigma_bucket",
    "vwap_slope_bucket",
    "h1_bias",
    "h4_bias",
    "volatility_bucket",
]
METADATA_SCHEMA_FIELDS = [
    "strategy_3_regime_schema_version",
    "session_bucket",
    "signal_direction",
    "vwap_slope_bucket",
    "vwap_distance_bucket",
    "h1_bias",
    "h4_bias",
    "volatility_bucket",
    "cooldown_active",
    "cooldown_remaining_minutes",
    "block_reason",
    "context_compatibility_status",
]


@dataclass(frozen=True)
class DashboardConfig:
    paper_signals_path: Path
    scanner_summary_path: Path
    pipeline_summary_path: Path
    regime_dir: Path
    output_dir: Path
    docs_path: Path
    min_bucket_total: int
    watchlist_accepted_threshold: int
    pre_registered_accepted_threshold: int
    dry_run: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strategy 3 paper accumulation evidence dashboard")
    parser.add_argument("--paper-signals-path", default="backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv")
    parser.add_argument("--scanner-summary-path", default="backtests/reports/strategy_3_paper_shadow_scanner/scanner_summary.json")
    parser.add_argument("--pipeline-summary-path", default="backtests/reports/strategy_3_local_paper_pipeline/pipeline_summary.json")
    parser.add_argument("--regime-dir", default=str(DEFAULT_REGIME_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--docs-path", default=str(DEFAULT_DOCS_PATH))
    parser.add_argument("--min-bucket-total", type=int, default=30)
    parser.add_argument("--watchlist-accepted-threshold", type=int, default=100)
    parser.add_argument("--pre-registered-accepted-threshold", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = sorted({key for row in rows for key in row.keys()}) or ["empty"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_ts(value: Any) -> datetime | None:
    if value is None or str(value).strip() == "":
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.to_pydatetime()


def readiness_label(*, total_rows: int, accepted_rows: int, min_bucket_total: int, watchlist_accepted_threshold: int, pre_registered_accepted_threshold: int) -> str:
    if total_rows < min_bucket_total or accepted_rows < 30:
        return "INSUFFICIENT_N"
    if accepted_rows < watchlist_accepted_threshold:
        return "DESCRIPTIVE_ONLY"
    if accepted_rows < pre_registered_accepted_threshold:
        return "WATCHLIST"
    return "READY_FOR_PRE_REGISTERED_DIAGNOSTIC"


def global_sample_status(accepted_rows: int, watchlist_accepted_threshold: int, pre_registered_accepted_threshold: int) -> dict[str, Any]:
    if accepted_rows < 30:
        label = "INSUFFICIENT_N"
    elif accepted_rows < watchlist_accepted_threshold:
        label = "DESCRIPTIVE_ONLY"
    elif accepted_rows < pre_registered_accepted_threshold:
        label = "WATCHLIST"
    else:
        label = "READY_FOR_PRE_REGISTERED_DIAGNOSTIC"
    return {
        "accepted_rows": accepted_rows,
        "sample_size_status": label,
        "accepted_rows_too_small_warning": accepted_rows < watchlist_accepted_threshold,
        "power_planning_note": (
            "26 accepted rows is insufficient for regime-level conclusions. n>=100 accepted can support only exploratory watchlist status; "
            "robust regime comparisons may need much larger samples, especially for modest win-rate differences."
        ),
    }


def segment_paper_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    legacy = [row for row in rows if not str(row.get("data_context_hash") or "").strip()]
    clean = [row for row in rows if str(row.get("data_context_hash") or "").strip()]
    accepted = [row for row in clean if _bool(row.get("cooldown_accepted"))]
    blocked = [row for row in clean if not _bool(row.get("cooldown_accepted"))]
    return {
        "total_paper_rows": len(rows),
        "legacy_without_context_rows": len(legacy),
        "clean_context_rows": len(clean),
        "clean_accepted_rows": len(accepted),
        "clean_blocked_rows": len(blocked),
        "clean_acceptance_rate": round(len(accepted) / len(clean), 4) if clean else None,
        "legacy_rows": legacy,
        "clean_rows": clean,
        "accepted_rows": accepted,
        "blocked_rows": blocked,
    }


def load_regime_rows(regime_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    per_signal = _read_csv(regime_dir / "regime_diagnostics_per_signal.csv")
    by_regime = _read_csv(regime_dir / "accepted_vs_blocked_by_regime.csv")
    summary = _read_json(regime_dir / "regime_summary.json")
    return per_signal, by_regime, summary


def accepted_sample_by_regime(by_regime: list[dict[str, Any]], cfg: DashboardConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in by_regime:
        total = _int(item.get("total_rows"))
        accepted = _int(item.get("accepted_rows"))
        rows.append(
            {
                "regime_dimension": item.get("regime_dimension"),
                "regime_bucket": item.get("regime_bucket"),
                "total_rows": total,
                "accepted_rows": accepted,
                "blocked_rows": _int(item.get("blocked_rows")),
                "accepted_rate": item.get("accepted_rate"),
                "sample_size_status": readiness_label(
                    total_rows=total,
                    accepted_rows=accepted,
                    min_bucket_total=cfg.min_bucket_total,
                    watchlist_accepted_threshold=cfg.watchlist_accepted_threshold,
                    pre_registered_accepted_threshold=cfg.pre_registered_accepted_threshold,
                ),
                "non_decision_metadata_only": True,
            }
        )
    return rows


def blocked_sample_by_reason(clean_blocked_rows: list[dict[str, Any]], existing_summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if existing_summary:
        return [
            {
                "block_reason": row.get("block_reason"),
                "blocked_rows": _int(row.get("blocked_rows")),
                "pct_blocked_rows": row.get("pct_blocked_rows"),
                "decision_policy_changed": False,
            }
            for row in existing_summary
        ]
    counts: dict[str, int] = {}
    for row in clean_blocked_rows:
        reason = row.get("cooldown_block_reason") or "blocked_unspecified"
        counts[str(reason)] = counts.get(str(reason), 0) + 1
    total = sum(counts.values())
    return [
        {
            "block_reason": reason,
            "blocked_rows": count,
            "pct_blocked_rows": round(count / total, 4) if total else 0.0,
            "decision_policy_changed": False,
        }
        for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def cooldown_tracking(clean_rows: list[dict[str, Any]], cooldown_minutes: int = 120) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in clean_rows:
        accepted = _bool(row.get("cooldown_accepted"))
        decision_time = _parse_ts(row.get("signal_timestamp"))
        previous_time = _parse_ts(row.get("last_signal_timestamp_same_symbol_direction"))
        minutes_since_previous = None
        remaining = None
        if decision_time and previous_time:
            minutes_since_previous = round((decision_time - previous_time).total_seconds() / 60.0, 2)
            remaining = max(0.0, round(cooldown_minutes - minutes_since_previous, 2))
        rows.append(
            {
                "decision_time": row.get("signal_timestamp"),
                "direction": row.get("direction"),
                "session_bucket": row.get("session"),
                "cooldown_accepted": accepted,
                "cooldown_active": not accepted,
                "block_reason": "" if accepted else (row.get("cooldown_block_reason") or "blocked_unspecified"),
                "last_signal_timestamp_same_symbol_direction": row.get("last_signal_timestamp_same_symbol_direction"),
                "minutes_since_previous_same_symbol_direction": minutes_since_previous,
                "cooldown_remaining_minutes_estimate": remaining,
                "cooldown_minutes_policy": cooldown_minutes,
                "cooldown_policy_changed": False,
            }
        )
    return rows


def regime_sample_size_status(by_regime: list[dict[str, Any]], cfg: DashboardConfig) -> list[dict[str, Any]]:
    status = accepted_sample_by_regime(by_regime, cfg)
    return sorted(status, key=lambda row: (str(row["regime_dimension"]), str(row["regime_bucket"])))


def build_summary(
    *,
    cfg: DashboardConfig,
    paper_segments: dict[str, Any],
    scanner_summary: dict[str, Any],
    pipeline_summary: dict[str, Any],
    regime_summary: dict[str, Any],
    accepted_regimes: list[dict[str, Any]],
    blocked_reasons: list[dict[str, Any]],
    cooldown_rows: list[dict[str, Any]],
    sample_status_rows: list[dict[str, Any]],
    runtime_seconds: float,
) -> dict[str, Any]:
    global_status = global_sample_status(
        paper_segments["clean_accepted_rows"],
        cfg.watchlist_accepted_threshold,
        cfg.pre_registered_accepted_threshold,
    )
    context_gate_passed = bool(regime_summary.get("context_gate", {}).get("context_gate_passed"))
    prefix_compatible = regime_summary.get("comparison_context", {}).get("prefix_compatible_rows")
    prefix_incompatible = regime_summary.get("comparison_context", {}).get("prefix_incompatible_rows")
    return {
        "run_finished_at": _utc_now(),
        "runtime_seconds": round(runtime_seconds, 4),
        "dry_run": cfg.dry_run,
        "strategy": STRATEGY_NAME,
        "inputs": {
            "paper_signals_path": str(cfg.paper_signals_path),
            "scanner_summary_path": str(cfg.scanner_summary_path),
            "pipeline_summary_path": str(cfg.pipeline_summary_path),
            "regime_dir": str(cfg.regime_dir),
        },
        "paper_rows": {
            "total_paper_rows": paper_segments["total_paper_rows"],
            "legacy_without_context_rows": paper_segments["legacy_without_context_rows"],
            "clean_context_rows": paper_segments["clean_context_rows"],
            "clean_accepted_rows": paper_segments["clean_accepted_rows"],
            "clean_blocked_rows": paper_segments["clean_blocked_rows"],
            "clean_acceptance_rate": paper_segments["clean_acceptance_rate"],
        },
        "context": {
            "context_gate_passed": context_gate_passed,
            "prefix_compatible_rows": prefix_compatible,
            "prefix_incompatible_rows": prefix_incompatible,
            "paper_signals_clean_for_validation": regime_summary.get("context_gate", {}).get("context_gate_passed"),
            "scanner_summary_latest_processed_timestamp": scanner_summary.get("last_processed_timestamp") or scanner_summary.get("new_last_processed_timestamp"),
            "pipeline_summary_consistency_status": pipeline_summary.get("summary_consistency_status"),
        },
        "cooldown": {
            "cooldown_blocked_count": sum(1 for row in cooldown_rows if row["cooldown_active"]),
            "cooldown_accepted_count": sum(1 for row in cooldown_rows if not row["cooldown_active"]),
            "cooldown_policy_changed": False,
            "block_reason_distribution": blocked_reasons,
        },
        "sample_size": global_status,
        "regime_bucket_count": len(sample_status_rows),
        "metadata_schema_fields": list(METADATA_SCHEMA_FIELDS),
        "metadata_fields_are_decision_fields": False,
        "deployment_recommendation_emitted": False,
        "parameter_or_filter_recommendation_emitted": False,
        "verdict_flags": [
            "STRATEGY_3_LEVEL_3_PAPER_CANDIDATE",
            "PAPER_ACCUMULATION_EVIDENCE_DASHBOARD_CREATED",
            "CONTEXT_GATE_PASSED" if context_gate_passed else "CONTEXT_GATE_NOT_PASSED",
            "INSUFFICIENT_ACCEPTED_SAMPLE_FOR_REGIME_CONCLUSIONS" if global_status["accepted_rows_too_small_warning"] else "ACCEPTED_SAMPLE_WATCHLIST_READY",
            "DIAGNOSTICS_ONLY",
            "NO_PARAMETER_RECOMMENDATION",
            "NO_COOLDOWN_CHANGE_RECOMMENDATION",
            "NO_LIVE_DEPLOYMENT_DECISION",
            "STRATEGY_3_REMAINS_PAPER_ONLY",
        ],
        "next_recommendation": (
            "Continue Strategy 3 paper accumulation with metadata logging active; use dashboard labels to decide when a future pre-registered diagnostic is worth opening."
        ),
        "safety": dict(SAFETY),
    }


def write_dashboard_report(output_dir: Path, docs_path: Path, summary: dict[str, Any], sample_status_rows: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    top_rows = sample_status_rows[:12]
    lines = [
        "# Strategy 3 Paper Accumulation Evidence Dashboard",
        "",
        "Strategy 3 remains Level 3 / Paper Candidate. This dashboard is diagnostics/logging only and does not approve live trading or change signal behavior.",
        "",
        "## Paper Accumulation Status",
        "",
        f"- total paper rows: `{summary['paper_rows']['total_paper_rows']}`",
        f"- legacy rows excluded from clean evidence: `{summary['paper_rows']['legacy_without_context_rows']}`",
        f"- clean context rows: `{summary['paper_rows']['clean_context_rows']}`",
        f"- clean accepted/blocked: `{summary['paper_rows']['clean_accepted_rows']}/{summary['paper_rows']['clean_blocked_rows']}`",
        f"- clean acceptance rate: `{summary['paper_rows']['clean_acceptance_rate']}`",
        f"- accepted sample status: `{summary['sample_size']['sample_size_status']}`",
        "",
        "## Context Gate",
        "",
        f"- context_gate_passed: `{summary['context']['context_gate_passed']}`",
        f"- prefix_compatible_rows: `{summary['context']['prefix_compatible_rows']}`",
        f"- prefix_incompatible_rows: `{summary['context']['prefix_incompatible_rows']}`",
        "",
        "## Cooldown",
        "",
        f"- cooldown accepted count: `{summary['cooldown']['cooldown_accepted_count']}`",
        f"- cooldown blocked count: `{summary['cooldown']['cooldown_blocked_count']}`",
        f"- cooldown policy changed: `{summary['cooldown']['cooldown_policy_changed']}`",
        "",
        "| block_reason | blocked_rows | pct_blocked_rows |",
        "|---|---:|---:|",
    ]
    for row in summary["cooldown"]["block_reason_distribution"]:
        lines.append(f"| {row['block_reason']} | {row['blocked_rows']} | {row['pct_blocked_rows']} |")
    lines.extend(
        [
            "",
            "## Regime Sample Status",
            "",
            "| dimension | bucket | total | accepted | status |",
            "|---|---|---:|---:|---|",
        ]
    )
    for row in top_rows:
        lines.append(
            f"| {row['regime_dimension']} | {row['regime_bucket']} | {row['total_rows']} | {row['accepted_rows']} | {row['sample_size_status']} |"
        )
    lines.extend(
        [
            "",
            "## Metadata Schema",
            "",
            "Future paper logging may record the following non-decision metadata fields:",
            "",
        ]
    )
    for field in METADATA_SCHEMA_FIELDS:
        lines.append(f"- `{field}`")
    lines.extend(
        [
            "",
            "These fields are metadata only. They must not be used to accept, block, filter, or modify signals in this branch.",
            "",
            "## Power Planning",
            "",
            "- 26 accepted clean signals is insufficient for regime-level conclusions.",
            "- n>=100 accepted may be enough only for exploratory watchlist status, not robust inference.",
            "- Regime comparisons may require much larger samples, especially when looking for modest win-rate differences.",
            "- No trading recommendation is emitted from this power planning section.",
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
            summary["next_recommendation"],
            "",
        ]
    )
    rendered = "\n".join(lines)
    (output_dir / "paper_accumulation_dashboard.md").write_text(rendered, encoding="utf-8")
    docs_path.write_text(rendered, encoding="utf-8")


def run_dashboard(cfg: DashboardConfig) -> dict[str, Any]:
    started = perf_counter()
    paper_rows = _read_csv(cfg.paper_signals_path)
    scanner_summary = _read_json(cfg.scanner_summary_path)
    pipeline_summary = _read_json(cfg.pipeline_summary_path)
    regime_per_signal, regime_by_bucket, regime_summary = load_regime_rows(cfg.regime_dir)
    paper_segments = segment_paper_rows(paper_rows)
    accepted_regimes = accepted_sample_by_regime(regime_by_bucket, cfg)
    existing_blocked = _read_csv(cfg.regime_dir / "blocked_reason_summary.csv")
    blocked_reasons = blocked_sample_by_reason(paper_segments["blocked_rows"], existing_blocked)
    cooldown_rows = cooldown_tracking(paper_segments["clean_rows"])
    sample_status_rows = regime_sample_size_status(regime_by_bucket, cfg)
    summary = build_summary(
        cfg=cfg,
        paper_segments=paper_segments,
        scanner_summary=scanner_summary,
        pipeline_summary=pipeline_summary,
        regime_summary=regime_summary,
        accepted_regimes=accepted_regimes,
        blocked_reasons=blocked_reasons,
        cooldown_rows=cooldown_rows,
        sample_status_rows=sample_status_rows,
        runtime_seconds=perf_counter() - started,
    )
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    (cfg.output_dir / "paper_accumulation_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    _write_csv(
        cfg.output_dir / "accepted_sample_by_regime.csv",
        accepted_regimes,
        ["regime_dimension", "regime_bucket", "total_rows", "accepted_rows", "blocked_rows", "accepted_rate", "sample_size_status", "non_decision_metadata_only"],
    )
    _write_csv(cfg.output_dir / "blocked_sample_by_reason.csv", blocked_reasons, ["block_reason", "blocked_rows", "pct_blocked_rows", "decision_policy_changed"])
    _write_csv(
        cfg.output_dir / "cooldown_block_tracking.csv",
        cooldown_rows,
        [
            "decision_time",
            "direction",
            "session_bucket",
            "cooldown_accepted",
            "cooldown_active",
            "block_reason",
            "last_signal_timestamp_same_symbol_direction",
            "minutes_since_previous_same_symbol_direction",
            "cooldown_remaining_minutes_estimate",
            "cooldown_minutes_policy",
            "cooldown_policy_changed",
        ],
    )
    _write_csv(
        cfg.output_dir / "regime_sample_size_status.csv",
        sample_status_rows,
        ["regime_dimension", "regime_bucket", "total_rows", "accepted_rows", "blocked_rows", "accepted_rate", "sample_size_status", "non_decision_metadata_only"],
    )
    write_dashboard_report(cfg.output_dir, cfg.docs_path, summary, sample_status_rows)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = DashboardConfig(
        paper_signals_path=Path(args.paper_signals_path),
        scanner_summary_path=Path(args.scanner_summary_path),
        pipeline_summary_path=Path(args.pipeline_summary_path),
        regime_dir=Path(args.regime_dir),
        output_dir=Path(args.output_dir),
        docs_path=Path(args.docs_path),
        min_bucket_total=int(args.min_bucket_total),
        watchlist_accepted_threshold=int(args.watchlist_accepted_threshold),
        pre_registered_accepted_threshold=int(args.pre_registered_accepted_threshold),
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(run_dashboard(cfg), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
