from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
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
XAUUSD_PROJECT_PIPS_PER_USD = 10.0
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
    parser.add_argument("--pre-registered-accepted-threshold", type=int, default=200)
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
            f"{accepted_rows} accepted rows is insufficient for regime-level conclusions. n>=100 accepted can support only exploratory watchlist status; "
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


def allowed_interpretation(sample_status: str) -> str:
    if sample_status in {"INSUFFICIENT_N", "DESCRIPTIVE_ONLY"}:
        return "INSUFFICIENT_N_DESCRIPTIVE_ONLY"
    if sample_status == "WATCHLIST":
        return "WATCHLIST_ONLY"
    if sample_status == "READY_FOR_PRE_REGISTERED_DIAGNOSTIC":
        return "READY_FOR_PRE_REGISTERED_DIAGNOSTIC"
    return "NOT_ALLOWED_FOR_DEPLOYMENT"


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
    rows: list[dict[str, Any]] = []
    for item in accepted_sample_by_regime(by_regime, cfg):
        accepted = _int(item.get("accepted_rows"))
        status = str(item.get("sample_size_status"))
        rows.append(
            {
                "bucket_name": item.get("regime_dimension"),
                "bucket_value": item.get("regime_bucket"),
                "clean_rows": item.get("total_rows"),
                "accepted_rows": accepted,
                "blocked_rows": item.get("blocked_rows"),
                "sample_status": status,
                "gap_to_100_accepted": max(0, cfg.watchlist_accepted_threshold - accepted),
                "gap_to_200_accepted": max(0, cfg.pre_registered_accepted_threshold - accepted),
                "allowed_interpretation": allowed_interpretation(status),
                "deployment_allowed": False,
            }
        )
    return sorted(rows, key=lambda row: (str(row["bucket_name"]), str(row["bucket_value"])))


def accumulation_projection(clean_rows: list[dict[str, Any]], accepted_rows: list[dict[str, Any]], cfg: DashboardConfig) -> dict[str, Any]:
    timestamps = [_parse_ts(row.get("signal_timestamp")) for row in clean_rows]
    timestamps = [ts for ts in timestamps if ts is not None]
    if not timestamps:
        return {
            "projection_status": "INSUFFICIENT_TIMESTAMP_DATA",
            "first_clean_signal_timestamp": None,
            "latest_clean_signal_timestamp": None,
            "days_since_first_clean_signal": None,
            "clean_rows_per_day": None,
            "accepted_rows_per_day": None,
            "target_accepted_n_exploratory": cfg.watchlist_accepted_threshold,
            "target_accepted_n_pre_registered_diagnostic": cfg.pre_registered_accepted_threshold,
            "current_gap_to_exploratory_n": max(0, cfg.watchlist_accepted_threshold - len(accepted_rows)),
            "current_gap_to_pre_registered_diagnostic_n": max(0, cfg.pre_registered_accepted_threshold - len(accepted_rows)),
            "projected_days_to_exploratory_n": None,
            "projected_days_to_pre_registered_diagnostic_n": None,
            "regime_level_claims": "NOT_ALLOWED_FROM_DASHBOARD",
        }
    first = min(timestamps)
    latest = max(timestamps)
    elapsed_days = max((latest - first).total_seconds() / 86400.0, 0.0)
    denominator_days = elapsed_days if elapsed_days > 0 else None
    clean_per_day = round(len(clean_rows) / denominator_days, 4) if denominator_days else None
    accepted_per_day = round(len(accepted_rows) / denominator_days, 4) if denominator_days else None
    gap_exploratory = max(0, cfg.watchlist_accepted_threshold - len(accepted_rows))
    gap_pre_registered = max(0, cfg.pre_registered_accepted_threshold - len(accepted_rows))

    def project(gap: int) -> float | None:
        if gap <= 0:
            return 0.0
        if not accepted_per_day or accepted_per_day <= 0:
            return None
        return round(gap / accepted_per_day, 2)

    return {
        "projection_status": "OK" if denominator_days else "INSUFFICIENT_TIMESTAMP_SPAN",
        "first_clean_signal_timestamp": first.isoformat(),
        "latest_clean_signal_timestamp": latest.isoformat(),
        "days_since_first_clean_signal": round(elapsed_days, 4),
        "clean_rows_per_day": clean_per_day,
        "accepted_rows_per_day": accepted_per_day,
        "target_accepted_n_exploratory": cfg.watchlist_accepted_threshold,
        "target_accepted_n_pre_registered_diagnostic": cfg.pre_registered_accepted_threshold,
        "current_gap_to_exploratory_n": gap_exploratory,
        "current_gap_to_pre_registered_diagnostic_n": gap_pre_registered,
        "projected_days_to_exploratory_n": project(gap_exploratory),
        "projected_days_to_pre_registered_diagnostic_n": project(gap_pre_registered),
        "regime_level_claims": "NOT_ALLOWED_FROM_DASHBOARD",
    }


