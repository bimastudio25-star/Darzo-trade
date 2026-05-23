# Adelin v2 H3/H4 Proxy Methodology Review

## Context

This document reviews the completed Adelin v2 H3/H4 proxy diagnostic execution in:

* `backtests/reports/adelin_v2_h3_h4_proxy_diagnostic_execution/summary.json`
* `backtests/reports/adelin_v2_h3_h4_proxy_diagnostic_execution/h3_h4_proxy_group_summary.csv`
* `backtests/reports/adelin_v2_h3_h4_proxy_diagnostic_execution/h3_h4_proxy_per_sample.csv`
* `docs/research/adelin_v2_h3_h4_proxy_diagnostic_execution.md`

This review is methodology-only. It does not run new diagnostics, read OHLC, execute H3/H4 proxies, run replay, run backtest, run matched-control, tune thresholds, modify runtime logic, or unlock Phase 4.

## Execution Results Reviewed

The completed diagnostic reported:

* Total samples: 40.
* Executable samples: 40.
* Skipped samples: 0.
* H3 state counts:
  * TIGHT: 31/40 = 77.5%.
  * MEDIUM: 4/40 = 10.0%.
  * WIDE: 0/40 = 0.0%.
  * NO_VALID_INVALIDATION_EXTREME: 5/40 = 12.5%.
* H4 state counts:
  * INSIDE_ZONE: 23/40 = 57.5%.
  * RETEST_FAILED_PRE_DECISION: 10/40 = 25.0%.
  * RECLAIM_CONFIRMED: 6/40 = 15.0%.
  * NO_ZONE_AVAILABLE: 1/40 = 2.5%.
* Leakage failures: 0.
* Matched-control run: false.
* Phase 4 unlocked: false.
* Runtime logic changed: false.

## Direction Source And Confidence Stratification

The key methodology issue is direction-source and direction-confidence sample-selection bias.

Verified cross-tab from `h3_h4_proxy_per_sample.csv`:

| Direction source | Confidence | N | H3 TIGHT | H3 NO_VALID_INVALIDATION_EXTREME | H4 INSIDE_ZONE | H4 RETEST_FAILED_PRE_DECISION |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| EXISTING_METADATA | 3 | 21 | 15/21 = 71.4% | 4/21 = 19.0% | 9/21 = 42.9% | 7/21 = 33.3% |
| PRE_DECISION_SWEEP_INFERENCE | 2 | 19 | 16/19 = 84.2% | 1/19 = 5.3% | 14/19 = 73.7% | 3/19 = 15.8% |

Methodological consequence:

PRE_DECISION_SWEEP_INFERENCE samples are structurally correlated with H3 TIGHT and H4 INSIDE_ZONE. The direction recovery rule uses a recent pre-decision sweep. That same sweep can become the H3 invalidation extreme, and it can also help define an active H4 zone or zone interaction. Therefore, the combined global N=40 must not be treated as independent primary evidence for H3/H4 separator validity.

Evidence hierarchy for future work:

* Confidence-3 / EXISTING_METADATA rows are the primary evidence set.
* Confidence-2 / PRE_DECISION_SWEEP_INFERENCE rows are secondary or sensitivity evidence only.
* Combined global N=40 is descriptive only and must not be the decision basis.
* Effective primary sample size for H3/H4 separator review is 21, not 40.
* Future larger-sample diagnostics must target at least 60 confidence-3 / EXISTING_METADATA samples before evaluating H3/H4 as real separators.

## Review Questions

### 1. H3 TIGHT Dominance

Observed:

* Global H3 TIGHT: 31/40 = 77.5%.
* Confidence-3 H3 TIGHT: 15/21 = 71.4%.
* Confidence-2 H3 TIGHT: 16/19 = 84.2%.

Review:

H3 TIGHT dominance appears partly real within this sample family because it remains common even in confidence-3 rows. However, it is also boosted by direction-recovery selection. The confidence-2 sweep-inferred subset has a higher TIGHT rate because the recovered direction is anchored to a pre-decision sweep, and that sweep can become the nearest invalidation extreme by construction.

Conclusion:

Do not treat global 77.5% as independent evidence. For separator validity, the relevant first read is confidence-3 only: 15/21 = 71.4%, still descriptive and still underpowered.

