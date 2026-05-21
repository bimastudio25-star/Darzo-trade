from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from dazro_trade.adelin.confluence_engine import calculate_scalp_levels, calculate_vwap_scalp, score_setup
from dazro_trade.adelin.liquidity_map import build_liquidity_map, find_swept_level
from dazro_trade.adelin.number_theory import nearest_number_theory, score_number_theory_confluence
from dazro_trade.adelin.sweep_detector import calculate_vwap_bands, find_liquidity_sweep
from dazro_trade.adelin.telemetry import build_signal_telemetry
from dazro_trade.adelin.volume_profile import build_multi_anchor_volume_profiles, find_best_volume_crack_confluence
from dazro_trade.core.symbols import get_symbol_spec
from dazro_trade.runtime.sessions import current_session_name


def run_adelin_scan(
    *,
    mt5: Any | None = None,
    market_data: dict[str, pd.DataFrame] | None = None,
    news_events: list[dict[str, Any]] | None = None,
    pip: float | None = None,
    settings: Any | None = None,
    current_price: float | None = None,
    spread_pips: float | None = None,
    now_utc: datetime | None = None,
    session_name: str | None = None,
    liquidity_map_cache: dict[tuple[Any, ...], list[dict[str, Any]]] | None = None,
    liquidity_map_lookback_by_timeframe: dict[str, int] | None = None,
) -> dict[str, Any]:
    now = now_utc or datetime.now(timezone.utc)
    symbol = getattr(settings, "mt5_symbol", "XAUUSD")
    pip_size = float(pip if pip is not None else get_symbol_spec(symbol).pip_size)
    frames = market_data or _fetch_market_data(mt5)
    rejected: list[str] = []
    if not frames:
        rejected.append("no_candle_data")
    price = float(current_price) if current_price is not None else _infer_price(frames)
    if price <= 0:
        rejected.append("no_tick_price")
    session = session_name or current_session_name(now)
    session_ok = _session_allowed(now, session, settings)
    if not session_ok:
        rejected.append("outside_adelin_session_window")
    news_block = _news_block(news_events or [], now, settings)
    if news_block:
        rejected.append(news_block)
    if rejected:
        return _result(now, None, rejected, None, None, None, "NO_TRADE", {"session": session, "pip": pip_size})

    liq_map = _cached_liquidity_map(
        frames,
        symbol=symbol,
        pip_size=pip_size,
        cache=liquidity_map_cache,
        lookback_by_timeframe=liquidity_map_lookback_by_timeframe,
    )
    profiles = build_multi_anchor_volume_profiles(frames, liq_map, price, pip_size)
    vwap_data = calculate_vwap_bands(frames.get("M5", pd.DataFrame())) or {}
    sweep = find_liquidity_sweep(frames.get("M5", pd.DataFrame()), frames.get("M1", pd.DataFrame()), liq_map=liq_map, pip=pip_size)
    if sweep is None:
        rejected.append("liquidity_sweep_missing")
        vwap_signal = _maybe_vwap_research(price, vwap_data, pip_size, settings)
        if vwap_signal is not None:
            score_detail = {"score": 80, "setup_mode": "VWAP_STD_RESEARCH_1R", "verdict": "VWAP_RESEARCH", "hard_filters": {"paper_only": True}}
            signal = {**vwap_signal, "symbol": symbol, "direction": vwap_signal["direction"], "score": 80, "setup_mode": "VWAP_STD_RESEARCH_1R"}
            return _result(now, signal, [], score_detail, _vp_summary(profiles), vwap_data, "VWAP_STD_RESEARCH_1R", {"session": session, "pip": pip_size, "liquidity_map": liq_map})
        return _result(now, None, rejected, None, _vp_summary(profiles), vwap_data, "NO_TRADE", {"session": session, "pip": pip_size, "liquidity_map": liq_map})

    swept_level = find_swept_level(float(sweep["level"]), liq_map, tolerance_pips=float(getattr(settings, "adelin_liq_match_tolerance_pips", 25.0)), pip=pip_size)
    fvg = sweep.get("fvg") or {}
    volume_check = find_best_volume_crack_confluence((float(fvg["top"]), float(fvg["bot"])) if fvg.get("top") is not None else float(sweep["level"]), profiles, tolerance_pips=5.0, pip=pip_size)
    nt = score_number_theory_confluence(price, float(fvg.get("top", price)), float(fvg.get("bot", price)), pip_size) if fvg else nearest_number_theory(float(sweep["level"]), tolerance_pips=float(getattr(settings, "adelin_nt_tolerance_pips", 15.0)), pip=pip_size)
    nt_confluence = {"confluence": bool(nt.get("confluence") or nt.get("score", 0) > 0), "detail": nt}
    levels = calculate_scalp_levels(
        str(sweep["direction"]),
        price,
        float(sweep["level"]),
        pip_size,
        min_stop_pips=float(getattr(settings, "adelin_sl_min_pips", 35.0)),
        max_stop_pips=float(getattr(settings, "adelin_sl_max_pips", 65.0)),
        stop_buffer_pips=float(getattr(settings, "adelin_sl_buffer_pips", 8.0)),
        tp1_rr=float(getattr(settings, "adelin_tp1_rr", 2.0)),
        tp2_rr=float(getattr(settings, "adelin_tp2_rr", 3.0)),
    )
    score_detail = score_setup(
        sweep=sweep,
        volume_confluence=volume_check,
        number_theory=nt_confluence,
        levels=levels,
        spread_pips=float(spread_pips or 0.0),
        max_spread_pips=float(getattr(settings, "max_spread_pips", 3.0)),
        min_score=int(getattr(settings, "adelin_min_score", 65)),
        a_plus_score=int(getattr(settings, "adelin_a_plus_score", 85)),
        min_scalp_target_pips=float(getattr(settings, "adelin_min_scalp_target_pips", 50.0)),
        ideal_target_pips=float(getattr(settings, "adelin_ideal_target_pips", 100.0)),
        min_scalp_rr=float(getattr(settings, "adelin_min_scalp_rr", 1.5)),
        a_plus_rr=float(getattr(settings, "adelin_a_plus_rr", 2.0)),
    )
    setup_mode = str(score_detail["setup_mode"])
    signal = None
    if score_detail["verdict"] == "TRIGGERED":
        telemetry = build_signal_telemetry(
            symbol=symbol,
            current_price=price,
            liquidity=swept_level or sweep,
            pip_size=pip_size,
            score_detail=score_detail,
            continuation_candidate=None,
        )
        signal = {
            "symbol": symbol,
            "setup_mode": setup_mode,
            "direction": sweep["direction"],
            "score": score_detail["score"],
            "entry": levels["entry"],
            "entry_zone": levels["entry_zone"],
            "sl": levels["sl"],
            "sl_pips": levels["sl_pips"],
            "sl_dollars": levels["sl_dollars"],
            "tp1": levels["tp1"],
            "tp2": levels["tp2"],
            "liquidity_swept": swept_level or sweep,
            "volume_confluence": volume_check,
            "number_theory": nt_confluence,
            "fvg": fvg,
            "sweep": sweep,
            "session": session,
            "spread_pips": float(spread_pips or 0.0),
            "paper_demo": True,
            "telemetry": telemetry,
        }
    rejected.extend(score_detail.get("rejected") or [])
    return _result(now, signal, [] if signal else rejected, score_detail, _vp_summary(profiles), vwap_data, setup_mode, {"session": session, "pip": pip_size, "liquidity_map": liq_map, "profiles": profiles})


