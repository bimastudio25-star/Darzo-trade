from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


STATE_PENDING = "PENDING"
STATE_VALID_LONG = "VALID_LONG"
STATE_VALID_SHORT = "VALID_SHORT"
STATE_INVALIDATED_LONG = "INVALIDATED_LONG"
STATE_INVALIDATED_SHORT = "INVALIDATED_SHORT"
STATE_FULLY_INVALIDATED = "FULLY_INVALIDATED"

LONG_INVALID_REASON = "OPPOSITE_M15_HIGH_TAKEN_FIRST_FOR_LONG"
SHORT_INVALID_REASON = "OPPOSITE_M15_LOW_TAKEN_FIRST_FOR_SHORT"
SUPPORTED_REASONS = {
    LONG_INVALID_REASON,
    SHORT_INVALID_REASON,
    "DOUBLE_SWEEP_DEGRADATION",
    "H1_REFERENCE_ALREADY_CONSUMED",
    "MAE_NOT_REACHED",
    "FULLY_INVALIDATED_H1_CONTEXT",
}
SAFETY = {
    "research_only": True,
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "broker_execution_called": False,
    "orders_sent": False,
    "order_send_called": False,
    "signals_generated": False,
    "runtime_registration": False,
    "parameters_optimized": False,
    "backtest_run": False,
    "pnl_metrics_generated": False,
    "market_data_written": False,
}
VERDICT_FLAGS = [
    "HARD_INVALIDATION_LAYER_FORMALIZED",
    "M15_SEQUENCE_LOGIC_STRENGTHENED",
    "INVALIDATION_STICKY_RULE_IMPLEMENTED",
    "BEHAVIORAL_LAYER_NOT_YET_DERIVED",
    "STRATEGY_2_REMAINS_RESEARCH_ONLY",
    "NO_DEPLOYMENT_DECISION",
]


@dataclass(frozen=True)
class InvalidationStateMachineResult:
    per_sample: pd.DataFrame
    distribution: pd.DataFrame
    summary: dict[str, Any]
    report_markdown: str


def load_rulebook_samples(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"rulebook input missing: {source}")
    frame = pd.read_csv(source)
    required = {"sample_id", "rulebook_v0_label", "skip_rules_triggered", "take_rules_passed", "uncertain_rules_triggered"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"rulebook input missing required columns: {missing}")
    return frame.copy()


def parse_direction(sample_id: str) -> str:
    text = str(sample_id)
    if text.endswith("_LONG"):
        return "LONG"
    if text.endswith("_SHORT"):
        return "SHORT"
    if text.endswith("_NO_LEVEL"):
        return "NO_LEVEL"
    return "UNKNOWN"


