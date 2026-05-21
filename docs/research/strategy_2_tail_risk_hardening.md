# Strategy 2 Tail Risk Hardening Diagnostics

## Context

`containing` is selected only as the next Strategy 2 diagnostic model. The prior containing diagnostic showed a structurally weak R-profile and a very large Max Excursion tail. This branch asks whether simple mechanical diagnostics can reduce that tail without changing the base strategy.

## Safety

- Strategy 3 untouched.
- data/XAUUSD/*.csv untouched.
- No live trading, Telegram, broker execution, orders, optimization, signal generation, grid search, ML, or runtime registration.

## Method

- Primary model: containing.
- Tail buckets: <=8, <=10, <=12, >12, >20, >40, >100 USD.
- Hypotheses are one-factor diagnostic probes using fixed buckets or descriptive percentiles only.
- No PnL/PF, no parameter optimization, no final filter deployment.
- Unit conversion: pips = USD/price distance * 10.0. Do not call USD values pips.

## Body vs Tail Profile

| Bucket | Count | % | Avg MAE | Median MAE | p95 MAE | Max MAE | Avg expansion | TP4_R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BODY_MAE_LE_8 | 145 | 53.9 | 3.528 | 3.44 | 7.178 | 7.92 | 17.1278 | 11.0982 |
| BODY_MAE_LE_10 | 171 | 63.57 | 4.3438 | 4.33 | 9.185 | 9.93 | 16.4481 | 8.8656 |
| BODY_MAE_LE_12 | 179 | 66.54 | 4.6498 | 4.52 | 9.876 | 11.86 | 16.0969 | 7.0603 |
| TAIL_MAE_GT_12 | 90 | 33.46 | 29.0038 | 20.83 | 69.378 | 180.93 | 11.5081 | 0.4465 |
| TAIL_MAE_GT_20 | 49 | 18.22 | 40.5602 | 28.37 | 112.136 | 180.93 | 12.1706 | 0.5365 |
| TAIL_MAE_GT_40 | 15 | 5.58 | 73.4227 | 54.32 | 141.821 | 180.93 | 9.5347 | 0.7641 |
| TAIL_MAE_GT_100 | 4 | 1.49 | 131.6375 | 122.31 | 172.5495 | 180.93 | 9.9675 | 1.5294 |

## Strongest Tail Drivers

| Dimension | Bucket | Count | >12 % | >20 % | p95 MAE | Max MAE |
|---|---|---:|---:|---:|---:|---:|
| h1_range_bucket | >p90 | 27 | 77.78 | 59.26 | 92.075 | 119.56 |
| hour | 14 | 12 | 41.67 | 41.67 | 83.678 | 119.56 |
| hour | 4 | 20 | 60.0 | 40.0 | 73.9405 | 125.06 |
| reentry_minute_bucket | <=p50 | 72 | 62.5 | 38.89 | 82.3495 | 180.93 |
| mae_reach_minute_bucket | <=p50 | 92 | 60.87 | 35.87 | 59.555 | 180.93 |

## Hardening Hypotheses

| Rule | Kept | Removed | Body removed % | Tail removed % | >20 removed % | SL after | TP4_R after | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| NO_TRADE_IF_H1_RANGE_ABOVE_P90 | 242 | 27 | 3.35 | 23.33 | 32.65 | 226.1625 | 0.3626 | WEAK_DIAGNOSTIC |
| NO_TRADE_IF_H1_RANGE_ABOVE_P95 | 255 | 14 | 1.68 | 12.22 | 20.41 | 226.1625 | 0.368 | WEAK_DIAGNOSTIC |
| NO_TRADE_IF_LEVEL_TAKE_AFTER_P75_MINUTE | 214 | 55 | 25.7 | 10.0 | 8.16 | 226.1625 | 0.3857 | WEAK_DIAGNOSTIC |
| NO_TRADE_IF_LEVEL_TAKE_AFTER_P90_MINUTE | 245 | 24 | 10.61 | 5.56 | 6.12 | 226.1625 | 0.3783 | WEAK_DIAGNOSTIC |
| NO_TRADE_IF_MAE_REACH_AFTER_P75_MINUTE | 227 | 42 | 15.64 | 15.56 | 8.16 | 226.1625 | 0.378 | WEAK_DIAGNOSTIC |
| NO_TRADE_IF_REENTRY_AFTER_P75_MINUTE | 236 | 33 | 11.17 | 14.44 | 8.16 | 226.1625 | 0.3765 | WEAK_DIAGNOSTIC |
| NO_TRADE_IF_EXPANSION_MAE_RATIO_BELOW_P25 | 202 | 67 | 6.15 | 62.22 | 69.39 | 54.275 | 1.566 | PROMISING_DIAGNOSTIC |
| NO_TRADE_IF_MAE_ABOVE_P90 | 242 | 27 | 0.0 | 30.0 | 55.1 | 34.725 | 2.8325 | WEAK_DIAGNOSTIC |
| NO_TRADE_IF_DOMINANT_H1 | 261 | 8 | 1.68 | 5.56 | 8.16 | 226.1625 | 0.3733 | WEAK_DIAGNOSTIC |
| NO_TRADE_IF_DIRECTION_LONG | 131 | 138 | 50.84 | 52.22 | 59.18 | 226.1625 | 0.3695 | REJECTED_TOO_BROAD |
| NO_TRADE_IF_DIRECTION_SHORT | 138 | 131 | 49.16 | 47.78 | 40.82 | 156.325 | 0.524 | REJECTED_TOO_BROAD |

## R-Profile Impact

- Raw containing Max Excursion / Conservative SL: 180.93 / 226.1625 USD.
- Raw TP4_R: 0.3749.
- Best diagnostic hypothesis: `NO_TRADE_IF_EXPANSION_MAE_RATIO_BELOW_P25`.
- Important: expansion/MAE ratio is a diagnostic/ex-post tail driver here, not a deployable pre-entry filter.
- After-hypothesis Max Excursion / Conservative SL: 43.42 / 54.275 USD.
- After-hypothesis TP4_R: 1.566.

## Top Tail Cases

| Sample | Direction | H1 ref | Session | Hour | MAE USD | Expansion USD | Ratio |
|---|---|---|---|---:|---:|---:|---:|
| XAUUSD_20260323130000+0000_previous_h1_containing_SHORT | SHORT | previous_h1 | NewYork | 13 | 180.93 | 12.79 | 0.07069032222406454 |
| XAUUSD_20260402040000+0000_previous_h1_containing_LONG | LONG | previous_h1 | Asia | 4 | 125.06 | 11.19 | 0.08947705101551255 |
| XAUUSD_20260319140000+0000_previous_h1_containing_LONG | LONG | previous_h1 | NewYork | 14 | 119.56 | 2.96 | 0.024757443961191034 |
| XAUUSD_20260408010000+0000_previous_h1_containing_SHORT | SHORT | previous_h1 | Asia | 1 | 101.0 | 12.93 | 0.12801980198019802 |
| XAUUSD_20260331040000+0000_previous_h1_containing_SHORT | SHORT | previous_h1 | Asia | 4 | 71.25 | 16.22 | 0.22764912280701752 |
| XAUUSD_20260326180000+0000_previous_h1_containing_LONG | LONG | previous_h1 | NewYork | 18 | 67.09 | 8.85 | 0.13191235653599642 |
| XAUUSD_20260320160000+0000_previous_h1_containing_LONG | LONG | previous_h1 | NewYork | 16 | 64.87 | 9.92 | 0.15292122706952366 |
| XAUUSD_20260318140000+0000_previous_h1_containing_LONG | LONG | previous_h1 | NewYork | 14 | 54.32 | 7.41 | 0.1364138438880707 |
| XAUUSD_20260406010000+0000_previous_h1_containing_LONG | LONG | previous_h1 | Asia | 1 | 53.39 | 3.41 | 0.0638696385090841 |
| XAUUSD_20260428140000+0000_previous_h1_containing_LONG | LONG | previous_h1 | NewYork | 14 | 47.58 | 5.66 | 0.11895754518705338 |

## Verdict

This diagnostic does not prove edge and does not create a filter. If the only meaningful tail reduction comes from broad or ex-post rules, Strategy 2 should remain research-only or be paused rather than forced.

## Verdict Flags

- TAIL_RISK_HARDENING_COMPLETE
- TAIL_RISK_REMAINS_STRUCTURAL
- R_PROFILE_STILL_STRUCTURALLY_WEAK
- STRATEGY_2_REMAINS_RESEARCH_ONLY
- NO_LIVE_DEPLOYMENT_DECISION
- H1_RANGE_TAIL_DRIVER
- ENTRY_TIMING_TAIL_DRIVER
- EXPANSION_MAE_RATIO_TAIL_DRIVER
- R_PROFILE_IMPROVES_DIAGNOSTICALLY

## Next Strategy 2-Only Step

- If one simple hypothesis is promising: feat/strategy-2-hardening-hypothesis-validation
- If no simple hypothesis helps: feat/strategy-2-research-pause-summary
- If H1 dominant is main cause: feat/strategy-2-dominant-h1-hardening
- If entry timing is main cause: feat/strategy-2-entry-timing-diagnostic
