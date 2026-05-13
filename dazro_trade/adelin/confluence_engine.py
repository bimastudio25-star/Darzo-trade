from __future__ import annotations

from typing import Any

from dazro_trade.core.symbols import get_symbol_spec


def _pip(pip: float | None = None) -> float:
    return float(pip if pip is not None else get_symbol_spec("XAUUSD").pip_size)


def calculate_scalp_levels(
    direction: str,
    entry: float,
    swept_level: float,
    pip: float | None = None,
    *,
    min_stop_pips: float = 35.0,
    max_stop_pips: float = 65.0,
    stop_buffer_pips: float = 8.0,
    tp1_rr: float = 2.0,
    tp2_rr: float = 3.0,
) -> dict[str, Any]:
    pip_size = _pip(pip)
    raw_stop_pips = abs(float(entry) - float(swept_level)) / pip_size + stop_buffer_pips
    stop_pips = min(max(raw_stop_pips, min_stop_pips), max_stop_pips)
    if direction == "LONG":
        stop = entry - stop_pips * pip_size
        tp1 = entry + stop_pips * tp1_rr * pip_size
        tp2 = entry + stop_pips * tp2_rr * pip_size
    else:
        stop = entry + stop_pips * pip_size
        tp1 = entry - stop_pips * tp1_rr * pip_size
        tp2 = entry - stop_pips * tp2_rr * pip_size
    return {
        "entry": round(entry, 2),
        "entry_zone": (round(entry - 2 * pip_size, 2), round(entry + 2 * pip_size, 2)),
        "sl": round(stop, 2),
        "sl_pips": round(stop_pips, 1),
        "sl_dollars": round(stop_pips * pip_size, 2),
        "tp1": {"price": round(tp1, 2), "rr": tp1_rr, "distance_pips": round(stop_pips * tp1_rr, 1), "dollars": round(stop_pips * tp1_rr * pip_size, 2), "basis": "liquidity/VP target"},
        "tp2": {"price": round(tp2, 2), "rr": tp2_rr, "distance_pips": round(stop_pips * tp2_rr, 1), "dollars": round(stop_pips * tp2_rr * pip_size, 2), "basis": "runner liquidity/VP target"},
    }


def calculate_vwap_scalp(direction: str, entry: float, vwap_data: dict[str, Any], pip: float | None = None) -> dict[str, Any] | None:
    pip_size = _pip(pip)
    std = float(vwap_data.get("std", 0) or 0)
    if std <= 0:
        return None
    stop_dist = std * 0.75
    if direction == "LONG":
        stop = entry - stop_dist
        tp = entry + stop_dist
    else:
        stop = entry + stop_dist
        tp = entry - stop_dist
    return {
        "setup_mode": "VWAP_STD_RESEARCH_1R",
        "paper_only": True,
        "entry": round(entry, 2),
        "sl": round(stop, 2),
        "tp1": {"price": round(tp, 2), "rr": 1.0, "distance_pips": round(abs(tp - entry) / pip_size, 1), "dollars": round(abs(tp - entry), 2), "basis": "VWAP_STD_RESEARCH_1R"},
        "rr": 1.0,
    }


def score_setup(
    *,
    sweep: dict[str, Any] | None,
    volume_confluence: dict[str, Any] | None,
    number_theory: dict[str, Any] | None,
    levels: dict[str, Any] | None,
    spread_pips: float,
    max_spread_pips: float = 3.0,
    entry_available: bool = True,
    min_score: int = 65,
    a_plus_score: int = 85,
    min_scalp_target_pips: float = 50.0,
    ideal_target_pips: float = 100.0,
    min_scalp_rr: float = 1.5,
    a_plus_rr: float = 2.0,
    vwap_research: dict[str, Any] | None = None,
) -> dict[str, Any]:
    components: dict[str, int] = {}
    rejected: list[str] = []
    liquidity_ok = bool(sweep and sweep.get("liquidity_swept") and sweep.get("close_back_inside"))
    fvg_ok = bool(sweep and (sweep.get("fvg_after_liquidity") or sweep.get("ifvg_after_liquidity")))
    volume_ok = bool(volume_confluence and volume_confluence.get("confluence"))
    nt_ok = bool(number_theory and number_theory.get("confluence"))
    spread_ok = float(spread_pips) <= max_spread_pips
    target_pips = float(((levels or {}).get("tp1") or {}).get("distance_pips", 0) or 0)
    rr = float(((levels or {}).get("tp1") or {}).get("rr", 0) or 0)
    target_ok = target_pips >= min_scalp_target_pips and rr >= min_scalp_rr
    ideal_target_ok = target_pips >= ideal_target_pips and rr >= a_plus_rr
    if liquidity_ok:
        components["liquidity_swept"] = 25
    else:
        rejected.append("liquidity_swept_missing")
    if fvg_ok:
        components["fvg_or_ifvg_post_liq"] = 20 if not sweep.get("ifvg_after_liquidity") else 25
    else:
        rejected.append("fvg_or_ifvg_post_liq_missing")
    if volume_ok:
        components["volume_crack_or_lvn"] = 20
    else:
        rejected.append("volume_crack_or_lvn_missing")
    if nt_ok:
        components["number_theory"] = 15
    else:
        rejected.append("number_theory_missing")
    if target_ok:
        components["target_rr"] = 15
    else:
        rejected.append("target_or_rr_invalid")
    if spread_ok:
        components["spread_ok"] = 5
    else:
        rejected.append("spread_too_high")
    if not entry_available:
        rejected.append("entry_touched_no_chase")
    score = 0 if not liquidity_ok else max(0, min(100, sum(components.values())))
    hard_filters = {
        "liquidity_swept": liquidity_ok,
        "fvg_or_ifvg_post_liq": fvg_ok,
        "volume_crack_or_lvn": volume_ok,
        "number_theory": nt_ok,
        "target_clean": target_ok,
        "spread_ok": spread_ok,
        "entry_available": entry_available,
        "setup_not_invalidated": True,
    }
    if vwap_research and score >= 80:
        mode = "VWAP_STD_RESEARCH_1R"
        verdict = "VWAP_RESEARCH"
    elif score >= a_plus_score and all(hard_filters.values()) and ideal_target_ok:
        mode = "LIQ_VP_NT_FVG_A_PLUS"
        verdict = "TRIGGERED"
    elif score >= min_score and liquidity_ok and fvg_ok and target_ok and spread_ok and entry_available:
        mode = "LIQ_VP_NT_FVG_SCALP"
        verdict = "TRIGGERED"
    elif liquidity_ok:
        mode = "NO_TRADE"
        verdict = "REACTION_PREP"
    else:
        mode = "NO_TRADE"
        verdict = "NO_TRADE"
    return {
        "score": score,
        "components": components,
        "hard_filters": hard_filters,
        "verdict": verdict,
        "setup_mode": mode,
        "summary": ", ".join(components) if components else "no_confluence",
        "rejected": rejected,
    }


__all__ = ["calculate_scalp_levels", "calculate_vwap_scalp", "score_setup"]
