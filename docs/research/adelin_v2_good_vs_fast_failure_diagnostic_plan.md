# Adelin v2 GOOD_FAST_REACTION vs FAST_FAILURE Diagnostic Plan

## Context

Static Phase 3 labeling was not usable because the human reviewer could not reliably label the original static M1/M5/M15 charts. Objective pre-entry outcome diagnostics were then created, direction metadata was recovered, and direction inference governance was frozen before any further diagnostic work.

Current validated baseline, carried forward as context only:

- total samples: 40
- direction coverage: 40/40
- existing metadata direction: 21 samples at confidence 3
- inferred pre-decision sweep direction: 19 samples at confidence 2
- post-entry data used for direction recovery: 0
- inference rule version: `adelin_v2_pre_decision_sweep_v1`
- prior diagnostic outcomes: 27 `FAST_FAILURE`, 10 `GOOD_FAST_REACTION`, 2 `MIXED_REACTION`, 1 `CHOP_AFTER_ENTRY`

Failure and win tags are multi-label and separated by `|`; they must not be interpreted as mutually exclusive buckets.

## Purpose

This document pre-registers how a later branch may compare `GOOD_FAST_REACTION` samples against `FAST_FAILURE` samples. The plan is written before the comparison is executed so the later diagnostic cannot move feature definitions, thresholds, inclusion rules, or interpretation rules after seeing the result.

## Non-purpose

This branch does not execute analysis. It does not read OHLC data, inspect candles, run replay, run matched-control replay, generate candidates, produce feature-vs-outcome tables, tune features, create scoring, or start Phase 4.

This is not validation, not profitability evidence, not strategy scoring, and not a deployment decision.

## Included And Excluded Groups

Primary comparison groups:

- `GOOD_FAST_REACTION`
- `FAST_FAILURE`

Secondary review groups, excluded from the primary GOOD vs FAST comparison:

- `MIXED_REACTION`
- `CHOP_AFTER_ENTRY`

The secondary groups may be reviewed separately in a later branch, but they must not be mixed into the primary separation test.

## Direction Confidence Handling

The primary planned analysis may include both confidence 3 and confidence 2 samples, but every result must be stratified by direction confidence and direction source.

Mandatory sensitivity analysis:

- confidence 3 only

Guardrails:

- confidence 2 samples are inferred from pre-decision sweep evidence and must not be treated as identical to original metadata direction
- if separation exists mainly or only in confidence 2 samples, the result is weak and research-only
- if confidence 3 sensitivity does not support the same direction as the pooled analysis, do not proceed to Phase 4

## Allowed Pre-entry Feature Families

Only features known before `decision_timestamp` may be used. The later execution branch may define deterministic formulas for:

- numeric level confluence
- round level proximity
- pre-decision sweep type
- M1 candle anatomy before decision
- M5 candle anatomy before decision
- M15 context before decision
- wick/body proxy before decision
- compression/overlap proxy before decision
- FVG/IFVG proximity if available pre-entry
- session/hour
- volatility/range context before decision
- target space proxy available at decision
- direction confidence stratum
- direction source stratum

## Forbidden Leakage Features

The later execution branch must not use:

- TP hit
- SL hit
- pnl
- r_multiple
- future MFE
- future MAE
- post-entry candles
- future liquidity behavior
- outcome-derived thresholds
- feature thresholds selected after looking at GOOD vs FAST separation
- any field created after seeing whether setup was `GOOD_FAST_REACTION` or `FAST_FAILURE`
- non-directional max move replay as primary evidence

Post-entry information may identify the already existing diagnostic group, but it must not define pre-entry features.

## Planned Descriptive Comparison Method

A later execution branch may produce:

- descriptive feature frequency table
- difference in proportions
- confidence-3-only sensitivity
- confidence-2-only caution table
- human review priority list
- leakage check report

The later execution branch must not produce:

- statistical significance claims
- ML classifier
- optimized thresholds
- score generation
- live-entry filter
- profitability claim

Small-N warning: `GOOD_FAST_REACTION` has N=10 in the prior baseline. That is too small for strong conclusions. Any later output is diagnostic only.

## Strict Minimum-N Gate

The following minimum-N gate is locked before any GOOD vs FAST execution branch:

- current `GOOD_FAST_REACTION` N: 10
- current `FAST_FAILURE` N: 27
- if any primary group has N <= 10, `STRONG_DESCRIPTIVE_SEPARATION` is forbidden
- if the gate is tripped, Phase 4 remains blocked
- if the gate is tripped, the strongest allowed verdict is `MIXED_AMBIGUOUS_SMALL_N`
- an optional directional/descriptive note is allowed
- allowed next actions are more sample collection or a bounded confirmatory diagnostic
- Phase 4 matched-control replay is not an allowed next action

There is no confidence-stratum exception. Even if a future comparison found a visually interesting confidence-3 subset, N <= 10 in any primary group still blocks `STRONG_DESCRIPTIVE_SEPARATION`.

## Decision Matrix

### A. Strong descriptive separation

If the minimum-N gate is not tripped, one or two pre-entry features show strong descriptive separation, and the same pattern appears in confidence-3-only sensitivity:

- allow a small confirmatory diagnostic branch
- still no Phase 4 unless reviewed

### B. Confidence-2-only separation

If separation exists mainly or only in confidence-2 inferred-direction samples:

- mark weak
- require more data or manual review
- do not proceed to Phase 4

### C. No stable separation

If no stable pre-entry separation exists:

- pause Adelin v2 as a strategy candidate
- optionally keep it as a research lab
- do not proceed to Phase 4

### D. Leakage-dependent separation

If separation requires post-entry interpretation:

- reject the feature
- mark leakage risk
- do not proceed to Phase 4

### E. Mixed or ambiguous

If separation is ambiguous due small N, or any primary group has N <= 10:

- allow only an optional directional/descriptive note
- require more sample collection or a bounded confirmatory diagnostic
- no Phase 4

## Phase 4 Gate

Phase 4 matched-control replay remains blocked until:

- this plan is reviewed and signed off
- a separate execution branch runs only the planned diagnostic
- the diagnostic is reviewed
- leakage checks pass
- confidence-3 sensitivity is acceptable
- a human methodology gate approves proceeding

## Output Artifacts

This branch creates:

- `backtests/reports/adelin_v2_good_vs_fast_failure_diagnostic_plan/diagnostic_plan.json`
- `backtests/reports/adelin_v2_good_vs_fast_failure_diagnostic_plan/allowed_features.json`
- `backtests/reports/adelin_v2_good_vs_fast_failure_diagnostic_plan/excluded_features.json`
- `backtests/reports/adelin_v2_good_vs_fast_failure_diagnostic_plan/comparison_schema.json`
- `backtests/reports/adelin_v2_good_vs_fast_failure_diagnostic_plan/decision_matrix.json`
- `backtests/reports/adelin_v2_good_vs_fast_failure_diagnostic_plan/summary.json`

## Safety

No OHLC was read in this planning branch. No replay was run. No matched-control replay was run. No runtime logic was modified. Strategy 2 and Strategy 3 were untouched. No live trading, orders, Telegram trade alerts, broker execution, or v3 stash apply/pop occurred.
