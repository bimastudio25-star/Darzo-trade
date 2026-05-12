from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from dazro_trade.analysis.number_theory import has_number_theory_confluence
from dazro_trade.analysis.volume_profile import VolumeProfile, volume_crack_confluence
from dazro_trade.analysis.vwap import vwap_deviation_confluence
from dazro_trade.core.symbols import price_to_pips, pips_to_price
from dazro_trade.liquidity.map import LiquidityPool

SweepDirection = Literal["bearish_reversal_candidate", "bullish_reversal_candidate"]
SweepStatus = Literal["WATCH", "ARMED", "SWEEPING_INTRABAR", "CONFIRMED_SWEEP", "TRIGGERED", "INVALIDATED", "accepted_breakout"]


@dataclass
class SweepEvent:
    pool_id: str
    symbol: str
    level: float
    direction: SweepDirection
    timeframe: str
    sweep_type: str
    penetration_pips: float
    wick_rejection_ratio: float
    close_back_inside: bool
    accepted_breakout: bool
    displacement_after_sweep: bool = False
    choch_after_sweep: bool = False
    fvg_after_sweep: bool = False
    ifvg_after_sweep: bool = False
    number_theory_confluence: bool = False
    vwap_deviation_confluence: bool = False
    volume_crack_confluence: bool = False
    status: SweepStatus = "WATCH"
    score: int = 0
    reason_codes: list[str] = field(default_factory=list)


def detect_sweep_event(
    pool: LiquidityPool,
    trigger_df: pd.DataFrame,
    *,
    m5_df: pd.DataFrame | None = None,
    m1_df: pd.DataFrame | None = None,
    vwap_df: pd.DataFrame | None = None,
    volume_profile: VolumeProfile | None = None,
    min_penetration_pips: float = 5.0,
    current_candle_closed: bool = True,
) -> SweepEvent | None:
    df = _normalize(trigger_df)
    if df.empty:
        return None
    candle = df.iloc[-1]
    level = pool.level
    direction: SweepDirection = "bearish_reversal_candidate" if pool.side == "buy_side" else "bullish_reversal_candidate"
    if pool.side == "buy_side":
        penetration = max(0.0, float(candle["h"]) - level)
        close_back_inside = float(candle["c"]) < level
        accepted_breakout = float(candle["c"]) > level and _accepted_retest(df, level, "BUY")
        rejection = _wick_rejection_ratio(candle, side="high")
    else:
        penetration = max(0.0, level - float(candle["l"]))
        close_back_inside = float(candle["c"]) > level
        accepted_breakout = float(candle["c"]) < level and _accepted_retest(df, level, "SELL")
        rejection = _wick_rejection_ratio(candle, side="low")
    penetration_pips = round(price_to_pips(pool.symbol, penetration), 1)
    if penetration_pips < min_penetration_pips and pool.distance_pips > 80:
        status: SweepStatus = "ARMED"
    elif penetration_pips >= min_penetration_pips and not current_candle_closed:
        status = "SWEEPING_INTRABAR"
    elif accepted_breakout:
        status = "accepted_breakout"
    elif penetration_pips >= min_penetration_pips and close_back_inside:
        status = "CONFIRMED_SWEEP"
    elif penetration_pips >= min_penetration_pips:
        status = "ARMED"
    else:
        status = "WATCH"

    trade_direction = "SELL" if pool.side == "buy_side" else "BUY"
    displacement = _detect_displacement(_closed_frame(m5_df), trade_direction)
    choch = _detect_choch(_closed_frame(m1_df), trade_direction)
    fvg = _fvg_after_sweep(_closed_frame(m5_df), trade_direction)
    nt = has_number_theory_confluence(level, symbol=pool.symbol)
    vw = vwap_deviation_confluence(vwap_df if vwap_df is not None else trigger_df, level, trade_direction)
    vc = volume_crack_confluence(volume_profile, level) if volume_profile is not None else {"confluence": False}

    reason_codes: list[str] = []
    if pool.pool_type.startswith("external") or pool.pool_type in {"previous_day_high", "previous_day_low", "daily_range_high", "daily_range_low"}:
        reason_codes.append("external_liquidity_swept" if status in {"CONFIRMED_SWEEP", "TRIGGERED"} else "external_liquidity_in_reaction_band")
    if close_back_inside:
        reason_codes.append("close_back_inside")
    if accepted_breakout:
        reason_codes.append("accepted_breakout_not_reversal")
    if displacement:
        reason_codes.append("m5_displacement")
    if choch:
        reason_codes.append("m1_choch")
    if fvg:
        reason_codes.append(("bearish_fvg_after_buy_side_sweep" if trade_direction == "SELL" else "bullish_fvg_after_sell_side_sweep"))
    else:
        reason_codes.append("sweep_confirmed_missing_fvg" if status == "CONFIRMED_SWEEP" else "fvg_without_liquidity_penalty")
    if nt["confluence"]:
        reason_codes.append("number_theory_confluence")
    if vw["confluence"]:
        reason_codes.append(vw["reason"])
    if vc.get("confluence"):
        reason_codes.append(vc.get("reason", "volume_crack_reaction_candidate"))

    score = 0
    score += 20 if status in {"CONFIRMED_SWEEP", "TRIGGERED"} else 0
    score += 20 if displacement else 0
    score += 15 if choch else 0
    score += 20 if fvg else 0
    score += 8 if nt["confluence"] else 0
    score += 10 if vw["confluence"] else 0
    score += 10 if vc.get("confluence") else 0
    score += 7 if rejection >= 0.45 else 0
    if status == "accepted_breakout":
        score = max(0, score - 45)
    if status == "CONFIRMED_SWEEP" and displacement and choch and fvg and score >= 75:
        status = "TRIGGERED"

    return SweepEvent(
        pool_id=pool.id,
        symbol=pool.symbol,
        level=pool.level,
        direction=direction,
        timeframe=pool.timeframe,
        sweep_type=_sweep_type(pool),
        penetration_pips=penetration_pips,
        wick_rejection_ratio=round(rejection, 2),
        close_back_inside=close_back_inside,
        accepted_breakout=accepted_breakout,
        displacement_after_sweep=displacement,
        choch_after_sweep=choch,
        fvg_after_sweep=fvg,
        ifvg_after_sweep=False,
        number_theory_confluence=bool(nt["confluence"]),
        vwap_deviation_confluence=bool(vw["confluence"]),
        volume_crack_confluence=bool(vc.get("confluence")),
        status=status,
        score=min(100, score),
        reason_codes=reason_codes,
    )


