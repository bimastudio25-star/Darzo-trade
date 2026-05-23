from __future__ import annotations

import json
import random
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_SOURCE_PACK = Path("backtests/reports/strategy_2_layer_b_manual_validation_pack/manual_validation_pack.csv")
DEFAULT_OUTPUT_ROOT = Path("backtests/reports/strategy_2_layer_b_manual_validation_pack")
DEFAULT_SHUFFLE_SEED = 20260523
EXPECTED_ROW_COUNT = 135
EXPECTED_DESCRIPTOR_COUNTS = {
    "FAST_REENTRY": 56,
    "CHOP_AFTER_SWEEP_CANDIDATE": 79,
}
ALLOWED_DESCRIPTORS = set(EXPECTED_DESCRIPTOR_COUNTS)
REENTRY_NOT_REACHED_VALUES = {"REENTRY_NOT_REACHED", "NO_ENTRY_REENTRY_NOT_REACHED"}

DIRECT_DESCRIPTOR_COLUMNS = {
    "reaction_descriptor",
    "descriptor",
    "descriptor_category",
}
INDIRECT_LEAK_COLUMNS = {
    "layer_b_candidate_label",
    "clean_vs_dirty_path_candidate",
    "time_to_reentry_seconds",
    "reentry_distance_usd",
    "reentry_distance_pips",
    "reentry_distance",
}
REACTION_WINDOW_RECONSTRUCTION_COLUMNS = {
    "h1_level_take_timestamp",
    "range_reentry_timestamp",
    "entry_timestamp",
    "data_window_start",
    "data_window_end",
}
ENGINEERED_LAYER_B_COLUMNS = {
    "rejection_wick_ratio",
    "body_displacement_usd",
    "body_displacement_pips",
    "micro_range_size_usd",
    "micro_range_size_pips",
}
LEAK_COLUMN_NAMES = (
    DIRECT_DESCRIPTOR_COLUMNS
    | INDIRECT_LEAK_COLUMNS
    | REACTION_WINDOW_RECONSTRUCTION_COLUMNS
    | ENGINEERED_LAYER_B_COLUMNS
)
DESCRIPTOR_REVEALING_VALUES = {
    "FAST_REENTRY",
    "CHOP_AFTER_SWEEP_CANDIDATE",
    "STRONG_REACTION_CANDIDATE",
    "CHOPPY_REACTION_CANDIDATE",
    "DIRTY",
}
MANUAL_LABEL_COLUMNS = [
    "label_take_skip_uncertain",
    "manual_notes",
    "reviewer",
    "reviewed_at",
]
VISIBLE_BLINDED_COLUMNS = [
    "shuffled_order_index",
    "original_index",
    "pack_row_id",
    "sample_id",
    "symbol",
    "direction_candidate",
    "layer_a_state",
    "entry_status_audit",
    "h1_context_id",
    "h1_context_timestamp",
    "h1_liquidity_level",
    "decision_time",
    "manipulation_depth_usd",
    "manipulation_depth_pips",
    "mae_avg_used_usd",
    "mae_avg_used_pips",
    "pip_factor_used",
    *MANUAL_LABEL_COLUMNS,
]
ANSWER_KEY_COLUMNS = [
    "sample_id",
    "pack_row_id",
    "original_index",
    "shuffled_order_index",
    "reaction_descriptor",
    "layer_b_candidate_label",
    "clean_vs_dirty_path_candidate",
    "time_to_reentry_seconds",
    "reentry_distance_usd",
    "reentry_distance_pips",
    "rejection_wick_ratio",
    "body_displacement_usd",
    "body_displacement_pips",
    "micro_range_size_usd",
    "micro_range_size_pips",
    "h1_level_take_timestamp",
    "range_reentry_timestamp",
    "entry_timestamp",
    "data_window_start",
    "data_window_end",
]
FORBIDDEN_PERFORMANCE_COLUMNS = {
    "pnl",
    "profit",
    "profit" + "_factor",
    "win" + "_rate",
    "wr",
    "pf",
    "r_multiple",
    "actual_outcome",
    "outcome",
}
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
    "take_skip_inferred": False,
}


@dataclass(frozen=True)
class BlindedManualValidationPackResult:
    blinded: pd.DataFrame
    answer_key: pd.DataFrame
    unblinded_source: pd.DataFrame
    summary: dict[str, Any]
    blinded_readme: str
    answer_key_readme: str
    root_warning: str


def load_source_pack(path: str | Path = DEFAULT_SOURCE_PACK) -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"approved unblinded source pack is missing: {source}")
    frame = pd.read_csv(source, keep_default_na=False)
    required = {"sample_id", "reaction_descriptor", "decision_time"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"source pack is malformed; missing columns: {missing}")
    return frame.copy()


