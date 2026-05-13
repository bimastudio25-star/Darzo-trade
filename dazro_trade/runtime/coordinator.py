from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from dazro_trade.analysis.liquidity_expansion import LiquidityExpansionSignal
from dazro_trade.core.symbols import price_to_pips
from dazro_trade.runtime.session_bias import SessionRelationship, apply_session_bias_to_strategy

CombinedMode = Literal[
    "STRATEGY_1_ONLY",
    "STRATEGY_2_ONLY",
    "A_PLUS_PLUS",
    "CONFLICT",
    "INDEPENDENT_BOTH",
    "NO_TRADE",
]


@dataclass(frozen=True)
class CoordinatorDecision:
    combined_mode: CombinedMode
    primary_strategy: str | None
    should_send: bool
    suppress_reason: str | None
    warnings: list[str] = field(default_factory=list)
    strategy_1_signal: dict[str, Any] | None = None
    strategy_2_signal: dict[str, Any] | None = None
    distance_pips: float | None = None
    bias_effect_s1: dict[str, Any] | None = None
    bias_effect_s2: dict[str, Any] | None = None
    bias_demoted: bool = False
    bias_favored: str | None = None
    session_label: str | None = None


def _extract_adelin_signal(adelin_result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not adelin_result:
        return None
    signal = adelin_result.get("signal")
    if not isinstance(signal, dict):
        return None
    if signal.get("direction") not in {"LONG", "SHORT"}:
        return None
    if signal.get("entry") in (None, 0):
        return None
    return signal


def _lex_to_dict(lex: LiquidityExpansionSignal | None) -> dict[str, Any] | None:
    if lex is None:
        return None
    return {
        "direction": lex.direction,
        "entry": lex.entry,
        "stop": lex.stop,
        "tp1": lex.tp1,
        "tp2": lex.tp2,
        "tp3": lex.tp3,
        "tp4": lex.tp4,
        "rr_tp1": lex.rr_tp1,
        "rr_tp4": lex.rr_tp4,
        "trigger_kind": lex.trigger_kind,
        "candle_model": lex.candle_model,
        "h1_source": lex.reference.h1_source,
        "m15_source": lex.reference.m15_source,
        "stats_samples": lex.stats.samples,
        "reason_codes": list(lex.reason_codes),
    }


def _bias_effect_for(direction: str | None, relationship: SessionRelationship | None) -> dict[str, Any] | None:
    if relationship is None or direction is None:
        return None
    effect = apply_session_bias_to_strategy(direction, relationship)
    return {"effect": effect.get("effect", "neutral"), "reason_codes": list(effect.get("reason_codes", []))}


def _bias_favored_in_conflict(eff1: dict[str, Any] | None, eff2: dict[str, Any] | None) -> str | None:
    if eff1 is None or eff2 is None:
        return None
    e1 = eff1.get("effect")
    e2 = eff2.get("effect")
    if e1 == "boost" and e2 in {"demote", "warning"}:
        return "strategy_1"
    if e2 == "boost" and e1 in {"demote", "warning"}:
        return "strategy_2"
    return None


def _apply_bias_reason_code(signal: dict[str, Any] | None, effect: dict[str, Any] | None) -> None:
    if signal is None or effect is None or not isinstance(signal.get("reason_codes"), list):
        return
    if effect.get("effect") == "boost":
        signal["reason_codes"].append("session_bias_boost")
    elif effect.get("effect") == "warning":
        signal["reason_codes"].append("session_bias_warning")


def combine_strategy_results(
    adelin_result: dict[str, Any] | None,
    liquidity_expansion_signal: LiquidityExpansionSignal | None,
    *,
    zone_tolerance_pips: float = 30.0,
    conflict_tolerance_pips: float = 50.0,
    symbol: str = "XAUUSD",
    session_relationship: SessionRelationship | None = None,
) -> CoordinatorDecision:
    s1 = _extract_adelin_signal(adelin_result)
    s2_obj = liquidity_expansion_signal
    s2 = _lex_to_dict(s2_obj)
    session_label = session_relationship.label if session_relationship is not None else None

    if s1 is None and s2 is None:
        return CoordinatorDecision(
            combined_mode="NO_TRADE",
            primary_strategy=None,
            should_send=False,
            suppress_reason="no_strategy_valid",
            session_label=session_label,
        )

    if s1 is not None and s2 is None:
        eff1 = _bias_effect_for(s1.get("direction"), session_relationship)
        _apply_bias_reason_code(s1, eff1)
        demoted = bool(eff1 and eff1.get("effect") == "demote")
        return CoordinatorDecision(
            combined_mode="STRATEGY_1_ONLY",
            primary_strategy="strategy_1",
            should_send=True,
            suppress_reason=None,
            strategy_1_signal=s1,
            bias_effect_s1=eff1,
            bias_demoted=demoted,
            session_label=session_label,
        )

    if s1 is None and s2 is not None:
        eff2 = _bias_effect_for(s2.get("direction"), session_relationship)
        _apply_bias_reason_code(s2, eff2)
        demoted = bool(eff2 and eff2.get("effect") == "demote")
        return CoordinatorDecision(
            combined_mode="STRATEGY_2_ONLY",
            primary_strategy="strategy_2",
            should_send=True,
            suppress_reason=None,
            strategy_2_signal=s2,
            bias_effect_s2=eff2,
            bias_demoted=demoted,
            session_label=session_label,
        )

    assert s1 is not None and s2 is not None
    entry_1 = float(s1["entry"])
    entry_2 = float(s2["entry"])
    distance_price = abs(entry_1 - entry_2)
    distance_pips = round(price_to_pips(symbol, distance_price), 2)
    same_direction = s1["direction"] == s2["direction"]

    eff1 = _bias_effect_for(s1.get("direction"), session_relationship)
    eff2 = _bias_effect_for(s2.get("direction"), session_relationship)
    _apply_bias_reason_code(s1, eff1)
    _apply_bias_reason_code(s2, eff2)

    if same_direction and distance_pips <= zone_tolerance_pips:
        return CoordinatorDecision(
            combined_mode="A_PLUS_PLUS",
            primary_strategy="both",
            should_send=True,
            suppress_reason=None,
            warnings=[],
            strategy_1_signal=s1,
            strategy_2_signal=s2,
            distance_pips=distance_pips,
            bias_effect_s1=eff1,
            bias_effect_s2=eff2,
            bias_demoted=False,
            session_label=session_label,
        )

    if (not same_direction) and distance_pips <= conflict_tolerance_pips:
        return CoordinatorDecision(
            combined_mode="CONFLICT",
            primary_strategy=None,
            should_send=False,
            suppress_reason="opposite_signals_same_zone",
            warnings=[
                f"strategy_1={s1['direction']}@{entry_1}",
                f"strategy_2={s2['direction']}@{entry_2}",
                f"distance_pips={distance_pips}",
            ],
            strategy_1_signal=s1,
            strategy_2_signal=s2,
            distance_pips=distance_pips,
            bias_effect_s1=eff1,
            bias_effect_s2=eff2,
            bias_favored=_bias_favored_in_conflict(eff1, eff2),
            session_label=session_label,
        )

    demoted_both = bool((eff1 and eff1.get("effect") == "demote") or (eff2 and eff2.get("effect") == "demote"))
    return CoordinatorDecision(
        combined_mode="INDEPENDENT_BOTH",
        primary_strategy="both",
        should_send=True,
        suppress_reason=None,
        warnings=[f"zones_independent_distance_pips={distance_pips}"],
        strategy_1_signal=s1,
        strategy_2_signal=s2,
        distance_pips=distance_pips,
        bias_effect_s1=eff1,
        bias_effect_s2=eff2,
        bias_demoted=demoted_both,
        session_label=session_label,
    )


__all__ = ["CombinedMode", "CoordinatorDecision", "combine_strategy_results"]
