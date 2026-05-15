from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd

from dazro_trade.core.symbols import get_symbol_spec, normalize_price, pips_to_price, price_to_pips

ExpansionDirection = Literal["LONG", "SHORT"]
TriggerKind = Literal["reclaim", "rejection", "aggressive_shift", "displacement"]
CandleModel = Literal["IMMEDIATE_EXPANSION", "ACCUMULATION_BEFORE_EXPANSION"]
H1ReferenceType = Literal["H1_HIGH", "H1_LOW"]

# Fallback statistics used by Strategy 2.0 (XAUUSD Liquidity Expansion Model)
# when live SweepStatistics has insufficient samples (< MIN_SAMPLES_REQUIRED).
# All values are in USD price distance (not pips). Derived empirically from
# historical H1 sweep behaviour on XAUUSD.
#
# Document-defined relations (kept here for traceability):
#   SL = MAX_EXCURSION * (1 + SL_BUFFER_PCT)       → SL_BUFFER_MULTIPLIER = 1.25
#   TPi = MAX_EXPANSION * quartile_i                → quartiles = 0.25, 0.50, 0.75, 1.00
H1_FALLBACK_MAE_ENTRY_USD = 45.9
H1_FALLBACK_MAX_EXCURSION_USD = 98.8
H1_FALLBACK_MAX_EXPANSION_USD = 387.2
H1_SL_BUFFER_MULTIPLIER = 1.25
TP_QUARTILES: tuple[float, float, float, float] = (0.25, 0.50, 0.75, 1.00)
MIN_SAMPLES_REQUIRED = 10


@dataclass(frozen=True)
class SweepStatistics:
    mae_avg_pips: float
    max_excursion_pips: float
    avg_expansion_pips: float
    max_expansion_pips: float
    samples: int

    @property
    def insufficient(self) -> bool:
        return self.samples < MIN_SAMPLES_REQUIRED


@dataclass(frozen=True)
class LiquidityReferenceLevels:
    h1_ref_high: float
    h1_ref_low: float
    m15_ref_high: float
    m15_ref_low: float
    h1_source: Literal["previous_h1", "range_dominant_h1"]
    m15_source: Literal["minute_45", "fallback_last_m15"]


@dataclass(frozen=True)
class H1LiquidityLevels:
    reference_price: float
    reference_type: H1ReferenceType
    entry: float
    sl_risk: float
    sl_conservative: float
    tp1: float
    tp2: float
    tp3: float
    tp4: float
    rr_to_tp1_risk: float
    rr_to_tp2_risk: float
    rr_to_tp3_risk: float
    rr_to_tp4_risk: float
    rr_to_tp1_conservative: float
    rr_to_tp2_conservative: float
    rr_to_tp3_conservative: float
    rr_to_tp4_conservative: float


@dataclass(frozen=True)
class LiquidityExpansionSignal:
    symbol: str
    direction: ExpansionDirection
    candle_model: CandleModel
    reference: LiquidityReferenceLevels
    stats: SweepStatistics
    entry: float
    stop: float
    tp1: float
    tp2: float
    tp3: float
    tp4: float
    tp1_basis: Literal["quartile_25", "avg_expansion_adaptive", "h1_reference_statistics"]
    rr_tp1: float
    rr_tp4: float
    trigger_kind: TriggerKind
    reason_codes: list[str]
    timestamp_utc: datetime
    reference_type: H1ReferenceType | None = None
    reference_price: float | None = None
    sl_risk: float | None = None
    sl_conservative: float | None = None
    rr_to_tp1_risk: float | None = None
    rr_to_tp2_risk: float | None = None
    rr_to_tp3_risk: float | None = None
    rr_to_tp4_risk: float | None = None
    rr_to_tp1_conservative: float | None = None
    rr_to_tp2_conservative: float | None = None
    rr_to_tp3_conservative: float | None = None
    rr_to_tp4_conservative: float | None = None
    mae_stats_long: dict | None = None
    mae_stats_short: dict | None = None


def _rr(entry: float, stop: float, target: float) -> float:
    risk = abs(stop - entry)
    if risk <= 0:
        return 0.0
    return round(abs(target - entry) / risk, 2)


def _price_delta(symbol: str, distance: float) -> float:
    return pips_to_price(symbol, price_to_pips(symbol, distance))


