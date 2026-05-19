from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median
from typing import Any, Literal

import pandas as pd

from dazro_trade.analysis.strategy_2_liquidity_expansion_stats import (
    LiquidityExpansionStatsProfile,
    adaptive_tp1_distance,
    expansion_quartiles,
    find_m15_0045_for_h1,
    first_level_touch,
    max_excursion_plus_25,
    normalize_ohlc,
    validate_liquidity_sequence,
)
from dazro_trade.backtest.simulator import BacktestSignal, simulate_trade_outcome


Direction = Literal["LONG", "SHORT"]

SETUP_FIELDS = [
    "setup_id",
    "symbol",
    "h1_timestamp",
    "h1_reference_timestamp",
    "direction",
    "decision",
    "entry_timestamp",
    "entry_price",
    "stop_loss",
    "tp1",
    "tp2",
    "tp3",
    "tp4",
    "h1_liquidity_level",
    "h1_liquidity_side",
    "m15_0045_high",
    "m15_0045_low",
    "liquidity_sequence_valid",
    "average_mae_used",
    "max_excursion_used",
    "average_expansion_used",
    "max_expansion_used",
    "entry_deviation_from_h1",
    "sl_distance_from_h1",
    "effective_risk_usd",
    "risk_too_large",
    "tp_anchor",
    "sl_formula",
    "entry_model",
    "confirmation_type",
    "no_trade_reason_codes",
    "outcome",
    "exit_time",
    "exit_price",
    "r_multiple",
    "mae",
    "mfe",
    "bars_held",
]

SAFETY = {
    "research_only": True,
    "dry_run": True,
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "order_execution_enabled": False,
    "broker_called": False,
    "telegram_sent": False,
    "order_sent": False,
    "order_send_called": False,
}


@dataclass(frozen=True)
class SpecTargets:
    tp1: float
    tp2: float
    tp3: float
    tp4: float
    tp1_distance: float
    tp2_distance: float
    tp3_distance: float
    tp4_distance: float


