from __future__ import annotations

import argparse
import csv
import json
import sys
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
FILL_MODEL_REFERENCE = "PAPER_REFERENCE_FILL_AT_SIGNAL"
FILL_MODEL_UNRESOLVED = "UNRESOLVED_FILL_MODEL"
TIMEOUT_POLICY_SOURCE = "BACKTEST_MAX_SIM_BARS_480"
PROJECT_PIP_CONVENTION = "1_USD_10_PIPS"
PIPS_PER_USD_XAUUSD = 10.0
DEFAULT_OUTPUT_DIR = Path("backtests/reports/strategy_3_paper_lifecycle_outcomes")
DEFAULT_DOCS_PATH = Path("docs/research/strategy_3_paper_lifecycle_outcome_tracker.md")
DEFAULT_MAX_FORWARD_BARS = 480
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
    "signal_stream_enabled": False,
    "lot_sizing_enabled": False,
    "real_position_management_enabled": False,
}

EVENT_FIELDS = [
    "event_id",
    "signal_id",
    "decision_timestamp",
    "event_timestamp",
    "symbol",
    "direction",
    "lifecycle_state",
    "fill_model",
    "paper_only",
    "details",
]
OUTCOME_FIELDS = [
    "event_id",
    "signal_id",
    "decision_timestamp",
    "symbol",
    "direction",
    "signal_status",
    "block_reason",
    "fill_model",
    "entry_price",
    "stop_loss",
    "take_profit",
    "risk_distance_usd",
    "risk_distance_pips",
    "entry_status",
    "entry_timestamp",
    "outcome_status",
    "outcome_timestamp",
    "exit_price",
    "outcome_r",
    "bars_to_entry",
    "bars_to_outcome",
    "minutes_to_outcome",
    "max_favorable_excursion_usd",
    "max_adverse_excursion_usd",
    "ambiguous_intrabar_flag",
    "insufficient_forward_data_flag",
    "still_open_flag",
    "context_gate_status",
    "prefix_compatible",
    "paper_only",
]


@dataclass(frozen=True)
class LifecycleConfig:
    symbol: str
    data_dir: str
    paper_signals_path: Path
    evidence_refresh_summary_path: Path
    dashboard_summary_path: Path
    output_dir: Path
    docs_path: Path
    dry_run: bool
    clean_context_only: bool
    include_legacy: bool
    fill_model: str
    forward_timeframe: str
    fallback_timeframe: str
    max_forward_bars: int


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strategy 3 paper lifecycle and outcome tracker")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--paper-signals-path", default="backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv")
    parser.add_argument("--evidence-refresh-summary-path", default="backtests/reports/strategy_3_paper_evidence_refresh/paper_evidence_refresh_summary.json")
    parser.add_argument("--dashboard-summary-path", default="backtests/reports/strategy_3_paper_accumulation_dashboard/paper_accumulation_summary.json")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--docs-path", default=str(DEFAULT_DOCS_PATH))
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--include-legacy", action="store_true", default=False, help="Include paper rows without data_context_hash. Default excludes legacy rows.")
    parser.add_argument("--fill-model", choices=[FILL_MODEL_REFERENCE, FILL_MODEL_UNRESOLVED], default=FILL_MODEL_REFERENCE)
    parser.add_argument("--forward-timeframe", default="M1")
    parser.add_argument("--fallback-timeframe", default="M5")
    parser.add_argument("--max-forward-bars", type=int, default=DEFAULT_MAX_FORWARD_BARS)
    return parser.parse_args(argv)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


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


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "accepted"}


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


def _iso(value: Any) -> str | None:
    ts = _parse_ts(value)
    return ts.isoformat() if ts else None


def _risk_distance(row: dict[str, Any], entry: float | None, stop: float | None) -> float | None:
    fallback = _float(row.get("risk_distance_usd") or row.get("risk_distance"))
    if entry is not None and stop is not None:
        distance = abs(entry - stop)
        if fallback is not None and abs(distance - fallback) <= 0.0001:
            return round(fallback, 6)
        return round(distance, 6)
    return round(abs(fallback), 6) if fallback is not None else None


