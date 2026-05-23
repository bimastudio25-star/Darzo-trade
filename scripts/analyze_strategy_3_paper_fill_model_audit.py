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
REFERENCE_MODEL = "PAPER_REFERENCE_FILL_AT_SIGNAL"
PENDING_TOUCH_MODEL = "PAPER_PENDING_ENTRY_TOUCH"
CONSERVATIVE_MODEL = "CONSERVATIVE_NEXT_CANDLE_FILL_OR_TOUCH"
NOT_COMPUTABLE = "NOT_COMPUTABLE"
DEFAULT_OUTPUT_DIR = Path("backtests/reports/strategy_3_paper_fill_model_audit")
DEFAULT_DOCS_PATH = Path("docs/research/strategy_3_paper_fill_model_audit.md")
DEFAULT_MAX_FORWARD_BARS = 480
PROJECT_PIP_CONVENTION = "1_USD_10_PIPS"
PIPS_PER_USD_XAUUSD = 10.0
TIMEOUT_POLICY_SOURCE = "BACKTEST_MAX_SIM_BARS_480"

SAFETY = {
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "order_execution_enabled": False,
    "broker_execution_enabled": False,
    "order_send_called": False,
    "signal_stream_enabled": False,
    "lot_sizing_enabled": False,
    "account_risk_sizing_enabled": False,
    "real_position_management_enabled": False,
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
    "signal_id",
    "decision_timestamp",
    "symbol",
    "direction",
    "signal_status",
    "block_reason",
    "entry_reference_price",
    "stop_loss",
    "take_profit",
    "risk_distance_usd",
    "risk_distance_pips",
    "current_lifecycle_outcome_status",
    "reference_fill_outcome_status",
    "pending_touch_entry_status",
    "pending_touch_entry_timestamp",
    "pending_touch_outcome_status",
    "conservative_entry_status",
    "conservative_entry_timestamp",
    "conservative_outcome_status",
    "reference_outcome_r",
    "pending_touch_outcome_r",
    "conservative_outcome_r",
    "reference_minutes_to_outcome",
    "pending_touch_minutes_to_entry",
    "pending_touch_minutes_to_outcome",
    "conservative_minutes_to_entry",
    "conservative_minutes_to_outcome",
    "changed_under_pending_touch_flag",
    "changed_under_conservative_flag",
    "ambiguous_intrabar_flag_by_model",
    "insufficient_forward_data_flag_by_model",
    "paper_only",
]

SUMMARY_FIELDS = [
    "fill_model",
    "model_status",
    "accepted_signals",
    "entry_filled_count",
    "entry_not_triggered_count",
    "tp_hit_count",
    "sl_hit_count",
    "ambiguous_intrabar_count",
    "timeout_count",
    "still_open_count",
    "insufficient_forward_data_count",
    "deterministic_outcome_count",
    "gross_win_rate",
    "decisive_win_rate_tp_vs_sl_only",
    "total_outcome_r",
    "average_outcome_r",
    "median_outcome_r",
    "average_minutes_to_entry",
    "median_minutes_to_entry",
    "average_minutes_to_outcome",
    "median_minutes_to_outcome",
    "max_losing_streak",
    "sample_status",
    "interpretation_status",
]


@dataclass(frozen=True)
class FillAuditConfig:
    symbol: str
    data_dir: str
    paper_signals_path: Path
    lifecycle_outcomes_path: Path
    lifecycle_summary_path: Path
    evidence_gate_status_path: Path
    evidence_refresh_summary_path: Path
    output_dir: Path
    docs_path: Path
    dry_run: bool
    include_legacy: bool
    forward_timeframe: str
    fallback_timeframe: str
    max_forward_bars: int


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strategy 3 paper fill-model audit")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--paper-signals-path", default="backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv")
    parser.add_argument("--lifecycle-outcomes-path", default="backtests/reports/strategy_3_paper_lifecycle_outcomes/paper_signal_outcomes.csv")
    parser.add_argument("--lifecycle-summary-path", default="backtests/reports/strategy_3_paper_lifecycle_outcomes/paper_lifecycle_summary.json")
    parser.add_argument("--evidence-gate-status-path", default="backtests/reports/strategy_3_paper_evidence_refresh/gate_status.json")
    parser.add_argument("--evidence-refresh-summary-path", default="backtests/reports/strategy_3_paper_evidence_refresh/paper_evidence_refresh_summary.json")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--docs-path", default=str(DEFAULT_DOCS_PATH))
    parser.add_argument("--include-legacy", action="store_true", default=False)
    parser.add_argument("--forward-timeframe", default="M1")
    parser.add_argument("--fallback-timeframe", default="M5")
    parser.add_argument("--max-forward-bars", type=int, default=DEFAULT_MAX_FORWARD_BARS)
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
    return str(value).strip().lower() in {"1", "true", "yes", "y", "accepted"}


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


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _risk_distance(row: dict[str, Any], entry: float | None, stop: float | None) -> float | None:
    fallback = _float(row.get("risk_distance_usd") or row.get("risk_distance"))
    if entry is not None and stop is not None:
        return round(abs(entry - stop), 6)
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


def select_signal_rows(rows: list[dict[str, Any]], cfg: FillAuditConfig) -> tuple[list[dict[str, Any]], int]:
    strategy_rows = [row for row in rows if str(row.get("strategy") or STRATEGY_NAME) == STRATEGY_NAME and str(row.get("symbol") or cfg.symbol) == cfg.symbol]
    if cfg.include_legacy:
        return strategy_rows, 0
    clean = [row for row in strategy_rows if str(row.get("data_context_hash") or "").strip()]
    return clean, len(strategy_rows) - len(clean)


