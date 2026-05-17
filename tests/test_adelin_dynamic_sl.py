"""
Tests for the Adelin dynamic SL policy (backtest-only feature).

Covers:
- compute_micro_confluence boolean map
- evaluate_adelin_sl_acceptance classifier for all tiers and edge cases
- AdelinSLDecision.rejection_code formatting
- _apply_adelin_sl_policy mutation + diagnostics population
- BacktestConfig backward-compat (no policy -> legacy filter)
- compute_adelin_sl_bucket_performance bucket grouping
- ex_rejected_recovered_count threshold (legacy = 5 USD)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from dazro_trade.adelin import compute_micro_confluence
from dazro_trade.backtest.adelin_sl_policy import (
    AdelinSLDecision,
    AdelinSLPolicy,
    evaluate_adelin_sl_acceptance,
)
from dazro_trade.backtest.metrics import (
    ADELIN_SL_BUCKETS,
    LEGACY_ADELIN_MAX_SL_USD,
    _bucket_for_sl,
    compute_adelin_sl_bucket_performance,
)
from dazro_trade.backtest.runner import (
    AdelinDiagnostics,
    BacktestConfig,
    LEGACY_ADELIN_MAX_SL_USD as RUNNER_LEGACY_MAX_SL,
    STRATEGY_1_NAME,
    _apply_adelin_sl_policy,
    _apply_per_strategy_sl_filter,
)
from dazro_trade.backtest.simulator import BacktestSignal, BacktestTrade


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _make_signal(*, sl_distance: float, score: int = 70,
                 setup_mode: str = "LIQ_VP_NT_FVG_SCALP",
                 micro_all_pass: bool = False) -> BacktestSignal:
    entry = 4700.0
    stop = entry - sl_distance
    return BacktestSignal(
        timestamp=datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
        symbol="XAUUSD",
        strategy=STRATEGY_1_NAME,
        direction="LONG",
        entry=entry,
        stop=round(stop, 2),
        tp1=entry + sl_distance * 2,
        rr_tp1=2.0,
        score=score,
        metadata={
            "setup_mode": setup_mode,
            "micro_confluence": {"all_pass": micro_all_pass},
        },
    )


# ----------------------------------------------------------------------
# compute_micro_confluence
# ----------------------------------------------------------------------

def test_micro_confluence_all_pass_when_full_setup():
    res = compute_micro_confluence(
        sweep={"direction": "LONG"},
        fvg={"top": 4702, "bot": 4698},
        volume_confluence={"tag": "POC"},
        tp1_rr=2.5,
        min_rr=2.0,
    )
    assert res["sweep_present"] is True
    assert res["fvg_present"] is True
    assert res["liquidity_crack_present"] is True
    assert res["rr_ok"] is True
    assert res["all_pass"] is True


def test_micro_confluence_fails_when_rr_below_min():
    res = compute_micro_confluence(
        sweep={"direction": "LONG"},
        fvg={"top": 4702, "bot": 4698},
        volume_confluence={"tag": "POC"},
        tp1_rr=1.5,
        min_rr=2.0,
    )
    assert res["rr_ok"] is False
    assert res["all_pass"] is False


def test_micro_confluence_fails_when_no_post_sweep_zone():
    res = compute_micro_confluence(
        sweep={"direction": "LONG"},
        fvg=None,
        volume_confluence=None,
        tp1_rr=2.0,
        min_rr=2.0,
    )
    assert res["all_pass"] is False


# ----------------------------------------------------------------------
# Tier classification
# ----------------------------------------------------------------------

@pytest.mark.parametrize("sl,expected_tier,expected_reason", [
    (3.5, "tier_1", "tier_1_within_4"),
    (4.0, "tier_1", "tier_1_within_4"),
    (4.5, "tier_2", "tier_2_within_5"),
    (5.0, "tier_2", "tier_2_within_5"),
])
def test_tier_1_and_2_always_accept(sl, expected_tier, expected_reason):
    d = evaluate_adelin_sl_acceptance(sl_usd=sl, score=0, setup_mode=None, micro_confluence=None)
    assert d.accepted is True
    assert d.tier == expected_tier
    assert d.reason == expected_reason


def test_tier_3_accept_when_score_ge_85():
    d = evaluate_adelin_sl_acceptance(sl_usd=6.5, score=85, setup_mode=None, micro_confluence=None)
    assert d.accepted is True
    assert d.tier == "tier_3"
    assert d.reason == "tier_3_score_ge_85"


def test_tier_3_reject_when_score_below_85():
    d = evaluate_adelin_sl_acceptance(sl_usd=6.5, score=84, setup_mode=None, micro_confluence=None)
    assert d.accepted is False
    assert d.tier == "tier_3"
    assert d.reason == "rejected_score_below_85"


def test_tier_4_accept_when_score_ge_90():
    d = evaluate_adelin_sl_acceptance(sl_usd=7.0, score=90, setup_mode=None, micro_confluence=None)
    assert d.accepted is True
    assert d.tier == "tier_4"
    assert d.reason == "tier_4_score_ge_90"


def test_tier_4_accept_when_setup_a_plus():
    d = evaluate_adelin_sl_acceptance(
        sl_usd=7.0, score=85, setup_mode="LIQ_VP_NT_FVG_A_PLUS", micro_confluence=None
    )
    assert d.accepted is True
    assert d.reason == "tier_4_setup_a_plus"


def test_tier_4_accept_when_micro_confluence_all_pass():
    d = evaluate_adelin_sl_acceptance(
        sl_usd=7.0, score=70, setup_mode="LIQ_VP_NT_FVG_SCALP", micro_confluence={"all_pass": True}
    )
    assert d.accepted is True
    assert d.reason == "tier_4_micro_confluence"


def test_tier_4_reject_when_no_condition_satisfied():
    d = evaluate_adelin_sl_acceptance(
        sl_usd=7.0, score=80, setup_mode="LIQ_VP_NT_FVG_SCALP", micro_confluence={"all_pass": False}
    )
    assert d.accepted is False
    assert d.reason == "rejected_score_below_90_no_a_plus_no_micro"


def test_tier_4_disabled_rejects_even_when_a_plus():
    policy = AdelinSLPolicy(tier_4_enabled=False)
    d = evaluate_adelin_sl_acceptance(
        sl_usd=7.0, score=95,
        setup_mode="LIQ_VP_NT_FVG_A_PLUS",
        micro_confluence={"all_pass": True},
        policy=policy,
    )
    assert d.accepted is False
    assert d.reason == "rejected_tier_4_disabled"


def test_above_max_always_rejected():
    d = evaluate_adelin_sl_acceptance(
        sl_usd=7.5, score=100, setup_mode="LIQ_VP_NT_FVG_A_PLUS", micro_confluence={"all_pass": True}
    )
    assert d.accepted is False
    assert d.reason == "rejected_sl_above_max"


# ----------------------------------------------------------------------
# rejection_code format
# ----------------------------------------------------------------------

def test_rejection_code_includes_tier_and_reason():
    d = evaluate_adelin_sl_acceptance(sl_usd=6.5, score=70, setup_mode=None, micro_confluence=None)
    code = d.rejection_code()
    assert code is not None
    assert "SL_TOO_WIDE" in code
    assert "tier=tier_3" in code
    assert "reason=rejected_score_below_85" in code


def test_rejection_code_is_none_for_accepted():
    d = evaluate_adelin_sl_acceptance(sl_usd=3.0, score=70, setup_mode=None, micro_confluence=None)
    assert d.rejection_code() is None


# ----------------------------------------------------------------------
# _apply_adelin_sl_policy: mutation + diagnostics
# ----------------------------------------------------------------------

def test_apply_policy_accepts_signal_and_updates_diagnostics():
    sig = _make_signal(sl_distance=3.5, score=70)
    diag = AdelinDiagnostics()
    policy = AdelinSLPolicy()
    decision = _apply_adelin_sl_policy(sig, policy, diagnostics=diag)
    assert sig.accepted is True
    assert decision.tier == "tier_1"
    assert diag.sl_tier_counts == {"tier_1": 1}
    assert diag.sl_tier_acceptance_reason_counts == {"tier_1_within_4": 1}
    assert diag.ex_rejected_recovered_count == 0


def test_apply_policy_rejects_above_max_and_adds_rejection_reason():
    sig = _make_signal(sl_distance=7.5, score=95, setup_mode="LIQ_VP_NT_FVG_A_PLUS")
    diag = AdelinDiagnostics()
    decision = _apply_adelin_sl_policy(sig, AdelinSLPolicy(), diagnostics=diag)
    assert sig.accepted is False
    assert any("SL_TOO_WIDE" in r and "tier=rejected" in r for r in sig.rejection_reasons)
    assert decision.tier == "rejected"
    assert diag.sl_tier_counts == {"rejected": 1}


def test_apply_policy_ex_rejected_recovered_count_triggers_above_legacy_5usd():
    # Tier 3 accept with sl=6.5 (>5) -> recovered
    sig = _make_signal(sl_distance=6.5, score=85)
    diag = AdelinDiagnostics()
    _apply_adelin_sl_policy(sig, AdelinSLPolicy(), diagnostics=diag)
    assert sig.accepted is True
    assert diag.ex_rejected_recovered_count == 1
    # Tier 2 accept with sl=5.0 (==5, NOT >5) -> not recovered
    sig2 = _make_signal(sl_distance=5.0, score=70)
    diag2 = AdelinDiagnostics()
    _apply_adelin_sl_policy(sig2, AdelinSLPolicy(), diagnostics=diag2)
    assert diag2.ex_rejected_recovered_count == 0


# ----------------------------------------------------------------------
# BacktestConfig backward compatibility
# ----------------------------------------------------------------------

def test_backtest_config_default_has_no_adelin_sl_policy():
    cfg = BacktestConfig()
    assert cfg.adelin_sl_policy is None
    # Legacy cap is still there for backward compatibility
    assert cfg.per_strategy_max_sl["strategy_1_adelin_scalp"] == 5.0


def test_backtest_config_accepts_explicit_adelin_sl_policy():
    policy = AdelinSLPolicy(tier_4_enabled=False)
    cfg = BacktestConfig(adelin_sl_policy=policy)
    assert cfg.adelin_sl_policy is policy
    assert cfg.adelin_sl_policy.tier_4_enabled is False


def test_legacy_filter_still_rejects_when_policy_none():
    sig = _make_signal(sl_distance=6.0, score=70)
    cfg = BacktestConfig()
    _apply_per_strategy_sl_filter(sig, cfg.per_strategy_max_sl)
    assert sig.accepted is False
    assert any("SL_TOO_WIDE_for_strategy_1_adelin_scalp_max=5.0" in r for r in sig.rejection_reasons)


# ----------------------------------------------------------------------
# Constants alignment between metrics and runner
# ----------------------------------------------------------------------

def test_legacy_max_sl_constant_matches_between_modules():
    assert LEGACY_ADELIN_MAX_SL_USD == RUNNER_LEGACY_MAX_SL == 5.0


# ----------------------------------------------------------------------
# SL bucket performance
# ----------------------------------------------------------------------

def test_bucket_for_sl_classification():
    assert _bucket_for_sl(3.5) == "le_4.00"
    assert _bucket_for_sl(4.0) == "le_4.00"
    assert _bucket_for_sl(4.5) == "4.01_to_5.00"
    assert _bucket_for_sl(5.0) == "4.01_to_5.00"
    assert _bucket_for_sl(6.5) == "5.01_to_6.50"
    assert _bucket_for_sl(7.0) == "6.51_to_7.00"
    assert _bucket_for_sl(7.5) == "gt_7.00"


def test_sl_bucket_performance_counts_recovered_and_outcomes():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    sigs = [
        _make_signal(sl_distance=3.5, score=70),                  # T1 accept
        _make_signal(sl_distance=6.5, score=85),                  # T3 accept (recovered)
        _make_signal(sl_distance=7.0, score=70, micro_all_pass=True),  # T4 accept (recovered)
    ]
    for i, s in enumerate(sigs):
        s.timestamp = base + timedelta(hours=i)
    trades = [
        BacktestTrade(signal=sigs[0], outcome="TP1", exit_time=base, exit_price=4707, r_multiple=2.0, mae=0.5, mfe=7.0, bars_held=10),
        BacktestTrade(signal=sigs[1], outcome="TP1", exit_time=base, exit_price=4713, r_multiple=2.0, mae=1.0, mfe=13.0, bars_held=20),
        BacktestTrade(signal=sigs[2], outcome="SL", exit_time=base, exit_price=4693.0, r_multiple=-1.0, mae=7.0, mfe=2.0, bars_held=15),
    ]
    perf = compute_adelin_sl_bucket_performance(sigs, trades)
    assert perf["le_4.00"]["total_signals"] == 1
    assert perf["le_4.00"]["wins"] == 1
    assert perf["le_4.00"]["ex_rejected_recovered_count"] == 0  # 3.5 <= 5
    assert perf["5.01_to_6.50"]["wins"] == 1
    assert perf["5.01_to_6.50"]["ex_rejected_recovered_count"] == 1  # 6.5 > 5
    assert perf["6.51_to_7.00"]["losses"] == 1
    assert perf["6.51_to_7.00"]["ex_rejected_recovered_count"] == 1  # 7.0 > 5
    assert perf["gt_7.00"]["total_signals"] == 0


def test_bucket_definitions_match_policy_thresholds():
    policy = AdelinSLPolicy()
    bucket_uppers = [high for _, _, high in ADELIN_SL_BUCKETS]
    assert policy.tier_1_max_usd in bucket_uppers
    assert policy.tier_2_max_usd in bucket_uppers
    assert policy.tier_3_max_usd in bucket_uppers
    assert policy.tier_4_max_usd in bucket_uppers
