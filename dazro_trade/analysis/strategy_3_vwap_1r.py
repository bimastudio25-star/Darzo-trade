from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import pandas as pd

from dazro_trade.adelin.liquidity_map import build_liquidity_map, find_swept_level
from dazro_trade.adelin.number_theory import nearest_number_theory
from dazro_trade.adelin.sweep_detector import find_liquidity_sweep
from dazro_trade.adelin.volume_profile import build_multi_anchor_volume_profiles, find_best_volume_crack_confluence
from dazro_trade.analysis.vwap import VwapSnapshot, vwap_snapshot
from dazro_trade.core.symbols import get_symbol_spec, normalize_price, price_to_pips, pips_to_price

Strategy3SetupMode = Literal["trend_following", "reversal", "no_trade"]
Strategy3Direction = Literal["LONG", "SHORT"]


@dataclass(frozen=True)
class Strategy3Config:
    max_liquidity_distance_pips: float = 120.0
    band_tolerance_pips: float = 25.0
    stop_buffer_pips: float = 8.0
    min_stop_pips: float = 8.0
    max_stop_pips: float = 80.0
    number_theory_tolerance_pips: float = 15.0
    volume_tolerance_pips: float = 8.0


@dataclass(frozen=True)
class Strategy3Signal:
    symbol: str
    direction: Strategy3Direction
    setup_mode: Strategy3SetupMode
    entry: float
    stop: float
    tp1: float
    rr_tp1: float
    timestamp_utc: datetime
    reason_codes: list[str]
    confluences: dict[str, Any]
    vwap_distance_pips: float
    band_touched: str
    liquidity_context: dict[str, Any]
    fvg_ifvg_context: dict[str, Any]
    number_theory_context: dict[str, Any]


@dataclass
class Strategy3Diagnostics:
    total_calls: int = 0
    skip_missing_data: int = 0
    no_trade_count: int = 0
    signals_emitted: int = 0
    setup_modes: dict[str, int] = field(default_factory=dict)
    rejected_reasons: dict[str, int] = field(default_factory=dict)
    long_signals: int = 0
    short_signals: int = 0
    driver_timeframe: str = "M15"
    setup_timeframe: str = "M15"
    refinement_timeframe: str = "M5"
    trigger_timeframe: str = "M1"
    htf_context_timeframes: list[str] = field(default_factory=lambda: ["D1", "H4", "H1"])
    first_eval_time: datetime | None = None
    last_eval_time: datetime | None = None

    def record_rejection(self, reason: str) -> None:
        self.rejected_reasons[reason] = self.rejected_reasons.get(reason, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        signals_per_day = 0.0
        if self.signals_emitted > 0 and self.first_eval_time and self.last_eval_time:
            days = (self.last_eval_time - self.first_eval_time).total_seconds() / 86400.0
            signals_per_day = round(self.signals_emitted / days, 4) if days > 0 else 0.0
        return {
            "evaluation_count": self.total_calls,
            "driver_timeframe": self.driver_timeframe,
            "setup_timeframe": self.setup_timeframe,
            "refinement_timeframe": self.refinement_timeframe,
            "trigger_timeframe": self.trigger_timeframe,
            "htf_context_timeframes": list(self.htf_context_timeframes),
            "skip_missing_data": self.skip_missing_data,
            "no_trade_count": self.no_trade_count,
            "signals_emitted": self.signals_emitted,
            "signals_per_day": signals_per_day,
            "setup_modes": dict(self.setup_modes),
            "rejected_reasons": dict(self.rejected_reasons),
            "long_signals": self.long_signals,
            "short_signals": self.short_signals,
            "first_eval_time": self.first_eval_time.isoformat() if self.first_eval_time else None,
            "last_eval_time": self.last_eval_time.isoformat() if self.last_eval_time else None,
        }


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    rename = {
        source: alias
        for source, alias in {"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"}.items()
        if source in df.columns and alias not in df.columns
    }
    out = df.copy().rename(columns=rename)
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], utc=True)
    if {"o", "h", "l", "c"}.issubset(out.columns):
        return out
    return pd.DataFrame()


