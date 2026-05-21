from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from dazro_trade.backtest.metrics import BacktestMetrics, compute_per_strategy_metrics
from dazro_trade.backtest.simulator import BacktestSignal, BacktestTrade

log = logging.getLogger(__name__)


def _jsonish(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _flatten_signal(signal: BacktestSignal) -> dict:
    metadata = signal.metadata or {}
    liquidity_context = metadata.get("liquidity_context")
    if isinstance(liquidity_context, dict):
        sweep = liquidity_context.get("sweep") if isinstance(liquidity_context.get("sweep"), dict) else {}
    else:
        sweep = {}
    base = {
        "timestamp": signal.timestamp.isoformat() if signal.timestamp else None,
        "symbol": signal.symbol,
        "strategy": signal.strategy,
        "direction": signal.direction,
        "entry": signal.entry,
        "stop": signal.stop,
        "sl_distance": signal.sl_distance,
        "sl_distance_usd": signal.sl_distance_usd,
        "sl_distance_pips": signal.sl_distance_pips,
        "risk_label": signal.risk_label,
        "tp1": signal.tp1,
        "tp2": signal.tp2,
        "tp3": signal.tp3,
        "tp4": signal.tp4,
        "rr_tp1": signal.rr_tp1,
        "score": signal.score,
        "session": signal.session,
        "accepted": signal.accepted,
        "rejection_reasons": ";".join(signal.rejection_reasons or []),
    }
    base.update(
        {
            "setup_mode": metadata.get("setup_mode"),
            "reason_codes": ";".join(str(item) for item in metadata.get("reason_codes", []) if item is not None)
            if isinstance(metadata.get("reason_codes"), (list, tuple, set))
            else metadata.get("reason_codes"),
            "confluences": _jsonish(metadata.get("confluences")),
            "vwap": _jsonish(metadata.get("vwap")),
            "vwap_distance": metadata.get("vwap_distance"),
            "vwap_distance_pips": metadata.get("vwap_distance_pips"),
            "band_touched": metadata.get("band_touched"),
            "liquidity_context": _jsonish(liquidity_context),
            "sweep_timeframe": liquidity_context.get("timeframe") if isinstance(liquidity_context, dict) else None,
            "sweep_type": sweep.get("side") or liquidity_context.get("type") if isinstance(liquidity_context, dict) else None,
            "sweep_price": liquidity_context.get("level") if isinstance(liquidity_context, dict) else None,
            "fvg_ifvg_context": _jsonish(metadata.get("fvg_ifvg_context")),
            "number_theory_context": _jsonish(metadata.get("number_theory_context")),
            "target_model": metadata.get("target_model"),
            "research_only": metadata.get("research_only"),
            "strategy_name": signal.strategy,
            "risk_distance": signal.sl_distance,
            "reward_distance": abs(float(signal.tp1) - float(signal.entry)) if signal.tp1 is not None else None,
            "rr": signal.rr_tp1,
        }
    )
    return base


def _flatten_trade(trade: BacktestTrade) -> dict:
    base = _flatten_signal(trade.signal)
    base.update(
        {
            "outcome": trade.outcome,
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
            "exit_price": trade.exit_price,
            "r_multiple": trade.r_multiple,
            "mae": trade.mae,
            "mfe": trade.mfe,
            "bars_held": trade.bars_held,
        }
    )
    return base


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _serialize_diagnostics(diagnostics: dict[str, object] | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not diagnostics:
        return out
    for name, value in diagnostics.items():
        if value is None:
            continue
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            out[name] = to_dict()
        elif isinstance(value, dict):
            out[name] = dict(value)
        else:
            out[name] = {"repr": repr(value)}
    return out


def export_backtest_reports(
    *,
    output_dir: str,
    metrics: BacktestMetrics,
    signals: Iterable[BacktestSignal],
    trades: Iterable[BacktestTrade],
    equity_curve: Iterable[tuple[str, float]] | None = None,
    strategy_diagnostics: dict[str, object] | None = None,
    partial: bool = False,
) -> dict[str, str]:
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    signals_list = list(signals)
    trades_list = list(trades)

    executed_rows = [_flatten_trade(t) for t in trades_list if t.outcome != "NO_DATA"]
    rejected_rows = [_flatten_signal(s) for s in signals_list if not s.accepted]

    paths = {
        "summary_json": str(out_root / ("summary_partial.json" if partial else "summary.json")),
        "summary_csv": str(out_root / "summary.csv"),
        "executed_trades": str(out_root / "executed_trades.csv"),
        "rejected_signals": str(out_root / "rejected_signals.csv"),
        "equity_curve": str(out_root / "equity_curve.csv"),
        "diagnostics_json": str(out_root / "strategy_diagnostics.json"),
    }

    metrics_dict = metrics.to_dict()
    if partial:
        metrics_dict = {**metrics_dict, "partial": True}
    diag_dict = _serialize_diagnostics(strategy_diagnostics)
    per_strategy = compute_per_strategy_metrics(signals_list, trades_list)
    if per_strategy:
        metrics_dict = {**metrics_dict, "per_strategy": per_strategy}
    if diag_dict:
        metrics_dict = {**metrics_dict, "strategy_diagnostics": diag_dict}
    Path(paths["summary_json"]).write_text(json.dumps(metrics_dict, indent=2), encoding="utf-8")
    paths["per_strategy_json"] = str(out_root / "per_strategy.json")
    Path(paths["per_strategy_json"]).write_text(json.dumps(per_strategy, indent=2), encoding="utf-8")
    _write_csv(Path(paths["summary_csv"]), [{"metric": k, "value": v if not isinstance(v, dict) else json.dumps(v)} for k, v in metrics_dict.items()])
    _write_csv(Path(paths["executed_trades"]), executed_rows)
    _write_csv(Path(paths["rejected_signals"]), rejected_rows)
    eq_rows = [{"time": t, "cumulative_r": r} for t, r in (equity_curve or [])]
    _write_csv(Path(paths["equity_curve"]), eq_rows)
    Path(paths["diagnostics_json"]).write_text(json.dumps(diag_dict, indent=2), encoding="utf-8")

    log.info("backtest_reports_exported dir=%s executed=%s rejected=%s diagnostics=%s",
             out_root, len(executed_rows), len(rejected_rows), list(diag_dict.keys()))
    return paths


__all__ = ["export_backtest_reports"]