def _timestamp(value: Any) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _timestamp_text(value: Any) -> str | None:
    ts = _timestamp(value)
    return ts.isoformat() if ts is not None else None


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(float(value), digits) if value is not None else None


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def _mean(values: list[float]) -> float | None:
    return round(fmean(values), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(median(values), 4) if values else None


def build_spec_targets(direction: Direction, h1_level: float, profile: LiquidityExpansionStatsProfile) -> SpecTargets:
    quartiles = expansion_quartiles(profile.max_expansion)
    tp1_distance = adaptive_tp1_distance(average_expansion=profile.average_expansion, max_expansion=profile.max_expansion)
    tp2_distance = quartiles["tp2_quartile_distance"]
    tp3_distance = quartiles["tp3_quartile_distance"]
    tp4_distance = quartiles["tp4_quartile_distance"]
    multiplier = 1 if direction == "LONG" else -1
    return SpecTargets(
        tp1=round(h1_level + multiplier * tp1_distance, 4),
        tp2=round(h1_level + multiplier * tp2_distance, 4),
        tp3=round(h1_level + multiplier * tp3_distance, 4),
        tp4=round(h1_level + multiplier * tp4_distance, 4),
        tp1_distance=tp1_distance,
        tp2_distance=tp2_distance,
        tp3_distance=tp3_distance,
        tp4_distance=tp4_distance,
    )


def build_spec_stop(direction: Direction, h1_level: float, profile: LiquidityExpansionStatsProfile) -> float:
    distance = max_excursion_plus_25(profile.max_excursion)
    if direction == "LONG":
        return round(h1_level - distance, 4)
    return round(h1_level + distance, 4)


def _risk(entry: float, stop: float) -> float:
    return round(abs(float(entry) - float(stop)), 4)


def _entry_level(direction: Direction, h1_level: float, profile: LiquidityExpansionStatsProfile) -> float:
    if direction == "LONG":
        return round(h1_level - profile.average_mae, 4)
    return round(h1_level + profile.average_mae, 4)


def _entry_touch_time(m1_window: pd.DataFrame, *, direction: Direction, entry_level: float, after: Any) -> pd.Timestamp | None:
    ts = _timestamp(after)
    frame = normalize_ohlc(m1_window)
    if frame.empty or ts is None:
        return None
    after_frame = frame[frame["time"] >= ts]
    if direction == "LONG":
        hits = after_frame[after_frame["low"] <= entry_level]
    else:
        hits = after_frame[after_frame["high"] >= entry_level]
    if hits.empty:
        return None
    return pd.Timestamp(hits.iloc[0]["time"])


def detect_confirmation_type(m1_window: pd.DataFrame, *, direction: Direction, h1_level: float, after: Any) -> str | None:
    ts = _timestamp(after)
    frame = normalize_ohlc(m1_window)
    if frame.empty or ts is None:
        return None
    candidates = frame[frame["time"] >= ts].head(8)
    if candidates.empty:
        return None
    for _, candle in candidates.iterrows():
        open_price = float(candle["open"])
        close = float(candle["close"])
        high = float(candle["high"])
        low = float(candle["low"])
        candle_range = max(high - low, 0.0001)
        body = abs(close - open_price)
        body_ratio = body / candle_range
        if direction == "LONG":
            lower_wick = min(open_price, close) - low
            if close > h1_level:
                return "reclaim"
            if lower_wick / candle_range >= 0.45 and close > open_price:
                return "rejection"
            if close > open_price and body_ratio >= 0.6:
                return "aggressive_shift"
        else:
            upper_wick = high - max(open_price, close)
            if close < h1_level:
                return "reclaim"
            if upper_wick / candle_range >= 0.45 and close < open_price:
                return "rejection"
            if close < open_price and body_ratio >= 0.6:
                return "aggressive_shift"
    return None


def evaluate_spec_setup(
    *,
    symbol: str,
    h1_current: pd.Series,
    h1_reference: pd.Series,
    m1: pd.DataFrame,
    m15: pd.DataFrame,
    profile: LiquidityExpansionStatsProfile,
    direction: Direction,
    risk_limit_usd: float = 12.0,
    allow_risk_too_large: bool = False,
    max_bars: int = 480,
) -> dict[str, Any]:
    h1_start = pd.Timestamp(h1_current["time"])
    h1_end = h1_start + pd.Timedelta(hours=1)
    h1_ref_ts = pd.Timestamp(h1_reference["time"])
    h1_level = float(h1_reference["low"] if direction == "LONG" else h1_reference["high"])
    h1_side = "LOW" if direction == "LONG" else "HIGH"
    m1_frame = normalize_ohlc(m1)
    window = m1_frame[(m1_frame["time"] >= h1_start) & (m1_frame["time"] < h1_end)]
    m15_ref = find_m15_0045_for_h1(m15, h1_ref_ts) or {}
    reasons: list[str] = []
    setup_id = f"{symbol}_{h1_start.strftime('%Y%m%d%H%M')}_{direction}"
    row: dict[str, Any] = {
        "setup_id": setup_id,
        "symbol": symbol,
        "h1_timestamp": _timestamp_text(h1_start),
        "h1_reference_timestamp": _timestamp_text(h1_ref_ts),
        "direction": direction,
        "decision": "NO_TRADE",
        "h1_liquidity_level": round(h1_level, 4),
        "h1_liquidity_side": h1_side,
        "m15_0045_high": m15_ref.get("m15_0045_high"),
        "m15_0045_low": m15_ref.get("m15_0045_low"),
        "average_mae_used": profile.average_mae,
        "max_excursion_used": profile.max_excursion,
        "average_expansion_used": profile.average_expansion,
        "max_expansion_used": profile.max_expansion,
        "sl_distance_from_h1": profile.suggested_sl_distance,
        "tp_anchor": "H1_LEVEL",
        "sl_formula": "MAX_EXCURSION_PLUS_25",
        "entry_model": "AVERAGE_MAE_DEVIATION",
    }
    if window.empty:
        reasons.append("NO_TRADE_M1_WINDOW_MISSING")
        row.update({"no_trade_reason_codes": "|".join(reasons)})
        return row
    if not m15_ref:
        reasons.append("NO_TRADE_M15_0045_MISSING")
        row.update({"liquidity_sequence_valid": False, "no_trade_reason_codes": "|".join(reasons)})
        return row
    m15_opposite = float(m15_ref["m15_0045_high"] if direction == "LONG" else m15_ref["m15_0045_low"])
    sequence = validate_liquidity_sequence(
        window,
        direction=direction,
        h1_start=h1_start,
        h1_level=h1_level,
        m15_opposite_level=m15_opposite,
        end=h1_end,
    )
    row["liquidity_sequence_valid"] = bool(sequence["liquidity_sequence_valid"])
    if not sequence["h1_liquidity_taken"]:
        reasons.append("NO_TRADE_H1_LIQUIDITY_NOT_TAKEN")
    if not sequence["liquidity_sequence_valid"]:
        reasons.extend(str(v) for v in sequence.get("liquidity_sequence_reason_codes") or [] if v != "h1_liquidity_not_taken")
    if reasons:
        row.update({"no_trade_reason_codes": "|".join(sorted(set(reasons)))})
        return row

    sweep_time = sequence["h1_liquidity_taken_timestamp"]
    entry_level = _entry_level(direction, h1_level, profile)
    if profile.average_mae <= 0:
        reasons.append("NO_TRADE_AVERAGE_MAE_MISSING")
        row.update({"entry_deviation_from_h1": profile.average_mae, "no_trade_reason_codes": "|".join(reasons)})
        return row
    entry_time = _entry_touch_time(window, direction=direction, entry_level=entry_level, after=sweep_time)
    if entry_time is None:
        reasons.append("NO_TRADE_MAE_NOT_REACHED")
        row.update({"entry_deviation_from_h1": profile.average_mae, "no_trade_reason_codes": "|".join(reasons)})
        return row
    confirmation = detect_confirmation_type(window, direction=direction, h1_level=h1_level, after=entry_time)
    if confirmation is None:
        reasons.append("NO_TRADE_CONFIRMATION_MISSING")
        row.update(
            {
                "entry_timestamp": _timestamp_text(entry_time),
                "entry_price": entry_level,
                "entry_deviation_from_h1": profile.average_mae,
                "no_trade_reason_codes": "|".join(reasons),
            }
        )
        return row

    stop = build_spec_stop(direction, h1_level, profile)
    targets = build_spec_targets(direction, h1_level, profile)
    effective_risk = _risk(entry_level, stop)
    risk_too_large = effective_risk > risk_limit_usd
    row.update(
        {
            "entry_timestamp": _timestamp_text(entry_time),
            "entry_price": entry_level,
            "stop_loss": stop,
            "tp1": targets.tp1,
            "tp2": targets.tp2,
            "tp3": targets.tp3,
            "tp4": targets.tp4,
            "entry_deviation_from_h1": profile.average_mae,
            "effective_risk_usd": effective_risk,
            "risk_too_large": risk_too_large,
            "confirmation_type": confirmation,
        }
    )
    if effective_risk <= 0:
        reasons.append("NO_TRADE_INVALID_RISK")
    if risk_too_large and not allow_risk_too_large:
        reasons.append("RISK_TOO_LARGE")
    if reasons:
        row.update({"no_trade_reason_codes": "|".join(sorted(set(reasons)))})
        return row

    signal = BacktestSignal(
        timestamp=entry_time.to_pydatetime(),
        symbol=symbol,
        strategy="strategy_2_1_liquidity_expansion_spec",
        direction=direction,
        entry=entry_level,
        stop=stop,
        tp1=targets.tp1,
        tp2=targets.tp2,
        tp3=targets.tp3,
        tp4=targets.tp4,
        rr_tp1=round(abs(targets.tp1 - entry_level) / effective_risk, 4) if effective_risk > 0 else 0.0,
        metadata={
            "research_only": True,
            "enable_be_after_tp1": True,
            "tp_anchor": "H1_LEVEL",
            "sl_formula": "MAX_EXCURSION_PLUS_25",
            "entry_model": "AVERAGE_MAE_DEVIATION",
        },
    )
    future = m1_frame[m1_frame["time"] > entry_time]
    trade = simulate_trade_outcome(signal, future, max_bars=max_bars)
    row.update(
        {
            "decision": "TRADE",
            "no_trade_reason_codes": "",
            "outcome": trade.outcome,
            "exit_time": _timestamp_text(trade.exit_time),
            "exit_price": _round(trade.exit_price),
            "r_multiple": trade.r_multiple,
            "mae": trade.mae,
            "mfe": trade.mfe,
            "bars_held": trade.bars_held,
        }
    )
    return row


def scan_spec_model(
    *,
    symbol: str,
    market_data: dict[str, pd.DataFrame],
    profile: LiquidityExpansionStatsProfile,
    smoke_from: Any,
    smoke_to: Any,
    risk_limit_usd: float = 12.0,
    allow_risk_too_large: bool = False,
) -> dict[str, Any]:
    m1 = normalize_ohlc(market_data.get("M1"))
    m15 = normalize_ohlc(market_data.get("M15"))
    h1 = normalize_ohlc(market_data.get("H1"))
    start = _timestamp(smoke_from)
    end = _timestamp(smoke_to)
    setup_rows: list[dict[str, Any]] = []
    if m1.empty or m15.empty or h1.empty or start is None or end is None:
        summary = _summary(symbol, setup_rows, profile, smoke_from, smoke_to)
        summary["data_available"] = False
        return {"setup_rows": setup_rows, "trade_rows": [], "summary": summary, "report_markdown": render_smoke_markdown(summary)}
    window_h1 = h1[(h1["time"] >= start) & (h1["time"] <= end)]
    for _, current in window_h1.iterrows():
        prior = h1[h1["time"] < current["time"]].tail(1)
        if prior.empty:
            continue
        ref = prior.iloc[0]
        for direction in ("LONG", "SHORT"):
            setup_rows.append(
                evaluate_spec_setup(
                    symbol=symbol,
                    h1_current=current,
                    h1_reference=ref,
                    m1=m1,
                    m15=m15,
                    profile=profile,
                    direction=direction,  # type: ignore[arg-type]
                    risk_limit_usd=risk_limit_usd,
                    allow_risk_too_large=allow_risk_too_large,
                )
            )
    trade_rows = [row for row in setup_rows if row.get("decision") == "TRADE"]
    summary = _summary(symbol, setup_rows, profile, smoke_from, smoke_to)
    return {
        "setup_rows": setup_rows,
        "trade_rows": trade_rows,
        "summary": summary,
        "report_markdown": render_smoke_markdown(summary),
    }


def _summary(
    symbol: str,
    rows: list[dict[str, Any]],
    profile: LiquidityExpansionStatsProfile,
    smoke_from: Any,
    smoke_to: Any,
) -> dict[str, Any]:
    total = len(rows)
    trades = [row for row in rows if row.get("decision") == "TRADE"]
    no_trades = [row for row in rows if row.get("decision") != "TRADE"]
    reason_counts: Counter[str] = Counter()
    for row in no_trades:
        for reason in str(row.get("no_trade_reason_codes") or "").split("|"):
            if reason:
                reason_counts[reason] += 1
    sls = [float(row["effective_risk_usd"]) for row in rows if row.get("effective_risk_usd") not in (None, "")]
    rrs = _planned_rrs(trades)
    outcome_counts = Counter(str(row.get("outcome") or "NO_TRADE") for row in rows)
    summary = {
        "research_only": True,
        "safety": SAFETY,
        "symbol": symbol,
        "smoke_from": _timestamp_text(smoke_from),
        "smoke_to": _timestamp_text(smoke_to),
        "setups_found": total,
        "trades_taken": len(trades),
        "no_trades": len(no_trades),
        "no_trade_reasons": dict(reason_counts),
        "average_sl": _mean(sls),
        "median_sl": _median(sls),
        "sl_gt_12_count": sum(1 for value in sls if value > 12.0),
        "sl_gt_12_rate": _rate(sum(1 for value in sls if value > 12.0), len(sls)),
        "planned_rr_to_tp1": rrs["tp1"],
        "planned_rr_to_tp2": rrs["tp2"],
        "planned_rr_to_tp3": rrs["tp3"],
        "planned_rr_to_tp4": rrs["tp4"],
        "outcome_counts": dict(outcome_counts),
        "still_open_rate": _rate(outcome_counts.get("STILL_OPEN", 0), max(1, len(trades))),
        "timeout_rate": _rate(outcome_counts.get("TIMEOUT_CLOSE", 0), max(1, len(trades))),
        "end_of_data_rate": _rate(outcome_counts.get("END_OF_DATA_CLOSE", 0), max(1, len(trades))),
        "stats_profile": profile.to_dict(),
        "stat_profile_unrealistic": profile.effective_risk_gt_12 or profile.samples < 10,
    }
    verdict_flags = ["STRATEGY_2_1_SPEC_MODEL_ADDED_RESEARCH_ONLY"]
    if len(trades) < 10:
        verdict_flags.append("STRATEGY_2_1_SAMPLE_TOO_SMALL")
    if summary["sl_gt_12_rate"] > 0:
        verdict_flags.append("SPEC_MODEL_RISK_TOO_LARGE")
    if len(trades) < 10 and total > 0:
        verdict_flags.append("SPEC_MODEL_MECHANICS_OK_SAMPLE_TOO_SMALL")
    verdict_flags.extend(["STRATEGY_2_REMAINS_RESEARCH_ONLY", "NO_LIVE_DEPLOYMENT_DECISION"])
    summary["verdict_flags"] = verdict_flags
    return summary


def _planned_rrs(trades: list[dict[str, Any]]) -> dict[str, float | None]:
    out: dict[str, list[float]] = {"tp1": [], "tp2": [], "tp3": [], "tp4": []}
    for row in trades:
        entry = row.get("entry_price")
        stop = row.get("stop_loss")
        if entry in (None, "") or stop in (None, ""):
            continue
        risk = abs(float(entry) - float(stop))
        if risk <= 0:
            continue
        for key in out:
            tp = row.get(key)
            if tp not in (None, ""):
                out[key].append(abs(float(tp) - float(entry)) / risk)
    return {key: _mean(vals) for key, vals in out.items()}


def render_smoke_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Strategy 2.1 Liquidity Expansion Spec Smoke",
        "",
        "Research-only smoke. This is mechanics/sanity only, not validation.",
        "",
        f"- symbol: `{summary['symbol']}`",
        f"- smoke window: `{summary['smoke_from']}` -> `{summary['smoke_to']}`",
        f"- setups found: `{summary['setups_found']}`",
        f"- trades taken: `{summary['trades_taken']}`",
        f"- no-trades: `{summary['no_trades']}`",
        f"- average SL: `{summary['average_sl']}`",
        f"- median SL: `{summary['median_sl']}`",
        f"- SL > 12 count/rate: `{summary['sl_gt_12_count']}` / `{summary['sl_gt_12_rate']}`",
        f"- planned R:R to TP1/TP2/TP3/TP4: `{summary['planned_rr_to_tp1']}`, `{summary['planned_rr_to_tp2']}`, `{summary['planned_rr_to_tp3']}`, `{summary['planned_rr_to_tp4']}`",
        "",
        "## No-Trade Reasons",
        "",
        "```json",
        json.dumps(summary["no_trade_reasons"], indent=2, sort_keys=True),
        "```",
        "",
        "## Outcomes",
        "",
        "```json",
        json.dumps(summary["outcome_counts"], indent=2, sort_keys=True),
        "```",
        "",
        "## Verdict Flags",
        "",
        "\n".join(f"- `{flag}`" for flag in summary["verdict_flags"]),
    ]
    return "\n".join(lines) + "\n"


def write_smoke_outputs(report: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "setups_csv": str(output_dir / "strategy_2_1_spec_smoke_setups.csv"),
        "trades_csv": str(output_dir / "strategy_2_1_spec_smoke_trades.csv"),
        "summary_json": str(output_dir / "strategy_2_1_spec_smoke_summary.json"),
        "report_md": str(output_dir / "strategy_2_1_spec_smoke_report.md"),
    }
    with Path(paths["setups_csv"]).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SETUP_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["setup_rows"])
    with Path(paths["trades_csv"]).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SETUP_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["trade_rows"])
    Path(paths["summary_json"]).write_text(json.dumps(report["summary"], indent=2, sort_keys=True, default=str), encoding="utf-8")
    Path(paths["report_md"]).write_text(report["report_markdown"], encoding="utf-8")
    return paths


__all__ = [
    "SAFETY",
    "SETUP_FIELDS",
    "SpecTargets",
    "build_spec_stop",
    "build_spec_targets",
    "detect_confirmation_type",
    "evaluate_spec_setup",
    "render_smoke_markdown",
    "scan_spec_model",
    "write_smoke_outputs",
]
