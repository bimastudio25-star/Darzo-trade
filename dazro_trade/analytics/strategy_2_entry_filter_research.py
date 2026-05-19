from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from statistics import fmean
from typing import Any, Callable, Iterable

import pandas as pd

from dazro_trade.analysis.human_trade_management import evaluate_m5_close_quality, metric_block_from_r
from dazro_trade.analytics.strategy_2_entry_quality_diagnostics import (
    enrich_trade_entry_quality,
    read_executed_trades,
)
from dazro_trade.analytics.strategy_2_hourly_session_diagnostics import (
    derived_session_from_hour,
    sample_size_interpretation,
    sample_size_label,
)


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
    "strategy_2_entry_logic_changed": False,
    "strategy_3_logic_changed": False,
    "adelin_logic_changed": False,
    "machine_learning_used": False,
}

ENTRY_FILTER_RESULT_FIELDS = [
    "filter_name",
    "feature_safety_status",
    "rule_definition",
    "n_total",
    "n_kept",
    "n_rejected",
    "kept_sample_label",
    "rejected_sample_label",
    "baseline_PF",
    "kept_PF",
    "rejected_PF",
    "baseline_WR",
    "kept_WR",
    "rejected_WR",
    "baseline_AvgR",
    "kept_AvgR",
    "rejected_AvgR",
    "baseline_total_R",
    "kept_total_R",
    "rejected_total_R",
    "kept_MaxDD",
    "n_kept_ge_30",
    "kept_PF_gt_1",
    "kept_PF_ge_1_10",
    "improvement_logically_explainable",
    "exploratory",
    "rejected_for_leakage",
    "caveats",
]

FEATURE_AUDIT_FIELDS = [
    "trade_id",
    "feature_name",
    "feature_latest_timestamp",
    "entry_timestamp",
    "is_pre_entry_safe",
    "value",
    "source",
]

REACTION_ALIVE_NOTE_FIELDS = [
    "feature_name",
    "feature_value",
    "n",
    "reaction_alive_count",
    "reaction_alive_rate",
    "sample_label",
    "PF",
    "WR",
    "AvgR",
    "total_R",
    "notes",
]


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _direction(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"BUY", "BULL", "BULLISH", "LONG"}:
        return "LONG"
    if text in {"SELL", "BEAR", "BEARISH", "SHORT"}:
        return "SHORT"
    return text or "UNKNOWN"


def _entry_timestamp(row: dict[str, Any]) -> pd.Timestamp | None:
    for field in ("entry_timestamp", "signal_timestamp", "timestamp", "time"):
        ts = _timestamp(row.get(field))
        if ts is not None:
            return ts
    return None


def _entry_price(row: dict[str, Any]) -> float | None:
    return _to_float(row.get("entry_price") or row.get("entry"))


def _stop_loss(row: dict[str, Any]) -> float | None:
    return _to_float(row.get("stop_loss") or row.get("stop"))


def _risk(row: dict[str, Any]) -> float | None:
    entry = _entry_price(row)
    stop = _stop_loss(row)
    if entry is None or stop is None:
        return None
    distance = abs(entry - stop)
    return distance if distance > 0 else None


def _r_value(row: dict[str, Any]) -> float | None:
    for field in ("r_multiple", "result_baseline_R"):
        value = _to_float(row.get(field))
        if value is not None:
            return value
    return None


def _prepare_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], utc=True, errors="coerce")
        out = out.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    return out


def _previous_candles(frame: pd.DataFrame | None, entry_time: Any, count: int) -> pd.DataFrame:
    candles = _prepare_frame(frame)
    ts = _timestamp(entry_time)
    if candles.empty or ts is None or "time" not in candles.columns:
        return pd.DataFrame()
    return candles[candles["time"] < ts].tail(count).copy()


def audit_feature_timestamp(
    feature_name: str,
    feature_latest_timestamp: Any,
    entry_timestamp: Any,
    *,
    trade_id: str = "",
    value: Any = None,
    source: str = "",
) -> dict[str, Any]:
    latest = _timestamp(feature_latest_timestamp)
    entry = _timestamp(entry_timestamp)
    safe = bool(latest is not None and entry is not None and latest <= entry)
    return {
        "trade_id": trade_id,
        "feature_name": feature_name,
        "feature_latest_timestamp": latest.isoformat() if latest is not None else None,
        "entry_timestamp": entry.isoformat() if entry is not None else None,
        "is_pre_entry_safe": safe,
        "value": value,
        "source": source,
    }


def _session_from_row(row: dict[str, Any], hour: int | None) -> str:
    session = str(row.get("session") or "").strip()
    if session:
        return session
    return derived_session_from_hour(hour)


def _target_space_r(source: dict[str, Any], diagnostic: dict[str, Any], risk: float | None, direction: str, entry: float | None) -> float | None:
    direct = _to_float(diagnostic.get("target_space_proxy"))
    if direct is not None:
        return direct
    for field in ("rr", "rr_tp1"):
        value = _to_float(source.get(field))
        if value is not None:
            return round(value, 4)
    reward = _to_float(source.get("reward_distance"))
    if reward is not None and risk:
        return round(reward / risk, 4)
    target = _to_float(source.get("take_profit") or source.get("tp2") or source.get("tp1"))
    if entry is not None and target is not None and risk:
        distance = target - entry if direction == "LONG" else entry - target
        return round(distance / risk, 4)
    return None


