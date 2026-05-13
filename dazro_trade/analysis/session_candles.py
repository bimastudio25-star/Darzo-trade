from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from dazro_trade.analysis.candle_path import classify_candle_path
from dazro_trade.analysis.time_behaviour import TimeBehaviourContext


@dataclass(frozen=True)
class SessionCandleEvent:
    session_name: str
    timeframe: str
    candle_time: datetime
    candle_role: str
    swept_level: float | None
    swept_level_name: str | None
    direction: str | None
    wick_ratio: float
    body_ratio: float
    close_location: str
    accepted_breakout: bool
    failed_breakout: bool
    displacement: bool
    follow_through: bool
    ema_context: dict
    vwap_context: dict
    time_behaviour: dict
    candle_path: dict
    classification: str
    reason_codes: list[str]

    def to_dict(self) -> dict:
        out = asdict(self)
        out["candle_time"] = self.candle_time.isoformat()
        return out


def classify_session_candle(
    *,
    symbol: str,
    timeframe: str,
    candle: pd.Series,
    lower_tf: pd.DataFrame | None,
    session_name: str,
    time_context: TimeBehaviourContext,
    reference_ranges: dict,
    ema_context: dict | None,
    vwap_context: dict | None,
    liquidity_pools: list[dict],
) -> SessionCandleEvent:
    open_ = float(_get(candle, "o", "open"))
    high = float(_get(candle, "h", "high"))
    low = float(_get(candle, "l", "low"))
    close = float(_get(candle, "c", "close"))
    rng = max(high - low, 0.01)
    body_ratio = abs(close - open_) / rng
    upper_wick_ratio = (high - max(open_, close)) / rng
    lower_wick_ratio = (min(open_, close) - low) / rng
    swept_name, swept_level, swept_side = _swept_reference(high, low, reference_ranges)
    close_location = _close_location(close, high, low)
    path = classify_candle_path(candle, lower_tf if lower_tf is not None else pd.DataFrame(), _nearest_high(reference_ranges), _nearest_low(reference_ranges))
    accepted_breakout = bool(swept_level is not None and ((swept_side == "buy_side" and close > swept_level and body_ratio >= 0.45) or (swept_side == "sell_side" and close < swept_level and body_ratio >= 0.45)))
    failed_breakout = bool(swept_level is not None and ((swept_side == "buy_side" and close < swept_level) or (swept_side == "sell_side" and close > swept_level)))
    displacement = body_ratio >= 0.55
    follow_through = _follow_through(lower_tf, "BUY" if close > open_ else "SELL")
    reasons = list(time_context.reason_codes)
    classification = "NO_CLEAR_SESSION_BEHAVIOUR"
    direction = None

    open_window = time_context.time_window in {"london_open", "ny_open", "pre_london", "pre_ny"}
    if path.two_sided_sweep or (body_ratio < 0.25 and not displacement):
        classification = "LIQUIDITY_SEARCH_NO_TRADE"
        reasons.extend(["two_sided_liquidity_search", "no_clear_acceptance", "no_trade_chop"])
    elif open_window and failed_breakout and swept_side == "buy_side" and upper_wick_ratio >= 0.12:
        classification = "NY_MANIPULATION_REVERSAL_SHORT" if time_context.time_window == "ny_open" else "OPEN_MANIPULATION_BUY_SIDE_SWEEP"
        direction = "SELL"
        reasons.extend(["session_open_liquidity_sweep", _level_reason(swept_name), "close_back_inside_range", "no_acceptance_after_sweep", "manipulation_candle_candidate"])
    elif open_window and failed_breakout and swept_side == "sell_side" and lower_wick_ratio >= 0.12:
        classification = "NY_MANIPULATION_REVERSAL_LONG" if time_context.time_window == "ny_open" else "OPEN_MANIPULATION_SELL_SIDE_SWEEP"
        direction = "BUY"
        reasons.extend(["session_open_liquidity_sweep", _level_reason(swept_name), "close_back_inside_range", "no_acceptance_after_sweep", "manipulation_candle_candidate"])
    elif open_window and accepted_breakout and swept_side == "buy_side":
        classification = "OPEN_DRIVE_CONTINUATION_LONG" if follow_through else "ACCEPTED_BREAKOUT_LONG"
        direction = "BUY"
        reasons.extend(["open_drive_detected", "accepted_breakout", "vwap_acceptance" if _vwap_aligned(vwap_context, "BUY", close) else "vwap_neutral"])
        if _ema_aligned(ema_context, "BUY"):
            reasons.append("ema_trend_aligned")
    elif open_window and accepted_breakout and swept_side == "sell_side":
        classification = "OPEN_DRIVE_CONTINUATION_SHORT" if follow_through else "ACCEPTED_BREAKOUT_SHORT"
        direction = "SELL"
        reasons.extend(["open_drive_detected", "accepted_breakout", "vwap_acceptance" if _vwap_aligned(vwap_context, "SELL", close) else "vwap_neutral"])
        if _ema_aligned(ema_context, "SELL"):
            reasons.append("ema_trend_aligned")

    if classification in {"OPEN_MANIPULATION_BUY_SIDE_SWEEP", "NY_MANIPULATION_REVERSAL_SHORT"} and _has_confirmations(liquidity_pools, {"m1_choch", "m5_displacement", "bearish_fvg_after_buy_side_sweep", "bearish_ifvg_after_buy_side_sweep"}):
        classification = "AMD_DISTRIBUTION_SHORT"
        reasons.extend(["amd_manipulation_complete", "distribution_after_manipulation", "choch_after_manipulation", "displacement_after_manipulation", "fvg_after_manipulation"])
    if classification in {"OPEN_MANIPULATION_SELL_SIDE_SWEEP", "NY_MANIPULATION_REVERSAL_LONG"} and _has_confirmations(liquidity_pools, {"m1_choch", "m5_displacement", "bullish_fvg_after_sell_side_sweep", "bullish_ifvg_after_sell_side_sweep"}):
        classification = "AMD_DISTRIBUTION_LONG"
        reasons.extend(["amd_manipulation_complete", "distribution_after_manipulation", "choch_after_manipulation", "displacement_after_manipulation", "fvg_after_manipulation"])

    return SessionCandleEvent(
        session_name=session_name,
        timeframe=timeframe,
        candle_time=path.candle_time,
        candle_role=time_context.time_window,
        swept_level=swept_level,
        swept_level_name=swept_name,
        direction=direction,
        wick_ratio=round(max(upper_wick_ratio, lower_wick_ratio), 2),
        body_ratio=round(body_ratio, 2),
        close_location=close_location,
        accepted_breakout=accepted_breakout,
        failed_breakout=failed_breakout,
        displacement=displacement,
        follow_through=follow_through,
        ema_context=ema_context or {},
        vwap_context=vwap_context or {},
        time_behaviour=time_context.to_dict(),
        candle_path=path.to_dict(),
        classification=classification,
        reason_codes=list(dict.fromkeys(reasons)),
    )


