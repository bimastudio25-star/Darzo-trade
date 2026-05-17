"""
Trade-linked edge report.

Builds on the candle-behavior profiler by attaching each candle record
to its nearest Adelin trade (via dazro_trade.analytics.trade_link) and
then aggregating WR / PF / AvgR / max drawdown on the subset of *trades*
qualifying under each filter:

    - candle pattern label                  (continuation / rejection / ...)
    - zone type touched at signal time
    - presence flags                        (swept_high/low, reclaim, fvg,
                                              displacement bucket, relative
                                              volume bucket)
    - score bucket
    - direction
    - setup_mode

Goal: find an A+ subset of Adelin trades whose profit factor exceeds 1.
The report does NOT modify the live strategy; it only flags candidate
filters for a follow-up policy change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable, Sequence

from dazro_trade.analytics.candle_behavior_report import CandleBehaviorRecord
from dazro_trade.analytics.trade_link import TradeLink


@dataclass(frozen=True)
class TradeLinkedConfig:
    min_trades_for_significance: int = 30
    # Anti-overfitting guardrails for the A+ subset finder.
    exploratory_min_trades: int = 20
    valid_min_trades: int = 50
    robust_min_trades: int = 100
    valid_min_profit_factor: float = 1.15
    valid_min_avg_r: float = 0.0
    # Soft warning thresholds
    confidence_warn_below: int = 30
    strong_warn_below: int = 50
    displacement_buckets: tuple[tuple[str, float, float], ...] = (
        ("d_lt_1.0", 0.0, 1.0),
        ("d_1.0_to_1.5", 1.0, 1.5),
        ("d_1.5_to_2.5", 1.5, 2.5),
        ("d_ge_2.5", 2.5, float("inf")),
    )
    relative_volume_buckets: tuple[tuple[str, float, float], ...] = (
        ("rv_lt_0.75", 0.0, 0.75),
        ("rv_0.75_to_1.25", 0.75, 1.25),
        ("rv_1.25_to_2.0", 1.25, 2.0),
        ("rv_ge_2.0", 2.0, float("inf")),
    )


@dataclass(frozen=True)
class LinkedTrade:
    """A trade enriched with the candle-behavior features that fired
    at (or near) the signal timestamp."""
    trade_outcome: str
    r_multiple: float
    score: int | None
    setup_mode: str | None
    direction: str | None
    session: str | None
    pattern_label: str
    swept_high: bool
    swept_low: bool
    reclaim_after_sweep: bool
    fvg_created: bool
    ifvg_created: bool
    absorption: bool
    continuation: bool
    rejection: bool
    displacement_score: float
    relative_volume_20: float | None
    zone_type: str | None
    zone_side: str | None
    sl_distance: float | None


# ----------------------------------------------------------------------
# Build linked trade list from records + links
# ----------------------------------------------------------------------

def build_linked_trades(
    records: Sequence[CandleBehaviorRecord],
    trade_links: dict[int, TradeLink],
) -> list[LinkedTrade]:
    """One LinkedTrade per unique signal that has a trade outcome.

    For each signal in trade_links, pick the record whose timestamp is
    closest to the signal timestamp (= the record_index keyed in
    trade_links). If the same signal got linked to multiple records,
    we keep the closest one (smallest distance_to_signal_bars).
    """
    chosen_by_signal: dict[Any, tuple[int, TradeLink]] = {}
    for idx, link in trade_links.items():
        if link.nearest_signal_timestamp is None or link.trade_outcome is None:
            continue
        if link.trade_outcome == "NO_DATA":
            continue
        key = link.nearest_signal_timestamp
        current = chosen_by_signal.get(key)
        if current is None or (link.distance_to_signal_bars or 0) < (current[1].distance_to_signal_bars or 0):
            chosen_by_signal[key] = (idx, link)

    linked: list[LinkedTrade] = []
    for idx, link in chosen_by_signal.values():
        rec = records[idx] if 0 <= idx < len(records) else None
        if rec is None:
            continue
        features = rec.features or {}
        zone_type = rec.touches[0].zone.type if rec.touches else None
        zone_side = rec.touches[0].zone.side if rec.touches else None
        linked.append(LinkedTrade(
            trade_outcome=link.trade_outcome,
            r_multiple=float(link.trade_r_multiple) if link.trade_r_multiple is not None else 0.0,
            score=link.nearest_signal_score,
            setup_mode=link.nearest_signal_setup_mode,
            direction=link.nearest_signal_direction,
            session=link.nearest_signal_session,
            pattern_label=rec.pattern_label,
            swept_high=bool(features.get("swept_high")),
            swept_low=bool(features.get("swept_low")),
            reclaim_after_sweep=bool(features.get("reclaim_after_sweep")),
            fvg_created=bool(features.get("fvg_created")),
            ifvg_created=bool(features.get("ifvg_created")),
            absorption=bool(features.get("absorption_candidate")),
            continuation=bool(features.get("continuation_candidate")),
            rejection=bool(features.get("rejection_candidate")),
            displacement_score=float(features.get("displacement_score") or 0.0),
            relative_volume_20=(
                None if features.get("relative_volume_20") is None
                else float(features["relative_volume_20"])
            ),
            zone_type=zone_type,
            zone_side=zone_side,
            sl_distance=link.nearest_signal_sl_distance,
        ))
    return linked


# ----------------------------------------------------------------------
# Stats helpers
# ----------------------------------------------------------------------

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


def _longest_loss_streak(rs: Sequence[float]) -> int:
    longest = 0
    current = 0
    for r in rs:
        if r < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _trade_stats(trades: Sequence[LinkedTrade]) -> dict[str, Any]:
    rs = [t.r_multiple for t in trades if t.trade_outcome != "NO_DATA"]
    if not rs:
        return {
            "n_trades": 0, "wins": 0, "losses": 0, "be": 0,
            "win_rate": 0.0, "loss_rate": 0.0, "avg_r": 0.0, "median_r": 0.0,
            "expectancy_r": 0.0,
            "profit_factor": 0.0, "max_drawdown_r": 0.0,
            "longest_loss_streak": 0,
            "best_r": 0.0, "worst_r": 0.0, "statistically_significant": False,
        }
    wins = sum(1 for r in rs if r > 0)
    losses = sum(1 for r in rs if r < 0)
    be = sum(1 for r in rs if r == 0)
    win_r = sum(r for r in rs if r > 0)
    loss_r = sum(-r for r in rs if r < 0)
    if loss_r > 0:
        pf: float = round(win_r / loss_r, 4)
    elif win_r > 0:
        pf = 999.0
    else:
        pf = 0.0
    denom = wins + losses
    avg_r = round(fmean(rs), 4)
    return {
        "n_trades": len(rs),
        "wins": wins,
        "losses": losses,
        "be": be,
        "win_rate": round(wins / denom, 4) if denom > 0 else 0.0,
        "loss_rate": round(losses / denom, 4) if denom > 0 else 0.0,
        "avg_r": avg_r,
        "median_r": round(median(rs), 4),
        "expectancy_r": avg_r,
        "profit_factor": pf,
        "max_drawdown_r": _max_drawdown_r(rs),
        "longest_loss_streak": _longest_loss_streak(rs),
        "best_r": round(max(rs), 4),
        "worst_r": round(min(rs), 4),
        "statistically_significant": len(rs) >= 30,
    }


# ----------------------------------------------------------------------
# Filters
# ----------------------------------------------------------------------

def _bucket(value: float | None, buckets: Sequence[tuple[str, float, float]]) -> str | None:
    if value is None:
        return None
    v = float(value)
    for label, low, high in buckets:
        if low <= v < high:
            return label
    return None


def _by_pattern(trades: Sequence[LinkedTrade]) -> dict[str, dict]:
    groups: dict[str, list[LinkedTrade]] = {}
    for t in trades:
        groups.setdefault(t.pattern_label, []).append(t)
    return {k: _trade_stats(v) for k, v in groups.items()}


def _by_zone_type(trades: Sequence[LinkedTrade]) -> dict[str, dict]:
    groups: dict[str, list[LinkedTrade]] = {}
    for t in trades:
        groups.setdefault(t.zone_type or "no_zone", []).append(t)
    return {k: _trade_stats(v) for k, v in groups.items()}


def _by_setup_mode(trades: Sequence[LinkedTrade]) -> dict[str, dict]:
    groups: dict[str, list[LinkedTrade]] = {}
    for t in trades:
        groups.setdefault(t.setup_mode or "unknown", []).append(t)
    return {k: _trade_stats(v) for k, v in groups.items()}


def _by_session(trades: Sequence[LinkedTrade]) -> dict[str, dict]:
    groups: dict[str, list[LinkedTrade]] = {}
    for t in trades:
        groups.setdefault(t.session or "unknown", []).append(t)
    return {k: _trade_stats(v) for k, v in groups.items()}


def _by_direction(trades: Sequence[LinkedTrade]) -> dict[str, dict]:
    groups: dict[str, list[LinkedTrade]] = {}
    for t in trades:
        groups.setdefault(t.direction or "unknown", []).append(t)
    return {k: _trade_stats(v) for k, v in groups.items()}


def _by_flag(trades: Sequence[LinkedTrade], attr: str) -> dict[str, dict]:
    groups: dict[str, list[LinkedTrade]] = {"with": [], "without": []}
    for t in trades:
        key = "with" if bool(getattr(t, attr)) else "without"
        groups[key].append(t)
    return {k: _trade_stats(v) for k, v in groups.items()}


def _by_bucket(trades: Sequence[LinkedTrade], value_fn, buckets) -> dict[str, dict]:
    groups: dict[str, list[LinkedTrade]] = {}
    for t in trades:
        label = _bucket(value_fn(t), buckets)
        if label is None:
            continue
        groups.setdefault(label, []).append(t)
    return {k: _trade_stats(v) for k, v in groups.items()}


# ----------------------------------------------------------------------
# A+ subset finder
# ----------------------------------------------------------------------

FILTER_KEYS_FOR_A_PLUS: tuple[str, ...] = (
    "swept_high",
    "swept_low",
    "reclaim_after_sweep",
    "fvg_created",
    "ifvg_created",
    "continuation",
    "rejection",
)


def _matches_filter(t: LinkedTrade, filter_spec: tuple[tuple[str, bool], ...]) -> bool:
    for attr, expected in filter_spec:
        if bool(getattr(t, attr)) != expected:
            return False
    return True


def _score_candidate(
    combo: tuple[str, ...],
    subset_stats: dict[str, Any],
    baseline_stats: dict[str, Any],
    baseline_n: int,
    cfg: TradeLinkedConfig,
) -> dict[str, Any]:
    """Wrap subset_stats with anti-overfitting guardrails."""
    n = int(subset_stats.get("n_trades", 0))
    sample_pct = round(n / baseline_n, 4) if baseline_n > 0 else 0.0
    warnings: list[str] = []
    if n < cfg.confidence_warn_below:
        warnings.append(f"confidence_warning_n<{cfg.confidence_warn_below}")
    if n < cfg.strong_warn_below:
        warnings.append(f"strong_warning_n<{cfg.strong_warn_below}")
    delta_pf = round(subset_stats["profit_factor"] - baseline_stats.get("profit_factor", 0.0), 4)
    delta_avg_r = round(subset_stats["avg_r"] - baseline_stats.get("avg_r", 0.0), 4)
    delta_win_rate = round(subset_stats["win_rate"] - baseline_stats.get("win_rate", 0.0), 4)
    delta_max_dd = round(subset_stats["max_drawdown_r"] - baseline_stats.get("max_drawdown_r", 0.0), 4)
    delta_longest_loss = subset_stats.get("longest_loss_streak", 0) - baseline_stats.get("longest_loss_streak", 0)
    worse_aspects: list[str] = []
    if delta_max_dd > 0:
        worse_aspects.append(f"max_drawdown_r increased by {delta_max_dd}")
    if delta_longest_loss > 0:
        worse_aspects.append(f"longest_loss_streak increased by {delta_longest_loss}")
    if subset_stats["worst_r"] < baseline_stats.get("worst_r", 0.0):
        worse_aspects.append("worst trade R got worse")
    valid_candidate = (
        n >= cfg.valid_min_trades
        and subset_stats["profit_factor"] >= cfg.valid_min_profit_factor
        and subset_stats["avg_r"] >= cfg.valid_min_avg_r
    )
    is_robust = n >= cfg.robust_min_trades and valid_candidate
    is_exploratory = n >= cfg.exploratory_min_trades and not valid_candidate

    return {
        "filter_rules_required": list(combo),
        "rules_excluded_from_baseline": [k for k in FILTER_KEYS_FOR_A_PLUS if k not in combo],
        "baseline_trade_count": baseline_n,
        "trade_count": n,
        "win_count": subset_stats["wins"],
        "loss_count": subset_stats["losses"],
        "be_count": subset_stats["be"],
        "sample_pct": sample_pct,
        "win_rate": subset_stats["win_rate"],
        "profit_factor": subset_stats["profit_factor"],
        "avg_r": subset_stats["avg_r"],
        "median_r": subset_stats["median_r"],
        "expectancy_r": subset_stats["expectancy_r"],
        "max_drawdown_r": subset_stats["max_drawdown_r"],
        "longest_loss_streak": subset_stats["longest_loss_streak"],
        "best_r": subset_stats["best_r"],
        "worst_r": subset_stats["worst_r"],
        "delta_profit_factor_vs_baseline": delta_pf,
        "delta_avg_r_vs_baseline": delta_avg_r,
        "delta_win_rate_vs_baseline": delta_win_rate,
        "delta_max_drawdown_vs_baseline": delta_max_dd,
        "delta_longest_loss_streak_vs_baseline": delta_longest_loss,
        "worse_than_baseline": worse_aspects,
        "warnings": warnings,
        "valid_candidate": valid_candidate,
        "is_robust": is_robust,
        "is_exploratory_only": is_exploratory,
    }


def find_a_plus_subsets(
    trades: Sequence[LinkedTrade],
    *,
    cfg: TradeLinkedConfig,
    keys: tuple[str, ...] = FILTER_KEYS_FOR_A_PLUS,
    max_combo_size: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Exhaustive scan of small filter combinations from `keys`.

    Returns a dict with three separately ranked lists:
        exploratory_candidates  n >= cfg.exploratory_min_trades
        valid_candidates        n >= cfg.valid_min_trades AND
                                PF >= cfg.valid_min_profit_factor AND
                                avg_r >= cfg.valid_min_avg_r
        robust_candidates       n >= cfg.robust_min_trades AND valid

    Each candidate carries anti-overfitting metadata: trade_count,
    win_count/loss_count, sample_pct, WR/PF/AvgR/median_R/expectancy_R,
    MaxDD, longest_loss_streak, delta_* vs baseline, worse_than_baseline
    aspects, warnings (confidence/strong) and the boolean flags
    valid_candidate / is_robust / is_exploratory_only.
    """
    baseline_stats = _trade_stats(trades)
    baseline_n = baseline_stats["n_trades"]
    exploratory: list[dict[str, Any]] = []
    valid: list[dict[str, Any]] = []
    robust: list[dict[str, Any]] = []

    for size in range(1, max_combo_size + 1):
        for combo in combinations(keys, size):
            spec = tuple((k, True) for k in combo)
            subset = [t for t in trades if _matches_filter(t, spec)]
            if len(subset) < cfg.exploratory_min_trades:
                continue
            stats = _trade_stats(subset)
            scored = _score_candidate(combo, stats, baseline_stats, baseline_n, cfg)
            if scored["is_robust"]:
                robust.append(scored)
                valid.append(scored)
            elif scored["valid_candidate"]:
                valid.append(scored)
            else:
                exploratory.append(scored)

    def _sort_key(r: dict[str, Any]) -> tuple[float, float, int]:
        return (float(r["profit_factor"]), float(r["avg_r"]), int(r["trade_count"]))

    exploratory.sort(key=_sort_key, reverse=True)
    valid.sort(key=_sort_key, reverse=True)
    robust.sort(key=_sort_key, reverse=True)

    return {
        "baseline": {**baseline_stats, "baseline_trade_count": baseline_n},
        "exploratory_candidates": exploratory,
        "valid_candidates": valid,
        "robust_candidates": robust,
    }