def _maybe_vwap_research(price: float, vwap_data: dict[str, Any], pip: float, settings: Any | None) -> dict[str, Any] | None:
    if not bool(getattr(settings, "adelin_send_vwap_research", True)):
        return None
    std = float(vwap_data.get("std", 0) or 0)
    if std <= 0:
        return None
    z = (price - float(vwap_data["vwap"])) / std
    if abs(z) < 2:
        return None
    direction = "LONG" if z <= -2 else "SHORT"
    scalp = calculate_vwap_scalp(direction, price, vwap_data, pip)
    if scalp is None:
        return None
    return {**scalp, "direction": direction, "z_score": round(z, 2)}


def _fetch_market_data(mt5: Any | None) -> dict[str, pd.DataFrame]:
    if mt5 is None:
        return {}
    return {tf: mt5.get_candles(tf, 500) for tf in ("D1", "H4", "H1", "M15", "M5", "M1")}


def _latest_timestamp(frame: pd.DataFrame | None) -> str | None:
    if frame is None or len(frame) == 0 or "time" not in frame.columns:
        return None
    value = frame["time"].iloc[-1]
    return pd.Timestamp(value).isoformat()


def _limit_frame(frame: pd.DataFrame | None, limit: int | None) -> pd.DataFrame | None:
    if frame is None or len(frame) == 0 or limit is None or limit <= 0:
        return frame
    return frame.tail(int(limit))