def _m5_quality_before_entry(
    previous_m5: pd.DataFrame,
    direction: str,
    entry: float | None,
    stop: float | None,
) -> tuple[str | None, float | None, str]:
    if previous_m5.empty or entry is None:
        return None, None, "missing_pre_entry_m5"
    candle = previous_m5.iloc[-1].to_dict()
    prior = previous_m5.iloc[-2].to_dict() if len(previous_m5) >= 2 else None
    quality = evaluate_m5_close_quality(
        candle,
        direction,
        previous_candle=prior,
        entry_price=entry,
        invalidation_level=stop,
    )
    return quality.get("quality"), quality.get("score"), ";".join(str(code) for code in quality.get("reason_codes", []))


def _body_to_range(row: dict[str, Any]) -> float | None:
    open_ = _to_float(row.get("open"))
    high = _to_float(row.get("high"))
    low = _to_float(row.get("low"))
    close = _to_float(row.get("close"))
    if None in (open_, high, low, close) or high == low:
        return None
    return abs(float(close) - float(open_)) / abs(float(high) - float(low))


def _m15_context(previous_m15: pd.DataFrame, direction: str, entry: float | None, risk: float | None) -> dict[str, Any]:
    if previous_m15.empty:
        return {
            "recent_m15_favorable_count": None,
            "recent_m15_adverse_count": None,
            "recent_m15_avg_body_to_range": None,
            "recent_m15_dead_context_proxy": None,
            "pre_entry_displacement_R": None,
            "overextension_proxy": None,
            "nearest_obstacle_distance_R": None,
            "too_close_to_obstacle_proxy": None,
        }
    last3 = previous_m15.tail(3)
    favorable = 0
    adverse = 0
    body_ratios: list[float] = []
    for _, candle in last3.iterrows():
        open_ = _to_float(candle.get("open"))
        close = _to_float(candle.get("close"))
        ratio = _body_to_range(candle.to_dict())
        if ratio is not None:
            body_ratios.append(ratio)
        if open_ is None or close is None:
            continue
        bullish = close > open_
        bearish = close < open_
        if (direction == "LONG" and bullish) or (direction == "SHORT" and bearish):
            favorable += 1
        if (direction == "LONG" and bearish) or (direction == "SHORT" and bullish):
            adverse += 1
    avg_body = round(fmean(body_ratios), 4) if body_ratios else None
    dead_context = bool(adverse >= 2 or (favorable <= 1 and avg_body is not None and avg_body < 0.25))

    displacement_r = None
    overextended = None
    if len(last3) >= 2 and risk:
        first_open = _to_float(last3.iloc[0].get("open"))
        last_close = _to_float(last3.iloc[-1].get("close"))
        if first_open is not None and last_close is not None:
            displacement = last_close - first_open if direction == "LONG" else first_open - last_close
            displacement_r = round(max(0.0, displacement) / risk, 4)
            overextended = displacement_r >= 0.75

    obstacle_r = None
    too_close = None
    if entry is not None and risk:
        if direction == "LONG":
            candidates = [
                _to_float(value) - entry
                for value in previous_m15.tail(20)["high"].tolist()
                if _to_float(value) is not None and _to_float(value) > entry
            ]
        else:
            candidates = [
                entry - _to_float(value)
                for value in previous_m15.tail(20)["low"].tolist()
                if _to_float(value) is not None and _to_float(value) < entry
            ]
        positive = [distance for distance in candidates if distance is not None and distance > 0]
        if positive:
            obstacle_r = round(min(positive) / risk, 4)
            too_close = obstacle_r < 1.0

    return {
        "recent_m15_favorable_count": favorable,
        "recent_m15_adverse_count": adverse,
        "recent_m15_avg_body_to_range": avg_body,
        "recent_m15_dead_context_proxy": dead_context,
        "pre_entry_displacement_R": displacement_r,
        "overextension_proxy": overextended,
        "nearest_obstacle_distance_R": obstacle_r,
        "too_close_to_obstacle_proxy": too_close,
    }


def _price_escape_pre_entry(previous_m5: pd.DataFrame, direction: str, entry: float | None, risk: float | None) -> dict[str, Any]:
    if previous_m5.empty or entry is None:
        return {"price_escape_pre_entry_usd": None, "price_escape_pre_entry_R": None, "price_escape_pre_entry_proxy": None}
    prev_close = _to_float(previous_m5.iloc[-1].get("close"))
    if prev_close is None:
        return {"price_escape_pre_entry_usd": None, "price_escape_pre_entry_R": None, "price_escape_pre_entry_proxy": None}
    escape = entry - prev_close if direction == "LONG" else prev_close - entry
    escape = max(0.0, escape)
    escape_r = escape / risk if risk else None
    proxy = escape >= 10.0 or (escape_r is not None and escape_r >= 0.25)
    return {
        "price_escape_pre_entry_usd": round(escape, 4),
        "price_escape_pre_entry_R": round(escape_r, 4) if escape_r is not None else None,
        "price_escape_pre_entry_proxy": proxy,
    }