def _latest_price(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    return float(frame["c"].iloc[-1])


def _band_touch(snapshot: VwapSnapshot, price: float, pip_size: float, tolerance_pips: float) -> tuple[str, float]:
    bands = {
        "vwap": snapshot.vwap,
        "upper_1": snapshot.upper_1,
        "upper_2": snapshot.upper_2,
        "lower_1": snapshot.lower_1,
        "lower_2": snapshot.lower_2,
    }
    closest = min(bands.items(), key=lambda item: abs(float(item[1]) - float(price)))
    distance_pips = abs(float(closest[1]) - float(price)) / pip_size
    if distance_pips <= tolerance_pips:
        return closest[0], round(distance_pips, 1)
    return "none", round(distance_pips, 1)


def _classify_setup(direction: str, snapshot: VwapSnapshot, band_touched: str) -> Strategy3SetupMode:
    if direction == "LONG" and snapshot.z_score <= -1.0 and band_touched.startswith("lower"):
        return "reversal"
    if direction == "SHORT" and snapshot.z_score >= 1.0 and band_touched.startswith("upper"):
        return "reversal"
    if direction == "LONG" and snapshot.slope > 0 and band_touched in {"vwap", "upper_1"}:
        return "trend_following"
    if direction == "SHORT" and snapshot.slope < 0 and band_touched in {"vwap", "lower_1"}:
        return "trend_following"
    return "no_trade"


def _levels(
    *,
    symbol: str,
    direction: Strategy3Direction,
    entry: float,
    sweep_level: float,
    cfg: Strategy3Config,
) -> tuple[float, float] | None:
    buffer_price = pips_to_price(symbol, cfg.stop_buffer_pips)
    if direction == "LONG":
        stop = min(float(sweep_level) - buffer_price, entry - pips_to_price(symbol, cfg.min_stop_pips))
        risk = entry - stop
        target = entry + risk
    else:
        stop = max(float(sweep_level) + buffer_price, entry + pips_to_price(symbol, cfg.min_stop_pips))
        risk = stop - entry
        target = entry - risk
    risk_pips = price_to_pips(symbol, risk)
    if risk_pips < cfg.min_stop_pips or risk_pips > cfg.max_stop_pips:
        return None
    return normalize_price(symbol, stop), normalize_price(symbol, target)


def _empty_context(reason: str) -> dict[str, Any]:
    return {"confluence": False, "reason": reason}


def evaluate_strategy_3_vwap_1r(
    market_data: dict[str, pd.DataFrame],
    *,
    symbol: str = "XAUUSD",
    now_utc: datetime | None = None,
    config: Strategy3Config | None = None,
    diagnostics: Strategy3Diagnostics | None = None,
) -> Strategy3Signal | None:
    cfg = config or Strategy3Config()
    if diagnostics is not None:
        diagnostics.total_calls += 1
        if diagnostics.first_eval_time is None and now_utc is not None:
            diagnostics.first_eval_time = now_utc
        if now_utc is not None:
            diagnostics.last_eval_time = now_utc
    pip_size = get_symbol_spec(symbol).pip_size
    m1 = _normalize(market_data.get("M1"))
    m5 = _normalize(market_data.get("M5"))
    m15 = _normalize(market_data.get("M15"))
    h1 = _normalize(market_data.get("H1"))
    h4 = _normalize(market_data.get("H4"))
    d1 = _normalize(market_data.get("D1"))
    if any(frame.empty for frame in (m1, m5, m15)):
        if diagnostics is not None:
            diagnostics.skip_missing_data += 1
            diagnostics.record_rejection("missing_m1_m5_m15")
        return None

    price = _latest_price(m1)
    snapshot = vwap_snapshot(m15, price)
    if snapshot is None or snapshot.std <= 0:
        if diagnostics is not None:
            diagnostics.no_trade_count += 1
            diagnostics.record_rejection("vwap_unavailable")
        return None

    liq_map = build_liquidity_map(h4, h1, m15, m5, pip=pip_size)
    sweep = find_liquidity_sweep(m5, m1, liq_map=liq_map, pip=pip_size)
    if not sweep:
        if diagnostics is not None:
            diagnostics.no_trade_count += 1
            diagnostics.record_rejection("liquidity_sweep_missing")
        return None

    swept_level = find_swept_level(
        float(sweep["level"]),
        liq_map,
        tolerance_pips=cfg.max_liquidity_distance_pips,
        pip=pip_size,
    ) or sweep
    distance_to_liquidity = abs(float(swept_level.get("level", sweep["level"])) - price) / pip_size
    if distance_to_liquidity > cfg.max_liquidity_distance_pips:
        if diagnostics is not None:
            diagnostics.no_trade_count += 1
            diagnostics.record_rejection("liquidity_level_too_far")
        return None

    band_touched, vwap_distance_pips = _band_touch(snapshot, price, pip_size, cfg.band_tolerance_pips)
    direction = "LONG" if str(sweep.get("direction")).upper() == "LONG" else "SHORT"
    setup_mode = _classify_setup(direction, snapshot, band_touched)
    if setup_mode == "no_trade":
        if diagnostics is not None:
            diagnostics.no_trade_count += 1
            diagnostics.setup_modes["no_trade"] = diagnostics.setup_modes.get("no_trade", 0) + 1
            diagnostics.record_rejection("vwap_context_no_trade")
        return None

    levels = _levels(
        symbol=symbol,
        direction=direction,
        entry=price,
        sweep_level=float(sweep["level"]),
        cfg=cfg,
    )
    if levels is None:
        if diagnostics is not None:
            diagnostics.no_trade_count += 1
            diagnostics.record_rejection("risk_model_invalid")
        return None
    stop, tp1 = levels
    fvg = sweep.get("fvg") or {}
    fvg_context = {
        "has_fvg": bool(sweep.get("fvg_after_liquidity")),
        "has_ifvg": bool(sweep.get("ifvg_after_liquidity")),
        "fvg": fvg,
    }
    nt = nearest_number_theory(price, tolerance_pips=cfg.number_theory_tolerance_pips, pip=pip_size)
    profiles = build_multi_anchor_volume_profiles(
        {"M5": m5, "M15": m15, "H1": h1, "H4": h4, "D1": d1},
        liq_map,
        price,
        pip=pip_size,
    )
    volume = find_best_volume_crack_confluence(price, profiles, tolerance_pips=cfg.volume_tolerance_pips, pip=pip_size)
    reason_codes = [
        "liquidity_sweep",
        f"vwap_band_{band_touched}",
        f"setup_{setup_mode}",
        "target_1r",
    ]
    if fvg_context["has_fvg"] or fvg_context["has_ifvg"]:
        reason_codes.append("fvg_ifvg_context")
    if nt.get("confluence"):
        reason_codes.append("number_theory_context")
    if volume.get("confluence"):
        reason_codes.append("volume_crack_context")

    signal = Strategy3Signal(
        symbol=symbol,
        direction=direction,
        setup_mode=setup_mode,
        entry=normalize_price(symbol, price),
        stop=stop,
        tp1=tp1,
        rr_tp1=1.0,
        timestamp_utc=now_utc or datetime.now(timezone.utc),
        reason_codes=reason_codes,
        confluences={
            "vwap": snapshot.__dict__,
            "number_theory": nt,
            "volume": volume,
        },
        vwap_distance_pips=vwap_distance_pips,
        band_touched=band_touched,
        liquidity_context={
            "level": swept_level.get("level"),
            "timeframe": swept_level.get("timeframe"),
            "type": swept_level.get("kind") or swept_level.get("level_kind"),
            "scope": swept_level.get("scope"),
            "distance_pips": round(distance_to_liquidity, 1),
            "sweep": sweep,
        },
        fvg_ifvg_context=fvg_context,
        number_theory_context=nt,
    )
    if diagnostics is not None:
        diagnostics.signals_emitted += 1
        diagnostics.setup_modes[setup_mode] = diagnostics.setup_modes.get(setup_mode, 0) + 1
        if direction == "LONG":
            diagnostics.long_signals += 1
        else:
            diagnostics.short_signals += 1
    return signal


__all__ = [
    "Strategy3Config",
    "Strategy3Diagnostics",
    "Strategy3Signal",
    "evaluate_strategy_3_vwap_1r",
]