def _cached_liquidity_map(
    frames: dict[str, pd.DataFrame],
    *,
    symbol: str,
    pip_size: float,
    cache: dict[tuple[Any, ...], list[dict[str, Any]]] | None,
    lookback_by_timeframe: dict[str, int] | None,
) -> list[dict[str, Any]]:
    key = (
        "strategy_1_adelin_scalp",
        symbol,
        round(float(pip_size), 10),
        _latest_timestamp(frames.get("H4")),
        _latest_timestamp(frames.get("H1")),
        _latest_timestamp(frames.get("M15")),
        _latest_timestamp(frames.get("M5")),
    )
    if cache is not None and key in cache:
        return cache[key]
    limits = lookback_by_timeframe or {}
    liq_map = build_liquidity_map(
        _limit_frame(frames.get("H4"), limits.get("H4")),
        _limit_frame(frames.get("H1"), limits.get("H1")),
        _limit_frame(frames.get("M15"), limits.get("M15")),
        _limit_frame(frames.get("M5"), limits.get("M5")),
        pip_size,
    )
    if cache is not None:
        cache[key] = liq_map
    return liq_map


def _infer_price(frames: dict[str, pd.DataFrame]) -> float:
    for timeframe in ("M1", "M5", "M15", "H1", "H4"):
        df = frames.get(timeframe)
        if df is not None and len(df):
            column = "c" if "c" in df.columns else "close"
            if column in df.columns:
                return float(df[column].iloc[-1])
    return 0.0


def _session_allowed(now: datetime, session_name: str, settings: Any | None) -> bool:
    if not bool(getattr(settings, "adelin_session_gate_enabled", True)):
        return True
    if session_name in {"London", "New York", "London + New York"}:
        return True
    windows = str(getattr(settings, "adelin_session_windows_utc", "08:00-10:30,13:00-17:00"))
    current = now.astimezone(timezone.utc).time()
    for item in windows.split(","):
        start_text, end_text = item.split("-", 1)
        start = datetime.strptime(start_text.strip(), "%H:%M").time()
        end = datetime.strptime(end_text.strip(), "%H:%M").time()
        if start <= current <= end:
            return True
    return False


def _news_block(events: list[dict[str, Any]], now: datetime, settings: Any | None) -> str | None:
    if not bool(getattr(settings, "adelin_news_gate_enabled", True)):
        return None
    weights = {"nfp": 3, "fomc": 3, "fed": 3, "non-farm payrolls": 3, "cpi": 2, "ppi": 2, "gdp": 2, "retail sales": 2, "ism": 1, "pmi": 1, "claims": 1}
    buffers = {3: 30, 2: 20, 1: 10}
    for event in events:
        text = " ".join(str(event.get(key, "")) for key in ("title", "name", "event", "impact")).lower()
        weight = max((value for key, value in weights.items() if key in text), default=0)
        if weight == 0:
            continue
        when = pd.Timestamp(event.get("time") or event.get("timestamp") or now).to_pydatetime()
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if abs(now - when.astimezone(timezone.utc)) <= timedelta(minutes=buffers[weight]):
            return f"news_gate_weight_{weight}"
    return None


def _vp_summary(profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "profiles": list(profiles.keys()),
        "daily": profiles.get("daily_current"),
        "best_poc": next((profile.get("poc") for profile in profiles.values() if profile.get("poc") is not None), None),
        "volume_note": "Volume profile usa tick_volume MT5 come proxy, non vero volume futures.",
    }


def _result(now: datetime, signal: dict[str, Any] | None, rejected: list[str], score_detail: dict[str, Any] | None, vp_summary: dict[str, Any] | None, vwap_data: dict[str, Any] | None, setup_mode: str, debug: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": now.isoformat(),
        "signal": signal,
        "rejected": list(dict.fromkeys(rejected)),
        "score_detail": score_detail,
        "vp_summary": vp_summary,
        "vwap_data": vwap_data,
        "setup_mode": setup_mode,
        "debug": debug,
    }


__all__ = ["run_adelin_scan"]