def calculate_h1_liquidity_levels(
    reference_price: float,
    reference_type: H1ReferenceType,
    pip_size: float | None = None,
    *,
    symbol: str = "XAUUSD",
    mae_stats: dict | None = None,
) -> H1LiquidityLevels:
    spec = get_symbol_spec(symbol)
    if pip_size is not None and abs(float(pip_size) - spec.pip_size) > 1e-12:
        raise ValueError("pip_size_mismatch_for_symbol")

    ref = float(reference_price)
    direction_sign = 1.0 if reference_type == "H1_HIGH" else -1.0
    target_sign = -direction_sign
    stats = mae_stats or {}
    fallback_max_excursion = H1_FALLBACK_MAX_EXCURSION_USD
    fallback_max_expansion = H1_FALLBACK_MAX_EXPANSION_USD
    entry_distance = float(stats.get("entry_distance", H1_FALLBACK_MAE_ENTRY_USD))
    sl_risk_distance = float(stats.get("sl_risk_distance", fallback_max_excursion))
    sl_conservative_distance = float(stats.get("sl_conservative_distance", fallback_max_excursion * H1_SL_BUFFER_MULTIPLIER))
    tp1_distance = float(stats.get("tp1_distance", fallback_max_expansion * TP_QUARTILES[0]))
    tp2_distance = float(stats.get("tp2_distance", fallback_max_expansion * TP_QUARTILES[1]))
    tp3_distance = float(stats.get("tp3_distance", fallback_max_expansion * TP_QUARTILES[2]))
    tp4_distance = float(stats.get("tp4_distance", fallback_max_expansion * TP_QUARTILES[3]))
    entry = ref + direction_sign * _price_delta(symbol, entry_distance)
    sl_risk = ref + direction_sign * _price_delta(symbol, sl_risk_distance)
    sl_conservative = ref + direction_sign * _price_delta(symbol, sl_conservative_distance)
    tp1 = ref + target_sign * _price_delta(symbol, tp1_distance)
    tp2 = ref + target_sign * _price_delta(symbol, tp2_distance)
    tp3 = ref + target_sign * _price_delta(symbol, tp3_distance)
    tp4 = ref + target_sign * _price_delta(symbol, tp4_distance)

    return H1LiquidityLevels(
        reference_price=normalize_price(symbol, ref),
        reference_type=reference_type,
        entry=normalize_price(symbol, entry),
        sl_risk=normalize_price(symbol, sl_risk),
        sl_conservative=normalize_price(symbol, sl_conservative),
        tp1=normalize_price(symbol, tp1),
        tp2=normalize_price(symbol, tp2),
        tp3=normalize_price(symbol, tp3),
        tp4=normalize_price(symbol, tp4),
        rr_to_tp1_risk=_rr(entry, sl_risk, tp1),
        rr_to_tp2_risk=_rr(entry, sl_risk, tp2),
        rr_to_tp3_risk=_rr(entry, sl_risk, tp3),
        rr_to_tp4_risk=_rr(entry, sl_risk, tp4),
        rr_to_tp1_conservative=_rr(entry, sl_conservative, tp1),
        rr_to_tp2_conservative=_rr(entry, sl_conservative, tp2),
        rr_to_tp3_conservative=_rr(entry, sl_conservative, tp3),
        rr_to_tp4_conservative=_rr(entry, sl_conservative, tp4),
    )


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy().rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"})
    if not {"o", "h", "l", "c"}.issubset(out.columns):
        return pd.DataFrame()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], utc=True)
    return out


def _localize_minute(ts: pd.Timestamp, timezone_name: str) -> int | None:
    if timezone_name == "broker":
        return int(ts.minute)
    try:
        zone = ZoneInfo(timezone_name)
        return int(ts.tz_convert(zone).minute)
    except Exception:
        return None


