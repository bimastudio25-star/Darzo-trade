# Adelin v2 Phase 3 Visual Review Labels

Status: Phase 3 labeling infrastructure. This branch creates schema,
template, validation, and documentation only.

## Context

- Phase 0 old Adelin archived as non-deployable.
- Phase 1 contextual measurability audit complete.
- Phase 2 pre-registered feature test plan complete.
- Phase 2b fixed the 004/005 numeric-level overlap.
- Human signoff approved Phase 2.
- Phase 3 visual labels are now allowed.

Phase 3 asks whether each primary feature is visually recognizable before
entry / before the decision point. It does not ask whether the setup worked.

## Purpose

Phase 3 checks whether the 9 primary pre-registered features are visually
observable before entry:

- `ADELINV2_CTX_001` - h1_sweep_reaction_context
- `ADELINV2_CTX_002` - m5_m15_fvg_reaction_zone_context
- `ADELINV2_CTX_003` - m5_m15_ifvg_retest_context
- `004` - NUMERIC_LEVEL_CONFLUENCE
- `ADELINV2_CTX_006` - pre_anchor_rejection_candle_morphology
- `ADELINV2_CTX_007` - pre_anchor_displacement_context
- `ADELINV2_CTX_008` - time_of_day_bucket_context
- `ADELINV2_CTX_009` - session_bucket_context
- `ADELINV2_CTX_010` - pre_anchor_volatility_bucket_context

The output is a manual label dataset for later gated review. It is not a
performance dataset.

## Non-purpose

This is NOT:

- a backtest;
- objective replay;
- matched-control replay;
- performance validation;
- strategy scoring;
- feature optimization;
- candidate generation;
- deployment evidence;
- live trading preparation.

## Inputs

Feature specs:

- `backtests/reports/adelin_v2_pre_registered_context_feature_test_plan/feature_test_specs.csv`
- `backtests/reports/adelin_v2_pre_registered_context_feature_test_plan/feature_test_specs.json`
- `backtests/reports/adelin_v2_pre_registered_context_feature_test_plan/summary.json`

Human signoff:

- `docs/research/adelin_v2_feature_test_human_signoff_template.md`

Existing visual review source:

- `backtests/reports/adelin_v2_visual_review_pack/index.html`
- `backtests/reports/adelin_v2_visual_review_pack/manual_labels_template.csv`

The existing visual pack was found and 40 sample rows were linked into the
Phase 3 template. No new candidate pack was generated.

## Outputs

- `backtests/reports/adelin_v2_phase_3_visual_review_labels/phase_3_label_schema.json`
- `backtests/reports/adelin_v2_phase_3_visual_review_labels/manual_labels_template.csv`
- `backtests/reports/adelin_v2_phase_3_visual_review_labels/manual_labels_validation_summary.json`
- `backtests/reports/adelin_v2_phase_3_visual_review_labels/phase_3_summary.json`
- `scripts/validate_adelin_v2_phase_3_labels.py`

## Label schema

Global identity fields include sample ID, symbol, decision timestamp, chart
path, sample page path, execution coverage status, and reviewer metadata.

Global review fields:

- `overall_reviewable`: `YES`, `NO`, `UNCLEAR`
- `pre_entry_only_confirmed`: `YES`, `NO`
- `leakage_risk_detected`: `YES`, `NO`, `UNCLEAR`
- `exclude_from_phase_4`: `YES`, `NO`
- `exclude_reason`: free text
- `reviewer_notes`: free text

For each primary feature, the template includes:

- `feature_<test_id>_<feature_name>_visible_pre_entry`
- `feature_<test_id>_<feature_name>_label`
- `feature_<test_id>_<feature_name>_confidence`
- `feature_<test_id>_<feature_name>_notes`

Allowed values:

