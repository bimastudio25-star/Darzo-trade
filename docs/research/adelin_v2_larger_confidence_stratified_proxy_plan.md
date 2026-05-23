# Adelin v2 Larger Confidence-Stratified Proxy Plan

## Context

The completed H3/H4 proxy diagnostic execution produced a useful descriptive result, but the follow-up methodology review concluded that the global 40-sample result is not the true primary evidence base.

Prior methodology decision:

REQUIRE_LARGER_CONFIDENCE_STRATIFIED_SAMPLE_DIAGNOSTIC_PLAN

Reason:

* The global 40-sample result is descriptive only.
* Effective primary evidence is only 21 confidence-3 / EXISTING_METADATA samples.
* PRE_DECISION_SWEEP_INFERENCE / confidence-2 samples are structurally correlated with H3 TIGHT and H4 INSIDE_ZONE.
* Confidence-2 samples must be treated as secondary or sensitivity evidence only.
* H3 formula, H3 thresholds, and H4 states must remain frozen.
* Phase 4 remains blocked.

Prior confidence-stratified result:

| Direction source | Confidence | N | H3 TIGHT | H3 NO_VALID_INVALIDATION_EXTREME | H4 INSIDE_ZONE | H4 RETEST_FAILED_PRE_DECISION |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| EXISTING_METADATA | 3 | 21 | 15/21 | 4/21 | 9/21 | 7/21 |
| PRE_DECISION_SWEEP_INFERENCE | 2 | 19 | 16/19 | 1/19 | 14/19 | 3/19 |

## Purpose

This document pre-registers a future larger H3/H4 proxy diagnostic design. The goal is to collect or identify a larger confidence-stratified sample before judging whether H3/H4 are stable descriptive separators.

This branch is plan-only. It does not collect samples, read OHLC, execute H3/H4 proxies, run replay, run backtest, run matched-control, start Phase 4, tune thresholds, modify runtime logic, or approve live trading.

## Evidence Hierarchy

1. Confidence-3 / EXISTING_METADATA = primary evidence.
2. Confidence-2 / PRE_DECISION_SWEEP_INFERENCE = secondary or sensitivity evidence.
3. Combined global sample = descriptive only and not a decision basis.

The previous global N=40 must not be used as primary evidence because 19 samples were confidence-2 sweep-inferred samples. Those samples are structurally correlated with H3 TIGHT and H4 INSIDE_ZONE.

## Primary Sample Target

The future diagnostic must target:

* At least 60 total confidence-3 / EXISTING_METADATA samples.
* The existing 21 confidence-3 samples already analyzed count toward the 60.
* Therefore at least 39 additional confidence-3 / EXISTING_METADATA samples are required, unless a later signed methodology review raises the target.

If fewer than 60 total confidence-3 samples are available, the future execution must report INSUFFICIENT_CONFIDENCE_3_SAMPLE. It must not lower the gate.

## Secondary Sample Handling

Confidence-2 / PRE_DECISION_SWEEP_INFERENCE samples may be included, but they must be reported separately and must not drive primary conclusions.

Confidence-2 rows can be used to ask whether the sweep-inferred subset behaves differently from the metadata-direction subset. They cannot be used to claim H3/H4 separator validity.

## Sample Sourcing Rules

The future execution must not leave sample sourcing ambiguous.

Allowed source A - existing unprocessed Adelin v2 artifacts:

* Allowed only if lineage is clear.
* Allowed only if decision_timestamp, direction, direction_source, direction_confidence, and reference/entry fields are present or reconstructable without future leakage.
* Must not silently mix different sample definitions.

Allowed source B - forward/new collection:

* Allowed only if collected with pre-registered criteria.
* Must preserve direction_source and direction_confidence.
* Must not select based on H3/H4 states, outcomes, TP/SL, PnL, MFE/MAE, or post-entry behavior.

Source C - broader historical OHLC mining:

* Not approved by this plan.
* If proposed later, it requires a separate pre-registered mining rule because it introduces different discovery bias.

Recommended sourcing rule:

* Primary source should be existing or newly collected Adelin v2 candidate/sample artifacts that contain explicit EXISTING_METADATA direction with confidence-3.
* Do not use H3/H4 proxy states to select or balance the sample.
* Do not use outcome labels to select the sample.
* Do not use TP/SL, PnL, R multiple, MFE/MAE, or future liquidity behavior to select the sample.
* If fewer than 60 total confidence-3 samples are available, report INSUFFICIENT_CONFIDENCE_3_SAMPLE.

H3/H4 states must be measured and reported after proxy computation. They must not be sampling quotas.

## Mandatory Future Stratification

The future execution must report H3/H4 distributions by:

* direction_source.
* direction_confidence.
* confidence-3 only.
* confidence-2 only.
* combined global sample, descriptive only.
* session, if available.
* date/week, if available.
* direction LONG/SHORT, if available.

## Honest Power And Coverage Statement

Even with 60 confidence-3 / EXISTING_METADATA samples, the diagnostic remains a methodology review sample, not proof of separator validity.

Reasons:

* H3 has multiple states.
* H4 has multiple states.
* H3 x H4 creates up to 20 state-combination cells.
* Adding LONG/SHORT or session stratification makes cells thinner.
* Rare states such as H3 WIDE, H4 NO_ZONE_AVAILABLE, and H4 RECLAIM_CONFIRMED may remain zero-count or low-count.
* Low-count cells must be treated as descriptive only.
* N=60 confidence-3 is a minimum gate for methodology review, not a profitability, edge, or validation threshold.

## Frozen H3 Rules

