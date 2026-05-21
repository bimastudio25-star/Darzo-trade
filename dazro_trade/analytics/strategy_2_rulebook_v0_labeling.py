from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


EXPECTED_CONTAINING_VALID_COUNT = 269
TAKE_REACTION_TAGS = {"RECLAIM", "REJECTION", "AGGRESSIVE_SHIFT", "BODY_REACTION", "WICK_REJECTION"}
UNCERTAIN_REACTION_TAGS = {"WEAK_REACTION", "NOT_COMPUTED", "UNKNOWN", ""}
HARD_M15_INVALID_REASONS = {
    "INVALID_CURRENT_M15_HIGH_TAKEN_FIRST_FOR_LONG",
    "INVALID_CURRENT_M15_LOW_TAKEN_FIRST_FOR_SHORT",
    "NO_H1_LEVEL_TAKEN",
}
VERDICT_FLAGS = [
    "RULEBOOK_V0_LABELING_COMPLETE",
    "ALL_THRESHOLDS_USER_TBD",
    "REACTION_QUALITY_NOT_COMPUTED_BY_DEFAULT",
    "MOST_SAMPLES_UNCERTAIN_EXPECTED",
    "NO_PERFORMANCE_CLAIM",
    "NO_DEPLOYMENT_DECISION",
    "MANUAL_VALIDATION_REQUIRED",
    "STRATEGY_2_REMAINS_RESEARCH_ONLY",
]
SAFETY = {
    "research_only": True,
    "dry_run": True,
    "live_trading_enabled": False,
    "telegram_alerts_sent": False,
    "broker_execution_called": False,
    "orders_sent": False,
    "order_send_called": False,
    "signals_generated": False,
    "runtime_registration": False,
    "parameters_optimized": False,
    "thresholds_optimized": False,
    "ml_classifier_used": False,
    "market_data_written": False,
}


@dataclass(frozen=True)
class RulebookV0Result:
    per_sample: pd.DataFrame
    counters: pd.DataFrame
    risk_distribution: pd.DataFrame
    manipulation_distribution: pd.DataFrame
    threshold_status: pd.DataFrame
    summary: dict[str, Any]
    report_markdown: str


def pips_to_usd(pips: float | None, pip_factor: float = 10.0) -> float | None:
    if pips is None:
        return None
    return round(float(pips) / float(pip_factor), 6)


def usd_to_pips(usd: float | None, pip_factor: float = 10.0) -> float | None:
    if usd is None:
        return None
    return round(float(usd) * float(pip_factor), 6)


def load_containing_samples(input_dir: str | Path) -> pd.DataFrame:
    path = Path(input_dir) / "corrected_mechanical_samples.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing mechanical samples: {path}")
    frame = pd.read_csv(path)
    if "m15_filter_model" not in frame.columns:
        raise ValueError("corrected_mechanical_samples.csv missing m15_filter_model column")
    return frame[frame["m15_filter_model"].astype(str).str.lower().eq("containing")].copy()


def risk_zone(sl_distance_usd: float | None) -> tuple[str, bool, bool, bool, str]:
    if sl_distance_usd is None:
        return "UNKNOWN", False, False, False, ""
    value = float(sl_distance_usd)
    if value <= 12:
        return "STANDARD", False, False, False, ""
    if value <= 20:
        return "LARGE", True, False, False, ""
    if value <= 30:
        return "DEEP_TAIL", True, True, True, ""
    return "EXTREME_TAIL", True, True, True, "SKIP_OR_INVALID"


def manipulation_zone(manipulation_depth_usd: float | None) -> tuple[str, bool, bool, str]:
    if manipulation_depth_usd is None:
        return "UNKNOWN", False, False, ""
    value = float(manipulation_depth_usd)
    if value < 2:
        return "SHALLOW", True, False, "USER_REVIEW"
    if value <= 6:
        return "IDEAL", False, False, ""
    if value <= 12:
        return "ACCEPTABLE", False, False, ""
    if value <= 20:
        return "DEEP", True, False, ""
    if value <= 30:
        return "VERY_DEEP", True, True, ""
    return "EXTREME", True, True, "SKIP_OR_INVALID"