### 2. Zero H3 WIDE Samples

Observed:

* H3 WIDE: 0/40.

Review:

The absence of WIDE samples may mean the fixed 0.50 threshold is too loose or high for this selected sample set. It may also mean the sample lineage is already concentrated around invalidation-zone examples, especially because many rows come from a review pack and 19 directions are sweep-inferred.

Conclusion:

Do not change thresholds from this result. Any H3 threshold review must be separate, pre-registered work. The current 0.25 / 0.50 thresholds remain frozen.

### 3. H4 INSIDE_ZONE Dominance

Observed:

* Global H4 INSIDE_ZONE: 23/40 = 57.5%.
* Confidence-3 H4 INSIDE_ZONE: 9/21 = 42.9%.
* Confidence-2 H4 INSIDE_ZONE: 14/19 = 73.7%.

Review:

H4 appears more affected by direction-recovery bias than H3. The confidence-2 rows were recovered from pre-decision sweep structure, which tends to place price near or inside an active zone. That creates a structural pathway from the direction recovery method to H4 INSIDE_ZONE.

Conclusion:

The global H4 INSIDE_ZONE rate must be treated as descriptive only. Confidence-3-only H4 INSIDE_ZONE, 9/21 = 42.9%, is the primary baseline for future methodology review.

### 4. H4 RETEST_FAILED_PRE_DECISION

Observed:

* Global H4 RETEST_FAILED_PRE_DECISION: 10/40 = 25.0%.
* Confidence-3: 7/21 = 33.3%.
* Confidence-2: 3/19 = 15.8%.

Review:

RETEST_FAILED_PRE_DECISION is more common in confidence-3 rows than confidence-2 rows. This may make it useful as a negative or pre-failure category. However, it can also mean that those rows should be excluded from "valid H4 zone interaction" evaluation if the future question is specifically whether held/reclaimed zones are useful.

Consequences:

* Keep as negative/pre-failure category: preserves information about failed zone behavior and may help explain weak setups. It also keeps the H4 state machine honest.
* Exclude from valid-zone evaluation: narrows H4 to constructive zone behavior only, but risks hiding failed pre-decision zone interactions and must be pre-registered before execution.

Conclusion:

Keep RETEST_FAILED_PRE_DECISION as a negative/pre-failure category for now. Do not exclude it without a future pre-registered plan.

### 5. H3 Missing States

Observed:

* Global H3 NO_VALID_INVALIDATION_EXTREME: 5/40 = 12.5%.
* Confidence-3: 4/21 = 19.0%.
* Confidence-2: 1/19 = 5.3%.

Review:

Confidence-3 rows have a higher missing-invalidation rate because their direction comes from existing metadata, not from a pre-decision sweep inference that already supplies a nearby sweep extreme candidate. This is expected and is exactly why confidence-2 rows cannot be treated as equal primary evidence.

Conclusion:

The 12.5% global missing rate is acceptable for a proxy diagnostic, but the confidence-3 missing rate of 19.0% must be carried forward as a real computability limitation.

### 6. H4 Missing States

Observed:

* H4 NO_ZONE_AVAILABLE: 1/40 = 2.5%.

Review:

The low NO_ZONE_AVAILABLE rate suggests H4 metadata coverage is strong for this sample artifact. However, this does not prove H4 is robust generally because H4 zone availability depends on existing pre-entry metadata fields such as FVG/iFVG zone bounds, numeric levels, and liquidity-level metadata.

Conclusion:

H4 metadata coverage is acceptable for this sample set, but future diagnostics must still report zone source and metadata dependency explicitly.

### 7. Sample Size And Lineage

Observed:

* Total samples: 40.
* Primary effective sample: 21 confidence-3 / EXISTING_METADATA samples.
* Secondary/sensitivity sample: 19 confidence-2 / PRE_DECISION_SWEEP_INFERENCE samples.
* Input artifact: `backtests/reports/adelin_v2_preentry_outcome_diagnostics_direction_recovered/sample_diagnostics.csv`.

Review:

The input artifact is appropriate for reviewing the completed H3/H4 execution because it has direction-resolved Adelin v2 samples, decision timestamps, and entry reference prices. It is still descriptive only. The sample set includes 19 direction-recovered rows where the recovery method can mechanically increase H3 TIGHT and H4 INSIDE_ZONE rates.

