from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from statistics import fmean, median
from typing import Any, Iterable, Literal


Direction = Literal["LONG", "SHORT"]
M5CloseQuality = Literal["GOOD_CLOSE", "ACCEPTABLE_CLOSE", "BAD_CLOSE", "INVALIDATING_CLOSE"]
ReactionState = Literal["REACTION_ALIVE", "REACTION_WEAK", "REACTION_DEAD"]
RetestQuality = Literal["HEALTHY_RETEST", "FAILED_RETEST", "RETEST_PENDING", "NO_RETEST"]
RunnerOpportunity = Literal["STANDARD_TP", "EXTENDED_RUNNER", "LIQUIDITY_MAGNET_RUN", "REVERSAL_RUN"]
EntryQuality = Literal[
    "TRADE_NOW",
    "WAIT_RETEST",
    "NO_TRADE_PRICE_ESCAPED",
    "NO_TRADE_DIRTY_SETUP",
    "NO_TRADE_INSUFFICIENT_TARGET_SPACE",
]
HumanAction = Literal[
    "MOVE_BE",
    "TAKE_PARTIAL",
    "HOLD_RETEST",
    "EXIT_BAD_M5_CLOSE",
    "LET_RUN_TO_LIQUIDITY",
    "REENTER_AFTER_BE_RETEST",
]
BeMode = Literal["hard_be", "m5_confirmed_be", "structural_be"]
RunnerMode = Literal["disabled", "liquidity_target", "structure_trailing"]


M5_CLOSE_QUALITIES = ("GOOD_CLOSE", "ACCEPTABLE_CLOSE", "BAD_CLOSE", "INVALIDATING_CLOSE")
REACTION_STATES = ("REACTION_ALIVE", "REACTION_WEAK", "REACTION_DEAD")
RETEST_QUALITIES = ("HEALTHY_RETEST", "FAILED_RETEST", "RETEST_PENDING", "NO_RETEST")
RUNNER_OPPORTUNITIES = ("STANDARD_TP", "EXTENDED_RUNNER", "LIQUIDITY_MAGNET_RUN", "REVERSAL_RUN")
ENTRY_QUALITIES = (
    "TRADE_NOW",
    "WAIT_RETEST",
    "NO_TRADE_PRICE_ESCAPED",
    "NO_TRADE_DIRTY_SETUP",
    "NO_TRADE_INSUFFICIENT_TARGET_SPACE",
)
HUMAN_ACTIONS = (
    "MOVE_BE",
    "TAKE_PARTIAL",
    "HOLD_RETEST",
    "EXIT_BAD_M5_CLOSE",
    "LET_RUN_TO_LIQUIDITY",
    "REENTER_AFTER_BE_RETEST",
)


HUMAN_LABEL_FIELDS = [
    "human_would_enter",
    "human_would_skip",
    "human_would_hold",
    "human_would_exit",
    "human_would_partial",
    "human_would_let_run",
    "human_would_reenter",
    "human_decision",
    "human_reason",
    "human_label_timestamp",
    "manual_screenshot_before",
    "manual_screenshot_after",
    "manual_screenshot_final",
]

COMPARISON_PLACEHOLDER_FIELDS = [
    "bot_decision",
    "ai_decision",
    "bot_vs_human_match",
    "ai_vs_human_match",
    "error_category",
]

ERROR_CATEGORIES = [
    "entered_but_human_would_skip",
    "exited_but_human_would_hold",
    "held_but_human_would_exit",
    "moved_BE_too_early",
    "failed_to_reenter_after_BE",
    "missed_runner",
    "chased_price",
    "missed_healthy_retest",
    "ignored_bad_m5_close",
]

PER_TRADE_EXPORT_FIELDS = [
    "trade_id",
    "symbol",
    "strategy",
    "direction",
    "signal_timestamp",
    "entry_timestamp",
    "entry_price",
    "stop_loss",
    "original_take_profit",
    "stop_distance_usd",
    "tp_distance_usd",
    "stop_distance_R",
    "be_trigger_usd",
    "partial_trigger_usd",
    "partial_fraction",
    "hit_be_10",
    "hit_partial_15",
    "hit_partial_20",
    "be_timestamp",
    "partial_15_timestamp",
    "partial_20_timestamp",
    "mfe_usd",
    "mae_usd",
    "mfe_R",
    "mae_R",
    "m5_close_quality_sequence",
    "first_bad_m5_close_timestamp",
    "first_invalidating_m5_close_timestamp",
    "reaction_state_sequence",
    "retest_detected",
    "retest_quality",
    "retest_timestamp",
    "retest_depth_usd",
    "retest_depth_R",
    "runner_opportunity",
    "liquidity_target_price",
    "dynamic_target_distance_usd",
    "dynamic_target_R",
    "result_baseline_R",
    "result_hard_be_R",
    "result_m5_confirmed_be_R",
    "result_structural_be_R",
    "result_partial15_R",
    "result_partial20_R",
    "result_exit_bad_m5_R",
    "result_hold_healthy_retest_R",
    "result_runner_liquidity_R",
    "decision_reason_codes",
    "ai_judge_enabled",
    "ai_judge_status",
    "ai_m5_close_quality",
    "ai_reaction_state",
    "ai_retest_quality",
    "ai_runner_opportunity",
    "ai_suggested_action",
    "ai_confidence",
    "ai_reason_codes",
    *HUMAN_LABEL_FIELDS,
]


@dataclass(frozen=True)
class HumanManagementConfig:
    be_trigger_usd: float = 10.0
    partial_triggers_usd: tuple[float, ...] = (15.0, 20.0)
    partial_close_fraction: float = 0.50
    be_buffer_usd: float = 0.0
    be_mode: BeMode = "hard_be"
    runner_mode: RunnerMode = "disabled"
    max_path_bars: int = 480


@dataclass(frozen=True)
class TradeInput:
    trade_id: str
    symbol: str
    strategy: str
    direction: Direction
    signal_timestamp: Any
    entry_timestamp: Any
    entry_price: float
    stop_loss: float
    original_take_profit: float | None = None
    protected_level: float | None = None

    @property
    def stop_distance_usd(self) -> float:
        return abs(float(self.entry_price) - float(self.stop_loss))

    @property
    def tp_distance_usd(self) -> float | None:
        if self.original_take_profit is None:
            return None
        return abs(float(self.original_take_profit) - float(self.entry_price))


@dataclass(frozen=True)
class TradePathResult:
    outcome: str
    exit_timestamp: Any
    exit_price: float | None
    r_multiple: float
    reason_codes: tuple[str, ...] = ()
    partial_trigger_usd: float | None = None
    partial_fraction: float = 0.0
    partial_timestamp: Any = None
    partial_realized_R: float = 0.0
    runner_R: float = 0.0


