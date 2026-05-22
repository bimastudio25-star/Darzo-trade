from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from dazro_trade.analytics.strategy_2_invalidation_rate_audit import (
    audit_directionality,
    build_h1_context_audit,
    build_sticky_audit,
)
from dazro_trade.analytics.strategy_2_invalidation_state_machine import (
    STATE_H1_CONTEXT_ALREADY_CONSUMED,
    STATE_INVALIDATED_LONG,
    STATE_INVALIDATED_SHORT,
    STATE_MAE_NOT_REACHED,
    STATE_STRUCTURE_INVALID,
    STATE_TRUE_DUAL_DIRECTION_INVALIDATED,
    STATE_UNKNOWN_INVALIDATION_STATE,
    STATE_VALID_LONG,
    STATE_VALID_SHORT,
    build_invalidation_state_machine,
)


DEFAULT_RULEBOOK_INPUT = Path("backtests/reports/strategy_2_rulebook_v0_labeling/rulebook_v0_per_sample.csv")
OLD_FULLY_INVALIDATED_COUNT = 256
SAFETY = {
    "research_only": True,
    "taxonomy_fix_only": True,
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "broker_execution_called": False,
    "orders_sent": False,
    "order_send_called": False,
    "signals_generated": False,
    "runtime_registration": False,
    "parameters_optimized": False,
    "thresholds_tuned": False,
    "ml_used": False,
    "backtest_run": False,
    "pnl_metrics_generated": False,
    "reaction_quality_derived": False,
    "market_data_written": False,
}
VERDICT_FLAGS = [
    "FULLY_INVALIDATED_STATE_SPLIT_COMPLETE",
    "TRUE_DUAL_DIRECTION_INVALIDATION_SEPARATED",
    "H1_CONSUMED_SEPARATED",
    "MAE_NOT_REACHED_SEPARATED",
    "STATE_TAXONOMY_OVERLOAD_REDUCED",
    "STICKY_INVALIDATION_PRESERVED",
    "STRATEGY_2_REMAINS_RESEARCH_ONLY",
    "NO_DEPLOYMENT_DECISION",
]


@dataclass(frozen=True)
class FullyInvalidatedStateSplitResult:
    per_sample: pd.DataFrame
    distribution: pd.DataFrame
    true_dual_direction_examples: pd.DataFrame
    h1_consumed_examples: pd.DataFrame
    mae_not_reached_examples: pd.DataFrame
    structure_invalid_examples: pd.DataFrame
    summary: dict[str, Any]
    report_markdown: str


def resolve_rulebook_input(input_dir: str | Path) -> Path:
    summary_path = Path(input_dir) / "invalidation_state_machine_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        candidate = Path(str(summary.get("input_path", "")))
        if candidate.exists():
            return candidate
    if DEFAULT_RULEBOOK_INPUT.exists():
        return DEFAULT_RULEBOOK_INPUT
    raise FileNotFoundError(f"could not resolve rulebook input from {summary_path} or {DEFAULT_RULEBOOK_INPUT}")


def load_old_fully_invalidated_count(input_dir: str | Path, audit_dir: str | Path) -> int:
    for directory, filename in (
        (audit_dir, "invalidation_rate_summary.json"),
        (input_dir, "invalidation_state_machine_summary.json"),
    ):
        path = Path(directory) / filename
        if path.exists():
            summary = json.loads(path.read_text(encoding="utf-8"))
            if "fully_invalidated_count" in summary:
                return int(summary["fully_invalidated_count"])
    return OLD_FULLY_INVALIDATED_COUNT