Conclusion:

The sample lineage is usable for a descriptive methodology review, not for separator validation, Phase 4, matched-control, scoring, or deployment claims.

### 8. Safety And Gates

Confirmed for this review branch:

* Review-only: yes.
* OHLC read: no.
* New H3/H4 proxy execution: no.
* Replay/backtest/matched-control: no.
* Phase 4 unlock: no.
* Runtime logic changes: no.
* Live/orders/Telegram/broker/order_send: no.

## Decision Matrix

### A. ACCEPT_PROXY_AS_DESCRIPTIVE_ONLY

Meaning:

* Current H3/H4 proxy results are usable only as descriptive metadata.
* No confirmatory run yet.
* Phase 4 remains blocked.

### B. REQUIRE_LARGER_SAMPLE_DIAGNOSTIC_PLAN

Meaning:

* Current 40 samples are too biased/small.
* Next step should be a pre-registered larger-sample diagnostic plan.
* No threshold changes allowed yet.

### C. REQUIRE_LARGER_CONFIDENCE_STRATIFIED_SAMPLE_DIAGNOSTIC_PLAN

Meaning:

* Current global N=40 is not the true primary evidence size.
* Confidence-3-only N=21 is the effective primary sample for separator validity.
* Future diagnostic must stratify by direction_source and direction_confidence.
* Confidence-2 samples are secondary/sensitivity only.
* Larger diagnostic must target at least 60 confidence-3 samples before evaluating H3/H4 as real separators.
* No H3 threshold or H4 state changes allowed yet.

### D. REQUIRE_PROXY_SPEC_REVISION

Meaning:

* H3/H4 proxy definitions are not yet stable enough.
* Future work must revise proxy spec before more OHLC execution.
* Any revision must be pre-registered before looking at outcome distributions.

### E. BLOCK_FURTHER_ADELIN_H3_H4_WORK

Meaning:

* Proxy diagnostics do not provide enough value.
* Stop this path and keep Adelin archived/research-only.

## Recommended Decision

Recommended decision:

REQUIRE_LARGER_CONFIDENCE_STRATIFIED_SAMPLE_DIAGNOSTIC_PLAN

Justification:

* The 40-sample result is descriptive only.
* Effective primary N is only 21 confidence-3 samples.
* Confidence-2 PRE_DECISION_SWEEP_INFERENCE samples are structurally correlated with H3 TIGHT and H4 INSIDE_ZONE.
* H3 TIGHT dominance is partly real within the sample and partly boosted by sample selection.
* H4 INSIDE_ZONE is more strongly affected by direction-recovery bias.
* H3 formula, H3 thresholds 0.25 / 0.50, and H4 states must remain frozen to avoid tuning on observed results.
* Phase 4 remains blocked.

## Mandatory Next-Step Requirements

A future larger-sample plan must include:

1. Minimum target:
   * At least 60 confidence-3 / EXISTING_METADATA samples before evaluating H3/H4 separator validity.

2. Stratification:
   * Report all H3/H4 distributions separately for direction_source.
   * Report all H3/H4 distributions separately for direction_confidence.
   * Report confidence-3 only.
   * Report confidence-2 only.
   * Report combined global sample only as descriptive context.

3. Evidence hierarchy:
   * Confidence-3 only = primary evidence.
   * Confidence-2 = secondary/sensitivity evidence.
   * Global combined = descriptive only, not decision basis.

4. Frozen rules:
   * H3 formula frozen.
   * H3 thresholds 0.25 / 0.50 frozen.
   * H4 states frozen.
   * No tuning based on GOOD/FAST outcomes.
   * No threshold changes based on current distributions.

5. Gate status:
   * Phase 4 remains blocked.
   * Matched-control remains blocked.
   * Scoring remains blocked.
   * Live remains blocked.

## Safety Statement

This review did not read OHLC, execute new proxy computation, run replay, run backtest, run matched-control, start Phase 4, modify H3 thresholds, modify H3 formula, modify H4 states, tune anything from results, modify runtime logic, modify Strategy 2, modify Strategy 3, modify `data/XAUUSD/*.csv`, enable live trading, place orders, call or introduce order_send, send Telegram alerts, call broker execution, claim edge, claim profitability, or claim deployability.
