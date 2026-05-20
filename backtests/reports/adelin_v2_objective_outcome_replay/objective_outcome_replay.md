# Adelin v2 Objective Outcome Replay

Status: diagnostic baseline comparison only. Candidate windows are not signals and this is not validation.

- symbol: `XAUUSD`
- pip_size: `0.1` from `core.symbols.get_symbol_spec`
- forward_hours: `4.0`

Forward windows above 4h may overstate runner quality on XAUUSD.

## Counts

- candidate samples loaded: `40`
- candidate samples replayed: `40`
- control samples generated: `40`
- rows written: `80`
- candidate known-entry rows: `35`
- control known-entry rows: `40`
- candidate unknown entry-level rate: `0.125`

Known-entry subset is still descriptive and not validation.

## Entry Level Source Counts

### Candidate

- `ROUND_LEVEL`: `7`
- `SWEEP_EXTREME`: `24`
- `SWEPT_LIQUIDITY_LEVEL`: `4`
- `UNKNOWN`: `5`

### Control

- `ROUND_LEVEL`: `40`

## Candidate Outcome Counts

- `FAST_SL_20`: `7`
- `GOOD_FAST_REACTION`: `13`
- `GOOD_REACTION_BUT_DIRTY_ACCUMULATION`: `4`
- `GOOD_SLOW_REACTION`: `9`
- `RUNNER_CANDIDATE`: `1`
- `UNKNOWN_ENTRY_LEVEL`: `5`
- `UNKNOWN_INSUFFICIENT_FORWARD_DATA`: `1`

## Control Outcome Counts

- `FAST_SL_20`: `22`
- `GOOD_FAST_REACTION`: `5`
- `GOOD_REACTION_BUT_DIRTY_ACCUMULATION`: `7`
- `GOOD_SLOW_REACTION`: `4`
- `UNKNOWN_DIRECTION`: `2`

## Candidate Vs Control

- `candidate_fast_reaction_rate`: `0.35`
- `control_fast_reaction_rate`: `0.175`
- `candidate_fast_sl_20_rate`: `0.175`
- `control_fast_sl_20_rate`: `0.55`
- `candidate_runner_candidate_rate`: `0.025`
- `control_runner_candidate_rate`: `0.0`
- `candidate_unknown_rate`: `0.15`
- `control_unknown_rate`: `0.05`

## Candidate Vs Control Known Entry

- `candidate_fast_reaction_rate`: `0.4`
- `control_fast_reaction_rate`: `0.175`
- `candidate_fast_sl_20_rate`: `0.2`
- `control_fast_sl_20_rate`: `0.55`
- `candidate_runner_candidate_rate`: `0.0286`
- `control_runner_candidate_rate`: `0.0`
- `candidate_unknown_rate`: `0.0286`
- `control_unknown_rate`: `0.05`

## Candidate Outcome Counts By Entry Source

- `ROUND_LEVEL`: {"FAST_SL_20": 4, "GOOD_FAST_REACTION": 1, "GOOD_SLOW_REACTION": 2}
- `SWEEP_EXTREME`: {"FAST_SL_20": 2, "GOOD_FAST_REACTION": 10, "GOOD_REACTION_BUT_DIRTY_ACCUMULATION": 3, "GOOD_SLOW_REACTION": 7, "RUNNER_CANDIDATE": 1, "UNKNOWN_INSUFFICIENT_FORWARD_DATA": 1}
- `SWEPT_LIQUIDITY_LEVEL`: {"FAST_SL_20": 1, "GOOD_FAST_REACTION": 2, "GOOD_REACTION_BUT_DIRTY_ACCUMULATION": 1}
- `UNKNOWN`: {"UNKNOWN_ENTRY_LEVEL": 5}

## Control Outcome Counts By Entry Source

- `ROUND_LEVEL`: {"FAST_SL_20": 22, "GOOD_FAST_REACTION": 5, "GOOD_REACTION_BUT_DIRTY_ACCUMULATION": 7, "GOOD_SLOW_REACTION": 4, "UNKNOWN_DIRECTION": 2}

## Limitations

- `CANDIDATE_UNKNOWN_ENTRY_LEVEL_ROWS_5`
- `CONTROL_SWEEP_EXTREME_ROWS_0_BASELINE_UNAVAILABLE`
- `CONTROL_UNKNOWN_DIRECTION_ROWS_2`