def build_reference_levels(
    h1_df: pd.DataFrame,
    m15_df: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
    range_in_range_max_pips: float = 30.0,
    m15_reference_timezone: str = "broker",
) -> LiquidityReferenceLevels | None:
    h1 = _normalize(h1_df)
    m15 = _normalize(m15_df)
    if len(h1) < 2:
        return None

    closed_h1 = h1.iloc[:-1] if "time" in h1.columns and len(h1) >= 2 else h1
    if len(closed_h1) < 1:
        return None

    range_in_range_price = pips_to_price(symbol, range_in_range_max_pips)
    h1_source: Literal["previous_h1", "range_dominant_h1"] = "previous_h1"

    if len(closed_h1) >= 3:
        last_three = closed_h1.iloc[-3:]
        span = float(last_three["h"].max()) - float(last_three["l"].min())
        if span <= range_in_range_price:
            bodies = (last_three["c"].astype(float) - last_three["o"].astype(float)).abs()
            dominant_idx = int(bodies.idxmax())
            dominant_row = last_three.loc[dominant_idx]
            h1_ref_high = float(dominant_row["h"])
            h1_ref_low = float(dominant_row["l"])
            h1_source = "range_dominant_h1"
        else:
            prev = closed_h1.iloc[-1]
            h1_ref_high = float(prev["h"])
            h1_ref_low = float(prev["l"])
    else:
        prev = closed_h1.iloc[-1]
        h1_ref_high = float(prev["h"])
        h1_ref_low = float(prev["l"])

    if len(m15) == 0 or "time" not in m15.columns:
        return None

    latest_h1_open = pd.Timestamp(h1.iloc[-1]["time"]) if "time" in h1.columns else None
    if latest_h1_open is None:
        return None
    previous_h1_open = latest_h1_open - pd.Timedelta(hours=1)

    m15_in_prev = m15[(m15["time"] >= previous_h1_open) & (m15["time"] < latest_h1_open)]
    selected_m15: pd.Series | None = None
    m15_source: Literal["minute_45", "fallback_last_m15"] = "fallback_last_m15"

    for _, row in m15_in_prev.iterrows():
        minute = _localize_minute(pd.Timestamp(row["time"]), m15_reference_timezone)
        if minute == 45:
            selected_m15 = row
            m15_source = "minute_45"
            break

    if selected_m15 is None:
        before_h1 = m15[m15["time"] < latest_h1_open]
        if len(before_h1) == 0:
            return None
        selected_m15 = before_h1.iloc[-1]
        m15_source = "fallback_last_m15"

    return LiquidityReferenceLevels(
        h1_ref_high=h1_ref_high,
        h1_ref_low=h1_ref_low,
        m15_ref_high=float(selected_m15["h"]),
        m15_ref_low=float(selected_m15["l"]),
        h1_source=h1_source,
        m15_source=m15_source,
    )


def compute_h1_sweep_stats(
    h1_df: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
    lookback_h1: int = 60,
) -> SweepStatistics:
    h1 = _normalize(h1_df)
    if len(h1) < 4:
        return SweepStatistics(0.0, 0.0, 0.0, 0.0, 0)

    closed = h1.iloc[:-1] if "time" in h1.columns else h1
    closed = closed.tail(lookback_h1).reset_index(drop=True)
    if len(closed) < 4:
        return SweepStatistics(0.0, 0.0, 0.0, 0.0, 0)

    mae_samples: list[float] = []
    exp_samples_valid: list[float] = []
    exp_samples_all: list[float] = []

    for i in range(1, len(closed) - 2):
        prev_h = float(closed["h"].iloc[i - 1])
        prev_l = float(closed["l"].iloc[i - 1])
        cur_h = float(closed["h"].iloc[i])
        cur_l = float(closed["l"].iloc[i])
        next1_l = float(closed["l"].iloc[i + 1])
        next1_h = float(closed["h"].iloc[i + 1])
        next2_l = float(closed["l"].iloc[i + 2])
        next2_h = float(closed["h"].iloc[i + 2])
        next1_c = float(closed["c"].iloc[i + 1])
        next2_c = float(closed["c"].iloc[i + 2])

        if cur_h > prev_h:
            level = prev_h
            mae = max(0.0, cur_h - level)
            expansion = max(0.0, level - min(next1_l, next2_l))
            invalidated = next1_c > level or next2_c > level
            mae_samples.append(price_to_pips(symbol, mae))
            exp_samples_all.append(price_to_pips(symbol, expansion))
            if not invalidated:
                exp_samples_valid.append(price_to_pips(symbol, expansion))

        if cur_l < prev_l:
            level = prev_l
            mae = max(0.0, level - cur_l)
            expansion = max(0.0, max(next1_h, next2_h) - level)
            invalidated = next1_c < level or next2_c < level
            mae_samples.append(price_to_pips(symbol, mae))
            exp_samples_all.append(price_to_pips(symbol, expansion))
            if not invalidated:
                exp_samples_valid.append(price_to_pips(symbol, expansion))

    samples = len(mae_samples)
    if samples == 0:
        return SweepStatistics(0.0, 0.0, 0.0, 0.0, 0)

    mae_avg = sum(mae_samples) / samples
    max_exc = max(mae_samples)
    avg_exp = sum(exp_samples_valid) / len(exp_samples_valid) if exp_samples_valid else 0.0
    max_exp = max(exp_samples_all) if exp_samples_all else 0.0

    return SweepStatistics(
        mae_avg_pips=round(mae_avg, 2),
        max_excursion_pips=round(max_exc, 2),
        avg_expansion_pips=round(avg_exp, 2),
        max_expansion_pips=round(max_exp, 2),
        samples=samples,
    )


