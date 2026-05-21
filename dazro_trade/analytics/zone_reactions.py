"""
Zone reaction profiler.

Given a `ZoneTouch` and the candles that follow the touch (M1 or M5),
compute the price reaction over a configurable set of horizons plus
boolean labels for the classical sweep / reclaim / displacement /
break-and-continue / rejection signatures.

The module is pure: it does not touch the live strategy and does not
modify the touch / zone objects. All distances are returned in raw
price units; pip conversion is the caller's responsibility.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from dazro_trade.analytics.zone_features import ZoneTouch

DEFAULT_HORIZONS: tuple[int, ...] = (1, 3, 5, 10, 20)
DISPLACEMENT_BODY_MULTIPLIER: float = 1.5
BREAK_AND_CONTINUE_RANGE_MULTIPLIER: float = 1.0


@dataclass(frozen=True)
class ZoneReaction:
    horizons: tuple[int, ...]
    # signed reaction at each horizon: positive = price moved up from touch close,
    # negative = price moved down. Caller interprets vs zone side.
    reaction_at: dict[int, float | None] = field(default_factory=dict)
    max_favorable_excursion: float = 0.0       # max price - close_at_touch
    max_adverse_excursion: float = 0.0         # close_at_touch - min price
    did_sweep: bool = False
    did_reclaim: bool = False
    did_displace: bool = False
    did_break_and_continue: bool = False
    did_reject: bool = False
    time_to_reaction_bars: int | None = None
    volume_on_touch: float = 0.0
    relative_volume_on_touch: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizons": list(self.horizons),
            "reaction_at": {int(k): (None if v is None else round(v, 6)) for k, v in self.reaction_at.items()},
            "max_favorable_excursion": round(self.max_favorable_excursion, 6),
            "max_adverse_excursion": round(self.max_adverse_excursion, 6),
            "did_sweep": self.did_sweep,
            "did_reclaim": self.did_reclaim,
            "did_displace": self.did_displace,
            "did_break_and_continue": self.did_break_and_continue,
            "did_reject": self.did_reject,
            "time_to_reaction_bars": self.time_to_reaction_bars,
            "volume_on_touch": round(self.volume_on_touch, 6),
            "relative_volume_on_touch": None if self.relative_volume_on_touch is None else round(self.relative_volume_on_touch, 4),
        }


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rename: dict[str, str] = {}
    if "open" in out.columns and "o" not in out.columns:
        rename["open"] = "o"
    if "high" in out.columns and "h" not in out.columns:
        rename["high"] = "h"
    if "low" in out.columns and "l" not in out.columns:
        rename["low"] = "l"
    if "close" in out.columns and "c" not in out.columns:
        rename["close"] = "c"
    if "tick_volume" in out.columns and "vol" not in out.columns:
        rename["tick_volume"] = "vol"
    if rename:
        out = out.rename(columns=rename)
    return out


def compute_reaction(
    touch: ZoneTouch,
    touch_candle_close: float,
    touch_candle_volume: float,
    future: pd.DataFrame,
    *,
    history_for_relative_volume: pd.DataFrame | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    relative_volume_lookback: int = 20,
) -> ZoneReaction:
    """Compute reaction metrics after a `ZoneTouch`.

    Args:
        touch: the ZoneTouch object describing zone + candle.
        touch_candle_close: close price of the candle that touched the
            zone (anchor for reaction_at / MFE / MAE).
        touch_candle_volume: volume of the touch candle.
        future: dataframe of candles strictly after the touch (already
            sliced by the caller — the profiler does NOT look up to or
            include the touch candle itself).
        history_for_relative_volume: optional history window used to
            compute volume_on_touch / mean(volume) baseline.
        horizons: list of bars-after-touch checkpoints.
        relative_volume_lookback: window size for the baseline.

    Returns:
        ZoneReaction with all metrics.
    """
    if future is None or len(future) == 0:
        return ZoneReaction(
            horizons=horizons,
            reaction_at={h: None for h in horizons},
            volume_on_touch=float(touch_candle_volume),
            relative_volume_on_touch=_rel_vol(touch_candle_volume, history_for_relative_volume, relative_volume_lookback),
        )

    norm = _normalize(future)
    closes = norm["c"].astype(float).values
    highs = norm["h"].astype(float).values
    lows = norm["l"].astype(float).values
    opens = norm["o"].astype(float).values

    anchor = float(touch_candle_close)
    reaction_at: dict[int, float | None] = {}
    for h in horizons:
        idx = h - 1
        if idx < 0 or idx >= len(closes):
            reaction_at[h] = None
            continue
        reaction_at[h] = float(closes[idx]) - anchor

    if len(highs) > 0:
        mfe = float(max(highs.max() - anchor, 0.0))
        mae = float(max(anchor - lows.min(), 0.0))
    else:
        mfe = 0.0
        mae = 0.0

    zone_top = max(float(touch.zone.top), float(touch.zone.bottom))
    zone_bot = min(float(touch.zone.top), float(touch.zone.bottom))

    # Sweep direction relevant to the zone:
    # - buy_side zones (e.g. H1 highs): the meaningful sweep is the
    #   candle_high exceeding zone_top
    # - sell_side zones (e.g. H1 lows): the meaningful sweep is the
    #   candle_low piercing zone_bot
    # - neutral zones (FVG, VWAP): both directions count
    sweep_above = bool(touch.candle_high > zone_top)
    sweep_below = bool(touch.candle_low < zone_bot)
    if touch.zone.side == "buy_side":
        sweep_relevant_above = sweep_above
        sweep_relevant_below = False
    elif touch.zone.side == "sell_side":
        sweep_relevant_above = False
        sweep_relevant_below = sweep_below
    else:
        sweep_relevant_above = sweep_above
        sweep_relevant_below = sweep_below
    did_sweep = sweep_relevant_above or sweep_relevant_below

    # Reclaim: after a sweep, price closed back inside the zone within
    # the short horizon (first 3 future bars).
    reclaim_window = 3
    reclaim_slice = norm.head(reclaim_window)
    did_reclaim = False
    if not reclaim_slice.empty:
        closes_short = reclaim_slice["c"].astype(float)
        if sweep_relevant_above:
            did_reclaim = bool((closes_short <= zone_top).any())
        if not did_reclaim and sweep_relevant_below:
            did_reclaim = bool((closes_short >= zone_bot).any())

    # Displacement: any of the first 3 future candles has |body| >=
    # 1.5x the touch-candle range.
    touch_range = max(touch.candle_high - touch.candle_low, 1e-9)
    displace_slice = norm.head(reclaim_window)
    bodies = (displace_slice["c"].astype(float) - displace_slice["o"].astype(float)).abs()
    did_displace = bool(len(bodies) and float(bodies.max()) >= DISPLACEMENT_BODY_MULTIPLIER * touch_range)

    # Break-and-continue: after a relevant sweep, price continued in the
    # sweep direction by at least one zone-height.
    zone_height = max(zone_top - zone_bot, touch_range)
    did_break_continue = False
    if sweep_relevant_above:
        threshold = zone_top + BREAK_AND_CONTINUE_RANGE_MULTIPLIER * zone_height
        did_break_continue = did_break_continue or bool((norm["h"].astype(float) >= threshold).any())
    if sweep_relevant_below:
        threshold = zone_bot - BREAK_AND_CONTINUE_RANGE_MULTIPLIER * zone_height
        did_break_continue = did_break_continue or bool((norm["l"].astype(float) <= threshold).any())

    # Rejection: NO break-and-continue AND price moved opposite the touch
    # direction by at least zone-height. For buy-side zones (highs) we
    # expect a move down, for sell-side (lows) a move up.
    did_reject = False
    if touch.zone.side == "buy_side":
        did_reject = bool(anchor - lows.min() >= zone_height) and not did_break_continue
    elif touch.zone.side == "sell_side":
        did_reject = bool(highs.max() - anchor >= zone_height) and not did_break_continue
    else:
        # Neutral zones: rejection = absolute opposite move >= zone_height
        opposite = max(mae, mfe)
        did_reject = bool(opposite >= zone_height) and not did_break_continue

    # Time to reaction: first bar where |close - anchor| >= zone_height
    time_to_reaction: int | None = None
    for i, c_val in enumerate(closes, start=1):
        if abs(float(c_val) - anchor) >= zone_height:
            time_to_reaction = i
            break

    return ZoneReaction(
        horizons=horizons,
        reaction_at=reaction_at,
        max_favorable_excursion=mfe,
        max_adverse_excursion=mae,
        did_sweep=did_sweep,
        did_reclaim=did_reclaim,
        did_displace=did_displace,
        did_break_and_continue=did_break_continue,
        did_reject=did_reject,
        time_to_reaction_bars=time_to_reaction,
        volume_on_touch=float(touch_candle_volume),
        relative_volume_on_touch=_rel_vol(touch_candle_volume, history_for_relative_volume, relative_volume_lookback),
    )


def _rel_vol(touch_volume: float, history: pd.DataFrame | None, lookback: int) -> float | None:
    if history is None or len(history) < lookback or lookback <= 0:
        return None
    norm = _normalize(history.tail(lookback))
    if "vol" not in norm.columns or len(norm) == 0:
        return None
    mean_vol = float(norm["vol"].astype(float).mean() or 0.0)
    if mean_vol <= 0:
        return None
    return round(float(touch_volume) / mean_vol, 4)


__all__ = [
    "DEFAULT_HORIZONS",
    "ZoneReaction",
    "compute_reaction",
]
