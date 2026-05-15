from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import pandas as pd

from dazro_trade.core.symbols import price_to_pips
from dazro_trade.strategy.risk_labels import RiskLabel, classify_sl_risk

log = logging.getLogger(__name__)

Outcome = Literal["SL", "TP1", "TP2", "TP3", "TP4", "BE", "STILL_OPEN", "NO_DATA"]
Direction = Literal["LONG", "SHORT"]


@dataclass
class BacktestSignal:
    timestamp: datetime
    symbol: str
    strategy: str
    direction: Direction
    entry: float
    stop: float
    tp1: float
    tp2: float | None = None
    tp3: float | None = None
    tp4: float | None = None
    rr_tp1: float = 0.0
    score: int | None = None
    session: str | None = None
    accepted: bool = True
    rejection_reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def sl_distance(self) -> float:
        return abs(float(self.entry) - float(self.stop))

    @property
    def sl_distance_usd(self) -> float:
        return round(self.sl_distance, 4)

    @property
    def sl_distance_pips(self) -> float:
        return round(price_to_pips(self.symbol, self.sl_distance), 1)

    @property
    def risk_label(self) -> RiskLabel:
        return classify_sl_risk(self.sl_distance)


@dataclass
class BacktestTrade:
    signal: BacktestSignal
    outcome: Outcome
    exit_time: datetime | None
    exit_price: float | None
    r_multiple: float
    mae: float
    mfe: float
    bars_held: int


def _normalize_m1(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy().rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"})
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], utc=True)
    return out


def simulate_trade_outcome(
    signal: BacktestSignal,
    m1_future: pd.DataFrame,
    *,
    max_bars: int = 480,
) -> BacktestTrade:
    if not signal.accepted:
        return BacktestTrade(
            signal=signal,
            outcome="NO_DATA",
            exit_time=None,
            exit_price=None,
            r_multiple=0.0,
            mae=0.0,
            mfe=0.0,
            bars_held=0,
        )
    frame = _normalize_m1(m1_future)
    if frame.empty or signal.sl_distance <= 0:
        return BacktestTrade(
            signal=signal,
            outcome="NO_DATA",
            exit_time=None,
            exit_price=None,
            r_multiple=0.0,
            mae=0.0,
            mfe=0.0,
            bars_held=0,
        )

    direction = signal.direction
    entry = float(signal.entry)
    stop = float(signal.stop)
    risk = signal.sl_distance
    enable_be = bool(signal.metadata.get("enable_be_after_tp1", False))
    initial_tps: list[tuple[str, float]] = [(label, float(level)) for label, level in (("TP1", signal.tp1), ("TP2", signal.tp2), ("TP3", signal.tp3), ("TP4", signal.tp4)) if level is not None]
    remaining_tps = list(initial_tps)

    mae = 0.0
    mfe = 0.0
    bars_held = 0
    outcome: Outcome = "STILL_OPEN"
    exit_time: datetime | None = None
    exit_price: float | None = None
    tp1_locked = False

    iter_frame = frame.head(max_bars)
    for _, candle in iter_frame.iterrows():
        bars_held += 1
        high = float(candle["h"])
        low = float(candle["l"])
        when = candle["time"].to_pydatetime() if "time" in candle and hasattr(candle["time"], "to_pydatetime") else None
        if direction == "LONG":
            adverse_excursion = max(0.0, entry - low)
            favorable_excursion = max(0.0, high - entry)
            mae = max(mae, adverse_excursion)
            mfe = max(mfe, favorable_excursion)
            sl_hit = low <= stop
            tp_hit_label: str | None = None
            for label, tp in remaining_tps:
                if high >= tp:
                    tp_hit_label = label
                    break
        else:
            adverse_excursion = max(0.0, high - entry)
            favorable_excursion = max(0.0, entry - low)
            mae = max(mae, adverse_excursion)
            mfe = max(mfe, favorable_excursion)
            sl_hit = high >= stop
            tp_hit_label = None
            for label, tp in remaining_tps:
                if low <= tp:
                    tp_hit_label = label
                    break

        if sl_hit:
            outcome = "BE" if tp1_locked else "SL"
            exit_price = stop
            exit_time = when
            break
        if tp_hit_label == "TP1" and enable_be and not tp1_locked:
            stop = entry
            tp1_locked = True
            remaining_tps = [t for t in remaining_tps if t[0] != "TP1"]
            if not remaining_tps:
                outcome = "TP1"
                exit_price = next(level for label, level in initial_tps if label == "TP1")
                exit_time = when
                break
            continue
        if tp_hit_label is not None:
            outcome = tp_hit_label  # type: ignore[assignment]
            exit_price = next(level for label, level in initial_tps if label == tp_hit_label)
            exit_time = when
            break

    r_multiple = 0.0
    if outcome == "SL":
        r_multiple = -1.0
    elif outcome == "BE":
        r_multiple = 0.0
    elif outcome in {"TP1", "TP2", "TP3", "TP4"} and exit_price is not None:
        reward = abs(float(exit_price) - entry)
        r_multiple = reward / risk if risk > 0 else 0.0

    return BacktestTrade(
        signal=signal,
        outcome=outcome,
        exit_time=exit_time,
        exit_price=exit_price,
        r_multiple=round(r_multiple, 4),
        mae=round(mae, 4),
        mfe=round(mfe, 4),
        bars_held=bars_held,
    )


__all__ = ["BacktestSignal", "BacktestTrade", "Direction", "Outcome", "simulate_trade_outcome"]
