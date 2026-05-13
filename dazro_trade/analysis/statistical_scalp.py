from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import pandas as pd

from dazro_trade.analysis.number_theory import has_number_theory_confluence
from dazro_trade.analysis.vwap import vwap_snapshot
from dazro_trade.core.symbols import pips_to_price


@dataclass(frozen=True)
class StatisticalScalpSignal:
    symbol: str
    direction: Literal["LONG", "SHORT"]
    entry: float
    stop: float
    tp: float
    rr: float
    z_score: float
    vwap: float
    sigma: float
    reason_codes: list[str]
    timestamp_utc: datetime


def evaluate_statistical_scalp(
    m5_df: pd.DataFrame,
    *,
    current_price: float,
    symbol: str = "XAUUSD",
    tolerance_pips_to_band: float = 0.5,
    min_abs_z: float = 2.0,
    nt_tolerance_pips: float = 1.2,
    now_utc: datetime | None = None,
) -> StatisticalScalpSignal | None:
    snap = vwap_snapshot(m5_df, current_price)
    if snap is None or snap.std <= 0:
        return None
    if abs(snap.z_score) < min_abs_z:
        return None
    tolerance = pips_to_price(symbol, tolerance_pips_to_band)
    if snap.z_score <= -min_abs_z and abs(current_price - snap.lower_2) <= tolerance:
        direction: Literal["LONG", "SHORT"] = "LONG"
        stop_dist = snap.std * 0.75
        stop = current_price - stop_dist
        tp = current_price + stop_dist
    elif snap.z_score >= min_abs_z and abs(current_price - snap.upper_2) <= tolerance:
        direction = "SHORT"
        stop_dist = snap.std * 0.75
        stop = current_price + stop_dist
        tp = current_price - stop_dist
    else:
        return None
    nt = has_number_theory_confluence(current_price, symbol=symbol, tolerance_pips=nt_tolerance_pips)
    if not nt["confluence"]:
        return None
    return StatisticalScalpSignal(
        symbol=symbol,
        direction=direction,
        entry=round(float(current_price), 2),
        stop=round(float(stop), 2),
        tp=round(float(tp), 2),
        rr=1.0,
        z_score=snap.z_score,
        vwap=snap.vwap,
        sigma=snap.std,
        reason_codes=[
            "statistical_mean_reversion",
            f"z={round(snap.z_score, 2)}",
            "vwap_2sigma_extension",
            "number_theory_confluence",
            f"nt_tier={nt['tier']}",
        ],
        timestamp_utc=now_utc or datetime.now(timezone.utc),
    )


__all__ = ["StatisticalScalpSignal", "evaluate_statistical_scalp"]