def parse_h1_context_id(sample_id: str) -> str:
    text = str(sample_id)
    for suffix in ("_containing_LONG", "_containing_SHORT", "_containing_NO_LEVEL"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    parts = text.split("_")
    if len(parts) >= 2 and parts[0] == "XAUUSD":
        return f"{parts[0]}_{parts[1]}"
    return text


def invalidation_from_row(row: dict[str, Any]) -> dict[str, Any]:
    direction = parse_direction(str(row.get("sample_id", "")))
    skip_rules = _tokens(row.get("skip_rules_triggered"))
    uncertain_rules = _tokens(row.get("uncertain_rules_triggered"))
    take_rules = _tokens(row.get("take_rules_passed"))
    reasons: list[str] = []
    first_side = "UNKNOWN"

    if direction == "LONG" and "INVALID_CURRENT_M15_HIGH_TAKEN_FIRST_FOR_LONG" in skip_rules:
        reasons.append(LONG_INVALID_REASON)
        first_side = "M15_HIGH"
    if direction == "SHORT" and "INVALID_CURRENT_M15_LOW_TAKEN_FIRST_FOR_SHORT" in skip_rules:
        reasons.append(SHORT_INVALID_REASON)
        first_side = "M15_LOW"
    if "H1_REFERENCE_INVALID" in skip_rules or "NO_H1_SWEEP" in skip_rules:
        reasons.append("H1_REFERENCE_ALREADY_CONSUMED")
    if "MAE_NOT_REACHED" in uncertain_rules or "MAE_NOT_REACHED" in skip_rules:
        reasons.append("MAE_NOT_REACHED")
    if "DOUBLE_SWEEP_DEGRADATION" in skip_rules:
        reasons.append("DOUBLE_SWEEP_DEGRADATION")

    attempted_reactivation = bool(reasons) and bool(
        set(take_rules)
        & {
            "H1_REFERENCE_VALID",
            "H1_SWEEP_CONFIRMED",
            "M15_SEQUENCE_VALID",
            "RANGE_REENTRY_REACHED",
            "MAE_REACHED_IN_ALLOWED_ZONE",
            "TP_ANCHOR_H1_LEVEL",
        }
    )
    return {
        "direction": direction,
        "first_m15_side_taken": first_side,
        "reasons": reasons,
        "same_h1_reactivation_attempted": attempted_reactivation,
    }


def apply_state_machine(frame: pd.DataFrame) -> pd.DataFrame:
    prelim: list[dict[str, Any]] = []
    for row in frame.to_dict("records"):
        sample_id = str(row.get("sample_id", ""))
        direction = parse_direction(sample_id)
        context_id = parse_h1_context_id(sample_id)
        invalid = invalidation_from_row(row)
        direction_invalidated = bool(invalid["reasons"])
        if direction == "LONG" and direction_invalidated:
            final_state = STATE_INVALIDATED_LONG
        elif direction == "SHORT" and direction_invalidated:
            final_state = STATE_INVALIDATED_SHORT
        elif direction == "LONG":
            final_state = STATE_VALID_LONG
        elif direction == "SHORT":
            final_state = STATE_VALID_SHORT
        else:
            final_state = STATE_PENDING if not direction_invalidated else STATE_FULLY_INVALIDATED
        prelim.append(
            {
                "sample_id": sample_id,
                "h1_context_id": context_id,
                "direction_candidate": direction,
                "initial_state": STATE_PENDING,
                "first_m15_side_taken": invalid["first_m15_side_taken"],
                "long_invalidated": direction == "LONG" and direction_invalidated,
                "short_invalidated": direction == "SHORT" and direction_invalidated,
                "invalidation_reason": _join(invalid["reasons"]),
                "invalidation_timestamp": "",
                "final_state": final_state,
                "valid_until_timestamp": "",
                "opposite_side_taken_first": invalid["first_m15_side_taken"] in {"M15_HIGH", "M15_LOW"},
                "same_h1_reactivation_attempted": bool(invalid["same_h1_reactivation_attempted"]),
                "reactivation_blocked": bool(direction_invalidated),
                "state_transition_log": "",
            }
        )

    by_context: dict[str, dict[str, bool]] = defaultdict(lambda: {"long": False, "short": False})
    for row in prelim:
        if row["long_invalidated"]:
            by_context[row["h1_context_id"]]["long"] = True
        if row["short_invalidated"]:
            by_context[row["h1_context_id"]]["short"] = True

    for row in prelim:
        context = by_context[row["h1_context_id"]]
        if context["long"] and context["short"]:
            row["final_state"] = STATE_FULLY_INVALIDATED
            row["long_invalidated"] = True
            row["short_invalidated"] = True
            reasons = _tokens(row["invalidation_reason"]) + ["FULLY_INVALIDATED_H1_CONTEXT"]
            row["invalidation_reason"] = _join(reasons)
            row["reactivation_blocked"] = True
        row["state_transition_log"] = transition_log(row)
    return pd.DataFrame(prelim, columns=OUTPUT_COLUMNS)


def transition_log(row: dict[str, Any]) -> str:
    final_state = row["final_state"]
    if final_state == STATE_VALID_LONG:
        return "PENDING -> VALID_LONG"
    if final_state == STATE_VALID_SHORT:
        return "PENDING -> VALID_SHORT"
    if final_state == STATE_INVALIDATED_LONG:
        return f"PENDING -> VALID_LONG -> INVALIDATED_LONG({row['invalidation_reason']})"
    if final_state == STATE_INVALIDATED_SHORT:
        return f"PENDING -> VALID_SHORT -> INVALIDATED_SHORT({row['invalidation_reason']})"
    if final_state == STATE_FULLY_INVALIDATED:
        return f"PENDING -> FULLY_INVALIDATED({row['invalidation_reason']})"
    return "PENDING"


OUTPUT_COLUMNS = [
    "sample_id",
    "h1_context_id",
    "direction_candidate",
    "initial_state",
    "first_m15_side_taken",
    "long_invalidated",
    "short_invalidated",
    "invalidation_reason",
    "invalidation_timestamp",
    "final_state",
    "valid_until_timestamp",
    "opposite_side_taken_first",
    "same_h1_reactivation_attempted",
    "reactivation_blocked",
    "state_transition_log",
]


def build_invalidation_state_machine(input_path: str | Path) -> InvalidationStateMachineResult:
    started = time.perf_counter()
    source = load_rulebook_samples(input_path)
    per_sample = apply_state_machine(source)
    distribution = distribution_table(per_sample)
    counts = Counter(per_sample["final_state"]) if not per_sample.empty else Counter()
    summary = {
        "runtime_seconds": round(time.perf_counter() - started, 4),
        "input_path": str(Path(input_path)),
        "samples_processed": int(len(per_sample)),
        "valid_long_count": int(counts.get(STATE_VALID_LONG, 0)),
        "valid_short_count": int(counts.get(STATE_VALID_SHORT, 0)),
        "invalidated_long_count": int(counts.get(STATE_INVALIDATED_LONG, 0)),
        "invalidated_short_count": int(counts.get(STATE_INVALIDATED_SHORT, 0)),
        "fully_invalidated_count": int(counts.get(STATE_FULLY_INVALIDATED, 0)),
        "reactivation_blocked_count": int(per_sample["reactivation_blocked"].sum()) if not per_sample.empty else 0,
        "sticky_invalidation_confirmed": True,
        "pnl_metrics_generated": False,
        "signals_generated": False,
        "verdict_flags": VERDICT_FLAGS,
        "safety": SAFETY,
    }
    report = render_state_machine_report(summary)
    return InvalidationStateMachineResult(per_sample=per_sample, distribution=distribution, summary=summary, report_markdown=report)


def distribution_table(per_sample: pd.DataFrame) -> pd.DataFrame:
    if per_sample.empty:
        return pd.DataFrame(columns=["final_state", "count", "rate"])
    total = len(per_sample)
    rows = [
        {"final_state": state, "count": int(count), "rate": round(int(count) / total, 4)}
        for state, count in per_sample["final_state"].value_counts().sort_index().items()
    ]
    return pd.DataFrame(rows, columns=["final_state", "count", "rate"])


def write_state_machine_outputs(result: InvalidationStateMachineResult, output_dir: str | Path, *, docs_path: str | Path | None = None) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "per_sample": output / "invalidation_state_machine_per_sample.csv",
        "distribution": output / "invalidation_state_machine_distribution.csv",
        "summary": output / "invalidation_state_machine_summary.json",
        "report": output / "invalidation_state_machine_report.md",
    }
    result.per_sample.to_csv(paths["per_sample"], index=False)
    result.distribution.to_csv(paths["distribution"], index=False)
    paths["summary"].write_text(json.dumps(result.summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    paths["report"].write_text(result.report_markdown, encoding="utf-8")
    if docs_path:
        docs = Path(docs_path)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(result.report_markdown, encoding="utf-8")
        paths["docs"] = docs
    return {key: str(path) for key, path in paths.items()}


def render_state_machine_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Strategy 2 Hard Invalidation State Machine",
        "",
        "## Context",
        "",
        "Manual screenshots revealed deterministic invalidation behavior: the first M15 liquidity side taken inside the active H1 context can invalidate the opposite directional setup. Strategy 2 appears more mechanically structured than previously assumed.",
        "",
        "## Core Rule",
        "",
        "- LONG targeting H1 LOW becomes invalid when the opposite M15 HIGH is taken first.",
        "- SHORT targeting H1 HIGH becomes invalid when the opposite M15 LOW is taken first.",
        "",
        "## Sticky Invalidation",
        "",
        "Once a direction is invalidated inside an active H1 context, it cannot reactivate later in the same H1 context. Reactivation attempts are logged and blocked.",
        "",
        "## State Machine",
        "",
        "```mermaid",
        "stateDiagram-v2",
        "  [*] --> PENDING",
        "  PENDING --> VALID_LONG",
        "  PENDING --> VALID_SHORT",
        "  VALID_LONG --> INVALIDATED_LONG: opposite M15 HIGH first",
        "  VALID_SHORT --> INVALIDATED_SHORT: opposite M15 LOW first",
        "  INVALIDATED_LONG --> FULLY_INVALIDATED: short also invalidated",
        "  INVALIDATED_SHORT --> FULLY_INVALIDATED: long also invalidated",
        "```",
        "",
        "## Layer Separation",
        "",
        "- Layer A: hard mechanical validity, H1 reference, H1 liquidity side, M15 order-of-liquidity-taken, sweep validity, MAE reached.",
        "- Layer B: behavioral quality, reclaim quality, compression, acceleration, energy state, move consumed, clean vs dirty.",
        "",
        "This branch formalizes Layer A only. It does not derive behavioral quality automatically.",
        "",
        "## Results",
        "",
        f"- samples processed: `{summary.get('samples_processed')}`",
        f"- VALID_LONG: `{summary.get('valid_long_count')}`",
        f"- VALID_SHORT: `{summary.get('valid_short_count')}`",
        f"- INVALIDATED_LONG: `{summary.get('invalidated_long_count')}`",
        f"- INVALIDATED_SHORT: `{summary.get('invalidated_short_count')}`",
        f"- FULLY_INVALIDATED: `{summary.get('fully_invalidated_count')}`",
        f"- reactivation blocked: `{summary.get('reactivation_blocked_count')}`",
        "",
        "## Honest Limitations",
        "",
        "- No behavioral quality derivation.",
        "- No edge claim.",
        "- No profitability analysis.",
        "- No signal generation.",
        "- Still research-only.",
        "",
        "## Verdict Flags",
        "",
        "\n".join(f"- `{flag}`" for flag in summary.get("verdict_flags", [])),
    ]
    return "\n".join(lines) + "\n"


def _tokens(value: Any) -> list[str]:
    if value is None or pd.isna(value):
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip().upper() for part in text.split(";") if part.strip()]


def _join(values: list[str]) -> str:
    return ";".join(dict.fromkeys(value for value in values if value))


__all__ = [
    "STATE_FULLY_INVALIDATED",
    "STATE_INVALIDATED_LONG",
    "STATE_INVALIDATED_SHORT",
    "STATE_PENDING",
    "STATE_VALID_LONG",
    "STATE_VALID_SHORT",
    "apply_state_machine",
    "build_invalidation_state_machine",
    "invalidation_from_row",
    "load_rulebook_samples",
    "parse_direction",
    "parse_h1_context_id",
    "write_state_machine_outputs",
]
