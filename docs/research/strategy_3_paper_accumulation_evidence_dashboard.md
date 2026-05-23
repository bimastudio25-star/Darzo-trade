# Strategy 3 Paper Accumulation Evidence Dashboard

Strategy 3 remains Level 3 / Paper Candidate. This dashboard is diagnostics/logging only and does not approve live trading or change signal behavior.

## Paper Accumulation Status

- total paper rows: `135`
- legacy rows excluded from clean evidence: `64`
- clean context rows: `71`
- clean accepted/blocked: `26/45`
- clean acceptance rate: `0.3662`
- accepted sample status: `INSUFFICIENT_N`

## Accumulation Projection

- first clean signal: `2026-05-21T02:30:00+00:00`
- latest clean signal: `2026-05-22T22:30:00+00:00`
- days since first clean signal: `1.8333`
- clean rows/day: `38.7273`
- accepted rows/day: `14.1818`
- exploratory accepted target: `100`
- pre-registered diagnostic accepted target: `200`
- gap to exploratory target: `74`
- gap to pre-registered diagnostic target: `174`
- projected days to exploratory target: `5.22`
- projected days to pre-registered diagnostic target: `12.27`
- regime-level claims: `NOT_ALLOWED_FROM_DASHBOARD`

## Context Gate

- context_gate_passed: `True`
- prefix_compatible_rows: `71`
- prefix_incompatible_rows: `0`

## Cooldown

- cooldown accepted count: `26`
- cooldown blocked count: `45`
- cooldown policy changed: `False`

| block_reason | blocked_rows | pct_blocked_rows |
|---|---:|---:|
| STRATEGY_3_COOLDOWN_BLOCKED | 45 | 1.0 |

## Regime Sample Status

| dimension | bucket | total | accepted | status |
|---|---|---:|---:|---|
| band_touched | sigma_1_lower | 21 | 10 | INSUFFICIENT_N |
| band_touched | sigma_1_upper | 16 | 6 | INSUFFICIENT_N |
| band_touched | sigma_2_lower | 11 | 3 | INSUFFICIENT_N |
| band_touched | sigma_2_upper | 7 | 3 | INSUFFICIENT_N |
| band_touched | vwap | 16 | 4 | INSUFFICIENT_N |
| direction | LONG | 47 | 16 | INSUFFICIENT_N |
| direction | SHORT | 24 | 10 | INSUFFICIENT_N |
| h1_bias | down | 44 | 16 | INSUFFICIENT_N |
| h1_bias | up | 27 | 10 | INSUFFICIENT_N |
| h4_bias | down | 38 | 11 | INSUFFICIENT_N |
| h4_bias | up | 33 | 15 | INSUFFICIENT_N |
| price_vs_vwap | above_vwap | 30 | 11 | INSUFFICIENT_N |

## Risk Distance / Stop Loss

- pip convention: `PROJECT_PIP_CONVENTION: 1 USD = 10 pips`
- all clean median SL distance: `0.96` USD / `9.6` pips
- all clean p90 SL distance: `3.46` USD / `34.6` pips
- accepted median SL distance: `1.35` USD / `13.5` pips
- accepted p90 SL distance: `4.705` USD / `47.05` pips

Risk stats are descriptive only. Large SL outliers require review, not automatic parameter changes. No SL/TP/cooldown/entry logic is modified.

## Metadata Schema

Future paper logging may record the following non-decision metadata fields:

- `strategy_3_regime_schema_version`
- `session_bucket`
- `signal_direction`
- `vwap_slope_bucket`
- `vwap_distance_bucket`
- `h1_bias`
- `h4_bias`
- `volatility_bucket`
- `cooldown_active`
- `cooldown_remaining_minutes`
- `block_reason`
- `context_compatibility_status`

These fields are metadata only. They must not be used to accept, block, filter, or modify signals in this branch.

## Power Planning

- 26 accepted clean signals is insufficient for regime-level conclusions.
- n>=100 accepted may be enough only for exploratory watchlist status, not robust inference.
- n>=200 accepted is the current dashboard target for considering a pre-registered diagnostic, not deployment.
- Regime comparisons may require much larger samples, especially when looking for modest win-rate differences.
- No trading recommendation is emitted from this power planning section.

## Safety

- no live trading
- no Telegram operational alerts
- no orders
- no broker execution
- no order_send
- no Strategy 3 VWAP/sigma/cooldown/entry/TP/SL/filter changes
- no Strategy 2 touch
- no Adelin touch
- no data/XAUUSD/*.csv mutation

## Next Recommendation

Continue Strategy 3 paper accumulation with metadata logging active; use dashboard labels to decide when a future pre-registered diagnostic is worth opening.
