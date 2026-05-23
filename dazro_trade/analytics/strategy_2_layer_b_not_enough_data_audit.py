from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from dazro_trade.analytics.strategy_2_layer_b_reaction_quality import load_ohlc_data


NED_DESCRIPTOR = "NOT_ENOUGH_DATA"
REENTRY_NOT_REACHED_DESCRIPTOR = "NO_ENTRY_REENTRY_NOT_REACHED"
REENTRY_NOT_REACHED_FUNNEL_STATE = "REENTRY_NOT_REACHED"
VALID_STATES = {"VALID_LONG", "VALID_SHORT"}
CAUSE_EDGE_OF_DATASET = "EDGE_OF_DATASET"
CAUSE_WEEKEND_OR_MARKET_GAP = "WEEKEND_OR_MARKET_GAP"
CAUSE_MISSING_CANDLES = "MISSING_M1_M5_CANDLES"
CAUSE_WINDOW_TOO_SHORT = "WINDOW_TOO_SHORT"
CAUSE_TIMESTAMP_ALIGNMENT = "TIMESTAMP_ALIGNMENT_ISSUE"
CAUSE_UNKNOWN = "UNKNOWN_CAUSE"
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
    "reaction_rule_changed": False,
    "manual_validation_pack_generated": False,
    "market_data_written": False,
}
VERDICT_FLAGS = [
    "LAYER_B_NOT_ENOUGH_DATA_AUDITED",
    "NOT_ENOUGH_DATA_CLUSTERING_ANALYZED",
    "NO_REACTION_RULE_CHANGE",
    "NO_PERFORMANCE_CLAIM",
    "STRATEGY_2_REMAINS_RESEARCH_ONLY",
    "NO_DEPLOYMENT_DECISION",
]


@dataclass(frozen=True)
class NotEnoughDataAuditResult:
    not_enough_data_samples: pd.DataFrame
    by_direction: pd.DataFrame
    by_hour: pd.DataFrame
    by_session: pd.DataFrame
    by_weekday: pd.DataFrame
    by_h1_context: pd.DataFrame
    cause_breakdown: pd.DataFrame
    comparison: pd.DataFrame
    summary: dict[str, Any]
    report_markdown: str