def build_live_mae_stats(stats: SweepStatistics, symbol: str) -> dict[str, float]:
    return {
        "entry_distance": pips_to_price(symbol, stats.mae_avg_pips),
        "sl_risk_distance": pips_to_price(symbol, stats.max_excursion_pips),
        "sl_conservative_distance": pips_to_price(symbol, stats.max_excursion_pips * H1_SL_BUFFER_MULTIPLIER),
        "tp1_distance": pips_to_price(symbol, stats.max_expansion_pips * TP_QUARTILES[0]),
        "tp2_distance": pips_to_price(symbol, stats.max_expansion_pips * TP_QUARTILES[1]),
        "tp3_distance": pips_to_price(symbol, stats.max_expansion_pips * TP_QUARTILES[2]),
        "tp4_distance": pips_to_price(symbol, stats.max_expansion_pips * TP_QUARTILES[3]),
    }


def _detect_trigger(
    m1: pd.DataFrame,
    m5: pd.DataFrame,
    direction: ExpansionDirection,
    h1_ref_low: float,
    h1_ref_high: float,
) -> TriggerKind | None:
    if len(m1) < 4:
        return None
    closed_m1 = m1.iloc[:-1] if "time" in m1.columns and len(m1) > 3 else m1
    if len(closed_m1) < 3:
        return None

    last3 = closed_m1.iloc[-3:]
    last = closed_m1.iloc[-1]
    prev = closed_m1.iloc[-2]

    o = float(last["o"])
    c = float(last["c"])
    h = float(last["h"])
    l = float(last["l"])
    body = abs(c - o)

    if direction == "LONG":
        if bool((last3["c"].astype(float) >= h1_ref_low).any()):
            return "reclaim"
        lower_wick = min(o, c) - l
        if body > 0 and lower_wick > body * 1.5 and c > o:
            return "rejection"
        if c > float(prev["h"]):
            return "aggressive_shift"
    else:
        if bool((last3["c"].astype(float) <= h1_ref_high).any()):
            return "reclaim"
        upper_wick = h - max(o, c)
        if body > 0 and upper_wick > body * 1.5 and c < o:
            return "rejection"
        if c < float(prev["l"]):
            return "aggressive_shift"

    closed_m5 = m5.iloc[:-1] if "time" in m5.columns and len(m5) > 6 else m5
    if len(closed_m5) >= 6:
        bodies_m5 = (closed_m5["c"].astype(float) - closed_m5["o"].astype(float)).abs()
        last_m5 = closed_m5.iloc[-1]
        avg_body = float(bodies_m5.iloc[-6:-1].mean() or 0.0)
        last_body = abs(float(last_m5["c"]) - float(last_m5["o"]))
        if avg_body > 0 and last_body >= avg_body * 1.2:
            bullish = float(last_m5["c"]) > float(last_m5["o"])
            if direction == "LONG" and bullish:
                return "displacement"
            if direction == "SHORT" and not bullish:
                return "displacement"

    return None


def _classify_candle_model(h1_df: pd.DataFrame) -> CandleModel:
    closed = h1_df.iloc[:-1] if "time" in h1_df.columns and len(h1_df) > 2 else h1_df
    if len(closed) < 2:
        return "IMMEDIATE_EXPANSION"
    a = closed.iloc[-2]
    b = closed.iloc[-1]
    a_h, a_l = float(a["h"]), float(a["l"])
    b_h, b_l = float(b["h"]), float(b["l"])
    overlap = min(a_h, b_h) >= max(a_l, b_l)
    if not overlap:
        return "IMMEDIATE_EXPANSION"
    body_a = abs(float(a["c"]) - float(a["o"]))
    body_b = abs(float(b["c"]) - float(b["o"]))
    range_a = max(a_h - a_l, 1e-9)
    range_b = max(b_h - b_l, 1e-9)
    ratio = max(body_a / range_a, body_b / range_b)
    if ratio < 0.6:
        return "ACCUMULATION_BEFORE_EXPANSION"
    return "IMMEDIATE_EXPANSION"