def build_strict_blinded_manual_validation_pack(
    source_pack: str | Path = DEFAULT_SOURCE_PACK,
    *,
    shuffle_seed: int = DEFAULT_SHUFFLE_SEED,
    expected_count: int = EXPECTED_ROW_COUNT,
) -> BlindedManualValidationPackResult:
    started = time.perf_counter()
    source = load_source_pack(source_pack)
    validate_source_pack(source, expected_count=expected_count)

    prepared = source.copy()
    prepared.insert(0, "original_index", range(1, len(prepared) + 1))
    if "layer_b_candidate_label" not in prepared.columns:
        prepared["layer_b_candidate_label"] = prepared["reaction_descriptor"].map(candidate_label_for_descriptor).fillna("UNKNOWN_REACTION_CANDIDATE")

    shuffled_indices = list(prepared.index)
    random.Random(shuffle_seed).shuffle(shuffled_indices)
    shuffled = prepared.loc[shuffled_indices].copy().reset_index(drop=True)
    shuffled.insert(0, "shuffled_order_index", range(1, len(shuffled) + 1))

    blinded = build_blinded_frame(shuffled)
    answer_key = build_answer_key_frame(shuffled)
    order_changed = list(source["sample_id"]) != list(blinded["sample_id"])

    gate = validate_blinding_gate(
        blinded,
        answer_key,
        source,
        expected_count=expected_count,
        order_changed=order_changed,
    )
    descriptor_counts = dict(sorted(Counter(source["reaction_descriptor"]).items()))
    removed_columns = sorted([column for column in source.columns if column in LEAK_COLUMN_NAMES or "descriptor" in column.lower()])
    removed_columns = sorted(set(removed_columns) | (LEAK_COLUMN_NAMES & set(source.columns)) | {"layer_b_candidate_label"})
    summary = {
        "runtime_seconds": round(time.perf_counter() - started, 4),
        "source_pack_path": str(Path(source_pack)),
        "source_pack_row_count": int(len(source)),
        "blinded_row_count": int(len(blinded)),
        "answer_key_row_count": int(len(answer_key)),
        "shuffle_seed": int(shuffle_seed),
        "row_order_changed": bool(order_changed),
        "visible_columns_in_blinded_csv": list(blinded.columns),
        "removed_descriptor_leak_columns": removed_columns,
        "descriptor_counts_hidden_in_answer_key": descriptor_counts,
        "reentry_not_reached_count_inside_blinded_csv": count_reentry_not_reached(blinded),
        "missing_decision_time_count_inside_blinded_csv": count_missing_decision_time(blinded),
        "validation_gate_result": gate["validation_gate_result"],
        "blinding_gate_result": gate["blinding_gate_result"],
        "manual_label_columns_blank": manual_label_columns_blank(blinded),
        "layer_b_pipeline_rerun": False,
        "performance_metrics_generated": False,
        "reaction_rules_changed": False,
        "safety": SAFETY,
    }
    return BlindedManualValidationPackResult(
        blinded=blinded,
        answer_key=answer_key,
        unblinded_source=source,
        summary=summary,
        blinded_readme=render_blinded_readme(),
        answer_key_readme=render_answer_key_readme(),
        root_warning=render_root_warning(),
    )


def validate_source_pack(source: pd.DataFrame, *, expected_count: int) -> None:
    failures: list[str] = []
    if len(source) != expected_count:
        failures.append(f"source pack row count {len(source)} differs from expected {expected_count}")
    descriptor_counts = Counter(source["reaction_descriptor"])
    for descriptor, expected in EXPECTED_DESCRIPTOR_COUNTS.items():
        if int(descriptor_counts.get(descriptor, 0)) != expected:
            failures.append(f"source {descriptor} count {descriptor_counts.get(descriptor, 0)} differs from expected {expected}")
    unexpected_descriptors = sorted(set(descriptor_counts) - ALLOWED_DESCRIPTORS)
    if unexpected_descriptors:
        failures.append(f"source pack contains unexpected descriptors: {unexpected_descriptors}")
    if count_reentry_not_reached(source) > 0:
        failures.append("source pack contains REENTRY_NOT_REACHED rows")
    if count_missing_decision_time(source) > 0:
        failures.append("source pack contains missing or unparseable decision_time rows")
    if failures:
        raise ValueError("; ".join(failures))


def build_blinded_frame(shuffled: pd.DataFrame) -> pd.DataFrame:
    visible = pd.DataFrame()
    for column in VISIBLE_BLINDED_COLUMNS:
        if column in shuffled.columns:
            visible[column] = shuffled[column]
        else:
            visible[column] = ""
    for column in MANUAL_LABEL_COLUMNS:
        visible[column] = ""
    return visible[VISIBLE_BLINDED_COLUMNS].copy()


