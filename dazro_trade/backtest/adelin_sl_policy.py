"""
Adelin dynamic SL acceptance policy (backtest-only for now).

Replaces the legacy fixed cap `per_strategy_max_sl["strategy_1_adelin_scalp"]=5.0`
with a 4-tier scheme that lets wider-stop trades through when supported by
score, setup quality or M5/M1 micro-confluence.

Tier rules:
    Tier 1: SL <= 4.00 USD                                      -> accept
    Tier 2: 4.01 - 5.00 USD                                     -> accept
    Tier 3: 5.01 - 6.50 USD                                     -> accept if score >= 85
    Tier 4: 6.51 - 7.00 USD                                     -> accept if (score >= 90
                                                                    OR setup_mode == "LIQ_VP_NT_FVG_A_PLUS"
                                                                    OR micro_confluence.all_pass)
    Reject: SL > 7.00 USD                                       -> reject SL_TOO_WIDE

Tier 4 can be disabled via `AdelinSLPolicy.tier_4_enabled = False`.

The classifier is pure (no side effects), so it can be unit-tested in
isolation and is safe to call from both the backtest runner and (in a
later commit) the live scanner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

AdelinSLTier = Literal["tier_1", "tier_2", "tier_3", "tier_4", "rejected"]
AdelinSLAcceptanceReason = Literal[
    "tier_1_within_4",
    "tier_2_within_5",
    "tier_3_score_ge_85",
    "tier_4_score_ge_90",
    "tier_4_setup_a_plus",
    "tier_4_micro_confluence",
    "rejected_score_below_85",
    "rejected_score_below_90_no_a_plus_no_micro",
    "rejected_tier_4_disabled",
    "rejected_sl_above_max",
]


@dataclass(frozen=True)
class AdelinSLPolicy:
    """Tier thresholds and gate conditions for Adelin SL acceptance."""

    tier_1_max_usd: float = 4.00
    tier_2_max_usd: float = 5.00
    tier_3_max_usd: float = 6.50
    tier_3_min_score: int = 85
    tier_4_max_usd: float = 7.00
    tier_4_min_score: int = 90
    tier_4_enabled: bool = True
    a_plus_setup_mode: str = "LIQ_VP_NT_FVG_A_PLUS"


@dataclass(frozen=True)
class AdelinSLDecision:
    """Result of evaluating a single Adelin signal against the SL policy."""

    accepted: bool
    tier: AdelinSLTier
    reason: AdelinSLAcceptanceReason
    sl_usd: float

    def rejection_code(self) -> str | None:
        if self.accepted:
            return None
        return f"SL_TOO_WIDE_for_strategy_1_adelin_scalp_dynamic_tier={self.tier}_sl={round(self.sl_usd, 2)}_reason={self.reason}"


def evaluate_adelin_sl_acceptance(
    *,
    sl_usd: float,
    score: int | None,
    setup_mode: str | None,
    micro_confluence: dict | None,
    policy: AdelinSLPolicy | None = None,
) -> AdelinSLDecision:
    """Classify an Adelin signal into a tier and decide accept/reject.

    Args:
        sl_usd: absolute SL distance in USD (entry - stop, sign-stripped).
        score: Adelin score 0-100 (None counts as 0 for tier 3/4 gates).
        setup_mode: pipeline setup_mode (e.g. "LIQ_VP_NT_FVG_SCALP",
            "LIQ_VP_NT_FVG_A_PLUS").
        micro_confluence: signal["micro_confluence"] dict produced by
            `dazro_trade.adelin.compute_micro_confluence`.
        policy: optional override. Default policy applied when None.
    """
    policy = policy or AdelinSLPolicy()
    sl = abs(float(sl_usd))
    score_val = int(score) if score is not None else 0
    is_a_plus_setup = (setup_mode or "") == policy.a_plus_setup_mode
    micro_all_pass = bool((micro_confluence or {}).get("all_pass", False))

    if sl <= policy.tier_1_max_usd:
        return AdelinSLDecision(accepted=True, tier="tier_1", reason="tier_1_within_4", sl_usd=sl)

    if sl <= policy.tier_2_max_usd:
        return AdelinSLDecision(accepted=True, tier="tier_2", reason="tier_2_within_5", sl_usd=sl)

    if sl <= policy.tier_3_max_usd:
        if score_val >= policy.tier_3_min_score:
            return AdelinSLDecision(accepted=True, tier="tier_3", reason="tier_3_score_ge_85", sl_usd=sl)
        return AdelinSLDecision(accepted=False, tier="tier_3", reason="rejected_score_below_85", sl_usd=sl)

    if sl <= policy.tier_4_max_usd:
        if not policy.tier_4_enabled:
            return AdelinSLDecision(accepted=False, tier="tier_4", reason="rejected_tier_4_disabled", sl_usd=sl)
        if score_val >= policy.tier_4_min_score:
            return AdelinSLDecision(accepted=True, tier="tier_4", reason="tier_4_score_ge_90", sl_usd=sl)
        if is_a_plus_setup:
            return AdelinSLDecision(accepted=True, tier="tier_4", reason="tier_4_setup_a_plus", sl_usd=sl)
        if micro_all_pass:
            return AdelinSLDecision(accepted=True, tier="tier_4", reason="tier_4_micro_confluence", sl_usd=sl)
        return AdelinSLDecision(
            accepted=False,
            tier="tier_4",
            reason="rejected_score_below_90_no_a_plus_no_micro",
            sl_usd=sl,
        )

    return AdelinSLDecision(accepted=False, tier="rejected", reason="rejected_sl_above_max", sl_usd=sl)


__all__ = [
    "AdelinSLDecision",
    "AdelinSLPolicy",
    "AdelinSLTier",
    "AdelinSLAcceptanceReason",
    "evaluate_adelin_sl_acceptance",
]