def detect_sweeps_for_pools(
    pools: list[LiquidityPool],
    trigger_df: pd.DataFrame,
    *,
    m5_df: pd.DataFrame | None = None,
    m1_df: pd.DataFrame | None = None,
    vwap_df: pd.DataFrame | None = None,
    volume_profile: VolumeProfile | None = None,
    current_candle_closed: bool = True,
) -> list[SweepEvent]:
    events = []
    for pool in pools:
        event = detect_sweep_event(
            pool,
            trigger_df,
            m5_df=m5_df,
            m1_df=m1_df,
            vwap_df=vwap_df,
            volume_profile=volume_profile,
            current_candle_closed=current_candle_closed,
        )
        if event is not None and event.status != "WATCH":
            events.append(event)
    return sorted(events, key=lambda item: (-item.score, item.penetration_pips))


def liquidity_pressure_proxy(event: SweepEvent, trigger_df: pd.DataFrame) -> dict:
    df = _normalize(trigger_df)
    if df.empty or len(df) < 10:
        return {"score": 0, "reason": "insufficient_data"}
    last = df.iloc[-1]
    avg_range = ((df["h"].astype(float) - df["l"].astype(float)).tail(10).mean()) or 0.01
    last_range = float(last["h"]) - float(last["l"])
    volume = float(last.get("vol", 0) or 0)
    avg_volume = float(df.get("vol", pd.Series([1] * len(df))).tail(10).mean() or 1)
    score = 0
    if last_range > avg_range * 1.5:
        score += 25
    if volume > avg_volume * 1.5:
        score += 20
    if event.close_back_inside:
        score += 25
    if event.wick_rejection_ratio > 0.45:
        score += 20
    if event.penetration_pips > 10:
        score += 10
    return {
        "score": min(100, score),
        "reason": "observable_stop_run_proxy_not_real_l2_gamma",
    }


def _sweep_type(pool: LiquidityPool) -> str:
    if "session" in pool.pool_type:
        return "session"
    if "daily" in pool.pool_type or "previous_day" in pool.pool_type:
        return "daily_range"
    if "external" in pool.pool_type:
        return "external"
    return "internal"


def _accepted_retest(df: pd.DataFrame, level: float, direction: str) -> bool:
    if len(df) < 2:
        return False
    last_two = df.tail(2)
    if direction == "BUY":
        return bool((last_two["l"].astype(float) <= level + pips_to_price("XAUUSD", 10)).any() and float(last_two["c"].iloc[-1]) > level)
    return bool((last_two["h"].astype(float) >= level - pips_to_price("XAUUSD", 10)).any() and float(last_two["c"].iloc[-1]) < level)


def _wick_rejection_ratio(candle: pd.Series, *, side: str) -> float:
    high = float(candle["h"])
    low = float(candle["l"])
    open_ = float(candle["o"])
    close = float(candle["c"])
    rng = max(high - low, 0.01)
    if side == "high":
        wick = high - max(open_, close)
    else:
        wick = min(open_, close) - low
    return max(0.0, wick / rng)


def _detect_displacement(df: pd.DataFrame, direction: str) -> bool:
    if df.empty or len(df) < 4:
        return False
    bodies = (df["c"].astype(float) - df["o"].astype(float)).abs()
    avg = float(bodies.iloc[:-1].tail(5).mean() or 0.01)
    last = df.iloc[-1]
    body = abs(float(last["c"]) - float(last["o"]))
    return body >= avg * 1.2 and ((direction == "SELL" and float(last["c"]) < float(last["o"])) or (direction == "BUY" and float(last["c"]) > float(last["o"])))


def _detect_choch(df: pd.DataFrame, direction: str) -> bool:
    if df.empty or len(df) < 5:
        return False
    previous = df.iloc[:-1].tail(5)
    close = float(df["c"].iloc[-1])
    if direction == "SELL":
        return close < float(previous["l"].min())
    return close > float(previous["h"].max())


def _fvg_after_sweep(df: pd.DataFrame, direction: str) -> bool:
    if df.empty or len(df) < 3:
        return False
    a = df.iloc[-3]
    c = df.iloc[-1]
    if direction == "SELL":
        return float(c["h"]) < float(a["l"])
    return float(c["l"]) > float(a["h"])


def _closed_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    frame = _normalize(df)
    if len(frame) > 3:
        return frame.iloc[:-1].copy()
    return frame


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy().rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"})
    if {"o", "h", "l", "c"}.issubset(out.columns):
        return out
    return pd.DataFrame()


__all__ = ["SweepEvent", "detect_sweep_event", "detect_sweeps_for_pools", "liquidity_pressure_proxy"]