- `visible_pre_entry`: `YES`, `NO`, `UNCLEAR`, `NOT_VISIBLE`
- `label`: `PRESENT`, `ABSENT`, `UNCLEAR`, `NOT_APPLICABLE`
- `confidence`: `0`, `1`, `2`, `3`
- `notes`: free text

Confidence scale:

- `0`: no confidence / cannot judge
- `1`: low confidence
- `2`: medium confidence
- `3`: high confidence

No predictive score, trade outcome, PnL, R-multiple, TP/SL result, MFE/MAE, or
future-return field is allowed in the label schema.

## Leakage rules

The reviewer must label only what is visible before entry / before decision.

Forbidden information during labeling:

- final result;
- TP hit;
- SL hit;
- pnl;
- R multiple;
- future bars after entry;
- whether setup later worked;
- replay outcome;
- matched-control result;
- future MFE/MAE;
- future liquidity behavior after decision.

The existing visual review pack may show future candles. This creates leakage
risk. The reviewer may set `pre_entry_only_confirmed = YES` only if they
consciously ignore future information and label exclusively from pre-entry /
pre-decision context.

If the reviewer cannot ignore visible future information, set:

- `pre_entry_only_confirmed = NO`
- `leakage_risk_detected = YES`
- `exclude_from_phase_4 = YES`

The preferred future review surface is a pre-entry-only visual pack, but this
branch does not generate one.

## Spec 004/005 handling

Spec 004 is the only primary numeric-level hypothesis:

- test_id: `004`
- feature_name: `NUMERIC_LEVEL_CONFLUENCE`
- role: `PRIMARY_TEST`
- grid: XAUUSD price levels divisible by `10.00 USD`
- threshold: `<=20 pips = 2.0 USD`

Spec 005 is stratification metadata only:

- test_id: `005`
- feature_name: `tight_numeric_level_touch_band`
- role: `STRATIFICATION_METADATA_ONLY`
- bands: `0-10_PIPS`, `10-20_PIPS`, `GT_20_PIPS`
- removed from primary tests

Spec 005 must not be used as a standalone predictive feature or independent
edge hypothesis.

## Human workflow

1. Open `backtests/reports/adelin_v2_visual_review_pack/index.html` if
   available.
2. Fill:
   `backtests/reports/adelin_v2_phase_3_visual_review_labels/manual_labels_template.csv`
3. Label only pre-entry visible information.
4. Save the completed file as:
   `backtests/reports/adelin_v2_phase_3_visual_review_labels/manual_labels_filled.csv`
5. Run validation:

```bash
python scripts/validate_adelin_v2_phase_3_labels.py --labels-path backtests/reports/adelin_v2_phase_3_visual_review_labels/manual_labels_filled.csv --schema-path backtests/reports/adelin_v2_phase_3_visual_review_labels/phase_3_label_schema.json --output-path backtests/reports/adelin_v2_phase_3_visual_review_labels/manual_labels_validation_summary.json
```

For the blank template only:

```bash
python scripts/validate_adelin_v2_phase_3_labels.py --labels-path backtests/reports/adelin_v2_phase_3_visual_review_labels/manual_labels_template.csv --schema-path backtests/reports/adelin_v2_phase_3_visual_review_labels/phase_3_label_schema.json --output-path backtests/reports/adelin_v2_phase_3_visual_review_labels/manual_labels_validation_summary.json --allow-empty
```

Commit filled labels only after validation passes.

## Gate after Phase 3

Only after complete and validated human labels exist may Phase 4
matched-control replay be considered.

No replay is run in this branch.

## Safety

No OHLC data was read.

No backtest was run.

No candidate pack was generated.

No matched-control replay was run.

No detector was executed.

No runtime logic was modified.

Strategy 2 was untouched.

Strategy 3 was untouched.

`data/XAUUSD/*.csv` was untouched.

No live trading was enabled.

No orders were created or sent.

No Telegram trade alerts were sent.

No broker execution was called.

The v3 stash was not applied or popped.
