# Strategy 2 Fully Invalidated State Split

## Context

The invalidation state machine was mechanically consistent, but the audit showed that `FULLY_INVALIDATED` was overloaded. Many rows were H1-consumed or MAE-not-reached cases, not true dual-direction M15 invalidations.

## Old Vs New Taxonomy

- `TRUE_DUAL_DIRECTION_INVALIDATED`: both LONG and SHORT were invalidated by their valid directional M15 opposite-side logic.
- `H1_CONTEXT_ALREADY_CONSUMED`: the H1 reference was already consumed or no fresh H1 setup remained.
- `MAE_NOT_REACHED`: the setup never reached the valid deviation zone and remains setup-incomplete/no-entry.
- `STRUCTURE_INVALID`: source/H1/M15 structure is invalid without true dual-direction invalidation.
- `UNKNOWN_INVALIDATION_STATE`: fallback when the reason cannot be classified confidently.

## Results

- total samples: `1089`
- OLD FULLY_INVALIDATED: `256`
- NEW TRUE_DUAL_DIRECTION_INVALIDATED: `2`
- H1_CONTEXT_ALREADY_CONSUMED: `248`
- MAE_NOT_REACHED: `93`
- STRUCTURE_INVALID: `0`
- UNKNOWN_INVALIDATION_STATE: `0`
- sticky violations: `0`
- cross-H1 contamination flags: `0`
- direction violations: `0`
- critical conclusion: `FULLY_INVALIDATED_OVERLOAD_RESOLVED_LAYER_A_TAXONOMY_CLEARER`

## State Distribution

| State | Count | Rate |
|---|---:|---:|
| H1_CONTEXT_ALREADY_CONSUMED | 248 | 0.2277 |
| INVALIDATED_LONG | 272 | 0.2498 |
| INVALIDATED_SHORT | 288 | 0.2645 |
| MAE_NOT_REACHED | 93 | 0.0854 |
| TRUE_DUAL_DIRECTION_INVALIDATED | 2 | 0.0018 |
| VALID_LONG | 99 | 0.0909 |
| VALID_SHORT | 87 | 0.0799 |

## Safety

- Strategy 3 untouched.
- Adelin untouched.
- data/XAUUSD/*.csv untouched.
- No live trading, broker execution, orders, Telegram, optimization, ML, backtest, PnL, signals, or reaction-quality derivation.

## Critical Conclusion

The `FULLY_INVALIDATED` overload is resolved when true dual-direction invalidation is separated from H1-consumed, MAE-not-reached, structure-invalid, and unknown terminal states. True hard invalidation is now clearer, and Layer A is taxonomy-ready for later Layer B work. This does not validate profitability or derive Layer B reaction quality.

## Honest Limitations

- No reaction-quality derivation.
- No behavioral layer.
- No profitability claim.
- No deployment decision.

## Verdict Flags

- `FULLY_INVALIDATED_STATE_SPLIT_COMPLETE`
- `TRUE_DUAL_DIRECTION_INVALIDATION_SEPARATED`
- `H1_CONSUMED_SEPARATED`
- `MAE_NOT_REACHED_SEPARATED`
- `STATE_TAXONOMY_OVERLOAD_REDUCED`
- `STICKY_INVALIDATION_PRESERVED`
- `STRATEGY_2_REMAINS_RESEARCH_ONLY`
- `NO_DEPLOYMENT_DECISION`
