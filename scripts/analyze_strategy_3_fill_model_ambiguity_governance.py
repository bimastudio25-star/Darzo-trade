from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.backtest.data_loader import load_csv_timeframes

STRATEGY_NAME = "strategy_3_vwap_1r"
REFERENCE_MODEL = "PAPER_REFERENCE_FILL_AT_SIGNAL"
PENDING_TOUCH_MODEL = "PAPER_PENDING_ENTRY_TOUCH"
CONSERVATIVE_MODEL = "CONSERVATIVE_NEXT_CANDLE_FILL_OR_TOUCH"
DEFAULT_OUTPUT_DIR = Path("backtests/reports/strategy_3_fill_model_ambiguity_governance")
DEFAULT_DOCS_PATH = Path("docs/research/strategy_3_fill_model_ambiguity_governance.md")
PIPS_PER_USD_XAUUSD = 10.0

SAFETY = {
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "order_execution_enabled": False,
    "broker_execution_enabled": False,
    "order_send_called": False,
    "signal_stream_enabled": False,
    "lot_sizing_enabled": False,
    "account_risk_sizing_enabled": False,
    "strategy_3_runtime_logic_changed": False,
    "vwap_sigma_cooldown_logic_changed": False,
    "strategy_2_touched": False,
    "adelin_touched": False,
    "data_xauusd_mutated": False,
    "parameter_tuning_enabled": False,
    "deployment_recommendation_emitted": False,
}

PER_SIGNAL_FIELDS = [
    "event_id",
    "decision_timestamp",
    "symbol",
    "direction",
    "entry_reference_price",
    "stop_loss",
    "take_profit",
    "risk_distance_usd",
    "risk_distance_pips",
    "reference_outcome_status",
    "pending_touch_outcome_status",
    "conservative_outcome_status",
    "reference_outcome_r",
    "pending_touch_outcome_r",
    "conservative_outcome_r",
    "changed_under_conservative_flag",
    "changed_under_pending_touch_flag",
    "ambiguous_candle_timestamp",
    "ambiguous_candle_open",
    "ambiguous_candle_high",
    "ambiguous_candle_low",
    "ambiguous_candle_close",
    "entry_inside_ambiguous_candle",
    "tp_inside_ambiguous_candle",
    "sl_inside_ambiguous_candle",
    "ambiguity_type",
    "ambiguity_source",
    "required_data_to_resolve",
    "recommended_outcome_handling",
    "paper_only",
]
TYPE_SUMMARY_FIELDS = [
    "ambiguity_type",
    "required_data_to_resolve",
    "recommended_outcome_handling",
    "direction",
    "risk_distance_bucket",
    "count",
]
IMPACT_FIELDS = [
    "mode",
    "accepted_signals",
    "deterministic_outcome_count",
    "ambiguous_count",
    "tp_hit_count",
    "sl_hit_count",
    "decisive_wr",
    "total_r",
    "average_r",
    "median_r",
    "excluded_count",
    "interpretation_status",
]


@dataclass(frozen=True)
class AmbiguityGovernanceConfig:
    symbol: str
    data_dir: str
    fill_model_audit_dir: Path
    lifecycle_outcomes_path: Path
    paper_signals_path: Path
    output_dir: Path
    docs_path: Path
    dry_run: bool
    forward_timeframe: str
    fallback_timeframe: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strategy 3 fill-model ambiguity governance")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--fill-model-audit-dir", default="backtests/reports/strategy_3_paper_fill_model_audit")
    parser.add_argument("--lifecycle-outcomes-path", default="backtests/reports/strategy_3_paper_lifecycle_outcomes/paper_signal_outcomes.csv")
    parser.add_argument("--paper-signals-path", default="backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--docs-path", default=str(DEFAULT_DOCS_PATH))
    parser.add_argument("--forward-timeframe", default="M1")
    parser.add_argument("--fallback-timeframe", default="M5")
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_ts(value: Any) -> pd.Timestamp | None:
    if value is None or str(value).strip() == "":
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _iso(value: Any) -> str | None:
    ts = _parse_ts(value)
    return ts.isoformat() if ts is not None else None


