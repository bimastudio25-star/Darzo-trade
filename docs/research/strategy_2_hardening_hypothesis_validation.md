# Strategy 2 Hardening Hypothesis Validation

## Context

Tail-risk hardening found that low expansion/MAE ratio was the strongest separator, but that ratio is ex-post and cannot be used operationally. This branch tests whether faithful pre-entry mechanical proxies can approximate that separator.

## Safety

- Strategy 3 untouched.
- data/XAUUSD/*.csv untouched.
- No live trading, Telegram, broker execution, orders, optimization, signal generation, grid search, ML, or runtime registration.

## Leakage Rules

- Allowed: H1 reference metadata, direction, hour/session, level-take timing, MAE timing, re-entry timing, and other values known before or at entry.
- Forbidden: future expansion, MFE, TP reached, final result, PnL, R multiple, or expansion/MAE ratio as a deployable feature.
- Ex-post expansion/MAE ratio is used only as the target/upper bound.

## Method

- Target label: `BAD_EXPOST_RATIO` = expansion/MAE ratio <= p25 (0.4925).
- Proxy candidates are one-factor descriptive thresholds plus a small limited set of two-factor combinations from top single proxies.
- No PnL/PF and no threshold optimization are used.
- Unit conversion: pips = USD/price distance * 10.0.

## Ex-Post Upper Bound

- Upper bound: `EX_POST_EXPANSION_MAE_RATIO_P25`.
- Bad ex-post ratio caught: 100.0%.
- Tail >20 caught: 69.39%.
- Body false positive: 6.15%.
- Status: EX_POST_UPPER_BOUND_NOT_DEPLOYABLE.

## Pre-Entry Proxy Results

| Proxy | Bad caught % | >20 tail caught % | Body FP % | SL after | TP4_R after | Verdict |
|---|---:|---:|---:|---:|---:|---|
| LEVEL_TAKE_MINUTE_IN_H1_LE_P25 | 87.72 | 85.71 | 59.78 | 83.8625 | 0.867 | REJECTED_TOO_BROAD |
| DIRECTION_LONG | 56.14 | 59.18 | 50.84 | 226.1625 | 0.3695 | REJECTED_TOO_BROAD |
| COMBO_TIME_FROM_MAE_TO_REENTRY_LE_P25__OR__MAE_REACH_MINUTE_IN_H1_LE_P25 | 45.61 | 61.22 | 12.85 | 89.0625 | 0.9288 | PROMISING_PRE_ENTRY_PROXY |
| COMBO_TIME_FROM_MAE_TO_REENTRY_LE_P25__OR__TIME_FROM_TAKE_TO_MAE_LE_P25 | 45.61 | 61.22 | 13.41 | 89.0625 | 0.9287 | PROMISING_PRE_ENTRY_PROXY |
| DIRECTION_SHORT | 43.86 | 40.82 | 49.16 | 156.325 | 0.524 | REJECTED_TOO_BROAD |
| SESSION_Asia | 40.35 | 40.82 | 30.73 | 226.1625 | 0.3691 | REJECTED_TOO_BROAD |
| TIME_FROM_MAE_TO_REENTRY_LE_P25 | 38.6 | 53.06 | 11.17 | 89.0625 | 0.9467 | WEAK_PROXY |
| TIME_FROM_TAKE_TO_MAE_LE_P25 | 38.6 | 51.02 | 10.61 | 89.0625 | 0.9477 | WEAK_PROXY |
| COMBO_TIME_FROM_TAKE_TO_MAE_LE_P25__OR__MAE_REACH_MINUTE_IN_H1_LE_P25 | 38.6 | 51.02 | 10.61 | 89.0625 | 0.9477 | WEAK_PROXY |
| MAE_REACH_MINUTE_IN_H1_LE_P25 | 38.6 | 48.98 | 8.94 | 89.0625 | 0.9507 | WEAK_PROXY |
| REENTRY_MINUTE_IN_H1_LE_P25 | 33.33 | 42.86 | 7.82 | 89.0625 | 0.9605 | WEAK_PROXY |
| SESSION_NewYork | 31.58 | 38.78 | 30.17 | 156.325 | 0.5031 | REJECTED_TOO_BROAD |

## Best Proxy

- Best pre-entry proxy: `COMBO_TIME_FROM_MAE_TO_REENTRY_LE_P25__OR__MAE_REACH_MINUTE_IN_H1_LE_P25`.
- Final verdict: `PRE_ENTRY_PROXY_FOUND_DIAGNOSTIC_ONLY`.

## R-Profile Impact

- Raw TP4_R: 0.3749.
- Raw conservative SL: 226.1625 USD.
- After best proxy TP4_R: 0.9288.
- After best proxy conservative SL: 89.0625 USD.

## Leakage Audit

| Feature | Pre-entry? | Leakage flag | Reason |
|---|---|---|---|
| expansion_mae_ratio | False | LEAKAGE_FEATURE | Requires future expansion after entry; target/upper-bound only. |
| expansion_usd | False | LEAKAGE_FEATURE | Future expansion after setup. |
| max_favorable_excursion | False | LEAKAGE_FEATURE | Future path after entry. |
| tp_reached | False | LEAKAGE_FEATURE | Future outcome. |
| final_result | False | LEAKAGE_FEATURE | Future outcome. |
| pnl | False | LEAKAGE_FEATURE | Performance outcome. |
| r_multiple | False | LEAKAGE_FEATURE | Performance outcome. |
| h1_reference_range | True |  | Known before the level-take setup. |
| direction | True |  | Known from H1 liquidity side. |
| hour | True |  | Known before or at entry. |
| session | True |  | Known before or at entry. |
| level_take_minute_in_h1 | True |  | Known before entry after level take. |
| mae_reach_minute_in_h1 | True |  | Known at MAE reach. |
| reentry_minute_in_h1 | True |  | Known at entry/re-entry. |
| time_from_take_to_mae | True |  | Known at MAE reach. |
| time_from_mae_to_reentry | True |  | Known at entry/re-entry. |

## Limitations

- The target is ex-post and diagnostic only.
- No manual labels are available.
- No live/signal validation is made.
- A proxy that helps diagnostically is not a deployment decision.

## Verdict Flags

- HARDENING_HYPOTHESIS_VALIDATION_COMPLETE
- EX_POST_UPPER_BOUND_NOT_DEPLOYABLE
- R_PROFILE_STILL_STRUCTURALLY_WEAK
- STRATEGY_2_REMAINS_RESEARCH_ONLY
- NO_LIVE_DEPLOYMENT_DECISION
- PRE_ENTRY_PROXY_FOUND_DIAGNOSTIC_ONLY
- LEAKAGE_FEATURES_REJECTED

## Next Strategy 2-Only Step

- If promising proxy: feat/strategy-2-pre-entry-proxy-limited-diagnostic
- If no proxy: feat/strategy-2-research-pause-summary
- If inconclusive: feat/strategy-2-proxy-data-enrichment
