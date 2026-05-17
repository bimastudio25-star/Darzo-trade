"""
Link candle-behavior records to Adelin trades for the trade-linked edge
report.

For each `CandleBehaviorRecord` we look up the *nearest* Adelin signal
in time and attach the matching trade outcome (if the signal is also
present in the trades list). The link is one-sided: a candle is linked
to at most one signal, and the relationship is anchored by the candle
timestamp.

Two records are kept per signal:
- the candle whose timestamp falls inside the signal's bar
- the candles within `link_window_bars` (default 10 on the M5 scan)
  before the signal — they are useful to study setup-context features
  that *predict* a signal.

The module is read-only: the candle records and the BacktestSignal /
BacktestTrade objects are not mutated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from dazro_trade.analytics.candle_behavior_report import CandleBehaviorRecord
from dazro_trade.backtest.simulator import BacktestSignal, BacktestTrade


@dataclass(frozen=True)
class TradeLink:
    """Metadata attached to a candle record describing the nearest Adelin
    signal/trade.

    Fields starting with `trade_` come from the matching BacktestTrade
    (None when the signal was rejected and never traded).
    """
    nearest_signal_timestamp: datetime | None = None
    nearest_signal_strategy: str | None = None
    nearest_signal_direction: str | None = None
    nearest_signal_session: str | None = None
    nearest_signal_score: int | None = None
    nearest_signal_setup_mode: str | None = None
    nearest_signal_accepted: bool | None = None
    nearest_signal_entry: float | None = None
    nearest_signal_stop: float | None = None
    nearest_signal_tp1: float | None = None
    nearest_signal_sl_distance: float | None = None
    nearest_signal_rejection_reasons: list[str] = field(default_factory=list)
    distance_to_signal_bars: int | None = None
    trade_outcome: str | None = None
    trade_r_multiple: float | None = None
    trade_mae: float | None = None
    trade_mfe: float | None = None
    trade_bars_held: int | None = None
    trade_exit_time: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "nearest_signal_timestamp": self.nearest_signal_timestamp.isoformat() if self.nearest_signal_timestamp else None,
            "nearest_signal_strategy": self.nearest_signal_strategy,
            "nearest_signal_direction": self.nearest_signal_direction,
            "nearest_signal_session": self.nearest_signal_session,
            "nearest_signal_score": self.nearest_signal_score,
            "nearest_signal_setup_mode": self.nearest_signal_setup_mode,
            "nearest_signal_accepted": self.nearest_signal_accepted,
            "nearest_signal_entry": self.nearest_signal_entry,
            "nearest_signal_stop": self.nearest_signal_stop,
            "nearest_signal_tp1": self.nearest_signal_tp1,
            "nearest_signal_sl_distance": self.nearest_signal_sl_distance,
            "nearest_signal_rejection_reasons": list(self.nearest_signal_rejection_reasons),
            "distance_to_signal_bars": self.distance_to_signal_bars,
            "trade_outcome": self.trade_outcome,
            "trade_r_multiple": self.trade_r_multiple,
            "trade_mae": self.trade_mae,
            "trade_mfe": self.trade_mfe,
            "trade_bars_held": self.trade_bars_held,
            "trade_exit_time": self.trade_exit_time.isoformat() if self.trade_exit_time else None,
        }


def _as_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime()
        except Exception:
            return None
    return None


def link_records_to_trades(
    records: Sequence[CandleBehaviorRecord],
    signals: Sequence[BacktestSignal],
    trades: Sequence[BacktestTrade],
    *,
    strategy: str = "strategy_1_adelin_scalp",
    timeframe_minutes: int = 5,
    link_window_bars: int = 20,
) -> dict[int, TradeLink]:
    """Return a {record_index -> TradeLink} mapping.

    For each candle record, find the nearest signal (by absolute time
    delta) that belongs to `strategy` and falls within
    `link_window_bars * timeframe_minutes` minutes. The matching trade
    (if any) is looked up by signal identity.
    """
    if not records or not signals:
        return {}
    sig_subset = [s for s in signals if s.strategy == strategy and s.timestamp is not None]
    if not sig_subset:
        return {}
    trades_by_sig_id = {id(t.signal): t for t in trades if t.signal.strategy == strategy}
    window_seconds = float(link_window_bars * timeframe_minutes * 60)
    out: dict[int, TradeLink] = {}
    for idx, rec in enumerate(records):
        rec_ts = _as_dt(rec.timestamp)
        if rec_ts is None:
            continue
        best_sig: BacktestSignal | None = None
        best_delta_seconds: float | None = None
        for sig in sig_subset:
            sig_ts = _as_dt(sig.timestamp)
            if sig_ts is None:
                continue
            delta = abs((sig_ts - rec_ts).total_seconds())
            if best_delta_seconds is None or delta < best_delta_seconds:
                best_delta_seconds = delta
                best_sig = sig
        if best_sig is None or best_delta_seconds is None:
            continue
        if best_delta_seconds > window_seconds:
            continue
        distance_bars = int(round(best_delta_seconds / (timeframe_minutes * 60)))
        trade = trades_by_sig_id.get(id(best_sig))
        out[idx] = TradeLink(
            nearest_signal_timestamp=_as_dt(best_sig.timestamp),
            nearest_signal_strategy=best_sig.strategy,
            nearest_signal_direction=best_sig.direction,
            nearest_signal_session=best_sig.session,
            nearest_signal_score=best_sig.score,
            nearest_signal_setup_mode=(best_sig.metadata or {}).get("setup_mode"),
            nearest_signal_accepted=best_sig.accepted,
            nearest_signal_entry=float(best_sig.entry),
            nearest_signal_stop=float(best_sig.stop),
            nearest_signal_tp1=float(best_sig.tp1) if best_sig.tp1 is not None else None,
            nearest_signal_sl_distance=float(best_sig.sl_distance),
            nearest_signal_rejection_reasons=list(best_sig.rejection_reasons or []),
            distance_to_signal_bars=distance_bars,
            trade_outcome=trade.outcome if trade else None,
            trade_r_multiple=float(trade.r_multiple) if trade else None,
            trade_mae=float(trade.mae) if trade else None,
            trade_mfe=float(trade.mfe) if trade else None,
            trade_bars_held=int(trade.bars_held) if trade else None,
            trade_exit_time=_as_dt(trade.exit_time) if trade else None,
        )
    return out


__all__ = ["TradeLink", "link_records_to_trades"]
