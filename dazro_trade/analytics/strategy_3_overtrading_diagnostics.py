from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable


REQUIRED_DIAGNOSTIC_FIELDS = {
    "timestamp",
    "symbol",
    "direction",
    "entry",
    "stop",
    "tp1",
    "outcome",
    "r_multiple",
    "setup_mode",
    "band_touched",
    "vwap",
    "vwap_distance",
    "session",
    "reason_codes",
    "confluences",
    "liquidity_context",
    "sweep_timeframe",
    "sweep_type",
    "sweep_price",
    "risk_distance",
    "rr",
    "strategy_name",
}

OUTCOME_COLUMNS = ("TP1", "TP2", "TP3", "TP4", "SL", "BE", "TIMEOUT_CLOSE", "END_OF_DATA_CLOSE", "STILL_OPEN")


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return round(fmean(values), 4) if values else None


def _median(values: Iterable[float]) -> float | None:
    values = list(values)
    return round(median(values), 4) if values else None


def _pct(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def category_significance(n: int) -> str:
    if n < 10:
        return "insufficient"
    if n < 30:
        return "weak"
    if n < 100:
        return "moderate"
    return "significant"


def category_interpretation(n: int) -> str:
    if n < 10:
        return "insufficient_sample"
    if n < 30:
        return "directional_only"
    return "analyzable_hypothesis"


def _r_values(rows: list[dict[str, str]]) -> list[float]:
    return [value for row in rows if (value := _to_float(row.get("r_multiple"))) is not None]


def _profit_factor(values: list[float]) -> float | str | None:
    wins = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    if not values:
        return None
    if losses == 0:
        return "inf" if wins > 0 else 0.0
    return round(wins / losses, 4)


def metric_block(rows: list[dict[str, str]]) -> dict[str, Any]:
    values = _r_values(rows)
    wins = sum(1 for value in values if value > 0)
    out = {
        "trades": len(rows),
        "WR": round(wins / len(values), 4) if values else 0.0,
        "PF": _profit_factor(values),
        "AvgR": _mean(values),
        "MedianR": _median(values),
        "total_R": round(sum(values), 4) if values else 0.0,
        "category_significance": category_significance(len(rows)),
        "interpretation": category_interpretation(len(rows)),
    }
    for outcome in OUTCOME_COLUMNS:
        out[outcome] = sum(1 for row in rows if (row.get("outcome") or "UNKNOWN") == outcome)
    return out


def group_metrics(rows: list[dict[str, str]], field: str, columns: set[str]) -> list[dict[str, Any]] | str:
    if field not in columns:
        return "field_not_available_skip"
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row.get(field) or "UNKNOWN"].append(row)
    return [
        {"category": key, **metric_block(group)}
        for key, group in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def _split_reason_codes(value: Any) -> list[str]:
    if not value:
        return []
    text = str(value).strip()
    if text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [str(item) for item in data if item]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in text.split(";") if part.strip()]


def _parse_jsonish(value: Any) -> Any:
    if not value:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return None