@dataclass(frozen=True)
class EventState:
    hit_be_10: bool = False
    hit_partial_15: bool = False
    hit_partial_20: bool = False
    be_timestamp: Any = None
    partial_15_timestamp: Any = None
    partial_20_timestamp: Any = None
    mfe_usd: float = 0.0
    mae_usd: float = 0.0
    reason_codes: tuple[str, ...] = ()


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None, ndigits: int = 4) -> float | None:
    return round(value, ndigits) if value is not None else None


def _norm_direction(direction: Any) -> Direction:
    text = str(direction or "").strip().upper()
    if text in {"BUY", "BULL", "BULLISH", "LONG"}:
        return "LONG"
    if text in {"SELL", "BEAR", "BEARISH", "SHORT"}:
        return "SHORT"
    raise ValueError(f"unsupported trade direction: {direction!r}")


def _as_records(candles: Any) -> list[dict[str, Any]]:
    if candles is None:
        return []
    if isinstance(candles, list):
        return [dict(row) for row in candles]
    if isinstance(candles, tuple):
        return [dict(row) for row in candles]
    to_dict = getattr(candles, "to_dict", None)
    if callable(to_dict):
        try:
            return [dict(row) for row in candles.to_dict("records")]
        except TypeError:
            pass
    return [dict(row) for row in candles]