def _swept_reference(high: float, low: float, reference_ranges: dict) -> tuple[str | None, float | None, str | None]:
    candidates: list[tuple[str, float, str]] = []
    for name, value in reference_ranges.items():
        if value is None:
            continue
        if name.endswith("_high") and high > float(value):
            candidates.append((name, float(value), "buy_side"))
        if name.endswith("_low") and low < float(value):
            candidates.append((name, float(value), "sell_side"))
    if not candidates:
        return None, None, None
    return min(candidates, key=lambda item: abs((high if item[2] == "buy_side" else low) - item[1]))


def _nearest_high(reference_ranges: dict) -> float | None:
    highs = [float(v) for k, v in reference_ranges.items() if k.endswith("_high") and v is not None]
    return min(highs) if highs else None


def _nearest_low(reference_ranges: dict) -> float | None:
    lows = [float(v) for k, v in reference_ranges.items() if k.endswith("_low") and v is not None]
    return max(lows) if lows else None


def _level_reason(name: str | None) -> str:
    if not name:
        return "liquidity_level_swept"
    if "asia_high" in name:
        return "asia_high_swept"
    if "asia_low" in name:
        return "asia_low_swept"
    if "london_high" in name:
        return "london_high_swept"
    if "london_low" in name:
        return "london_low_swept"
    return f"{name}_swept"


def _close_location(close: float, high: float, low: float) -> str:
    pos = (close - low) / max(high - low, 0.01)
    if pos >= 0.67:
        return "upper_third"
    if pos <= 0.33:
        return "lower_third"
    return "middle"


def _follow_through(lower_tf: pd.DataFrame | None, direction: str) -> bool:
    if lower_tf is None or len(lower_tf) < 3:
        return False
    df = lower_tf.tail(3)
    if direction == "BUY":
        return bool(df["c"].astype(float).iloc[-1] > df["c"].astype(float).iloc[0])
    return bool(df["c"].astype(float).iloc[-1] < df["c"].astype(float).iloc[0])


def _vwap_aligned(ctx: dict | None, direction: str, close: float) -> bool:
    if not ctx or ctx.get("vwap") is None:
        return False
    return close >= float(ctx["vwap"]) if direction == "BUY" else close <= float(ctx["vwap"])


def _ema_aligned(ctx: dict | None, direction: str) -> bool:
    if not ctx:
        return False
    desired = "bullish" if direction == "BUY" else "bearish"
    return ctx.get("ema_alignment") == desired


def _has_confirmations(items: list[dict], required: set[str]) -> bool:
    reasons = set()
    for item in items:
        reasons.update(item.get("reason_codes", []) or [])
    return bool(required.intersection(reasons)) and "m1_choch" in reasons and "m5_displacement" in reasons


def _get(row: pd.Series, short: str, long: str) -> float:
    return row[short] if short in row else row[long]


__all__ = ["SessionCandleEvent", "classify_session_candle"]