def _signal_id(row: dict[str, Any], index: int) -> str:
    raw = row.get("signal_id") or row.get("event_id")
    if raw:
        return str(raw)
    return "|".join(
        [
            str(row.get("symbol") or ""),
            str(row.get("strategy") or STRATEGY_NAME),
            str(row.get("signal_timestamp") or ""),
            str(row.get("direction") or ""),
            str(index),
        ]
    )


def _event(event_id: str, signal_id: str, decision_timestamp: str | None, event_timestamp: str | None, symbol: str, direction: str, state: str, fill_model: str, details: str = "") -> dict[str, Any]:
    return {
        "event_id": event_id,
        "signal_id": signal_id,
        "decision_timestamp": decision_timestamp,
        "event_timestamp": event_timestamp,
        "symbol": symbol,
        "direction": direction,
        "lifecycle_state": state,
        "fill_model": fill_model,
        "paper_only": True,
        "details": details,
    }


def select_signal_rows(rows: list[dict[str, Any]], cfg: LifecycleConfig) -> tuple[list[dict[str, Any]], int]:
    strategy_rows = [row for row in rows if str(row.get("strategy") or STRATEGY_NAME) == STRATEGY_NAME and str(row.get("symbol") or cfg.symbol) == cfg.symbol]
    if cfg.include_legacy or not cfg.clean_context_only:
        return strategy_rows, 0
    clean = [row for row in strategy_rows if str(row.get("data_context_hash") or "").strip()]
    return clean, len(strategy_rows) - len(clean)


def load_forward_frame(cfg: LifecycleConfig) -> tuple[pd.DataFrame, str, list[str]]:
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


def _compute_excursions(direction: str, entry: float, high: float, low: float) -> tuple[float, float]:
    if direction == "LONG":
        mfe = max(0.0, high - entry)
        mae = max(0.0, entry - low)
    else:
        mfe = max(0.0, entry - low)
        mae = max(0.0, high - entry)
    return mfe, mae