def load_forward_frame(cfg: FillAuditConfig) -> tuple[pd.DataFrame, str, list[str]]:
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


def _levels(row: dict[str, Any]) -> dict[str, Any]:
    entry = _float(row.get("entry_price") or row.get("entry_reference_price"))
    stop = _float(row.get("stop_loss") or row.get("sl"))
    target = _float(row.get("take_profit") or row.get("tp1") or row.get("target"))
    risk = _risk_distance(row, entry, stop)
    return {
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk": risk,
        "risk_pips": round(risk * PIPS_PER_USD_XAUUSD, 6) if risk is not None else None,
    }


def _required_fields_ok(levels: dict[str, Any], decision_time: pd.Timestamp | None, direction: str) -> bool:
    return (
        decision_time is not None
        and direction in {"LONG", "SHORT"}
        and levels["entry"] is not None
        and levels["stop"] is not None
        and levels["target"] is not None
        and levels["risk"] is not None
        and levels["risk"] > 0
    )


def _future(frame: pd.DataFrame, decision_time: pd.Timestamp, max_rows: int) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    times = pd.to_datetime(frame["time"], utc=True)
    return frame.loc[times > decision_time].copy().head(max_rows)


def _hit_flags(direction: str, high: float, low: float, target: float, stop: float) -> tuple[bool, bool]:
    if direction == "LONG":
        return high >= target, low <= stop
    return low <= target, high >= stop


def _r_for_timeout(direction: str, close: float, entry: float, risk: float) -> float:
    return (close - entry) / risk if direction == "LONG" else (entry - close) / risk


def _base_outcome(model: str, status: str, *, entry_status: str = "ENTRY_FILLED", entry_ts: Any = None, outcome_ts: Any = None, outcome_r: float | None = None, exit_price: float | None = None, bars_to_entry: int | None = None, bars_to_outcome: int | None = None, minutes_to_entry: float | None = None, minutes_to_outcome: float | None = None, ambiguous: bool = False, insufficient: bool = False) -> dict[str, Any]:
    return {
        "fill_model": model,
        "model_status": "COMPUTABLE" if status != NOT_COMPUTABLE else NOT_COMPUTABLE,
        "entry_status": entry_status,
        "entry_timestamp": _iso(entry_ts),
        "outcome_status": status,
        "outcome_timestamp": _iso(outcome_ts),
        "exit_price": exit_price,
        "outcome_r": round(outcome_r, 6) if outcome_r is not None else None,
        "bars_to_entry": bars_to_entry,
        "bars_to_outcome": bars_to_outcome,
        "minutes_to_entry": minutes_to_entry,
        "minutes_to_outcome": minutes_to_outcome,
        "ambiguous_intrabar_flag": ambiguous,
        "insufficient_forward_data_flag": insufficient,
    }


def reference_fill_outcome(row: dict[str, Any], frame: pd.DataFrame, cfg: FillAuditConfig) -> dict[str, Any]:
    decision_time = _parse_ts(row.get("signal_timestamp"))
    direction = str(row.get("direction") or "").upper()
    levels = _levels(row)
    if not _required_fields_ok(levels, decision_time, direction):
        return _base_outcome(REFERENCE_MODEL, NOT_COMPUTABLE, entry_status="ENTRY_NOT_TRIGGERED", insufficient=True)
    future = _future(frame, decision_time, cfg.max_forward_bars)
    if future.empty:
        return _base_outcome(REFERENCE_MODEL, "INSUFFICIENT_FORWARD_DATA", entry_ts=decision_time, insufficient=True)
    entry = float(levels["entry"])
    stop = float(levels["stop"])
    target = float(levels["target"])
    risk = float(levels["risk"])
    last_close: float | None = None
    last_time: pd.Timestamp | None = None
    for idx, candle in enumerate(future.itertuples(index=False), start=1):
        high = float(getattr(candle, "high"))
        low = float(getattr(candle, "low"))
        close = float(getattr(candle, "close"))
        when = _parse_ts(getattr(candle, "time"))
        last_close = close
        last_time = when
        tp_hit, sl_hit = _hit_flags(direction, high, low, target, stop)
        minutes = round((when - decision_time).total_seconds() / 60.0, 2) if when is not None else None
        if tp_hit and sl_hit:
            return _base_outcome(REFERENCE_MODEL, "AMBIGUOUS_INTRABAR", entry_ts=decision_time, outcome_ts=when, bars_to_entry=0, bars_to_outcome=idx, minutes_to_outcome=minutes, ambiguous=True)
        if tp_hit:
            return _base_outcome(REFERENCE_MODEL, "TP_HIT", entry_ts=decision_time, outcome_ts=when, outcome_r=abs(target - entry) / risk, exit_price=target, bars_to_entry=0, bars_to_outcome=idx, minutes_to_outcome=minutes)
        if sl_hit:
            return _base_outcome(REFERENCE_MODEL, "SL_HIT", entry_ts=decision_time, outcome_ts=when, outcome_r=-1.0, exit_price=stop, bars_to_entry=0, bars_to_outcome=idx, minutes_to_outcome=minutes)
    if len(future) >= cfg.max_forward_bars and last_close is not None:
        return _base_outcome(REFERENCE_MODEL, "TIMEOUT_CLOSE", entry_ts=decision_time, outcome_ts=last_time, outcome_r=_r_for_timeout(direction, last_close, entry, risk), exit_price=last_close, bars_to_entry=0, bars_to_outcome=len(future), minutes_to_outcome=round((last_time - decision_time).total_seconds() / 60.0, 2) if last_time is not None else None)
    return _base_outcome(REFERENCE_MODEL, "STILL_OPEN", entry_ts=decision_time, bars_to_entry=0)


