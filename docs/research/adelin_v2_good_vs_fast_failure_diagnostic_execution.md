# Adelin v2 GOOD vs FAST Diagnostic Execution

## Context

Static Phase 3 labels were not usable, so Adelin v2 moved to objective pre-entry outcome diagnostics. Direction metadata recovery then restored direction coverage to 40/40, and the direction inference rule was frozen as `adelin_v2_pre_decision_sweep_v1`.

The GOOD_FAST_REACTION vs FAST_FAILURE plan was signed off before execution, including the strict minimum-N gate. Because `GOOD_FAST_REACTION` has N = 10, the gate is active before any descriptive finding is considered.

## Execution Scope

This branch ran only the bounded pre-registered diagnostic. It did not start Phase 4, did not run matched-control replay, did not modify runtime logic, did not create scoring, and did not create a live-entry filter.

The execution used existing recovered diagnostic rows and did not read OHLC in this branch. Existing diagnostic rows already contained pre-entry feature fields and post-entry diagnostic group labels. Post-entry fields were not used as pre-entry features.

## Inputs

- `docs/research/adelin_v2_good_vs_fast_failure_diagnostic_plan.md`
- `docs/research/adelin_v2_good_vs_fast_failure_diagnostic_plan_signoff.md`
- `backtests/reports/adelin_v2_good_vs_fast_failure_diagnostic_plan/`
- `backtests/reports/adelin_v2_direction_metadata_recovery/`
- `backtests/reports/adelin_v2_preentry_outcome_diagnostics_direction_recovered/sample_diagnostics.json`

## Sample Counts

Primary comparison groups:

- GOOD_FAST_REACTION: 10
- FAST_FAILURE: 27

Secondary groups excluded from the primary comparison:

- MIXED_REACTION: 2
- CHOP_AFTER_ENTRY: 1

## Minimum-N Gate

The minimum-N gate is active. `GOOD_FAST_REACTION` N = 10 triggers the rule:

- `STRONG_DESCRIPTIVE_SEPARATION` is forbidden
- strongest allowed verdict is `MIXED_AMBIGUOUS_SMALL_N`
- Phase 4 remains blocked regardless of observed effect size
- no confidence-stratum exception is allowed

## Feature Comparison

The largest pooled descriptive differences were:

- `fvg_ifvg_near_20p`: GOOD 3/10 (0.300) vs FAST 23/27 (0.852), difference -0.552
- `liquidity_htf_recent_level`: GOOD 6/10 (0.600) vs FAST 3/27 (0.111), difference +0.489
- `m1_large_body_ge_0_60`: GOOD 7/10 (0.700) vs FAST 8/27 (0.296), difference +0.404
- `m1_close_high_ge_0_70`: GOOD 7/10 (0.700) vs FAST 10/27 (0.370), difference +0.330
- `wick_body_m1_wick_dominant`: GOOD 1/10 (0.100) vs FAST 11/27 (0.407), difference -0.307

These are descriptive only. They are not significance results, not optimized thresholds, not scoring rules, and not evidence for deployment.

## Confidence Sensitivity

Confidence-3-only sensitivity is required and was produced. The largest confidence-3 descriptive differences were:

- `m1_large_body_ge_0_60`: GOOD 5/5 (1.000) vs FAST 3/16 (0.188), difference +0.812
- `fvg_ifvg_near_20p`: GOOD 0/5 (0.000) vs FAST 12/16 (0.750), difference -0.750
- `liquidity_htf_recent_level`: GOOD 4/5 (0.800) vs FAST 1/16 (0.062), difference +0.738

Confidence-2-only caution output was also produced. Any confidence-2-only pattern is weak/research-only because those directions are inferred from pre-decision sweep evidence rather than original metadata. Confidence-2 separation cannot unlock Phase 4.

## Leakage Check

Leakage check passed:

- forbidden fields found as features: none
- post-entry feature usage detected: false
- post-entry candles used: false
- non-directional max move replay used as primary evidence: false

## Verdict

Final verdict: `MIXED_AMBIGUOUS_SMALL_N`

The verdict is capped by the minimum-N gate. This branch does not and cannot produce `STRONG_DESCRIPTIVE_SEPARATION`.

## Next Actions

Allowed:

- more sample collection
- bounded confirmatory diagnostic
- human review of priority samples

Not allowed:

- Phase 4
- matched-control replay
- live trading
- scoring
- profitability claims

## Safety

No runtime logic changed. Strategy 2 and Strategy 3 were untouched. No live trading, orders, Telegram alerts, broker execution, matched-control replay, Phase 4, scoring, tuning, or v3 stash apply/pop occurred.
