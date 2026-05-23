# Strategy 2 Layer B Reaction Quality Diagnostics

## Context

Layer A taxonomy is now clean. Only `VALID_LONG` and `VALID_SHORT` states enter the Layer B funnel. Reaction-quality descriptors are measurable only when a real decision/re-entry timestamp exists. Behavioral Layer B remains unvalidated.

## Method

- Compute reaction candidate descriptors only.
- Do not produce TAKE/SKIP decisions.
- Do not use outcome columns.
- Do not compute performance metrics.
- Do not optimize thresholds.

## Eligibility

- samples loaded: `1089`
- original VALID_LONG: `99`
- original VALID_SHORT: `87`
- original Layer A valid count: `186`
- measurable Layer B count: `135`
- REENTRY_NOT_REACHED count: `51`
- MISSING_DECISION_TIME_BUG count: `0`
- true NOT_ENOUGH_DATA count: `0`
- original NOT_ENOUGH_DATA before reclassification: `51`
- excluded count: `903`
- MAE_NOT_REACHED reported separately: `93`

Excluded states:

- `INVALIDATED_LONG`: `272`
- `INVALIDATED_SHORT`: `288`
- `H1_CONTEXT_ALREADY_CONSUMED`: `248`
- `MAE_NOT_REACHED`: `93`
- `TRUE_DUAL_DIRECTION_INVALIDATED`: `2`

## Funnel / Attrition

`REENTRY_NOT_REACHED` rows remain in the export but are outside the measurable reaction-quality denominator.

## Feature Distributions

| Type | Value | Count | Rate |
|---|---|---:|---:|
| reaction_descriptor_all_layer_a_valid | CHOP_AFTER_SWEEP_CANDIDATE | 79 | 0.4247 |
| reaction_descriptor_all_layer_a_valid | FAST_REENTRY | 56 | 0.3011 |
| reaction_descriptor_all_layer_a_valid | NO_ENTRY_REENTRY_NOT_REACHED | 51 | 0.2742 |
| layer_b_candidate_label_all_layer_a_valid | CHOPPY_REACTION_CANDIDATE | 79 | 0.4247 |
| layer_b_candidate_label_all_layer_a_valid | STRONG_REACTION_CANDIDATE | 56 | 0.3011 |
| layer_b_candidate_label_all_layer_a_valid | UNKNOWN_REACTION_CANDIDATE | 51 | 0.2742 |
| reaction_descriptor_measurable | CHOP_AFTER_SWEEP_CANDIDATE | 79 | 0.5852 |
| reaction_descriptor_measurable | FAST_REENTRY | 56 | 0.4148 |
| layer_b_candidate_label_measurable | CHOPPY_REACTION_CANDIDATE | 79 | 0.5852 |
| layer_b_candidate_label_measurable | STRONG_REACTION_CANDIDATE | 56 | 0.4148 |

## Null / Missing Data

| Feature | Null Or Unknown | Rate |
|---|---:|---:|
| sweep_timestamp | 0 | 0.0 |
| decision_time | 0 | 0.0 |
| range_reentry_detected | 0 | 0.0 |
| time_to_reentry_seconds | 0 | 0.0 |
| reentry_distance_usd | 0 | 0.0 |
| rejection_wick_ratio | 0 | 0.0 |
| body_displacement_usd | 0 | 0.0 |
| post_sweep_compression_seconds | 0 | 0.0 |
| micro_range_size_usd | 0 | 0.0 |
| clean_vs_dirty_path_candidate | 2 | 0.0148 |

## Leakage Audit

| Feature | Uses Future Data | Diagnostic Only | Allowed For Candidate Label |
|---|---|---|---|
| range_reentry_detected | False | False | True |
| time_to_reentry_seconds | False | False | True |
| reentry_distance_usd | False | False | True |
| rejection_wick_ratio | False | False | True |
| body_displacement_usd | False | False | True |
| post_sweep_compression_seconds | False | False | True |
| micro_range_size_usd | False | False | True |
| clean_vs_dirty_path_candidate | False | False | True |
| acceleration_after_reentry_usd | True | True | False |

Future-looking acceleration is exported only as diagnostic-only metadata and is not used in the candidate label.

## Critical Limitations

- Descriptors are not validated.
- No manual labels are used yet.
- No edge claim.
- No deployment decision.
- Human validation is required.

## Verdict Flags

- `LAYER_B_REACTION_DIAGNOSTICS_CREATED`
- `VALID_STATES_ONLY`
- `NO_TAKE_SKIP_DECISION`
- `NO_PERFORMANCE_CLAIM`
- `NO_OUTCOME_USAGE`
- `FUTURE_DATA_AUDITED`
- `MANUAL_VALIDATION_REQUIRED`
- `STRATEGY_2_REMAINS_RESEARCH_ONLY`
- `NO_DEPLOYMENT_DECISION`

## Next Strategy 2-Only Step

`feat/strategy-2-layer-b-manual-validation-pack`