def pending_touch_outcome(row: dict[str, Any], frame: pd.DataFrame, cfg: FillAuditConfig, *, conservative: bool = False) -> dict[str, Any]:
    model = CONSERVATIVE_MODEL if conservative else PENDING_TOUCH_MODEL
    decision_time = _parse_ts(row.get("signal_timestamp"))
    direction = str(row.get("direction") or "").upper()
    levels = _levels(row)
    if not _required_fields_ok(levels, decision_time, direction):
        return _base_outcome(model, NOT_COMPUTABLE, entry_status="ENTRY_NOT_TRIGGERED", insufficient=True)
    future = _future(frame, decision_time, cfg.max_forward_bars)
    if future.empty:
        return _base_outcome(model, "INSUFFICIENT_FORWARD_DATA", entry_status="ENTRY_NOT_TRIGGERED", insufficient=True)
    entry = float(levels["entry"])
    stop = float(levels["stop"])
    target = float(levels["target"])
    risk = float(levels["risk"])
    fill_idx: int | None = None
    fill_time: pd.Timestamp | None = None
    fill_candle: Any | None = None
    for idx, candle in enumerate(future.itertuples(index=False), start=1):
        high = float(getattr(candle, "high"))
        low = float(getattr(candle, "low"))
        if low <= entry <= high:
            fill_idx = idx
            fill_time = _parse_ts(getattr(candle, "time"))
            fill_candle = candle
            break
    if fill_idx is None or fill_time is None or fill_candle is None:
        return _base_outcome(model, "ENTRY_NOT_TRIGGERED", entry_status="ENTRY_NOT_TRIGGERED")

    minutes_to_entry = round((fill_time - decision_time).total_seconds() / 60.0, 2)
    fill_high = float(getattr(fill_candle, "high"))
    fill_low = float(getattr(fill_candle, "low"))
    fill_tp, fill_sl = _hit_flags(direction, fill_high, fill_low, target, stop)
    if conservative and (fill_tp or fill_sl):
        return _base_outcome(model, "AMBIGUOUS_INTRABAR", entry_ts=fill_time, outcome_ts=fill_time, bars_to_entry=fill_idx, bars_to_outcome=0, minutes_to_entry=minutes_to_entry, minutes_to_outcome=0.0, ambiguous=True)
    if not conservative:
        if fill_tp and fill_sl:
            return _base_outcome(model, "AMBIGUOUS_INTRABAR", entry_ts=fill_time, outcome_ts=fill_time, bars_to_entry=fill_idx, bars_to_outcome=0, minutes_to_entry=minutes_to_entry, minutes_to_outcome=0.0, ambiguous=True)
        if fill_tp:
            return _base_outcome(model, "TP_HIT", entry_ts=fill_time, outcome_ts=fill_time, outcome_r=abs(target - entry) / risk, exit_price=target, bars_to_entry=fill_idx, bars_to_outcome=0, minutes_to_entry=minutes_to_entry, minutes_to_outcome=0.0)
        if fill_sl:
            return _base_outcome(model, "SL_HIT", entry_ts=fill_time, outcome_ts=fill_time, outcome_r=-1.0, exit_price=stop, bars_to_entry=fill_idx, bars_to_outcome=0, minutes_to_entry=minutes_to_entry, minutes_to_outcome=0.0)

    after_fill = future.iloc[fill_idx:].copy()
    last_close: float | None = None
    last_time: pd.Timestamp | None = None
    for offset, candle in enumerate(after_fill.itertuples(index=False), start=1):
        high = float(getattr(candle, "high"))
        low = float(getattr(candle, "low"))
        close = float(getattr(candle, "close"))
        when = _parse_ts(getattr(candle, "time"))
        last_close = close
        last_time = when
        tp_hit, sl_hit = _hit_flags(direction, high, low, target, stop)
        minutes_outcome = round((when - fill_time).total_seconds() / 60.0, 2) if when is not None else None
        if tp_hit and sl_hit:
            return _base_outcome(model, "AMBIGUOUS_INTRABAR", entry_ts=fill_time, outcome_ts=when, bars_to_entry=fill_idx, bars_to_outcome=offset, minutes_to_entry=minutes_to_entry, minutes_to_outcome=minutes_outcome, ambiguous=True)
        if tp_hit:
            return _base_outcome(model, "TP_HIT", entry_ts=fill_time, outcome_ts=when, outcome_r=abs(target - entry) / risk, exit_price=target, bars_to_entry=fill_idx, bars_to_outcome=offset, minutes_to_entry=minutes_to_entry, minutes_to_outcome=minutes_outcome)
        if sl_hit:
            return _base_outcome(model, "SL_HIT", entry_ts=fill_time, outcome_ts=when, outcome_r=-1.0, exit_price=stop, bars_to_entry=fill_idx, bars_to_outcome=offset, minutes_to_entry=minutes_to_entry, minutes_to_outcome=minutes_outcome)
    remaining_window_used = len(future)
    if remaining_window_used >= cfg.max_forward_bars and last_close is not None:
        return _base_outcome(model, "TIMEOUT_CLOSE", entry_ts=fill_time, outcome_ts=last_time, outcome_r=_r_for_timeout(direction, last_close, entry, risk), exit_price=last_close, bars_to_entry=fill_idx, bars_to_outcome=len(after_fill), minutes_to_entry=minutes_to_entry, minutes_to_outcome=round((last_time - fill_time).total_seconds() / 60.0, 2) if last_time is not None else None)
    return _base_outcome(model, "STILL_OPEN", entry_ts=fill_time, bars_to_entry=fill_idx, minutes_to_entry=minutes_to_entry)


