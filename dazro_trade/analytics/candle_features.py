"""
Candle micro-pattern features for M1/M5 behaviour profiling.

Pure functions that, given a single candle and a prior-candles window,
return a dict of numeric / boolean features used downstream by the
candle-behavior profiler.

NO trading rule lives here. Features are intentionally low-level so the
profiler can mix-and-match them when computing per-pattern statistics.

Inputs expected on each row / window:
    columns: time (optional), open, high, low, close, tick_volume (optional)
The module also accepts the short-name schema (o/h/l/c/vol) used inside
the Adelin pipeline; columns are normalized internally.

All numeric features are in price units; pip-conversion is the
caller's responsibility (kept symbol-agnostic).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


# ----------------------------------------------------------------------
# Column normalization
# ----------------------------------------------------------------------

def _open(row: Any) -> float:
    return float(row["o"] if "o" in row else row["open"])


def _high(row: Any) -> float:
    return float(row["h"] if "h" in row else row["high"])


def _low(row: Any) -> float:
    return float(row["l"] if "l" in row else row["low"])


def _close(row: Any) -> float:
    return float(row["c"] if "c" in row else row["close"])


def _volume(row: Any) -> float:
    if "vol" in row:
        return float(row["vol"])
    if "tick_volume" in row:
        return float(row["tick_volume"])
    return 0.0


def _normalize_window(df: pd.DataFrame) -> pd.DataFrame:
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


# ----------------------------------------------------------------------
# Single-candle geometry
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class CandleGeometry:
    candle_range: float
    body_size: float
    upper_wick: float
    lower_wick: float
    close_position_in_range: float   # 0 (close==low) -> 1 (close==high)
    body_to_range_ratio: float       # 0 -> 1 (Marubozu)
    wick_imbalance: float            # (upper - lower) / range, range [-1, 1]
    direction: str                   # "BULL" / "BEAR" / "DOJI"

    def to_dict(self) -> dict[str, Any]:
        return {
            "candle_range": round(self.candle_range, 6),
            "body_size": round(self.body_size, 6),
            "upper_wick": round(self.upper_wick, 6),
            "lower_wick": round(self.lower_wick, 6),
            "close_position_in_range": round(self.close_position_in_range, 4),
            "body_to_range_ratio": round(self.body_to_range_ratio, 4),
            "wick_imbalance": round(self.wick_imbalance, 4),
            "direction": self.direction,
        }


def compute_candle_geometry(candle: Any) -> CandleGeometry:
    o = _open(candle)
    h = _high(candle)
    l = _low(candle)
    c = _close(candle)
    rng = max(h - l, 0.0)
    body = abs(c - o)
    upper_wick = max(h - max(o, c), 0.0)
    lower_wick = max(min(o, c) - l, 0.0)
    if rng > 0:
        close_pos = (c - l) / rng
        body_ratio = body / rng
        wick_imb = (upper_wick - lower_wick) / rng
    else:
        close_pos = 0.5
        body_ratio = 0.0
        wick_imb = 0.0
    direction = "BULL" if c > o else "BEAR" if c < o else "DOJI"
    return CandleGeometry(
        candle_range=rng,
        body_size=body,
        upper_wick=upper_wick,
        lower_wick=lower_wick,
        close_position_in_range=close_pos,
        body_to_range_ratio=body_ratio,
        wick_imbalance=wick_imb,
        direction=direction,
    )


# ----------------------------------------------------------------------
# Volume features
# ----------------------------------------------------------------------

def compute_relative_volume(candle: Any, window: pd.DataFrame, *, lookback: int) -> float | None:
    """Volume of `candle` divided by the mean volume of the last `lookback`
    candles in `window`. Returns None when not enough history."""
    if window is None or len(window) < lookback:
        return None
    if lookback <= 0:
        return None
    norm = _normalize_window(window.tail(lookback))
    vols = norm.get("vol")
    if vols is None or len(vols) == 0:
        return None
    mean_vol = float(vols.astype(float).mean())
    if mean_vol <= 0:
        return None
    cur_vol = _volume(candle)
    return round(cur_vol / mean_vol, 4)


# ----------------------------------------------------------------------
# Displacement
# ----------------------------------------------------------------------

def compute_displacement_score(candle: Any, window: pd.DataFrame, *, lookback: int = 20) -> float:
    """How "expansive" is this candle compared to recent body sizes.

    Returns body_size / mean(body_size over last `lookback` candles).
    0.0 when there is not enough history.
    """
    if window is None or len(window) < lookback:
        return 0.0
    norm = _normalize_window(window.tail(lookback))
    bodies = (norm["c"].astype(float) - norm["o"].astype(float)).abs()
    mean_body = float(bodies.mean() or 0.0)
    if mean_body <= 0:
        return 0.0
    body = abs(_close(candle) - _open(candle))
    return round(body / mean_body, 4)


# ----------------------------------------------------------------------
# Sweep + reclaim
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class SweepInfo:
    swept_high: bool
    swept_low: bool
    swept_high_level: float | None
    swept_low_level: float | None
    reclaim_after_sweep: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "swept_high": self.swept_high,
            "swept_low": self.swept_low,
            "swept_high_level": self.swept_high_level,
            "swept_low_level": self.swept_low_level,
            "reclaim_after_sweep": self.reclaim_after_sweep,
        }


def detect_sweep(candle: Any, window: pd.DataFrame, *, lookback: int = 10) -> SweepInfo:
    """A "sweep" is defined as the candle high (resp. low) exceeding the
    max (resp. min) of the previous `lookback` candles.

    `reclaim_after_sweep` is True when the body closes back inside the
    previous range despite the wick excursion (classic liquidity grab
    + reclaim signature).
    """
    if window is None or len(window) < 2:
        return SweepInfo(False, False, None, None, False)
    norm = _normalize_window(window.tail(lookback))
    prev_high = float(norm["h"].astype(float).max())
    prev_low = float(norm["l"].astype(float).min())
    h = _high(candle)
    l = _low(candle)
    c = _close(candle)
    swept_high = h > prev_high
    swept_low = l < prev_low
    reclaim = (swept_high and c < prev_high) or (swept_low and c > prev_low)
    return SweepInfo(
        swept_high=swept_high,
        swept_low=swept_low,
        swept_high_level=prev_high if swept_high else None,
        swept_low_level=prev_low if swept_low else None,
        reclaim_after_sweep=reclaim,
    )


# ----------------------------------------------------------------------
# FVG / IFVG detection on a 3-candle window
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class FVGInfo:
    fvg_created: bool
    ifvg_created: bool
    fvg_direction: str | None   # "BULL" / "BEAR" / None
    fvg_top: float | None
    fvg_bottom: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fvg_created": self.fvg_created,
            "ifvg_created": self.ifvg_created,
            "fvg_direction": self.fvg_direction,
            "fvg_top": self.fvg_top,
            "fvg_bottom": self.fvg_bottom,
        }


def detect_fvg_ifvg(window_3: pd.DataFrame) -> FVGInfo:
    """Classic FVG: candle c1.low > c-1.high (bullish) or c1.high < c-1.low (bearish),
    where the middle candle (c0) is the displacement candle.

    Inverse FVG (IFVG) is detected when an existing bullish gap is
    closed and price reverses below it (or vice-versa). This is a
    light heuristic — full IFVG tracking would need state across many
    candles, out of scope for the per-candle feature pass.
    """
    if window_3 is None or len(window_3) < 3:
        return FVGInfo(False, False, None, None, None)
    norm = _normalize_window(window_3.tail(3))
    c_prev = norm.iloc[-3]
    c_mid = norm.iloc[-2]
    c_last = norm.iloc[-1]
    prev_h = float(c_prev["h"])
    prev_l = float(c_prev["l"])
    last_h = float(c_last["h"])
    last_l = float(c_last["l"])
    mid_o = float(c_mid["o"])
    mid_c = float(c_mid["c"])
    bull_gap = last_l > prev_h and mid_c > mid_o
    bear_gap = last_h < prev_l and mid_c < mid_o
    if bull_gap:
        return FVGInfo(True, False, "BULL", last_l, prev_h)
    if bear_gap:
        return FVGInfo(True, False, "BEAR", prev_l, last_h)
    # Heuristic IFVG: middle candle wicked into a prior small gap and
    # closed the opposite side of it.
    body_prev = abs(float(c_prev["c"]) - float(c_prev["o"]))
    body_mid = abs(mid_c - mid_o)
    if body_mid > 0 and body_prev > 0 and body_mid >= body_prev * 1.5:
        # Strong middle candle that closed beyond the prior range
        prev_range_top = max(prev_h, float(c_prev["o"]), float(c_prev["c"]))
        prev_range_bottom = min(prev_l, float(c_prev["o"]), float(c_prev["c"]))
        if mid_c > prev_range_top or mid_c < prev_range_bottom:
            direction = "BULL" if mid_c > mid_o else "BEAR"
            return FVGInfo(False, True, direction, prev_range_top, prev_range_bottom)
    return FVGInfo(False, False, None, None, None)


# ----------------------------------------------------------------------
# Behavior labels
# ----------------------------------------------------------------------

def label_candle_behavior(
    geometry: CandleGeometry,
    displacement: float,
    sweep: SweepInfo,
    fvg: FVGInfo,
) -> dict[str, bool]:
    """Boolean labels used by the profiler aggregations.

    - absorption_candidate: long wick on one side, small body, no displacement
    - continuation_candidate: dominant body, displacement >= 1.5, no opposing wick
    - rejection_candidate: wick at extreme side >= 60% range, body small,
      reclaim if sweep occurred
    """
    rng = geometry.candle_range
    body = geometry.body_size
    upper = geometry.upper_wick
    lower = geometry.lower_wick

    long_wick_threshold = 0.5  # >= 50% of range
    absorption = rng > 0 and body / rng <= 0.35 and (
        (upper / rng) >= long_wick_threshold or (lower / rng) >= long_wick_threshold
    ) and displacement < 1.2

    continuation = geometry.body_to_range_ratio >= 0.6 and displacement >= 1.5

    if rng > 0:
        bullish_rejection = (
            geometry.direction == "BULL"
            and lower / rng >= 0.6
            and body / rng <= 0.4
            and (not sweep.swept_low or sweep.reclaim_after_sweep)
        )
        bearish_rejection = (
            geometry.direction == "BEAR"
            and upper / rng >= 0.6
            and body / rng <= 0.4
            and (not sweep.swept_high or sweep.reclaim_after_sweep)
        )
        rejection = bullish_rejection or bearish_rejection
    else:
        rejection = False

    return {
        "absorption_candidate": bool(absorption),
        "continuation_candidate": bool(continuation),
        "rejection_candidate": bool(rejection),
    }


# ----------------------------------------------------------------------
# Top-level feature row
# ----------------------------------------------------------------------

def compute_candle_features(
    candle: Any,
    history: pd.DataFrame,
    *,
    relative_volume_lookbacks: tuple[int, ...] = (20, 50),
    displacement_lookback: int = 20,
    sweep_lookback: int = 10,
) -> dict[str, Any]:
    """Return a flat dict of all features for one candle given prior history."""
    geometry = compute_candle_geometry(candle)
    displacement = compute_displacement_score(candle, history, lookback=displacement_lookback)
    sweep = detect_sweep(candle, history, lookback=sweep_lookback)
    # Need at least 2 prior candles + the current one to detect FVG;
    # build the 3-candle window from history + candle.
    window_3 = pd.concat([history.tail(2), pd.DataFrame([candle])], ignore_index=True) if history is not None and len(history) >= 2 else None
    fvg = detect_fvg_ifvg(window_3) if window_3 is not None else FVGInfo(False, False, None, None, None)
    labels = label_candle_behavior(geometry, displacement, sweep, fvg)

    out: dict[str, Any] = {}
    out.update(geometry.to_dict())
    for lb in relative_volume_lookbacks:
        out[f"relative_volume_{lb}"] = compute_relative_volume(candle, history, lookback=lb)
    out["volume"] = _volume(candle)
    out["displacement_score"] = displacement
    out.update(sweep.to_dict())
    out.update(fvg.to_dict())
    out.update(labels)
    return out


__all__ = [
    "CandleGeometry",
    "FVGInfo",
    "SweepInfo",
    "compute_candle_features",
    "compute_candle_geometry",
    "compute_displacement_score",
    "compute_relative_volume",
    "detect_fvg_ifvg",
    "detect_sweep",
    "label_candle_behavior",
]
