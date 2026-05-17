"""
Adelin profile report: auto-recommendations + JSON / Markdown writer.

Builds non-binding heuristic recommendations on top of profile_adelin()
output and renders both a JSON dump and a human-readable Markdown
report ready for review.

The recommendations are intentionally simple and conservative:

  best_min_score          smallest score-bucket with avg_r >= 0 and PF >= 1.0
                          (must be statistically significant)
  best_max_sl_usd         largest SL bucket where avg_r remains >= 0
                          (drop wider buckets that turn negative)
  useful_confluences      flags whose `with`-bucket clearly improves
                          avg_r over `without` (default delta >= 0.1)
  useless_confluences     flags whose `with`-bucket does NOT improve
                          avg_r (no observed edge, candidate to relax
                          if currently mandatory)
  toxic_buckets           any bucket with avg_r <= -0.3 and statistically
                          significant — strong candidates to exclude
                          regardless of policy

These are *signals* for human review, not auto-applied changes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFLUENCE_FLAGS: tuple[str, ...] = (
    "has_sweep",
    "has_fvg",
    "has_volume_confluence",
    "has_number_theory",
)


@dataclass(frozen=True)
class RecommendationConfig:
    min_avg_r: float = 0.0
    min_profit_factor: float = 1.0
    useful_avg_r_delta: float = 0.1
    toxic_avg_r_threshold: float = -0.3
    require_significance: bool = True


# ----------------------------------------------------------------------
# Recommendations
# ----------------------------------------------------------------------

def _score_bucket_lower(label: str) -> int:
    if label.startswith("lt_"):
        return 0
    if label.startswith("ge_"):
        return int(label.split("_", 1)[1])
    low, _ = label.split("_to_", 1)
    return int(low)


def _sl_bucket_upper(label: str) -> float:
    if label.startswith("le_"):
        return float(label.split("_", 1)[1])
    if label.startswith("gt_"):
        return float("inf")
    _, high = label.split("_to_", 1)
    return float(high)


def build_recommendations(profile: dict, cfg: RecommendationConfig | None = None) -> dict:
    cfg = cfg or RecommendationConfig()

    by_score = profile.get("by_score_bucket", {})
    by_sl = profile.get("by_sl_bucket", {})
    confluence = profile.get("by_confluence", {})
    micro = profile.get("micro_confluence_split", {})

    # best_min_score: smallest bucket lower-bound where avg_r >= 0, PF >= 1, significant
    qualifying_scores: list[tuple[int, str, dict]] = []
    for label, stats in by_score.items():
        if cfg.require_significance and not stats.get("statistically_significant", False):
            continue
        if stats.get("avg_r", 0.0) >= cfg.min_avg_r and stats.get("profit_factor", 0.0) >= cfg.min_profit_factor:
            qualifying_scores.append((_score_bucket_lower(label), label, stats))
    qualifying_scores.sort()
    best_min_score = qualifying_scores[0][0] if qualifying_scores else None
    best_min_score_label = qualifying_scores[0][1] if qualifying_scores else None

    # best_max_sl_usd: largest bucket upper-bound where avg_r >= 0 (and significant)
    qualifying_sl: list[tuple[float, str, dict]] = []
    for label, stats in by_sl.items():
        if cfg.require_significance and not stats.get("statistically_significant", False):
            continue
        if stats.get("avg_r", 0.0) >= cfg.min_avg_r:
            qualifying_sl.append((_sl_bucket_upper(label), label, stats))
    qualifying_sl.sort()
    best_max_sl_usd = qualifying_sl[-1][0] if qualifying_sl else None
    best_max_sl_label = qualifying_sl[-1][1] if qualifying_sl else None

    # useful vs useless confluences
    useful: list[dict] = []
    useless: list[dict] = []
    for flag in CONFLUENCE_FLAGS:
        entry = confluence.get(flag) or {}
        with_stats = entry.get("with", {})
        without_stats = entry.get("without", {})
        delta = (with_stats.get("avg_r", 0.0) or 0.0) - (without_stats.get("avg_r", 0.0) or 0.0)
        record = {
            "flag": flag,
            "with_avg_r": with_stats.get("avg_r"),
            "without_avg_r": without_stats.get("avg_r"),
            "delta_avg_r": round(delta, 4),
            "with_valid_trades": with_stats.get("valid_trades"),
            "without_valid_trades": without_stats.get("valid_trades"),
        }
        if delta >= cfg.useful_avg_r_delta:
            useful.append(record)
        elif delta <= 0:
            useless.append(record)

    # Full micro_confluence delta
    micro_with = micro.get("with_full_micro_confluence", {})
    micro_without = micro.get("without_full_micro_confluence", {})
    micro_delta = (micro_with.get("avg_r", 0.0) or 0.0) - (micro_without.get("avg_r", 0.0) or 0.0)
    micro_record = {
        "with_avg_r": micro_with.get("avg_r"),
        "without_avg_r": micro_without.get("avg_r"),
        "delta_avg_r": round(micro_delta, 4),
        "with_valid_trades": micro_with.get("valid_trades"),
        "without_valid_trades": micro_without.get("valid_trades"),
        "verdict": (
            "useful" if micro_delta >= cfg.useful_avg_r_delta
            else "useless" if micro_delta <= 0
            else "marginal"
        ),
    }

    # Toxic buckets: any cell in the profile with avg_r <= -0.3 + significant
    toxic: list[dict] = []
    for label, stats in by_score.items():
        if stats.get("avg_r", 0.0) <= cfg.toxic_avg_r_threshold and stats.get("statistically_significant", False):
            toxic.append({"dimension": "score_bucket", "label": label, "avg_r": stats["avg_r"], "valid_trades": stats["valid_trades"]})
    for label, stats in by_sl.items():
        if stats.get("avg_r", 0.0) <= cfg.toxic_avg_r_threshold and stats.get("statistically_significant", False):
            toxic.append({"dimension": "sl_bucket", "label": label, "avg_r": stats["avg_r"], "valid_trades": stats["valid_trades"]})
    for label, stats in (profile.get("by_setup_mode") or {}).items():
        if stats.get("avg_r", 0.0) <= cfg.toxic_avg_r_threshold and stats.get("statistically_significant", False):
            toxic.append({"dimension": "setup_mode", "label": label, "avg_r": stats["avg_r"], "valid_trades": stats["valid_trades"]})
    for label, stats in (profile.get("by_session") or {}).items():
        if stats.get("avg_r", 0.0) <= cfg.toxic_avg_r_threshold and stats.get("statistically_significant", False):
            toxic.append({"dimension": "session", "label": label, "avg_r": stats["avg_r"], "valid_trades": stats["valid_trades"]})

    return {
        "config": {
            "min_avg_r": cfg.min_avg_r,
            "min_profit_factor": cfg.min_profit_factor,
            "useful_avg_r_delta": cfg.useful_avg_r_delta,
            "toxic_avg_r_threshold": cfg.toxic_avg_r_threshold,
            "require_significance": cfg.require_significance,
        },
        "best_min_score": best_min_score,
        "best_min_score_bucket": best_min_score_label,
        "best_max_sl_usd": best_max_sl_usd,
        "best_max_sl_bucket": best_max_sl_label,
        "useful_confluences": useful,
        "useless_confluences": useless,
        "full_micro_confluence": micro_record,
        "toxic_buckets": toxic,
    }


# ----------------------------------------------------------------------
# Markdown rendering
# ----------------------------------------------------------------------

def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def _render_bucket_table(title: str, buckets: dict[str, dict], key_order: list[str] | None = None) -> str:
    headers = ["bucket", "n", "acc", "trades", "wins", "loss", "BE", "WR", "avg_R", "PF", "max_DD", "sig"]
    rows: list[str] = []
    keys = key_order if key_order is not None else sorted(buckets.keys())
    for k in keys:
        s = buckets[k]
        rows.append(
            f"| {k} | {s['total_signals']} | {s['accepted']} | {s['valid_trades']} | "
            f"{s['wins']} | {s['losses']} | {s['be']} | {_fmt(s['win_rate'])} | "
            f"{_fmt(s['avg_r'])} | {_fmt(s['profit_factor'])} | {_fmt(s['max_drawdown_r'])} | "
            f"{'YES' if s['statistically_significant'] else 'no'} |"
        )
    table = (
        f"### {title}\n\n"
        + "| " + " | ".join(headers) + " |\n"
        + "|" + "|".join(["---"] * len(headers)) + "|\n"
        + "\n".join(rows)
    )
    return table + "\n\n"


def render_markdown(profile: dict, recommendations: dict) -> str:
    overall = profile.get("overall") or {}
    lines: list[str] = []
    lines.append("# Adelin edge profile\n")
    lines.append(f"Strategy: `{profile.get('strategy')}`\n")
    lines.append("## Overall\n")
    lines.append(f"- total_signals: {overall.get('total_signals')}")
    lines.append(f"- valid_trades: {overall.get('valid_trades')}")
    lines.append(f"- wins / losses / BE: {overall.get('wins')} / {overall.get('losses')} / {overall.get('be')}")
    lines.append(f"- win_rate: {_fmt(overall.get('win_rate'))}")
    lines.append(f"- avg_R: {_fmt(overall.get('avg_r'))}")
    lines.append(f"- profit_factor: {_fmt(overall.get('profit_factor'))}")
    lines.append(f"- max_drawdown_R: {_fmt(overall.get('max_drawdown_r'))}\n")

    lines.append("## Recommendations\n")
    lines.append(f"- **best_min_score**: {_fmt(recommendations.get('best_min_score'))} "
                 f"(bucket `{recommendations.get('best_min_score_bucket')}`)")
    lines.append(f"- **best_max_sl_usd**: {_fmt(recommendations.get('best_max_sl_usd'))} "
                 f"(bucket `{recommendations.get('best_max_sl_bucket')}`)")
    useful = recommendations.get("useful_confluences") or []
    useless = recommendations.get("useless_confluences") or []
    if useful:
        lines.append("- **useful confluences** (with > without by delta_avg_r >= 0.1):")
        for r in useful:
            lines.append(f"    - `{r['flag']}` delta_avg_r={_fmt(r['delta_avg_r'])} (with n={r['with_valid_trades']}, without n={r['without_valid_trades']})")
    else:
        lines.append("- **useful confluences**: none observed")
    if useless:
        lines.append("- **useless confluences** (no edge):")
        for r in useless:
            lines.append(f"    - `{r['flag']}` delta_avg_r={_fmt(r['delta_avg_r'])} (with n={r['with_valid_trades']}, without n={r['without_valid_trades']})")
    else:
        lines.append("- **useless confluences**: none")
    mc = recommendations.get("full_micro_confluence") or {}
    lines.append(f"- **full micro_confluence**: verdict=`{mc.get('verdict')}` "
                 f"delta_avg_r={_fmt(mc.get('delta_avg_r'))} "
                 f"(with n={mc.get('with_valid_trades')}, without n={mc.get('without_valid_trades')})")
    toxic = recommendations.get("toxic_buckets") or []
    if toxic:
        lines.append("- **toxic buckets** (avg_R <= -0.3, statistically significant):")
        for t in toxic:
            lines.append(f"    - {t['dimension']}=`{t['label']}` avg_R={_fmt(t['avg_r'])} (n={t['valid_trades']})")
    else:
        lines.append("- **toxic buckets**: none")
    lines.append("")

    lines.append(_render_bucket_table("By score bucket", profile.get("by_score_bucket") or {}))
    lines.append(_render_bucket_table("By SL bucket", profile.get("by_sl_bucket") or {}))
    lines.append(_render_bucket_table("By setup_mode", profile.get("by_setup_mode") or {}))
    lines.append(_render_bucket_table("By session", profile.get("by_session") or {}))
    lines.append(_render_bucket_table("By direction", profile.get("by_direction") or {}))

    # Confluence with/without table
    lines.append("### Confluence split (with vs without)\n")
    headers = ["flag", "side", "trades", "WR", "avg_R", "PF", "sig"]
    rows: list[str] = []
    for flag, entry in (profile.get("by_confluence") or {}).items():
        for side in ("with", "without"):
            s = entry.get(side, {})
            rows.append(
                f"| {flag} | {side} | {s.get('valid_trades')} | {_fmt(s.get('win_rate'))} | "
                f"{_fmt(s.get('avg_r'))} | {_fmt(s.get('profit_factor'))} | "
                f"{'YES' if s.get('statistically_significant') else 'no'} |"
            )
    mc_split = profile.get("micro_confluence_split") or {}
    for side_key, label in (("with_full_micro_confluence", "with"), ("without_full_micro_confluence", "without")):
        s = mc_split.get(side_key, {})
        rows.append(
            f"| full_micro_confluence | {label} | {s.get('valid_trades')} | {_fmt(s.get('win_rate'))} | "
            f"{_fmt(s.get('avg_r'))} | {_fmt(s.get('profit_factor'))} | "
            f"{'YES' if s.get('statistically_significant') else 'no'} |"
        )
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    lines.extend(rows)
    lines.append("")

    # Score x SL matrix table
    matrix = profile.get("score_x_sl_matrix") or {}
    if matrix:
        lines.append("### Score x SL matrix (avg_R / n_trades)\n")
        sl_labels = sorted({sl for buckets in matrix.values() for sl in buckets.keys()})
        headers = ["score \\ SL", *sl_labels]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for score_label in sorted(matrix.keys()):
            row_cells = [score_label]
            for sl in sl_labels:
                cell = matrix[score_label].get(sl)
                if cell:
                    row_cells.append(f"{_fmt(cell['avg_r'])} / n={cell['valid_trades']}")
                else:
                    row_cells.append("—")
            lines.append("| " + " | ".join(row_cells) + " |")
        lines.append("")

    return "\n".join(lines)


# ----------------------------------------------------------------------
# Writer
# ----------------------------------------------------------------------

def write_profile_files(
    *,
    output_dir: str,
    profile: dict,
    recommendations: dict,
    file_stem: str = "profile_adelin",
) -> dict[str, str]:
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    json_path = out_root / f"{file_stem}.json"
    md_path = out_root / f"{file_stem}.md"
    payload = {
        "profile": profile,
        "recommendations": recommendations,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(profile, recommendations), encoding="utf-8")
    return {
        "profile_json": str(json_path),
        "profile_md": str(md_path),
    }


__all__ = [
    "CONFLUENCE_FLAGS",
    "RecommendationConfig",
    "build_recommendations",
    "render_markdown",
    "write_profile_files",
]