def label_sample(row: dict[str, Any], *, pip_factor: float = 10.0) -> dict[str, Any]:
    sample_id = _clean(row.get("sample_id"))
    manipulation_usd = _distance_usd(row, "manipulation_depth", pip_factor)
    manipulation_pips = usd_to_pips(manipulation_usd, pip_factor) if manipulation_usd is not None else None
    sl_usd = round(manipulation_usd * 1.25, 6) if manipulation_usd is not None else None
    sl_pips = usd_to_pips(sl_usd, pip_factor) if sl_usd is not None else None
    risk, sl_warning, size_adaptation, manual_required_risk, risk_default = risk_zone(sl_usd)
    manip, manip_warning, manual_required_manip, manip_default = manipulation_zone(manipulation_usd)
    reaction_quality = _clean(row.get("reaction_quality_tag")).upper() or "NOT_COMPUTED"
    reaction_observable = _tri_state(row.get("reaction_observable_at_decision_time"))

    take_passed: list[str] = []
    take_failed: list[str] = []
    skip_rules: list[str] = []
    uncertain_rules: list[str] = []
    diagnostic_only: list[str] = []

    h1_ref = _clean(row.get("h1_reference_type")).lower()
    h1_side = _clean(row.get("h1_liquidity_side")).upper()
    direction = _clean(row.get("direction")).upper()
    h1_level = _to_float(row.get("h1_liquidity_level"))
    opposite_h1 = _tri_state(row.get("opposite_h1_side_taken_first"))
    if not h1_ref or h1_ref not in {"previous_h1", "dominant_h1"} or h1_level is None:
        skip_rules.append("H1_REFERENCE_INVALID")
    elif opposite_h1 == "TRUE":
        skip_rules.append("OPPOSITE_H1_SIDE_TAKEN_FIRST")
    else:
        take_passed.append("H1_REFERENCE_VALID")

    m15_valid = _tri_state(row.get("m15_sequence_valid"))
    m15_invalid_reason = _clean(row.get("m15_invalid_reason")).upper()
    if m15_valid == "FALSE" or m15_invalid_reason in HARD_M15_INVALID_REASONS:
        skip_rules.append(m15_invalid_reason or "M15_SEQUENCE_INVALID")
    elif m15_valid == "TRUE" and not m15_invalid_reason:
        take_passed.append("M15_SEQUENCE_VALID")
    else:
        uncertain_rules.append("M15_SEQUENCE_UNKNOWN")

    take_ts = _clean(row.get("h1_level_take_timestamp"))
    side_is_coherent = (direction == "LONG" and h1_side == "LOW") or (direction == "SHORT" and h1_side == "HIGH")
    if not take_ts or take_ts.lower() == "nan":
        skip_rules.append("NO_H1_SWEEP")
    elif not side_is_coherent:
        skip_rules.append("H1_SWEEP_DIRECTION_MISMATCH")
    else:
        take_passed.append("H1_SWEEP_CONFIRMED")

    mae_reached = _tri_state(row.get("mae_reached"))
    if mae_reached == "TRUE":
        if manip in {"IDEAL", "ACCEPTABLE", "DEEP"}:
            take_passed.append("MAE_REACHED_IN_ALLOWED_ZONE")
        else:
            take_failed.append(f"MAE_ZONE_NOT_TAKE_READY_{manip}")
    elif mae_reached == "FALSE":
        uncertain_rules.append("MAE_NOT_REACHED")
        take_failed.append("MAE_NOT_REACHED")
    else:
        uncertain_rules.append("MAE_REACHED_UNKNOWN")

    range_reentry = _tri_state(row.get("range_reentry_reached"))
    if range_reentry == "FALSE":
        skip_rules.append("NO_RANGE_REENTRY_CONFIRMED")
    elif range_reentry == "TRUE":
        take_passed.append("RANGE_REENTRY_REACHED")
    else:
        uncertain_rules.append("RANGE_REENTRY_UNKNOWN")

    if reaction_observable == "FALSE":
        skip_rules.append("NO_REACTION_CONFIRMED_AT_DECISION_TIME")
    elif reaction_observable in {"UNKNOWN", ""}:
        uncertain_rules.append("REACTION_OBSERVABLE_UNKNOWN")
    if reaction_quality in TAKE_REACTION_TAGS:
        take_passed.append("REACTION_QUALITY_TAKE_READY")
    elif reaction_quality in UNCERTAIN_REACTION_TAGS:
        uncertain_rules.append(f"REACTION_QUALITY_{reaction_quality or 'UNKNOWN'}")
        take_failed.append(f"REACTION_QUALITY_{reaction_quality or 'UNKNOWN'}")
    else:
        uncertain_rules.append(f"REACTION_QUALITY_UNRECOGNIZED_{reaction_quality}")

    if h1_level is not None:
        take_passed.append("TP_ANCHOR_H1_LEVEL")
    else:
        uncertain_rules.append("TP_ANCHOR_UNKNOWN")
    uncertain_rules.append("EXPANSION_POTENTIAL_USER_TBD")
    take_failed.append("EXPANSION_POTENTIAL_USER_TBD")
    uncertain_rules.append("ENTRY_SETUP_COMPLETE_PRE_TRIGGER_USER_TBD")

    if _clean(row.get("sample_status")).upper() == "INVALID_NO_DISTRIBUTION":
        diagnostic_only.append("INVALID_NO_DISTRIBUTION_DIAGNOSTIC_ONLY_NOT_HARD_SKIP")

    if risk in {"DEEP_TAIL", "EXTREME_TAIL"}:
        uncertain_rules.append(f"RISK_ZONE_{risk}")
    if manip in {"VERY_DEEP", "EXTREME", "SHALLOW", "UNKNOWN"}:
        uncertain_rules.append(f"MANIPULATION_ZONE_{manip}")
    if risk == "LARGE" and manip == "DEEP":
        uncertain_rules.append("MULTIPLE_WARNINGS_LARGE_PLUS_DEEP")
    dominant_count = _to_float(row.get("dominant_contains_internal_count"))
    if dominant_count is not None and dominant_count > 1:
        uncertain_rules.append("DOMINANT_H1_INTERNAL_COUNT_GT_1")

    if skip_rules:
        label = "SKIP"
    elif uncertain_rules:
        label = "UNCERTAIN"
    elif not take_failed:
        label = "TAKE"
    else:
        label = "UNCERTAIN"

    default_suggestion = risk_default or manip_default
    manual_decision_required = manual_required_risk or manual_required_manip or label == "UNCERTAIN"
    return {
        "sample_id": sample_id,
        "draft_rule_label": label,
        "rulebook_v0_label": label,
        "user_decision": "",
        "risk_zone": risk,
        "sl_distance_usd": sl_usd,
        "sl_distance_pips": sl_pips,
        "sl_warning": bool(sl_warning),
        "manipulation_zone": manip,
        "manipulation_depth_usd": manipulation_usd,
        "manipulation_depth_pips": manipulation_pips,
        "take_rules_passed": _join(take_passed),
        "take_rules_failed": _join(take_failed),
        "skip_rules_triggered": _join(skip_rules),
        "uncertain_rules_triggered": _join(uncertain_rules),
        "size_adaptation_required": bool(size_adaptation),
        "manual_decision_required": bool(manual_decision_required),
        "default_suggestion": default_suggestion,
        "threshold_status": "USER_TBD",
        "reaction_quality_tag": reaction_quality,
        "reaction_observable_at_decision_time": reaction_observable or "UNKNOWN",
        "pip_factor_used": float(pip_factor),
        "diagnostic_only_reason": _join(diagnostic_only),
    }