def build_answer_key_frame(shuffled: pd.DataFrame) -> pd.DataFrame:
    key = pd.DataFrame()
    for column in ANSWER_KEY_COLUMNS:
        if column in shuffled.columns:
            key[column] = shuffled[column]
        else:
            key[column] = ""
    for column in MANUAL_LABEL_COLUMNS:
        if column in key.columns:
            key = key.drop(columns=[column])
    return key[ANSWER_KEY_COLUMNS].copy()


def validate_blinding_gate(
    blinded: pd.DataFrame,
    answer_key: pd.DataFrame,
    source: pd.DataFrame,
    *,
    expected_count: int,
    order_changed: bool,
) -> dict[str, dict[str, Any]]:
    validation_failures: list[str] = []
    blinding_failures: list[str] = []

    if len(blinded) != expected_count:
        validation_failures.append(f"blinded row count {len(blinded)} differs from expected {expected_count}")
    if len(answer_key) != expected_count:
        validation_failures.append(f"answer key row count {len(answer_key)} differs from expected {expected_count}")
    if set(blinded["sample_id"]) != set(answer_key["sample_id"]):
        validation_failures.append("sample_id sets differ between blinded CSV and answer key")
    if set(blinded["original_index"]) != set(answer_key["original_index"]):
        validation_failures.append("original_index sets differ between blinded CSV and answer key")
    if not order_changed:
        validation_failures.append("shuffled order equals original order")
    if count_reentry_not_reached(blinded) > 0:
        validation_failures.append("REENTRY_NOT_REACHED row appears in blinded CSV")
    if count_missing_decision_time(blinded) > 0:
        validation_failures.append("blinded CSV contains missing or unparseable decision_time")
    if not manual_label_columns_blank(blinded):
        validation_failures.append("manual label fields are pre-filled")
    if list(blinded["shuffled_order_index"]) != sorted(blinded["shuffled_order_index"]):
        validation_failures.append("blinded CSV is not sorted by shuffled_order_index")
    if sorted(source["original_index"].tolist()) if "original_index" in source.columns else []:
        validation_failures.append("source pack unexpectedly already contains original_index")

    leaked_columns = sorted([column for column in blinded.columns if is_descriptor_leak_column(column)])
    if leaked_columns:
        blinding_failures.append(f"descriptor-revealing columns remain in blinded CSV: {leaked_columns}")
    leaked_values = find_descriptor_revealing_values(blinded)
    if leaked_values:
        blinding_failures.append(f"descriptor-revealing values remain in blinded CSV: {leaked_values[:10]}")
    performance_columns = sorted([column for column in blinded.columns if is_performance_column(column)])
    if performance_columns:
        blinding_failures.append(f"performance/outcome columns remain in blinded CSV: {performance_columns}")
    missing_key_columns = sorted(set(["reaction_descriptor", "layer_b_candidate_label", "clean_vs_dirty_path_candidate"]) - set(answer_key.columns))
    if missing_key_columns:
        validation_failures.append(f"answer key missing hidden descriptor columns: {missing_key_columns}")

    if validation_failures or blinding_failures:
        raise ValueError("; ".join(validation_failures + blinding_failures))
    return {
        "validation_gate_result": {
            "status": "PASS",
            "failures": [],
            "expected_row_count": expected_count,
            "sample_id_sets_match": True,
            "original_index_sets_match": True,
            "row_order_changed": bool(order_changed),
        },
        "blinding_gate_result": {
            "status": "PASS",
            "failures": [],
            "descriptor_columns_removed": True,
            "descriptor_values_removed": True,
            "indirect_leak_fields_removed": True,
            "performance_columns_removed": True,
        },
    }