# ----------------------------------------------------------------------
# Build full report
# ----------------------------------------------------------------------

def build_trade_linked_report(
    records: Sequence[CandleBehaviorRecord],
    trade_links: dict[int, TradeLink],
    *,
    config: TradeLinkedConfig | None = None,
) -> dict[str, Any]:
    cfg = config or TradeLinkedConfig()
    linked = build_linked_trades(records, trade_links)
    overall = _trade_stats(linked)
    by_pattern = _by_pattern(linked)
    by_zone = _by_zone_type(linked)
    by_setup_mode = _by_setup_mode(linked)
    by_session = _by_session(linked)
    by_direction = _by_direction(linked)
    by_flags = {flag: _by_flag(linked, flag) for flag in FILTER_KEYS_FOR_A_PLUS}
    by_displacement = _by_bucket(linked, lambda t: t.displacement_score, cfg.displacement_buckets)
    by_relative_volume = _by_bucket(linked, lambda t: t.relative_volume_20, cfg.relative_volume_buckets)
    a_plus = find_a_plus_subsets(linked, cfg=cfg)
    verdict = _build_verdict(overall, a_plus, cfg)
    return {
        "config": {
            "min_trades_for_significance": cfg.min_trades_for_significance,
            "exploratory_min_trades": cfg.exploratory_min_trades,
            "valid_min_trades": cfg.valid_min_trades,
            "robust_min_trades": cfg.robust_min_trades,
            "valid_min_profit_factor": cfg.valid_min_profit_factor,
            "valid_min_avg_r": cfg.valid_min_avg_r,
            "displacement_buckets": [list(b) for b in cfg.displacement_buckets],
            "relative_volume_buckets": [list(b) for b in cfg.relative_volume_buckets],
        },
        "n_linked_trades": len(linked),
        "overall": overall,
        "by_pattern": by_pattern,
        "by_zone_type": by_zone,
        "by_setup_mode": by_setup_mode,
        "by_session": by_session,
        "by_direction": by_direction,
        "by_flag": by_flags,
        "by_displacement_bucket": by_displacement,
        "by_relative_volume_bucket": by_relative_volume,
        "a_plus_subsets": a_plus,
        "verdict": verdict,
    }


