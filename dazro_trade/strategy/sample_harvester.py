from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import pandas as pd

from dazro_trade.storage.mae_sample_repository import save_mae_sample

log = logging.getLogger(__name__)

VolatilityRegime = Literal["high_volatility", "low_volatility", "normal", "unknown"]


@dataclass(frozen=True)
class HarvestedSample:
    reference_type: Literal["H1_HIGH", "H1_LOW"]
    reference_price: float
    sample_high: float
    sample_low: float
    sample_open: float
    sample_close: float
    manipulation_extreme: float
    manipulation_depth: float
    distribution_direction: Literal["bullish", "bearish"]
    distribution_reached: bool
    distribution_reach_max_price: float
    distribution_reach_distance: float
    max_favorable_excursion_price: float
    mfe_distance: float
    candle_time: datetime | None
    session: str | None
    volatility_regime: VolatilityRegime


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy().rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"})
    if not {"o", "h", "l", "c"}.issubset(out.columns):
        return pd.DataFrame()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], utc=True)
    return out


def _true_range(prev_close: float, h: float, l: float) -> float:
    return max(h - l, abs(h - prev_close), abs(l - prev_close))


def classify_volatility_regime(
    m15_df: pd.DataFrame,
    *,
    atr_period: int = 14,
    median_lookback: int = 100,
    high_multiplier: float = 1.3,
    low_multiplier: float = 0.7,
) -> VolatilityRegime:
    frame = _normalize(m15_df)
    if len(frame) < atr_period + 2:
        return "unknown"
    closes = frame["c"].astype(float).tolist()
    highs = frame["h"].astype(float).tolist()
    lows = frame["l"].astype(float).tolist()
    tr_values: list[float] = []
    for i in range(1, len(frame)):
        tr_values.append(_true_range(closes[i - 1], highs[i], lows[i]))
    if len(tr_values) < atr_period:
        return "unknown"
    atr_series: list[float] = []
    for end in range(atr_period, len(tr_values) + 1):
        atr_series.append(statistics.fmean(tr_values[end - atr_period:end]))
    if len(atr_series) < 2:
        return "unknown"
    atr_now = atr_series[-1]
    history = atr_series[-min(len(atr_series), median_lookback):]
    if len(history) < 2:
        return "unknown"
    median_atr = statistics.median(history)
    if median_atr <= 0:
        return "unknown"
    ratio = atr_now / median_atr
    if ratio >= high_multiplier:
        return "high_volatility"
    if ratio <= low_multiplier:
        return "low_volatility"
    return "normal"


def detect_manipulation_distribution(
    h1_df: pd.DataFrame,
    m15_df: pd.DataFrame,
    *,
    session: str | None = None,
    close_back_inside_max_m15_candles: int = 4,
    volatility_regime: VolatilityRegime | None = None,
) -> HarvestedSample | None:
    h1 = _normalize(h1_df)
    m15 = _normalize(m15_df)
    if len(h1) < 3:
        return None
    closed_h1 = h1.iloc[:-1] if "time" in h1.columns and len(h1) > 1 else h1
    if len(closed_h1) < 2:
        return None
    reference_candle = closed_h1.iloc[-2]
    distribution_candle = closed_h1.iloc[-1]
    ref_high = float(reference_candle["h"])
    ref_low = float(reference_candle["l"])
    dist_high = float(distribution_candle["h"])
    dist_low = float(distribution_candle["l"])
    dist_close = float(distribution_candle["c"])
    dist_open = float(distribution_candle["o"])
    candle_time = pd.Timestamp(distribution_candle["time"]).to_pydatetime() if "time" in distribution_candle else None

    reference_type: Literal["H1_HIGH", "H1_LOW"] | None = None
    reference_price = 0.0
    manipulation_extreme = 0.0
    distribution_direction: Literal["bullish", "bearish"] | None = None
    distribution_reach_max_price = 0.0
    if dist_high > ref_high and dist_close < ref_high:
        reference_type = "H1_HIGH"
        reference_price = ref_high
        manipulation_extreme = dist_high
        distribution_direction = "bearish"
        distribution_reach_max_price = dist_low
    elif dist_low < ref_low and dist_close > ref_low:
        reference_type = "H1_LOW"
        reference_price = ref_low
        manipulation_extreme = dist_low
        distribution_direction = "bullish"
        distribution_reach_max_price = dist_high
    else:
        return None

    if "time" in m15.columns and candle_time is not None:
        prev_h1_start = pd.Timestamp(distribution_candle["time"])
        prev_h1_end = prev_h1_start + pd.Timedelta(hours=1)
        m15_window = m15[(m15["time"] >= prev_h1_start) & (m15["time"] < prev_h1_end)]
        if len(m15_window) > close_back_inside_max_m15_candles:
            m15_window = m15_window.head(close_back_inside_max_m15_candles)
        close_back_inside = bool(
            (
                (reference_type == "H1_HIGH" and (m15_window["c"].astype(float) < reference_price).any())
                or (reference_type == "H1_LOW" and (m15_window["c"].astype(float) > reference_price).any())
            )
        ) if len(m15_window) > 0 else True
        if not close_back_inside:
            return None

    manipulation_depth = (
        manipulation_extreme - reference_price
        if reference_type == "H1_HIGH"
        else reference_price - manipulation_extreme
    )
    if manipulation_depth <= 0:
        return None

    distribution_reach_distance = (
        reference_price - distribution_reach_max_price
        if reference_type == "H1_HIGH"
        else distribution_reach_max_price - reference_price
    )
    mfe_distance = max(0.0, distribution_reach_distance)

    return HarvestedSample(
        reference_type=reference_type,
        reference_price=reference_price,
        sample_high=dist_high,
        sample_low=dist_low,
        sample_open=dist_open,
        sample_close=dist_close,
        manipulation_extreme=manipulation_extreme,
        manipulation_depth=manipulation_depth,
        distribution_direction=distribution_direction,
        distribution_reached=True,
        distribution_reach_max_price=distribution_reach_max_price,
        distribution_reach_distance=distribution_reach_distance,
        max_favorable_excursion_price=distribution_reach_max_price,
        mfe_distance=mfe_distance,
        candle_time=candle_time,
        session=session,
        volatility_regime=volatility_regime or "unknown",
    )


def persist_harvested_sample(sample: HarvestedSample, *, db_path: str) -> int | None:
    payload: dict[str, Any] = {
        "reference_type": sample.reference_type,
        "reference_price": sample.reference_price,
        "sample_high": sample.sample_high,
        "sample_low": sample.sample_low,
        "sample_open": sample.sample_open,
        "sample_close": sample.sample_close,
        "manipulation_extreme": sample.manipulation_extreme,
        "manipulation_depth": sample.manipulation_depth,
        "distribution_direction": sample.distribution_direction,
        "distribution_reached": 1 if sample.distribution_reached else 0,
        "distribution_reach_max_price": sample.distribution_reach_max_price,
        "distribution_reach_distance": sample.distribution_reach_distance,
        "max_favorable_excursion_price": sample.max_favorable_excursion_price,
        "mfe_distance": sample.mfe_distance,
        "candle_time": sample.candle_time.isoformat() if sample.candle_time else None,
        "session": sample.session,
        "volatility_regime": sample.volatility_regime,
    }
    return save_mae_sample(payload, db_path=db_path)


__all__ = [
    "HarvestedSample",
    "VolatilityRegime",
    "classify_volatility_regime",
    "detect_manipulation_distribution",
    "persist_harvested_sample",
]
