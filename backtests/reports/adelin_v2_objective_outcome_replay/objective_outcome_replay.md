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

## Candidate Outcome Counts

- `FAST_SL_20`: `4`
- `GOOD_FAST_REACTION`: `1`
- `GOOD_SLOW_REACTION`: `2`
- `UNKNOWN_ENTRY_LEVEL`: `33`

## Control Outcome Counts

- `FAST_SL_20`: `22`
- `GOOD_FAST_REACTION`: `5`
- `GOOD_REACTION_BUT_DIRTY_ACCUMULATION`: `7`
- `GOOD_SLOW_REACTION`: `4`
- `UNKNOWN_DIRECTION`: `2`

## Candidate Vs Control

- `candidate_fast_reaction_rate`: `0.025`
- `control_fast_reaction_rate`: `0.175`
- `candidate_fast_sl_20_rate`: `0.1`
- `control_fast_sl_20_rate`: `0.55`
- `candidate_runner_candidate_rate`: `0.0`
- `control_runner_candidate_rate`: `0.0`
- `candidate_unknown_rate`: `0.825`
- `control_unknown_rate`: `0.05`

## Limitations

- `CANDIDATE_UNKNOWN_ENTRY_LEVEL_ROWS_33`
- `CONTROL_UNKNOWN_DIRECTION_ROWS_2`