def _build_verdict(overall: dict[str, Any], a_plus: dict[str, list], cfg: TradeLinkedConfig) -> dict[str, Any]:
    robust = a_plus.get("robust_candidates", [])
    valid = a_plus.get("valid_candidates", [])
    exploratory = a_plus.get("exploratory_candidates", [])
    baseline_profitable = overall.get("profit_factor", 0.0) >= 1.0 and overall.get("avg_r", 0.0) >= 0.0
    if robust:
        decision = "PROFITABLE_SUBSET_FOUND_ROBUST"
        rationale = (
            f"At least {len(robust)} robust subset(s) found "
            f"(n >= {cfg.robust_min_trades}, PF >= {cfg.valid_min_profit_factor}, avg_R >= {cfg.valid_min_avg_r}). "
            "Strategy has actionable edge under those filters."
        )
    elif valid:
        decision = "PROFITABLE_SUBSET_FOUND_NEEDS_MORE_DATA"
        rationale = (
            f"{len(valid)} valid subset(s) found at n >= {cfg.valid_min_trades} but none at the "
            f"robust threshold (n >= {cfg.robust_min_trades}). Edge looks real but sample size still "
            "too small for production deployment without further validation."
        )
    elif exploratory:
        decision = "WEAK_EXPLORATORY_ONLY"
        rationale = (
            f"Only {len(exploratory)} exploratory candidate(s) above n >= {cfg.exploratory_min_trades} "
            "and they failed the valid thresholds. Likely overfitting risk; no actionable edge yet."
        )
    elif baseline_profitable:
        decision = "BASELINE_OK_NO_FILTER_NEEDED"
        rationale = "Baseline Adelin is already profitable; no filter combination significantly improves it."
    else:
        decision = "NO_EDGE_FOUND_SUSPEND_OR_REWORK"
        rationale = (
            "Baseline Adelin is unprofitable (PF < 1 or avg_R < 0) and no subset filter restores "
            "edge. Suspend Adelin until the entry/score logic is reworked."
        )
    return {
        "decision": decision,
        "rationale": rationale,
        "robust_count": len(robust),
        "valid_count": len(valid),
        "exploratory_count": len(exploratory),
        "baseline_profit_factor": overall.get("profit_factor", 0.0),
        "baseline_avg_r": overall.get("avg_r", 0.0),
        "baseline_max_drawdown_r": overall.get("max_drawdown_r", 0.0),
    }


