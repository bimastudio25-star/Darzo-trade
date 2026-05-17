"""
Adelin candle-behavior + zone-reaction report builder.

Iterates an M1/M5 dataframe, computes candle features for each row,
finds zone touches against the supplied zone list, computes the
post-touch reaction for each touch and aggregates the records by:

  - candle pattern label (absorption / continuation / rejection /
    none / multiple)
  - zone type
  - pattern x zone type combination
  - session (column `session` if present, else "unknown")
  - news proximity (TODO -- news_events not yet populated in backtest)

Returns a JSON-ready dict with stats per bucket plus best / worst
combos and helper writers for Markdown / JSON files.

The module is read-only and side-effect free: it does not modify the
strategy, the dataframe, or the zone list.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Sequence

import pandas as pd

from dazro_trade.analytics.candle_features import compute_candle_features
from dazro_trade.analytics.zone_features import Zone, ZoneTouch, detect_touches
from dazro_trade.analytics.zone_reactions import (
    DEFAULT_HORIZONS,
    ZoneReaction,
    compute_reaction,
)

NEWS_PROXIMITY_TODO_LABEL = "news_proximity_unavailable"


@dataclass(frozen=True)
class CandleBehaviorConfig:
    relative_volume_lookbacks: tuple[int, ...] = (20, 50)
    displacement_lookback: int = 20
    sweep_lookback: int = 10
    horizons: tuple[int, ...] = DEFAULT_HORIZONS
    min_history: int = 30
    max_records: int | None = None


@dataclass(frozen=True)
class CandleBehaviorRecord:
    timestamp: Any
    session: str
    features: dict[str, Any]
    touches: list[ZoneTouch]
    reactions: list[ZoneReaction]

    @property
    def pattern_label(self) -> str:
        flags = (
            self.features.get("absorption_candidate", False),
            self.features.get("continuation_candidate", False),
            self.features.get("rejection_candidate", False),
        )
        names = []
        if flags[0]:
            names.append("absorption")
        if flags[1]:
            names.append("continuation")
        if flags[2]:
            names.append("rejection")
        if not names:
            return "none"
        if len(names) == 1:
            return names[0]
        return "multiple:" + "+".join(sorted(names))


# ----------------------------------------------------------------------
# Iterator
# ----------------------------------------------------------------------

def iterate_candle_behavior_records(
    df: pd.DataFrame,
    zones: Sequence[Zone],
    *,
    session_for_time=None,
    config: CandleBehaviorConfig | None = None,
) -> list[CandleBehaviorRecord]:
    cfg = config or CandleBehaviorConfig()
    if df is None or len(df) <= cfg.min_history:
        return []
    out: list[CandleBehaviorRecord] = []
    df_indexed = df.reset_index(drop=True)
    n = len(df_indexed)
    for i in range(cfg.min_history, n):
        candle = df_indexed.iloc[i]
        history = df_indexed.iloc[:i]
        features = compute_candle_features(
            candle, history,
            relative_volume_lookbacks=cfg.relative_volume_lookbacks,
            displacement_lookback=cfg.displacement_lookback,
            sweep_lookback=cfg.sweep_lookback,
        )
        touches = detect_touches(candle, zones)
        reactions: list[ZoneReaction] = []
        future_slice = df_indexed.iloc[i + 1 : i + 1 + max(cfg.horizons)]
        if touches:
            close_val = float(candle["close"] if "close" in candle else candle["c"])
            vol_val = float(candle["tick_volume"] if "tick_volume" in candle else candle.get("vol", 0))
            for t in touches:
                reactions.append(
                    compute_reaction(
                        t,
                        touch_candle_close=close_val,
                        touch_candle_volume=vol_val,
                        future=future_slice,
                        history_for_relative_volume=history,
                        horizons=cfg.horizons,
                    )
                )
        ts = candle["time"] if "time" in candle else None
        session = session_for_time(ts) if session_for_time and ts is not None else (candle.get("session") if hasattr(candle, "get") else "unknown")
        if session is None:
            session = "unknown"
        out.append(
            CandleBehaviorRecord(
                timestamp=ts,
                session=str(session),
                features=features,
                touches=touches,
                reactions=reactions,
            )
        )
        if cfg.max_records is not None and len(out) >= cfg.max_records:
            break
    return out


# ----------------------------------------------------------------------
# Aggregations
# ----------------------------------------------------------------------

def _aggregate_records(
    records: Sequence[CandleBehaviorRecord],
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    if not records:
        return _empty_bucket(horizons)
    n_records = len(records)
    n_with_touch = sum(1 for r in records if r.touches)
    reactions: list[ZoneReaction] = [rxn for r in records for rxn in r.reactions]
    n_reactions = len(reactions)
    mean_reaction = {h: None for h in horizons}
    if n_reactions:
        for h in horizons:
            vals = [r.reaction_at.get(h) for r in reactions if r.reaction_at.get(h) is not None]
            mean_reaction[h] = round(fmean(vals), 4) if vals else None
    mfes = [r.max_favorable_excursion for r in reactions]
    maes = [r.max_adverse_excursion for r in reactions]
    return {
        "candle_count": n_records,
        "candles_with_touch": n_with_touch,
        "touch_count": n_reactions,
        "mean_reaction_at": mean_reaction,
        "mean_mfe": round(fmean(mfes), 4) if mfes else 0.0,
        "mean_mae": round(fmean(maes), 4) if maes else 0.0,
        "rate_did_sweep": round(sum(1 for r in reactions if r.did_sweep) / n_reactions, 4) if n_reactions else 0.0,
        "rate_did_reclaim": round(sum(1 for r in reactions if r.did_reclaim) / n_reactions, 4) if n_reactions else 0.0,
        "rate_did_displace": round(sum(1 for r in reactions if r.did_displace) / n_reactions, 4) if n_reactions else 0.0,
        "rate_did_break_and_continue": round(sum(1 for r in reactions if r.did_break_and_continue) / n_reactions, 4) if n_reactions else 0.0,
        "rate_did_reject": round(sum(1 for r in reactions if r.did_reject) / n_reactions, 4) if n_reactions else 0.0,
        "statistically_significant": n_reactions >= 30,
    }


def _empty_bucket(horizons: tuple[int, ...]) -> dict[str, Any]:
    return {
        "candle_count": 0,
        "candles_with_touch": 0,
        "touch_count": 0,
        "mean_reaction_at": {h: None for h in horizons},
        "mean_mfe": 0.0,
        "mean_mae": 0.0,
        "rate_did_sweep": 0.0,
        "rate_did_reclaim": 0.0,
        "rate_did_displace": 0.0,
        "rate_did_break_and_continue": 0.0,
        "rate_did_reject": 0.0,
        "statistically_significant": False,
    }


def aggregate_by_pattern(records: Sequence[CandleBehaviorRecord], horizons: tuple[int, ...] = DEFAULT_HORIZONS) -> dict[str, dict]:
    groups: dict[str, list[CandleBehaviorRecord]] = {}
    for r in records:
        groups.setdefault(r.pattern_label, []).append(r)
    return {k: _aggregate_records(v, horizons=horizons) for k, v in groups.items()}


def aggregate_by_zone_type(records: Sequence[CandleBehaviorRecord], horizons: tuple[int, ...] = DEFAULT_HORIZONS) -> dict[str, dict]:
    grouped_records: dict[str, list[CandleBehaviorRecord]] = {}
    grouped_reactions: dict[str, list[ZoneReaction]] = {}
    for r in records:
        seen_types_for_record: set[str] = set()
        for touch, rxn in zip(r.touches, r.reactions):
            zt = touch.zone.type
            if zt not in seen_types_for_record:
                grouped_records.setdefault(zt, []).append(r)
                seen_types_for_record.add(zt)
            grouped_reactions.setdefault(zt, []).append(rxn)
    out: dict[str, dict] = {}
    for zt, recs in grouped_records.items():
        agg = _aggregate_records(recs, horizons=horizons)
        # Override the reaction stats with the zone-type-specific subset.
        rxns = grouped_reactions.get(zt, [])
        if rxns:
            agg["touch_count"] = len(rxns)
            for h in horizons:
                vals = [r.reaction_at.get(h) for r in rxns if r.reaction_at.get(h) is not None]
                agg["mean_reaction_at"][h] = round(fmean(vals), 4) if vals else None
            mfes = [r.max_favorable_excursion for r in rxns]
            maes = [r.max_adverse_excursion for r in rxns]
            agg["mean_mfe"] = round(fmean(mfes), 4) if mfes else 0.0
            agg["mean_mae"] = round(fmean(maes), 4) if maes else 0.0
            agg["rate_did_sweep"] = round(sum(1 for r in rxns if r.did_sweep) / len(rxns), 4)
            agg["rate_did_reclaim"] = round(sum(1 for r in rxns if r.did_reclaim) / len(rxns), 4)
            agg["rate_did_displace"] = round(sum(1 for r in rxns if r.did_displace) / len(rxns), 4)
            agg["rate_did_break_and_continue"] = round(sum(1 for r in rxns if r.did_break_and_continue) / len(rxns), 4)
            agg["rate_did_reject"] = round(sum(1 for r in rxns if r.did_reject) / len(rxns), 4)
            agg["statistically_significant"] = len(rxns) >= 30
        out[zt] = agg
    return out


def aggregate_by_pattern_zone_combo(
    records: Sequence[CandleBehaviorRecord],
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, dict]:
    groups: dict[str, list[ZoneReaction]] = {}
    for r in records:
        pattern = r.pattern_label
        for touch, rxn in zip(r.touches, r.reactions):
            key = f"{pattern}__{touch.zone.type}"
            groups.setdefault(key, []).append(rxn)
    out: dict[str, dict] = {}
    for key, rxns in groups.items():
        n = len(rxns)
        mean_reaction = {h: None for h in horizons}
        for h in horizons:
            vals = [r.reaction_at.get(h) for r in rxns if r.reaction_at.get(h) is not None]
            mean_reaction[h] = round(fmean(vals), 4) if vals else None
        mfes = [r.max_favorable_excursion for r in rxns]
        maes = [r.max_adverse_excursion for r in rxns]
        out[key] = {
            "touch_count": n,
            "mean_reaction_at": mean_reaction,
            "mean_mfe": round(fmean(mfes), 4) if mfes else 0.0,
            "mean_mae": round(fmean(maes), 4) if maes else 0.0,
            "rate_did_reject": round(sum(1 for r in rxns if r.did_reject) / n, 4) if n else 0.0,
            "rate_did_break_and_continue": round(sum(1 for r in rxns if r.did_break_and_continue) / n, 4) if n else 0.0,
            "statistically_significant": n >= 30,
        }
    return out


def aggregate_by_session(records: Sequence[CandleBehaviorRecord], horizons: tuple[int, ...] = DEFAULT_HORIZONS) -> dict[str, dict]:
    groups: dict[str, list[CandleBehaviorRecord]] = {}
    for r in records:
        groups.setdefault(r.session or "unknown", []).append(r)
    return {k: _aggregate_records(v, horizons=horizons) for k, v in groups.items()}


# ----------------------------------------------------------------------
# Best / worst combos
# ----------------------------------------------------------------------

def rank_combos(
    combo_stats: dict[str, dict],
    *,
    horizon: int = 5,
    min_touches: int = 30,
) -> dict[str, list[dict]]:
    scored: list[tuple[float, str, dict]] = []
    for key, stats in combo_stats.items():
        if stats.get("touch_count", 0) < min_touches:
            continue
        score = stats.get("mean_reaction_at", {}).get(horizon)
        if score is None:
            continue
        scored.append((float(score), key, stats))
    scored.sort(key=lambda x: x[0])
    return {
        "best_combos": [
            {"combo": k, "horizon": horizon, "mean_reaction": s, **stats}
            for s, k, stats in scored[::-1][:5]
        ],
        "worst_combos": [
            {"combo": k, "horizon": horizon, "mean_reaction": s, **stats}
            for s, k, stats in scored[:5]
        ],
    }


# ----------------------------------------------------------------------
# Public top-level builder + writer
# ----------------------------------------------------------------------

def build_report(
    records: Sequence[CandleBehaviorRecord],
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    min_touches_for_ranking: int = 30,
) -> dict[str, Any]:
    overall = _aggregate_records(records, horizons=horizons)
    by_pattern = aggregate_by_pattern(records, horizons=horizons)
    by_zone = aggregate_by_zone_type(records, horizons=horizons)
    combos = aggregate_by_pattern_zone_combo(records, horizons=horizons)
    by_session = aggregate_by_session(records, horizons=horizons)
    ranking_horizon = horizons[len(horizons) // 2] if horizons else 5
    ranking = rank_combos(combos, horizon=ranking_horizon, min_touches=min_touches_for_ranking)
    return {
        "config": {
            "horizons": list(horizons),
            "ranking_horizon": ranking_horizon,
            "min_touches_for_ranking": min_touches_for_ranking,
            "news_proximity": NEWS_PROXIMITY_TODO_LABEL,
        },
        "overall": overall,
        "by_pattern": by_pattern,
        "by_zone_type": by_zone,
        "by_pattern_zone_combo": combos,
        "by_session": by_session,
        "ranking": ranking,
    }


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def render_markdown(report: dict[str, Any]) -> str:
    horizons = report.get("config", {}).get("horizons") or list(DEFAULT_HORIZONS)
    lines: list[str] = []
    overall = report.get("overall") or {}
    lines.append("# Adelin candle-behavior + zone-reaction profile\n")
    lines.append("## Overall\n")
    lines.append(f"- candle_count: {overall.get('candle_count')}")
    lines.append(f"- candles_with_touch: {overall.get('candles_with_touch')}")
    lines.append(f"- touch_count: {overall.get('touch_count')}")
    lines.append(f"- mean_mfe: {_fmt(overall.get('mean_mfe'))}")
    lines.append(f"- mean_mae: {_fmt(overall.get('mean_mae'))}")
    lines.append(f"- rate_did_reclaim: {_fmt(overall.get('rate_did_reclaim'))}")
    lines.append(f"- rate_did_break_and_continue: {_fmt(overall.get('rate_did_break_and_continue'))}")
    lines.append(f"- rate_did_reject: {_fmt(overall.get('rate_did_reject'))}\n")

    def _table(title: str, buckets: dict[str, dict]) -> str:
        if not buckets:
            return f"### {title}\n\n_no data_\n\n"
        headers = ["bucket", "candles", "touches", *[f"react@{h}" for h in horizons], "MFE", "MAE", "reject%", "break%", "sig"]
        rows = []
        for k in sorted(buckets.keys()):
            s = buckets[k]
            mean_reaction = s.get("mean_reaction_at") or {}
            cells = [
                k,
                s.get("candle_count", s.get("touch_count", 0)),
                s.get("touch_count", 0),
            ]
            cells.extend(_fmt(mean_reaction.get(h)) for h in horizons)
            cells.extend([
                _fmt(s.get("mean_mfe")),
                _fmt(s.get("mean_mae")),
                _fmt(s.get("rate_did_reject")),
                _fmt(s.get("rate_did_break_and_continue")),
                "YES" if s.get("statistically_significant") else "no",
            ])
            rows.append("| " + " | ".join(str(c) for c in cells) + " |")
        body = (
            f"### {title}\n\n"
            + "| " + " | ".join(headers) + " |\n"
            + "|" + "|".join(["---"] * len(headers)) + "|\n"
            + "\n".join(rows)
        )
        return body + "\n\n"

    lines.append(_table("By candle pattern", report.get("by_pattern") or {}))
    lines.append(_table("By zone type", report.get("by_zone_type") or {}))
    lines.append(_table("By session", report.get("by_session") or {}))
    lines.append(_table("By pattern x zone combo", report.get("by_pattern_zone_combo") or {}))

    ranking = report.get("ranking") or {}
    lines.append(f"## Best / worst combos (mean_reaction_at horizon={report['config'].get('ranking_horizon')}, min_touches={report['config'].get('min_touches_for_ranking')})\n")
    lines.append("### Best 5 combos\n")
    for combo in ranking.get("best_combos") or []:
        lines.append(f"- `{combo['combo']}` mean_reaction={_fmt(combo.get('mean_reaction'))} (n={combo.get('touch_count')})")
    if not ranking.get("best_combos"):
        lines.append("- _no combos with enough data_")
    lines.append("\n### Worst 5 combos\n")
    for combo in ranking.get("worst_combos") or []:
        lines.append(f"- `{combo['combo']}` mean_reaction={_fmt(combo.get('mean_reaction'))} (n={combo.get('touch_count')})")
    if not ranking.get("worst_combos"):
        lines.append("- _no combos with enough data_")
    lines.append("")

    lines.append("## TODO\n")
    lines.append("- News proximity stats not yet available (news_events is empty in the current backtest pipeline).")
    return "\n".join(lines)


def write_report_files(
    *,
    output_dir: str,
    report: dict[str, Any],
    file_stem: str = "profile_candle_behavior",
) -> dict[str, str]:
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    json_path = out_root / f"{file_stem}.json"
    md_path = out_root / f"{file_stem}.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"report_json": str(json_path), "report_md": str(md_path)}


__all__ = [
    "NEWS_PROXIMITY_TODO_LABEL",
    "CandleBehaviorConfig",
    "CandleBehaviorRecord",
    "aggregate_by_pattern",
    "aggregate_by_pattern_zone_combo",
    "aggregate_by_session",
    "aggregate_by_zone_type",
    "build_report",
    "iterate_candle_behavior_records",
    "rank_combos",
    "render_markdown",
    "write_report_files",
]