def reason_code_frequency(rows: list[dict[str, str]], columns: set[str]) -> list[dict[str, Any]] | str:
    if "reason_codes" not in columns:
        return "field_not_available_skip"
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        for code in _split_reason_codes(row.get("reason_codes")):
            grouped[code].append(row)
    if not grouped:
        return []
    total = len(rows)
    return [
        {"reason_code": key, "count": len(group), "count_pct": _pct(len(group), total), **metric_block(group)}
        for key, group in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def confluence_breakdown(rows: list[dict[str, str]], columns: set[str]) -> list[dict[str, Any]] | str:
    if "confluences" not in columns:
        return "CONFLUENCE_BREAKDOWN_UNAVAILABLE"
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        data = _parse_jsonish(row.get("confluences"))
        if not isinstance(data, dict):
            grouped["unknown"].append(row)
            continue
        added = False
        for key, value in data.items():
            label = f"{key}:present"
            if isinstance(value, bool):
                label = f"{key}:{str(value).lower()}"
            elif isinstance(value, dict) and "confluence" in value:
                label = f"{key}:confluence_{str(bool(value.get('confluence'))).lower()}"
            elif value in (None, "", {}, []):
                label = f"{key}:absent"
            grouped[label].append(row)
            added = True
        if not added:
            grouped["no_confluence_context"].append(row)
    return [
        {"confluence": key, "count": len(group), "count_pct": _pct(len(group), len(rows)), **metric_block(group)}
        for key, group in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def trade_density(rows: list[dict[str, str]]) -> dict[str, Any]:
    times = sorted(ts for row in rows if (ts := _to_datetime(row.get("timestamp"))) is not None)
    gaps = [round((b - a).total_seconds() / 60, 4) for a, b in zip(times, times[1:])]
    by_day = Counter(ts.date().isoformat() for ts in times)
    by_hour = Counter(ts.strftime("%Y-%m-%d %H:00") for ts in times)
    by_session = Counter(row.get("session") or "UNKNOWN" for row in rows)
    observed_days = ((times[-1] - times[0]).total_seconds() / 86400.0) + 1 if len(times) >= 2 else 1
    observed_days = max(observed_days, 1)
    median_gap = _median(gaps)
    max_hour = max(by_hour.values(), default=0)
    trades_per_day = round(len(rows) / observed_days, 4)
    overtrading = trades_per_day > 10 or max_hour > 3 or (median_gap is not None and median_gap < 30)
    return {
        "total_trades": len(rows),
        "first_trade": times[0].isoformat() if times else None,
        "last_trade": times[-1].isoformat() if times else None,
        "observed_days": round(observed_days, 4),
        "trades_per_day": trades_per_day,
        "trades_per_session": dict(by_session),
        "trades_per_hour": dict(sorted(by_hour.items())),
        "max_trades_in_one_day": max(by_day.values(), default=0),
        "max_trades_in_one_hour": max_hour,
        "average_time_between_trades_minutes": _mean(gaps),
        "median_time_between_trades_minutes": median_gap,
        "OVERTRADING_DENSITY_CONFIRMED": overtrading,
    }


def cluster_diagnostics(rows: list[dict[str, str]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: _to_datetime(row.get("timestamp")) or datetime.min)
    gaps: list[float] = []
    same_context_15 = 0
    same_context_30 = 0
    for prev, cur in zip(ordered, ordered[1:]):
        a = _to_datetime(prev.get("timestamp"))
        b = _to_datetime(cur.get("timestamp"))
        if a is None or b is None:
            continue
        gap = (b - a).total_seconds() / 60
        gaps.append(gap)
        same_context = (
            prev.get("direction") == cur.get("direction")
            or prev.get("band_touched") == cur.get("band_touched")
            or prev.get("setup_mode") == cur.get("setup_mode")
        )
        if gap < 15 and same_context:
            same_context_15 += 1
        if gap < 30 and same_context:
            same_context_30 += 1
    by_hour = Counter(
        ts.strftime("%Y-%m-%d %H:00")
        for row in rows
        if (ts := _to_datetime(row.get("timestamp"))) is not None
    )
    by_session_context = Counter(
        (
            (_to_datetime(row.get("timestamp")).date().isoformat() if _to_datetime(row.get("timestamp")) else "UNKNOWN"),
            row.get("session") or "UNKNOWN",
            row.get("direction") or "UNKNOWN",
            row.get("band_touched") or "UNKNOWN",
        )
        for row in rows
    )
    gap_lt_15 = sum(1 for gap in gaps if gap < 15)
    potential_duplicate = max(by_hour.values(), default=0) > 3 or max(by_session_context.values(), default=0) > 5 or gap_lt_15 > len(rows) * 0.20
    missing_cooldown = same_context_15 > len(rows) * 0.15 or same_context_30 > len(rows) * 0.30
    return {
        "average_trade_gap_minutes": _mean(gaps),
        "median_trade_gap_minutes": _median(gaps),
        "trade_gap_min_minutes": round(min(gaps), 4) if gaps else None,
        "trade_gap_max_minutes": round(max(gaps), 4) if gaps else None,
        "gap_lt_5m_count": sum(1 for gap in gaps if gap < 5),
        "gap_lt_15m_count": gap_lt_15,
        "gap_lt_30m_count": sum(1 for gap in gaps if gap < 30),
        "gap_lt_60m_count": sum(1 for gap in gaps if gap < 60),
        "same_context_gap_lt_15m_count": same_context_15,
        "same_context_gap_lt_30m_count": same_context_30,
        "max_trades_in_same_hour": max(by_hour.values(), default=0),
        "max_trades_same_session_direction_band": max(by_session_context.values(), default=0),
        "POTENTIAL_DUPLICATE_CLUSTER": potential_duplicate,
        "MISSING_COOLDOWN": missing_cooldown,
    }


def _dedup(rows: list[dict[str, str]], minutes: int) -> list[dict[str, str]]:
    kept: list[dict[str, str]] = []
    last_by_direction: dict[str, datetime] = {}
    for row in sorted(rows, key=lambda item: _to_datetime(item.get("timestamp")) or datetime.min):
        ts = _to_datetime(row.get("timestamp"))
        direction = row.get("direction") or "UNKNOWN"
        if ts is None:
            kept.append(row)
            continue
        previous = last_by_direction.get(direction)
        if previous is not None and (ts - previous).total_seconds() / 60 < minutes:
            continue
        kept.append(row)
        last_by_direction[direction] = ts
    return kept


def cluster_impact(rows: list[dict[str, str]]) -> dict[str, Any]:
    all_block = metric_block(rows)
    out: dict[str, Any] = {"all_trades": all_block}
    all_pf = all_block["PF"] if isinstance(all_block["PF"], float) else None
    for minutes in (15, 60):
        kept = _dedup(rows, minutes)
        block = metric_block(kept)
        kept_pf = block["PF"] if isinstance(block["PF"], float) else None
        delta = round(all_pf - kept_pf, 4) if all_pf is not None and kept_pf is not None else None
        out[f"dedupped_{minutes}m"] = {
            "kept_trades": len(kept),
            "removed_trades": len(rows) - len(kept),
            **block,
            "delta_PF_vs_all": delta,
        }
    max_delta = max((value.get("delta_PF_vs_all") or 0.0 for key, value in out.items() if key.startswith("dedupped_")), default=0.0)
    out["DUPLICATE_CONTEXT_ENTRIES_DETECTED"] = max_delta >= 0.3
    return out


def distance_diagnostics(rows: list[dict[str, str]], columns: set[str]) -> dict[str, Any] | str:
    if "vwap_distance" not in columns and "vwap_distance_pips" not in columns:
        return "VWAP_DISTANCE_DIAGNOSTICS_UNAVAILABLE"
    field = "vwap_distance_pips" if "vwap_distance_pips" in columns else "vwap_distance"
    values = [value for row in rows if (value := _to_float(row.get(field))) is not None]
    buckets: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        band = row.get("band_touched") or ""
        distance = _to_float(row.get(field))
        if distance is None:
            bucket = "unknown"
        elif band == "vwap":
            bucket = "near_vwap"
        elif band.startswith("sigma_1"):
            bucket = "sigma_1_area"
        elif band.startswith("sigma_2"):
            bucket = "sigma_2_area"
        else:
            bucket = "far_from_vwap"
        buckets[bucket].append(row)
    return {
        "mean_vwap_distance": _mean(values),
        "median_vwap_distance": _median(values),
        "min_vwap_distance": round(min(values), 4) if values else None,
        "max_vwap_distance": round(max(values), 4) if values else None,
        "buckets": [{"category": key, **metric_block(group)} for key, group in sorted(buckets.items())],
    }


def liquidity_diagnostics(rows: list[dict[str, str]], columns: set[str]) -> list[dict[str, Any]] | str:
    if "liquidity_context" not in columns:
        return "LIQUIDITY_CONTEXT_DIAGNOSTICS_UNAVAILABLE"
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        context = _parse_jsonish(row.get("liquidity_context"))
        if not isinstance(context, dict):
            groups["no_liquidity_context"].append(row)
            continue
        sweep = context.get("sweep") if isinstance(context.get("sweep"), dict) else {}
        side = str(sweep.get("side") or context.get("side") or context.get("type") or "")
        scope = str(context.get("scope") or "")
        added = False
        if "buy" in side or "high" in side:
            groups["swept_recent_high"].append(row)
            added = True
        if "sell" in side or "low" in side:
            groups["swept_recent_low"].append(row)
            added = True
        if scope:
            groups[f"{scope}_liquidity"].append(row)
            added = True
        if not added:
            groups["unknown"].append(row)
    return [
        {"category": key, **metric_block(group)}
        for key, group in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def build_overtrading_diagnostic(
    rows: list[dict[str, str]],
    columns: list[str],
    summary: dict[str, Any] | None = None,
    *,
    source_path: str,
    summary_path: str,
    rerun_command: str | None = None,
    original_trade_count: int = 94,
) -> dict[str, Any]:
    columns_set = set(columns)
    missing = sorted(REQUIRED_DIAGNOSTIC_FIELDS - columns_set)
    no_trade_rows = [row for row in rows if (row.get("setup_mode") or "").lower() == "no_trade"]
    setup = group_metrics(rows, "setup_mode", columns_set)
    band = group_metrics(rows, "band_touched", columns_set)
    session = group_metrics(rows, "session", columns_set)
    direction = group_metrics(rows, "direction", columns_set)
    density = trade_density(rows)
    clusters = cluster_diagnostics(rows)
    impact = cluster_impact(rows)
    reason_codes = reason_code_frequency(rows, columns_set)
    confluences = confluence_breakdown(rows, columns_set)
    distance = distance_diagnostics(rows, columns_set)
    liquidity = liquidity_diagnostics(rows, columns_set)

    verdicts: list[str] = ["OVERTRADING_DIAGNOSTICS_COMPLETE"]
    if no_trade_rows:
        verdicts.append("NO_TRADE_LEAKAGE_BUG_FOUND")
    vwap_and_sigma1_count = sum(
        1 for row in rows if (row.get("band_touched") or "") in {"vwap", "sigma_1_upper", "sigma_1_lower"}
    )
    vwap_touch_too_permissive = bool(rows) and vwap_and_sigma1_count / len(rows) > 0.5 and density["OVERTRADING_DENSITY_CONFIRMED"]
    sigma1_rows = [row for row in rows if (row.get("band_touched") or "").startswith("sigma_1")]
    sigma1_block = metric_block(sigma1_rows)
    sigma1_too_noisy = len(sigma1_rows) >= 10 and (
        (isinstance(sigma1_block["PF"], float) and sigma1_block["PF"] <= 1.05)
        or (sigma1_block["AvgR"] is not None and sigma1_block["AvgR"] <= 0.05)
    )
    setup_counts = Counter(row.get("setup_mode") or "UNKNOWN" for row in rows)
    session_counts = Counter(row.get("session") or "UNKNOWN" for row in rows)
    session_overtrading = bool(rows) and (max(session_counts.values(), default=0) / len(rows) > 0.5)
    if clusters["MISSING_COOLDOWN"]:
        verdicts.append("MISSING_COOLDOWN")
    if impact["DUPLICATE_CONTEXT_ENTRIES_DETECTED"]:
        verdicts.append("DUPLICATE_CONTEXT_ENTRIES_DETECTED")
    if vwap_touch_too_permissive:
        verdicts.append("VWAP_TOUCH_TOO_PERMISSIVE")
    if sigma1_too_noisy:
        verdicts.append("SIGMA_1_TOO_NOISY")
    if session_overtrading:
        verdicts.append("SESSION_OVERTRADING")
    for mode, label in (("reversal", "REVERSAL_TOO_FREQUENT"), ("trend_following", "TREND_FOLLOWING_TOO_FREQUENT")):
        if rows and setup_counts.get(mode, 0) / len(rows) > 0.5:
            verdicts.append(label)

    positive_categories: list[tuple[str, float]] = []
    for name, groups in (("setup_mode", setup), ("band_touched", band), ("session", session)):
        if isinstance(groups, list):
            for group in groups:
                total_r = float(group.get("total_R") or 0.0)
                if total_r > 0:
                    positive_categories.append((f"{name}:{group['category']}", total_r))
    total_positive_r = sum(value for _, value in positive_categories)
    concentrated = bool(positive_categories) and max(value for _, value in positive_categories) / total_positive_r >= 0.70
    if concentrated:
        verdicts.append("POSITIVE_EDGE_CONCENTRATED")
    if density["OVERTRADING_DENSITY_CONFIRMED"] and not concentrated:
        verdicts.append("EDGE_NOT_DIAGNOSTICALLY_STABLE")
    if missing:
        verdicts.append("DIAGNOSTIC_DATA_INSUFFICIENT")

    primary = "NO_TRADE_LEAKAGE_BUG_FOUND" if no_trade_rows else None
    if primary is None:
        if impact["DUPLICATE_CONTEXT_ENTRIES_DETECTED"] or clusters["MISSING_COOLDOWN"]:
            primary = "MISSING_COOLDOWN"
        elif vwap_touch_too_permissive:
            primary = "VWAP_TOUCH_TOO_PERMISSIVE"
        elif sigma1_too_noisy:
            primary = "SIGMA_1_TOO_NOISY"
        elif session_overtrading:
            primary = "SESSION_OVERTRADING"
        elif missing:
            primary = "DIAGNOSTIC_DATA_INSUFFICIENT"
        else:
            primary = "EDGE_NOT_DIAGNOSTICALLY_STABLE"

    next_branch = {
        "NO_TRADE_LEAKAGE_BUG_FOUND": "fix/strategy-3-no-trade-leakage",
        "MISSING_COOLDOWN": "feat/strategy-3-add-cooldown",
        "VWAP_TOUCH_TOO_PERMISSIVE": "feat/strategy-3-tighten-band-conditions",
        "SIGMA_1_TOO_NOISY": "feat/strategy-3-sigma-2-only",
        "SESSION_OVERTRADING": "feat/strategy-3-restrict-sessions",
        "POSITIVE_EDGE_CONCENTRATED": "feat/strategy-3-isolate-winning-mode",
        "EDGE_NOT_DIAGNOSTICALLY_STABLE": "suspend_strategy_3_and_evaluate_alternatives",
        "DIAGNOSTIC_DATA_INSUFFICIENT": "feat/strategy-3-telemetry-export",
    }.get(primary, "feat/strategy-3-add-cooldown")

    return {
        "branch": "feat/strategy-3-overtrading-diagnostics",
        "base_commit": "7b14abf Add Strategy 3 VWAP 1R research scaffold",
        "source_data": {
            "executed_trades_csv": source_path,
            "summary_json": summary_path,
            "rows_read": len(rows),
            "columns_available": columns,
            "columns_missing": missing,
            "rerun_command": rerun_command,
            "original_trade_count": original_trade_count,
            "diagnostic_trade_count": len(rows),
            "diagnostic_rerun_trade_count_changed": len(rows) != original_trade_count,
        },
        "original_smoke_summary": {
            "total_trades": 94,
            "PF": 1.186,
            "WR": 0.5426,
            "AvgR": 0.0851,
            "total_R": 8.0,
            "MaxDD": 6.0,
            "note": "NON considerare il PF positivo come edge validato.",
        },
        "statistical_floor": {
            "n_lt_10": "insufficient",
            "n_10_to_29": "weak",
            "n_30_to_99": "moderate",
            "n_ge_100": "significant",
        },
        "no_trade_leakage": {
            "no_trade_executed_count": len(no_trade_rows),
            "no_trade_leakage_detected": bool(no_trade_rows),
        },
        "trade_density": density,
        "breakdowns": {
            "setup_mode": setup,
            "band_touched": band,
            "session": session,
            "direction": direction,
            "reason_codes": reason_codes,
            "confluences": confluences,
            "distance": distance,
            "liquidity_context": liquidity,
        },
        "cluster_diagnostics": clusters,
        "cluster_impact": impact,
        "a_priori_hypothesis": {
            "VWAP_TOUCH_TOO_PERMISSIVE_confirmed": vwap_touch_too_permissive,
            "MISSING_COOLDOWN_confirmed": bool(clusters["MISSING_COOLDOWN"]),
            "DUPLICATE_CONTEXT_ENTRIES_confirmed": bool(impact["DUPLICATE_CONTEXT_ENTRIES_DETECTED"]),
            "both_vwap_touch_and_missing_cooldown_confirmed": vwap_touch_too_permissive and bool(clusters["MISSING_COOLDOWN"]),
            "none_confirmed": not (vwap_touch_too_permissive or clusters["MISSING_COOLDOWN"] or impact["DUPLICATE_CONTEXT_ENTRIES_DETECTED"]),
        },
        "diagnosis": {
            "primary_verdict": primary,
            "secondary_verdicts": [item for item in dict.fromkeys(verdicts) if item != primary],
            "next_branch": next_branch,
            "limits": [
                "5-day smoke only",
                "subset sizes shrink quickly after breakdowns",
                "no OOS validation",
                "no edge validation",
            ],
        },
        "summary_metrics": summary or {},
        "not_done": [
            "no tuning",
            "no entry changes",
            "no filter changes",
            "no live",
            "no Telegram",
            "no full backtest",
            "no multi-symbol",
            "no multi-strategy",
        ],
    }


def _markdown_table(rows: list[dict[str, Any]], first_col: str = "category") -> str:
    if not rows:
        return "_No rows._"
    headers = [first_col, "trades", "WR", "PF", "AvgR", "MedianR", "total_R", "category_significance", "interpretation"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(header, "")) for header in headers) + " |")
    return "\n".join(lines)


def render_markdown(report: dict[str, Any]) -> str:
    density = report["trade_density"]
    leak = report["no_trade_leakage"]
    impact = report["cluster_impact"]
    hypo = report["a_priori_hypothesis"]
    diagnosis = report["diagnosis"]
    breakdowns = report["breakdowns"]
    lines = [
        "# Strategy 3 Overtrading Diagnostics",
        "",
        "Status: research-only diagnostic. NON considerare il PF positivo come edge validato.",
        "",
        "## Source",
        "",
        f"- branch: `{report['branch']}`",
        f"- base commit: `{report['base_commit']}`",
        f"- executed trades: `{report['source_data']['executed_trades_csv']}`",
        f"- summary: `{report['source_data']['summary_json']}`",
        f"- rows read: `{report['source_data']['rows_read']}`",
        f"- diagnostic rerun trade count changed: `{str(report['source_data']['diagnostic_rerun_trade_count_changed']).lower()}`",
        "",
        "## Original Smoke Reminder",
        "",
        "- trades: `94`",
        "- PF: `1.186`",
        "- WR: `54.26%`",
        "- AvgR: `0.0851`",
        "- total_R: `8.0`",
        "- MaxDD: `6.0R`",
        "- warning: `STRATEGY_3_OVERTRADING_INITIAL`",
        "",
        "## Statistical Floor",
        "",
        "- `n < 10`: insufficient",
        "- `10 <= n < 30`: weak",
        "- `30 <= n < 100`: moderate",
        "- `n >= 100`: significant",
        "",
        "## NO_TRADE Leakage Check",
        "",
        f"- no_trade_executed_count: `{leak['no_trade_executed_count']}`",
        f"- no_trade_leakage_detected: `{str(leak['no_trade_leakage_detected']).lower()}`",
        "",
        "## Trade Density",
        "",
        f"- total trades: `{density['total_trades']}`",
        f"- observed days: `{density['observed_days']}`",
        f"- trades/day: `{density['trades_per_day']}`",
        f"- max trades/day: `{density['max_trades_in_one_day']}`",
        f"- max trades/hour: `{density['max_trades_in_one_hour']}`",
        f"- average gap minutes: `{density['average_time_between_trades_minutes']}`",
        f"- median gap minutes: `{density['median_time_between_trades_minutes']}`",
        f"- OVERTRADING_DENSITY_CONFIRMED: `{str(density['OVERTRADING_DENSITY_CONFIRMED']).lower()}`",
        "",
        "## Breakdown By Setup Mode",
        "",
        _markdown_table(breakdowns["setup_mode"] if isinstance(breakdowns["setup_mode"], list) else []),
        "",
        "## Breakdown By Band Touched",
        "",
        _markdown_table(breakdowns["band_touched"] if isinstance(breakdowns["band_touched"], list) else []),
        "",
        "## Breakdown By Session",
        "",
        _markdown_table(breakdowns["session"] if isinstance(breakdowns["session"], list) else []),
        "",
        "## Breakdown By Direction",
        "",
        _markdown_table(breakdowns["direction"] if isinstance(breakdowns["direction"], list) else []),
        "",
        "## Reason Code Frequency",
        "",
        _markdown_table(breakdowns["reason_codes"] if isinstance(breakdowns["reason_codes"], list) else [], first_col="reason_code"),
        "",
        "## Confluence Breakdown",
        "",
        _markdown_table(breakdowns["confluences"] if isinstance(breakdowns["confluences"], list) else [], first_col="confluence")
        if isinstance(breakdowns["confluences"], list)
        else str(breakdowns["confluences"]),
        "",
        "## Cluster Diagnostics",
        "",
        f"- average trade gap minutes: `{report['cluster_diagnostics']['average_trade_gap_minutes']}`",
        f"- median trade gap minutes: `{report['cluster_diagnostics']['median_trade_gap_minutes']}`",
        f"- gap < 15m count: `{report['cluster_diagnostics']['gap_lt_15m_count']}`",
        f"- gap < 30m count: `{report['cluster_diagnostics']['gap_lt_30m_count']}`",
        f"- max trades same hour: `{report['cluster_diagnostics']['max_trades_in_same_hour']}`",
        f"- max trades same session/direction/band: `{report['cluster_diagnostics']['max_trades_same_session_direction_band']}`",
        f"- POTENTIAL_DUPLICATE_CLUSTER: `{str(report['cluster_diagnostics']['POTENTIAL_DUPLICATE_CLUSTER']).lower()}`",
        f"- MISSING_COOLDOWN: `{str(report['cluster_diagnostics']['MISSING_COOLDOWN']).lower()}`",
        "",
        "## Cluster Impact Metric",
        "",
        f"- all trades: PF `{impact['all_trades']['PF']}`, AvgR `{impact['all_trades']['AvgR']}`, total_R `{impact['all_trades']['total_R']}`",
        f"- dedupped 15m: kept `{impact['dedupped_15m']['kept_trades']}`, removed `{impact['dedupped_15m']['removed_trades']}`, PF `{impact['dedupped_15m']['PF']}`, AvgR `{impact['dedupped_15m']['AvgR']}`, total_R `{impact['dedupped_15m']['total_R']}`, delta_PF `{impact['dedupped_15m']['delta_PF_vs_all']}`",
        f"- dedupped 60m: kept `{impact['dedupped_60m']['kept_trades']}`, removed `{impact['dedupped_60m']['removed_trades']}`, PF `{impact['dedupped_60m']['PF']}`, AvgR `{impact['dedupped_60m']['AvgR']}`, total_R `{impact['dedupped_60m']['total_R']}`, delta_PF `{impact['dedupped_60m']['delta_PF_vs_all']}`",
        f"- DUPLICATE_CONTEXT_ENTRIES_DETECTED: `{str(impact['DUPLICATE_CONTEXT_ENTRIES_DETECTED']).lower()}`",
        "",
        "## Distance Diagnostics",
        "",
    ]
    distance = breakdowns["distance"]
    if isinstance(distance, dict):
        lines.extend(
            [
                f"- mean vwap_distance: `{distance['mean_vwap_distance']}`",
                f"- median vwap_distance: `{distance['median_vwap_distance']}`",
                f"- min/max vwap_distance: `{distance['min_vwap_distance']}` / `{distance['max_vwap_distance']}`",
                "",
                _markdown_table(distance["buckets"]),
            ]
        )
    else:
        lines.append(str(distance))
    lines.extend(["", "## Liquidity Context Diagnostics", ""])
    liquidity = breakdowns["liquidity_context"]
    lines.append(_markdown_table(liquidity if isinstance(liquidity, list) else []) if isinstance(liquidity, list) else str(liquidity))
    lines.extend(
        [
            "",
            "## A-priori Hypothesis",
            "",
            f"- VWAP_TOUCH_TOO_PERMISSIVE confermata: `{str(hypo['VWAP_TOUCH_TOO_PERMISSIVE_confirmed']).lower()}`",
            f"- MISSING_COOLDOWN confermata: `{str(hypo['MISSING_COOLDOWN_confirmed']).lower()}`",
            f"- DUPLICATE_CONTEXT_ENTRIES confermata: `{str(hypo['DUPLICATE_CONTEXT_ENTRIES_confirmed']).lower()}`",
            f"- entrambe VWAP touch/cooldown confermate: `{str(hypo['both_vwap_touch_and_missing_cooldown_confirmed']).lower()}`",
            f"- nessuna confermata: `{str(hypo['none_confirmed']).lower()}`",
            "",
            "## Final Diagnosis",
            "",
            f"- primary verdict: `{diagnosis['primary_verdict']}`",
            f"- secondary verdicts: `{', '.join(diagnosis['secondary_verdicts'])}`",
            f"- next branch: `{diagnosis['next_branch']}`",
            "",
            "## What Was Not Done",
            "",
            "- no tuning",
            "- no entry changes",
            "- no filter changes",
            "- no live",
            "- no Telegram",
            "- no full backtest",
            "- no multi-symbol",
            "- no multi-strategy",
            "",
            "## Limits",
            "",
            "- 5-day smoke only",
            "- subset sizes are often weak or moderate, not validation-grade",
            "- no OOS validation",
            "- no live/deploy conclusion",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any], output_dir: Path, docs_path: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "strategy_3_overtrading_diagnostics.json"
    md_path = output_dir / "strategy_3_overtrading_diagnostics.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown = render_markdown(report)
    md_path.write_text(markdown, encoding="utf-8")
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    docs_path.write_text(markdown, encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path), "docs_markdown": str(docs_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Strategy 3 overtrading diagnostics from smoke CSV outputs.")
    parser.add_argument("--executed-trades", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--output-dir", default="backtests/reports/strategy_3_overtrading_diagnostics")
    parser.add_argument("--docs-path", default="docs/research/strategy_3_overtrading_diagnostics.md")
    parser.add_argument("--rerun-command", default=None)
    args = parser.parse_args(argv)
    rows, columns = read_csv(Path(args.executed_trades))
    summary = read_json(Path(args.summary))
    report = build_overtrading_diagnostic(
        rows,
        columns,
        summary,
        source_path=args.executed_trades,
        summary_path=args.summary,
        rerun_command=args.rerun_command,
    )
    write_outputs(report, Path(args.output_dir), Path(args.docs_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