def _json_flags(value: Any) -> dict[str, bool]:
    if value is None or str(value).strip() == "":
        return {}
    try:
        raw = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return {str(k): _bool(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _risk_bucket(value: Any) -> str:
    risk = _float(value)
    if risk is None:
        return "missing"
    if risk <= 1.0:
        return "0_to_1_usd"
    if risk <= 2.0:
        return "1_to_2_usd"
    if risk <= 4.0:
        return "2_to_4_usd"
    return "over_4_usd"


def load_forward_frame(cfg: AmbiguityGovernanceConfig) -> tuple[pd.DataFrame, str, list[str]]:
    warnings: list[str] = []
    loaded = load_csv_timeframes(cfg.symbol, [cfg.forward_timeframe], data_dir=cfg.data_dir)
    frame = loaded.get(cfg.forward_timeframe, pd.DataFrame())
    timeframe_used = cfg.forward_timeframe
    if frame.empty and cfg.fallback_timeframe:
        warnings.append(f"FORWARD_TIMEFRAME_MISSING_OR_EMPTY: {cfg.forward_timeframe}; falling back to {cfg.fallback_timeframe}")
        loaded = load_csv_timeframes(cfg.symbol, [cfg.fallback_timeframe], data_dir=cfg.data_dir)
        frame = loaded.get(cfg.fallback_timeframe, pd.DataFrame())
        timeframe_used = cfg.fallback_timeframe
    if frame.empty:
        warnings.append("FORWARD_DATA_MISSING")
        return frame, timeframe_used, warnings
    out = frame.copy()
    out["time"] = pd.to_datetime(out["time"], utc=True)
    for col in ("open", "high", "low", "close"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time").reset_index(drop=True)
    return out, timeframe_used, warnings


def is_ambiguity_candidate(row: dict[str, Any]) -> bool:
    if row.get("signal_status") != "SIGNAL_ACCEPTED":
        return False
    statuses = [row.get("reference_fill_outcome_status"), row.get("pending_touch_outcome_status"), row.get("conservative_outcome_status")]
    flags = _json_flags(row.get("ambiguous_intrabar_flag_by_model"))
    return (
        "AMBIGUOUS_INTRABAR" in statuses
        or _bool(row.get("changed_under_conservative_flag"))
        or _bool(row.get("changed_under_pending_touch_flag"))
        or any(flags.values())
    )


def _find_candle(frame: pd.DataFrame, timestamp: Any) -> dict[str, Any] | None:
    ts = _parse_ts(timestamp)
    if ts is None or frame.empty:
        return None
    times = pd.to_datetime(frame["time"], utc=True)
    match = frame.loc[times == ts]
    if match.empty:
        return None
    return dict(match.iloc[0])


def _first_tp_sl_same_candle(row: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any] | None:
    decision = _parse_ts(row.get("decision_timestamp"))
    entry = _float(row.get("entry_reference_price"))
    stop = _float(row.get("stop_loss"))
    target = _float(row.get("take_profit"))
    direction = str(row.get("direction") or "").upper()
    if decision is None or entry is None or stop is None or target is None or direction not in {"LONG", "SHORT"} or frame.empty:
        return None
    future = frame.loc[pd.to_datetime(frame["time"], utc=True) > decision]
    for _, candle in future.iterrows():
        high = float(candle["high"])
        low = float(candle["low"])
        if direction == "LONG":
            tp_inside = high >= target
            sl_inside = low <= stop
        else:
            tp_inside = low <= target
            sl_inside = high >= stop
        if tp_inside and sl_inside:
            return dict(candle)
    return None


def locate_ambiguous_candle(row: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any] | None:
    if row.get("reference_fill_outcome_status") == "AMBIGUOUS_INTRABAR" or row.get("pending_touch_outcome_status") == "AMBIGUOUS_INTRABAR":
        found = _first_tp_sl_same_candle(row, frame)
        if found is not None:
            return found
    if row.get("conservative_outcome_status") == "AMBIGUOUS_INTRABAR":
        found = _find_candle(frame, row.get("conservative_entry_timestamp"))
        if found is not None:
            return found
    found = _find_candle(frame, row.get("pending_touch_entry_timestamp"))
    if found is not None:
        return found
    return _find_candle(frame, row.get("decision_timestamp"))


def classify_ambiguity(row: dict[str, Any], candle: dict[str, Any] | None) -> dict[str, Any]:
    entry = _float(row.get("entry_reference_price"))
    stop = _float(row.get("stop_loss"))
    target = _float(row.get("take_profit"))
    direction = str(row.get("direction") or "").upper()
    if entry is None or stop is None or target is None or direction not in {"LONG", "SHORT"}:
        return {
            "entry_inside_ambiguous_candle": False,
            "tp_inside_ambiguous_candle": False,
            "sl_inside_ambiguous_candle": False,
            "ambiguity_type": "MISSING_REQUIRED_FIELDS",
            "required_data_to_resolve": "NOT_RESOLVABLE_WITH_CURRENT_DATA",
            "recommended_outcome_handling": "REQUIRE_HUMAN_REVIEW",
        }
    if candle is None:
        return {
            "entry_inside_ambiguous_candle": False,
            "tp_inside_ambiguous_candle": False,
            "sl_inside_ambiguous_candle": False,
            "ambiguity_type": "UNCLASSIFIED_AMBIGUITY",
            "required_data_to_resolve": "NOT_RESOLVABLE_WITH_CURRENT_DATA",
            "recommended_outcome_handling": "REQUIRE_HUMAN_REVIEW",
        }
    high = float(candle["high"])
    low = float(candle["low"])
    entry_inside = low <= entry <= high
    if direction == "LONG":
        tp_inside = high >= target
        sl_inside = low <= stop
    else:
        tp_inside = low <= target
        sl_inside = high >= stop

    reference_ambiguous = row.get("reference_fill_outcome_status") == "AMBIGUOUS_INTRABAR"
    pending_ambiguous = row.get("pending_touch_outcome_status") == "AMBIGUOUS_INTRABAR"
    conservative_ambiguous = row.get("conservative_outcome_status") == "AMBIGUOUS_INTRABAR"
    conservative_only = conservative_ambiguous and not reference_ambiguous and not pending_ambiguous
    if reference_ambiguous or pending_ambiguous:
        ambiguity_type = "TRUE_TP_SL_SAME_CANDLE" if tp_inside and sl_inside else "DATA_RESOLUTION_LIMIT_M1"
        handling = "EXCLUDE_FROM_DECISIVE_WR"
    elif conservative_only and entry_inside and (tp_inside or sl_inside):
        ambiguity_type = "CONSERVATIVE_POLICY_ARTIFACT"
        handling = "COUNT_AS_AMBIGUOUS_ONLY"
    elif entry_inside and (tp_inside or sl_inside):
        ambiguity_type = "ENTRY_AND_EXIT_SAME_CANDLE"
        handling = "COUNT_AS_AMBIGUOUS_ONLY"
    else:
        ambiguity_type = "FIRST_ELIGIBLE_CANDLE_ORDER_UNKNOWN" if conservative_ambiguous else "UNCLASSIFIED_AMBIGUITY"
        handling = "REQUIRE_HUMAN_REVIEW"

    required = "NEEDS_TICK_DATA" if ambiguity_type != "CONSERVATIVE_POLICY_ARTIFACT" else "NEEDS_BROKER_FILL_MODEL"
    if ambiguity_type == "DATA_RESOLUTION_LIMIT_M1":
        required = "NEEDS_TICK_DATA"
    return {
        "entry_inside_ambiguous_candle": entry_inside,
        "tp_inside_ambiguous_candle": tp_inside,
        "sl_inside_ambiguous_candle": sl_inside,
        "ambiguity_type": ambiguity_type,
        "required_data_to_resolve": required,
        "recommended_outcome_handling": handling,
    }


def ambiguity_source(row: dict[str, Any]) -> str:
    sources: list[str] = []
    if row.get("reference_fill_outcome_status") == "AMBIGUOUS_INTRABAR":
        sources.append("REFERENCE_MODEL")
    if row.get("pending_touch_outcome_status") == "AMBIGUOUS_INTRABAR":
        sources.append("PENDING_TOUCH_MODEL")
    if row.get("conservative_outcome_status") == "AMBIGUOUS_INTRABAR":
        sources.append("CONSERVATIVE_MODEL")
    if len(sources) > 1:
        return "MULTI_MODEL"
    return sources[0] if sources else "CONSERVATIVE_MODEL" if _bool(row.get("changed_under_conservative_flag")) else "UNCLASSIFIED_AMBIGUITY"


def build_per_signal_rows(audit_rows: list[dict[str, Any]], frame: pd.DataFrame) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in audit_rows:
        if not is_ambiguity_candidate(row):
            continue
        candle = locate_ambiguous_candle(row, frame)
        classification = classify_ambiguity(row, candle)
        out.append(
            {
                "event_id": row.get("event_id"),
                "decision_timestamp": row.get("decision_timestamp"),
                "symbol": row.get("symbol"),
                "direction": row.get("direction"),
                "entry_reference_price": row.get("entry_reference_price"),
                "stop_loss": row.get("stop_loss"),
                "take_profit": row.get("take_profit"),
                "risk_distance_usd": row.get("risk_distance_usd"),
                "risk_distance_pips": row.get("risk_distance_pips"),
                "reference_outcome_status": row.get("reference_fill_outcome_status"),
                "pending_touch_outcome_status": row.get("pending_touch_outcome_status"),
                "conservative_outcome_status": row.get("conservative_outcome_status"),
                "reference_outcome_r": row.get("reference_outcome_r"),
                "pending_touch_outcome_r": row.get("pending_touch_outcome_r"),
                "conservative_outcome_r": row.get("conservative_outcome_r"),
                "changed_under_conservative_flag": _bool(row.get("changed_under_conservative_flag")),
                "changed_under_pending_touch_flag": _bool(row.get("changed_under_pending_touch_flag")),
                "ambiguous_candle_timestamp": _iso(candle.get("time")) if candle else None,
                "ambiguous_candle_open": candle.get("open") if candle else None,
                "ambiguous_candle_high": candle.get("high") if candle else None,
                "ambiguous_candle_low": candle.get("low") if candle else None,
                "ambiguous_candle_close": candle.get("close") if candle else None,
                **classification,
                "ambiguity_source": ambiguity_source(row),
                "paper_only": True,
            }
        )
    return out


def build_type_summary(per_signal: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str, str, str, str]] = Counter()
    for row in per_signal:
        key = (
            str(row.get("ambiguity_type") or "UNCLASSIFIED_AMBIGUITY"),
            str(row.get("required_data_to_resolve") or "NOT_RESOLVABLE_WITH_CURRENT_DATA"),
            str(row.get("recommended_outcome_handling") or "REQUIRE_HUMAN_REVIEW"),
            str(row.get("direction") or "UNKNOWN"),
            _risk_bucket(row.get("risk_distance_usd")),
        )
        counts[key] += 1
    return [
        {
            "ambiguity_type": key[0],
            "required_data_to_resolve": key[1],
            "recommended_outcome_handling": key[2],
            "direction": key[3],
            "risk_distance_bucket": key[4],
            "count": count,
        }
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _accepted_rows(audit_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in audit_rows if row.get("signal_status") == "SIGNAL_ACCEPTED"]


def _r(row: dict[str, Any], field: str) -> float | None:
    return _float(row.get(field))


def _stats(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    return round(sum(values), 6), round(sum(values) / len(values), 6), round(float(median(values)), 6)


def build_impact_summary(audit_rows: list[dict[str, Any]], per_signal: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted = _accepted_rows(audit_rows)
    ambiguous_any = {row.get("event_id") for row in per_signal}

    def mode_row(mode: str, rows: list[dict[str, Any]], *, conservative_loss: bool = False, excluded_count: int = 0, interpretation: str) -> dict[str, Any]:
        tp = 0
        sl = 0
        ambiguous = 0
        r_values: list[float] = []
        for row in rows:
            status = row.get("conservative_outcome_status") if conservative_loss else row.get("reference_fill_outcome_status")
            r_field = "conservative_outcome_r" if conservative_loss else "reference_outcome_r"
            if status == "AMBIGUOUS_INTRABAR":
                ambiguous += 1
                if conservative_loss:
                    sl += 1
                    r_values.append(-1.0)
                continue
            if status == "TP_HIT":
                tp += 1
                r_values.append(_r(row, r_field) if _r(row, r_field) is not None else 1.0)
            elif status == "SL_HIT":
                sl += 1
                r_values.append(_r(row, r_field) if _r(row, r_field) is not None else -1.0)
            elif status == "TIMEOUT_CLOSE" and _r(row, r_field) is not None:
                r_values.append(float(_r(row, r_field)))
        total_r, avg_r, med_r = _stats(r_values)
        return {
            "mode": mode,
            "accepted_signals": len(accepted),
            "deterministic_outcome_count": len(r_values),
            "ambiguous_count": ambiguous,
            "tp_hit_count": tp,
            "sl_hit_count": sl,
            "decisive_wr": round(tp / (tp + sl), 6) if (tp + sl) else None,
            "total_r": total_r,
            "average_r": avg_r,
            "median_r": med_r,
            "excluded_count": excluded_count,
            "interpretation_status": interpretation,
        }

    reference = mode_row("REFERENCE_PRIMARY", accepted, excluded_count=0, interpretation="PRIMARY_DESCRIPTIVE_ONLY_SMALL_N")
    excluded = [row for row in accepted if row.get("event_id") in ambiguous_any]
    included = [row for row in accepted if row.get("event_id") not in ambiguous_any]
    excluded_primary = mode_row(
        "AMBIGUOUS_EXCLUDED_PRIMARY",
        included,
        excluded_count=len(excluded),
        interpretation="PRIMARY_AMBIGUOUS_EXCLUDED_DESCRIPTIVE_ONLY_SMALL_N",
    )
    conservative = mode_row(
        "CONSERVATIVE_DIAGNOSTIC_ONLY",
        accepted,
        conservative_loss=True,
        excluded_count=0,
        interpretation="CONSERVATIVE_DIAGNOSTIC_ONLY_NOT_PRIMARY",
    )
    return [reference, excluded_primary, conservative]


def governance_policy(gate: str, stream_gate: str) -> dict[str, Any]:
    return {
        "primary_outcome_policy": "REFERENCE_PRIMARY_WITH_AMBIGUOUS_EXCLUDED_FROM_DECISIVE_WR",
        "ambiguous_intrabar_policy": "AMBIGUOUS_NOT_COUNTED_AS_WIN_AND_EXCLUDED_FROM_DECISIVE_WR",
        "same_candle_entry_exit_policy": "COUNT_AS_AMBIGUOUS_ONLY_UNTIL_TICK_OR_BROKER_FILL_DATA_EXISTS",
        "conservative_mode_policy": "CONSERVATIVE_LOSS_DIAGNOSTIC_ONLY_NOT_PRIMARY",
        "paper_signal_stream_gate_policy": stream_gate,
        "human_review_policy": "REQUIRE_HUMAN_REVIEW_FOR_MISSING_OR_UNCLASSIFIED_AMBIGUITY",
        "tick_data_requirement_policy": "TICK_DATA_REQUIRED_TO_RESOLVE_INTRABAR_ORDERING; M1_IS_NOT_ENOUGH_FOR_PATH_ORDER",
        "ambiguity_governance_gate": gate,
        "live_gate": "BLOCKED",
        "deployment_gate": "BLOCKED",
        "order_send_gate": "BLOCKED",
        "broker_gate": "BLOCKED",
        "paper_only": True,
    }


def compute_gates(audit_rows: list[dict[str, Any]], per_signal: list[dict[str, Any]]) -> tuple[str, str, dict[str, Any]]:
    accepted = _accepted_rows(audit_rows)
    accepted_count = len(accepted)
    primary_ambiguous = sum(1 for row in accepted if row.get("reference_fill_outcome_status") == "AMBIGUOUS_INTRABAR")
    conservative_changed = sum(1 for row in accepted if _bool(row.get("changed_under_conservative_flag")))
    missing = sum(1 for row in per_signal if row.get("ambiguity_type") == "MISSING_REQUIRED_FIELDS")
    unclassified = sum(1 for row in per_signal if row.get("ambiguity_type") == "UNCLASSIFIED_AMBIGUITY")
    primary_rate = round(primary_ambiguous / accepted_count, 6) if accepted_count else 0.0
    conservative_rate = round(conservative_changed / accepted_count, 6) if accepted_count else 0.0
    details = {
        "accepted_count": accepted_count,
        "primary_ambiguous_count": primary_ambiguous,
        "primary_ambiguous_rate": primary_rate,
        "conservative_changed_count": conservative_changed,
        "conservative_changed_rate": conservative_rate,
        "missing_required_fields_count": missing,
        "unclassified_ambiguity_count": unclassified,
        "governance_thresholds": {
            "passed_primary_ambiguity_rate_max": 0.10,
            "passed_conservative_changed_rate_watch_max": 0.20,
            "blocked_conservative_changed_rate_min": 0.35,
        },
    }
    if accepted_count == 0 or missing > 0 or unclassified > 0:
        return "BLOCKED", "BLOCKED", details
    if primary_rate <= 0.10 and conservative_rate <= 0.20:
        return "PASSED", "ELIGIBLE_FOR_PAPER_ONLY_SIGNAL_STREAM", details
    if primary_rate <= 0.10 and conservative_rate <= 0.35:
        return "WARNING", "WARNING", details
    return "BLOCKED", "BLOCKED", details


def build_summary(
    *,
    cfg: AmbiguityGovernanceConfig,
    audit_rows: list[dict[str, Any]],
    per_signal: list[dict[str, Any]],
    type_summary: list[dict[str, Any]],
    impact_summary: list[dict[str, Any]],
    policy: dict[str, Any],
    audit_summary: dict[str, Any],
    sensitivity: dict[str, Any],
    forward_timeframe_used: str,
    forward_warnings: list[str],
    gate_details: dict[str, Any],
    runtime_seconds: float,
) -> dict[str, Any]:
    return {
        "run_finished_at": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": round(runtime_seconds, 4),
        "dry_run": cfg.dry_run,
        "strategy": STRATEGY_NAME,
        "symbol": cfg.symbol,
        "inputs": {
            "fill_model_audit_dir": str(cfg.fill_model_audit_dir),
            "lifecycle_outcomes_path": str(cfg.lifecycle_outcomes_path),
            "paper_signals_path": str(cfg.paper_signals_path),
            "data_dir": cfg.data_dir,
        },
        "methodology": {
            "forward_timeframe_requested": cfg.forward_timeframe,
            "forward_timeframe_used": forward_timeframe_used,
            "closed_candles_only": True,
            "ambiguity_candidates": "conservative ambiguous, changed under conservative/pending, or any model ambiguous",
            "tick_data_limitation": "M1 OHLC cannot resolve intrabar path ordering.",
        },
        "source_fill_model_audit": {
            "fill_model_alignment": audit_summary.get("alignment", {}).get("fill_model_alignment"),
            "fill_model_sensitivity_status": sensitivity.get("fill_model_sensitivity_status"),
            "fill_model_audit_gate": audit_summary.get("fill_model_audit_gate"),
            "paper_signal_stream_gate": audit_summary.get("paper_signal_stream_gate"),
        },
        "counts": {
            "accepted_signals": gate_details["accepted_count"],
            "ambiguity_candidate_count": len(per_signal),
            "primary_ambiguous_count": gate_details["primary_ambiguous_count"],
            "primary_ambiguous_rate": gate_details["primary_ambiguous_rate"],
            "conservative_changed_count": gate_details["conservative_changed_count"],
            "conservative_changed_rate": gate_details["conservative_changed_rate"],
            "missing_required_fields_count": gate_details["missing_required_fields_count"],
            "unclassified_ambiguity_count": gate_details["unclassified_ambiguity_count"],
        },
        "ambiguity_type_counts": dict(Counter(row["ambiguity_type"] for row in per_signal)),
        "ambiguity_type_summary": type_summary,
        "ambiguity_impact_summary": impact_summary,
        "governance_policy": policy,
        "ambiguity_governance_gate": policy["ambiguity_governance_gate"],
        "paper_signal_stream_gate": policy["paper_signal_stream_gate_policy"],
        "live_gate": "BLOCKED",
        "deployment_gate": "BLOCKED",
        "order_send_gate": "BLOCKED",
        "broker_gate": "BLOCKED",
        "forward_warnings": forward_warnings,
        "verdict_flags": [
            "AMBIGUITY_GOVERNANCE_CREATED",
            f"AMBIGUITY_GOVERNANCE_GATE_{policy['ambiguity_governance_gate']}",
            f"PAPER_SIGNAL_STREAM_GATE_{policy['paper_signal_stream_gate_policy']}",
            "CONSERVATIVE_LOSS_DIAGNOSTIC_ONLY_NOT_PRIMARY",
            "AMBIGUOUS_EXCLUDED_FROM_DECISIVE_WR",
            "NO_TELEGRAM_SIGNAL_STREAM_AUTHORIZATION",
            "NO_LIVE_DEPLOYMENT_DECISION",
            "STRATEGY_3_REMAINS_PAPER_ONLY",
        ],
        "safety": dict(SAFETY),
    }


def write_report(output_dir: Path, docs_path: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Strategy 3 Fill-Model Ambiguity Governance",
        "",
        "This branch is governance/diagnostic only. It does not change Strategy 3, enable Telegram, send signals, place orders, call broker execution, tune parameters, or approve live trading.",
        "",
        "## Why This Exists",
        "",
        "The fill-model audit found that reference and pending-touch outcomes match, but conservative first-eligible-candle ambiguity changes several outcomes. This report freezes how ambiguous paper outcomes are reported before any paper signal-stream work.",
        "",
        "## Source Fill-Model Audit",
        "",
        f"- fill model alignment: `{summary['source_fill_model_audit']['fill_model_alignment']}`",
        f"- fill model sensitivity: `{summary['source_fill_model_audit']['fill_model_sensitivity_status']}`",
        f"- fill model audit gate: `{summary['source_fill_model_audit']['fill_model_audit_gate']}`",
        "",
        "## Ambiguity Counts",
        "",
        f"- accepted signals: `{summary['counts']['accepted_signals']}`",
        f"- ambiguity candidates: `{summary['counts']['ambiguity_candidate_count']}`",
        f"- primary ambiguous count/rate: `{summary['counts']['primary_ambiguous_count']}` / `{summary['counts']['primary_ambiguous_rate']}`",
        f"- conservative changed count/rate: `{summary['counts']['conservative_changed_count']}` / `{summary['counts']['conservative_changed_rate']}`",
        "",
        "| ambiguity_type | count |",
        "|---|---:|",
    ]
    for key, count in summary["ambiguity_type_counts"].items():
        lines.append(f"| {key} | {count} |")
    lines.extend(
        [
            "",
            "## Impact Summary",
            "",
            "| mode | deterministic | ambiguous | TP | SL | decisive_WR | total_R | interpretation |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in summary["ambiguity_impact_summary"]:
        lines.append(
            f"| {row['mode']} | {row['deterministic_outcome_count']} | {row['ambiguous_count']} | {row['tp_hit_count']} | {row['sl_hit_count']} | {row['decisive_wr']} | {row['total_r']} | {row['interpretation_status']} |"
        )
    lines.extend(
        [
            "",
            "## Frozen Governance Policy",
            "",
            f"- primary outcome policy: `{summary['governance_policy']['primary_outcome_policy']}`",
            f"- ambiguous intrabar policy: `{summary['governance_policy']['ambiguous_intrabar_policy']}`",
            f"- same-candle entry/exit policy: `{summary['governance_policy']['same_candle_entry_exit_policy']}`",
            f"- conservative mode policy: `{summary['governance_policy']['conservative_mode_policy']}`",
            f"- tick data requirement policy: `{summary['governance_policy']['tick_data_requirement_policy']}`",
            "",
            "## Gates",
            "",
            f"- ambiguity governance gate: `{summary['ambiguity_governance_gate']}`",
            f"- paper signal stream gate: `{summary['paper_signal_stream_gate']}`",
            f"- live gate: `{summary['live_gate']}`",
            f"- deployment gate: `{summary['deployment_gate']}`",
            f"- order_send gate: `{summary['order_send_gate']}`",
            f"- broker gate: `{summary['broker_gate']}`",
            "",
            "## Limitations",
            "",
            "- M1 OHLC data cannot resolve true intrabar path ordering.",
            "- Tick data, bid/ask spread, and broker fill rules would materially improve confidence.",
            "- Ambiguous cases are not reinterpreted as wins.",
            "- Conservative-loss mode is stress-test only and is not the primary outcome metric.",
            "- No Strategy 3 rule is changed by this governance report.",
            "",
            "## Safety",
            "",
            "- no live trading",
            "- no Telegram",
            "- no signal stream",
            "- no orders",
            "- no broker execution",
            "- no order_send",
            "- no lot sizing or account risk sizing",
            "- no Strategy 3 VWAP/sigma/cooldown/entry/TP/SL/filter changes",
            "- no Strategy 2 touch",
            "- no Adelin touch",
            "- no data/XAUUSD/*.csv mutation",
            "",
            "## Next Recommendation",
            "",
            "Keep Strategy 3 paper-only. If a future signal-stream governance branch is opened, it must explicitly carry ambiguity labels and must not promote the strategy to live trading.",
            "",
        ]
    )
    rendered = "\n".join(lines)
    (output_dir / "strategy_3_fill_model_ambiguity_governance.md").write_text(rendered, encoding="utf-8")
    docs_path.write_text(rendered, encoding="utf-8")


def run_governance(cfg: AmbiguityGovernanceConfig) -> dict[str, Any]:
    started = perf_counter()
    audit_rows = _read_csv(cfg.fill_model_audit_dir / "fill_model_audit_per_signal.csv")
    audit_summary = _read_json(cfg.fill_model_audit_dir / "fill_model_audit_summary.json")
    sensitivity = _read_json(cfg.fill_model_audit_dir / "fill_model_sensitivity_flags.json")
    frame, forward_timeframe_used, forward_warnings = load_forward_frame(cfg)
    per_signal = build_per_signal_rows(audit_rows, frame)
    type_summary = build_type_summary(per_signal)
    impact_summary = build_impact_summary(audit_rows, per_signal)
    gate, stream_gate, gate_details = compute_gates(audit_rows, per_signal)
    policy = governance_policy(gate, stream_gate)
    summary = build_summary(
        cfg=cfg,
        audit_rows=audit_rows,
        per_signal=per_signal,
        type_summary=type_summary,
        impact_summary=impact_summary,
        policy=policy,
        audit_summary=audit_summary,
        sensitivity=sensitivity,
        forward_timeframe_used=forward_timeframe_used,
        forward_warnings=forward_warnings,
        gate_details=gate_details,
        runtime_seconds=perf_counter() - started,
    )
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(cfg.output_dir / "ambiguity_governance_per_signal.csv", per_signal, PER_SIGNAL_FIELDS)
    _write_csv(cfg.output_dir / "ambiguity_type_summary.csv", type_summary, TYPE_SUMMARY_FIELDS)
    _write_csv(cfg.output_dir / "ambiguity_impact_summary.csv", impact_summary, IMPACT_FIELDS)
    _write_json(cfg.output_dir / "ambiguity_governance_summary.json", summary)
    _write_json(cfg.output_dir / "ambiguity_governance_policy.json", policy)
    write_report(cfg.output_dir, cfg.docs_path, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = AmbiguityGovernanceConfig(
        symbol=str(args.symbol),
        data_dir=str(args.data_dir),
        fill_model_audit_dir=Path(args.fill_model_audit_dir),
        lifecycle_outcomes_path=Path(args.lifecycle_outcomes_path),
        paper_signals_path=Path(args.paper_signals_path),
        output_dir=Path(args.output_dir),
        docs_path=Path(args.docs_path),
        dry_run=bool(args.dry_run),
        forward_timeframe=str(args.forward_timeframe),
        fallback_timeframe=str(args.fallback_timeframe),
    )
    print(json.dumps(run_governance(cfg), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
