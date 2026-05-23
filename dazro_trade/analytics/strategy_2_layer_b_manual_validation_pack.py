from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_INPUT_PATH = Path("backtests/reports/strategy_2_layer_b_reaction_quality/layer_b_reaction_features_per_sample.csv")
DEFAULT_MECHANICAL_PATH = Path("backtests/reports/strategy_2_mechanical_spec_correction/corrected_mechanical_samples.csv")
VALID_LAYER_A_STATES = {"VALID_LONG", "VALID_SHORT"}
PACK_REACTION_DESCRIPTORS = {"FAST_REENTRY", "CHOP_AFTER_SWEEP_CANDIDATE"}
EXCLUDED_REACTION_DESCRIPTORS = {
    "NO_ENTRY_REENTRY_NOT_REACHED",
    "REENTRY_NOT_REACHED",
    "NOT_ENOUGH_DATA",
    "MISSING_DECISION_TIME_BUG",
}
REENTRY_NOT_REACHED_VALUES = {"REENTRY_NOT_REACHED", "NO_ENTRY_REENTRY_NOT_REACHED"}
MANUAL_LABEL_ALLOWED_VALUES = ["TAKE", "SKIP", "UNCERTAIN"]

PACK_COLUMNS = [
    "pack_row_id",
    "sample_id",
    "symbol",
    "direction_candidate",
    "layer_a_state",
    "reaction_descriptor",
    "entry_status_audit",
    "h1_context_id",
    "h1_context_timestamp",
    "h1_liquidity_level",
    "h1_level_take_timestamp",
    "range_reentry_timestamp",
    "entry_timestamp",
    "decision_time",
    "data_window_start",
    "data_window_end",
    "time_to_reentry_seconds",
    "reentry_distance_usd",
    "reentry_distance_pips",
    "rejection_wick_ratio",
    "body_displacement_usd",
    "body_displacement_pips",
    "micro_range_size_usd",
    "micro_range_size_pips",
    "clean_vs_dirty_path_candidate",
    "manipulation_depth_usd",
    "manipulation_depth_pips",
    "mae_avg_used_usd",
    "mae_avg_used_pips",
    "pip_factor_used",
    "label_take_skip_uncertain",
    "manual_notes",
    "reviewer",
    "reviewed_at",
]

SAFETY = {
    "strategy_2_only": True,
    "layer_b_pipeline_rerun": False,
    "live_trading_enabled": False,
    "order_send_called": False,
    "broker_execution_called": False,
    "telegram_operational_signals_sent": False,
    "signals_generated": False,
    "parameters_optimized": False,
    "ml_used": False,
    "backtest_executed": False,
    "performance_claim_made": False,
    "reaction_rules_changed": False,
    "market_data_written": False,
}

VERDICT_FLAGS = [
    "LAYER_B_MANUAL_VALIDATION_PACK_CREATED",
    "MEASURABLE_REACTION_WINDOW_ONLY",
    "REENTRY_NOT_REACHED_EXCLUDED_FROM_PACK",
    "MANUAL_LABEL_COLUMNS_BLANK",
    "NO_PERFORMANCE_CLAIM",
    "NO_REACTION_RULE_CHANGE",
    "STRATEGY_2_REMAINS_RESEARCH_ONLY",
    "NO_DEPLOYMENT_DECISION",
]


@dataclass(frozen=True)
class LayerBManualValidationPackResult:
    pack: pd.DataFrame
    summary: dict[str, Any]
    readme_markdown: str