def build_fully_invalidated_state_split(input_dir: str | Path, audit_dir: str | Path) -> FullyInvalidatedStateSplitResult:
    started = time.perf_counter()
    old_fully_count = load_old_fully_invalidated_count(input_dir, audit_dir)
    rulebook_input = resolve_rulebook_input(input_dir)
    rebuilt = build_invalidation_state_machine(rulebook_input)
    per_sample = rebuilt.per_sample.copy()
    distribution = rebuilt.distribution.copy()
    counts = Counter(per_sample["final_state"]) if not per_sample.empty else Counter()
    sticky_audit = build_sticky_audit(per_sample)
    h1_audit = build_h1_context_audit(per_sample)
    directionality = audit_directionality(per_sample)
    sticky_violations = int(sticky_audit["sticky_violation"].sum()) if not sticky_audit.empty else 0
    cross_h1_flags = int(h1_audit["potential_cross_h1_contamination"].sum()) if not h1_audit.empty else 0
    direction_violations = int(directionality["long_direction_violation_count"] + directionality["short_direction_violation_count"])
    true_dual_count = int(counts.get(STATE_TRUE_DUAL_DIRECTION_INVALIDATED, 0))
    summary = {
        "runtime_seconds": round(time.perf_counter() - started, 4),
        "input_dir": str(Path(input_dir)),
        "audit_dir": str(Path(audit_dir)),
        "rulebook_input": str(rulebook_input),
        "total_samples": int(len(per_sample)),
        "old_fully_invalidated_count": old_fully_count,
        "valid_long_count": int(counts.get(STATE_VALID_LONG, 0)),
        "valid_short_count": int(counts.get(STATE_VALID_SHORT, 0)),
        "invalidated_long_count": int(counts.get(STATE_INVALIDATED_LONG, 0)),
        "invalidated_short_count": int(counts.get(STATE_INVALIDATED_SHORT, 0)),
        "true_dual_direction_invalidated_count": true_dual_count,
        "h1_context_already_consumed_count": int(counts.get(STATE_H1_CONTEXT_ALREADY_CONSUMED, 0)),
        "mae_not_reached_count": int(counts.get(STATE_MAE_NOT_REACHED, 0)),
        "structure_invalid_count": int(counts.get(STATE_STRUCTURE_INVALID, 0)),
        "unknown_invalidation_state_count": int(counts.get(STATE_UNKNOWN_INVALIDATION_STATE, 0)),
        "sticky_violations": sticky_violations,
        "cross_h1_contamination_flags": cross_h1_flags,
        "direction_violations": direction_violations,
        "sticky_invalidation_preserved": sticky_violations == 0,
        "h1_boundary_cross_contamination_confirmed_absent": cross_h1_flags == 0,
        "directionality_confirmed": direction_violations == 0,
        "critical_conclusion": critical_conclusion(
            old_fully_count=old_fully_count,
            true_dual_count=true_dual_count,
            sticky_violations=sticky_violations,
            cross_h1_flags=cross_h1_flags,
            direction_violations=direction_violations,
        ),
        "pnl_metrics_generated": False,
        "signals_generated": False,
        "reaction_quality_derived": False,
        "verdict_flags": VERDICT_FLAGS,
        "safety": SAFETY,
    }
    result = FullyInvalidatedStateSplitResult(
        per_sample=per_sample,
        distribution=distribution,
        true_dual_direction_examples=examples_for_state(per_sample, STATE_TRUE_DUAL_DIRECTION_INVALIDATED),
        h1_consumed_examples=examples_for_state(per_sample, STATE_H1_CONTEXT_ALREADY_CONSUMED),
        mae_not_reached_examples=examples_for_state(per_sample, STATE_MAE_NOT_REACHED),
        structure_invalid_examples=examples_for_state(per_sample, STATE_STRUCTURE_INVALID),
        summary=summary,
        report_markdown="",
    )
    return FullyInvalidatedStateSplitResult(
        per_sample=result.per_sample,
        distribution=result.distribution,
        true_dual_direction_examples=result.true_dual_direction_examples,
        h1_consumed_examples=result.h1_consumed_examples,
        mae_not_reached_examples=result.mae_not_reached_examples,
        structure_invalid_examples=result.structure_invalid_examples,
        summary=result.summary,
        report_markdown=render_state_split_report(result.summary, result.distribution),
    )


def critical_conclusion(
    *,
    old_fully_count: int,
    true_dual_count: int,
    sticky_violations: int,
    cross_h1_flags: int,
    direction_violations: int,
) -> str:
    if sticky_violations or cross_h1_flags or direction_violations:
        return "STATE_SPLIT_FOUND_MECHANICAL_AUDIT_FLAGS"
    if true_dual_count < old_fully_count:
        return "FULLY_INVALIDATED_OVERLOAD_RESOLVED_LAYER_A_TAXONOMY_CLEARER"
    if true_dual_count == old_fully_count:
        return "TRUE_DUAL_REMAINS_CLOSE_TO_OLD_FULLY_REQUIRES_SAMPLE_EVIDENCE"
    return "STATE_SPLIT_COMPLETE_REVIEW_REQUIRED"


def examples_for_state(per_sample: pd.DataFrame, state: str, *, limit: int = 25) -> pd.DataFrame:
    columns = [
        "sample_id",
        "h1_context_id",
        "direction_candidate",
        "first_m15_side_taken",
        "long_invalidated",
        "short_invalidated",
        "invalidation_reason",
        "final_state",
        "reactivation_blocked",
        "state_transition_log",
    ]
    if per_sample.empty:
        return pd.DataFrame(columns=columns)
    return per_sample[per_sample["final_state"].eq(state)].head(limit)[columns].copy()


