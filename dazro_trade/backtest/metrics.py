from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean, median
from typing import Iterable

from dazro_trade.backtest.simulator import BacktestSignal, BacktestTrade


@dataclass(frozen=True)
class BacktestMetrics:
    total_signals: int
    valid_trades: int
    rejected_signals: int
    rejection_reasons: dict[str, int]
    wins: int
    losses: int
    win_rate: float
    loss_rate: float
    profit_factor: float
    average_r: float
    median_r: float
    expectancy: float
    max_drawdown_r: float
    best_trade_r: float
    worst_trade_r: float
    average_win_r: float
    average_loss_r: float
    average_mae: float
    median_mae: float
    average_mfe: float
    median_mfe: float
    tp1_hit_rate: float
    tp2_hit_rate: float
    tp3_hit_rate: float
    tp4_hit_rate: float
    sl_hit_rate: float
    be_hit_rate: float
    still_open_rate: float
    average_bars_held: float

    def to_dict(self) -> dict:
        return {
            "total_signals": self.total_signals,
            "valid_trades": self.valid_trades,
            "rejected_signals": self.rejected_signals,
            "rejection_reasons": dict(self.rejection_reasons),
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 4),
            "loss_rate": round(self.loss_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "average_r": round(self.average_r, 4),
            "median_r": round(self.median_r, 4),
            "expectancy": round(self.expectancy, 4),
            "max_drawdown_r": round(self.max_drawdown_r, 4),
            "best_trade_r": round(self.best_trade_r, 4),
            "worst_trade_r": round(self.worst_trade_r, 4),
            "average_win_r": round(self.average_win_r, 4),
            "average_loss_r": round(self.average_loss_r, 4),
            "average_mae": round(self.average_mae, 4),
            "median_mae": round(self.median_mae, 4),
            "average_mfe": round(self.average_mfe, 4),
            "median_mfe": round(self.median_mfe, 4),
            "tp1_hit_rate": round(self.tp1_hit_rate, 4),
            "tp2_hit_rate": round(self.tp2_hit_rate, 4),
            "tp3_hit_rate": round(self.tp3_hit_rate, 4),
            "tp4_hit_rate": round(self.tp4_hit_rate, 4),
            "sl_hit_rate": round(self.sl_hit_rate, 4),
            "be_hit_rate": round(self.be_hit_rate, 4),
            "still_open_rate": round(self.still_open_rate, 4),
            "average_bars_held": round(self.average_bars_held, 4),
        }


def _safe_div(num: float, den: float) -> float:
    if den == 0:
        return 0.0
    return num / den


def _max_drawdown(r_series: list[float]) -> float:
    peak = 0.0
    cumulative = 0.0
    max_dd = 0.0
    for r in r_series:
        cumulative += r
        peak = max(peak, cumulative)
        drawdown = peak - cumulative
        if drawdown > max_dd:
            max_dd = drawdown
    return max_dd


ADELIN_SL_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("le_4.00", 0.0, 4.00),
    ("4.01_to_5.00", 4.00, 5.00),
    ("5.01_to_6.50", 5.00, 6.50),
    ("6.51_to_7.00", 6.50, 7.00),
    ("gt_7.00", 7.00, float("inf")),
)

LEGACY_ADELIN_MAX_SL_USD = 5.0


def _bucket_for_sl(sl_distance: float) -> str:
    for label, low, high in ADELIN_SL_BUCKETS:
        if low < sl_distance <= high or (label == "le_4.00" and sl_distance <= high):
            return label
    return "gt_7.00"


def compute_adelin_sl_bucket_performance(
    signals: Iterable[BacktestSignal],
    trades: Iterable[BacktestTrade],
) -> dict[str, dict]:
    """SL-distance bucket breakdown for Adelin signals/trades.

    For each bucket returns total/accepted/rejected counts, wins/losses,
    win_rate, avg_r, profit_factor and ex_rejected_recovered_count
    (signals that would have been rejected by the legacy cap of
    LEGACY_ADELIN_MAX_SL_USD but are accepted under the dynamic policy).
    """
    signals = [s for s in signals if s.strategy == "strategy_1_adelin_scalp"]
    trades_by_sig_id = {id(t.signal): t for t in trades if t.signal.strategy == "strategy_1_adelin_scalp"}
    out: dict[str, dict] = {}
    for label, _, _ in ADELIN_SL_BUCKETS:
        out[label] = {
            "total_signals": 0,
            "accepted": 0,
            "rejected": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "avg_r": 0.0,
            "profit_factor": 0.0,
            "ex_rejected_recovered_count": 0,
        }
    for sig in signals:
        bucket = _bucket_for_sl(sig.sl_distance)
        b = out[bucket]
        b["total_signals"] += 1
        if sig.accepted:
            b["accepted"] += 1
            if sig.sl_distance > LEGACY_ADELIN_MAX_SL_USD:
                b["ex_rejected_recovered_count"] += 1
            trade = trades_by_sig_id.get(id(sig))
            if trade is not None and trade.outcome != "NO_DATA":
                if trade.r_multiple > 0:
                    b["wins"] += 1
                elif trade.r_multiple < 0:
                    b["losses"] += 1
        else:
            b["rejected"] += 1
    for label, _, _ in ADELIN_SL_BUCKETS:
        b = out[label]
        rs = [
            trade.r_multiple
            for sig in signals
            if sig.accepted and _bucket_for_sl(sig.sl_distance) == label
            for trade in [trades_by_sig_id.get(id(sig))]
            if trade is not None and trade.outcome != "NO_DATA"
        ]
        if rs:
            wins_r = sum(r for r in rs if r > 0)
            loss_r = sum(-r for r in rs if r < 0)
            b["avg_r"] = round(fmean(rs), 4)
            b["profit_factor"] = round(wins_r / loss_r, 4) if loss_r > 0 else (float("inf") if wins_r > 0 else 0.0)
            denom = b["wins"] + b["losses"]
            b["win_rate"] = round(b["wins"] / denom, 4) if denom > 0 else 0.0
            if b["profit_factor"] == float("inf"):
                b["profit_factor"] = 0.0
    return out