def load_layer_b_features(path: str | Path = DEFAULT_INPUT_PATH) -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Layer B feature CSV not found: {source}")
    frame = pd.read_csv(source)
    required = {"sample_id", "layer_a_state", "reaction_descriptor", "decision_time"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Layer B feature CSV missing required columns: {missing}")
    return frame.copy()


def load_mechanical_enrichment(path: str | Path = DEFAULT_MECHANICAL_PATH) -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        return pd.DataFrame(columns=["sample_id"])
    frame = pd.read_csv(source)
    if "m15_filter_model" in frame.columns:
        frame = frame[frame["m15_filter_model"].astype(str).str.lower().eq("containing")].copy()
    keep_columns = [
        "sample_id",
        "symbol",
        "h1_context_timestamp",
        "h1_liquidity_level",
        "h1_level_take_timestamp",
        "range_reentry_timestamp",
        "entry_timestamp",
        "entry_status",
        "manipulation_depth_usd",
        "manipulation_depth_pips",
        "mae_avg_used_usd",
    ]
    available = [column for column in keep_columns if column in frame.columns]
    return frame[available].copy() if available else pd.DataFrame(columns=["sample_id"])


def build_layer_b_manual_validation_pack(
    input_path: str | Path = DEFAULT_INPUT_PATH,
    *,
    mechanical_path: str | Path = DEFAULT_MECHANICAL_PATH,
    expected_count: int | None = 135,
    expected_descriptor_counts: dict[str, int] | None = None,
    allow_count_mismatch: bool = False,
    pip_factor: float = 10.0,
) -> LayerBManualValidationPackResult:
    started = time.perf_counter()
    source = load_layer_b_features(input_path)
    mechanical = load_mechanical_enrichment(mechanical_path)
    merged = enrich_with_mechanical(source, mechanical)

    layer_a_valid_mask = merged["layer_a_state"].isin(VALID_LAYER_A_STATES)
    layer_a_valid = merged[layer_a_valid_mask].copy()
    decision_time = pd.to_datetime(merged["decision_time"], utc=True, errors="coerce")
    descriptor = merged["reaction_descriptor"].astype(str)
    funnel = merged.get("layer_b_funnel_state", pd.Series([""] * len(merged), index=merged.index)).astype(str)

    measurable_mask = (
        layer_a_valid_mask
        & descriptor.isin(PACK_REACTION_DESCRIPTORS)
        & decision_time.notna()
        & ~descriptor.isin(EXCLUDED_REACTION_DESCRIPTORS)
        & ~funnel.isin(EXCLUDED_REACTION_DESCRIPTORS | REENTRY_NOT_REACHED_VALUES)
    )
    pack_source = merged[measurable_mask].copy()
    pack = build_pack_frame(pack_source, pip_factor=pip_factor)

    excluded_reentry_not_reached = int(
        (layer_a_valid["reaction_descriptor"].astype(str).isin(REENTRY_NOT_REACHED_VALUES)).sum()
        + (layer_a_valid.get("layer_b_funnel_state", pd.Series([""] * len(layer_a_valid), index=layer_a_valid.index)).astype(str).eq("REENTRY_NOT_REACHED")).sum()
    )
    # Avoid double counting rows that carry both descriptor and funnel state.
    if "layer_b_funnel_state" in layer_a_valid.columns:
        reentry_union = (
            layer_a_valid["reaction_descriptor"].astype(str).isin(REENTRY_NOT_REACHED_VALUES)
            | layer_a_valid["layer_b_funnel_state"].astype(str).eq("REENTRY_NOT_REACHED")
        )
        excluded_reentry_not_reached = int(reentry_union.sum())

    true_not_enough_data = int(
        (
            layer_a_valid["reaction_descriptor"].astype(str).eq("NOT_ENOUGH_DATA")
            | layer_a_valid.get("layer_b_funnel_state", pd.Series([""] * len(layer_a_valid), index=layer_a_valid.index)).astype(str).eq("NOT_ENOUGH_DATA")
        ).sum()
    )
    missing_decision_bug = int(
        (
            layer_a_valid["reaction_descriptor"].astype(str).eq("MISSING_DECISION_TIME_BUG")
            | layer_a_valid.get("layer_b_funnel_state", pd.Series([""] * len(layer_a_valid), index=layer_a_valid.index)).astype(str).eq("MISSING_DECISION_TIME_BUG")
        ).sum()
    )
    descriptor_counts = dict(sorted(Counter(pack["reaction_descriptor"]).items()))
    expected_descriptor_counts = expected_descriptor_counts or {
        "FAST_REENTRY": 56,
        "CHOP_AFTER_SWEEP_CANDIDATE": 79,
    }
    gate = validate_pack_gate(
        pack,
        source=merged,
        expected_count=expected_count,
        expected_descriptor_counts=expected_descriptor_counts,
        allow_count_mismatch=allow_count_mismatch,
    )

    summary = {
        "runtime_seconds": round(time.perf_counter() - started, 4),
        "input_path": str(Path(input_path)),
        "mechanical_enrichment_path": str(Path(mechanical_path)),
        "mechanical_enrichment_loaded": bool(not mechanical.empty),
        "total_source_rows_loaded": int(len(source)),
        "layer_a_valid_count": int(layer_a_valid_mask.sum()),
        "measurable_layer_b_count_entering_pack": int(len(pack)),
        "pack_row_count": int(len(pack)),
        "excluded_reentry_not_reached_count": excluded_reentry_not_reached,
        "excluded_not_enough_data_count": true_not_enough_data,
        "excluded_missing_decision_time_bug_count": missing_decision_bug,
        "descriptor_counts_in_pack": descriptor_counts,
        "expected_pack_count": expected_count,
        "expected_descriptor_counts": expected_descriptor_counts,
        "validation_gate_result": gate,
        "manual_label_allowed_values": MANUAL_LABEL_ALLOWED_VALUES,
        "label_take_skip_uncertain_prefilled": False,
        "capture_only_not_strategy_rule": True,
        "layer_b_pipeline_rerun": False,
        "performance_metrics_generated": False,
        "take_skip_inferred": False,
        "pip_factor_used": float(pip_factor),
        "safety": SAFETY,
        "verdict_flags": VERDICT_FLAGS,
    }
    return LayerBManualValidationPackResult(
        pack=pack,
        summary=summary,
        readme_markdown=render_readme(summary),
    )


def enrich_with_mechanical(source: pd.DataFrame, mechanical: pd.DataFrame) -> pd.DataFrame:
    if mechanical.empty or "sample_id" not in mechanical.columns:
        return source.copy()
    merged = source.merge(mechanical, on="sample_id", how="left", suffixes=("", "_mechanical"))
    for column in [
        "symbol",
        "h1_context_timestamp",
        "h1_liquidity_level",
        "h1_level_take_timestamp",
        "range_reentry_timestamp",
        "entry_timestamp",
        "manipulation_depth_usd",
        "manipulation_depth_pips",
        "mae_avg_used_usd",
    ]:
        mechanical_column = f"{column}_mechanical"
        if mechanical_column in merged.columns:
            if column in merged.columns:
                merged[column] = merged[column].where(merged[column].notna() & merged[column].astype(str).ne(""), merged[mechanical_column])
                merged = merged.drop(columns=[mechanical_column])
            else:
                merged[column] = merged[mechanical_column]
                merged = merged.drop(columns=[mechanical_column])
    if "entry_status" in merged.columns and "entry_status_audit" in merged.columns:
        merged["entry_status_audit"] = merged["entry_status_audit"].where(
            merged["entry_status_audit"].notna() & merged["entry_status_audit"].astype(str).ne(""),
            merged["entry_status"],
        )
    return merged


def build_pack_frame(frame: pd.DataFrame, *, pip_factor: float) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for pack_index, (_, row) in enumerate(frame.sort_values(["decision_time", "sample_id"]).iterrows(), start=1):
        manipulation_depth_usd = _value(row, "manipulation_depth_usd")
        mae_avg_used_usd = _value(row, "mae_avg_used_usd")
        rows.append(
            {
                "pack_row_id": f"S2_LAYER_B_{pack_index:04d}",
                "sample_id": _clean(row.get("sample_id")),
                "symbol": _clean(row.get("symbol")) or "XAUUSD",
                "direction_candidate": _clean(row.get("direction_candidate")),
                "layer_a_state": _clean(row.get("layer_a_state")),
                "reaction_descriptor": _clean(row.get("reaction_descriptor")),
                "entry_status_audit": _clean(row.get("entry_status_audit")) or _clean(row.get("entry_status")),
                "h1_context_id": _clean(row.get("h1_context_id")),
                "h1_context_timestamp": _clean(row.get("h1_context_timestamp")),
                "h1_liquidity_level": _clean(row.get("h1_liquidity_level")),
                "h1_level_take_timestamp": _clean(row.get("h1_level_take_timestamp")) or _clean(row.get("sweep_timestamp")),
                "range_reentry_timestamp": _clean(row.get("range_reentry_timestamp")),
                "entry_timestamp": _clean(row.get("entry_timestamp")),
                "decision_time": _clean(row.get("decision_time")),
                "data_window_start": _clean(row.get("data_window_start")),
                "data_window_end": _clean(row.get("data_window_end")),
                "time_to_reentry_seconds": _clean(row.get("time_to_reentry_seconds")),
                "reentry_distance_usd": _clean(row.get("reentry_distance_usd")),
                "reentry_distance_pips": _clean(row.get("reentry_distance_pips")),
                "rejection_wick_ratio": _clean(row.get("rejection_wick_ratio")),
                "body_displacement_usd": _clean(row.get("body_displacement_usd")),
                "body_displacement_pips": _clean(row.get("body_displacement_pips")),
                "micro_range_size_usd": _clean(row.get("micro_range_size_usd")),
                "micro_range_size_pips": _clean(row.get("micro_range_size_pips")),
                "clean_vs_dirty_path_candidate": _clean(row.get("clean_vs_dirty_path_candidate")),
                "manipulation_depth_usd": _clean(manipulation_depth_usd),
                "manipulation_depth_pips": _clean(row.get("manipulation_depth_pips")) or _clean(_to_pips(manipulation_depth_usd, pip_factor)),
                "mae_avg_used_usd": _clean(mae_avg_used_usd),
                "mae_avg_used_pips": _clean(_to_pips(mae_avg_used_usd, pip_factor)),
                "pip_factor_used": _clean(row.get("pip_factor_used")) or _clean(pip_factor),
                "label_take_skip_uncertain": "",
                "manual_notes": "",
                "reviewer": "",
                "reviewed_at": "",
            }
        )
    return pd.DataFrame(rows, columns=PACK_COLUMNS)


def validate_pack_gate(
    pack: pd.DataFrame,
    *,
    source: pd.DataFrame,
    expected_count: int | None,
    expected_descriptor_counts: dict[str, int],
    allow_count_mismatch: bool,
) -> dict[str, Any]:
    failures: list[str] = []
    if pack["reaction_descriptor"].isin(REENTRY_NOT_REACHED_VALUES).any():
        failures.append("REENTRY_NOT_REACHED row entered manual validation pack")
    if pack["reaction_descriptor"].eq("NOT_ENOUGH_DATA").any():
        failures.append("NOT_ENOUGH_DATA row entered manual validation pack")
    if pack["reaction_descriptor"].eq("MISSING_DECISION_TIME_BUG").any():
        failures.append("MISSING_DECISION_TIME_BUG row entered manual validation pack")
    parsed_decision_time = pd.to_datetime(pack["decision_time"], utc=True, errors="coerce") if not pack.empty else pd.Series(dtype="datetime64[ns, UTC]")
    if parsed_decision_time.isna().any():
        failures.append("manual validation pack contains missing or unparseable decision_time")
    invalid_descriptors = sorted(set(pack["reaction_descriptor"]) - PACK_REACTION_DESCRIPTORS)
    if invalid_descriptors:
        failures.append(f"manual validation pack contains unsupported descriptors: {invalid_descriptors}")
    invalid_states = sorted(set(pack["layer_a_state"]) - VALID_LAYER_A_STATES)
    if invalid_states:
        failures.append(f"manual validation pack contains unsupported Layer A states: {invalid_states}")
    if expected_count is not None and len(pack) != expected_count and not allow_count_mismatch:
        failures.append(f"pack count {len(pack)} differs from expected measurable count {expected_count}")
    actual_descriptor_counts = dict(Counter(pack["reaction_descriptor"]))
    for descriptor, expected in expected_descriptor_counts.items():
        actual = int(actual_descriptor_counts.get(descriptor, 0))
        if actual != int(expected) and not allow_count_mismatch:
            failures.append(f"{descriptor} count {actual} differs from expected {expected}")
    if failures:
        raise ValueError("; ".join(failures))
    return {
        "status": "PASS",
        "failures": [],
        "source_rows_checked": int(len(source)),
        "pack_rows_checked": int(len(pack)),
        "expected_count_enforced": expected_count,
        "expected_descriptor_counts_enforced": expected_descriptor_counts,
        "allow_count_mismatch": bool(allow_count_mismatch),
    }


def write_manual_validation_pack_outputs(
    result: LayerBManualValidationPackResult,
    output_dir: str | Path,
) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "manual_validation_pack_csv": output / "manual_validation_pack.csv",
        "summary_json": output / "manual_validation_pack_summary.json",
        "readme_md": output / "README_manual_validation_pack.md",
    }
    result.pack.to_csv(paths["manual_validation_pack_csv"], index=False)
    paths["summary_json"].write_text(json.dumps(result.summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    paths["readme_md"].write_text(result.readme_markdown, encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def render_readme(summary: dict[str, Any]) -> str:
    descriptor_counts = summary["descriptor_counts_in_pack"]
    return "\n".join(
        [
            "# Strategy 2 Layer B Manual Validation Pack",
            "",
            "This pack is capture-only labeling infrastructure for Strategy 2 Layer B reaction-quality review.",
            "It is not a backtest, signal generator, optimization pass, or deployment artifact.",
            "",
            "## Scope",
            "",
            f"- Source rows loaded: {summary['total_source_rows_loaded']}",
            f"- Layer A valid rows: {summary['layer_a_valid_count']}",
            f"- Measurable Layer B rows entering pack: {summary['measurable_layer_b_count_entering_pack']}",
            f"- Pack rows: {summary['pack_row_count']}",
            f"- Excluded REENTRY_NOT_REACHED: {summary['excluded_reentry_not_reached_count']}",
            f"- Excluded NOT_ENOUGH_DATA: {summary['excluded_not_enough_data_count']}",
            f"- Excluded MISSING_DECISION_TIME_BUG: {summary['excluded_missing_decision_time_bug_count']}",
            "",
            "## Descriptor Counts",
            "",
            f"- FAST_REENTRY: {descriptor_counts.get('FAST_REENTRY', 0)}",
            f"- CHOP_AFTER_SWEEP_CANDIDATE: {descriptor_counts.get('CHOP_AFTER_SWEEP_CANDIDATE', 0)}",
            "",
            "## Manual Labels",
            "",
            "The `label_take_skip_uncertain` column is intentionally blank. Allowed manual values are TAKE, SKIP, or UNCERTAIN.",
            "Do not infer the user's decision from the descriptor. The descriptors are candidate descriptions only.",
            "",
            "## Validation Gate",
            "",
            f"- Result: {summary['validation_gate_result']['status']}",
            "- No REENTRY_NOT_REACHED rows are included.",
            "- No rows with missing or unparseable decision_time are included.",
            "- The pack is limited to FAST_REENTRY and CHOP_AFTER_SWEEP_CANDIDATE descriptors.",
            "",
            "## Safety",
            "",
            "- Strategy 2 only.",
            "- Layer B pipeline was not rerun.",
            "- No live trading, broker execution, order_send, orders, or Telegram operational signals.",
            "- No optimization, ML, backtest execution, performance claim, or reaction-rule change.",
            "- Strategy 2 remains research-only.",
            "",
            "## Next Step",
            "",
            "After Adelin fills the labels, compare TAKE/SKIP/UNCERTAIN labels against reaction_descriptor to measure whether the candidate descriptors match the user's actual selections.",
        ]
    ) + "\n"


def _to_pips(value: Any, pip_factor: float) -> float | None:
    number = _to_float(value)
    if number is None:
        return None
    return round(number * float(pip_factor), 6)


def _to_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _value(row: pd.Series, column: str) -> Any:
    if column not in row.index:
        return None
    value = row.get(column)
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    return value


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()