def build_pre_entry_feature_rows(
    executed_rows: Iterable[dict[str, Any]],
    diagnostic_rows: Iterable[dict[str, Any]],
    *,
    market_data: dict[str, pd.DataFrame],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    executed = list(executed_rows)
    diagnostics = list(diagnostic_rows)
    diagnostic_by_id = {str(row.get("trade_id") or idx): row for idx, row in enumerate(diagnostics)}
    m5 = market_data.get("M5")
    m15 = market_data.get("M15")
    feature_rows: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []

    for idx, row in enumerate(executed):
        trade_id = str(row.get("trade_id") or row.get("id") or idx)
        diagnostic = diagnostic_by_id.get(trade_id) or (diagnostics[idx] if idx < len(diagnostics) else {})
        merged = {**row, **diagnostic}
        entry_ts = _entry_timestamp(merged)
        entry_text = entry_ts.isoformat() if entry_ts is not None else None
        hour = entry_ts.hour if entry_ts is not None else None
        direction = _direction(merged.get("direction"))
        entry = _entry_price(merged)
        stop = _stop_loss(merged)
        risk = _risk(merged)
        prev_m5 = _previous_candles(m5, entry_ts, 2)
        prev_m15 = _previous_candles(m15, entry_ts, 20)
        m5_latest = prev_m5.iloc[-1].get("time") if not prev_m5.empty else None
        m15_latest = prev_m15.iloc[-1].get("time") if not prev_m15.empty else None

        last_m5_quality, last_m5_score, last_m5_reasons = _m5_quality_before_entry(prev_m5, direction, entry, stop)
        m15_context = _m15_context(prev_m15, direction, entry, risk)
        escape = _price_escape_pre_entry(prev_m5, direction, entry, risk)
        target_space_r = _target_space_r(merged, diagnostic, risk, direction, entry)
        session = _session_from_row(merged, hour)
        derived_session = derived_session_from_hour(hour)
        dirty_context = bool(last_m5_quality in {"BAD_CLOSE", "INVALIDATING_CLOSE"} or m15_context["recent_m15_dead_context_proxy"])
        weak_session = derived_session in {"Asia", "LateUS"}
        row_out = {
            "trade_id": trade_id,
            "symbol": merged.get("symbol"),
            "strategy": merged.get("strategy") or merged.get("strategy_name"),
            "direction": direction,
            "entry_timestamp": entry_text,
            "entry_hour": hour,
            "session": session,
            "derived_session": derived_session,
            "setup_mode": merged.get("setup_mode"),
            "risk_label": merged.get("risk_label"),
            "r_multiple": _r_value(merged),
            "outcome": merged.get("outcome"),
            "entry_quality_label": diagnostic.get("entry_quality_label"),
            "reaction_state_5_m5": diagnostic.get("reaction_state_5_m5"),
            "later_reaction_alive": diagnostic.get("reaction_state_5_m5") == "REACTION_ALIVE",
            "target_space_R": target_space_r,
            "target_space_lt_1R": target_space_r is not None and target_space_r < 1.0,
            "last_m5_close_quality_pre_entry": last_m5_quality,
            "last_m5_close_score_pre_entry": last_m5_score,
            "last_m5_close_reason_codes_pre_entry": last_m5_reasons,
            "dirty_context_pre_entry_proxy": dirty_context,
            "weak_session_context_proxy": weak_session,
            "hour_14_16_window": hour in {14, 15} if hour is not None else None,
            **escape,
            **m15_context,
        }
        feature_rows.append(row_out)

        static_features = {
            "entry_hour": hour,
            "session": session,
            "direction": direction,
            "setup_mode": merged.get("setup_mode"),
            "risk_label": merged.get("risk_label"),
            "target_space_R": target_space_r,
            "target_space_lt_1R": row_out["target_space_lt_1R"],
            "weak_session_context_proxy": weak_session,
            "hour_14_16_window": row_out["hour_14_16_window"],
        }
        for name, value in static_features.items():
            audits.append(audit_feature_timestamp(name, entry_text, entry_text, trade_id=trade_id, value=value, source="trade_export_at_entry"))
        for name in ("price_escape_pre_entry_proxy", "price_escape_pre_entry_R", "last_m5_close_quality_pre_entry"):
            audits.append(audit_feature_timestamp(name, m5_latest, entry_text, trade_id=trade_id, value=row_out.get(name), source="last_closed_m5_before_entry"))
        for name in (
            "recent_m15_dead_context_proxy",
            "recent_m15_adverse_count",
            "pre_entry_displacement_R",
            "overextension_proxy",
            "nearest_obstacle_distance_R",
            "too_close_to_obstacle_proxy",
        ):
            audits.append(audit_feature_timestamp(name, m15_latest, entry_text, trade_id=trade_id, value=row_out.get(name), source="last_closed_m15_before_entry"))
        unsafe_latest = entry_ts + pd.Timedelta(minutes=25) if entry_ts is not None else None
        audits.append(
            audit_feature_timestamp(
                "reaction_state_5_m5",
                unsafe_latest,
                entry_text,
                trade_id=trade_id,
                value=row_out["reaction_state_5_m5"],
                source="post_entry_label_for_analysis_only",
            )
        )

    return feature_rows, audits


def load_strategy_2_inputs(
    trades_path: Path,
    entry_quality_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    executed_rows, executed_columns = read_executed_trades(trades_path)
    quality_path = entry_quality_dir / "strategy_2_entry_quality_trades.csv"
    if quality_path.exists():
        diagnostic_rows, diagnostic_columns = read_executed_trades(quality_path)
    else:
        diagnostic_rows, diagnostic_columns = [], []
    return executed_rows, diagnostic_rows, {
        "executed_trades_path": str(trades_path),
        "executed_columns": executed_columns,
        "entry_quality_trades_path": str(quality_path),
        "entry_quality_columns": diagnostic_columns,
        "entry_quality_rows_available": bool(diagnostic_rows),
    }


def discover_strategy_3_sample(search_root: Path) -> Path | None:
    candidates = [
        search_root / "backtests/reports/strategy_3_intermediate_validation/executed_trades.csv",
        search_root / "backtests/reports/strategy_3_vwap_1r_limited_post_cooldown/executed_trades.csv",
        search_root / "backtests/reports/strategy_3_vwap_1r_cooldown_120m_smoke/executed_trades.csv",
        search_root / "backtests/reports/strategy_3_entry_filter_calibration_smoke/executed_trades.csv",
        search_root / "backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def calibration_verdict_from_counts(
    *,
    strategy2_trade_now: int,
    strategy2_no_trade: int,
    strategy2_sample_size: int,
    strategy3_trade_now: int,
    strategy3_no_trade: int,
    strategy3_sample_size: int,
) -> dict[str, Any]:
    if strategy3_sample_size <= 0:
        return {
            "verdict": "TAXONOMY_CALIBRATION_DATA_MISSING",
            "flags": ["TAXONOMY_CALIBRATION_DATA_MISSING", "TAXONOMY_CALIBRATION_INCONCLUSIVE"],
            "strategy3_no_trade_rate": None,
            "strategy3_trade_now_rate": None,
        }
    s2_no_trade_rate = strategy2_no_trade / strategy2_sample_size if strategy2_sample_size else None
    s2_trade_now_rate = strategy2_trade_now / strategy2_sample_size if strategy2_sample_size else None
    s3_no_trade_rate = strategy3_no_trade / strategy3_sample_size
    s3_trade_now_rate = strategy3_trade_now / strategy3_sample_size
    if s3_no_trade_rate >= 0.90:
        verdict = "TAXONOMY_TOO_STRICT"
        flags = ["TAXONOMY_TOO_STRICT"]
    elif strategy3_sample_size < 30:
        verdict = "TAXONOMY_CALIBRATION_INCONCLUSIVE"
        flags = ["TAXONOMY_CALIBRATION_INCONCLUSIVE"]
    elif (
        s2_no_trade_rate is not None
        and s3_no_trade_rate <= max(0.0, s2_no_trade_rate - 0.20)
    ) or (
        s2_trade_now_rate is not None
        and s3_trade_now_rate >= s2_trade_now_rate + 0.10
    ):
        verdict = "TAXONOMY_DISCRIMINATING"
        flags = ["TAXONOMY_DISCRIMINATING"]
    else:
        verdict = "TAXONOMY_CALIBRATION_INCONCLUSIVE"
        flags = ["TAXONOMY_CALIBRATION_INCONCLUSIVE"]
    return {
        "verdict": verdict,
        "flags": flags,
        "strategy2_no_trade_rate": round(s2_no_trade_rate, 4) if s2_no_trade_rate is not None else None,
        "strategy2_trade_now_rate": round(s2_trade_now_rate, 4) if s2_trade_now_rate is not None else None,
        "strategy3_no_trade_rate": round(s3_no_trade_rate, 4),
        "strategy3_trade_now_rate": round(s3_trade_now_rate, 4),
    }


def build_taxonomy_calibration(
    *,
    strategy2_diagnostic_rows: Iterable[dict[str, Any]],
    strategy3_rows: Iterable[dict[str, Any]] | None,
    strategy3_source_path: str | None,
    market_data: dict[str, pd.DataFrame],
    symbol: str = "XAUUSD",
) -> dict[str, Any]:
    s2_rows = list(strategy2_diagnostic_rows)
    s2_counts = Counter(str(row.get("entry_quality_label") or "UNKNOWN_INSUFFICIENT_DATA") for row in s2_rows)
    s2_trade_now = s2_counts.get("TRADE_NOW", 0)
    s2_no_trade = sum(count for label, count in s2_counts.items() if label.startswith("NO_TRADE"))

    if not strategy3_rows:
        verdict = calibration_verdict_from_counts(
            strategy2_trade_now=s2_trade_now,
            strategy2_no_trade=s2_no_trade,
            strategy2_sample_size=len(s2_rows),
            strategy3_trade_now=0,
            strategy3_no_trade=0,
            strategy3_sample_size=0,
        )
        return {
            "research_only": True,
            "symbol": symbol,
            "strategy3_source_path": strategy3_source_path,
            "strategy3_sample_size": 0,
            "strategy3_known_metrics": None,
            "strategy3_entry_quality_label_counts": {},
            "strategy3_trade_now_count": 0,
            "strategy3_no_trade_count": 0,
            "strategy2_entry_quality_label_counts": dict(s2_counts),
            **verdict,
            "limitation": "No usable Strategy 3 trade/signal sample was available for taxonomy calibration.",
        }

    s3_input_rows = list(strategy3_rows)
    enriched = [
        enrich_trade_entry_quality(row, m5=market_data.get("M5"), m1=market_data.get("M1"), reaction_window_m5=5, row_index=idx)
        for idx, row in enumerate(s3_input_rows)
    ]
    s3_counts = Counter(str(row.get("entry_quality_label") or "UNKNOWN_INSUFFICIENT_DATA") for row in enriched)
    s3_trade_now = s3_counts.get("TRADE_NOW", 0)
    s3_no_trade = sum(count for label, count in s3_counts.items() if label.startswith("NO_TRADE"))
    metrics = metric_block_from_r(value for row in s3_input_rows if (value := _r_value(row)) is not None)
    verdict = calibration_verdict_from_counts(
        strategy2_trade_now=s2_trade_now,
        strategy2_no_trade=s2_no_trade,
        strategy2_sample_size=len(s2_rows),
        strategy3_trade_now=s3_trade_now,
        strategy3_no_trade=s3_no_trade,
        strategy3_sample_size=len(enriched),
    )
    return {
        "research_only": True,
        "symbol": symbol,
        "strategy3_source_path": strategy3_source_path,
        "strategy3_sample_size": len(enriched),
        "strategy3_known_metrics": metrics if metrics["trades"] else None,
        "strategy3_entry_quality_label_counts": dict(s3_counts),
        "strategy3_trade_now_count": s3_trade_now,
        "strategy3_no_trade_count": s3_no_trade,
        "strategy2_entry_quality_label_counts": dict(s2_counts),
        "strategy2_trade_now_count": s2_trade_now,
        "strategy2_no_trade_count": s2_no_trade,
        "strategy2_sample_size": len(s2_rows),
        **verdict,
        "limitation": None,
    }


def _pf_to_float(value: Any) -> float | None:
    if value == "inf":
        return float("inf")
    return _to_float(value)


def _metric_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [value for row in rows if (value := _r_value(row)) is not None]
    return metric_block_from_r(values)


def _filter_result(
    *,
    name: str,
    rule: str,
    rows: list[dict[str, Any]],
    reject_predicate: Callable[[dict[str, Any]], bool],
    baseline: dict[str, Any],
    safe: bool,
    exploratory: bool = False,
    caveats: list[str] | None = None,
) -> dict[str, Any]:
    caveats = list(caveats or [])
    if not safe:
        caveats.append("Rejected: candidate uses post-entry/future data.")
    kept = [row for row in rows if not reject_predicate(row)]
    rejected = [row for row in rows if reject_predicate(row)]
    kept_metrics = _metric_block(kept)
    rejected_metrics = _metric_block(rejected)
    kept_pf = _pf_to_float(kept_metrics["PF"])
    baseline_pf = _pf_to_float(baseline["PF"])
    improves = bool(safe and kept_pf is not None and baseline_pf is not None and kept_pf > baseline_pf and kept_metrics["trades"] >= 10)
    if kept_metrics["trades"] < 30:
        caveats.append("kept sample below 30; exploratory only")
    if exploratory:
        caveats.append("exploratory rule; not suitable for live filtering")
    return {
        "filter_name": name,
        "feature_safety_status": "safe_pre_entry" if safe else "unsafe_future_data_rejected",
        "rule_definition": rule,
        "n_total": len(rows),
        "n_kept": kept_metrics["trades"],
        "n_rejected": rejected_metrics["trades"],
        "kept_sample_label": sample_size_label(kept_metrics["trades"]),
        "rejected_sample_label": sample_size_label(rejected_metrics["trades"]),
        "baseline_PF": baseline["PF"],
        "kept_PF": kept_metrics["PF"],
        "rejected_PF": rejected_metrics["PF"],
        "baseline_WR": baseline["WR"],
        "kept_WR": kept_metrics["WR"],
        "rejected_WR": rejected_metrics["WR"],
        "baseline_AvgR": baseline["AvgR"],
        "kept_AvgR": kept_metrics["AvgR"],
        "rejected_AvgR": rejected_metrics["AvgR"],
        "baseline_total_R": baseline["total_R"],
        "kept_total_R": kept_metrics["total_R"],
        "rejected_total_R": rejected_metrics["total_R"],
        "kept_MaxDD": kept_metrics["MaxDD"],
        "n_kept_ge_30": kept_metrics["trades"] >= 30,
        "kept_PF_gt_1": bool(kept_pf is not None and kept_pf > 1.0),
        "kept_PF_ge_1_10": bool(kept_pf is not None and kept_pf >= 1.10),
        "improvement_logically_explainable": improves,
        "exploratory": exploratory,
        "rejected_for_leakage": not safe,
        "caveats": "; ".join(dict.fromkeys(caveats)),
    }


def run_simple_filter_tests(feature_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(feature_rows)
    baseline = _metric_block(rows)
    return [
        _filter_result(
            name="reject_price_escape_pre_entry",
            rule="reject when price_escape_pre_entry_proxy is true",
            rows=rows,
            reject_predicate=lambda row: bool(row.get("price_escape_pre_entry_proxy")),
            baseline=baseline,
            safe=True,
        ),
        _filter_result(
            name="reject_dirty_pre_entry_m5_or_m15",
            rule="reject when last closed M5 is bad/invalidating or last closed M15 context is dead",
            rows=rows,
            reject_predicate=lambda row: bool(row.get("dirty_context_pre_entry_proxy")),
            baseline=baseline,
            safe=True,
        ),
        _filter_result(
            name="reject_target_space_lt_1R",
            rule="reject when target_space_R < 1.0 using target/stop known at entry",
            rows=rows,
            reject_predicate=lambda row: bool(row.get("target_space_lt_1R")),
            baseline=baseline,
            safe=True,
        ),
        _filter_result(
            name="reject_recent_m15_dead_context",
            rule="reject when the last 3 closed M15 candles show adverse or low-body context",
            rows=rows,
            reject_predicate=lambda row: bool(row.get("recent_m15_dead_context_proxy")),
            baseline=baseline,
            safe=True,
        ),
        _filter_result(
            name="reject_pre_entry_overextension",
            rule="reject when favorable displacement over last 3 closed M15 candles is >= 0.75R",
            rows=rows,
            reject_predicate=lambda row: bool(row.get("overextension_proxy")),
            baseline=baseline,
            safe=True,
        ),
        _filter_result(
            name="reject_too_close_to_pre_entry_obstacle",
            rule="reject when nearest prior M15 swing obstacle before target is closer than 1R",
            rows=rows,
            reject_predicate=lambda row: bool(row.get("too_close_to_obstacle_proxy")),
            baseline=baseline,
            safe=True,
        ),
        _filter_result(
            name="exploratory_keep_14_16_only",
            rule="reject entries outside the 14:00-16:00 hypothesis window",
            rows=rows,
            reject_predicate=lambda row: row.get("entry_hour") not in {14, 15},
            baseline=baseline,
            safe=True,
            exploratory=True,
            caveats=["hour/session buckets are same-sample exploratory"],
        ),
        _filter_result(
            name="exploratory_dirty_or_target_space",
            rule="reject when dirty_context_pre_entry_proxy is true or target_space_R < 1.0",
            rows=rows,
            reject_predicate=lambda row: bool(row.get("dirty_context_pre_entry_proxy")) or bool(row.get("target_space_lt_1R")),
            baseline=baseline,
            safe=True,
            exploratory=True,
            caveats=["max two simple conditions; exploratory"],
        ),
        _filter_result(
            name="rejected_post_entry_reaction_alive_filter",
            rule="reject when reaction_state_5_m5 is not REACTION_ALIVE",
            rows=rows,
            reject_predicate=lambda row: row.get("reaction_state_5_m5") != "REACTION_ALIVE",
            baseline=baseline,
            safe=False,
            caveats=["REACTION_ALIVE is a post-entry label and cannot be a live filter"],
        ),
    ]


def reaction_alive_predictor_notes(feature_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(feature_rows)
    features = [
        "price_escape_pre_entry_proxy",
        "dirty_context_pre_entry_proxy",
        "target_space_lt_1R",
        "recent_m15_dead_context_proxy",
        "overextension_proxy",
        "too_close_to_obstacle_proxy",
        "hour_14_16_window",
        "derived_session",
        "direction",
        "last_m5_close_quality_pre_entry",
    ]
    out: list[dict[str, Any]] = []
    for feature in features:
        values = sorted({str(row.get(feature)) for row in rows})
        for value in values:
            group = [row for row in rows if str(row.get(feature)) == value]
            if not group:
                continue
            alive_count = sum(1 for row in group if row.get("later_reaction_alive"))
            metrics = _metric_block(group)
            out.append(
                {
                    "feature_name": feature,
                    "feature_value": value,
                    "n": len(group),
                    "reaction_alive_count": alive_count,
                    "reaction_alive_rate": round(alive_count / len(group), 4),
                    "sample_label": sample_size_label(len(group)),
                    "PF": metrics["PF"],
                    "WR": metrics["WR"],
                    "AvgR": metrics["AvgR"],
                    "total_R": metrics["total_R"],
                    "notes": "REACTION_ALIVE is used only as a target label, not as a filter input.",
                }
            )
    return sorted(out, key=lambda row: (row["reaction_alive_rate"], row["n"]), reverse=True)


def _distribution(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(Counter(str(row.get(field)) for row in rows))


def build_decision_matrix(
    calibration: dict[str, Any],
    filter_results: list[dict[str, Any]],
    reaction_notes: list[dict[str, Any]],
) -> dict[str, Any]:
    flags = ["STRATEGY_2_REMAINS_RESEARCH_ONLY", "NO_LIVE_DEPLOYMENT_DECISION"]
    flags.extend(calibration.get("flags", []))
    usable = [row for row in filter_results if not row["rejected_for_leakage"]]
    safe_n30 = [row for row in usable if row["n_kept"] >= 30]
    pf_gt_1 = [row for row in safe_n30 if bool(row["kept_PF_gt_1"])]
    pf_ge_110 = [row for row in safe_n30 if bool(row["kept_PF_ge_1_10"])]
    if not safe_n30:
        flags.append("FILTER_RESULTS_INSUFFICIENT_SAMPLE")
    if pf_gt_1:
        flags.append("PRE_ENTRY_FILTER_IMPROVES_BASELINE_RESEARCH_ONLY")
    if pf_ge_110:
        flags.append("PRE_ENTRY_FILTER_PROMISING_BUT_NOT_VALIDATED")
    if not pf_gt_1:
        flags.append("NO_PREDICTIVE_ENTRY_FILTER_FOUND")
    if any(row["rejected_for_leakage"] for row in filter_results):
        flags.append("LEAKAGE_ATTEMPT_REJECTED")
    post_hoc = next((row for row in filter_results if row["filter_name"] == "rejected_post_entry_reaction_alive_filter"), None)
    safe_best = _best_usable_filter(usable)
    if post_hoc and post_hoc.get("kept_PF_gt_1") and (not safe_best or not safe_best.get("kept_PF_gt_1")):
        flags.append("POST_HOC_REACTION_ONLY_NOT_TRADABLE")
    if "NO_PREDICTIVE_ENTRY_FILTER_FOUND" in flags:
        flags.append("STRATEGY_2_ARCHIVE_RECOMMENDED")

    if "PRE_ENTRY_FILTER_PROMISING_BUT_NOT_VALIDATED" in flags:
        next_step = "feat/strategy-2-filter-validation-larger-sample"
    elif "TAXONOMY_TOO_STRICT" in flags:
        next_step = "feat/strategy-2-taxonomy-calibration-repair"
    elif "TAXONOMY_CALIBRATION_DATA_MISSING" in flags:
        next_step = "generate/locate usable Strategy 3 calibration sample first"
    else:
        next_step = "focus Strategy 3 paper validation; pause/archive Strategy 2"
    return {
        "verdict_flags": list(dict.fromkeys(flags)),
        "best_usable_filter": safe_best,
        "best_reaction_alive_association": _best_reaction_alive_association(reaction_notes),
        "next_step": next_step,
    }


def _best_usable_filter(filter_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [row for row in filter_results if row["n_kept"] > 0]
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: (_pf_to_float(row["kept_PF"]) or -999.0, row["kept_AvgR"] or -999.0), reverse=True)[0]


def _best_reaction_alive_association(reaction_notes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for minimum_n in (30, 10, 1):
        candidates = [row for row in reaction_notes if int(row.get("n") or 0) >= minimum_n]
        if candidates:
            return sorted(candidates, key=lambda row: (float(row["reaction_alive_rate"]), int(row["n"])), reverse=True)[0]
    return None


def build_entry_filter_research(
    *,
    strategy2_executed_rows: Iterable[dict[str, Any]],
    strategy2_diagnostic_rows: Iterable[dict[str, Any]],
    strategy3_rows: Iterable[dict[str, Any]] | None,
    strategy3_source_path: str | None,
    market_data: dict[str, pd.DataFrame],
    symbol: str,
    source: dict[str, Any],
) -> dict[str, Any]:
    s2_executed = list(strategy2_executed_rows)
    s2_diagnostics = list(strategy2_diagnostic_rows)
    if not s2_diagnostics:
        s2_diagnostics = [
            enrich_trade_entry_quality(row, m5=market_data.get("M5"), m1=market_data.get("M1"), row_index=idx)
            for idx, row in enumerate(s2_executed)
        ]
    feature_rows, audit_rows = build_pre_entry_feature_rows(s2_executed, s2_diagnostics, market_data=market_data)
    calibration = build_taxonomy_calibration(
        strategy2_diagnostic_rows=s2_diagnostics,
        strategy3_rows=strategy3_rows,
        strategy3_source_path=strategy3_source_path,
        market_data=market_data,
        symbol=symbol,
    )
    filter_results = run_simple_filter_tests(feature_rows)
    reaction_notes = reaction_alive_predictor_notes(feature_rows)
    decision = build_decision_matrix(calibration, filter_results, reaction_notes)
    baseline = _metric_block(feature_rows)
    summary = {
        "research_only": True,
        "safety": SAFETY,
        "source": source,
        "symbol": symbol,
        "strategy2_trades_analyzed": len(feature_rows),
        "baseline": baseline,
        "taxonomy_calibration": calibration,
        "pre_entry_feature_summary": {
            "feature_rows": len(feature_rows),
            "audit_rows": len(audit_rows),
            "unsafe_audit_rows": sum(1 for row in audit_rows if not row["is_pre_entry_safe"]),
            "feature_counts": {
                "price_escape_pre_entry_proxy": _distribution(feature_rows, "price_escape_pre_entry_proxy"),
                "dirty_context_pre_entry_proxy": _distribution(feature_rows, "dirty_context_pre_entry_proxy"),
                "target_space_lt_1R": _distribution(feature_rows, "target_space_lt_1R"),
                "recent_m15_dead_context_proxy": _distribution(feature_rows, "recent_m15_dead_context_proxy"),
                "overextension_proxy": _distribution(feature_rows, "overextension_proxy"),
                "too_close_to_obstacle_proxy": _distribution(feature_rows, "too_close_to_obstacle_proxy"),
            },
        },
        "filter_results": filter_results,
        "reaction_alive_predictor_notes": reaction_notes,
        "decision_matrix": decision,
    }
    return {
        "summary": summary,
        "taxonomy_calibration": calibration,
        "feature_rows": feature_rows,
        "feature_audit_rows": audit_rows,
        "filter_results": filter_results,
        "reaction_alive_notes": reaction_notes,
        "taxonomy_report_markdown": render_taxonomy_report(calibration),
        "report_markdown": render_entry_filter_report(summary),
    }


def _table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "_No rows._"
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return "\n".join(lines)


def render_taxonomy_report(calibration: dict[str, Any]) -> str:
    lines = [
        "# Strategy 2 Entry Filter Taxonomy Calibration",
        "",
        "Status: research-only calibration. No live trading, no Telegram, no broker orders.",
        "",
        f"- Strategy 3 source: `{calibration.get('strategy3_source_path')}`",
        f"- Strategy 3 sample size: `{calibration.get('strategy3_sample_size')}`",
        f"- calibration verdict: `{calibration.get('verdict')}`",
        f"- flags: `{', '.join(calibration.get('flags', []))}`",
        "",
        "## Strategy 2 Label Distribution",
        "",
        "```json",
        json.dumps(calibration.get("strategy2_entry_quality_label_counts", {}), indent=2, sort_keys=True),
        "```",
        "",
        "## Strategy 3 Label Distribution",
        "",
        "```json",
        json.dumps(calibration.get("strategy3_entry_quality_label_counts", {}), indent=2, sort_keys=True),
        "```",
        "",
    ]
    if calibration.get("strategy3_known_metrics"):
        lines.extend(["## Strategy 3 Known Metrics", "", "```json", json.dumps(calibration["strategy3_known_metrics"], indent=2), "```", ""])
    if calibration.get("limitation"):
        lines.extend(["## Limitation", "", str(calibration["limitation"]), ""])
    return "\n".join(lines) + "\n"


def render_entry_filter_report(summary: dict[str, Any]) -> str:
    baseline = summary["baseline"]
    calibration = summary["taxonomy_calibration"]
    decision = summary["decision_matrix"]
    best = decision.get("best_usable_filter") or {}
    lines = [
        "# Strategy 2 Entry Filter Research",
        "",
        "Status: research-only. This report does not change Strategy 2, Strategy 3, Adelin, live trading, Telegram, or broker execution.",
        "",
        "## Executive Summary",
        "",
        f"- Strategy 2 trades analyzed: `{summary['strategy2_trades_analyzed']}`",
        f"- baseline PF / WR / AvgR / total_R: `{baseline['PF']}` / `{baseline['WR']}` / `{baseline['AvgR']}` / `{baseline['total_R']}`",
        f"- taxonomy verdict: `{calibration.get('verdict')}`",
        f"- best safe filter: `{best.get('filter_name', 'none')}` n_kept=`{best.get('n_kept')}` PF=`{best.get('kept_PF')}` AvgR=`{best.get('kept_AvgR')}`",
        f"- verdict flags: `{', '.join(decision['verdict_flags'])}`",
        f"- recommended next step: `{decision['next_step']}`",
        "",
        "## Safety Confirmation",
        "",
        "- no live trading",
        "- no Telegram trade alerts",
        "- no broker execution",
        "- no `order_send`",
        "- no Strategy 2 entry-logic changes",
        "- no Strategy 3 logic/cooldown/VWAP/pipeline changes",
        "- no Adelin changes",
        "- no ML/classifier training",
        "",
        "## Input Data",
        "",
        "```json",
        json.dumps(summary["source"], indent=2, sort_keys=True, default=str),
        "```",
        "",
        "## Taxonomy Calibration Against Strategy 3",
        "",
        f"- Strategy 3 source: `{calibration.get('strategy3_source_path')}`",
        f"- Strategy 3 sample size: `{calibration.get('strategy3_sample_size')}`",
        f"- Strategy 3 TRADE_NOW count/rate: `{calibration.get('strategy3_trade_now_count')}` / `{calibration.get('strategy3_trade_now_rate')}`",
        f"- Strategy 3 NO_TRADE count/rate: `{calibration.get('strategy3_no_trade_count')}` / `{calibration.get('strategy3_no_trade_rate')}`",
        f"- Strategy 2 NO_TRADE rate: `{calibration.get('strategy2_no_trade_rate')}`",
        "",
        "Strategy 2 labels:",
        "",
        "```json",
        json.dumps(calibration.get("strategy2_entry_quality_label_counts", {}), indent=2, sort_keys=True),
        "```",
        "",
        "Strategy 3 labels:",
        "",
        "```json",
        json.dumps(calibration.get("strategy3_entry_quality_label_counts", {}), indent=2, sort_keys=True),
        "```",
        "",
        "## Calibration Verdict",
        "",
        f"`{calibration.get('verdict')}`",
        "",
        "## Pre-Entry Feature Audit",
        "",
        f"- feature rows: `{summary['pre_entry_feature_summary']['feature_rows']}`",
        f"- audit rows: `{summary['pre_entry_feature_summary']['audit_rows']}`",
        f"- unsafe audit rows: `{summary['pre_entry_feature_summary']['unsafe_audit_rows']}`",
        "",
        "Only the deliberate post-entry `reaction_state_5_m5` audit rows are unsafe. They are retained to prove leakage detection and are rejected as filter inputs.",
        "",
        "## Leakage Prevention Rules",
        "",
        "- Filter features must have `feature_latest_timestamp <= entry_timestamp`.",
        "- First/second/third M5 closes after entry, MFE/MAE, retest, outcome, and REACTION_ALIVE are forbidden as live-filter inputs.",
        "- `REACTION_ALIVE` may appear only as a target label for correlation notes.",
        "",
        "## Rule-Based Filters Tested",
        "",
        _table(summary["filter_results"], ENTRY_FILTER_RESULT_FIELDS),
        "",
        "## Reaction-Alive Predictability Analysis",
        "",
        _table(summary["reaction_alive_predictor_notes"][:20], REACTION_ALIVE_NOTE_FIELDS),
        "",
        "## Statistical Caveats",
        "",
        "- `n < 10`: insufficient; no conclusion.",
        "- `10 <= n < 30`: weak observation only.",
        "- `n >= 30`: interpretable but not validated.",
        "- No filter is live-ready, deployable, or validated.",
        "",
        "## Decision Matrix",
        "",
        "```json",
        json.dumps(decision, indent=2, sort_keys=True, default=str),
        "```",
        "",
        "## Final Recommendation",
        "",
        decision["next_step"],
    ]
    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any], output_dir: Path, docs_path: Path | None = None) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "taxonomy_calibration_summary_json": str(output_dir / "taxonomy_calibration_summary.json"),
        "taxonomy_calibration_report_md": str(output_dir / "taxonomy_calibration_report.md"),
        "pre_entry_feature_audit_csv": str(output_dir / "pre_entry_feature_audit.csv"),
        "strategy_2_entry_filter_results_csv": str(output_dir / "strategy_2_entry_filter_results.csv"),
        "strategy_2_entry_filter_summary_json": str(output_dir / "strategy_2_entry_filter_summary.json"),
        "strategy_2_entry_filter_report_md": str(output_dir / "strategy_2_entry_filter_report.md"),
        "strategy_2_reaction_alive_predictor_notes_csv": str(output_dir / "strategy_2_reaction_alive_predictor_notes.csv"),
    }
    Path(paths["taxonomy_calibration_summary_json"]).write_text(
        json.dumps(report["taxonomy_calibration"], indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    Path(paths["taxonomy_calibration_report_md"]).write_text(report["taxonomy_report_markdown"], encoding="utf-8")
    _write_csv(Path(paths["pre_entry_feature_audit_csv"]), report["feature_audit_rows"], FEATURE_AUDIT_FIELDS)
    _write_csv(Path(paths["strategy_2_entry_filter_results_csv"]), report["filter_results"], ENTRY_FILTER_RESULT_FIELDS)
    Path(paths["strategy_2_entry_filter_summary_json"]).write_text(
        json.dumps(report["summary"], indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    Path(paths["strategy_2_entry_filter_report_md"]).write_text(report["report_markdown"], encoding="utf-8")
    _write_csv(Path(paths["strategy_2_reaction_alive_predictor_notes_csv"]), report["reaction_alive_notes"], REACTION_ALIVE_NOTE_FIELDS)
    if docs_path is not None:
        docs_path.parent.mkdir(parents=True, exist_ok=True)
        docs_path.write_text(report["report_markdown"], encoding="utf-8")
        paths["docs_markdown"] = str(docs_path)
    return paths


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


__all__ = [
    "ENTRY_FILTER_RESULT_FIELDS",
    "FEATURE_AUDIT_FIELDS",
    "REACTION_ALIVE_NOTE_FIELDS",
    "SAFETY",
    "audit_feature_timestamp",
    "build_entry_filter_research",
    "build_pre_entry_feature_rows",
    "build_taxonomy_calibration",
    "calibration_verdict_from_counts",
    "discover_strategy_3_sample",
    "load_strategy_2_inputs",
    "reaction_alive_predictor_notes",
    "run_simple_filter_tests",
    "write_outputs",
]
