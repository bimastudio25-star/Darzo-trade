# Adelin v2 Objective Outcome Replay

Status: diagnostic baseline comparison only. Candidate windows are not signals and this is not validation.

- symbol: `XAUUSD`
- pip_size: `0.1` from `core.symbols.get_symbol_spec`
- forward_hours: `4.0`

Forward windows above 4h may overstate runner quality on XAUUSD.

CI95 robustness metadata annotates noise and directionality only. It does not change the locked pre-registered verdict.

Entry-source/session-matched controls improve baseline quality but are still descriptive and not validation.
Candidate sample size remains small; do not interpret as statistically significant. Report effect sizes only.

## Pre-Registered Verdict

- criteria loaded: `True`
- criteria source: `backtests\reports\adelin_v2_expanded_candidate_window_pack\decision_criteria.md`
- verdict: `INCONCLUSIVE`
- verdict reason: `NO_PRE_REGISTERED_RULE_FIRED`
- decision source: `None`
- decision metric: `None`
- decision effect size: `None`
- decision effect CI95: `None` to `None`
- triggering effect CI95 excludes zero: `None`
- robustness note: INCONCLUSIVE by locked criteria; pause Adelin v2 and do not iterate ad hoc.
- recommended next action: Pause Adelin v2; do not keep iterating without a new pre-registered plan.

The decision criteria were loaded from the expanded pack and are not changed by this replay branch.

## Counts

- candidate samples loaded: `300`
- candidate samples replayed: `300`
- control samples generated: `557`
- rows written: `857`
- candidate known-entry rows: `222`
- control known-entry rows: `557`
- candidate unknown entry-level rate: `0.26`

Known-entry subset is still descriptive and not validation.

## Entry Level Source Counts

### Candidate

- `ROUND_LEVEL`: `129`
- `SWEEP_EXTREME`: `71`
- `SWEPT_LIQUIDITY_LEVEL`: `22`
- `UNKNOWN`: `78`

### Control

- `ROUND_LEVEL`: `291`
- `SWEEP_EXTREME`: `266`

## Session Distribution

### Candidate

- `ASIA`: `71`
- `ASIA_OPEN`: `27`
- `LONDON`: `73`
- `LONDON_OPEN`: `8`
- `NEW_YORK`: `49`
- `NEW_YORK_OPEN`: `14`
- `OTHER`: `58`

### Control

- `ASIA`: `91`
- `ASIA_OPEN`: `1`
- `LONDON`: `182`
- `LONDON_OPEN`: `6`
- `NEW_YORK`: `91`
- `NEW_YORK_OPEN`: `20`
- `OTHER`: `166`

## Volatility Bucket Distribution

### Candidate

- `HIGH`: `86`
- `LOW`: `69`
- `MID`: `145`

### Control

- `UNKNOWN`: `557`

## Control Generation

- unmatched session controls allowed: `False`
- session match success rate: `0.0366`

### Attempts By Source And Session

- `ROUND_LEVEL|ASIA`: attempts `1800`, success `39`
- `ROUND_LEVEL|ASIA_OPEN`: attempts `100`, success `0`
- `ROUND_LEVEL|LONDON`: attempts `4300`, success `94`
- `ROUND_LEVEL|LONDON_OPEN`: attempts `300`, success `0`
- `ROUND_LEVEL|NEW_YORK`: attempts `2300`, success `43`
- `ROUND_LEVEL|NEW_YORK_OPEN`: attempts `400`, success `1`
- `ROUND_LEVEL|OTHER`: attempts `3700`, success `114`
- `SWEEP_EXTREME|ASIA`: attempts `277`, success `52`
- `SWEEP_EXTREME|ASIA_OPEN`: attempts `200`, success `1`
- `SWEEP_EXTREME|LONDON`: attempts `401`, success `88`
- `SWEEP_EXTREME|LONDON_OPEN`: attempts `300`, success `6`
- `SWEEP_EXTREME|NEW_YORK`: attempts `288`, success `48`
- `SWEEP_EXTREME|NEW_YORK_OPEN`: attempts `600`, success `19`
- `SWEEP_EXTREME|OTHER`: attempts `264`, success `52`

