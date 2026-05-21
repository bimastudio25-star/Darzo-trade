# Adelin v2 Objective Outcome Replay

Status: diagnostic baseline comparison only. Candidate windows are not signals and this is not validation.

- symbol: `XAUUSD`
- pip_size: `0.1` from `core.symbols.get_symbol_spec`
- forward_hours: `4.0`

Forward windows above 4h may overstate runner quality on XAUUSD.

Entry-source/session-matched controls improve baseline quality but are still descriptive and not validation.
Candidate sample size remains small; do not interpret as statistically significant. Report effect sizes only.

## Counts

- candidate samples loaded: `40`
- candidate samples replayed: `40`
- control samples generated: `486`
- rows written: `526`
- candidate known-entry rows: `35`
- control known-entry rows: `486`
- candidate unknown entry-level rate: `0.125`

Known-entry subset is still descriptive and not validation.

## Entry Level Source Counts

### Candidate

- `ROUND_LEVEL`: `7`
- `SWEEP_EXTREME`: `24`
- `SWEPT_LIQUIDITY_LEVEL`: `4`
- `UNKNOWN`: `5`

### Control

- `ROUND_LEVEL`: `69`
- `SWEEP_EXTREME`: `417`

## Session Distribution

### Candidate

- `ASIA`: `6`
- `ASIA_OPEN`: `5`
- `LONDON`: `5`
- `LONDON_OPEN`: `6`
- `NEW_YORK`: `5`
- `NEW_YORK_OPEN`: `5`
- `OTHER`: `8`

### Control

- `ASIA`: `51`
- `ASIA_OPEN`: `8`
- `LONDON`: `51`
- `LONDON_OPEN`: `80`
- `NEW_YORK`: `94`
- `NEW_YORK_OPEN`: `73`
- `OTHER`: `129`

## Control Generation

- unmatched session controls allowed: `False`
- session match success rate: `0.033`

### Attempts By Source And Session

- `ROUND_LEVEL|ASIA_OPEN`: attempts `625`, success `0`
- `ROUND_LEVEL|LONDON_OPEN`: attempts `750`, success `0`
- `ROUND_LEVEL|NEW_YORK`: attempts `1925`, success `43`
- `ROUND_LEVEL|OTHER`: attempts `1275`, success `26`
- `SWEEP_EXTREME|ASIA`: attempts `271`, success `51`
- `SWEEP_EXTREME|ASIA_OPEN`: attempts `2575`, success `8`
- `SWEEP_EXTREME|LONDON`: attempts `245`, success `51`
- `SWEEP_EXTREME|LONDON_OPEN`: attempts `3225`, success `80`
- `SWEEP_EXTREME|NEW_YORK`: attempts `267`, success `51`
- `SWEEP_EXTREME|NEW_YORK_OPEN`: attempts `3225`, success `73`
- `SWEEP_EXTREME|OTHER`: attempts `324`, success `103`

### Skip Reasons

- `SESSION_MISMATCH`: `13486`
- `ROUND_LEVEL_NOT_NEAR_PRE_ANCHOR_PRICE`: `690`
- `CONTROL_ANCHOR_OVERLAPS_CANDIDATE_OR_DUPLICATE`: `41`
- `MISSING_EXECUTION_COVERAGE`: `2`
- `SWEEP_EXTREME_NOT_DETECTED_PRE_ANCHOR`: `2`

## Candidate Outcome Counts

- `FAST_SL_20`: `7`
- `GOOD_FAST_REACTION`: `13`
- `GOOD_REACTION_BUT_DIRTY_ACCUMULATION`: `4`
- `GOOD_SLOW_REACTION`: `9`
- `RUNNER_CANDIDATE`: `1`
- `UNKNOWN_ENTRY_LEVEL`: `5`
- `UNKNOWN_INSUFFICIENT_FORWARD_DATA`: `1`

## Control Outcome Counts

- `FAST_SL_20`: `149`
- `GOOD_FAST_REACTION`: `197`
- `GOOD_REACTION_BUT_DIRTY_ACCUMULATION`: `36`
- `GOOD_SLOW_REACTION`: `80`
- `MFE_GOOD_BUT_BE_REQUIRED`: `19`
- `NO_REACTION`: `2`
- `RUNNER_CANDIDATE`: `3`

## Candidate Vs Control

- `candidate_fast_reaction_rate`: `0.35`
- `control_fast_reaction_rate`: `0.43`
- `candidate_fast_sl_20_rate`: `0.175`
- `control_fast_sl_20_rate`: `0.3066`
- `candidate_runner_candidate_rate`: `0.025`
- `control_runner_candidate_rate`: `0.0062`
- `candidate_unknown_rate`: `0.15`
- `control_unknown_rate`: `0.0`

