"""
Adelin edge profiler (read-only diagnostic).

Given the Adelin signals + trades produced by a backtest run, this module
breaks down win rate / avg R / profit factor by:

  - score bucket           (<65, 65-69, 70-74, 75-79, 80-84, 85-89, 90+)
  - SL bucket              (<=4, 4.01-5.00, 5.01-6.50)
  - score x SL matrix
  - setup_mode             (LIQ_VP_NT_FVG_SCALP, LIQ_VP_NT_FVG_A_PLUS,
                            VWAP_STD_RESEARCH_1R, NO_TRADE)
  - session                (London, New York, Asia, etc.)
  - direction              (LONG / SHORT)
  - presence flag          (has_sweep, has_fvg, has_volume_confluence,
                            has_number_theory, micro_confluence.all_pass)

It does NOT modify the strategy or filter signals. Output is a plain dict
ready to be serialized as JSON or rendered as a Markdown table.

The profiler also emits a non-binding `recommendations` block: simple
heuristics that flag candidate min_score / max_sl thresholds and which
confluence components actually predict edge in the observed dataset.

Buckets and thresholds (MIN_TRADES_FOR_SIGNIFICANCE = 30 by default) are
configurable via the optional `ProfilerConfig` dataclass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import fmean
from typing import Iterable, Sequence

from dazro_trade.backtest.simulator import BacktestSignal, BacktestTrade

ADELIN_STRATEGY_NAME = "strategy_1_adelin_scalp"


@dataclass(frozen=True)
class ProfilerConfig:
    score_bucket_edges: tuple[int, ...] = (0, 65, 70, 75, 80, 85, 90, 101)
    sl_bucket_edges: tuple[float, ...] = (0.0, 4.0, 5.0, 6.5, 7.0, float("inf"))
    min_trades_for_significance: int = 30
    recommend_min_avg_r: float = 0.0
    recommend_min_profit_factor: float = 1.0


# ----------------------------------------------------------------------
# Bucket helpers
# ----------------------------------------------------------------------

def _score_bucket_label(score: int | None, edges: Sequence[int]) -> str:
    s = int(score) if score is not None else 0
    for i in range(len(edges) - 1):
        low, high = edges[i], edges[i + 1]
        if low <= s < high:
            if low == 0:
                return f"lt_{high}"
            if high >= 101:
                return f"ge_{low}"
            return f"{low}_to_{high - 1}"
    return f"ge_{edges[-2]}"


def _sl_bucket_label(sl_distance: float, edges: Sequence[float]) -> str:
    sl = abs(float(sl_distance))
    for i in range(len(edges) - 1):
        low, high = edges[i], edges[i + 1]
        if i == 0 and sl <= high:
            return f"le_{high:.2f}"
        if low < sl <= high:
            if high == float("inf"):
                return f"gt_{low:.2f}"
            return f"{low + 0.01:.2f}_to_{high:.2f}"
    return f"gt_{edges[-2]:.2f}"


def _aggregate_bucket(
    signals: Sequence[BacktestSignal],
    trades_by_sig_id: dict[int, BacktestTrade],
) -> dict:
    total = len(signals)
    accepted = sum(1 for s in signals if s.accepted)
    rejected = total - accepted
    rs: list[float] = []
    wins = losses = bes = 0
    for s in signals:
        if not s.accepted:
            continue
        t = trades_by_sig_id.get(id(s))
        if t is None or t.outcome == "NO_DATA":
            continue
        rs.append(t.r_multiple)
        if t.outcome == "BE":
            bes += 1
        elif t.r_multiple > 0:
            wins += 1
        elif t.r_multiple < 0:
            losses += 1
    valid_trades = wins + losses + bes
    win_loss_denom = wins + losses
    win_r = sum(r for r in rs if r > 0)
    loss_r = sum(-r for r in rs if r < 0)
    if loss_r > 0:
        pf: float = round(win_r / loss_r, 4)
    elif win_r > 0:
        pf = float("inf")
    else:
        pf = 0.0
    return {
        "total_signals": total,
        "accepted": accepted,
        "rejected": rejected,
        "valid_trades": valid_trades,
        "wins": wins,
        "losses": losses,
        "be": bes,
        "win_rate": round(wins / win_loss_denom, 4) if win_loss_denom > 0 else 0.0,
        "avg_r": round(fmean(rs), 4) if rs else 0.0,
        "profit_factor": pf if pf != float("inf") else 0.0,
        "max_drawdown_r": _max_drawdown_r(rs),
        "statistically_significant": valid_trades >= 30,
    }


def _max_drawdown_r(rs: Sequence[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in rs:
        cumulative += r
        peak = max(peak, cumulative)
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 4)


# ----------------------------------------------------------------------
# Breakdowns
# ----------------------------------------------------------------------

def _group_signals_by(
    signals: Sequence[BacktestSignal],
    trades_by_sig_id: dict[int, BacktestTrade],
    key_fn,
) -> dict[str, dict]:
    groups: dict[str, list[BacktestSignal]] = {}
    for s in signals:
        key = key_fn(s)
        if key is None:
            key = "unknown"
        groups.setdefault(str(key), []).append(s)
    return {k: _aggregate_bucket(v, trades_by_sig_id) for k, v in groups.items()}


def _score_x_sl_matrix(
    signals: Sequence[BacktestSignal],
    trades_by_sig_id: dict[int, BacktestTrade],
    cfg: ProfilerConfig,
) -> dict[str, dict[str, dict]]:
    matrix: dict[str, dict[str, dict]] = {}
    groups: dict[tuple[str, str], list[BacktestSignal]] = {}
    for s in signals:
        sb = _score_bucket_label(s.score, cfg.score_bucket_edges)
        slb = _sl_bucket_label(s.sl_distance, cfg.sl_bucket_edges)
        groups.setdefault((sb, slb), []).append(s)
    for (sb, slb), sigs in groups.items():
        matrix.setdefault(sb, {})[slb] = _aggregate_bucket(sigs, trades_by_sig_id)
    return matrix


def _confluence_split(
    signals: Sequence[BacktestSignal],
    trades_by_sig_id: dict[int, BacktestTrade],
    flag: str,
) -> dict[str, dict]:
    with_flag = [s for s in signals if bool((s.metadata or {}).get(flag))]
    without_flag = [s for s in signals if not bool((s.metadata or {}).get(flag))]
    return {
        "with": _aggregate_bucket(with_flag, trades_by_sig_id),
        "without": _aggregate_bucket(without_flag, trades_by_sig_id),
    }


def _full_micro_confluence_split(
    signals: Sequence[BacktestSignal],
    trades_by_sig_id: dict[int, BacktestTrade],
) -> dict[str, dict]:
    def _has_all(s: BacktestSignal) -> bool:
        mc = (s.metadata or {}).get("micro_confluence") or {}
        return bool(mc.get("all_pass"))

    return {
        "with_full_micro_confluence": _aggregate_bucket([s for s in signals if _has_all(s)], trades_by_sig_id),
        "without_full_micro_confluence": _aggregate_bucket([s for s in signals if not _has_all(s)], trades_by_sig_id),
    }


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def profile_adelin(
    signals: Iterable[BacktestSignal],
    trades: Iterable[BacktestTrade],
    *,
    config: ProfilerConfig | None = None,
) -> dict:
    cfg = config or ProfilerConfig()
    sigs = [s for s in signals if s.strategy == ADELIN_STRATEGY_NAME]
    trades_by_sig_id = {id(t.signal): t for t in trades if t.signal.strategy == ADELIN_STRATEGY_NAME}

    overall = _aggregate_bucket(sigs, trades_by_sig_id)

    by_score = _group_signals_by(sigs, trades_by_sig_id, lambda s: _score_bucket_label(s.score, cfg.score_bucket_edges))
    by_sl = _group_signals_by(sigs, trades_by_sig_id, lambda s: _sl_bucket_label(s.sl_distance, cfg.sl_bucket_edges))
    score_sl_matrix = _score_x_sl_matrix(sigs, trades_by_sig_id, cfg)
    by_setup_mode = _group_signals_by(sigs, trades_by_sig_id, lambda s: (s.metadata or {}).get("setup_mode"))
    by_session = _group_signals_by(sigs, trades_by_sig_id, lambda s: s.session)
    by_direction = _group_signals_by(sigs, trades_by_sig_id, lambda s: s.direction)

    confluence_splits = {
        "has_sweep": _confluence_split(sigs, trades_by_sig_id, "has_sweep"),
        "has_fvg": _confluence_split(sigs, trades_by_sig_id, "has_fvg"),
        "has_volume_confluence": _confluence_split(sigs, trades_by_sig_id, "has_volume_confluence"),
        "has_number_theory": _confluence_split(sigs, trades_by_sig_id, "has_number_theory"),
    }
    full_micro = _full_micro_confluence_split(sigs, trades_by_sig_id)

    return {
        "strategy": ADELIN_STRATEGY_NAME,
        "config": {
            "score_bucket_edges": list(cfg.score_bucket_edges),
            "sl_bucket_edges": [e if e != float("inf") else None for e in cfg.sl_bucket_edges],
            "min_trades_for_significance": cfg.min_trades_for_significance,
        },
        "overall": overall,
        "by_score_bucket": by_score,
        "by_sl_bucket": by_sl,
        "score_x_sl_matrix": score_sl_matrix,
        "by_setup_mode": by_setup_mode,
        "by_session": by_session,
        "by_direction": by_direction,
        "by_confluence": confluence_splits,
        "micro_confluence_split": full_micro,
    }


__all__ = [
    "ADELIN_STRATEGY_NAME",
    "ProfilerConfig",
    "profile_adelin",
]
