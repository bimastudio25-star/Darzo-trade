from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from dazro_trade.analysis.liquidity_expansion import LiquidityExpansionSignal
from dazro_trade.core.symbols import price_to_pips

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


def combine_strategy_results(
    adelin_result: dict[str, Any] | None,
    liquidity_expansion_signal: LiquidityExpansionSignal | None,
    *,
    zone_tolerance_pips: float = 30.0,
    conflict_tolerance_pips: float = 50.0,
    symbol: str = "XAUUSD",
) -> CoordinatorDecision:
    s1 = _extract_adelin_signal(adelin_result)
    s2_obj = liquidity_expansion_signal
    s2 = _lex_to_dict(s2_obj)

    if s1 is None and s2 is None:
        return CoordinatorDecision(
            combined_mode="NO_TRADE",
            primary_strategy=None,
            should_send=False,
            suppress_reason="no_strategy_valid",
        )

    if s1 is not None and s2 is None:
        return CoordinatorDecision(
            combined_mode="STRATEGY_1_ONLY",
            primary_strategy="strategy_1",
            should_send=True,
            suppress_reason=None,
            strategy_1_signal=s1,
        )

    if s1 is None and s2 is not None:
        return CoordinatorDecision(
            combined_mode="STRATEGY_2_ONLY",
            primary_strategy="strategy_2",
            should_send=True,
            suppress_reason=None,
            strategy_2_signal=s2,
        )

    assert s1 is not None and s2 is not None
    entry_1 = float(s1["entry"])
    entry_2 = float(s2["entry"])
    distance_price = abs(entry_1 - entry_2)
    distance_pips = round(price_to_pips(symbol, distance_price), 2)
    same_direction = s1["direction"] == s2["direction"]

    if same_direction and distance_pips <= zone_tolerance_pips:
        warning = []
        return CoordinatorDecision(
            combined_mode="A_PLUS_PLUS",
            primary_strategy="both",
            should_send=True,
            suppress_reason=None,
            warnings=warning,
            strategy_1_signal=s1,
            strategy_2_signal=s2,
            distance_pips=distance_pips,
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
        )

    return CoordinatorDecision(
        combined_mode="INDEPENDENT_BOTH",
        primary_strategy="both",
        should_send=True,
        suppress_reason=None,
        warnings=[f"zones_independent_distance_pips={distance_pips}"],
        strategy_1_signal=s1,
        strategy_2_signal=s2,
        distance_pips=distance_pips,
    )


__all__ = ["CombinedMode", "CoordinatorDecision", "combine_strategy_results"]