def render_trade_linked_markdown(report: dict[str, Any]) -> str:
    def _fmt(v: Any) -> str:
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:.4f}"
        return str(v)

    lines: list[str] = []
    overall = report.get("overall") or {}
    lines.append("# Adelin trade-linked edge report\n")
    lines.append("## Overall\n")
    lines.append(f"- linked trades: {report.get('n_linked_trades')}")
    lines.append(f"- wins / losses / BE: {overall.get('wins')} / {overall.get('losses')} / {overall.get('be')}")
    lines.append(f"- win_rate: {_fmt(overall.get('win_rate'))}")
    lines.append(f"- profit_factor: {_fmt(overall.get('profit_factor'))}")
    lines.append(f"- avg_R: {_fmt(overall.get('avg_r'))}")
    lines.append(f"- max_drawdown_R: {_fmt(overall.get('max_drawdown_r'))}\n")

    def _table(title: str, buckets: dict[str, dict]) -> str:
        if not buckets:
            return f"### {title}\n\n_no data_\n\n"
        headers = ["bucket", "n", "wins", "loss", "BE", "WR", "PF", "avg_R", "max_DD", "best", "worst", "sig"]
        rows = []
        for k in sorted(buckets.keys()):
            s = buckets[k]
            rows.append(
                "| " + " | ".join([
                    k, str(s.get("n_trades")), str(s.get("wins")), str(s.get("losses")), str(s.get("be")),
                    _fmt(s.get("win_rate")), _fmt(s.get("profit_factor")), _fmt(s.get("avg_r")),
                    _fmt(s.get("max_drawdown_r")), _fmt(s.get("best_r")), _fmt(s.get("worst_r")),
                    "YES" if s.get("statistically_significant") else "no",
                ]) + " |"
            )
        body = (
            f"### {title}\n\n"
            + "| " + " | ".join(headers) + " |\n"
            + "|" + "|".join(["---"] * len(headers)) + "|\n"
            + "\n".join(rows)
        )
        return body + "\n\n"

    lines.append(_table("By candle pattern", report.get("by_pattern") or {}))
    lines.append(_table("By zone type", report.get("by_zone_type") or {}))
    lines.append(_table("By setup_mode", report.get("by_setup_mode") or {}))
    lines.append(_table("By session", report.get("by_session") or {}))
    lines.append(_table("By direction", report.get("by_direction") or {}))
    lines.append(_table("By displacement bucket", report.get("by_displacement_bucket") or {}))
    lines.append(_table("By relative-volume bucket", report.get("by_relative_volume_bucket") or {}))

    by_flag = report.get("by_flag") or {}
    for flag, buckets in by_flag.items():
        lines.append(_table(f"By flag: {flag}", buckets))

    verdict = report.get("verdict") or {}
    if verdict:
        lines.append("## Verdict\n")
        lines.append(f"- **decision**: `{verdict.get('decision')}`")
        lines.append(f"- rationale: {verdict.get('rationale')}")
        lines.append(f"- robust_count: {verdict.get('robust_count')}")
        lines.append(f"- valid_count: {verdict.get('valid_count')}")
        lines.append(f"- exploratory_count: {verdict.get('exploratory_count')}")
        lines.append(f"- baseline_profit_factor: {_fmt(verdict.get('baseline_profit_factor'))}")
        lines.append(f"- baseline_avg_r: {_fmt(verdict.get('baseline_avg_r'))}")
        lines.append(f"- baseline_max_drawdown_r: {_fmt(verdict.get('baseline_max_drawdown_r'))}\n")

    a_plus = report.get("a_plus_subsets") or {}
    cfg = report.get("config") or {}

    def _candidate_block(title: str, items: list[dict], threshold_label: str) -> str:
        out_lines: list[str] = [f"## {title} ({threshold_label})\n"]
        if not items:
            out_lines.append("_no qualifying subset_\n")
            return "\n".join(out_lines)
        headers = [
            "filter", "n", "sample%", "wins", "loss", "WR", "PF", "avg_R",
            "median_R", "max_DD", "loss_streak",
            "ΔPF", "Δavg_R", "ΔWR", "Δmax_DD",
            "worse", "warnings",
        ]
        out_lines.append("| " + " | ".join(headers) + " |")
        out_lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for row in items[:30]:
            cells = [
                " + ".join(row.get("filter_rules_required", [])) or "(none)",
                str(row.get("trade_count")),
                _fmt(row.get("sample_pct")),
                str(row.get("win_count")),
                str(row.get("loss_count")),
                _fmt(row.get("win_rate")),
                _fmt(row.get("profit_factor")),
                _fmt(row.get("avg_r")),
                _fmt(row.get("median_r")),
                _fmt(row.get("max_drawdown_r")),
                str(row.get("longest_loss_streak")),
                _fmt(row.get("delta_profit_factor_vs_baseline")),
                _fmt(row.get("delta_avg_r_vs_baseline")),
                _fmt(row.get("delta_win_rate_vs_baseline")),
                _fmt(row.get("delta_max_drawdown_vs_baseline")),
                "; ".join(row.get("worse_than_baseline") or []) or "—",
                "; ".join(row.get("warnings") or []) or "—",
            ]
            out_lines.append("| " + " | ".join(cells) + " |")
        out_lines.append("")
        return "\n".join(out_lines)

    lines.append(_candidate_block(
        "Robust candidates",
        a_plus.get("robust_candidates") or [],
        f"n >= {cfg.get('robust_min_trades')}, PF >= {cfg.get('valid_min_profit_factor')}, avg_R >= {cfg.get('valid_min_avg_r')}",
    ))
    lines.append(_candidate_block(
        "Valid candidates",
        a_plus.get("valid_candidates") or [],
        f"n >= {cfg.get('valid_min_trades')}, PF >= {cfg.get('valid_min_profit_factor')}, avg_R >= {cfg.get('valid_min_avg_r')}",
    ))
    lines.append(_candidate_block(
        "Exploratory candidates (DO NOT DEPLOY — sample too small)",
        a_plus.get("exploratory_candidates") or [],
        f"n >= {cfg.get('exploratory_min_trades')} but failed valid thresholds",
    ))

    return "\n".join(lines)


def write_trade_linked_files(
    *,
    output_dir: str,
    report: dict[str, Any],
    file_stem: str = "profile_trade_linked_edge",
) -> dict[str, str]:
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    json_path = out_root / f"{file_stem}.json"
    md_path = out_root / f"{file_stem}.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_trade_linked_markdown(report), encoding="utf-8")
    return {"trade_linked_json": str(json_path), "trade_linked_md": str(md_path)}


__all__ = [
    "FILTER_KEYS_FOR_A_PLUS",
    "LinkedTrade",
    "TradeLinkedConfig",
    "build_linked_trades",
    "build_trade_linked_report",
    "find_a_plus_subsets",
    "render_trade_linked_markdown",
    "write_trade_linked_files",
]