### Skip Reasons

- `SESSION_MISMATCH`: `11997`
- `ROUND_LEVEL_NOT_NEAR_PRE_ANCHOR_PRICE`: `2603`
- `CONTROL_ANCHOR_OVERLAPS_CANDIDATE_OR_DUPLICATE`: `47`
- `MISSING_EXECUTION_COVERAGE`: `23`
- `ROUND_LEVEL_PRE_ANCHOR_PRICE_MISSING`: `2`
- `SWEEP_EXTREME_NOT_DETECTED_PRE_ANCHOR`: `1`

## Candidate Outcome Counts

- `FAST_SL_20`: `112`
- `GOOD_FAST_REACTION`: `47`
- `GOOD_REACTION_BUT_DIRTY_ACCUMULATION`: `9`
- `GOOD_SLOW_REACTION`: `27`
- `MFE_GOOD_BUT_BE_REQUIRED`: `1`
- `NO_REACTION`: `1`
- `UNKNOWN_DIRECTION`: `25`
- `UNKNOWN_ENTRY_LEVEL`: `78`

## Control Outcome Counts

- `FAST_SL_20`: `269`
- `GOOD_FAST_REACTION`: `171`
- `GOOD_REACTION_BUT_DIRTY_ACCUMULATION`: `42`
- `GOOD_SLOW_REACTION`: `63`
- `MFE_GOOD_BUT_BE_REQUIRED`: `11`
- `NO_REACTION`: `1`

## Candidate Vs Control

- `candidate_fast_reaction_rate`: `0.1767`
- `control_fast_reaction_rate`: `0.3609`
- `candidate_fast_sl_20_rate`: `0.3733`
- `control_fast_sl_20_rate`: `0.4829`
- `candidate_runner_candidate_rate`: `0.0`
- `control_runner_candidate_rate`: `0.0`
- `candidate_unknown_rate`: `0.3433`
- `control_unknown_rate`: `0.0`

## Candidate Vs Control Known Entry

- `candidate_fast_reaction_rate`: `0.2387`
- `control_fast_reaction_rate`: `0.3609`
- `candidate_fast_sl_20_rate`: `0.5045`
- `control_fast_sl_20_rate`: `0.4829`
- `candidate_runner_candidate_rate`: `0.0`
- `control_runner_candidate_rate`: `0.0`
- `candidate_unknown_rate`: `0.1126`
- `control_unknown_rate`: `0.0`

## Entry Source Matched Metrics

- `ROUND_LEVEL`: {"candidate_count": 129, "candidate_fast_reaction_rate": 0.1395, "candidate_fast_sl_20_rate": 0.7054, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0233, "control_count": 291, "control_fast_reaction_rate": 0.2165, "control_fast_sl_20_rate": 0.7251, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": -0.077, "descriptive_effect_size_fast_sl20": -0.0197, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION"]}
- `SWEEP_EXTREME`: {"candidate_count": 71, "candidate_fast_reaction_rate": 0.493, "candidate_fast_sl_20_rate": 0.2958, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 266, "control_fast_reaction_rate": 0.5188, "control_fast_sl_20_rate": 0.218, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": -0.0258, "descriptive_effect_size_fast_sl20": 0.0778, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION"]}
- `SWEPT_LIQUIDITY_LEVEL`: {"candidate_count": 22, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "NO_MATCHED_CONTROLS"]}
- `UNKNOWN`: {"candidate_count": 78, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "NO_MATCHED_CONTROLS"]}

## Source Metrics With CI95