def evaluate_forward_outcome(row: dict[str, Any], forward_frame: pd.DataFrame, cfg: LifecycleConfig) -> dict[str, Any]:
    decision_time = _parse_ts(row.get("signal_timestamp"))
    direction = str(row.get("direction") or "").upper()
    entry = _float(row.get("entry_price") or row.get("entry_reference_price"))
    stop = _float(row.get("stop_loss") or row.get("sl"))
    target = _float(row.get("take_profit") or row.get("tp1") or row.get("target"))
    risk = _risk_distance(row, entry, stop)
    base = {
        "entry_price": entry,
        "stop_loss": stop,
        "take_profit": target,
        "risk_distance_usd": risk,
        "risk_distance_pips": round(risk * PIPS_PER_USD_XAUUSD, 6) if risk is not None else None,
        "entry_status": "ENTRY_FILLED" if cfg.fill_model == FILL_MODEL_REFERENCE else "ENTRY_NOT_TRIGGERED",
        "entry_timestamp": decision_time.isoformat() if decision_time and cfg.fill_model == FILL_MODEL_REFERENCE else None,
        "bars_to_entry": 0 if cfg.fill_model == FILL_MODEL_REFERENCE else None,
        "outcome_status": None,
        "outcome_timestamp": None,
        "exit_price": None,
        "outcome_r": None,
        "bars_to_outcome": None,
        "minutes_to_outcome": None,
        "max_favorable_excursion_usd": None,
        "max_adverse_excursion_usd": None,
        "ambiguous_intrabar_flag": False,
        "insufficient_forward_data_flag": False,
        "still_open_flag": False,
    }
    if cfg.fill_model == FILL_MODEL_UNRESOLVED:
        return {**base, "entry_status": "ENTRY_NOT_TRIGGERED", "outcome_status": "INSUFFICIENT_METHOD_SPECIFICATION"}
    if decision_time is None or direction not in {"LONG", "SHORT"} or entry is None or stop is None or target is None or risk is None or risk <= 0:
        return {**base, "outcome_status": "INSUFFICIENT_METHOD_SPECIFICATION", "insufficient_forward_data_flag": True}
    if forward_frame.empty:
        return {**base, "outcome_status": "INSUFFICIENT_FORWARD_DATA", "insufficient_forward_data_flag": True}

    times = pd.to_datetime(forward_frame["time"], utc=True)
    future = forward_frame.loc[times > pd.Timestamp(decision_time)].copy().head(cfg.max_forward_bars)
    if future.empty:
        return {**base, "outcome_status": "INSUFFICIENT_FORWARD_DATA", "insufficient_forward_data_flag": True}

    max_favorable = 0.0
    max_adverse = 0.0
    last_close: float | None = None
    last_time: datetime | None = None
    bars_seen = 0
    for _, candle in future.iterrows():
        bars_seen += 1
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
        when = _parse_ts(candle["time"])
        last_close = close
        last_time = when
        mfe, mae = _compute_excursions(direction, entry, high, low)
        max_favorable = max(max_favorable, mfe)
        max_adverse = max(max_adverse, mae)
        if direction == "LONG":
            tp_hit = high >= target
            sl_hit = low <= stop
        else:
            tp_hit = low <= target
            sl_hit = high >= stop
        minutes_to_outcome = round((when - decision_time).total_seconds() / 60.0, 2) if when else None
        common = {
            **base,
            "outcome_timestamp": when.isoformat() if when else None,
            "bars_to_outcome": bars_seen,
            "minutes_to_outcome": minutes_to_outcome,
            "max_favorable_excursion_usd": round(max_favorable, 6),
            "max_adverse_excursion_usd": round(max_adverse, 6),
        }
        if tp_hit and sl_hit:
            return {
                **common,
                "outcome_status": "AMBIGUOUS_INTRABAR",
                "ambiguous_intrabar_flag": True,
            }
        if tp_hit:
            return {
                **common,
                "outcome_status": "TP_HIT",
                "exit_price": target,
                "outcome_r": round(abs(target - entry) / risk, 6),
            }
        if sl_hit:
            return {
                **common,
                "outcome_status": "SL_HIT",
                "exit_price": stop,
                "outcome_r": -1.0,
            }

    if len(future) >= cfg.max_forward_bars and last_close is not None:
        if direction == "LONG":
            outcome_r = (last_close - entry) / risk
        else:
            outcome_r = (entry - last_close) / risk
        return {
            **base,
            "outcome_status": "TIMEOUT_CLOSE",
            "outcome_timestamp": last_time.isoformat() if last_time else None,
            "exit_price": last_close,
            "outcome_r": round(outcome_r, 6),
            "bars_to_outcome": bars_seen,
            "minutes_to_outcome": round((last_time - decision_time).total_seconds() / 60.0, 2) if last_time else None,
            "max_favorable_excursion_usd": round(max_favorable, 6),
            "max_adverse_excursion_usd": round(max_adverse, 6),
        }
    return {
        **base,
        "outcome_status": "STILL_OPEN",
        "max_favorable_excursion_usd": round(max_favorable, 6),
        "max_adverse_excursion_usd": round(max_adverse, 6),
        "still_open_flag": True,
    }


