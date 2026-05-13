from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import pandas as pd


@dataclass(frozen=True)
class CandlePathContext:
    timeframe: str
    candle_time: datetime
    open: float
    high: float
    low: float
    close: float
    path_type: str
    first_extreme: str | None
    swept_high_first: bool
    swept_low_first: bool
    returned_inside: bool
    one_way_direction: str | None
    two_sided_sweep: bool
    reason_codes: list[str]

    def to_dict(self) -> dict:
        out = asdict(self)
        out["candle_time"] = self.candle_time.isoformat()
        return out


def classify_candle_path(
    higher_tf_candle: pd.Series,
    lower_tf_df: pd.DataFrame,
    reference_high: float | None = None,
    reference_low: float | None = None,
) -> CandlePathContext:
    candle_time = _row_time(higher_tf_candle)
    open_ = float(_get(higher_tf_candle, "o", "open"))
    high = float(_get(higher_tf_candle, "h", "high"))
    low = float(_get(higher_tf_candle, "l", "low"))
    close = float(_get(higher_tf_candle, "c", "close"))
    lower = _normalize(lower_tf_df)
    if lower.empty:
        return CandlePathContext("unknown", candle_time, open_, high, low, close, "NO_CLEAR_PATH", None, False, False, False, None, False, ["lower_tf_unavailable"])
    window = _slice_inside_candle(lower, candle_time)
    if window.empty:
        window = lower.tail(5)
    high_idx = window["h"].astype(float).idxmax()
    low_idx = window["l"].astype(float).idxmin()
    first_extreme = "high" if window.index.get_loc(high_idx) < window.index.get_loc(low_idx) else "low"
    swept_high = reference_high is not None and high > reference_high
    swept_low = reference_low is not None and low < reference_low
    returned_inside = True
    if swept_high and reference_high is not None:
        returned_inside = close < reference_high
    if swept_low and reference_low is not None:
        returned_inside = close > reference_low
    body = close - open_
    body_ratio = abs(body) / max(high - low, 0.01)
    two_sided = bool(swept_high and swept_low)
    reasons: list[str] = []
    one_way_direction = None
    if two_sided:
        path_type = "TWO_SIDED_SWEEP"
        reasons.extend(["two_sided_liquidity_search", "choppy_open_range"])
    elif reference_high is None and reference_low is None and body_ratio >= 0.6 and body > 0:
        path_type = "ONE_WAY_UP"
        one_way_direction = "UP"
        reasons.extend(["one_way_up", "open_drive_possible"])
    elif reference_high is None and reference_low is None and body_ratio >= 0.6 and body < 0:
        path_type = "ONE_WAY_DOWN"
        one_way_direction = "DOWN"
        reasons.extend(["one_way_down", "open_drive_possible"])
    elif first_extreme == "high" and (swept_high or close < open_) and returned_inside:
        path_type = "HIGH_FIRST_REVERSAL"
        reasons.extend(["high_taken_first", "close_back_inside", "possible_buy_side_manipulation"])
    elif first_extreme == "low" and (swept_low or close > open_) and returned_inside:
        path_type = "LOW_FIRST_REVERSAL"
        reasons.extend(["low_taken_first", "close_back_inside", "possible_sell_side_manipulation"])
    elif body_ratio >= 0.6 and body > 0:
        path_type = "ONE_WAY_UP"
        one_way_direction = "UP"
        reasons.extend(["one_way_up", "open_drive_possible"])
    elif body_ratio >= 0.6 and body < 0:
        path_type = "ONE_WAY_DOWN"
        one_way_direction = "DOWN"
        reasons.extend(["one_way_down", "open_drive_possible"])
    elif body_ratio < 0.3:
        path_type = "INSIDE_ROTATION"
        reasons.extend(["inside_rotation", "no_clear_acceptance"])
    else:
        path_type = "NO_CLEAR_PATH"
        reasons.append("no_clear_path")
    return CandlePathContext(
        timeframe="derived",
        candle_time=candle_time,
        open=open_,
        high=high,
        low=low,
        close=close,
        path_type=path_type,
        first_extreme=first_extreme,
        swept_high_first=bool(swept_high and first_extreme == "high"),
        swept_low_first=bool(swept_low and first_extreme == "low"),
        returned_inside=returned_inside,
        one_way_direction=one_way_direction,
        two_sided_sweep=two_sided,
        reason_codes=reasons,
    )


def _slice_inside_candle(df: pd.DataFrame, candle_time: datetime) -> pd.DataFrame:
    if "time" not in df.columns:
        return df
    times = pd.to_datetime(df["time"], utc=True)
    start = pd.Timestamp(candle_time)
    later = df[times >= start]
    return later.head(15)


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy().rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"})
    if {"o", "h", "l", "c"}.issubset(out.columns):
        return out
    return pd.DataFrame()


def _row_time(row: pd.Series) -> datetime:
    if "time" in row:
        ts = pd.Timestamp(row["time"]).to_pydatetime()
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _get(row: pd.Series, short: str, long: str) -> float:
    return row[short] if short in row else row[long]


__all__ = ["CandlePathContext", "classify_candle_path"]