H3 remains:

TIGHT_SL_BEHIND_SPIKE_OR_SWING

Frozen rule:

* Formula frozen in commit 56dcff0.
* Candidate reference price to nearest valid pre-decision invalidation extreme.
* LONG uses nearest relevant pre-decision swing/sweep low.
* SHORT uses nearest relevant pre-decision swing/sweep high.
* Primary normalizer: M1 last 30 closed candles before decision.
* Fallback normalizer: M5 last 12 closed candles before decision.
* All candles must be before decision_timestamp.

Fixed thresholds:

* TIGHT <= 0.25.
* MEDIUM > 0.25 and <= 0.50.
* WIDE > 0.50.

Missing states:

* UNKNOWN_REFERENCE_PRICE.
* NO_VALID_INVALIDATION_EXTREME.
* INVALID_GEOMETRY.
* INSUFFICIENT_PRE_DECISION_RANGE.

## Frozen H4 Rules

H4 remains:

ZONE_RETEST_OR_RECLAIM

Frozen states:

* NO_ZONE_AVAILABLE.
* INSIDE_ZONE.
* RETEST_HELD.
* RECLAIM_CONFIRMED.
* RETEST_FAILED_PRE_DECISION.

## Strictly Forbidden Future Changes

The future diagnostic must not:

* Change H3 thresholds.
* Change the H3 formula.
* Change H4 states.
* Use outcome-derived thresholds.
* Tune thresholds from GOOD/FAST results.
* Tune thresholds from current H3/H4 distributions.
* Select samples based on H3/H4 states.
* Use post-entry candles for H3/H4 computation.
* Use TP/SL hit, PnL, R multiple, future MFE/MAE, or future liquidity behavior.
* Run matched-control unless separately approved in a later plan.
* Unlock Phase 4.

## Future Execution Design

A later execution branch may:

* Discover eligible Adelin v2 samples using the sourcing rules above.
* Read OHLC only for pre-decision proxy computation.
* Compute H3/H4 proxies using frozen definitions.
* Output per-sample and summary reports.
* Report confidence-stratified distributions.
* Report low-count cells as descriptive only.

That future branch must prove:

* OHLC reads used only candles with candle time < decision_timestamp.
* post_entry_data_used = 0.
* leakage_failures = 0.
* matched_control_run = false.
* phase_4_unlocked = false.
* runtime_logic_changed = false.

## Acceptance Criteria

Minimum requirements for the future diagnostic to be methodologically usable:

1. Primary sample size:
   * confidence-3 / EXISTING_METADATA samples >= 60 total, including the existing 21 already analyzed.

2. Additional confidence-3 requirement:
   * At least 39 additional confidence-3 / EXISTING_METADATA samples beyond the current 21, unless a later signed methodology review raises the target.

3. Leakage:
   * post_entry_data_used = 0.
   * leakage_failures = 0.

4. Input lineage:
   * All input artifacts documented.
   * No silent mixing of sample sources.
   * direction_source and direction_confidence present for every sample or explicitly marked missing.
   * Sample sourcing rule followed exactly.
   * Ambiguous lineage fails closed.

5. Reporting:
   * H3/H4 distributions reported separately for confidence-3 and confidence-2.
   * Combined distribution reported as descriptive only.
   * H3 WIDE count reported, including zero-count if applicable.
   * H3 missing states reported.
   * H4 RETEST_FAILED_PRE_DECISION reported.
   * H4 NO_ZONE_AVAILABLE reported.
   * Low-count cells marked descriptive only.
   * H3/H4 states not used as sampling quotas.

6. Gate status:
   * Phase 4 remains blocked.
   * Matched-control remains blocked.
   * Scoring remains blocked.
   * Runtime remains unchanged.
   * Live remains blocked.

## Future Decision Outcomes

LARGER_DIAGNOSTIC_USABLE_FOR_METHODOLOGY_REVIEW:

* >=60 total confidence-3 samples including the existing 21.
* Leakage clean.
* Lineage clean.
* H3/H4 distributions can be reviewed methodologically.
* Still no Phase 4 unlock.

INSUFFICIENT_CONFIDENCE_3_SAMPLE:

* Fewer than 60 total confidence-3 samples.
* Report remains descriptive only.
* Collect or identify more samples, or pause.

DIRECTION_SOURCE_BIAS_PERSISTS:

* Confidence-2 and confidence-3 distributions remain materially different.
* Confidence-2 stays secondary only.
* Primary conclusions must use confidence-3 only.

PROXY_SPEC_REVIEW_REQUIRED:

* Missing states, zero WIDE, or H4 failures indicate proxy definition may not separate useful states.
* Any revision must be pre-registered before further execution.

BLOCK_H3_H4_PROXY_PATH:

* Larger diagnostic shows H3/H4 are not useful or not stable enough.
* Keep Adelin research-only and do not continue this path.

No future decision outcome in this plan can unlock Phase 4, matched-control, scoring, live trading, Telegram alerts, broker execution, or order_send. Those would require separate methodology review and explicit approval.

## Safety

This branch:

* Does not read OHLC.
* Does not execute proxies.
* Does not run replay, backtest, or matched-control.
* Does not unlock Phase 4.
* Does not modify runtime logic.
* Does not modify Strategy 2.
* Does not modify Strategy 3.
* Does not modify `data/XAUUSD/*.csv`.
* Does not enable live, orders, Telegram, broker, or order_send.

Future branch:

* May read OHLC only if explicitly approved.
* Must read only pre-decision candles.
* Must prove post_entry_data_used = 0.
* Must prove leakage_failures = 0.