def build_lifecycle_rows(rows: list[dict[str, Any]], forward_frame: pd.DataFrame, cfg: LifecycleConfig, evidence: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    context_gate_status = evidence.get("context", {}).get("context_gate_status") or evidence.get("gate_status", {}).get("context_gate")
    for index, row in enumerate(rows):
        signal_id = _signal_id(row, index)
        event_id = f"strategy3-lifecycle-{index + 1:05d}"
        decision_ts = _iso(row.get("signal_timestamp"))
        symbol = str(row.get("symbol") or cfg.symbol)
        direction = str(row.get("direction") or "")
        accepted = _bool(row.get("cooldown_accepted")) or str(row.get("cooldown_status") or "").lower() == "accepted"
        block_reason = "" if accepted else str(row.get("cooldown_block_reason") or row.get("block_reason") or "blocked_unspecified")
        prefix_compatible = bool(str(row.get("data_context_hash") or "").strip())
        if not accepted:
            events.append(_event(event_id, signal_id, decision_ts, decision_ts, symbol, direction, "SIGNAL_BLOCKED", cfg.fill_model, block_reason))
            outcomes.append(
                {
                    "event_id": event_id,
                    "signal_id": signal_id,
                    "decision_timestamp": decision_ts,
                    "symbol": symbol,
                    "direction": direction,
                    "signal_status": "SIGNAL_BLOCKED",
                    "block_reason": block_reason,
                    "fill_model": cfg.fill_model,
                    "entry_status": "ENTRY_NOT_TRIGGERED",
                    "outcome_status": "SIGNAL_BLOCKED",
                    "ambiguous_intrabar_flag": False,
                    "insufficient_forward_data_flag": False,
                    "still_open_flag": False,
                    "context_gate_status": context_gate_status,
                    "prefix_compatible": prefix_compatible,
                    "paper_only": True,
                }
            )
            continue
        events.append(_event(event_id, signal_id, decision_ts, decision_ts, symbol, direction, "SIGNAL_ACCEPTED", cfg.fill_model))
        outcome = evaluate_forward_outcome(row, forward_frame, cfg)
        if outcome.get("entry_status") == "ENTRY_FILLED":
            events.append(_event(event_id, signal_id, decision_ts, outcome.get("entry_timestamp"), symbol, direction, "ENTRY_FILLED", cfg.fill_model))
            events.append(_event(event_id, signal_id, decision_ts, outcome.get("entry_timestamp"), symbol, direction, "PAPER_POSITION_OPEN", cfg.fill_model))
        outcome_state = str(outcome.get("outcome_status") or "INSUFFICIENT_FORWARD_DATA")
        if outcome_state not in {"STILL_OPEN", "INSUFFICIENT_METHOD_SPECIFICATION"}:
            events.append(_event(event_id, signal_id, decision_ts, outcome.get("outcome_timestamp"), symbol, direction, outcome_state, cfg.fill_model))
        if outcome_state in {"TP_HIT", "SL_HIT", "TIMEOUT_CLOSE"}:
            events.append(_event(event_id, signal_id, decision_ts, outcome.get("outcome_timestamp"), symbol, direction, "OUTCOME_RECORDED", cfg.fill_model))
        elif outcome_state == "STILL_OPEN":
            events.append(_event(event_id, signal_id, decision_ts, None, symbol, direction, "STILL_OPEN", cfg.fill_model))
        outcomes.append(
            {
                "event_id": event_id,
                "signal_id": signal_id,
                "decision_timestamp": decision_ts,
                "symbol": symbol,
                "direction": direction,
                "signal_status": "SIGNAL_ACCEPTED",
                "block_reason": "",
                "fill_model": cfg.fill_model,
                **outcome,
                "context_gate_status": context_gate_status,
                "prefix_compatible": prefix_compatible,
                "paper_only": True,
            }
        )
    return events, outcomes


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _streak(values: list[float]) -> int:
    best = 0
    current = 0
    for value in values:
        if value < 0:
            current += 1
            best = max(best, current)
        elif value > 0:
            current = 0
    return best


def build_summary(
    *,
    cfg: LifecycleConfig,
    all_rows: list[dict[str, Any]],
    tracked_rows: list[dict[str, Any]],
    legacy_excluded: int,
    outcomes: list[dict[str, Any]],
    forward_timeframe_used: str,
    forward_warnings: list[str],
    evidence: dict[str, Any],
    dashboard: dict[str, Any],
    runtime_seconds: float,
) -> dict[str, Any]:
    accepted = [row for row in tracked_rows if _bool(row.get("cooldown_accepted")) or str(row.get("cooldown_status") or "").lower() == "accepted"]
    blocked = [row for row in tracked_rows if not (_bool(row.get("cooldown_accepted")) or str(row.get("cooldown_status") or "").lower() == "accepted")]
    accepted_outcomes = [row for row in outcomes if row.get("signal_status") == "SIGNAL_ACCEPTED"]
    required_missing = [row for row in accepted_outcomes if row.get("outcome_status") == "INSUFFICIENT_METHOD_SPECIFICATION"]
    tp = [row for row in accepted_outcomes if row.get("outcome_status") == "TP_HIT"]
    sl = [row for row in accepted_outcomes if row.get("outcome_status") == "SL_HIT"]
    timeout = [row for row in accepted_outcomes if row.get("outcome_status") == "TIMEOUT_CLOSE"]
    still_open = [row for row in accepted_outcomes if row.get("outcome_status") == "STILL_OPEN"]
    ambiguous = [row for row in accepted_outcomes if row.get("outcome_status") == "AMBIGUOUS_INTRABAR"]
    insufficient = [row for row in accepted_outcomes if row.get("outcome_status") == "INSUFFICIENT_FORWARD_DATA"]
    decisive_denominator = len(tp) + len(sl)
    deterministic = [row for row in accepted_outcomes if row.get("outcome_status") in {"TP_HIT", "SL_HIT", "TIMEOUT_CLOSE"}]
    outcome_rs = [float(row["outcome_r"]) for row in deterministic if _float(row.get("outcome_r")) is not None]
    risk_distances = [float(row["risk_distance_usd"]) for row in accepted_outcomes if _float(row.get("risk_distance_usd")) is not None]
    unresolved_fill = cfg.fill_model == FILL_MODEL_UNRESOLVED
    mostly_missing = len(accepted) > 0 and len(required_missing) / len(accepted) >= 0.5
    if unresolved_fill or mostly_missing:
        lifecycle_gate = "BLOCKED"
    elif insufficient:
        lifecycle_gate = "WARNING"
    else:
        lifecycle_gate = "PASSED"
    sample_status = "INSUFFICIENT_N" if len(deterministic) < 100 else "DESCRIPTIVE_ONLY_WATCHLIST"
    return {
        "run_finished_at": _utc_now(),
        "runtime_seconds": round(runtime_seconds, 4),
        "dry_run": cfg.dry_run,
        "strategy": STRATEGY_NAME,
        "symbol": cfg.symbol,
        "inputs": {
            "paper_signals_path": str(cfg.paper_signals_path),
            "evidence_refresh_summary_path": str(cfg.evidence_refresh_summary_path),
            "dashboard_summary_path": str(cfg.dashboard_summary_path),
            "data_dir": cfg.data_dir,
        },
        "methodology": {
            "fill_model": cfg.fill_model,
            "fill_model_reason": "Strategy 3 paper scanner records entry_price as current_price/reference price at the decision timestamp; backtest simulation evaluates forward M1 after the cutoff.",
            "forward_timeframe_requested": cfg.forward_timeframe,
            "forward_timeframe_used": forward_timeframe_used,
            "closed_candles_only": True,
            "forward_candles_start": "strictly_after_signal_decision_timestamp",
            "timeout_policy_source": TIMEOUT_POLICY_SOURCE,
            "max_forward_bars": cfg.max_forward_bars,
            "ambiguous_intrabar_policy": "TP and SL touched inside the same candle are AMBIGUOUS_INTRABAR and excluded from decisive win rate.",
            "project_pip_convention": PROJECT_PIP_CONVENTION,
        },
        "selection": {
            "total_paper_rows": len(all_rows),
            "tracked_signals": len(tracked_rows),
            "legacy_excluded": legacy_excluded,
            "clean_context_only": cfg.clean_context_only and not cfg.include_legacy,
            "context_gate_status": evidence.get("context", {}).get("context_gate_status") or evidence.get("gate_status", {}).get("context_gate"),
            "dashboard_sample_status": dashboard.get("sample_size", {}).get("sample_size_status"),
        },
        "total_signals": len(tracked_rows),
        "accepted_signals": len(accepted),
        "blocked_signals": len(blocked),
        "accepted_with_outcome": len(deterministic),
        "entry_filled_count": sum(1 for row in accepted_outcomes if row.get("entry_status") == "ENTRY_FILLED"),
        "entry_not_triggered_count": sum(1 for row in accepted_outcomes if row.get("entry_status") != "ENTRY_FILLED"),
        "tp_hit_count": len(tp),
        "sl_hit_count": len(sl),
        "timeout_count": len(timeout),
        "still_open_count": len(still_open),
        "ambiguous_intrabar_count": len(ambiguous),
        "insufficient_forward_data_count": len(insufficient),
        "method_specification_missing_count": len(required_missing),
        "gross_win_rate": _rate(len(tp), len(accepted)),
        "gross_win_rate_denominator": "accepted_signals",
        "decisive_win_rate_tp_vs_sl_only": _rate(len(tp), decisive_denominator),
        "decisive_win_rate_denominator": "tp_hit_count + sl_hit_count",
        "timeout_rate": _rate(len(timeout), len(accepted)),
        "still_open_rate": _rate(len(still_open), len(accepted)),
        "ambiguous_rate": _rate(len(ambiguous), len(accepted)),
        "average_outcome_r": round(sum(outcome_rs) / len(outcome_rs), 6) if outcome_rs else None,
        "median_outcome_r": round(float(median(outcome_rs)), 6) if outcome_rs else None,
        "total_outcome_r": round(sum(outcome_rs), 6) if outcome_rs else None,
        "max_losing_streak": _streak(outcome_rs),
        "median_risk_distance_usd": round(float(median(risk_distances)), 6) if risk_distances else None,
        "median_risk_distance_pips": round(float(median(risk_distances)) * PIPS_PER_USD_XAUUSD, 6) if risk_distances else None,
        "sample_status": sample_status,
        "win_rate_interpretation": "DESCRIPTIVE_ONLY_SMALL_N" if len(deterministic) < 100 else "DESCRIPTIVE_ONLY",
        "lifecycle_gate": lifecycle_gate,
        "sample_gate": "INSUFFICIENT_N" if len(deterministic) < 100 else "WATCHLIST_ONLY",
        "paper_validated_gate": "BLOCKED",
        "live_gate": "BLOCKED",
        "deployment_gate": "BLOCKED",
        "order_send_gate": "BLOCKED",
        "broker_gate": "BLOCKED",
        "forward_warnings": forward_warnings,
        "verdict_flags": [
            "PAPER_LIFECYCLE_TRACKER_CREATED",
            f"LIFECYCLE_GATE_{lifecycle_gate}",
            "FILL_MODEL_SPECIFIED" if not unresolved_fill else "FILL_MODEL_UNRESOLVED",
            "WR_DESCRIPTIVE_ONLY_SMALL_N" if len(deterministic) < 100 else "WR_DESCRIPTIVE_ONLY",
            "NO_LIVE_DEPLOYMENT_DECISION",
            "STRATEGY_3_REMAINS_PAPER_ONLY",
        ],
        "safety": dict(SAFETY),
    }


def open_positions(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        {
            "signal_id": row.get("signal_id"),
            "decision_timestamp": row.get("decision_timestamp"),
            "direction": row.get("direction"),
            "entry_price": row.get("entry_price"),
            "stop_loss": row.get("stop_loss"),
            "take_profit": row.get("take_profit"),
            "outcome_status": row.get("outcome_status"),
        }
        for row in outcomes
        if row.get("outcome_status") == "STILL_OPEN"
    ]
    return {"paper_only": True, "open_position_count": len(rows), "positions": rows}


def write_report(output_dir: Path, docs_path: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Strategy 3 Paper Lifecycle Outcome Tracker",
        "",
        "This tracker is paper-only. It does not send alerts, enable Telegram, call broker execution, place orders, size positions, or change Strategy 3 logic.",
        "",
        "## Objective",
        "",
        "Track accepted Strategy 3 paper signals after detection and classify their report-only lifecycle and outcome using forward closed candles.",
        "",
        "## Inputs",
        "",
        f"- paper signals: `{summary['inputs']['paper_signals_path']}`",
        f"- evidence refresh summary: `{summary['inputs']['evidence_refresh_summary_path']}`",
        f"- dashboard summary: `{summary['inputs']['dashboard_summary_path']}`",
        f"- data directory: `{summary['inputs']['data_dir']}`",
        "",
        "## Methodology",
        "",
        f"- fill model: `{summary['methodology']['fill_model']}`",
        f"- fill model reason: {summary['methodology']['fill_model_reason']}",
        f"- forward timeframe used: `{summary['methodology']['forward_timeframe_used']}`",
        f"- forward candles start: `{summary['methodology']['forward_candles_start']}`",
        f"- timeout policy source: `{summary['methodology']['timeout_policy_source']}`",
        f"- max forward bars: `{summary['methodology']['max_forward_bars']}`",
        f"- ambiguous intrabar policy: {summary['methodology']['ambiguous_intrabar_policy']}",
        f"- pip convention: `{summary['methodology']['project_pip_convention']}`",
        "",
        "## Lifecycle States",
        "",
        "- `SIGNAL_ACCEPTED`",
        "- `SIGNAL_BLOCKED`",
        "- `ENTRY_FILLED`",
        "- `ENTRY_NOT_TRIGGERED`",
        "- `PAPER_POSITION_OPEN`",
        "- `TP_HIT`",
        "- `SL_HIT`",
        "- `TIMEOUT_CLOSE`",
        "- `STILL_OPEN`",
        "- `AMBIGUOUS_INTRABAR`",
        "- `INSUFFICIENT_FORWARD_DATA`",
        "- `OUTCOME_RECORDED`",
        "",
        "## Results",
        "",
        f"- tracked signals: `{summary['total_signals']}`",
        f"- legacy excluded: `{summary['selection']['legacy_excluded']}`",
        f"- accepted/blocked: `{summary['accepted_signals']}/{summary['blocked_signals']}`",
        f"- entry filled: `{summary['entry_filled_count']}`",
        f"- TP/SL/timeout: `{summary['tp_hit_count']}/{summary['sl_hit_count']}/{summary['timeout_count']}`",
        f"- still open: `{summary['still_open_count']}`",
        f"- ambiguous intrabar: `{summary['ambiguous_intrabar_count']}`",
        f"- insufficient forward data: `{summary['insufficient_forward_data_count']}`",
        f"- median risk distance: `{summary['median_risk_distance_usd']}` USD / `{summary['median_risk_distance_pips']}` pips",
        "",
        "## Win Rate Definitions",
        "",
        f"- gross win rate: `{summary['gross_win_rate']}` using denominator `{summary['gross_win_rate_denominator']}`",
        f"- decisive win rate TP vs SL only: `{summary['decisive_win_rate_tp_vs_sl_only']}` using denominator `{summary['decisive_win_rate_denominator']}`",
        f"- interpretation: `{summary['win_rate_interpretation']}`",
        "",
        "AMBIGUOUS_INTRABAR, STILL_OPEN, INSUFFICIENT_FORWARD_DATA, ENTRY_NOT_TRIGGERED, and TIMEOUT_CLOSE are not silently counted as wins.",
        "",
        "## Gates",
        "",
        f"- lifecycle gate: `{summary['lifecycle_gate']}`",
        f"- sample gate: `{summary['sample_gate']}`",
        f"- paper validated gate: `{summary['paper_validated_gate']}`",
        f"- live gate: `{summary['live_gate']}`",
        f"- deployment gate: `{summary['deployment_gate']}`",
        f"- order_send gate: `{summary['order_send_gate']}`",
        f"- broker gate: `{summary['broker_gate']}`",
        "",
        "## Sample Limitations",
        "",
        "Outcome data is post-signal evidence only. It must not be used to redefine signal validity, regime labels, filters, cooldown, or entry/TP/SL logic in this branch.",
        "",
        "## Safety",
        "",
        "- no live trading",
        "- no Telegram",
        "- no orders",
        "- no broker execution",
        "- no order_send",
        "- no signal stream",
        "- no lot size or account risk sizing",
        "- no Strategy 3 VWAP/sigma/cooldown/entry/TP/SL/filter changes",
        "- no Strategy 2 touch",
        "- no Adelin touch",
        "- no data/XAUUSD/*.csv mutation",
        "",
        "## Next Recommendation",
        "",
        "Continue paper accumulation and refresh lifecycle outcomes after additional clean accepted signals. Treat all outcome metrics as descriptive only until the sample is materially larger.",
        "",
    ]
    rendered = "\n".join(lines)
    (output_dir / "paper_lifecycle_outcome_tracker.md").write_text(rendered, encoding="utf-8")
    docs_path.write_text(rendered, encoding="utf-8")


def run_tracker(cfg: LifecycleConfig) -> dict[str, Any]:
    started = perf_counter()
    all_rows = _read_csv(cfg.paper_signals_path)
    tracked_rows, legacy_excluded = select_signal_rows(all_rows, cfg)
    evidence = _read_json(cfg.evidence_refresh_summary_path)
    dashboard = _read_json(cfg.dashboard_summary_path)
    forward_frame, forward_timeframe_used, forward_warnings = load_forward_frame(cfg)
    events, outcomes = build_lifecycle_rows(tracked_rows, forward_frame, cfg, evidence)
    summary = build_summary(
        cfg=cfg,
        all_rows=all_rows,
        tracked_rows=tracked_rows,
        legacy_excluded=legacy_excluded,
        outcomes=outcomes,
        forward_timeframe_used=forward_timeframe_used,
        forward_warnings=forward_warnings,
        evidence=evidence,
        dashboard=dashboard,
        runtime_seconds=perf_counter() - started,
    )
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(cfg.output_dir / "paper_lifecycle_events.csv", events, EVENT_FIELDS)
    _write_csv(cfg.output_dir / "paper_signal_outcomes.csv", outcomes, OUTCOME_FIELDS)
    _write_json(cfg.output_dir / "paper_open_positions.json", open_positions(outcomes))
    _write_json(cfg.output_dir / "paper_lifecycle_summary.json", summary)
    write_report(cfg.output_dir, cfg.docs_path, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = LifecycleConfig(
        symbol=str(args.symbol),
        data_dir=str(args.data_dir),
        paper_signals_path=Path(args.paper_signals_path),
        evidence_refresh_summary_path=Path(args.evidence_refresh_summary_path),
        dashboard_summary_path=Path(args.dashboard_summary_path),
        output_dir=Path(args.output_dir),
        docs_path=Path(args.docs_path),
        dry_run=bool(args.dry_run),
        clean_context_only=not bool(args.include_legacy),
        include_legacy=bool(args.include_legacy),
        fill_model=str(args.fill_model),
        forward_timeframe=str(args.forward_timeframe),
        fallback_timeframe=str(args.fallback_timeframe),
        max_forward_bars=int(args.max_forward_bars),
    )
    print(json.dumps(run_tracker(cfg), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
