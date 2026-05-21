# Adelin v2 Pre-entry Outcome Diagnostics

Status: research-only diagnostic replay. This replaces the unusable static
manual-label workflow for now; it does not replace the gated roadmap and does
not start Phase 4 matched-control testing.

## Context

The Phase 3 visual review label infrastructure was created and reviewed, but
static M1/M5/M15 charts are not reliable enough for the human reviewer to
label 40 samples manually. This branch therefore creates objective diagnostic
reports that separate:

- pre-entry measurable context;
- post-entry objective replay outcomes;
- diagnostic tags assigned after replay.

This is not a backtest, not matched-control replay, not optimization, and not
deployment evidence.

## Inputs

The script reads:

- `backtests/reports/adelin_v2_visual_review_pack/manual_labels_template.csv`
- `backtests/reports/adelin_v2_phase_3_visual_review_labels/phase_3_label_schema.json`
- `backtests/reports/adelin_v2_pre_registered_context_feature_test_plan/feature_test_specs.json`
- `data/XAUUSD/M1.csv`
- `data/XAUUSD/M5.csv`
- `data/XAUUSD/M15.csv`
- `data/XAUUSD/H1.csv`

The script does not generate candidate windows. It uses the existing 40 visual
review samples only.

## Outputs

Output directory:

`backtests/reports/adelin_v2_preentry_outcome_diagnostics/`

Files:

- `sample_diagnostics.csv`
- `sample_diagnostics.json`
- `feature_outcome_summary.csv`
- `failure_modes_summary.csv`
- `win_modes_summary.csv`
- `human_review_priority.csv`
- `summary.json`
- `objective_summary.md`

## Method

For each existing sample, the script computes pre-entry context at or before
the decision timestamp:

- direction if available from sample metadata;
- entry reference price from the last completed M1/M5/M15 close at decision;
- nearest recent liquidity proxy;
- distance to liquidity;
- numeric level proximity;
- FVG/IFVG proximity proxy;
- M1/M5/M15 candle anatomy;
- wick/body ratios;
- compression/overlap proxy;
- expansion-before-decision proxy;
- tick-volume ratio if available;
- session;
- volatility/range context;
- target-space proxy;
- default 20/40 pip SL price proxies.

Then the script computes post-entry objective replay diagnostics using the
forward M1 path:

- MFE and MAE in pips, USD, and 20-pip R proxy;
- time to first +50 and +100 pip favorable reaction;
- time to first 20 and 40 pip adverse move;
- proxy TP milestones at 50/100/250/500 pips;
- proxy SL20/SL40 hits;
- entry cross count in first 60 minutes;
- final diagnostic outcome;
- failure/win mode tags.

## Leakage rule

Post-entry data is used only for diagnostic outcomes and failure/win mode
tags. It is not used to redefine pre-entry features in this branch.

No thresholds are tuned from results. Thresholds are diagnostic-only proxies
for sorting samples and finding failure modes.

## Diagnostic tags

Failure tags include:

- `NO_IMMEDIATE_REACTION`
- `REACTION_TOO_LATE`
- `PRICE_CHOP_AFTER_ENTRY`
- `TARGET_TOO_FAR`
- `STOP_TOO_TIGHT`
- `STOP_TOO_WIDE`
- `DIRTY_LIQUIDITY_CONTEXT`
- `LIQUIDITY_ALREADY_CONSUMED`
- `VOLUME_NOT_CONFIRMING_REVERSAL`
- `CONTINUATION_AGAINST_ENTRY`
- `INSUFFICIENT_DATA`

Win tags include:

- `FAST_REACTION`
- `CLEAN_SWEEP_REJECTION`
- `ROUND_LEVEL_REACTION`
- `FVG_IFVG_REACTION`
- `VOLUME_CRACK_REACTION`
- `CLEAN_TARGET_SPACE`
- `STRONG_MFE_LOW_MAE`

These tags are descriptive. They are not strategy labels and are not proof of
edge.

## Smoke result

The smoke run analyzed 40 existing visual-review samples.

- Samples with sufficient directional replay data: 21
- Samples with insufficient data: 19
- Main limitation: `UNKNOWN_DIRECTION_NO_DIRECTIONAL_REPLAY`

Top failure modes:

- `INSUFFICIENT_DATA`: 19
- `CONTINUATION_AGAINST_ENTRY`: 15
- `PRICE_CHOP_AFTER_ENTRY`: 12
- `REACTION_TOO_LATE`: 8
- `NO_IMMEDIATE_REACTION`: 6

Top win modes:

- `CLEAN_TARGET_SPACE`: 17
- `FVG_IFVG_REACTION`: 9
- `ROUND_LEVEL_REACTION`: 6
- `FAST_REACTION`: 5
- `STRONG_MFE_LOW_MAE`: 4

Interpretation: this is descriptive only. The counts are not edge evidence
because there are no matched controls and many samples lack direction.

## Human review priority

`human_review_priority.csv` ranks samples for later human inspection where:

- outcome is extreme;
- feature/outcome conflict exists;
- replay is ambiguous;
- data is insufficient;
- setup looks diagnostically important.

This priority list is intended to make human review smaller and sharper, not
to select trades.

## Verdict flags

- `STATIC_LABELING_NOT_USABLE`
- `OBJECTIVE_REPLAY_DIAGNOSTICS_COMPLETE`
- `PRE_ENTRY_OUTCOME_SEPARATION_REPORTED`
- `FAILURE_MODES_REPORTED`
- `NO_PHASE_4_MATCHED_CONTROL_YET`
- `ADELIN_REMAINS_RESEARCH_ONLY`
- `NO_LIVE_DEPLOYMENT_DECISION`

## Safety

No old Adelin runtime was modified.

No Strategy 2 files were modified.

No Strategy 3 files were modified.

No candidate pack was generated.

No matched-control replay was run.

No Phase 4 was started.

No thresholds were optimized.

No live trading was enabled.

No Telegram trade alerts were sent.

No broker/order execution was called.

The v3 stash was not applied or popped.

## Next action

Review `human_review_priority.csv`, then decide whether the diagnostic output
is enough to design a smaller, pre-entry-only human review surface. Do not
start Phase 4 until the direction/entry-reference limitations are resolved or
accepted as part of a new pre-registered plan.