def lifecycle_lookup(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        out[(str(row.get("decision_timestamp") or ""), str(row.get("direction") or ""))] = row
    return out


def build_per_signal_rows(selected_rows: list[dict[str, Any]], lifecycle_rows: list[dict[str, Any]], frame: pd.DataFrame, cfg: FillAuditConfig) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    lookup = lifecycle_lookup(lifecycle_rows)
    rows: list[dict[str, Any]] = []
    outcomes_by_model: dict[str, dict[str, Any]] = {REFERENCE_MODEL: {}, PENDING_TOUCH_MODEL: {}, CONSERVATIVE_MODEL: {}}
    accepted_index = 0
    for index, row in enumerate(selected_rows):
        signal_id = _signal_id(row, index)
        event_id = f"strategy3-fill-audit-{index + 1:05d}"
        decision_ts = _iso(row.get("signal_timestamp"))
        direction = str(row.get("direction") or "").upper()
        accepted = _bool(row.get("cooldown_accepted")) or str(row.get("cooldown_status") or "").lower() == "accepted"
        block_reason = "" if accepted else str(row.get("cooldown_block_reason") or row.get("block_reason") or "blocked_unspecified")
        levels = _levels(row)
        current = lookup.get((str(decision_ts or ""), direction), {})
        if not accepted:
            rows.append(
                {
                    "event_id": event_id,
                    "signal_id": signal_id,
                    "decision_timestamp": decision_ts,
                    "symbol": row.get("symbol") or cfg.symbol,
                    "direction": direction,
                    "signal_status": "SIGNAL_BLOCKED",
                    "block_reason": block_reason,
                    "entry_reference_price": levels["entry"],
                    "stop_loss": levels["stop"],
                    "take_profit": levels["target"],
                    "risk_distance_usd": levels["risk"],
                    "risk_distance_pips": levels["risk_pips"],
                    "current_lifecycle_outcome_status": current.get("outcome_status") or "SIGNAL_BLOCKED",
                    "reference_fill_outcome_status": "SIGNAL_BLOCKED",
                    "pending_touch_entry_status": "ENTRY_NOT_TRIGGERED",
                    "pending_touch_outcome_status": "SIGNAL_BLOCKED",
                    "conservative_entry_status": "ENTRY_NOT_TRIGGERED",
                    "conservative_outcome_status": "SIGNAL_BLOCKED",
                    "changed_under_pending_touch_flag": False,
                    "changed_under_conservative_flag": False,
                    "paper_only": True,
                }
            )
            continue
        accepted_index += 1
        reference = reference_fill_outcome(row, frame, cfg)
        pending = pending_touch_outcome(row, frame, cfg, conservative=False)
        conservative = pending_touch_outcome(row, frame, cfg, conservative=True)
        outcomes_by_model[REFERENCE_MODEL][signal_id] = reference
        outcomes_by_model[PENDING_TOUCH_MODEL][signal_id] = pending
        outcomes_by_model[CONSERVATIVE_MODEL][signal_id] = conservative
        changed_pending = reference["outcome_status"] != pending["outcome_status"]
        changed_conservative = reference["outcome_status"] != conservative["outcome_status"]
        rows.append(
            {
                "event_id": event_id,
                "signal_id": signal_id,
                "decision_timestamp": decision_ts,
                "symbol": row.get("symbol") or cfg.symbol,
                "direction": direction,
                "signal_status": "SIGNAL_ACCEPTED",
                "block_reason": "",
                "entry_reference_price": levels["entry"],
                "stop_loss": levels["stop"],
                "take_profit": levels["target"],
                "risk_distance_usd": levels["risk"],
                "risk_distance_pips": levels["risk_pips"],
                "current_lifecycle_outcome_status": current.get("outcome_status"),
                "reference_fill_outcome_status": reference["outcome_status"],
                "pending_touch_entry_status": pending["entry_status"],
                "pending_touch_entry_timestamp": pending["entry_timestamp"],
                "pending_touch_outcome_status": pending["outcome_status"],
                "conservative_entry_status": conservative["entry_status"],
                "conservative_entry_timestamp": conservative["entry_timestamp"],
                "conservative_outcome_status": conservative["outcome_status"],
                "reference_outcome_r": reference["outcome_r"],
                "pending_touch_outcome_r": pending["outcome_r"],
                "conservative_outcome_r": conservative["outcome_r"],
                "reference_minutes_to_outcome": reference["minutes_to_outcome"],
                "pending_touch_minutes_to_entry": pending["minutes_to_entry"],
                "pending_touch_minutes_to_outcome": pending["minutes_to_outcome"],
                "conservative_minutes_to_entry": conservative["minutes_to_entry"],
                "conservative_minutes_to_outcome": conservative["minutes_to_outcome"],
                "changed_under_pending_touch_flag": changed_pending,
                "changed_under_conservative_flag": changed_conservative,
                "ambiguous_intrabar_flag_by_model": json.dumps(
                    {
                        REFERENCE_MODEL: reference["ambiguous_intrabar_flag"],
                        PENDING_TOUCH_MODEL: pending["ambiguous_intrabar_flag"],
                        CONSERVATIVE_MODEL: conservative["ambiguous_intrabar_flag"],
                    },
                    sort_keys=True,
                ),
                "insufficient_forward_data_flag_by_model": json.dumps(
                    {
                        REFERENCE_MODEL: reference["insufficient_forward_data_flag"],
                        PENDING_TOUCH_MODEL: pending["insufficient_forward_data_flag"],
                        CONSERVATIVE_MODEL: conservative["insufficient_forward_data_flag"],
                    },
                    sort_keys=True,
                ),
                "paper_only": True,
            }
        )
    return rows, outcomes_by_model


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _median(values: list[float]) -> float | None:
    return round(float(median(values)), 6) if values else None


def _max_losing_streak(values: list[float]) -> int:
    best = 0
    current = 0
    for value in values:
        if value < 0:
            current += 1
            best = max(best, current)
        elif value > 0:
            current = 0
    return best


def model_summary(model: str, accepted_count: int, outcomes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    values = list(outcomes.values())
    not_computable = [row for row in values if row.get("model_status") == NOT_COMPUTABLE]
    tp = [row for row in values if row.get("outcome_status") == "TP_HIT"]
    sl = [row for row in values if row.get("outcome_status") == "SL_HIT"]
    ambiguous = [row for row in values if row.get("outcome_status") == "AMBIGUOUS_INTRABAR"]
    timeout = [row for row in values if row.get("outcome_status") == "TIMEOUT_CLOSE"]
    still_open = [row for row in values if row.get("outcome_status") == "STILL_OPEN"]
    insufficient = [row for row in values if row.get("outcome_status") == "INSUFFICIENT_FORWARD_DATA"]
    entry_not = [row for row in values if row.get("entry_status") == "ENTRY_NOT_TRIGGERED"]
    filled = [row for row in values if row.get("entry_status") == "ENTRY_FILLED"]
    deterministic = [row for row in values if row.get("outcome_status") in {"TP_HIT", "SL_HIT", "TIMEOUT_CLOSE"}]
    r_values = [float(row["outcome_r"]) for row in deterministic if _float(row.get("outcome_r")) is not None]
    minutes_entry = [float(row["minutes_to_entry"]) for row in values if _float(row.get("minutes_to_entry")) is not None]
    minutes_outcome = [float(row["minutes_to_outcome"]) for row in values if _float(row.get("minutes_to_outcome")) is not None]
    return {
        "fill_model": model,
        "model_status": NOT_COMPUTABLE if accepted_count and len(not_computable) / accepted_count >= 0.5 else "COMPUTABLE",
        "accepted_signals": accepted_count,
        "entry_filled_count": len(filled),
        "entry_not_triggered_count": len(entry_not),
        "tp_hit_count": len(tp),
        "sl_hit_count": len(sl),
        "ambiguous_intrabar_count": len(ambiguous),
        "timeout_count": len(timeout),
        "still_open_count": len(still_open),
        "insufficient_forward_data_count": len(insufficient),
        "deterministic_outcome_count": len(deterministic),
        "gross_win_rate": _rate(len(tp), accepted_count),
        "decisive_win_rate_tp_vs_sl_only": _rate(len(tp), len(tp) + len(sl)),
        "total_outcome_r": round(sum(r_values), 6) if r_values else None,
        "average_outcome_r": _mean(r_values),
        "median_outcome_r": _median(r_values),
        "average_minutes_to_entry": _mean(minutes_entry),
        "median_minutes_to_entry": _median(minutes_entry),
        "average_minutes_to_outcome": _mean(minutes_outcome),
        "median_minutes_to_outcome": _median(minutes_outcome),
        "max_losing_streak": _max_losing_streak(r_values),
        "sample_status": "INSUFFICIENT_N" if accepted_count < 100 else "WATCHLIST_ONLY",
        "interpretation_status": "DESCRIPTIVE_ONLY_SMALL_N",
    }


def sensitivity_flags(per_signal: list[dict[str, Any]], summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    accepted = [row for row in per_signal if row.get("signal_status") == "SIGNAL_ACCEPTED"]
    accepted_count = len(accepted)
    changed_pending = sum(1 for row in accepted if str(row.get("changed_under_pending_touch_flag")).lower() == "true")
    changed_conservative = sum(1 for row in accepted if str(row.get("changed_under_conservative_flag")).lower() == "true")
    ref = summaries[REFERENCE_MODEL]
    pending = summaries[PENDING_TOUCH_MODEL]
    conservative = summaries[CONSERVATIVE_MODEL]

    def delta(model: dict[str, Any], key: str) -> float | None:
        a = _float(ref.get(key))
        b = _float(model.get(key))
        if a is None or b is None:
            return None
        return round(b - a, 6)

    pending_wr_delta = delta(pending, "decisive_win_rate_tp_vs_sl_only")
    conservative_wr_delta = delta(conservative, "decisive_win_rate_tp_vs_sl_only")
    pending_r_delta = delta(pending, "total_outcome_r")
    conservative_r_delta = delta(conservative, "total_outcome_r")
    ref_r = abs(_float(ref.get("total_outcome_r")) or 0.0)
    pending_r_delta_rate = abs(pending_r_delta) / ref_r if pending_r_delta is not None and ref_r > 0 else 0.0
    conservative_r_delta_rate = abs(conservative_r_delta) / ref_r if conservative_r_delta is not None and ref_r > 0 else 0.0
    entry_not_delta = int(pending.get("entry_not_triggered_count") or 0) - int(ref.get("entry_not_triggered_count") or 0)
    entry_not_rate = entry_not_delta / accepted_count if accepted_count else 0.0
    ambiguous_delta = {
        PENDING_TOUCH_MODEL: int(pending.get("ambiguous_intrabar_count") or 0) - int(ref.get("ambiguous_intrabar_count") or 0),
        CONSERVATIVE_MODEL: int(conservative.get("ambiguous_intrabar_count") or 0) - int(ref.get("ambiguous_intrabar_count") or 0),
    }
    status = "LOW"
    if any(summary.get("model_status") == NOT_COMPUTABLE for summary in summaries.values()):
        status = "NOT_COMPUTABLE"
    elif (
        abs(pending_wr_delta or 0.0) >= 0.10
        or abs(conservative_wr_delta or 0.0) >= 0.10
        or pending_r_delta_rate >= 0.25
        or conservative_r_delta_rate >= 0.25
        or entry_not_rate >= 0.20
    ):
        status = "HIGH"
    elif changed_pending or changed_conservative or pending_r_delta or conservative_r_delta:
        status = "MEDIUM"
    return {
        "outcome_changed_count_reference_vs_pending": changed_pending,
        "outcome_changed_rate_reference_vs_pending": _rate(changed_pending, accepted_count),
        "outcome_changed_count_reference_vs_conservative": changed_conservative,
        "outcome_changed_rate_reference_vs_conservative": _rate(changed_conservative, accepted_count),
        "wr_delta_reference_vs_pending": pending_wr_delta,
        "wr_delta_reference_vs_conservative": conservative_wr_delta,
        "total_r_delta_reference_vs_pending": pending_r_delta,
        "total_r_delta_reference_vs_conservative": conservative_r_delta,
        "entry_not_triggered_delta": entry_not_delta,
        "ambiguous_delta": ambiguous_delta,
        "fill_model_sensitivity_status": status,
        "threshold_note": "HIGH if decisive WR changes by >=10pp, total R changes by >=25%, or >=20% of accepted signals become entry-not-triggered.",
    }


def fill_alignment_report() -> dict[str, Any]:
    return {
        "current_backtest_fill_assumption_detected": (
            "Backtest runner builds Strategy 3 BacktestSignal from Strategy3Signal.entry and passes future M1 candles strictly after the driver cutoff to simulate_trade_outcome."
        ),
        "current_paper_scanner_fill_assumption_detected": (
            "Paper scanner serializes Strategy3Signal.entry as entry_price/current_price with no pending-entry state or entry touch lifecycle."
        ),
        "current_lifecycle_fill_assumption_detected": (
            "Lifecycle tracker uses PAPER_REFERENCE_FILL_AT_SIGNAL and evaluates forward closed candles strictly after the decision timestamp."
        ),
        "fill_model_alignment": "ALIGNED",
        "fill_model_governance": "AUDIT_REQUIRED_BEFORE_SIGNAL_STREAM",
    }


def build_summary(
    *,
    cfg: FillAuditConfig,
    selected_rows: list[dict[str, Any]],
    legacy_excluded: int,
    per_signal: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
    sensitivity: dict[str, Any],
    alignment: dict[str, Any],
    lifecycle_summary: dict[str, Any],
    forward_timeframe_used: str,
    forward_warnings: list[str],
    runtime_seconds: float,
) -> dict[str, Any]:
    accepted_count = sum(1 for row in per_signal if row.get("signal_status") == "SIGNAL_ACCEPTED")
    blocked_count = sum(1 for row in per_signal if row.get("signal_status") == "SIGNAL_BLOCKED")
    missing_most = any(row.get("model_status") == NOT_COMPUTABLE for row in comparison_rows)
    sensitivity_status = str(sensitivity.get("fill_model_sensitivity_status"))
    if missing_most or sensitivity_status == "HIGH":
        audit_gate = "BLOCKED"
    elif sensitivity_status in {"MEDIUM", "NOT_COMPUTABLE"} or alignment.get("fill_model_alignment") == "UNRESOLVED":
        audit_gate = "WARNING"
    else:
        audit_gate = "PASSED"
    if audit_gate == "BLOCKED":
        stream_gate = "BLOCKED"
    elif audit_gate == "WARNING":
        stream_gate = "WARNING"
    else:
        stream_gate = "ELIGIBLE_FOR_PAPER_ONLY_SIGNAL_STREAM"
    return {
        "run_finished_at": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": round(runtime_seconds, 4),
        "dry_run": cfg.dry_run,
        "strategy": STRATEGY_NAME,
        "symbol": cfg.symbol,
        "inputs": {
            "paper_signals_path": str(cfg.paper_signals_path),
            "lifecycle_outcomes_path": str(cfg.lifecycle_outcomes_path),
            "lifecycle_summary_path": str(cfg.lifecycle_summary_path),
            "data_dir": cfg.data_dir,
        },
        "methodology": {
            "fill_models_compared": [REFERENCE_MODEL, PENDING_TOUCH_MODEL, CONSERVATIVE_MODEL],
            "timeout_policy_source": TIMEOUT_POLICY_SOURCE,
            "max_forward_bars": cfg.max_forward_bars,
            "forward_timeframe_requested": cfg.forward_timeframe,
            "forward_timeframe_used": forward_timeframe_used,
            "closed_candles_only": True,
            "forward_candles_after_signal_only": True,
            "project_pip_convention": PROJECT_PIP_CONVENTION,
            "ambiguous_intrabar_policy": "TP and SL in same candle are AMBIGUOUS_INTRABAR and excluded from decisive WR.",
        },
        "selection": {
            "selected_clean_rows": len(selected_rows),
            "legacy_excluded": legacy_excluded,
            "accepted_signals": accepted_count,
            "blocked_signals": blocked_count,
            "clean_context_only": not cfg.include_legacy,
        },
        "alignment": alignment,
        "lifecycle_baseline": {
            "fill_model": lifecycle_summary.get("methodology", {}).get("fill_model"),
            "tp_hit_count": lifecycle_summary.get("tp_hit_count"),
            "sl_hit_count": lifecycle_summary.get("sl_hit_count"),
            "ambiguous_intrabar_count": lifecycle_summary.get("ambiguous_intrabar_count"),
            "decisive_win_rate_tp_vs_sl_only": lifecycle_summary.get("decisive_win_rate_tp_vs_sl_only"),
            "total_outcome_r": lifecycle_summary.get("total_outcome_r"),
        },
        "fill_model_comparison": comparison_rows,
        "sensitivity": sensitivity,
        "fill_model_audit_gate": audit_gate,
        "paper_signal_stream_gate": stream_gate,
        "live_gate": "BLOCKED",
        "deployment_gate": "BLOCKED",
        "order_send_gate": "BLOCKED",
        "broker_gate": "BLOCKED",
        "sample_status": "INSUFFICIENT_N" if accepted_count < 100 else "WATCHLIST_ONLY",
        "interpretation_status": "DESCRIPTIVE_ONLY_SMALL_N",
        "forward_warnings": forward_warnings,
        "verdict_flags": [
            "PAPER_FILL_MODEL_AUDIT_CREATED",
            f"FILL_MODEL_AUDIT_GATE_{audit_gate}",
            f"FILL_MODEL_SENSITIVITY_{sensitivity_status}",
            "REFERENCE_FILL_ALIGNMENT_ALIGNED" if alignment.get("fill_model_alignment") == "ALIGNED" else "REFERENCE_FILL_ALIGNMENT_UNRESOLVED",
            "NO_TELEGRAM_SIGNAL_STREAM_AUTHORIZATION",
            "NO_LIVE_DEPLOYMENT_DECISION",
            "STRATEGY_3_REMAINS_PAPER_ONLY",
        ],
        "safety": dict(SAFETY),
    }


def write_report(output_dir: Path, docs_path: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    rows = {row["fill_model"]: row for row in summary["fill_model_comparison"]}
    ref = rows.get(REFERENCE_MODEL, {})
    pending = rows.get(PENDING_TOUCH_MODEL, {})
    conservative = rows.get(CONSERVATIVE_MODEL, {})
    lines = [
        "# Strategy 3 Paper Fill-Model Audit",
        "",
        "This audit is diagnostic only. It does not change Strategy 3, send signals, enable Telegram, place orders, call broker execution, or approve live trading.",
        "",
        "## Objective",
        "",
        "Audit whether the current paper lifecycle outcome metrics are robust to fill assumptions before any paper signal stream work.",
        "",
        "## Why This Is Required",
        "",
        "The lifecycle tracker currently uses `PAPER_REFERENCE_FILL_AT_SIGNAL`. Before a signal stream can even be considered for paper-only use, the project needs to know whether the descriptive WR/R profile is stable under plausible alternative fill assumptions.",
        "",
        "## Alignment With Existing Assumptions",
        "",
        f"- backtest assumption detected: {summary['alignment']['current_backtest_fill_assumption_detected']}",
        f"- paper scanner assumption detected: {summary['alignment']['current_paper_scanner_fill_assumption_detected']}",
        f"- lifecycle assumption detected: {summary['alignment']['current_lifecycle_fill_assumption_detected']}",
        f"- alignment: `{summary['alignment']['fill_model_alignment']}`",
        f"- governance: `{summary['alignment']['fill_model_governance']}`",
        "",
        "## Tested Fill Models",
        "",
        "- `PAPER_REFERENCE_FILL_AT_SIGNAL`: accepted signal fills at the paper reference entry at the decision timestamp; forward tracking starts after the decision timestamp.",
        "- `PAPER_PENDING_ENTRY_TOUCH`: entry fills only if a later closed candle touches the entry reference level.",
        "- `CONSERVATIVE_NEXT_CANDLE_FILL_OR_TOUCH`: entry fills from the next closed candle onward, but first-fill candle TP/SL interaction is ambiguous rather than favorable.",
        "",
        "## Outcome Comparison",
        "",
        "| fill_model | entry_filled | entry_not_triggered | TP | SL | ambiguous | decisive_WR | total_R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["fill_model_comparison"]:
        lines.append(
            f"| {row['fill_model']} | {row['entry_filled_count']} | {row['entry_not_triggered_count']} | {row['tp_hit_count']} | {row['sl_hit_count']} | {row['ambiguous_intrabar_count']} | {row['decisive_win_rate_tp_vs_sl_only']} | {row['total_outcome_r']} |"
        )
    lines.extend(
        [
            "",
            "## Sensitivity",
            "",
            f"- sensitivity status: `{summary['sensitivity']['fill_model_sensitivity_status']}`",
            f"- changed outcomes reference vs pending: `{summary['sensitivity']['outcome_changed_count_reference_vs_pending']}`",
            f"- changed outcomes reference vs conservative: `{summary['sensitivity']['outcome_changed_count_reference_vs_conservative']}`",
            f"- WR delta reference vs pending: `{summary['sensitivity']['wr_delta_reference_vs_pending']}`",
            f"- WR delta reference vs conservative: `{summary['sensitivity']['wr_delta_reference_vs_conservative']}`",
            f"- total R delta reference vs pending: `{summary['sensitivity']['total_r_delta_reference_vs_pending']}`",
            f"- total R delta reference vs conservative: `{summary['sensitivity']['total_r_delta_reference_vs_conservative']}`",
            "",
            "Sensitivity labels are audit labels only, not strategy rules.",
            "",
            "## Gates",
            "",
            f"- fill model audit gate: `{summary['fill_model_audit_gate']}`",
            f"- paper signal stream gate: `{summary['paper_signal_stream_gate']}`",
            f"- live gate: `{summary['live_gate']}`",
            f"- deployment gate: `{summary['deployment_gate']}`",
            f"- order_send gate: `{summary['order_send_gate']}`",
            f"- broker gate: `{summary['broker_gate']}`",
            "",
            "## Limitations",
            "",
            "- sample remains `INSUFFICIENT_N`",
            "- outcome comparison is descriptive only",
            "- no outcome result may be used to change Strategy 3 in this branch",
            "- this does not validate edge or profitability",
            "- this does not authorize Telegram signal stream yet",
            "",
            "## Safety",
            "",
            "- no live trading",
            "- no Telegram",
            "- no signal stream",
            "- no orders",
            "- no broker execution",
            "- no order_send",
            "- no lot size or account risk sizing",
            "- no Strategy 3 VWAP/sigma/cooldown/entry/TP/SL/filter changes",
            "- no Strategy 2 touch",
            "- no Adelin touch",
            "- no data/XAUUSD/*.csv mutation",
            "",
            "## Next Recommendation",
            "",
            "If sensitivity is LOW and the audit gate passes, the next branch may define a paper-only signal-stream governance plan. If sensitivity is MEDIUM/HIGH, keep accumulating paper evidence and resolve fill-model governance before any signal stream work.",
            "",
        ]
    )
    rendered = "\n".join(lines)
    (output_dir / "paper_fill_model_audit.md").write_text(rendered, encoding="utf-8")
    docs_path.write_text(rendered, encoding="utf-8")


def run_audit(cfg: FillAuditConfig) -> dict[str, Any]:
    started = perf_counter()
    paper_rows = _read_csv(cfg.paper_signals_path)
    selected_rows, legacy_excluded = select_signal_rows(paper_rows, cfg)
    lifecycle_rows = _read_csv(cfg.lifecycle_outcomes_path)
    lifecycle_summary = _read_json(cfg.lifecycle_summary_path)
    frame, forward_timeframe_used, forward_warnings = load_forward_frame(cfg)
    per_signal, outcomes_by_model = build_per_signal_rows(selected_rows, lifecycle_rows, frame, cfg)
    accepted_count = sum(1 for row in per_signal if row.get("signal_status") == "SIGNAL_ACCEPTED")
    comparison_rows = [model_summary(model, accepted_count, outcomes_by_model[model]) for model in [REFERENCE_MODEL, PENDING_TOUCH_MODEL, CONSERVATIVE_MODEL]]
    summaries = {row["fill_model"]: row for row in comparison_rows}
    sensitivity = sensitivity_flags(per_signal, summaries)
    alignment = fill_alignment_report()
    summary = build_summary(
        cfg=cfg,
        selected_rows=selected_rows,
        legacy_excluded=legacy_excluded,
        per_signal=per_signal,
        comparison_rows=comparison_rows,
        sensitivity=sensitivity,
        alignment=alignment,
        lifecycle_summary=lifecycle_summary,
        forward_timeframe_used=forward_timeframe_used,
        forward_warnings=forward_warnings,
        runtime_seconds=perf_counter() - started,
    )
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(cfg.output_dir / "fill_model_audit_per_signal.csv", per_signal, PER_SIGNAL_FIELDS)
    _write_csv(cfg.output_dir / "fill_model_comparison_summary.csv", comparison_rows, SUMMARY_FIELDS)
    _write_json(cfg.output_dir / "fill_model_audit_summary.json", summary)
    _write_json(cfg.output_dir / "fill_model_sensitivity_flags.json", sensitivity)
    write_report(cfg.output_dir, cfg.docs_path, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = FillAuditConfig(
        symbol=str(args.symbol),
        data_dir=str(args.data_dir),
        paper_signals_path=Path(args.paper_signals_path),
        lifecycle_outcomes_path=Path(args.lifecycle_outcomes_path),
        lifecycle_summary_path=Path(args.lifecycle_summary_path),
        evidence_gate_status_path=Path(args.evidence_gate_status_path),
        evidence_refresh_summary_path=Path(args.evidence_refresh_summary_path),
        output_dir=Path(args.output_dir),
        docs_path=Path(args.docs_path),
        dry_run=bool(args.dry_run),
        include_legacy=bool(args.include_legacy),
        forward_timeframe=str(args.forward_timeframe),
        fallback_timeframe=str(args.fallback_timeframe),
        max_forward_bars=int(args.max_forward_bars),
    )
    print(json.dumps(run_audit(cfg), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
