# Adelin v2 Expanded Sample Plan Human Signoff

This signoff must be completed before any expanded sample collection branch starts.
Execution remains locked until the reviewer approves or requests changes.

## Context

- Prior diagnostic verdict: `MIXED_AMBIGUOUS_SMALL_N`
- Prior GOOD_FAST_REACTION N: 10 (minimum-N gate tripped)
- Prior FAST_FAILURE N: 27
- Plan version: `adelin_v2_good_fast_expanded_sample_plan_v1`
- Prior execution commit: `60824ca`
- Post-hoc disclosure commit: `9fdf3c8`

## Checklist

- [x] I confirm H1 (`fvg_ifvg_near_20p`) and H2 (`liquidity_htf_recent_level`) were selected post-hoc from an underpowered exploratory diagnostic (GOOD_FAST_REACTION N=10, verdict MIXED_AMBIGUOUS_SMALL_N).
- [x] I confirm H1 and H2 are not validated features and may be rejected by the expanded sample test.
- [x] I confirm H1 and H2 must not be treated as entry signals, filters, scoring components, or deployment evidence at this stage.
- [x] I confirm the minimum-N gate: GOOD_FAST_REACTION N must exceed 10 before STRONG_DESCRIPTIVE_SEPARATION can be considered; Phase 4 remains blocked until gate is cleared.
- [x] I confirm the hard minimums: GOOD_FAST_REACTION ≥ 11, FAST_FAILURE ≥ 25, total useful samples ≥ 60; targets are 20 / 40 / 80.
- [x] I confirm direction confidence 2 and confidence 3 results must be reported separately; confidence-2-only signal is marked weak/research-only.
- [x] I confirm the expanded sample collection must use only pre-entry, anti-leakage features per the approved feature test specs.
- [x] I confirm no replay, backtest, candidate generation, tuning, live, Telegram, orders, or broker execution are approved at this stage.
- [x] I confirm Phase 4 matched-control replay remains blocked under all current conditions and requires a separate gate review after N is cleared.
- [x] I confirm the direction recovery inference rule `adelin_v2_pre_decision_sweep_v1` applies to all samples with missing direction metadata; no post-entry data may be used.
- [x] I confirm execution remains locked until this signoff is filed.

## Signature

Reviewer: Adelin Bivol

Date: 2026-05-22

Decision: APPROVE

Notes:
Approved. H1 and H2 are acknowledged as post-hoc, unvalidated hypotheses from the N=10 GOOD_FAST_REACTION diagnostic. The expanded sample collection may proceed to test whether H1/H2 repeat on new samples, with the explicit understanding that both may be rejected. Phase 4 remains blocked until GOOD_FAST_REACTION N exceeds 10 and a separate gate review is completed. No live, Telegram, orders, or broker execution approved at this stage.