- `ROUND_LEVEL`: {"candidate_fast_reaction_ci95_lower": 0.079739, "candidate_fast_reaction_ci95_upper": 0.19933, "candidate_fast_reaction_rate": 0.139535, "candidate_fast_reaction_successes": 18, "candidate_fast_sl20_ci95_lower": 0.626761, "candidate_fast_sl20_ci95_upper": 0.784092, "candidate_fast_sl20_rate": 0.705426, "candidate_fast_sl20_successes": 91, "candidate_n": 129, "candidate_runner_ci95_lower": 0.125587, "candidate_runner_ci95_upper": 0.26201, "candidate_runner_rate": 0.193798, "candidate_runner_successes": 25, "control_fast_reaction_ci95_lower": 0.169174, "control_fast_reaction_ci95_upper": 0.263816, "control_fast_reaction_rate": 0.216495, "control_fast_reaction_successes": 63, "control_fast_sl20_ci95_lower": 0.673788, "control_fast_sl20_ci95_upper": 0.776384, "control_fast_sl20_rate": 0.725086, "control_fast_sl20_successes": 211, "control_n": 291, "control_runner_ci95_lower": 0.110041, "control_runner_ci95_upper": 0.192364, "control_runner_rate": 0.151203, "control_runner_successes": 44, "eligible_for_pre_registered_verdict": true, "fast_reaction_effect_size": -0.07696, "fast_reaction_effect_size_ci95_lower": -0.153215, "fast_reaction_effect_size_ci95_upper": -0.000705, "fast_reaction_effect_size_excludes_zero": true, "fast_reaction_robustness_label": "DIRECTIONAL_AND_CI95_EXCLUDES_ZERO", "fast_sl20_effect_size": -0.01966, "fast_sl20_effect_size_ci95_lower": -0.113574, "fast_sl20_effect_size_ci95_upper": 0.074254, "fast_sl20_effect_size_excludes_zero": false, "fast_sl20_robustness_label": "DIRECTIONAL_NOT_STATISTICALLY_ROBUST_AT_CURRENT_N", "required_candidate_min_n": 50, "runner_effect_size": 0.042595, "runner_effect_size_ci95_lower": -0.037074, "runner_effect_size_ci95_upper": 0.122264, "runner_effect_size_excludes_zero": false, "runner_robustness_label": "DIRECTIONAL_NOT_STATISTICALLY_ROBUST_AT_CURRENT_N"}
- `SWEEP_EXTREME`: {"candidate_fast_reaction_ci95_lower": 0.376665, "candidate_fast_reaction_ci95_upper": 0.609251, "candidate_fast_reaction_rate": 0.492958, "candidate_fast_reaction_successes": 35, "candidate_fast_sl20_ci95_lower": 0.189614, "candidate_fast_sl20_ci95_upper": 0.401935, "candidate_fast_sl20_rate": 0.295775, "candidate_fast_sl20_successes": 21, "candidate_n": 71, "candidate_runner_ci95_lower": 0.128165, "candidate_runner_ci95_upper": 0.322539, "candidate_runner_rate": 0.225352, "candidate_runner_successes": 16, "control_fast_reaction_ci95_lower": 0.458752, "control_fast_reaction_ci95_upper": 0.578842, "control_fast_reaction_rate": 0.518797, "control_fast_reaction_successes": 138, "control_fast_sl20_ci95_lower": 0.168423, "control_fast_sl20_ci95_upper": 0.267668, "control_fast_sl20_rate": 0.218045, "control_fast_sl20_successes": 58, "control_n": 266, "control_runner_ci95_lower": 0.124119, "control_runner_ci95_upper": 0.214227, "control_runner_rate": 0.169173, "control_runner_successes": 45, "eligible_for_pre_registered_verdict": false, "fast_reaction_effect_size": -0.025839, "fast_reaction_effect_size_ci95_lower": -0.156719, "fast_reaction_effect_size_ci95_upper": 0.105041, "fast_reaction_effect_size_excludes_zero": false, "fast_reaction_robustness_label": "INELIGIBLE_UNDERPOWERED_SOURCE", "fast_sl20_effect_size": 0.07773, "fast_sl20_effect_size_ci95_lower": -0.039456, "fast_sl20_effect_size_ci95_upper": 0.194916, "fast_sl20_effect_size_excludes_zero": false, "fast_sl20_robustness_label": "INELIGIBLE_UNDERPOWERED_SOURCE", "required_candidate_min_n": 80, "runner_effect_size": 0.056179, "runner_effect_size_ci95_lower": -0.050944, "runner_effect_size_ci95_upper": 0.163302, "runner_effect_size_excludes_zero": false, "runner_robustness_label": "INELIGIBLE_UNDERPOWERED_SOURCE"}
- `SWEPT_LIQUIDITY_LEVEL`: {"candidate_fast_reaction_ci95_lower": 0.0, "candidate_fast_reaction_ci95_upper": 0.0, "candidate_fast_reaction_rate": 0.0, "candidate_fast_reaction_successes": 0, "candidate_fast_sl20_ci95_lower": 0.0, "candidate_fast_sl20_ci95_upper": 0.0, "candidate_fast_sl20_rate": 0.0, "candidate_fast_sl20_successes": 0, "candidate_n": 22, "candidate_runner_ci95_lower": 0.0, "candidate_runner_ci95_upper": 0.0, "candidate_runner_rate": 0.0, "candidate_runner_successes": 0, "control_fast_reaction_ci95_lower": 0.0, "control_fast_reaction_ci95_upper": 0.0, "control_fast_reaction_rate": 0.0, "control_fast_reaction_successes": 0, "control_fast_sl20_ci95_lower": 0.0, "control_fast_sl20_ci95_upper": 0.0, "control_fast_sl20_rate": 0.0, "control_fast_sl20_successes": 0, "control_n": 0, "control_runner_ci95_lower": 0.0, "control_runner_ci95_upper": 0.0, "control_runner_rate": 0.0, "control_runner_successes": 0, "eligible_for_pre_registered_verdict": false, "fast_reaction_effect_size": 0.0, "fast_reaction_effect_size_ci95_lower": 0.0, "fast_reaction_effect_size_ci95_upper": 0.0, "fast_reaction_effect_size_excludes_zero": false, "fast_reaction_robustness_label": "INELIGIBLE_UNDERPOWERED_SOURCE", "fast_sl20_effect_size": 0.0, "fast_sl20_effect_size_ci95_lower": 0.0, "fast_sl20_effect_size_ci95_upper": 0.0, "fast_sl20_effect_size_excludes_zero": false, "fast_sl20_robustness_label": "INELIGIBLE_UNDERPOWERED_SOURCE", "required_candidate_min_n": 50, "runner_effect_size": 0.0, "runner_effect_size_ci95_lower": 0.0, "runner_effect_size_ci95_upper": 0.0, "runner_effect_size_excludes_zero": false, "runner_robustness_label": "INELIGIBLE_UNDERPOWERED_SOURCE"}
- `UNKNOWN`: {"candidate_n": 78, "control_n": 0, "eligible_for_pre_registered_verdict": false, "limitation": "UNKNOWN_ENTRY_SOURCE_EXCLUDED_FROM_PRE_REGISTERED_VERDICT", "required_candidate_min_n": null}