def compute_per_strategy_metrics(signals: Iterable[BacktestSignal], trades: Iterable[BacktestTrade]) -> dict[str, dict]:
    signals = list(signals)
    trades = list(trades)
    strategies = sorted({s.strategy for s in signals} | {t.signal.strategy for t in trades})
    out: dict[str, dict] = {}
    for name in strategies:
        s_sub = [s for s in signals if s.strategy == name]
        t_sub = [t for t in trades if t.signal.strategy == name]
        metrics = compute_backtest_metrics(s_sub, t_sub)
        timestamps = sorted({s.timestamp for s in s_sub if s.timestamp is not None})
        days_span = max((timestamps[-1] - timestamps[0]).days if len(timestamps) >= 2 else 1, 1)
        signals_per_day = len(s_sub) / days_span if days_span > 0 else 0.0
        entry = {
            **metrics.to_dict(),
            "days_observed": days_span,
            "signals_per_day": round(signals_per_day, 3),
        }
        if name == "strategy_1_adelin_scalp":
            entry["sl_bucket_performance"] = compute_adelin_sl_bucket_performance(s_sub, t_sub)
        out[name] = entry
    return out


def compute_backtest_metrics(signals: Iterable[BacktestSignal], trades: Iterable[BacktestTrade]) -> BacktestMetrics:
    signals = list(signals)
    trades = [t for t in trades if t.outcome != "NO_DATA"]
    rejections: dict[str, int] = {}
    for s in signals:
        if not s.accepted:
            for reason in s.rejection_reasons or ["unspecified"]:
                rejections[reason] = rejections.get(reason, 0) + 1
    valid = len(trades)
    total = len(signals)
    rejected = sum(rejections.values())

    wins = [t for t in trades if t.r_multiple > 0]
    losses = [t for t in trades if t.r_multiple < 0]
    r_values = [t.r_multiple for t in trades]
    win_r = [t.r_multiple for t in wins]
    loss_r = [abs(t.r_multiple) for t in losses]

    profit_factor = _safe_div(sum(win_r), sum(loss_r)) if loss_r else (float("inf") if win_r else 0.0)
    average_r = fmean(r_values) if r_values else 0.0
    median_r = median(r_values) if r_values else 0.0
    expectancy = average_r
    best = max(r_values) if r_values else 0.0
    worst = min(r_values) if r_values else 0.0
    avg_win = fmean(win_r) if win_r else 0.0
    avg_loss = -fmean(loss_r) if loss_r else 0.0
    mae_vals = [t.mae for t in trades]
    mfe_vals = [t.mfe for t in trades]
    outcomes = [t.outcome for t in trades]
    bars = [t.bars_held for t in trades]

    return BacktestMetrics(
        total_signals=total,
        valid_trades=valid,
        rejected_signals=rejected,
        rejection_reasons=rejections,
        wins=len(wins),
        losses=len(losses),
        win_rate=_safe_div(len(wins), valid),
        loss_rate=_safe_div(len(losses), valid),
        profit_factor=profit_factor if profit_factor != float("inf") else 0.0,
        average_r=average_r,
        median_r=median_r,
        expectancy=expectancy,
        max_drawdown_r=_max_drawdown(r_values),
        best_trade_r=best,
        worst_trade_r=worst,
        average_win_r=avg_win,
        average_loss_r=avg_loss,
        average_mae=fmean(mae_vals) if mae_vals else 0.0,
        median_mae=median(mae_vals) if mae_vals else 0.0,
        average_mfe=fmean(mfe_vals) if mfe_vals else 0.0,
        median_mfe=median(mfe_vals) if mfe_vals else 0.0,
        tp1_hit_rate=_safe_div(outcomes.count("TP1"), valid),
        tp2_hit_rate=_safe_div(outcomes.count("TP2"), valid),
        tp3_hit_rate=_safe_div(outcomes.count("TP3"), valid),
        tp4_hit_rate=_safe_div(outcomes.count("TP4"), valid),
        sl_hit_rate=_safe_div(outcomes.count("SL"), valid),
        be_hit_rate=_safe_div(outcomes.count("BE"), valid),
        still_open_rate=_safe_div(outcomes.count("STILL_OPEN"), valid),
        average_bars_held=fmean(bars) if bars else 0.0,
    )


__all__ = ["BacktestMetrics", "compute_backtest_metrics"]