def load_layer_b_features(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Layer B features input missing: {source}")
    frame = pd.read_csv(source)
    required = {
        "sample_id",
        "h1_context_id",
        "direction_candidate",
        "layer_a_state",
        "layer_b_eligible",
        "reaction_descriptor",
        "layer_b_candidate_label",
        "sweep_timestamp",
        "decision_time",
        "data_window_start",
        "data_window_end",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Layer B features input missing required columns: {missing}")
    return normalize_layer_b_frame(frame)


def normalize_layer_b_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["layer_b_eligible"] = out["layer_b_eligible"].map(_boolish)
    if "layer_a_valid" not in out.columns:
        out["layer_a_valid"] = out["layer_a_state"].astype(str).isin(VALID_STATES)
    else:
        out["layer_a_valid"] = out["layer_a_valid"].map(_boolish)
    if "layer_b_measurable" not in out.columns:
        out["layer_b_measurable"] = out["layer_b_eligible"]
    else:
        out["layer_b_measurable"] = out["layer_b_measurable"].map(_boolish)
    if "layer_b_funnel_state" not in out.columns:
        out["layer_b_funnel_state"] = out["reaction_descriptor"].map(
            lambda value: "NOT_ENOUGH_DATA" if str(value) == NED_DESCRIPTOR else "MEASURABLE_REACTION_WINDOW"
        )
    for column in ["sample_id", "h1_context_id", "direction_candidate", "layer_a_state", "reaction_descriptor", "layer_b_candidate_label"]:
        out[column] = out[column].fillna("").astype(str)
    for column in ["sweep_timestamp", "decision_time", "data_window_start", "data_window_end"]:
        out[f"{column}_parsed"] = pd.to_datetime(out[column], utc=True, errors="coerce")
    return out


def build_not_enough_data_audit(
    input_path: str | Path,
    *,
    state_split_path: str | Path | None = None,
    data_dir: str | Path = "data",
    symbol: str = "XAUUSD",
) -> NotEnoughDataAuditResult:
    started = time.perf_counter()
    frame = load_layer_b_features(input_path)
    if state_split_path:
        validate_state_split_path(state_split_path)
    ohlc = load_ohlc_data(data_dir, symbol, "M1")
    dataset_start = ohlc["time"].min() if not ohlc.empty else pd.NaT
    dataset_end = ohlc["time"].max() if not ohlc.empty else pd.NaT
    enriched = add_audit_columns(frame, ohlc=ohlc, dataset_start=dataset_start, dataset_end=dataset_end)
    layer_a_valid = enriched[enriched["layer_a_valid"]].copy()
    measurable = enriched[enriched["layer_b_eligible"]].copy()
    reentry_not_reached = layer_a_valid[layer_a_valid["layer_b_funnel_state"].eq(REENTRY_NOT_REACHED_FUNNEL_STATE)].copy()
    ned = measurable[measurable["reaction_descriptor"].eq(NED_DESCRIPTOR)].copy()
    available = measurable[~measurable["reaction_descriptor"].eq(NED_DESCRIPTOR)].copy()
    by_direction = grouped_rate_table(layer_a_valid, ned, "direction_candidate", "direction_candidate")
    by_hour = grouped_rate_table(layer_a_valid, ned, "hour_utc", "hour_utc")
    by_session = grouped_rate_table(layer_a_valid, ned, "session_bucket", "session_bucket")
    by_weekday = grouped_rate_table(layer_a_valid, ned, "weekday", "weekday")
    by_h1_context = grouped_rate_table(layer_a_valid, ned, "h1_context_id", "h1_context_id").sort_values(
        ["not_enough_data_count", "not_enough_data_rate"], ascending=[False, False]
    )
    cause_breakdown = cause_distribution(ned)
    comparison = available_comparison(ned, available)
    critical = critical_conclusion(ned, layer_a_valid, cause_breakdown, reentry_not_reached_count=len(reentry_not_reached))
    summary = {
        "runtime_seconds": round(time.perf_counter() - started, 4),
        "input_path": str(Path(input_path)),
        "state_split_path": str(Path(state_split_path)) if state_split_path else "",
        "data_dir": str(Path(data_dir)),
        "symbol": symbol,
        "samples_processed": int(len(frame)),
        "original_layer_a_valid_samples": int(len(layer_a_valid)),
        "layer_b_eligible_samples": int(len(measurable)),
        "layer_b_measurable_samples": int(len(measurable)),
        "reentry_not_reached_count": int(len(reentry_not_reached)),
        "not_enough_data_count": int(len(ned)),
        "not_enough_data_rate": _rate(len(ned), len(measurable)),
        "descriptor_distribution": dict(sorted(Counter(layer_a_valid["reaction_descriptor"]).items())),
        "measurable_descriptor_distribution": dict(sorted(Counter(measurable["reaction_descriptor"]).items())),
        "not_enough_data_by_direction": _records_by_key(by_direction, "direction_candidate"),
        "not_enough_data_by_session": _records_by_key(by_session, "session_bucket"),
        "not_enough_data_by_weekday": _records_by_key(by_weekday, "weekday"),
        "top_h1_contexts": by_h1_context.head(10).to_dict("records"),
        "likely_cause_breakdown": dict(sorted(Counter(ned["likely_not_enough_data_cause"]).items())),
        "critical_conclusion": critical,
        "recommended_next_step": recommended_next_step(critical),
        "reaction_rule_changed": False,
        "manual_validation_pack_generated": False,
        "pnl_metrics_generated": False,
        "safety": SAFETY,
        "verdict_flags": VERDICT_FLAGS,
    }
    return NotEnoughDataAuditResult(
        not_enough_data_samples=ned[NED_COLUMNS].copy(),
        by_direction=by_direction,
        by_hour=by_hour,
        by_session=by_session,
        by_weekday=by_weekday,
        by_h1_context=by_h1_context,
        cause_breakdown=cause_breakdown,
        comparison=comparison,
        summary=summary,
        report_markdown=render_audit_report(summary, by_direction, by_session, by_weekday, by_h1_context, cause_breakdown, comparison),
    )


def validate_state_split_path(path: str | Path) -> None:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"state split input missing: {source}")


def add_audit_columns(
    frame: pd.DataFrame,
    *,
    ohlc: pd.DataFrame,
    dataset_start: pd.Timestamp | pd.NaT,
    dataset_end: pd.Timestamp | pd.NaT,
) -> pd.DataFrame:
    out = frame.copy()
    event_ts = out["decision_time_parsed"].where(out["decision_time_parsed"].notna(), out["sweep_timestamp_parsed"])
    event_ts = event_ts.where(event_ts.notna(), out["data_window_start_parsed"])
    out["event_timestamp"] = event_ts
    out["hour_utc"] = out["event_timestamp"].dt.hour
    out["weekday"] = out["event_timestamp"].dt.day_name().fillna("UNKNOWN")
    out["session_bucket"] = out["hour_utc"].map(session_bucket)
    out["is_weekend_or_market_gap"] = out["event_timestamp"].map(is_weekend_or_market_gap)
    out["near_dataset_start"] = out["event_timestamp"].map(lambda value: near_boundary(value, dataset_start))
    out["near_dataset_end"] = out["event_timestamp"].map(lambda value: near_boundary(value, dataset_end))
    counts = [
        candle_window_counts(row, ohlc)
        for row in out[["data_window_start_parsed", "data_window_end_parsed"]].to_dict("records")
    ]
    out["available_candle_count"] = [item["available_candle_count"] for item in counts]
    out["expected_candle_count"] = [item["expected_candle_count"] for item in counts]
    out["missing_candle_count"] = [item["missing_candle_count"] for item in counts]
    out["data_window_seconds"] = [item["data_window_seconds"] for item in counts]
    out["likely_not_enough_data_cause"] = [
        classify_likely_cause(row)
        for row in out.to_dict("records")
    ]
    out["audit_notes"] = [audit_notes(row) for row in out.to_dict("records")]
    return out


def session_bucket(hour: Any) -> str:
    if pd.isna(hour):
        return "UNKNOWN"
    hour_int = int(hour)
    if 0 <= hour_int <= 7:
        return "ASIA"
    if 8 <= hour_int <= 12:
        return "LONDON"
    if 13 <= hour_int <= 20:
        return "NY"
    return "OFF_HOURS"


def is_weekend_or_market_gap(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    ts = pd.Timestamp(value)
    if ts.weekday() >= 5:
        return True
    if ts.weekday() == 4 and ts.hour >= 21:
        return True
    if ts.weekday() == 0 and ts.hour < 1:
        return True
    return False


def near_boundary(value: Any, boundary: Any, *, seconds: int = 3600) -> bool:
    if value is None or boundary is None or pd.isna(value) or pd.isna(boundary):
        return False
    return abs((pd.Timestamp(value) - pd.Timestamp(boundary)).total_seconds()) <= seconds


def candle_window_counts(row: dict[str, Any], ohlc: pd.DataFrame) -> dict[str, Any]:
    start = row.get("data_window_start_parsed")
    end = row.get("data_window_end_parsed")
    if start is None or end is None or pd.isna(start) or pd.isna(end) or end < start:
        return {
            "available_candle_count": 0,
            "expected_candle_count": 0,
            "missing_candle_count": 0,
            "data_window_seconds": None,
        }
    seconds = int((pd.Timestamp(end) - pd.Timestamp(start)).total_seconds())
    expected = int(seconds // 60) + 1
    available = int(((ohlc["time"] >= start) & (ohlc["time"] <= end)).sum()) if not ohlc.empty else 0
    return {
        "available_candle_count": available,
        "expected_candle_count": expected,
        "missing_candle_count": max(0, expected - available),
        "data_window_seconds": seconds,
    }


def classify_likely_cause(row: dict[str, Any]) -> str:
    if _boolish(row.get("near_dataset_start")) or _boolish(row.get("near_dataset_end")):
        return CAUSE_EDGE_OF_DATASET
    if _boolish(row.get("is_weekend_or_market_gap")):
        return CAUSE_WEEKEND_OR_MARKET_GAP
    if pd.isna(row.get("data_window_start_parsed")) or pd.isna(row.get("data_window_end_parsed")):
        return CAUSE_WINDOW_TOO_SHORT
    if int(row.get("expected_candle_count") or 0) <= 1:
        return CAUSE_WINDOW_TOO_SHORT
    if int(row.get("missing_candle_count") or 0) > 0:
        return CAUSE_MISSING_CANDLES
    if pd.isna(row.get("event_timestamp")):
        return CAUSE_TIMESTAMP_ALIGNMENT
    return CAUSE_UNKNOWN


def audit_notes(row: dict[str, Any]) -> str:
    notes: list[str] = []
    if row.get("reaction_descriptor") == NED_DESCRIPTOR:
        notes.append("Layer B descriptor is NOT_ENOUGH_DATA")
    if pd.isna(row.get("decision_time_parsed")):
        notes.append("decision_time missing")
    if pd.isna(row.get("data_window_end_parsed")):
        notes.append("data_window_end missing")
    if int(row.get("missing_candle_count") or 0) > 0:
        notes.append("missing candles inside window")
    if _boolish(row.get("near_dataset_start")):
        notes.append("near dataset start")
    if _boolish(row.get("near_dataset_end")):
        notes.append("near dataset end")
    if _boolish(row.get("is_weekend_or_market_gap")):
        notes.append("weekend or market gap proximity")
    return ";".join(notes)


def grouped_rate_table(eligible: pd.DataFrame, ned: pd.DataFrame, group_col: str, label_col: str) -> pd.DataFrame:
    total_counts = eligible.groupby(group_col, dropna=False).size().rename("eligible_count")
    ned_counts = ned.groupby(group_col, dropna=False).size().rename("not_enough_data_count")
    table = pd.concat([total_counts, ned_counts], axis=1).fillna(0).reset_index()
    table = table.rename(columns={group_col: label_col})
    table["eligible_count"] = table["eligible_count"].astype(int)
    table["not_enough_data_count"] = table["not_enough_data_count"].astype(int)
    table["not_enough_data_rate"] = [
        _rate(ned_count, total)
        for ned_count, total in zip(table["not_enough_data_count"], table["eligible_count"])
    ]
    return table.sort_values([label_col], kind="stable").reset_index(drop=True)


def cause_distribution(ned: pd.DataFrame) -> pd.DataFrame:
    total = len(ned)
    rows = [
        {"likely_not_enough_data_cause": cause, "count": int(count), "rate": _rate(int(count), total)}
        for cause, count in sorted(Counter(ned["likely_not_enough_data_cause"]).items())
    ]
    return pd.DataFrame(rows, columns=["likely_not_enough_data_cause", "count", "rate"])


def available_comparison(ned: pd.DataFrame, available: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, subset in (("NOT_ENOUGH_DATA", ned), ("AVAILABLE_DESCRIPTOR", available)):
        rows.append(
            {
                "group": name,
                "sample_count": int(len(subset)),
                "avg_available_candle_count": _mean(subset, "available_candle_count"),
                "median_available_candle_count": _median(subset, "available_candle_count"),
                "avg_expected_candle_count": _mean(subset, "expected_candle_count"),
                "avg_missing_candle_count": _mean(subset, "missing_candle_count"),
                "avg_data_window_seconds": _mean(subset, "data_window_seconds"),
                "missing_decision_time_count": int(subset["decision_time_parsed"].isna().sum()) if not subset.empty else 0,
                "near_dataset_boundary_count": int((subset["near_dataset_start"] | subset["near_dataset_end"]).sum()) if not subset.empty else 0,
                "weekend_or_market_gap_count": int(subset["is_weekend_or_market_gap"].sum()) if not subset.empty else 0,
            }
        )
    return pd.DataFrame(rows)


def critical_conclusion(
    ned: pd.DataFrame,
    eligible: pd.DataFrame,
    cause_breakdown: pd.DataFrame,
    *,
    reentry_not_reached_count: int = 0,
) -> str:
    if ned.empty:
        if reentry_not_reached_count:
            return "NOT_ENOUGH_DATA_RECLASSIFIED_AS_REENTRY_NOT_REACHED"
        return "RANDOM_DISTRIBUTED_LOW_RISK"
    cause_counts = Counter(ned["likely_not_enough_data_cause"])
    top_cause, top_count = cause_counts.most_common(1)[0]
    top_rate = _rate(top_count, len(ned))
    if top_cause == CAUSE_EDGE_OF_DATASET and top_rate >= 0.5:
        return "EDGE_OF_DATASET_ARTIFACT"
    if top_cause == CAUSE_WINDOW_TOO_SHORT and top_rate >= 0.5:
        return "WINDOW_CONFIGURATION_ISSUE"
    if top_cause == CAUSE_MISSING_CANDLES and top_rate >= 0.5:
        return "CLUSTERED_DATA_QUALITY_RISK"
    if top_cause == CAUSE_WEEKEND_OR_MARKET_GAP and top_rate >= 0.5:
        return "CLUSTERED_DATA_QUALITY_RISK"
    session_table = grouped_rate_table(eligible, ned, "session_bucket", "session_bucket")
    if not session_table.empty and float(session_table["not_enough_data_rate"].max()) >= 0.5:
        return "CLUSTERED_DATA_QUALITY_RISK"
    if top_cause == CAUSE_UNKNOWN:
        return "UNRESOLVED_REQUIRES_FIX"
    return "RANDOM_DISTRIBUTED_LOW_RISK"


def recommended_next_step(conclusion: str) -> str:
    if conclusion == "NOT_ENOUGH_DATA_RECLASSIFIED_AS_REENTRY_NOT_REACHED":
        return "rerun manual validation planning with REENTRY_NOT_REACHED outside the measurable Layer B denominator"
    if conclusion == "WINDOW_CONFIGURATION_ISSUE":
        return "fix data-window/reporting issue before manual validation"
    if conclusion == "CLUSTERED_DATA_QUALITY_RISK":
        return "create visual validation pack excluding NOT_ENOUGH_DATA or investigate data feed"
    if conclusion == "EDGE_OF_DATASET_ARTIFACT":
        return "proceed cautiously to manual validation pack while excluding edge artifacts"
    if conclusion == "UNRESOLVED_REQUIRES_FIX":
        return "investigate Layer B missing-data cause before manual validation"
    return "proceed to manual validation pack if other review checks remain clean"


def write_not_enough_data_audit_outputs(
    result: NotEnoughDataAuditResult,
    output_dir: str | Path,
    *,
    docs_path: str | Path | None = None,
) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "not_enough_data_samples": output / "not_enough_data_samples.csv",
        "by_direction": output / "not_enough_data_by_direction.csv",
        "by_hour": output / "not_enough_data_by_hour.csv",
        "by_session": output / "not_enough_data_by_session.csv",
        "by_weekday": output / "not_enough_data_by_weekday.csv",
        "by_h1_context": output / "not_enough_data_by_h1_context.csv",
        "cause_breakdown": output / "not_enough_data_cause_breakdown.csv",
        "comparison": output / "not_enough_data_vs_available_comparison.csv",
        "summary": output / "not_enough_data_audit_summary.json",
        "report": output / "not_enough_data_audit_report.md",
    }
    result.not_enough_data_samples.to_csv(paths["not_enough_data_samples"], index=False)
    result.by_direction.to_csv(paths["by_direction"], index=False)
    result.by_hour.to_csv(paths["by_hour"], index=False)
    result.by_session.to_csv(paths["by_session"], index=False)
    result.by_weekday.to_csv(paths["by_weekday"], index=False)
    result.by_h1_context.to_csv(paths["by_h1_context"], index=False)
    result.cause_breakdown.to_csv(paths["cause_breakdown"], index=False)
    result.comparison.to_csv(paths["comparison"], index=False)
    paths["summary"].write_text(json.dumps(result.summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    paths["report"].write_text(result.report_markdown, encoding="utf-8")
    if docs_path:
        docs = Path(docs_path)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(result.report_markdown, encoding="utf-8")
        paths["docs"] = docs
    return {key: str(path) for key, path in paths.items()}


def render_audit_report(
    summary: dict[str, Any],
    by_direction: pd.DataFrame,
    by_session: pd.DataFrame,
    by_weekday: pd.DataFrame,
    by_h1_context: pd.DataFrame,
    cause_breakdown: pd.DataFrame,
    comparison: pd.DataFrame,
) -> str:
    lines = [
        "# Strategy 2 Layer B NOT_ENOUGH_DATA Clustering Audit",
        "",
        "## Context",
        "",
        "Layer B diagnostics originally produced 51/186 Layer A-valid samples as `NOT_ENOUGH_DATA`. The denominator audit separates no-entry/no-reentry attrition from true missing-data cases.",
        "",
        "## Method",
        "",
        "- Inputs: Layer B reaction feature export, Layer A state split, and read-only XAUUSD M1 data.",
        "- Grouping dimensions: direction, hour, UTC session bucket, weekday, H1 context, dataset boundary proximity, candle availability, and likely cause.",
        "- Session buckets: ASIA 00:00-07:59 UTC, LONDON 08:00-12:59 UTC, NY 13:00-20:59 UTC, OFF_HOURS 21:00-23:59 UTC.",
        "- No Strategy 2 reaction rule changes were made.",
        "",
        "## Findings",
        "",
        f"- samples processed: `{summary['samples_processed']}`",
        f"- original Layer A valid samples: `{summary['original_layer_a_valid_samples']}`",
        f"- measurable Layer B samples: `{summary['layer_b_measurable_samples']}`",
        f"- REENTRY_NOT_REACHED count: `{summary['reentry_not_reached_count']}`",
        f"- NOT_ENOUGH_DATA count/rate: `{summary['not_enough_data_count']}` / `{summary['not_enough_data_rate']}`",
        f"- descriptor distribution after reclassification: `{summary['descriptor_distribution']}`",
        f"- measurable descriptor distribution: `{summary['measurable_descriptor_distribution']}`",
        "",
        "### Direction",
        "",
        table_markdown(by_direction),
        "",
        "### Session",
        "",
        table_markdown(by_session),
        "",
        "### Weekday",
        "",
        table_markdown(by_weekday),
        "",
        "### Top H1 Contexts",
        "",
        table_markdown(by_h1_context.head(10)),
        "",
        "### Cause Breakdown",
        "",
        table_markdown(cause_breakdown),
        "",
        "### NOT_ENOUGH_DATA Vs Available Descriptor",
        "",
        table_markdown(comparison),
        "",
        "## Critical Conclusion",
        "",
        f"`{summary['critical_conclusion']}`",
        "",
        f"Recommended next step: {summary['recommended_next_step']}.",
        "",
        "## Safety",
        "",
        "- Strategy 3 untouched.",
        "- Adelin untouched.",
        "- data/XAUUSD/*.csv untouched.",
        "- No live trading, broker execution, orders, Telegram, optimization, ML, backtest, PnL, signal generation, manual validation pack, or reaction-rule change.",
        "",
        "## Verdict Flags",
        "",
        "\n".join(f"- `{flag}`" for flag in summary["verdict_flags"]),
    ]
    return "\n".join(lines) + "\n"


NED_COLUMNS = [
    "sample_id",
    "h1_context_id",
    "direction_candidate",
    "layer_a_state",
    "reaction_descriptor",
    "layer_b_candidate_label",
    "decision_time",
    "sweep_timestamp",
    "data_window_start",
    "data_window_end",
    "hour_utc",
    "weekday",
    "session_bucket",
    "is_weekend_or_market_gap",
    "near_dataset_start",
    "near_dataset_end",
    "available_candle_count",
    "missing_candle_count",
    "expected_candle_count",
    "data_window_seconds",
    "likely_not_enough_data_cause",
    "audit_notes",
]


def table_markdown(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows._"
    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(str(column) for column in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in frame.to_dict("records"):
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return "\n".join(lines)


def _records_by_key(frame: pd.DataFrame, key: str) -> dict[str, dict[str, Any]]:
    records = {}
    for row in frame.to_dict("records"):
        records[str(row[key])] = {item_key: item_value for item_key, item_value in row.items() if item_key != key}
    return records


def _mean(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame.columns:
        return None
    value = pd.to_numeric(frame[column], errors="coerce").mean()
    return None if pd.isna(value) else round(float(value), 4)


def _median(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame.columns:
        return None
    value = pd.to_numeric(frame[column], errors="coerce").median()
    return None if pd.isna(value) else round(float(value), 4)


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


__all__ = [
    "CAUSE_EDGE_OF_DATASET",
    "CAUSE_MISSING_CANDLES",
    "CAUSE_TIMESTAMP_ALIGNMENT",
    "CAUSE_UNKNOWN",
    "CAUSE_WEEKEND_OR_MARKET_GAP",
    "CAUSE_WINDOW_TOO_SHORT",
    "NotEnoughDataAuditResult",
    "add_audit_columns",
    "build_not_enough_data_audit",
    "candle_window_counts",
    "classify_likely_cause",
    "critical_conclusion",
    "grouped_rate_table",
    "load_layer_b_features",
    "session_bucket",
    "write_not_enough_data_audit_outputs",
]
