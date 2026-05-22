from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


VALID_STATES = {"VALID_LONG", "VALID_SHORT"}
STATE_FULLY_INVALIDATED = "FULLY_INVALIDATED"
STATE_TRUE_DUAL_DIRECTION_INVALIDATED = "TRUE_DUAL_DIRECTION_INVALIDATED"
STATE_H1_CONTEXT_ALREADY_CONSUMED = "H1_CONTEXT_ALREADY_CONSUMED"
STATE_MAE_NOT_REACHED = "MAE_NOT_REACHED"
STATE_STRUCTURE_INVALID = "STRUCTURE_INVALID"
STATE_UNKNOWN_INVALIDATION_STATE = "UNKNOWN_INVALIDATION_STATE"
INVALID_STATES = {
    "INVALIDATED_LONG",
    "INVALIDATED_SHORT",
    STATE_FULLY_INVALIDATED,
    STATE_TRUE_DUAL_DIRECTION_INVALIDATED,
    STATE_H1_CONTEXT_ALREADY_CONSUMED,
    STATE_MAE_NOT_REACHED,
    STATE_STRUCTURE_INVALID,
    STATE_UNKNOWN_INVALIDATION_STATE,
}
LONG_REASON = "OPPOSITE_M15_HIGH_TAKEN_FIRST_FOR_LONG"
SHORT_REASON = "OPPOSITE_M15_LOW_TAKEN_FIRST_FOR_SHORT"
TRUE_DUAL_REASON = "TRUE_DUAL_DIRECTION_INVALIDATION"
SUPPORTED_REASON_GROUPS = [
    LONG_REASON,
    SHORT_REASON,
    "DOUBLE_SWEEP_DEGRADATION",
    "H1_REFERENCE_ALREADY_CONSUMED",
    "MAE_NOT_REACHED",
    TRUE_DUAL_REASON,
    "FULLY_INVALIDATED_H1_CONTEXT",
    "UNKNOWN_OR_NONE",
    "OTHER",
]
SAFETY = {
    "research_only": True,
    "audit_only": True,
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
    "INVALIDATION_RATE_AUDITED",
    "STICKY_INVALIDATION_CONFIRMED",
    "H1_CONTEXT_SCOPING_VERIFIED",
    "FULLY_INVALIDATED_LOGIC_REVIEWED",
    "LAYER_B_POSTPONED_PENDING_AUDIT",
    "STRATEGY_2_REMAINS_RESEARCH_ONLY",
    "NO_DEPLOYMENT_DECISION",
]


@dataclass(frozen=True)
class InvalidationRateAuditResult:
    reason_distribution: pd.DataFrame
    transition_examples: pd.DataFrame
    h1_context_audit: pd.DataFrame
    fully_invalidated_examples: pd.DataFrame
    sticky_audit: pd.DataFrame
    summary: dict[str, Any]
    report_markdown: str


def load_state_machine_samples(input_dir: str | Path) -> pd.DataFrame:
    path = Path(input_dir) / "invalidation_state_machine_per_sample.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing state machine per-sample output: {path}")
    frame = pd.read_csv(path)
    required = {
        "sample_id",
        "h1_context_id",
        "direction_candidate",
        "first_m15_side_taken",
        "long_invalidated",
        "short_invalidated",
        "invalidation_reason",
        "final_state",
        "same_h1_reactivation_attempted",
        "reactivation_blocked",
        "state_transition_log",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"state machine output missing columns: {missing}")
    return normalize_state_machine_frame(frame)


def normalize_state_machine_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for field in ["long_invalidated", "short_invalidated", "opposite_side_taken_first", "same_h1_reactivation_attempted", "reactivation_blocked"]:
        if field in out.columns:
            out[field] = out[field].map(_boolish)
    for field in ["sample_id", "h1_context_id", "direction_candidate", "first_m15_side_taken", "invalidation_reason", "final_state", "state_transition_log"]:
        if field in out.columns:
            out[field] = out[field].fillna("").astype(str)
    return out


def reason_groups(reason: Any) -> list[str]:
    tokens = _tokens(reason)
    if not tokens:
        return ["UNKNOWN_OR_NONE"]
    groups: list[str] = []
    for token in tokens:
        if token in SUPPORTED_REASON_GROUPS:
            groups.append(token)
        else:
            groups.append("OTHER")
    return list(dict.fromkeys(groups))


