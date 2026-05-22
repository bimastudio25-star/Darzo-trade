# Strategy 2 Invalidation Rate Audit

## Context

The hard invalidation state machine produced an extreme invalidation rate, so Layer B reaction-quality derivation is postponed until Layer A scope is audited.

## Mechanical Rule Recap

- LONG targeting H1 LOW is invalidated if the opposite M15 HIGH is taken first.
- SHORT targeting H1 HIGH is invalidated if the opposite M15 LOW is taken first.
- Invalidation is sticky inside the same H1 context.

## Findings

- samples processed: `1089`
- valid count/rate: `186` / `0.1708`
- invalidated count/rate: `903` / `0.8292`
- fully invalidated count/rate: `256` / `0.2351`
- sticky violations: `0`
- H1 cross-boundary flags: `0`
- fully-invalidated contexts without both directional invalidations: `233`
- critical assessment: `LIKELY_TOO_AGGRESSIVE_FULLY_INVALIDATED_IS_OVERLOADED`

## Invalidation Reason Distribution

| Reason | Samples | Rate |
|---|---:|---:|
| OPPOSITE_M15_LOW_TAKEN_FIRST_FOR_SHORT | 289 | 0.2654 |
| MAE_NOT_REACHED | 278 | 0.2553 |
| OPPOSITE_M15_HIGH_TAKEN_FIRST_FOR_LONG | 273 | 0.2507 |
| H1_REFERENCE_ALREADY_CONSUMED | 248 | 0.2277 |
| UNKNOWN_OR_NONE | 186 | 0.1708 |
| FULLY_INVALIDATED_H1_CONTEXT | 8 | 0.0073 |

## Critical Assessment

Directionality and sticky behavior are mechanically consistent in this audit. However, `FULLY_INVALIDATED` is currently overloaded because many rows are H1-reference/no-level consumed cases rather than contexts where both LONG and SHORT were truly invalidated. That makes the headline invalidation rate useful as a warning, but too aggressive to accept as final Layer A truth without separating H1-consumed/no-level states from true dual-direction invalidation.

## Safety

- Strategy 3 untouched.
- Adelin untouched.
- data/XAUUSD/*.csv untouched.
- No optimization, signals, broker execution, orders, Telegram, backtest, PnL, or reaction-quality derivation.

## Honest Limitations

- No behavioral layer.
- No reaction derivation.
- No profitability analysis.
- No deployment claim.

## Verdict Flags

- `INVALIDATION_RATE_AUDITED`
- `STICKY_INVALIDATION_CONFIRMED`
- `H1_CONTEXT_SCOPING_VERIFIED`
- `FULLY_INVALIDATED_LOGIC_REVIEWED`
- `LAYER_B_POSTPONED_PENDING_AUDIT`
- `STRATEGY_2_REMAINS_RESEARCH_ONLY`
- `NO_DEPLOYMENT_DECISION`
