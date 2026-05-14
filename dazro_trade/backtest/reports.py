from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from dazro_trade.backtest.metrics import BacktestMetrics
from dazro_trade.backtest.simulator import BacktestSignal, BacktestTrade

log = logging.getLogger(__name__)


def _flatten_signal(signal: BacktestSignal) -> dict:
    return {
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
) -> dict[str, str]:
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    signals_list = list(signals)
    trades_list = list(trades)

    executed_rows = [_flatten_trade(t) for t in trades_list if t.outcome != "NO_DATA"]
    rejected_rows = [_flatten_signal(s) for s in signals_list if not s.accepted]

    paths = {
        "summary_json": str(out_root / "summary.json"),
        "summary_csv": str(out_root / "summary.csv"),
        "executed_trades": str(out_root / "executed_trades.csv"),
        "rejected_signals": str(out_root / "rejected_signals.csv"),
        "equity_curve": str(out_root / "equity_curve.csv"),
        "diagnostics_json": str(out_root / "strategy_diagnostics.json"),
    }

    metrics_dict = metrics.to_dict()
    diag_dict = _serialize_diagnostics(strategy_diagnostics)
    if diag_dict:
        metrics_dict = {**metrics_dict, "strategy_diagnostics": diag_dict}
    Path(paths["summary_json"]).write_text(json.dumps(metrics_dict, indent=2), encoding="utf-8")
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