def write_strict_blinded_outputs(
    result: BlindedManualValidationPackResult,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> dict[str, str]:
    root = Path(output_root)
    blind_dir = root / "blinded_labeling"
    answer_dir = root / "answer_key_do_not_open_until_labels_complete"
    blind_dir.mkdir(parents=True, exist_ok=True)
    answer_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "blinded_csv": blind_dir / "manual_validation_pack_blinded.csv",
        "blinded_answer_key_csv": blind_dir / "manual_validation_pack_answer_key.csv",
        "blinded_readme": blind_dir / "README_READ_THIS_FIRST_BLINDED_LABELING.md",
        "summary_json": blind_dir / "blinded_manual_validation_summary.json",
        "answer_key_csv": answer_dir / "manual_validation_pack_answer_key.csv",
        "do_not_open_unblinded_csv": answer_dir / "_DO_NOT_OPEN_manual_validation_pack_with_descriptors.csv",
        "answer_key_readme": answer_dir / "README_DO_NOT_OPEN_UNTIL_LABELS_COMPLETE.md",
        "root_warning": root / "DO_NOT_OPEN_OR_LABEL_THIS_FILE_USE_BLINDED_PACK.md",
    }
    result.blinded.to_csv(paths["blinded_csv"], index=False)
    result.answer_key.to_csv(paths["blinded_answer_key_csv"], index=False)
    blinded_readme = (
        result.blinded_readme
        + "\nWarning: `manual_validation_pack_answer_key.csv` in this folder is not needed for labeling. "
        "Do not open it until labels are complete.\n"
    )
    paths["blinded_readme"].write_text(blinded_readme, encoding="utf-8")
    paths["summary_json"].write_text(json.dumps(result.summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    result.answer_key.to_csv(paths["answer_key_csv"], index=False)
    result.unblinded_source.to_csv(paths["do_not_open_unblinded_csv"], index=False)
    paths["answer_key_readme"].write_text(result.answer_key_readme, encoding="utf-8")
    paths["root_warning"].write_text(result.root_warning, encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def candidate_label_for_descriptor(descriptor: str) -> str:
    if descriptor == "FAST_REENTRY":
        return "STRONG_REACTION_CANDIDATE"
    if descriptor == "CHOP_AFTER_SWEEP_CANDIDATE":
        return "CHOPPY_REACTION_CANDIDATE"
    return "UNKNOWN_REACTION_CANDIDATE"


def count_reentry_not_reached(frame: pd.DataFrame) -> int:
    count = 0
    for column in ["reaction_descriptor", "layer_b_funnel_state"]:
        if column in frame.columns:
            count += int(frame[column].astype(str).isin(REENTRY_NOT_REACHED_VALUES).sum())
    return count


def count_missing_decision_time(frame: pd.DataFrame) -> int:
    if "decision_time" not in frame.columns:
        return len(frame)
    return int(pd.to_datetime(frame["decision_time"], utc=True, errors="coerce").isna().sum())


def manual_label_columns_blank(frame: pd.DataFrame) -> bool:
    for column in MANUAL_LABEL_COLUMNS:
        if column not in frame.columns:
            return False
        if not frame[column].astype(str).str.strip().eq("").all():
            return False
    return True


def is_descriptor_leak_column(column: str) -> bool:
    lower = column.lower()
    if lower in LEAK_COLUMN_NAMES:
        return True
    if lower in DIRECT_DESCRIPTOR_COLUMNS:
        return True
    if lower in INDIRECT_LEAK_COLUMNS:
        return True
    if "descriptor" in lower:
        return True
    if "reentry_distance" in lower:
        return True
    return lower in REACTION_WINDOW_RECONSTRUCTION_COLUMNS


def is_performance_column(column: str) -> bool:
    lower = column.lower()
    return any(token == lower or token in lower for token in FORBIDDEN_PERFORMANCE_COLUMNS)


def find_descriptor_revealing_values(frame: pd.DataFrame) -> list[str]:
    leaks: list[str] = []
    tokens = {token.upper() for token in DESCRIPTOR_REVEALING_VALUES}
    for column in frame.columns:
        for value in frame[column].astype(str):
            text = value.upper().strip()
            if not text:
                continue
            for token in tokens:
                if token in text:
                    leaks.append(f"{column}={value}")
                    break
    return leaks


def render_blinded_readme() -> str:
    return "\n".join(
        [
            "# Read This First: Blinded Strategy 2 Layer B Labeling",
            "",
            "Open only `manual_validation_pack_blinded.csv` for manual labeling.",
            "",
            "Do not open the answer key.",
            "Do not open the unblinded pack.",
            "Do not use descriptor files before labeling is complete.",
            "",
            "Allowed labels in `label_take_skip_uncertain`:",
            "",
            "- TAKE",
            "- SKIP",
            "- UNCERTAIN",
            "",
            "Do not change `sample_id`, `original_index`, or `shuffled_order_index`.",
            "Label in batches of 20-30 rows.",
            "Add rationale for every UNCERTAIN in `manual_notes`.",
            "",
            "This pack is capture-only. It does not create a rule, signal, backtest, or performance claim.",
        ]
    ) + "\n"


def render_answer_key_readme() -> str:
    return "\n".join(
        [
            "# Do Not Open Until Labels Are Complete",
            "",
            "This directory contains descriptor-revealing files.",
            "Opening these files before manual labels are complete breaks the blind.",
            "",
            "Use only `../blinded_labeling/manual_validation_pack_blinded.csv` during labeling.",
            "",
            "The answer key is for post-label analysis only, after TAKE / SKIP / UNCERTAIN labels are complete.",
        ]
    ) + "\n"


def render_root_warning() -> str:
    return "\n".join(
        [
            "# Do Not Label The Root Unblinded Pack",
            "",
            "For blind manual labeling, open only:",
            "",
            "`blinded_labeling/manual_validation_pack_blinded.csv`",
            "",
            "Do not open `manual_validation_pack.csv` or answer-key files until labels are complete.",
        ]
    ) + "\n"