def _pick(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    lowered = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


def _candle(row: dict[str, Any]) -> dict[str, Any]:
    open_ = _to_float(_pick(row, "open", "o"))
    high = _to_float(_pick(row, "high", "h"))
    low = _to_float(_pick(row, "low", "l"))
    close = _to_float(_pick(row, "close", "c"))
    return {
        "time": _pick(row, "time", "timestamp", "entry_time", "datetime", "date"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "raw": row,
    }


def _clean_candles(candles: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in _as_records(candles):
        c = _candle(row)
        if c["open"] is None or c["high"] is None or c["low"] is None or c["close"] is None:
            continue
        out.append(c)
    return out


def _timestamp(value: Any) -> Any:
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _favorable_distance(direction: Direction, entry: float, high: float, low: float) -> float:
    if direction == "LONG":
        return max(0.0, high - entry)
    return max(0.0, entry - low)


def _adverse_distance(direction: Direction, entry: float, high: float, low: float) -> float:
    if direction == "LONG":
        return max(0.0, entry - low)
    return max(0.0, high - entry)


def _price_r(direction: Direction, entry: float, price: float, risk: float) -> float:
    if risk <= 0:
        return 0.0
    if direction == "LONG":
        return (price - entry) / risk
    return (entry - price) / risk


def _profit_factor(values: Iterable[float]) -> float | str | None:
    values = list(values)
    if not values:
        return None
    wins = sum(v for v in values if v > 0)
    losses = abs(sum(v for v in values if v < 0))
    if losses == 0:
        return "inf" if wins > 0 else 0.0
    return round(wins / losses, 4)


def _max_drawdown(values: Iterable[float]) -> float:
    peak = 0.0
    equity = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return round(max_dd, 4)


def metric_block_from_r(values: Iterable[float]) -> dict[str, Any]:
    r_values = [float(v) for v in values if v is not None]
    wins = [v for v in r_values if v > 0]
    losses = [v for v in r_values if v < 0]
    return {
        "trades": len(r_values),
        "PF": _profit_factor(r_values),
        "WR": round(len(wins) / len(r_values), 4) if r_values else 0.0,
        "AvgR": round(fmean(r_values), 4) if r_values else None,
        "MedianR": round(median(r_values), 4) if r_values else None,
        "total_R": round(sum(r_values), 4) if r_values else 0.0,
        "MaxDD": _max_drawdown(r_values),
        "average_win_R": round(fmean(wins), 4) if wins else None,
        "average_loss_R": round(fmean(losses), 4) if losses else None,
        "average_RR": round((fmean(wins) / abs(fmean(losses))), 4) if wins and losses else None,
    }


def evaluate_m5_close_quality(
    candle: dict[str, Any],
    direction: Direction | str,
    *,
    previous_candle: dict[str, Any] | None = None,
    entry_price: float | None = None,
    key_level: float | None = None,
    invalidation_level: float | None = None,
    expected_displacement_usd: float | None = None,
    vwap: float | None = None,
) -> dict[str, Any]:
    """Classify a closed M5 candle for research-only management logging."""

    side = _norm_direction(direction)
    c = _candle(candle)
    if None in (c["open"], c["high"], c["low"], c["close"]):
        return {
            "quality": "BAD_CLOSE",
            "score": -2.0,
            "reason_codes": ["missing_candle_ohlc"],
        }

    open_ = float(c["open"])
    high = float(c["high"])
    low = float(c["low"])
    close = float(c["close"])
    rng = max(high - low, 0.0)
    body = abs(close - open_)
    body_ratio = body / rng if rng > 0 else 0.0
    close_location = (close - low) / rng if rng > 0 else 0.5
    upper_wick_ratio = (high - max(open_, close)) / rng if rng > 0 else 0.0
    lower_wick_ratio = (min(open_, close) - low) / rng if rng > 0 else 0.0
    reason_codes: list[str] = []
    score = 0.0

    if rng <= 0:
        reason_codes.append("zero_range_candle")
        score -= 1.0

    if side == "LONG":
        if invalidation_level is not None and close < float(invalidation_level):
            reason_codes.append("close_below_invalidation_level")
            return {"quality": "INVALIDATING_CLOSE", "score": -5.0, "reason_codes": reason_codes}
        if key_level is not None and close < float(key_level):
            reason_codes.append("close_below_key_recovered_level")
            score -= 2.0
        if entry_price is not None and close < float(entry_price):
            reason_codes.append("close_below_entry_after_reaction")
            score -= 1.75
        if vwap is not None and close < float(vwap):
            reason_codes.append("close_below_vwap_or_band")
            score -= 0.75
        if close > open_:
            reason_codes.append("directional_bullish_close")
            score += 1.0
        else:
            reason_codes.append("adverse_bearish_close")
            score -= 1.0
        if close_location >= 0.72:
            reason_codes.append("close_near_high")
            score += 1.0
        elif close_location <= 0.35:
            reason_codes.append("weak_close_location")
            score -= 1.0
        if upper_wick_ratio >= 0.45:
            reason_codes.append("large_upper_wick_rejection")
            score -= 1.25
        if lower_wick_ratio >= 0.35 and close >= open_:
            reason_codes.append("lower_wick_absorption")
            score += 0.5
        if expected_displacement_usd and entry_price is not None and high >= float(entry_price) + float(expected_displacement_usd):
            if close < float(entry_price) + float(expected_displacement_usd) * 0.35:
                reason_codes.append("displacement_fully_absorbed")
                score -= 1.5
            else:
                reason_codes.append("displacement_retained")
                score += 0.75
    else:
        if invalidation_level is not None and close > float(invalidation_level):
            reason_codes.append("close_above_invalidation_level")
            return {"quality": "INVALIDATING_CLOSE", "score": -5.0, "reason_codes": reason_codes}
        if key_level is not None and close > float(key_level):
            reason_codes.append("close_above_key_lost_level")
            score -= 2.0
        if entry_price is not None and close > float(entry_price):
            reason_codes.append("close_above_entry_after_reaction")
            score -= 1.75
        if vwap is not None and close > float(vwap):
            reason_codes.append("close_above_vwap_or_band")
            score -= 0.75
        if close < open_:
            reason_codes.append("directional_bearish_close")
            score += 1.0
        else:
            reason_codes.append("adverse_bullish_close")
            score -= 1.0
        if close_location <= 0.28:
            reason_codes.append("close_near_low")
            score += 1.0
        elif close_location >= 0.65:
            reason_codes.append("weak_close_location")
            score -= 1.0
        if lower_wick_ratio >= 0.45:
            reason_codes.append("large_lower_wick_rejection")
            score -= 1.25
        if upper_wick_ratio >= 0.35 and close <= open_:
            reason_codes.append("upper_wick_absorption")
            score += 0.5
        if expected_displacement_usd and entry_price is not None and low <= float(entry_price) - float(expected_displacement_usd):
            if close > float(entry_price) - float(expected_displacement_usd) * 0.35:
                reason_codes.append("displacement_fully_absorbed")
                score -= 1.5
            else:
                reason_codes.append("displacement_retained")
                score += 0.75

    if body_ratio < 0.22:
        reason_codes.append("weak_body_after_expected_displacement")
        score -= 0.75
    elif body_ratio >= 0.55:
        reason_codes.append("strong_body")
        score += 0.5

    if previous_candle is not None:
        prev = _candle(previous_candle)
        if None not in (prev["open"], prev["high"], prev["low"], prev["close"]):
            prev_open = float(prev["open"])
            prev_high = float(prev["high"])
            prev_low = float(prev["low"])
            prev_close = float(prev["close"])
            if side == "LONG":
                if high > prev_high and close <= prev_high:
                    reason_codes.append("close_back_inside_prior_range")
                    score -= 1.0
                if open_ > prev_close and close < prev_open:
                    reason_codes.append("bearish_engulfing_against_trade")
                    score -= 1.5
                if close > prev_close:
                    reason_codes.append("follow_through_after_signal")
                    score += 0.5
            else:
                if low < prev_low and close >= prev_low:
                    reason_codes.append("close_back_inside_prior_range")
                    score -= 1.0
                if open_ < prev_close and close > prev_open:
                    reason_codes.append("bullish_engulfing_against_trade")
                    score -= 1.5
                if close < prev_close:
                    reason_codes.append("follow_through_after_signal")
                    score += 0.5

    if score >= 2.0:
        quality: M5CloseQuality = "GOOD_CLOSE"
    elif score >= 0.0:
        quality = "ACCEPTABLE_CLOSE"
    elif score <= -3.0:
        quality = "INVALIDATING_CLOSE" if any("invalidation" in code or "displacement_fully_absorbed" in code for code in reason_codes) else "BAD_CLOSE"
    else:
        quality = "BAD_CLOSE"

    return {
        "quality": quality,
        "score": round(score, 4),
        "reason_codes": reason_codes or ["neutral_close"],
        "features": {
            "close_location": round(close_location, 4),
            "body_to_range_ratio": round(body_ratio, 4),
            "upper_wick_ratio": round(upper_wick_ratio, 4),
            "lower_wick_ratio": round(lower_wick_ratio, 4),
        },
    }


def evaluate_reaction_state(
    candles: Any,
    direction: Direction | str,
    entry_price: float,
    *,
    stop_loss: float | None = None,
    lookahead_candles: int = 3,
    key_level: float | None = None,
) -> dict[str, Any]:
    """Evaluate whether early post-entry reaction is alive, weak, or dead."""

    side = _norm_direction(direction)
    frame = _clean_candles(candles)[:lookahead_candles]
    if not frame:
        return {
            "reaction_state": "REACTION_WEAK",
            "mfe_usd": 0.0,
            "mae_usd": 0.0,
            "mfe_R": None,
            "mae_R": None,
            "reason_codes": ["missing_reaction_candles"],
        }

    entry = float(entry_price)
    risk = abs(entry - float(stop_loss)) if stop_loss is not None else None
    mfe = max(_favorable_distance(side, entry, float(c["high"]), float(c["low"])) for c in frame)
    mae = max(_adverse_distance(side, entry, float(c["high"]), float(c["low"])) for c in frame)
    closes = [float(c["close"]) for c in frame]
    highs = [float(c["high"]) for c in frame]
    lows = [float(c["low"]) for c in frame]
    last_close = closes[-1]
    reason_codes: list[str] = []
    score = 0.0

    if side == "LONG":
        if mfe >= 2.0 or (risk and mfe >= 0.5 * risk):
            reason_codes.append("favorable_acceptance")
            score += 1.25
        if last_close > entry:
            reason_codes.append("accepting_above_entry")
            score += 0.75
        if len(lows) >= 2 and lows[-1] >= min(lows[:-1]):
            reason_codes.append("higher_low_preserved")
            score += 0.5
        if len(closes) >= 2 and closes[-1] > closes[0]:
            reason_codes.append("follow_through_continues")
            score += 0.75
        if mfe <= max(1.0, 0.25 * risk) if risk else mfe <= 1.0:
            reason_codes.append("no_follow_through")
            score -= 1.0
        if last_close <= entry and mfe > 0:
            reason_codes.append("displacement_absorbed")
            score -= 1.5
        if key_level is not None and last_close < float(key_level):
            reason_codes.append("close_back_inside_range")
            score -= 1.0
        if len(closes) >= 3 and closes[-1] < closes[-2] < closes[-3]:
            reason_codes.append("adverse_close_sequence")
            score -= 1.0
        if mae > mfe:
            reason_codes.append("reaction_stalled")
            score -= 0.75
    else:
        if mfe >= 2.0 or (risk and mfe >= 0.5 * risk):
            reason_codes.append("favorable_acceptance")
            score += 1.25
        if last_close < entry:
            reason_codes.append("accepting_below_entry")
            score += 0.75
        if len(highs) >= 2 and highs[-1] <= max(highs[:-1]):
            reason_codes.append("lower_high_preserved")
            score += 0.5
        if len(closes) >= 2 and closes[-1] < closes[0]:
            reason_codes.append("follow_through_continues")
            score += 0.75
        if mfe <= max(1.0, 0.25 * risk) if risk else mfe <= 1.0:
            reason_codes.append("no_follow_through")
            score -= 1.0
        if last_close >= entry and mfe > 0:
            reason_codes.append("displacement_absorbed")
            score -= 1.5
        if key_level is not None and last_close > float(key_level):
            reason_codes.append("close_back_inside_range")
            score -= 1.0
        if len(closes) >= 3 and closes[-1] > closes[-2] > closes[-3]:
            reason_codes.append("adverse_close_sequence")
            score -= 1.0
        if mae > mfe:
            reason_codes.append("reaction_stalled")
            score -= 0.75

    if any(code in reason_codes for code in ("displacement_absorbed", "adverse_close_sequence")) and score <= -1.0:
        state: ReactionState = "REACTION_DEAD"
    elif score >= 1.5:
        state = "REACTION_ALIVE"
    else:
        state = "REACTION_WEAK"

    return {
        "reaction_state": state,
        "score": round(score, 4),
        "mfe_usd": round(mfe, 4),
        "mae_usd": round(mae, 4),
        "mfe_R": round(mfe / risk, 4) if risk else None,
        "mae_R": round(mae / risk, 4) if risk else None,
        "reason_codes": reason_codes or ["reaction_neutral"],
    }


def evaluate_retest_quality(
    candles: Any,
    direction: Direction | str,
    entry_price: float,
    *,
    stop_loss: float | None = None,
    be_trigger_usd: float = 10.0,
    key_level: float | None = None,
    fvg_level: float | None = None,
    vwap: float | None = None,
    tolerance_usd: float = 0.25,
) -> dict[str, Any]:
    """Classify a retest after favorable movement, without assuming entry retests are bad."""

    side = _norm_direction(direction)
    frame = _clean_candles(candles)
    if not frame:
        return {
            "retest_quality": "NO_RETEST",
            "retest_detected": False,
            "reason_codes": ["missing_retest_candles"],
        }

    entry = float(entry_price)
    risk = abs(entry - float(stop_loss)) if stop_loss is not None else None
    retest_level = float(key_level if key_level is not None else fvg_level if fvg_level is not None else vwap if vwap is not None else entry)
    favorable_seen = False
    retest_index: int | None = None
    depth = 0.0
    reason_codes: list[str] = []

    for idx, candle in enumerate(frame):
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
        just_triggered = False
        if not favorable_seen and _favorable_distance(side, entry, high, low) >= be_trigger_usd:
            favorable_seen = True
            just_triggered = True
        if not favorable_seen:
            continue
        if just_triggered:
            continue
        if side == "LONG":
            touched = low <= retest_level + tolerance_usd
            if touched:
                retest_index = idx
                depth = max(0.0, entry + be_trigger_usd - low)
                reason_codes.append("retest_to_entry" if abs(retest_level - entry) <= tolerance_usd else "retest_to_key_level")
                if fvg_level is not None and abs(retest_level - float(fvg_level)) <= tolerance_usd:
                    reason_codes.append("retest_to_fvg")
                if vwap is not None and abs(retest_level - float(vwap)) <= tolerance_usd:
                    reason_codes.append("retest_to_vwap")
                if stop_loss is not None and close < float(stop_loss):
                    reason_codes.append("close_breaks_invalidation")
                    return _retest_result("FAILED_RETEST", True, candle, depth, risk, reason_codes)
                if close < retest_level - tolerance_usd:
                    reason_codes.append("close_breaks_level")
                    return _retest_result("FAILED_RETEST", True, candle, depth, risk, reason_codes)
                reason_codes.append("close_holds_level")
                if low < retest_level and close > retest_level:
                    reason_codes.append("wick_absorption")
                break
        else:
            touched = high >= retest_level - tolerance_usd
            if touched:
                retest_index = idx
                depth = max(0.0, entry - be_trigger_usd - high)
                reason_codes.append("retest_to_entry" if abs(retest_level - entry) <= tolerance_usd else "retest_to_key_level")
                if fvg_level is not None and abs(retest_level - float(fvg_level)) <= tolerance_usd:
                    reason_codes.append("retest_to_fvg")
                if vwap is not None and abs(retest_level - float(vwap)) <= tolerance_usd:
                    reason_codes.append("retest_to_vwap")
                if stop_loss is not None and close > float(stop_loss):
                    reason_codes.append("close_breaks_invalidation")
                    return _retest_result("FAILED_RETEST", True, candle, depth, risk, reason_codes)
                if close > retest_level + tolerance_usd:
                    reason_codes.append("close_breaks_level")
                    return _retest_result("FAILED_RETEST", True, candle, depth, risk, reason_codes)
                reason_codes.append("close_holds_level")
                if high > retest_level and close < retest_level:
                    reason_codes.append("wick_absorption")
                break

    if not favorable_seen:
        return {
            "retest_quality": "NO_RETEST",
            "retest_detected": False,
            "reason_codes": ["be_trigger_not_reached_before_retest"],
        }
    if retest_index is None:
        return {
            "retest_quality": "NO_RETEST",
            "retest_detected": False,
            "reason_codes": ["no_return_to_retest_level_after_favorable_move"],
        }

    confirm = frame[retest_index + 1] if retest_index + 1 < len(frame) else None
    retest_candle = frame[retest_index]
    if confirm is None:
        reason_codes.append("awaiting_next_candle_confirmation")
        return _retest_result("RETEST_PENDING", True, retest_candle, depth, risk, reason_codes)

    if side == "LONG":
        if float(confirm["close"]) > float(retest_candle["high"]):
            reason_codes.append("continuation_confirmed")
            if float(retest_candle["low"]) <= entry <= float(retest_candle["high"]):
                reason_codes.append("be_hit_then_continuation")
            return _retest_result("HEALTHY_RETEST", True, retest_candle, depth, risk, reason_codes)
        if float(confirm["close"]) < retest_level:
            reason_codes.append("retest_failed_no_reaction")
            return _retest_result("FAILED_RETEST", True, retest_candle, depth, risk, reason_codes)
    else:
        if float(confirm["close"]) < float(retest_candle["low"]):
            reason_codes.append("continuation_confirmed")
            if float(retest_candle["low"]) <= entry <= float(retest_candle["high"]):
                reason_codes.append("be_hit_then_continuation")
            return _retest_result("HEALTHY_RETEST", True, retest_candle, depth, risk, reason_codes)
        if float(confirm["close"]) > retest_level:
            reason_codes.append("retest_failed_no_reaction")
            return _retest_result("FAILED_RETEST", True, retest_candle, depth, risk, reason_codes)

    reason_codes.append("confirmation_not_decisive")
    return _retest_result("RETEST_PENDING", True, retest_candle, depth, risk, reason_codes)


def _retest_result(
    quality: RetestQuality,
    detected: bool,
    candle: dict[str, Any],
    depth: float,
    risk: float | None,
    reason_codes: list[str],
) -> dict[str, Any]:
    return {
        "retest_quality": quality,
        "retest_detected": detected,
        "retest_timestamp": _timestamp(candle.get("time")),
        "retest_depth_usd": round(depth, 4),
        "retest_depth_R": round(depth / risk, 4) if risk else None,
        "reason_codes": reason_codes,
    }


def detect_runner_opportunity(
    direction: Direction | str,
    entry_price: float,
    stop_loss: float,
    *,
    original_take_profit: float | None = None,
    current_price: float | None = None,
    liquidity_levels: Iterable[float] | None = None,
    internal_liquidity: Iterable[float] | None = None,
    external_liquidity: Iterable[float] | None = None,
    htf_levels: Iterable[float] | None = None,
    vwap_sigma_targets: Iterable[float] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Detect whether a final target should remain standard or become a dynamic runner."""

    side = _norm_direction(direction)
    entry = float(entry_price)
    risk = abs(entry - float(stop_loss))
    current = float(current_price if current_price is not None else entry)
    candidates: list[tuple[float, str]] = []
    context = context or {}

    def add(levels: Iterable[float] | None, reason: str) -> None:
        if levels is None:
            return
        for value in levels:
            level = _to_float(value)
            if level is None:
                continue
            if side == "LONG" and level > max(entry, current):
                candidates.append((float(level), reason))
            if side == "SHORT" and level < min(entry, current):
                candidates.append((float(level), reason))

    add(liquidity_levels, "clean_liquidity_magnet")
    add(internal_liquidity, "nearest_internal_liquidity")
    add(external_liquidity, "nearest_external_liquidity")
    add(htf_levels, "htf_high_low")
    add(vwap_sigma_targets, "vwap_sigma_target")

    blockers: list[str] = []
    if risk <= 0:
        return {
            "runner_opportunity": "STANDARD_TP",
            "liquidity_target_price": None,
            "dynamic_target_distance_usd": None,
            "dynamic_target_R": None,
            "target_reason_codes": [],
            "target_blockers": ["invalid_stop_distance"],
        }
    if not candidates:
        return {
            "runner_opportunity": "STANDARD_TP",
            "liquidity_target_price": None,
            "dynamic_target_distance_usd": None,
            "dynamic_target_R": None,
            "target_reason_codes": [],
            "target_blockers": ["no_dynamic_target_data"],
        }

    if side == "LONG":
        target, reason = min(candidates, key=lambda item: item[0])
        distance = target - entry
        tp_distance = float(original_take_profit) - entry if original_take_profit is not None else 0.0
    else:
        target, reason = max(candidates, key=lambda item: item[0])
        distance = entry - target
        tp_distance = entry - float(original_take_profit) if original_take_profit is not None else 0.0

    if distance <= 0:
        blockers.append("target_not_in_trade_direction")
    if distance < risk:
        blockers.append("target_space_insufficient")
    if original_take_profit is not None and distance <= tp_distance:
        blockers.append("target_not_beyond_standard_tp")
    if context.get("major_obstacle_before_target"):
        blockers.append("major_obstacle_before_target")
    if context.get("m5_m15_continuation_quality") == "bad":
        blockers.append("continuation_quality_bad")

    reason_codes = [reason]
    if context.get("trend_continuation"):
        reason_codes.append("trend_context_supports_runner")
    if context.get("reversal_context"):
        reason_codes.append("reversal_context_supports_runner")
    if not blockers and original_take_profit is not None and distance > max(tp_distance, 0.0):
        reason_codes.append("target_extends_beyond_fixed_tp")

    if blockers:
        opportunity: RunnerOpportunity = "STANDARD_TP"
    elif context.get("reversal_context"):
        opportunity = "REVERSAL_RUN"
    elif reason in {"clean_liquidity_magnet", "nearest_external_liquidity", "nearest_internal_liquidity", "htf_high_low"}:
        opportunity = "LIQUIDITY_MAGNET_RUN"
    else:
        opportunity = "EXTENDED_RUNNER"

    return {
        "runner_opportunity": opportunity,
        "liquidity_target_price": round(target, 4),
        "dynamic_target_distance_usd": round(distance, 4),
        "dynamic_target_R": round(distance / risk, 4),
        "target_reason_codes": reason_codes,
        "target_blockers": blockers,
    }


def evaluate_entry_quality(
    direction: Direction | str,
    ideal_entry_price: float,
    current_price: float,
    *,
    stop_loss: float | None = None,
    target_price: float | None = None,
    be_trigger_usd: float = 10.0,
    retest_available: bool = False,
    retest_timestamp: Any = None,
    dirty_setup_reason_codes: Iterable[str] | None = None,
    spread: float | None = None,
) -> dict[str, Any]:
    side = _norm_direction(direction)
    ideal = float(ideal_entry_price)
    current = float(current_price)
    risk = abs(ideal - float(stop_loss)) if stop_loss is not None else None
    dirty = [str(code) for code in (dirty_setup_reason_codes or []) if code]
    if side == "LONG":
        escape_usd = current - ideal
        target_space_usd = float(target_price) - current if target_price is not None else None
    else:
        escape_usd = ideal - current
        target_space_usd = current - float(target_price) if target_price is not None else None
    escape_R = escape_usd / risk if risk else None
    target_space_R = target_space_usd / risk if risk and target_space_usd is not None else None
    reason_codes: list[str] = []

    if dirty:
        reason_codes.extend(dirty)
        label: EntryQuality = "NO_TRADE_DIRTY_SETUP"
    elif escape_usd >= be_trigger_usd:
        reason_codes.append("price_already_beyond_be_trigger")
        label = "NO_TRADE_PRICE_ESCAPED"
    elif target_space_usd is not None and target_space_usd <= 0:
        reason_codes.append("no_target_space_after_current_price")
        label = "NO_TRADE_INSUFFICIENT_TARGET_SPACE"
    elif target_space_R is not None and target_space_R < 1.0:
        reason_codes.append("target_space_lt_1R")
        label = "NO_TRADE_INSUFFICIENT_TARGET_SPACE"
    elif retest_available and escape_usd > max(1.0, 0.25 * risk) if risk else retest_available and escape_usd > 1.0:
        reason_codes.append("price_extended_wait_for_retest")
        label = "WAIT_RETEST"
    else:
        reason_codes.append("entry_price_still_actionable")
        label = "TRADE_NOW"

    return {
        "entry_quality": label,
        "price_escape_usd": round(escape_usd, 4),
        "price_escape_R": round(escape_R, 4) if escape_R is not None else None,
        "distance_from_ideal_entry": round(abs(current - ideal), 4),
        "retest_available": bool(retest_available),
        "retest_timestamp": _timestamp(retest_timestamp),
        "has_clean_target_space": label != "NO_TRADE_INSUFFICIENT_TARGET_SPACE",
        "target_space_usd": round(target_space_usd, 4) if target_space_usd is not None else None,
        "target_space_R": round(target_space_R, 4) if target_space_R is not None else None,
        "dirty_setup_reason_codes": dirty,
        "spread": spread,
        "current_price_relative_to_be_trigger": round(escape_usd - be_trigger_usd, 4),
        "reason_codes": reason_codes,
    }


def collect_path_event_state(
    trade: TradeInput,
    candles: Any,
    config: HumanManagementConfig = HumanManagementConfig(),
) -> EventState:
    frame = _clean_candles(candles)[: config.max_path_bars]
    if not frame:
        return EventState(reason_codes=("missing_m1_path_data",))
    side = _norm_direction(trade.direction)
    entry = float(trade.entry_price)
    mfe = 0.0
    mae = 0.0
    hit_be = False
    be_ts = None
    partial_hits: dict[float, Any] = {}
    reasons: list[str] = []
    for candle in frame:
        high = float(candle["high"])
        low = float(candle["low"])
        when = _timestamp(candle.get("time"))
        mfe = max(mfe, _favorable_distance(side, entry, high, low))
        mae = max(mae, _adverse_distance(side, entry, high, low))
        if not hit_be and mfe >= config.be_trigger_usd:
            hit_be = True
            be_ts = when
            reasons.append("MOVE_BE")
        for trigger in config.partial_triggers_usd:
            if trigger not in partial_hits and _favorable_distance(side, entry, high, low) >= trigger:
                partial_hits[trigger] = when
                reasons.append("TAKE_PARTIAL")
    return EventState(
        hit_be_10=hit_be,
        hit_partial_15=15.0 in partial_hits,
        hit_partial_20=20.0 in partial_hits,
        be_timestamp=be_ts,
        partial_15_timestamp=partial_hits.get(15.0),
        partial_20_timestamp=partial_hits.get(20.0),
        mfe_usd=round(mfe, 4),
        mae_usd=round(mae, 4),
        reason_codes=tuple(reasons),
    )


def simulate_trade_path_variant(
    trade: TradeInput,
    candles: Any,
    *,
    config: HumanManagementConfig = HumanManagementConfig(),
    variant: str = "baseline",
    m5_candles: Any = None,
    runner_target: float | None = None,
) -> TradePathResult:
    """Report-only intratrade path simulation for management variants."""

    frame = _clean_candles(candles)[: config.max_path_bars]
    if not frame or trade.stop_distance_usd <= 0:
        return TradePathResult(
            outcome="NO_PATH_DATA",
            exit_timestamp=None,
            exit_price=None,
            r_multiple=0.0,
            reason_codes=("missing_m1_path_data",),
        )

    side = _norm_direction(trade.direction)
    entry = float(trade.entry_price)
    stop = float(trade.stop_loss)
    risk = trade.stop_distance_usd
    tp = float(trade.original_take_profit) if trade.original_take_profit is not None else None
    if variant == "runner_liquidity" and runner_target is not None:
        tp = float(runner_target)
    current_stop = stop
    be_moved = False
    partial_done = False
    partial_r = 0.0
    partial_trigger = 15.0 if variant == "partial15" else 20.0 if variant == "partial20" else None
    partial_fraction = config.partial_close_fraction if partial_trigger is not None or variant in {"exit_bad_m5", "hold_healthy_retest", "runner_liquidity"} else 0.0
    if variant in {"exit_bad_m5", "hold_healthy_retest", "runner_liquidity"}:
        partial_trigger = min(config.partial_triggers_usd) if config.partial_triggers_usd else 15.0
    reason_codes: list[str] = []
    last_close = float(frame[0]["close"])
    last_time = _timestamp(frame[0].get("time"))
    m5_quality_by_time = _m5_quality_sequence(m5_candles, side, entry_price=entry, stop_loss=trade.stop_loss)
    m5_iter = iter(m5_quality_by_time)
    next_m5 = next(m5_iter, None)

    for candle in frame:
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
        when = _timestamp(candle.get("time"))
        last_close = close
        last_time = when

        if next_m5 is not None:
            quality, q_time = next_m5
            if variant == "exit_bad_m5" and quality == "INVALIDATING_CLOSE":
                reason_codes.append("EXIT_BAD_M5_CLOSE")
                return TradePathResult(
                    outcome="EXIT_BAD_M5_CLOSE",
                    exit_timestamp=q_time,
                    exit_price=close,
                    r_multiple=round(_price_r(side, entry, close, risk), 4),
                    reason_codes=tuple(reason_codes),
                )
            next_m5 = next(m5_iter, None)

        target_hit = _target_hit(side, high, low, tp)
        partial_hit = partial_trigger is not None and _favorable_distance(side, entry, high, low) >= partial_trigger
        be_hit = _favorable_distance(side, entry, high, low) >= config.be_trigger_usd
        sl_hit = _stop_hit(side, high, low, current_stop)

        if target_hit and tp is not None:
            full_r = _price_r(side, entry, tp, risk)
            total_r = partial_r + (1.0 - partial_fraction if partial_done else 1.0) * full_r
            return TradePathResult(
                outcome="TP",
                exit_timestamp=when,
                exit_price=tp,
                r_multiple=round(total_r, 4),
                reason_codes=tuple(reason_codes or ["STANDARD_TP"]),
                partial_trigger_usd=partial_trigger,
                partial_fraction=partial_fraction if partial_done else 0.0,
                partial_realized_R=round(partial_r, 4),
                runner_R=round(full_r, 4),
            )

        if variant != "baseline" and not be_moved and be_hit:
            be_price, be_reason = _be_stop_for_mode(trade, config, m5_candles=m5_candles)
            current_stop = be_price
            be_moved = True
            reason_codes.append(be_reason)

        if partial_hit and not partial_done and partial_trigger is not None:
            partial_done = True
            partial_r = partial_fraction * (partial_trigger / risk)
            reason_codes.append("TAKE_PARTIAL")

        if sl_hit:
            if variant == "hold_healthy_retest" and be_moved:
                retest = evaluate_retest_quality(frame, side, entry, stop_loss=trade.stop_loss, be_trigger_usd=config.be_trigger_usd)
                if retest["retest_quality"] == "HEALTHY_RETEST":
                    reason_codes.append("HOLD_RETEST")
                    continue
            stop_r = _price_r(side, entry, current_stop, risk)
            total_r = partial_r + (1.0 - partial_fraction if partial_done else 1.0) * stop_r
            outcome = "BE" if be_moved and abs(stop_r) <= 0.0001 else "SL"
            return TradePathResult(
                outcome=outcome,
                exit_timestamp=when,
                exit_price=current_stop,
                r_multiple=round(total_r, 4),
                reason_codes=tuple(reason_codes or [outcome]),
                partial_trigger_usd=partial_trigger,
                partial_fraction=partial_fraction if partial_done else 0.0,
                partial_timestamp=when if partial_done else None,
                partial_realized_R=round(partial_r, 4),
            )

    close_r = _price_r(side, entry, last_close, risk)
    total_r = partial_r + (1.0 - partial_fraction if partial_done else 1.0) * close_r
    return TradePathResult(
        outcome="TIMEOUT_CLOSE",
        exit_timestamp=last_time,
        exit_price=last_close,
        r_multiple=round(total_r, 4),
        reason_codes=tuple(reason_codes or ["path_ended_without_target_or_stop"]),
        partial_trigger_usd=partial_trigger,
        partial_fraction=partial_fraction if partial_done else 0.0,
        partial_realized_R=round(partial_r, 4),
        runner_R=round(close_r, 4),
    )


def _target_hit(side: Direction, high: float, low: float, target: float | None) -> bool:
    if target is None:
        return False
    if side == "LONG":
        return high >= target
    return low <= target


def _stop_hit(side: Direction, high: float, low: float, stop: float) -> bool:
    if side == "LONG":
        return low <= stop
    return high >= stop


def _be_stop_for_mode(trade: TradeInput, config: HumanManagementConfig, *, m5_candles: Any = None) -> tuple[float, str]:
    side = _norm_direction(trade.direction)
    entry = float(trade.entry_price)
    if config.be_mode == "structural_be":
        if trade.protected_level is not None:
            return float(trade.protected_level), "MOVE_BE_structural_protected_level"
        return _hard_be_stop(side, entry, config.be_buffer_usd), "MOVE_BE_structural_fallback_to_hard_be"
    if config.be_mode == "m5_confirmed_be":
        sequence = _m5_quality_sequence(m5_candles, side, entry_price=entry, stop_loss=trade.stop_loss)
        good = any(item[0] in {"GOOD_CLOSE", "ACCEPTABLE_CLOSE"} for item in sequence)
        if good:
            return _hard_be_stop(side, entry, config.be_buffer_usd), "MOVE_BE_m5_confirmed"
        return _hard_be_stop(side, entry, config.be_buffer_usd), "MOVE_BE_m5_missing_or_unconfirmed_fallback_to_hard_be"
    return _hard_be_stop(side, entry, config.be_buffer_usd), "MOVE_BE_hard_be"


def _hard_be_stop(side: Direction, entry: float, buffer_usd: float) -> float:
    if side == "LONG":
        return entry + float(buffer_usd)
    return entry - float(buffer_usd)


def _m5_quality_sequence(
    m5_candles: Any,
    side: Direction,
    *,
    entry_price: float,
    stop_loss: float | None = None,
) -> list[tuple[str, Any]]:
    frame = _clean_candles(m5_candles)
    sequence: list[tuple[str, Any]] = []
    previous: dict[str, Any] | None = None
    for candle in frame:
        result = evaluate_m5_close_quality(
            candle["raw"],
            side,
            previous_candle=previous["raw"] if previous else None,
            entry_price=entry_price,
            invalidation_level=stop_loss,
        )
        sequence.append((str(result["quality"]), _timestamp(candle.get("time"))))
        previous = candle
    return sequence


def build_trade_management_record(
    trade: TradeInput,
    *,
    m1_candles: Any = None,
    m5_candles: Any = None,
    config: HumanManagementConfig = HumanManagementConfig(),
    runner_context: dict[str, Any] | None = None,
    ai_judge_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    side = _norm_direction(trade.direction)
    event_state = collect_path_event_state(trade, m1_candles, config)
    risk = trade.stop_distance_usd
    m5_sequence = _m5_quality_sequence(m5_candles, side, entry_price=trade.entry_price, stop_loss=trade.stop_loss)
    reaction = evaluate_reaction_state(m5_candles, side, trade.entry_price, stop_loss=trade.stop_loss)
    retest_context = m5_candles if _clean_candles(m5_candles) else m1_candles
    retest = evaluate_retest_quality(retest_context, side, trade.entry_price, stop_loss=trade.stop_loss, be_trigger_usd=config.be_trigger_usd)
    runner = detect_runner_opportunity(
        side,
        trade.entry_price,
        trade.stop_loss,
        original_take_profit=trade.original_take_profit,
        current_price=trade.entry_price,
        **(runner_context or {}),
    )
    runner_target = runner.get("liquidity_target_price") if runner["runner_opportunity"] != "STANDARD_TP" else None

    baseline = simulate_trade_path_variant(trade, m1_candles, config=config, variant="baseline")
    hard_be = simulate_trade_path_variant(trade, m1_candles, config=HumanManagementConfig(**{**config.__dict__, "be_mode": "hard_be"}), variant="hard_be")
    m5_be = simulate_trade_path_variant(trade, m1_candles, config=HumanManagementConfig(**{**config.__dict__, "be_mode": "m5_confirmed_be"}), variant="hard_be", m5_candles=m5_candles)
    structural_be = simulate_trade_path_variant(trade, m1_candles, config=HumanManagementConfig(**{**config.__dict__, "be_mode": "structural_be"}), variant="hard_be")
    partial15 = simulate_trade_path_variant(trade, m1_candles, config=config, variant="partial15")
    partial20 = simulate_trade_path_variant(trade, m1_candles, config=config, variant="partial20")
    exit_bad_m5 = simulate_trade_path_variant(trade, m1_candles, config=config, variant="exit_bad_m5", m5_candles=m5_candles)
    hold_retest = simulate_trade_path_variant(trade, m1_candles, config=config, variant="hold_healthy_retest")
    runner_result = simulate_trade_path_variant(trade, m1_candles, config=config, variant="runner_liquidity", runner_target=runner_target)

    first_bad = next((ts for quality, ts in m5_sequence if quality == "BAD_CLOSE"), None)
    first_invalidating = next((ts for quality, ts in m5_sequence if quality == "INVALIDATING_CLOSE"), None)
    reason_codes = set(event_state.reason_codes)
    reason_codes.update(baseline.reason_codes)
    reason_codes.update(hard_be.reason_codes)
    reason_codes.update(retest.get("reason_codes", []))
    reason_codes.update(runner.get("target_reason_codes", []))
    reason_codes.update(runner.get("target_blockers", []))
    if not _clean_candles(m1_candles):
        reason_codes.add("M1_PATH_DATA_MISSING")
    if not _clean_candles(m5_candles):
        reason_codes.add("M5_CONTEXT_DATA_MISSING")

    ai_judge_result = ai_judge_result or {}
    ai_reason_codes = ai_judge_result.get("reason_codes")
    if isinstance(ai_reason_codes, list):
        ai_reason_codes_text = ";".join(str(code) for code in ai_reason_codes)
    else:
        ai_reason_codes_text = ai_reason_codes

    row = {
        "trade_id": trade.trade_id,
        "symbol": trade.symbol,
        "strategy": trade.strategy,
        "direction": side,
        "signal_timestamp": _timestamp(trade.signal_timestamp),
        "entry_timestamp": _timestamp(trade.entry_timestamp),
        "entry_price": trade.entry_price,
        "stop_loss": trade.stop_loss,
        "original_take_profit": trade.original_take_profit,
        "stop_distance_usd": _round(risk),
        "tp_distance_usd": _round(trade.tp_distance_usd),
        "stop_distance_R": 1.0 if risk > 0 else None,
        "be_trigger_usd": config.be_trigger_usd,
        "partial_trigger_usd": ",".join(str(v).rstrip("0").rstrip(".") for v in config.partial_triggers_usd),
        "partial_fraction": config.partial_close_fraction,
        "hit_be_10": event_state.hit_be_10,
        "hit_partial_15": event_state.hit_partial_15,
        "hit_partial_20": event_state.hit_partial_20,
        "be_timestamp": event_state.be_timestamp,
        "partial_15_timestamp": event_state.partial_15_timestamp,
        "partial_20_timestamp": event_state.partial_20_timestamp,
        "mfe_usd": event_state.mfe_usd,
        "mae_usd": event_state.mae_usd,
        "mfe_R": _round(event_state.mfe_usd / risk if risk else None),
        "mae_R": _round(event_state.mae_usd / risk if risk else None),
        "m5_close_quality_sequence": json.dumps([{"quality": q, "timestamp": ts} for q, ts in m5_sequence], sort_keys=True),
        "first_bad_m5_close_timestamp": first_bad,
        "first_invalidating_m5_close_timestamp": first_invalidating,
        "reaction_state_sequence": json.dumps([reaction["reaction_state"]], sort_keys=True),
        "retest_detected": bool(retest.get("retest_detected", False)),
        "retest_quality": retest.get("retest_quality", "NO_RETEST"),
        "retest_timestamp": retest.get("retest_timestamp"),
        "retest_depth_usd": retest.get("retest_depth_usd"),
        "retest_depth_R": retest.get("retest_depth_R"),
        "runner_opportunity": runner["runner_opportunity"],
        "liquidity_target_price": runner.get("liquidity_target_price"),
        "dynamic_target_distance_usd": runner.get("dynamic_target_distance_usd"),
        "dynamic_target_R": runner.get("dynamic_target_R"),
        "result_baseline_R": baseline.r_multiple,
        "result_hard_be_R": hard_be.r_multiple,
        "result_m5_confirmed_be_R": m5_be.r_multiple,
        "result_structural_be_R": structural_be.r_multiple,
        "result_partial15_R": partial15.r_multiple,
        "result_partial20_R": partial20.r_multiple,
        "result_exit_bad_m5_R": exit_bad_m5.r_multiple,
        "result_hold_healthy_retest_R": hold_retest.r_multiple,
        "result_runner_liquidity_R": runner_result.r_multiple,
        "decision_reason_codes": ";".join(sorted(str(code) for code in reason_codes if code)),
        "ai_judge_enabled": bool(ai_judge_result.get("enabled", False)),
        "ai_judge_status": ai_judge_result.get("status", "disabled"),
        "ai_m5_close_quality": ai_judge_result.get("m5_close_quality"),
        "ai_reaction_state": ai_judge_result.get("reaction_state"),
        "ai_retest_quality": ai_judge_result.get("retest_quality"),
        "ai_runner_opportunity": ai_judge_result.get("runner_opportunity"),
        "ai_suggested_action": ai_judge_result.get("suggested_action"),
        "ai_confidence": ai_judge_result.get("confidence"),
        "ai_reason_codes": ai_reason_codes_text,
    }
    for field_name in HUMAN_LABEL_FIELDS + COMPARISON_PLACEHOLDER_FIELDS:
        row.setdefault(field_name, None)
    return row


def build_synthetic_trade_examples(config: HumanManagementConfig = HumanManagementConfig()) -> list[dict[str, Any]]:
    long = TradeInput(
        trade_id="synthetic_long_human_management",
        symbol="XAUUSD",
        strategy="strategy_2_liquidity_expansion",
        direction="LONG",
        signal_timestamp="2026-05-19T14:00:00+00:00",
        entry_timestamp="2026-05-19T14:00:00+00:00",
        entry_price=2400.0,
        stop_loss=2394.0,
        original_take_profit=2424.0,
    )
    long_m1 = [
        {"time": "2026-05-19T14:01:00+00:00", "open": 2400.0, "high": 2408.0, "low": 2399.0, "close": 2407.0},
        {"time": "2026-05-19T14:02:00+00:00", "open": 2407.0, "high": 2416.0, "low": 2405.0, "close": 2414.0},
        {"time": "2026-05-19T14:03:00+00:00", "open": 2414.0, "high": 2426.0, "low": 2412.0, "close": 2424.0},
    ]
    long_m5 = [
        {"time": "2026-05-19T14:05:00+00:00", "open": 2400.0, "high": 2416.0, "low": 2399.0, "close": 2414.0},
        {"time": "2026-05-19T14:10:00+00:00", "open": 2414.0, "high": 2426.0, "low": 2410.0, "close": 2424.0},
    ]
    short = TradeInput(
        trade_id="synthetic_short_retest_management",
        symbol="XAUUSD",
        strategy="strategy_2_liquidity_expansion",
        direction="SHORT",
        signal_timestamp="2026-05-19T15:00:00+00:00",
        entry_timestamp="2026-05-19T15:00:00+00:00",
        entry_price=2400.0,
        stop_loss=2406.0,
        original_take_profit=2376.0,
    )
    short_m1 = [
        {"time": "2026-05-19T15:01:00+00:00", "open": 2400.0, "high": 2401.0, "low": 2391.0, "close": 2392.0},
        {"time": "2026-05-19T15:02:00+00:00", "open": 2392.0, "high": 2400.0, "low": 2388.0, "close": 2390.0},
        {"time": "2026-05-19T15:03:00+00:00", "open": 2390.0, "high": 2392.0, "low": 2374.0, "close": 2376.0},
    ]
    short_m5 = [
        {"time": "2026-05-19T15:05:00+00:00", "open": 2400.0, "high": 2401.0, "low": 2388.0, "close": 2390.0},
        {"time": "2026-05-19T15:10:00+00:00", "open": 2390.0, "high": 2393.0, "low": 2374.0, "close": 2376.0},
    ]
    return [
        build_trade_management_record(
            long,
            m1_candles=long_m1,
            m5_candles=long_m5,
            config=config,
            runner_context={"liquidity_levels": [2428.0], "context": {"trend_continuation": True}},
        ),
        build_trade_management_record(
            short,
            m1_candles=short_m1,
            m5_candles=short_m5,
            config=config,
            runner_context={"external_liquidity": [2372.0], "context": {"reversal_context": True}},
        ),
    ]


__all__ = [
    "COMPARISON_PLACEHOLDER_FIELDS",
    "ENTRY_QUALITIES",
    "ERROR_CATEGORIES",
    "HUMAN_ACTIONS",
    "HUMAN_LABEL_FIELDS",
    "M5_CLOSE_QUALITIES",
    "PER_TRADE_EXPORT_FIELDS",
    "REACTION_STATES",
    "RETEST_QUALITIES",
    "RUNNER_OPPORTUNITIES",
    "EventState",
    "HumanManagementConfig",
    "TradeInput",
    "TradePathResult",
    "build_synthetic_trade_examples",
    "build_trade_management_record",
    "collect_path_event_state",
    "detect_runner_opportunity",
    "evaluate_entry_quality",
    "evaluate_m5_close_quality",
    "evaluate_reaction_state",
    "evaluate_retest_quality",
    "metric_block_from_r",
    "simulate_trade_path_variant",
]