## Entry Source And Session Matched Metrics

- `ROUND_LEVEL|ASIA`: {"candidate_count": 18, "candidate_fast_reaction_rate": 0.1111, "candidate_fast_sl_20_rate": 0.7222, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.1111, "control_count": 39, "control_fast_reaction_rate": 0.1538, "control_fast_sl_20_rate": 0.7436, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": -0.0427, "descriptive_effect_size_fast_sl20": -0.0214, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `ROUND_LEVEL|ASIA_OPEN`: {"candidate_count": 1, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `ROUND_LEVEL|LONDON`: {"candidate_count": 43, "candidate_fast_reaction_rate": 0.0698, "candidate_fast_sl_20_rate": 0.7442, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 94, "control_fast_reaction_rate": 0.1809, "control_fast_sl_20_rate": 0.6277, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": -0.1111, "descriptive_effect_size_fast_sl20": 0.1165, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION"]}
- `ROUND_LEVEL|LONDON_OPEN`: {"candidate_count": 3, "candidate_fast_reaction_rate": 0.3333, "candidate_fast_sl_20_rate": 0.6667, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.3333, "descriptive_effect_size_fast_sl20": 0.6667, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `ROUND_LEVEL|NEW_YORK`: {"candidate_count": 23, "candidate_fast_reaction_rate": 0.0435, "candidate_fast_sl_20_rate": 0.6957, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 43, "control_fast_reaction_rate": 0.2326, "control_fast_sl_20_rate": 0.6977, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": -0.1891, "descriptive_effect_size_fast_sl20": -0.002, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION"]}
- `ROUND_LEVEL|NEW_YORK_OPEN`: {"candidate_count": 4, "candidate_fast_reaction_rate": 0.25, "candidate_fast_sl_20_rate": 0.75, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 1, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 1.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.25, "descriptive_effect_size_fast_sl20": -0.25, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `ROUND_LEVEL|OTHER`: {"candidate_count": 37, "candidate_fast_reaction_rate": 0.2703, "candidate_fast_sl_20_rate": 0.6757, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 114, "control_fast_reaction_rate": 0.2632, "control_fast_sl_20_rate": 0.807, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0071, "descriptive_effect_size_fast_sl20": -0.1313, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION"]}
- `SWEEP_EXTREME|ASIA`: {"candidate_count": 13, "candidate_fast_reaction_rate": 0.3077, "candidate_fast_sl_20_rate": 0.3846, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 52, "control_fast_reaction_rate": 0.3654, "control_fast_sl_20_rate": 0.2692, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": -0.0577, "descriptive_effect_size_fast_sl20": 0.1154, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `SWEEP_EXTREME|ASIA_OPEN`: {"candidate_count": 2, "candidate_fast_reaction_rate": 0.5, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 1, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 1.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.5, "descriptive_effect_size_fast_sl20": -1.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `SWEEP_EXTREME|LONDON`: {"candidate_count": 22, "candidate_fast_reaction_rate": 0.4545, "candidate_fast_sl_20_rate": 0.3182, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 88, "control_fast_reaction_rate": 0.5, "control_fast_sl_20_rate": 0.2159, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": -0.0455, "descriptive_effect_size_fast_sl20": 0.1023, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION"]}
- `SWEEP_EXTREME|LONDON_OPEN`: {"candidate_count": 3, "candidate_fast_reaction_rate": 0.3333, "candidate_fast_sl_20_rate": 0.6667, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 6, "control_fast_reaction_rate": 0.5, "control_fast_sl_20_rate": 0.1667, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": -0.1667, "descriptive_effect_size_fast_sl20": 0.5, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `SWEEP_EXTREME|NEW_YORK`: {"candidate_count": 12, "candidate_fast_reaction_rate": 0.3333, "candidate_fast_sl_20_rate": 0.3333, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 48, "control_fast_reaction_rate": 0.625, "control_fast_sl_20_rate": 0.2083, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": -0.2917, "descriptive_effect_size_fast_sl20": 0.125, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `SWEEP_EXTREME|NEW_YORK_OPEN`: {"candidate_count": 6, "candidate_fast_reaction_rate": 0.8333, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 19, "control_fast_reaction_rate": 0.4211, "control_fast_sl_20_rate": 0.3684, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.4122, "descriptive_effect_size_fast_sl20": -0.3684, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `SWEEP_EXTREME|OTHER`: {"candidate_count": 13, "candidate_fast_reaction_rate": 0.7692, "candidate_fast_sl_20_rate": 0.2308, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 52, "control_fast_reaction_rate": 0.6538, "control_fast_sl_20_rate": 0.1154, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.1154, "descriptive_effect_size_fast_sl20": 0.1154, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `SWEPT_LIQUIDITY_LEVEL|ASIA`: {"candidate_count": 11, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `SWEPT_LIQUIDITY_LEVEL|ASIA_OPEN`: {"candidate_count": 11, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `UNKNOWN|ASIA`: {"candidate_count": 29, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "NO_MATCHED_CONTROLS"]}
- `UNKNOWN|ASIA_OPEN`: {"candidate_count": 13, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `UNKNOWN|LONDON`: {"candidate_count": 8, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `UNKNOWN|LONDON_OPEN`: {"candidate_count": 2, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `UNKNOWN|NEW_YORK`: {"candidate_count": 14, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `UNKNOWN|NEW_YORK_OPEN`: {"candidate_count": 4, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `UNKNOWN|OTHER`: {"candidate_count": 8, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}

## Candidate Outcome Counts By Entry Source

- `ROUND_LEVEL`: {"FAST_SL_20": 91, "GOOD_FAST_REACTION": 13, "GOOD_REACTION_BUT_DIRTY_ACCUMULATION": 6, "GOOD_SLOW_REACTION": 15, "NO_REACTION": 1, "UNKNOWN_DIRECTION": 3}
- `SWEEP_EXTREME`: {"FAST_SL_20": 21, "GOOD_FAST_REACTION": 34, "GOOD_REACTION_BUT_DIRTY_ACCUMULATION": 3, "GOOD_SLOW_REACTION": 12, "MFE_GOOD_BUT_BE_REQUIRED": 1}
- `SWEPT_LIQUIDITY_LEVEL`: {"UNKNOWN_DIRECTION": 22}
- `UNKNOWN`: {"UNKNOWN_ENTRY_LEVEL": 78}

## Control Outcome Counts By Entry Source

- `ROUND_LEVEL`: {"FAST_SL_20": 211, "GOOD_FAST_REACTION": 35, "GOOD_REACTION_BUT_DIRTY_ACCUMULATION": 16, "GOOD_SLOW_REACTION": 25, "MFE_GOOD_BUT_BE_REQUIRED": 4}
- `SWEEP_EXTREME`: {"FAST_SL_20": 58, "GOOD_FAST_REACTION": 136, "GOOD_REACTION_BUT_DIRTY_ACCUMULATION": 26, "GOOD_SLOW_REACTION": 38, "MFE_GOOD_BUT_BE_REQUIRED": 7, "NO_REACTION": 1}

## Limitations

- `CANDIDATE_UNKNOWN_DIRECTION_ROWS_25`
- `CANDIDATE_UNKNOWN_ENTRY_LEVEL_ROWS_78`
- `CONTROL_GROUP_NOT_FILLED`
- `CONTROL_GROUP_NOT_FILLED_ROUND_LEVEL_ASIA_39_OF_72`
- `CONTROL_GROUP_NOT_FILLED_ROUND_LEVEL_ASIA_OPEN_0_OF_4`
- `CONTROL_GROUP_NOT_FILLED_ROUND_LEVEL_LONDON_94_OF_172`
- `CONTROL_GROUP_NOT_FILLED_ROUND_LEVEL_LONDON_OPEN_0_OF_12`
- `CONTROL_GROUP_NOT_FILLED_ROUND_LEVEL_NEW_YORK_43_OF_92`
- `CONTROL_GROUP_NOT_FILLED_ROUND_LEVEL_NEW_YORK_OPEN_1_OF_16`
- `CONTROL_GROUP_NOT_FILLED_ROUND_LEVEL_OTHER_114_OF_148`
- `CONTROL_GROUP_NOT_FILLED_SWEEP_EXTREME_ASIA_OPEN_1_OF_8`
- `CONTROL_GROUP_NOT_FILLED_SWEEP_EXTREME_LONDON_OPEN_6_OF_12`
- `CONTROL_GROUP_NOT_FILLED_SWEEP_EXTREME_NEW_YORK_OPEN_19_OF_24`
- `CONTROL_SOURCE_UNSUPPORTED_SWEPT_LIQUIDITY_LEVEL_CANDIDATES_22`
- `VISUAL_PACK_DATE_RANGE_BELOW_REQUESTED_MINIMUM`
- `VISUAL_PACK_INSUFFICIENT_EXECUTION_DATA_SAMPLES_SKIPPED`
- `VISUAL_PACK_LOCAL_DATA_COVERAGE_BELOW_REQUESTED_MIN_DATE_RANGE`
- `VISUAL_PACK_MATPLOTLIB_UNAVAILABLE_USING_SVG_CHARTS`
- `VISUAL_PACK_NO_TRADES_PATH_AVAILABLE`