@dataclass
class LiquidityExpansionDiagnostics:
    total_calls: int = 0
    skip_missing_data: int = 0
    skip_no_reference: int = 0
    skip_insufficient_stats: int = 0
    skip_no_current_window: int = 0
    h1_sweep_long_detected: int = 0
    h1_sweep_short_detected: int = 0
    m15_long_validity_passed: int = 0
    m15_short_validity_passed: int = 0
    skip_no_validity: int = 0
    skip_mae_gate_failed: int = 0
    skip_no_trigger: int = 0
    skip_invalid_risk: int = 0
    signals_emitted: int = 0
    long_signals: int = 0
    short_signals: int = 0
    trigger_kind_counts: dict[str, int] = field(default_factory=dict)
    driver_timeframe: str = "M15"
    setup_timeframe: str = "M15"
    refinement_timeframe: str = "M5"
    trigger_timeframe: str = "M1"
    htf_context_timeframes: list[str] = field(default_factory=lambda: ["D1", "H4", "H1"])
    first_eval_time: datetime | None = None
    last_eval_time: datetime | None = None

    def rejections_by_layer(self) -> dict[str, int]:
        layers: dict[str, int] = {}
        mapping = [
            ("DATA", self.skip_missing_data),
            ("HTF_CONTEXT", self.skip_no_reference + self.skip_insufficient_stats),
            ("SETUP_M15", self.skip_no_current_window + self.skip_no_validity),
            ("REFINEMENT_M5", self.skip_mae_gate_failed),
            ("TRIGGER_M1", self.skip_no_trigger),
            ("RISK", self.skip_invalid_risk),
        ]
        for layer, count in mapping:
            if count > 0:
                layers[layer] = count
        return layers

    def signals_per_day(self) -> float:
        if self.signals_emitted <= 0 or self.first_eval_time is None or self.last_eval_time is None:
            return 0.0
        delta = (self.last_eval_time - self.first_eval_time).total_seconds() / 86400.0
        if delta <= 0:
            return 0.0
        return round(self.signals_emitted / delta, 4)

    def to_dict(self) -> dict:
        return {
            "evaluation_count": self.total_calls,
            "driver_timeframe": self.driver_timeframe,
            "setup_timeframe": self.setup_timeframe,
            "refinement_timeframe": self.refinement_timeframe,
            "trigger_timeframe": self.trigger_timeframe,
            "htf_context_timeframes": list(self.htf_context_timeframes),
            "total_calls": self.total_calls,
            "skip_missing_data": self.skip_missing_data,
            "skip_no_reference": self.skip_no_reference,
            "skip_insufficient_stats": self.skip_insufficient_stats,
            "skip_no_current_window": self.skip_no_current_window,
            "h1_sweep_long_detected": self.h1_sweep_long_detected,
            "h1_sweep_short_detected": self.h1_sweep_short_detected,
            "m15_long_validity_passed": self.m15_long_validity_passed,
            "m15_short_validity_passed": self.m15_short_validity_passed,
            "skip_no_validity": self.skip_no_validity,
            "skip_mae_gate_failed": self.skip_mae_gate_failed,
            "skip_no_trigger": self.skip_no_trigger,
            "skip_invalid_risk": self.skip_invalid_risk,
            "signals_emitted": self.signals_emitted,
            "signals_per_day": self.signals_per_day(),
            "long_signals": self.long_signals,
            "short_signals": self.short_signals,
            "trigger_kind_counts": dict(self.trigger_kind_counts),
            "rejections_by_layer": self.rejections_by_layer(),
            "first_eval_time": self.first_eval_time.isoformat() if self.first_eval_time else None,
            "last_eval_time": self.last_eval_time.isoformat() if self.last_eval_time else None,
        }