def build_rulebook_v0_labeling(input_dir: str | Path, *, pip_factor: float = 10.0) -> RulebookV0Result:
    started = time.perf_counter()
    containing = load_containing_samples(input_dir)
    labels = pd.DataFrame([label_sample(row, pip_factor=pip_factor) for row in containing.to_dict("records")])
    counters = _counter_table(labels)
    risk_distribution = _distribution(labels, "risk_zone")
    manipulation_distribution = _distribution(labels, "manipulation_zone")
    threshold_status = _threshold_status_table()
    label_counts = labels["rulebook_v0_label"].value_counts().to_dict() if not labels.empty else {}
    valid_count = _valid_count(containing)
    flags = list(VERDICT_FLAGS)
    if valid_count != EXPECTED_CONTAINING_VALID_COUNT:
        flags.append("COUNT_CHANGED_FROM_EXPECTED_269")
    summary = {
        "runtime_seconds": round(time.perf_counter() - started, 4),
        "input_dir": str(Path(input_dir)),
        "containing_rows_loaded": int(len(containing)),
        "containing_valid_for_mae_count": int(valid_count),
        "expected_containing_valid_count": EXPECTED_CONTAINING_VALID_COUNT,
        "take_count": int(label_counts.get("TAKE", 0)),
        "skip_count": int(label_counts.get("SKIP", 0)),
        "uncertain_count": int(label_counts.get("UNCERTAIN", 0)),
        "not_computed_reaction_count": int((labels["reaction_quality_tag"] == "NOT_COMPUTED").sum()) if not labels.empty else 0,
        "uncertain_caused_by_not_computed_count": int(
            (
                labels["rulebook_v0_label"].eq("UNCERTAIN")
                & labels["uncertain_rules_triggered"].astype(str).str.contains("REACTION_QUALITY_NOT_COMPUTED", na=False)
            ).sum()
        )
        if not labels.empty
        else 0,
        "risk_zone_distribution": _counts_dict(labels, "risk_zone"),
        "manipulation_zone_distribution": _counts_dict(labels, "manipulation_zone"),
        "threshold_status_values": _counts_dict(labels, "threshold_status"),
        "threshold_status_confirmation": "ALL_THRESHOLDS_USER_TBD",
        "pip_factor_used": float(pip_factor),
        "performance_metrics_included": False,
        "take_vs_skip_comparison_included": False,
        "verdict_flags": flags,
        "safety": SAFETY,
    }
    report = render_rulebook_v0_report(summary)
    return RulebookV0Result(
        per_sample=labels,
        counters=counters,
        risk_distribution=risk_distribution,
        manipulation_distribution=manipulation_distribution,
        threshold_status=threshold_status,
        summary=summary,
        report_markdown=report,
    )