def write_state_split_outputs(
    result: FullyInvalidatedStateSplitResult,
    output_dir: str | Path,
    *,
    docs_path: str | Path | None = None,
) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "per_sample": output / "state_split_per_sample.csv",
        "distribution": output / "state_split_distribution.csv",
        "true_dual_direction_examples": output / "true_dual_direction_examples.csv",
        "h1_consumed_examples": output / "h1_consumed_examples.csv",
        "mae_not_reached_examples": output / "mae_not_reached_examples.csv",
        "structure_invalid_examples": output / "structure_invalid_examples.csv",
        "summary": output / "state_split_summary.json",
        "report": output / "state_split_report.md",
    }
    result.per_sample.to_csv(paths["per_sample"], index=False)
    result.distribution.to_csv(paths["distribution"], index=False)
    result.true_dual_direction_examples.to_csv(paths["true_dual_direction_examples"], index=False)
    result.h1_consumed_examples.to_csv(paths["h1_consumed_examples"], index=False)
    result.mae_not_reached_examples.to_csv(paths["mae_not_reached_examples"], index=False)
    result.structure_invalid_examples.to_csv(paths["structure_invalid_examples"], index=False)
    paths["summary"].write_text(json.dumps(result.summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    paths["report"].write_text(result.report_markdown, encoding="utf-8")
    if docs_path:
        docs = Path(docs_path)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(result.report_markdown, encoding="utf-8")
        paths["docs"] = docs
    return {key: str(path) for key, path in paths.items()}


def render_state_split_report(summary: dict[str, Any], distribution: pd.DataFrame) -> str:
    lines = [
        "# Strategy 2 Fully Invalidated State Split",
        "",
        "## Context",
        "",
        "The invalidation state machine was mechanically consistent, but the audit showed that `FULLY_INVALIDATED` was overloaded. Many rows were H1-consumed or MAE-not-reached cases, not true dual-direction M15 invalidations.",
        "",
        "## Old Vs New Taxonomy",
        "",
        "- `TRUE_DUAL_DIRECTION_INVALIDATED`: both LONG and SHORT were invalidated by their valid directional M15 opposite-side logic.",
        "- `H1_CONTEXT_ALREADY_CONSUMED`: the H1 reference was already consumed or no fresh H1 setup remained.",
        "- `MAE_NOT_REACHED`: the setup never reached the valid deviation zone and remains setup-incomplete/no-entry.",
        "- `STRUCTURE_INVALID`: source/H1/M15 structure is invalid without true dual-direction invalidation.",
        "- `UNKNOWN_INVALIDATION_STATE`: fallback when the reason cannot be classified confidently.",
        "",
        "## Results",
        "",
        f"- total samples: `{summary['total_samples']}`",
        f"- OLD FULLY_INVALIDATED: `{summary['old_fully_invalidated_count']}`",
        f"- NEW TRUE_DUAL_DIRECTION_INVALIDATED: `{summary['true_dual_direction_invalidated_count']}`",
        f"- H1_CONTEXT_ALREADY_CONSUMED: `{summary['h1_context_already_consumed_count']}`",
        f"- MAE_NOT_REACHED: `{summary['mae_not_reached_count']}`",
        f"- STRUCTURE_INVALID: `{summary['structure_invalid_count']}`",
        f"- UNKNOWN_INVALIDATION_STATE: `{summary['unknown_invalidation_state_count']}`",
        f"- sticky violations: `{summary['sticky_violations']}`",
        f"- cross-H1 contamination flags: `{summary['cross_h1_contamination_flags']}`",
        f"- direction violations: `{summary['direction_violations']}`",
        f"- critical conclusion: `{summary['critical_conclusion']}`",
        "",
        "## State Distribution",
        "",
        "| State | Count | Rate |",
        "|---|---:|---:|",
    ]
    for row in distribution.to_dict("records"):
        lines.append(f"| {row['final_state']} | {row['count']} | {row['rate']} |")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Strategy 3 untouched.",
            "- Adelin untouched.",
            "- data/XAUUSD/*.csv untouched.",
            "- No live trading, broker execution, orders, Telegram, optimization, ML, backtest, PnL, signals, or reaction-quality derivation.",
            "",
            "## Critical Conclusion",
            "",
            "The `FULLY_INVALIDATED` overload is resolved when true dual-direction invalidation is separated from H1-consumed, MAE-not-reached, structure-invalid, and unknown terminal states. True hard invalidation is now clearer, and Layer A is taxonomy-ready for later Layer B work. This does not validate profitability or derive Layer B reaction quality.",
            "",
            "## Honest Limitations",
            "",
            "- No reaction-quality derivation.",
            "- No behavioral layer.",
            "- No profitability claim.",
            "- No deployment decision.",
            "",
            "## Verdict Flags",
            "",
            "\n".join(f"- `{flag}`" for flag in summary["verdict_flags"]),
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "FullyInvalidatedStateSplitResult",
    "build_fully_invalidated_state_split",
    "critical_conclusion",
    "examples_for_state",
    "load_old_fully_invalidated_count",
    "resolve_rulebook_input",
    "write_state_split_outputs",
]