def risk_distance_usd(row: dict[str, Any]) -> float | None:
    entry = _float(row.get("entry_price"))
    stop = _float(row.get("stop_loss") or row.get("sl"))
    if entry is not None and stop is not None:
        return round(abs(entry - stop), 6)
    fallback = _float(row.get("risk_distance_usd") or row.get("risk_distance"))
    return round(abs(fallback), 6) if fallback is not None else None


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return round(float(pd.Series(values).quantile(q)), 6)


def risk_stats(label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [risk_distance_usd(row) for row in rows]
    values = [value for value in values if value is not None]
    pips = [value * XAUUSD_PROJECT_PIPS_PER_USD for value in values]

    def stat(source: list[float], q: float | None = None) -> float | None:
        if not source:
            return None
        if q is not None:
            return percentile(source, q)
        return round(float(pd.Series(source).mean()), 6)

    return {
        "group": label,
        "count": len(values),
        "usd_min": round(min(values), 6) if values else None,
        "usd_p25": stat(values, 0.25),
        "usd_median": stat(values, 0.50),
        "usd_mean": stat(values),
        "usd_p75": stat(values, 0.75),
        "usd_p90": stat(values, 0.90),
        "usd_p95": stat(values, 0.95),
        "usd_max": round(max(values), 6) if values else None,
        "pips_min": round(min(pips), 6) if pips else None,
        "pips_p25": stat(pips, 0.25),
        "pips_median": stat(pips, 0.50),
        "pips_mean": stat(pips),
        "pips_p75": stat(pips, 0.75),
        "pips_p90": stat(pips, 0.90),
        "pips_p95": stat(pips, 0.95),
        "pips_max": round(max(pips), 6) if pips else None,
        "pip_convention": "PROJECT_PIP_CONVENTION: 1 USD = 10 pips",
        "descriptive_only": True,
    }


def risk_distance_summary(clean_rows: list[dict[str, Any]], regime_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_time = {str(row.get("decision_time") or row.get("signal_timestamp")): row for row in regime_rows}
    enriched: list[dict[str, Any]] = []
    for row in clean_rows:
        merged = dict(row)
        merged.update(rows_by_time.get(str(row.get("signal_timestamp")), {}))
        enriched.append(merged)
    accepted = [row for row in enriched if _bool(row.get("cooldown_accepted")) or row.get("accepted_or_blocked") == "accepted"]
    blocked = [row for row in enriched if not (_bool(row.get("cooldown_accepted")) or row.get("accepted_or_blocked") == "accepted")]
    out = [
        risk_stats("all_clean_rows", enriched),
        risk_stats("accepted_rows", accepted),
        risk_stats("blocked_rows", blocked),
    ]
    for direction in sorted({str(row.get("direction") or "") for row in enriched if row.get("direction")}):
        out.append(risk_stats(f"direction={direction}", [row for row in enriched if str(row.get("direction") or "") == direction]))
    for field in ("vwap_slope_bucket", "band_touched", "setup_mode"):
        for value in sorted({str(row.get(field) or "") for row in enriched if row.get(field)}):
            out.append(risk_stats(f"{field}={value}", [row for row in enriched if str(row.get(field) or "") == value]))
    return out


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
    projection: dict[str, Any],
    risk_rows: list[dict[str, Any]],
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
        "accumulation_projection": projection,
        "risk_distance": {
            "pip_convention": "PROJECT_PIP_CONVENTION: 1 USD = 10 pips",
            "risk_stats_are_descriptive_only": True,
            "large_sl_outliers_require_review_not_parameter_change": True,
            "summary_rows": risk_rows,
        },
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
        "## Accumulation Projection",
        "",
        f"- first clean signal: `{summary['accumulation_projection']['first_clean_signal_timestamp']}`",
        f"- latest clean signal: `{summary['accumulation_projection']['latest_clean_signal_timestamp']}`",
        f"- days since first clean signal: `{summary['accumulation_projection']['days_since_first_clean_signal']}`",
        f"- clean rows/day: `{summary['accumulation_projection']['clean_rows_per_day']}`",
        f"- accepted rows/day: `{summary['accumulation_projection']['accepted_rows_per_day']}`",
        f"- exploratory accepted target: `{summary['accumulation_projection']['target_accepted_n_exploratory']}`",
        f"- pre-registered diagnostic accepted target: `{summary['accumulation_projection']['target_accepted_n_pre_registered_diagnostic']}`",
        f"- gap to exploratory target: `{summary['accumulation_projection']['current_gap_to_exploratory_n']}`",
        f"- gap to pre-registered diagnostic target: `{summary['accumulation_projection']['current_gap_to_pre_registered_diagnostic_n']}`",
        f"- projected days to exploratory target: `{summary['accumulation_projection']['projected_days_to_exploratory_n']}`",
        f"- projected days to pre-registered diagnostic target: `{summary['accumulation_projection']['projected_days_to_pre_registered_diagnostic_n']}`",
        f"- regime-level claims: `{summary['accumulation_projection']['regime_level_claims']}`",
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
            f"| {row['bucket_name']} | {row['bucket_value']} | {row['clean_rows']} | {row['accepted_rows']} | {row['sample_status']} |"
        )
    risk = {row["group"]: row for row in summary.get("risk_distance", {}).get("summary_rows", [])}
    all_clean = risk.get("all_clean_rows", {})
    accepted = risk.get("accepted_rows", {})
    lines.extend(
        [
            "",
            "## Risk Distance / Stop Loss",
            "",
            f"- pip convention: `{summary['risk_distance']['pip_convention']}`",
            f"- all clean median SL distance: `{all_clean.get('usd_median')}` USD / `{all_clean.get('pips_median')}` pips",
            f"- all clean p90 SL distance: `{all_clean.get('usd_p90')}` USD / `{all_clean.get('pips_p90')}` pips",
            f"- accepted median SL distance: `{accepted.get('usd_median')}` USD / `{accepted.get('pips_median')}` pips",
            f"- accepted p90 SL distance: `{accepted.get('usd_p90')}` USD / `{accepted.get('pips_p90')}` pips",
            "",
            "Risk stats are descriptive only. Large SL outliers require review, not automatic parameter changes. No SL/TP/cooldown/entry logic is modified.",
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
            "- n>=200 accepted is the current dashboard target for considering a pre-registered diagnostic, not deployment.",
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
    projection = accumulation_projection(paper_segments["clean_rows"], paper_segments["accepted_rows"], cfg)
    risk_rows = risk_distance_summary(paper_segments["clean_rows"], regime_per_signal)
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
        projection=projection,
        risk_rows=risk_rows,
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
        [
            "bucket_name",
            "bucket_value",
            "clean_rows",
            "accepted_rows",
            "blocked_rows",
            "sample_status",
            "gap_to_100_accepted",
            "gap_to_200_accepted",
            "allowed_interpretation",
            "deployment_allowed",
        ],
    )
    _write_csv(
        cfg.output_dir / "risk_distance_summary.csv",
        risk_rows,
        [
            "group",
            "count",
            "usd_min",
            "usd_p25",
            "usd_median",
            "usd_mean",
            "usd_p75",
            "usd_p90",
            "usd_p95",
            "usd_max",
            "pips_min",
            "pips_p25",
            "pips_median",
            "pips_mean",
            "pips_p75",
            "pips_p90",
            "pips_p95",
            "pips_max",
            "pip_convention",
            "descriptive_only",
        ],
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