def write_rulebook_v0_outputs(result: RulebookV0Result, output_dir: str | Path, *, docs_path: str | Path | None = None) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "per_sample": output / "rulebook_v0_per_sample.csv",
        "counters": output / "rulebook_v0_counters.csv",
        "risk_zone_distribution": output / "rulebook_v0_risk_zone_distribution.csv",
        "manipulation_zone_distribution": output / "rulebook_v0_manipulation_zone_distribution.csv",
        "threshold_status": output / "rulebook_v0_threshold_status.csv",
        "summary": output / "rulebook_v0_summary.json",
        "report": output / "rulebook_v0_report.md",
    }
    result.per_sample.to_csv(paths["per_sample"], index=False)
    result.counters.to_csv(paths["counters"], index=False)
    result.risk_distribution.to_csv(paths["risk_zone_distribution"], index=False)
    result.manipulation_distribution.to_csv(paths["manipulation_zone_distribution"], index=False)
    result.threshold_status.to_csv(paths["threshold_status"], index=False)
    paths["summary"].write_text(json.dumps(result.summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    paths["report"].write_text(result.report_markdown, encoding="utf-8")
    if docs_path:
        docs = Path(docs_path)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(result.report_markdown, encoding="utf-8")
        paths["docs"] = docs
    return {key: str(path) for key, path in paths.items()}


def render_rulebook_v0_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Strategy 2 Rulebook v0 Labeling",
        "",
        "## Context",
        "",
        "The containing M15 model is the current Strategy 2 research model. Previous ex-post separators are not deployable, the manual benchmark exists but is not filled yet, and a transparent deterministic rulebook is needed before manual validation.",
        "",
        "## Safety",
        "",
        "- Strategy 3 untouched.",
        "- data/XAUUSD/*.csv untouched.",
        "- No live trading, Telegram, broker execution, orders, signals, optimization, or runtime registration.",
        "",
        "## Method",
        "",
        "- Labels are TAKE / SKIP / UNCERTAIN using explicit decision-time rules only.",
        "- Hard SKIP is limited to objective pre-entry invalidations such as invalid M15 sequence, no H1 sweep, or confirmed no range re-entry.",
        "- `INVALID_NO_DISTRIBUTION` remains diagnostic-only because it is not proven decision-time safe.",
        "- `risk_zone` and `manipulation_zone` are separate classifications.",
        f"- Unit handling uses `pip_factor={summary.get('pip_factor_used')}`: USD/price distance = pips / pip_factor; when pips are present they are used as the explicit source for converted USD distance.",
        "- Reaction quality is not derived automatically in v0; default `reaction_quality_tag` is `NOT_COMPUTED`.",
        "- All thresholds have status `USER_TBD` and require manual benchmark validation.",
        "- This report includes no performance metrics and no TAKE-vs-SKIP outcome comparison.",
        "",
        "## Results",
        "",
        f"- containing rows loaded: `{summary.get('containing_rows_loaded')}`",
        f"- containing valid-for-MAE count: `{summary.get('containing_valid_for_mae_count')}`",
        f"- TAKE count: `{summary.get('take_count')}`",
        f"- SKIP count: `{summary.get('skip_count')}`",
        f"- UNCERTAIN count: `{summary.get('uncertain_count')}`",
        f"- NOT_COMPUTED reaction count: `{summary.get('not_computed_reaction_count')}`",
        f"- UNCERTAIN caused by NOT_COMPUTED reaction count: `{summary.get('uncertain_caused_by_not_computed_count')}`",
        f"- risk_zone distribution: `{json.dumps(summary.get('risk_zone_distribution', {}), sort_keys=True)}`",
        f"- manipulation_zone distribution: `{json.dumps(summary.get('manipulation_zone_distribution', {}), sort_keys=True)}`",
        f"- threshold status values: `{json.dumps(summary.get('threshold_status_values', {}), sort_keys=True)}`",
        "",
        "## Honest Limitations",
        "",
        "- This is not a performance baseline.",
        "- This is not a backtest.",
        "- This is not a signal generator.",
        "- Most samples are expected to be UNCERTAIN because reaction quality defaults to NOT_COMPUTED.",
        "- There is no reaction-quality derivation from M1/M5 in v0.",
        "- There is no edge claim and no deployment decision.",
        "",
        "## Verdict Flags",
        "",
        "\n".join(f"- `{flag}`" for flag in summary.get("verdict_flags", [])),
        "",
        "## Next Strategy 2-Only Step",
        "",
        "- `feat/strategy-2-rulebook-v0-manual-validation`",
        "- or `feat/strategy-2-reaction-quality-derivation`",
    ]
    return "\n".join(lines) + "\n"


def _valid_count(frame: pd.DataFrame) -> int:
    if "valid_for_mae_dataset" not in frame.columns:
        return 0
    return int(frame["valid_for_mae_dataset"].map(_tri_state).eq("TRUE").sum())


def _counter_table(labels: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if labels.empty:
        return pd.DataFrame(columns=["metric", "value"])
    rows.extend({"metric": f"label_{key}", "value": int(value)} for key, value in labels["rulebook_v0_label"].value_counts().sort_index().items())
    rows.append({"metric": "not_computed_reaction", "value": int((labels["reaction_quality_tag"] == "NOT_COMPUTED").sum())})
    rows.append({"metric": "manual_decision_required", "value": int(labels["manual_decision_required"].sum())})
    rows.append({"metric": "threshold_status_USER_TBD", "value": int((labels["threshold_status"] == "USER_TBD").sum())})
    return pd.DataFrame(rows, columns=["metric", "value"])


def _distribution(labels: pd.DataFrame, field: str) -> pd.DataFrame:
    if labels.empty:
        return pd.DataFrame(columns=[field, "count", "rate"])
    total = len(labels)
    rows = [{"count": int(count), "rate": round(float(count) / total, 4), field: str(value)} for value, count in labels[field].value_counts().sort_index().items()]
    return pd.DataFrame(rows, columns=[field, "count", "rate"])


def _threshold_status_table() -> pd.DataFrame:
    rows = [
        {"rule_area": "risk_zone", "threshold": "sl_distance_usd <= 12", "status": "USER_TBD"},
        {"rule_area": "risk_zone", "threshold": "12 < sl_distance_usd <= 20", "status": "USER_TBD"},
        {"rule_area": "risk_zone", "threshold": "20 < sl_distance_usd <= 30", "status": "USER_TBD"},
        {"rule_area": "risk_zone", "threshold": "sl_distance_usd > 30", "status": "USER_TBD"},
        {"rule_area": "manipulation_zone", "threshold": "2 <= manipulation_depth_usd <= 6", "status": "USER_TBD"},
        {"rule_area": "manipulation_zone", "threshold": "6 < manipulation_depth_usd <= 12", "status": "USER_TBD"},
        {"rule_area": "manipulation_zone", "threshold": "12 < manipulation_depth_usd <= 20", "status": "USER_TBD"},
        {"rule_area": "manipulation_zone", "threshold": "20 < manipulation_depth_usd <= 30", "status": "USER_TBD"},
        {"rule_area": "manipulation_zone", "threshold": "manipulation_depth_usd > 30", "status": "USER_TBD"},
    ]
    return pd.DataFrame(rows)


def _counts_dict(frame: pd.DataFrame, field: str) -> dict[str, int]:
    if frame.empty or field not in frame.columns:
        return {}
    return {str(key): int(value) for key, value in frame[field].value_counts().sort_index().items()}


def _distance_usd(row: dict[str, Any], prefix: str, pip_factor: float) -> float | None:
    pips = _to_float(row.get(f"{prefix}_pips"))
    if pips is not None:
        return pips_to_usd(pips, pip_factor)
    return _to_float(row.get(f"{prefix}_usd"))


def _tri_state(value: Any) -> str:
    text = _clean(value).upper()
    if text in {"TRUE", "T", "YES", "Y", "1"}:
        return "TRUE"
    if text in {"FALSE", "F", "NO", "N", "0"}:
        return "FALSE"
    return "UNKNOWN"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _join(values: list[str]) -> str:
    return ";".join(dict.fromkeys(value for value in values if value))


__all__ = [
    "RulebookV0Result",
    "build_rulebook_v0_labeling",
    "label_sample",
    "load_containing_samples",
    "manipulation_zone",
    "pips_to_usd",
    "risk_zone",
    "usd_to_pips",
    "write_rulebook_v0_outputs",
]