## Candidate Vs Control Known Entry

- `candidate_fast_reaction_rate`: `0.4`
- `control_fast_reaction_rate`: `0.43`
- `candidate_fast_sl_20_rate`: `0.2`
- `control_fast_sl_20_rate`: `0.3066`
- `candidate_runner_candidate_rate`: `0.0286`
- `control_runner_candidate_rate`: `0.0062`
- `candidate_unknown_rate`: `0.0286`
- `control_unknown_rate`: `0.0`

## Entry Source Matched Metrics

- `ROUND_LEVEL`: {"candidate_count": 7, "candidate_fast_reaction_rate": 0.1429, "candidate_fast_sl_20_rate": 0.5714, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 69, "control_fast_reaction_rate": 0.1304, "control_fast_sl_20_rate": 0.7681, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0125, "descriptive_effect_size_fast_sl20": -0.1967, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `SWEEP_EXTREME`: {"candidate_count": 24, "candidate_fast_reaction_rate": 0.4583, "candidate_fast_sl_20_rate": 0.0833, "candidate_runner_candidate_rate": 0.0417, "candidate_unknown_rate": 0.0417, "control_count": 417, "control_fast_reaction_rate": 0.4796, "control_fast_sl_20_rate": 0.2302, "control_runner_candidate_rate": 0.0072, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": -0.0213, "descriptive_effect_size_fast_sl20": -0.1469, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION"]}
- `SWEPT_LIQUIDITY_LEVEL`: {"candidate_count": 4, "candidate_fast_reaction_rate": 0.5, "candidate_fast_sl_20_rate": 0.25, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.5, "descriptive_effect_size_fast_sl20": 0.25, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `UNKNOWN`: {"candidate_count": 5, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}

## Entry Source And Session Matched Metrics

- `ROUND_LEVEL|ASIA_OPEN`: {"candidate_count": 1, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 1.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 1.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `ROUND_LEVEL|LONDON_OPEN`: {"candidate_count": 1, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `ROUND_LEVEL|NEW_YORK`: {"candidate_count": 3, "candidate_fast_reaction_rate": 0.3333, "candidate_fast_sl_20_rate": 0.6667, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 43, "control_fast_reaction_rate": 0.1628, "control_fast_sl_20_rate": 0.7209, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.1705, "descriptive_effect_size_fast_sl20": -0.0542, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `ROUND_LEVEL|OTHER`: {"candidate_count": 2, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.5, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 26, "control_fast_reaction_rate": 0.0769, "control_fast_sl_20_rate": 0.8462, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": -0.0769, "descriptive_effect_size_fast_sl20": -0.3462, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `SWEEP_EXTREME|ASIA`: {"candidate_count": 2, "candidate_fast_reaction_rate": 0.5, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 51, "control_fast_reaction_rate": 0.5098, "control_fast_sl_20_rate": 0.1569, "control_runner_candidate_rate": 0.0196, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": -0.0098, "descriptive_effect_size_fast_sl20": -0.1569, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `SWEEP_EXTREME|ASIA_OPEN`: {"candidate_count": 4, "candidate_fast_reaction_rate": 1.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 8, "control_fast_reaction_rate": 1.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `SWEEP_EXTREME|LONDON`: {"candidate_count": 2, "candidate_fast_reaction_rate": 0.5, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 51, "control_fast_reaction_rate": 0.4118, "control_fast_sl_20_rate": 0.2745, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0882, "descriptive_effect_size_fast_sl20": -0.2745, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `SWEEP_EXTREME|LONDON_OPEN`: {"candidate_count": 5, "candidate_fast_reaction_rate": 0.6, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 80, "control_fast_reaction_rate": 0.4, "control_fast_sl_20_rate": 0.25, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.2, "descriptive_effect_size_fast_sl20": -0.25, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `SWEEP_EXTREME|NEW_YORK`: {"candidate_count": 2, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 51, "control_fast_reaction_rate": 0.4706, "control_fast_sl_20_rate": 0.2157, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": -0.4706, "descriptive_effect_size_fast_sl20": -0.2157, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `SWEEP_EXTREME|NEW_YORK_OPEN`: {"candidate_count": 5, "candidate_fast_reaction_rate": 0.2, "candidate_fast_sl_20_rate": 0.2, "candidate_runner_candidate_rate": 0.2, "candidate_unknown_rate": 0.0, "control_count": 73, "control_fast_reaction_rate": 0.411, "control_fast_sl_20_rate": 0.2192, "control_runner_candidate_rate": 0.0274, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": -0.211, "descriptive_effect_size_fast_sl20": -0.0192, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `SWEEP_EXTREME|OTHER`: {"candidate_count": 4, "candidate_fast_reaction_rate": 0.25, "candidate_fast_sl_20_rate": 0.25, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.25, "control_count": 103, "control_fast_reaction_rate": 0.5728, "control_fast_sl_20_rate": 0.2621, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": -0.3228, "descriptive_effect_size_fast_sl20": -0.0121, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE"]}
- `SWEPT_LIQUIDITY_LEVEL|ASIA`: {"candidate_count": 3, "candidate_fast_reaction_rate": 0.6667, "candidate_fast_sl_20_rate": 0.3333, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.6667, "descriptive_effect_size_fast_sl20": 0.3333, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `SWEPT_LIQUIDITY_LEVEL|LONDON`: {"candidate_count": 1, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 0.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `UNKNOWN|ASIA`: {"candidate_count": 1, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `UNKNOWN|LONDON`: {"candidate_count": 2, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}
- `UNKNOWN|OTHER`: {"candidate_count": 2, "candidate_fast_reaction_rate": 0.0, "candidate_fast_sl_20_rate": 0.0, "candidate_runner_candidate_rate": 0.0, "candidate_unknown_rate": 1.0, "control_count": 0, "control_fast_reaction_rate": 0.0, "control_fast_sl_20_rate": 0.0, "control_runner_candidate_rate": 0.0, "control_unknown_rate": 0.0, "descriptive_effect_size_fast_reaction": 0.0, "descriptive_effect_size_fast_sl20": 0.0, "limitations": ["DESCRIPTIVE_ONLY_NOT_VALIDATION", "SMALL_CANDIDATE_SAMPLE", "NO_MATCHED_CONTROLS"]}

## Candidate Outcome Counts By Entry Source

- `ROUND_LEVEL`: {"FAST_SL_20": 4, "GOOD_FAST_REACTION": 1, "GOOD_SLOW_REACTION": 2}
- `SWEEP_EXTREME`: {"FAST_SL_20": 2, "GOOD_FAST_REACTION": 10, "GOOD_REACTION_BUT_DIRTY_ACCUMULATION": 3, "GOOD_SLOW_REACTION": 7, "RUNNER_CANDIDATE": 1, "UNKNOWN_INSUFFICIENT_FORWARD_DATA": 1}
- `SWEPT_LIQUIDITY_LEVEL`: {"FAST_SL_20": 1, "GOOD_FAST_REACTION": 2, "GOOD_REACTION_BUT_DIRTY_ACCUMULATION": 1}
- `UNKNOWN`: {"UNKNOWN_ENTRY_LEVEL": 5}

## Control Outcome Counts By Entry Source

- `ROUND_LEVEL`: {"FAST_SL_20": 53, "GOOD_FAST_REACTION": 4, "GOOD_REACTION_BUT_DIRTY_ACCUMULATION": 1, "GOOD_SLOW_REACTION": 10, "MFE_GOOD_BUT_BE_REQUIRED": 1}
- `SWEEP_EXTREME`: {"FAST_SL_20": 96, "GOOD_FAST_REACTION": 193, "GOOD_REACTION_BUT_DIRTY_ACCUMULATION": 35, "GOOD_SLOW_REACTION": 70, "MFE_GOOD_BUT_BE_REQUIRED": 18, "NO_REACTION": 2, "RUNNER_CANDIDATE": 3}

## Limitations

- `CANDIDATE_UNKNOWN_ENTRY_LEVEL_ROWS_5`
- `CONTROL_GROUP_NOT_FILLED`
- `CONTROL_GROUP_NOT_FILLED_ROUND_LEVEL_ASIA_OPEN_0_OF_25`
- `CONTROL_GROUP_NOT_FILLED_ROUND_LEVEL_LONDON_OPEN_0_OF_30`
- `CONTROL_GROUP_NOT_FILLED_ROUND_LEVEL_NEW_YORK_43_OF_77`
- `CONTROL_GROUP_NOT_FILLED_ROUND_LEVEL_OTHER_26_OF_51`
- `CONTROL_GROUP_NOT_FILLED_SWEEP_EXTREME_ASIA_OPEN_8_OF_103`
- `CONTROL_GROUP_NOT_FILLED_SWEEP_EXTREME_LONDON_OPEN_80_OF_129`
- `CONTROL_GROUP_NOT_FILLED_SWEEP_EXTREME_NEW_YORK_OPEN_73_OF_129`
- `CONTROL_SOURCE_UNSUPPORTED_SWEPT_LIQUIDITY_LEVEL_CANDIDATES_4`