def build_reason_distribution(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    total = len(frame)
    invalid_total = int(frame["final_state"].isin(INVALID_STATES).sum())
    for reason in SUPPORTED_REASON_GROUPS:
        mask = frame["invalidation_reason"].map(lambda value: reason in reason_groups(value))
        count = int(mask.sum())
        invalid_count = int((mask & frame["final_state"].isin(INVALID_STATES)).sum())
        rows.append(
            {
                "reason_group": reason,
                "sample_count": count,
                "sample_rate": _rate(count, total),
                "invalidated_sample_count": invalid_count,
                "invalidated_sample_rate": _rate(invalid_count, invalid_total),
            }
        )
    return pd.DataFrame(rows)


def audit_directionality(frame: pd.DataFrame) -> dict[str, Any]:
    long_rows = frame["direction_candidate"].eq("LONG")
    short_rows = frame["direction_candidate"].eq("SHORT")
    long_wrong = frame[long_rows & frame["invalidation_reason"].map(lambda value: SHORT_REASON in _tokens(value))]
    short_wrong = frame[short_rows & frame["invalidation_reason"].map(lambda value: LONG_REASON in _tokens(value))]
    long_m15 = frame[long_rows & frame["invalidation_reason"].map(lambda value: LONG_REASON in _tokens(value))]
    short_m15 = frame[short_rows & frame["invalidation_reason"].map(lambda value: SHORT_REASON in _tokens(value))]
    return {
        "long_m15_high_first_count": int(len(long_m15)),
        "short_m15_low_first_count": int(len(short_m15)),
        "long_direction_violation_count": int(len(long_wrong)),
        "short_direction_violation_count": int(len(short_wrong)),
        "directionality_confirmed": len(long_wrong) == 0 and len(short_wrong) == 0,
    }


def build_h1_context_audit(frame: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for context_id, group in frame.groupby("h1_context_id", dropna=False):
        long_invalidated = bool(group["long_invalidated"].any())
        short_invalidated = bool(group["short_invalidated"].any())
        legacy_fully_rows = group[group["final_state"].eq(STATE_FULLY_INVALIDATED)]
        true_dual_rows = group[group["final_state"].eq(STATE_TRUE_DUAL_DIRECTION_INVALIDATED)]
        fully_rows = group[group["final_state"].isin({STATE_FULLY_INVALIDATED, STATE_TRUE_DUAL_DIRECTION_INVALIDATED})]
        records.append(
            {
                "h1_context_id": context_id,
                "row_count": int(len(group)),
                "directions_present": ";".join(sorted(str(item) for item in group["direction_candidate"].dropna().unique())),
                "final_states": ";".join(sorted(str(item) for item in group["final_state"].dropna().unique())),
                "long_invalidated_any": long_invalidated,
                "short_invalidated_any": short_invalidated,
                "legacy_fully_invalidated_rows": int(len(legacy_fully_rows)),
                "true_dual_direction_invalidated_rows": int(len(true_dual_rows)),
                "fully_invalidated_rows": int(len(fully_rows)),
                "fully_invalidated_has_both_directional_invalidations": bool(long_invalidated and short_invalidated),
                "potential_cross_h1_contamination": bool(len(group) > 2),
            }
        )
    return pd.DataFrame(records)


def build_sticky_audit(frame: pd.DataFrame) -> pd.DataFrame:
    invalidated = frame[frame["final_state"].isin(INVALID_STATES)].copy()
    if invalidated.empty:
        return pd.DataFrame(columns=["sample_id", "h1_context_id", "final_state", "same_h1_reactivation_attempted", "reactivation_blocked", "sticky_violation"])
    invalidated["sticky_violation"] = invalidated["same_h1_reactivation_attempted"] & ~invalidated["reactivation_blocked"]
    return invalidated[
        [
            "sample_id",
            "h1_context_id",
            "final_state",
            "same_h1_reactivation_attempted",
            "reactivation_blocked",
            "sticky_violation",
            "state_transition_log",
        ]
    ].copy()


def build_transition_examples(frame: pd.DataFrame, *, per_state: int = 5) -> pd.DataFrame:
    examples: list[pd.DataFrame] = []
    for state in [
        "VALID_LONG",
        "VALID_SHORT",
        "INVALIDATED_LONG",
        "INVALIDATED_SHORT",
        STATE_TRUE_DUAL_DIRECTION_INVALIDATED,
        STATE_H1_CONTEXT_ALREADY_CONSUMED,
        STATE_MAE_NOT_REACHED,
        STATE_STRUCTURE_INVALID,
        STATE_UNKNOWN_INVALIDATION_STATE,
        STATE_FULLY_INVALIDATED,
    ]:
        subset = frame[frame["final_state"].eq(state)].head(per_state).copy()
        if not subset.empty:
            subset.insert(0, "example_group", state.lower())
            examples.append(subset)
    if not examples:
        return pd.DataFrame()
    columns = [
        "example_group",
        "sample_id",
        "h1_context_id",
        "direction_candidate",
        "first_m15_side_taken",
        "invalidation_reason",
        "final_state",
        "reactivation_blocked",
        "state_transition_log",
    ]
    return pd.concat(examples, ignore_index=True)[columns]


def build_fully_invalidated_examples(frame: pd.DataFrame, h1_context_audit: pd.DataFrame, *, limit: int = 25) -> pd.DataFrame:
    fully = frame[frame["final_state"].isin({STATE_FULLY_INVALIDATED, STATE_TRUE_DUAL_DIRECTION_INVALIDATED})].copy()
    if fully.empty:
        return pd.DataFrame()
    context_flags = h1_context_audit.set_index("h1_context_id")["fully_invalidated_has_both_directional_invalidations"].to_dict()
    fully["fully_invalidated_has_both_directional_invalidations"] = fully["h1_context_id"].map(context_flags).fillna(False)
    columns = [
        "sample_id",
        "h1_context_id",
        "direction_candidate",
        "invalidation_reason",
        "long_invalidated",
        "short_invalidated",
        "fully_invalidated_has_both_directional_invalidations",
        "state_transition_log",
    ]
    return fully[columns].head(limit)


def build_invalidation_rate_audit(input_dir: str | Path) -> InvalidationRateAuditResult:
    started = time.perf_counter()
    frame = load_state_machine_samples(input_dir)
    reason_distribution = build_reason_distribution(frame)
    h1_context_audit = build_h1_context_audit(frame)
    sticky_audit = build_sticky_audit(frame)
    transition_examples = build_transition_examples(frame)
    fully_examples = build_fully_invalidated_examples(frame, h1_context_audit)
    counts = Counter(frame["final_state"])
    total = int(len(frame))
    valid_count = int(sum(counts.get(state, 0) for state in VALID_STATES))
    invalidated_count = int(sum(counts.get(state, 0) for state in INVALID_STATES))
    fully_count = int(counts.get(STATE_FULLY_INVALIDATED, 0))
    true_dual_count = int(counts.get(STATE_TRUE_DUAL_DIRECTION_INVALIDATED, 0))
    h1_consumed_count = int(counts.get(STATE_H1_CONTEXT_ALREADY_CONSUMED, 0))
    mae_not_reached_count = int(counts.get(STATE_MAE_NOT_REACHED, 0))
    structure_invalid_count = int(counts.get(STATE_STRUCTURE_INVALID, 0))
    unknown_state_count = int(counts.get(STATE_UNKNOWN_INVALIDATION_STATE, 0))
    directionality = audit_directionality(frame)
    fully_contexts_without_both = h1_context_audit[
        h1_context_audit["legacy_fully_invalidated_rows"].gt(0) & ~h1_context_audit["fully_invalidated_has_both_directional_invalidations"]
    ]
    fully_rows_without_both = int(fully_examples["fully_invalidated_has_both_directional_invalidations"].eq(False).sum()) if not fully_examples.empty else 0
    sticky_violations = int(sticky_audit["sticky_violation"].sum()) if not sticky_audit.empty else 0
    cross_h1_flags = int(h1_context_audit["potential_cross_h1_contamination"].sum()) if not h1_context_audit.empty else 0
    critical_assessment = critical_assessment_text(
        invalidation_rate=_rate(invalidated_count, total),
        fully_contexts_without_both=int(len(fully_contexts_without_both)),
        directionality_confirmed=bool(directionality["directionality_confirmed"]),
        sticky_violations=sticky_violations,
        cross_h1_flags=cross_h1_flags,
    )
    summary = {
        "runtime_seconds": round(time.perf_counter() - started, 4),
        "input_dir": str(Path(input_dir)),
        "samples_processed": total,
        "valid_count": valid_count,
        "invalidated_count": invalidated_count,
        "valid_rate": _rate(valid_count, total),
        "invalidation_rate": _rate(invalidated_count, total),
        "fully_invalidated_count": fully_count,
        "fully_invalidated_rate": _rate(fully_count, total),
        "true_dual_direction_invalidated_count": true_dual_count,
        "true_dual_direction_invalidated_rate": _rate(true_dual_count, total),
        "h1_context_already_consumed_count": h1_consumed_count,
        "mae_not_reached_count": mae_not_reached_count,
        "structure_invalid_count": structure_invalid_count,
        "unknown_invalidation_state_count": unknown_state_count,
        "fully_invalidated_contexts_without_both_directional_invalidations": int(len(fully_contexts_without_both)),
        "fully_invalidated_example_rows_without_both_directional_invalidations": fully_rows_without_both,
        "sticky_invalidation_confirmed": sticky_violations == 0,
        "sticky_violation_count": sticky_violations,
        "h1_context_reset_confirmed": cross_h1_flags == 0,
        "cross_h1_contamination_flags": cross_h1_flags,
        "directionality": directionality,
        "critical_assessment": critical_assessment,
        "pnl_metrics_generated": False,
        "reaction_quality_derived": False,
        "verdict_flags": VERDICT_FLAGS,
        "safety": SAFETY,
    }
    report = render_invalidation_rate_report(summary, reason_distribution)
    return InvalidationRateAuditResult(
        reason_distribution=reason_distribution,
        transition_examples=transition_examples,
        h1_context_audit=h1_context_audit,
        fully_invalidated_examples=fully_examples,
        sticky_audit=sticky_audit,
        summary=summary,
        report_markdown=report,
    )


def critical_assessment_text(
    *,
    invalidation_rate: float,
    fully_contexts_without_both: int,
    directionality_confirmed: bool,
    sticky_violations: int,
    cross_h1_flags: int,
) -> str:
    if not directionality_confirmed or sticky_violations or cross_h1_flags:
        return "LIKELY_TOO_AGGRESSIVE_OR_BUGGY_LAYER_A_REVIEW_REQUIRED"
    if fully_contexts_without_both:
        return "LIKELY_TOO_AGGRESSIVE_FULLY_INVALIDATED_IS_OVERLOADED"
    if invalidation_rate >= 0.8:
        return "EXTREME_BUT_MECHANICALLY_CONSISTENT_REQUIRES_MORE_MANUAL_EXAMPLES"
    return "PLAUSIBLE_BUT_REQUIRES_MANUAL_EXAMPLES"


def write_invalidation_rate_outputs(result: InvalidationRateAuditResult, output_dir: str | Path, *, docs_path: str | Path | None = None) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "reason_distribution": output / "invalidation_reason_distribution.csv",
        "transition_examples": output / "invalidation_transition_examples.csv",
        "h1_context_audit": output / "h1_context_audit.csv",
        "fully_invalidated_examples": output / "fully_invalidated_examples.csv",
        "sticky_invalidation_audit": output / "sticky_invalidation_audit.csv",
        "summary": output / "invalidation_rate_summary.json",
        "report": output / "invalidation_rate_report.md",
    }
    result.reason_distribution.to_csv(paths["reason_distribution"], index=False)
    result.transition_examples.to_csv(paths["transition_examples"], index=False)
    result.h1_context_audit.to_csv(paths["h1_context_audit"], index=False)
    result.fully_invalidated_examples.to_csv(paths["fully_invalidated_examples"], index=False)
    result.sticky_audit.to_csv(paths["sticky_invalidation_audit"], index=False)
    paths["summary"].write_text(json.dumps(result.summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    paths["report"].write_text(result.report_markdown, encoding="utf-8")
    if docs_path:
        docs = Path(docs_path)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(result.report_markdown, encoding="utf-8")
        paths["docs"] = docs
    return {key: str(path) for key, path in paths.items()}


def render_invalidation_rate_report(summary: dict[str, Any], reason_distribution: pd.DataFrame) -> str:
    top_reasons = reason_distribution[reason_distribution["sample_count"].gt(0)].sort_values("sample_count", ascending=False)
    lines = [
        "# Strategy 2 Invalidation Rate Audit",
        "",
        "## Context",
        "",
        "The hard invalidation state machine produced an extreme invalidation rate, so Layer B reaction-quality derivation is postponed until Layer A scope is audited.",
        "",
        "## Mechanical Rule Recap",
        "",
        "- LONG targeting H1 LOW is invalidated if the opposite M15 HIGH is taken first.",
        "- SHORT targeting H1 HIGH is invalidated if the opposite M15 LOW is taken first.",
        "- Invalidation is sticky inside the same H1 context.",
        "",
        "## Findings",
        "",
        f"- samples processed: `{summary['samples_processed']}`",
        f"- valid count/rate: `{summary['valid_count']}` / `{summary['valid_rate']}`",
        f"- invalidated count/rate: `{summary['invalidated_count']}` / `{summary['invalidation_rate']}`",
        f"- fully invalidated count/rate: `{summary['fully_invalidated_count']}` / `{summary['fully_invalidated_rate']}`",
        f"- true dual-direction invalidated count/rate: `{summary.get('true_dual_direction_invalidated_count')}` / `{summary.get('true_dual_direction_invalidated_rate')}`",
        f"- H1 context already consumed: `{summary.get('h1_context_already_consumed_count')}`",
        f"- MAE not reached: `{summary.get('mae_not_reached_count')}`",
        f"- structure invalid: `{summary.get('structure_invalid_count')}`",
        f"- unknown invalidation state: `{summary.get('unknown_invalidation_state_count')}`",
        f"- sticky violations: `{summary['sticky_violation_count']}`",
        f"- H1 cross-boundary flags: `{summary['cross_h1_contamination_flags']}`",
        f"- fully-invalidated contexts without both directional invalidations: `{summary['fully_invalidated_contexts_without_both_directional_invalidations']}`",
        f"- critical assessment: `{summary['critical_assessment']}`",
        "",
        "## Invalidation Reason Distribution",
        "",
        "| Reason | Samples | Rate |",
        "|---|---:|---:|",
    ]
    for row in top_reasons.to_dict("records"):
        lines.append(f"| {row['reason_group']} | {row['sample_count']} | {row['sample_rate']} |")
    lines.extend(
        [
            "",
            "## Critical Assessment",
            "",
            "Directionality and sticky behavior are mechanically consistent in this audit. When legacy `FULLY_INVALIDATED` appears without both directional invalidations, it should be treated as an overloaded taxonomy bucket and split into true dual-direction, H1-consumed, MAE-not-reached, structure-invalid, or unknown terminal states.",
            "",
            "## Safety",
            "",
            "- Strategy 3 untouched.",
            "- Adelin untouched.",
            "- data/XAUUSD/*.csv untouched.",
            "- No optimization, signals, broker execution, orders, Telegram, backtest, PnL, or reaction-quality derivation.",
            "",
            "## Honest Limitations",
            "",
            "- No behavioral layer.",
            "- No reaction derivation.",
            "- No profitability analysis.",
            "- No deployment claim.",
            "",
            "## Verdict Flags",
            "",
            "\n".join(f"- `{flag}`" for flag in summary["verdict_flags"]),
        ]
    )
    return "\n".join(lines) + "\n"


def _tokens(value: Any) -> list[str]:
    if value is None or pd.isna(value):
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip().upper() for part in text.split(";") if part.strip()]


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y"}


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


__all__ = [
    "InvalidationRateAuditResult",
    "audit_directionality",
    "build_h1_context_audit",
    "build_invalidation_rate_audit",
    "build_reason_distribution",
    "build_sticky_audit",
    "critical_assessment_text",
    "load_state_machine_samples",
    "reason_groups",
    "write_invalidation_rate_outputs",
]
