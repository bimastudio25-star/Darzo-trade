# Adelin v2 Expanded Sample Diagnostic Execution

## Context

Adelin v2 remains research-only. The static manual chart-labeling path was not usable, direction recovery/governance was completed, and the GOOD_FAST_REACTION vs FAST_FAILURE diagnostic produced post-hoc exploratory H1/H2 candidates from an underpowered baseline.

The expanded sample plan was signed off after explicit post-hoc disclosure:

- H1: `fvg_ifvg_near_20p` as a possible FAST_FAILURE marker.
- H2: `liquidity_htf_recent_level` as a possible GOOD_FAST_REACTION marker.
- Both hypotheses are not validated and may be rejected by future tests.
- Phase 4 remains blocked.

## Execution Scope

This branch ran only the signed expanded/new-sample diagnostic. It did not run Phase 4, matched-control replay, candidate generation, live trading, scoring, runtime strategy logic, Telegram alerts, broker code, or order execution.

OHLC was read only to compute frozen pre-entry H1/H2 and secondary diagnostic features from candles strictly before `decision_timestamp`.

## Inputs

- `docs/research/adelin_v2_good_fast_expanded_sample_plan.md`
- `docs/research/adelin_v2_good_fast_expanded_sample_plan_signoff.md`
- `backtests/reports/adelin_v2_good_fast_expanded_sample_plan/`
- `backtests/reports/adelin_v2_expanded_objective_outcome_replay/objective_outcome_replay.csv`
- `backtests/reports/adelin_v2_expanded_candidate_window_pack/manual_labels_template.csv`
- `data/XAUUSD/`

## Sample Collection

Samples were selected from existing expanded objective replay rows only:

- Sample source: `EXISTING_EXPANDED_OBJECTIVE_REPLAY`
- Samples selected: 197
- Excluded samples: 103
- Duplicate/manual cherry-pick selection was not used.

Included group counts:

- `GOOD_FAST_REACTION`: 47
- `FAST_FAILURE`: 112
- `MIXED_REACTION`: 11
- `CHOP_AFTER_ENTRY`: 27

Primary H1/H2 comparison used only `GOOD_FAST_REACTION` and `FAST_FAILURE`. `MIXED_REACTION` and `CHOP_AFTER_ENTRY` remain secondary/review-only groups.

## Minimum-N Gate

The expanded hard minimum gates passed:

- Total hard minimum: 60, observed 197
- GOOD_FAST_REACTION hard minimum: 11, observed 47
- FAST_FAILURE hard minimum: 25, observed 112

The target gates also passed:

- Total target: 80
- GOOD_FAST_REACTION target: 20
- FAST_FAILURE target: 40

The prior `GOOD_FAST_REACTION <= 10` cap did not trigger on the expanded sample.

## H1/H2 Results

H1 repeated directionally:

- `fvg_ifvg_near_20p`: GOOD 22/47 (0.468) vs FAST 86/112 (0.768)
- Difference GOOD minus FAST: -0.300
- Expected direction: more frequent in FAST_FAILURE
- Result: repeated directionally

H2 did not repeat directionally:

- `liquidity_htf_recent_level`: GOOD 20/47 (0.426) vs FAST 51/112 (0.455)
- Difference GOOD minus FAST: -0.030
- Expected direction: more frequent in GOOD_FAST_REACTION
- Result: failed to repeat directionally

Because at least one frozen primary hypothesis failed to repeat, the final verdict is `HYPOTHESES_FAIL_TO_REPEAT`.

## Secondary Features

Secondary features were tracked only and did not influence the verdict:

- `m1_large_body_ge_0_60`: GOOD 20/47 (0.426) vs FAST 40/112 (0.357), difference +0.068
- `m1_close_high_ge_0_70`: GOOD 16/47 (0.340) vs FAST 35/112 (0.312), difference +0.028

These remain secondary descriptive notes and are not promoted to primary hypotheses.

## Confidence Stratification

Confidence 3 sensitivity:

- H1 repeated: GOOD 16/30 (0.533) vs FAST 47/62 (0.758), difference -0.225
- H2 failed: GOOD 11/30 (0.367) vs FAST 25/62 (0.403), difference -0.037

Confidence 2 caution:

- H1 repeated: GOOD 6/17 (0.353) vs FAST 39/50 (0.780), difference -0.427
- H2 was near flat: GOOD 9/17 (0.529) vs FAST 26/50 (0.520), difference +0.009

Confidence 2/inferred-direction samples remain weaker research evidence and cannot unlock Phase 4.

## Leakage Check

Leakage check passed:

- No post-entry candles were used to compute H1/H2.
- No TP, SL, PnL, R multiple, future MFE/MAE, or non-directional max-move replay was used as feature evidence.
- No outcome-derived thresholds were used.
- No manual cherry-pick source was used.
- No Phase 4 or matched-control logic was used.

## Verdict

Final verdict: `HYPOTHESES_FAIL_TO_REPEAT`

Reason: H1 repeated directionally, but H2 failed to repeat directionally on the expanded sample and in confidence-3-only sensitivity.

Phase 4 remains blocked in all cases. This result is descriptive only and is not evidence of edge, profitability, deployability, or live readiness.

## Next Actions

Allowed:

- Human review of priority samples.
- Pause Adelin v2 strategy-path work if H2 failure is accepted as sample-specific.
- A bounded confirmatory diagnostic only if a separate reviewed plan explicitly justifies it.

Not allowed:

- Phase 4 matched-control replay.
- Live trading.
- Scoring or live filters.
- Telegram trade alerts.
- Broker/order execution.
- Profitability, validation, or deployment claims.

## Safety

- No matched-control replay was run.
- No runtime logic was modified.
- Strategy 2 was untouched.
- Strategy 3 was untouched.
- No live trading was enabled.
- No orders were placed.
- No Telegram trade alerts were sent.
- No broker execution was called.
- The v3 stash was not applied or popped.