def evaluate_liquidity_expansion(
    m1_df: pd.DataFrame,
    m5_df: pd.DataFrame,
    m15_df: pd.DataFrame,
    h1_df: pd.DataFrame,
    *,
    current_price: float,
    symbol: str = "XAUUSD",
    lookback_h1: int = 60,
    range_in_range_max_pips: float = 30.0,
    m15_reference_timezone: str = "broker",
    now_utc: datetime | None = None,
    session: str | None = None,
    mae_engine_enabled: bool = False,
    mae_db_path: str | None = None,
    volatility_regime: str | None = None,
    diagnostics: LiquidityExpansionDiagnostics | None = None,
) -> LiquidityExpansionSignal | None:
    if diagnostics is not None:
        diagnostics.total_calls += 1
    m1 = _normalize(m1_df)
    m5 = _normalize(m5_df)
    m15 = _normalize(m15_df)
    h1 = _normalize(h1_df)
    if len(m1) == 0 or len(m5) == 0 or len(m15) == 0 or len(h1) < 2:
        if diagnostics is not None:
            diagnostics.skip_missing_data += 1
        return None
    if "time" not in m1.columns or "time" not in h1.columns:
        if diagnostics is not None:
            diagnostics.skip_missing_data += 1
        return None

    reference = build_reference_levels(
        h1, m15,
        symbol=symbol,
        range_in_range_max_pips=range_in_range_max_pips,
        m15_reference_timezone=m15_reference_timezone,
    )
    if reference is None:
        if diagnostics is not None:
            diagnostics.skip_no_reference += 1
        return None

    stats = compute_h1_sweep_stats(h1, symbol=symbol, lookback_h1=lookback_h1)
    if stats.insufficient:
        if diagnostics is not None:
            diagnostics.skip_insufficient_stats += 1
        return None

    latest_h1_open = pd.Timestamp(h1.iloc[-1]["time"])
    current_window = m1[m1["time"] >= latest_h1_open]
    if len(current_window) == 0:
        if diagnostics is not None:
            diagnostics.skip_no_current_window += 1
        return None

    high_m15_hits = current_window[current_window["h"].astype(float) >= reference.m15_ref_high]
    low_m15_hits = current_window[current_window["l"].astype(float) <= reference.m15_ref_low]
    high_h1_hits = current_window[current_window["h"].astype(float) >= reference.h1_ref_high]
    low_h1_hits = current_window[current_window["l"].astype(float) <= reference.h1_ref_low]

    t_high_m15 = pd.Timestamp(high_m15_hits.iloc[0]["time"]) if len(high_m15_hits) else None
    t_low_m15 = pd.Timestamp(low_m15_hits.iloc[0]["time"]) if len(low_m15_hits) else None
    t_high_h1 = pd.Timestamp(high_h1_hits.iloc[0]["time"]) if len(high_h1_hits) else None
    t_low_h1 = pd.Timestamp(low_h1_hits.iloc[0]["time"]) if len(low_h1_hits) else None

    long_valid = t_low_h1 is not None and (t_high_m15 is None or t_low_h1 <= t_high_m15)
    short_valid = t_high_h1 is not None and (t_low_m15 is None or t_high_h1 <= t_low_m15)
    if diagnostics is not None:
        if t_low_h1 is not None:
            diagnostics.h1_sweep_long_detected += 1
        if t_high_h1 is not None:
            diagnostics.h1_sweep_short_detected += 1
        if long_valid:
            diagnostics.m15_long_validity_passed += 1
        if short_valid:
            diagnostics.m15_short_validity_passed += 1
        if not long_valid and not short_valid:
            diagnostics.skip_no_validity += 1

    live_mae_stats = build_live_mae_stats(stats, symbol)
    tp1_standard_pips = stats.max_expansion_pips * TP_QUARTILES[0]
    use_adaptive_tp1 = (
        0 < stats.avg_expansion_pips < tp1_standard_pips
    )
    if use_adaptive_tp1:
        live_mae_stats["tp1_distance"] = pips_to_price(symbol, stats.avg_expansion_pips)
    mae_stats_long: dict = live_mae_stats
    mae_stats_short: dict = live_mae_stats
    if mae_engine_enabled:
        try:
            from dazro_trade.strategy.mae_engine import load_mae_stats_for_bucket
            db_path = mae_db_path or "data/darzo_trade.db"
            db_long = load_mae_stats_for_bucket(
                session=session,
                reference_type="H1_LOW",
                volatility_regime=volatility_regime,
                db_path=db_path,
            )
            db_short = load_mae_stats_for_bucket(
                session=session,
                reference_type="H1_HIGH",
                volatility_regime=volatility_regime,
                db_path=db_path,
            )
            if db_long:
                mae_stats_long = db_long
            if db_short:
                mae_stats_short = db_short
        except Exception:
            pass
    long_levels = calculate_h1_liquidity_levels(reference.h1_ref_low, "H1_LOW", symbol=symbol, mae_stats=mae_stats_long)
    short_levels = calculate_h1_liquidity_levels(reference.h1_ref_high, "H1_HIGH", symbol=symbol, mae_stats=mae_stats_short)

    direction: ExpansionDirection | None = None
    levels: H1LiquidityLevels | None = None
    if long_valid and current_price <= long_levels.entry:
        direction = "LONG"
        levels = long_levels
    elif short_valid and current_price >= short_levels.entry:
        direction = "SHORT"
        levels = short_levels

    if direction is None:
        if diagnostics is not None:
            diagnostics.skip_mae_gate_failed += 1
        return None
    assert levels is not None

    trigger = _detect_trigger(m1, m5, direction, reference.h1_ref_low, reference.h1_ref_high)
    if trigger is None:
        if diagnostics is not None:
            diagnostics.skip_no_trigger += 1
        return None

    entry = levels.entry
    stop = levels.sl_conservative
    tp1_basis: Literal["quartile_25", "avg_expansion_adaptive", "h1_reference_statistics"] = (
        "avg_expansion_adaptive" if use_adaptive_tp1 else "quartile_25"
    )

    candle_model = _classify_candle_model(h1)

    reason_codes = [
        "liquidity_expansion_model_2_0",
        f"trigger_{trigger}",
        f"h1_source_{reference.h1_source}",
        f"m15_source_{reference.m15_source}",
        f"candle_model_{candle_model.lower()}",
        "h1_reference_level_based_levels",
        f"reference_type_{levels.reference_type.lower()}",
    ]

    if diagnostics is not None:
        diagnostics.signals_emitted += 1
        if direction == "LONG":
            diagnostics.long_signals += 1
        else:
            diagnostics.short_signals += 1
        diagnostics.trigger_kind_counts[trigger] = diagnostics.trigger_kind_counts.get(trigger, 0) + 1

    return LiquidityExpansionSignal(
        symbol=symbol,
        direction=direction,
        candle_model=candle_model,
        reference=reference,
        stats=stats,
        entry=entry,
        stop=stop,
        tp1=levels.tp1,
        tp2=levels.tp2,
        tp3=levels.tp3,
        tp4=levels.tp4,
        tp1_basis=tp1_basis,
        rr_tp1=levels.rr_to_tp1_conservative,
        rr_tp4=levels.rr_to_tp4_conservative,
        trigger_kind=trigger,
        reason_codes=reason_codes,
        timestamp_utc=now_utc or datetime.now(timezone.utc),
        reference_type=levels.reference_type,
        reference_price=levels.reference_price,
        sl_risk=levels.sl_risk,
        sl_conservative=levels.sl_conservative,
        rr_to_tp1_risk=levels.rr_to_tp1_risk,
        rr_to_tp2_risk=levels.rr_to_tp2_risk,
        rr_to_tp3_risk=levels.rr_to_tp3_risk,
        rr_to_tp4_risk=levels.rr_to_tp4_risk,
        rr_to_tp1_conservative=levels.rr_to_tp1_conservative,
        rr_to_tp2_conservative=levels.rr_to_tp2_conservative,
        rr_to_tp3_conservative=levels.rr_to_tp3_conservative,
        rr_to_tp4_conservative=levels.rr_to_tp4_conservative,
        mae_stats_long=mae_stats_long,
        mae_stats_short=mae_stats_short,
    )


__all__ = [
    "SweepStatistics",
    "H1LiquidityLevels",
    "H1ReferenceType",
    "LiquidityExpansionDiagnostics",
    "LiquidityReferenceLevels",
    "LiquidityExpansionSignal",
    "build_live_mae_stats",
    "build_reference_levels",
    "calculate_h1_liquidity_levels",
    "compute_h1_sweep_stats",
    "evaluate_liquidity_expansion",
]
