# Strategy 2.0 STILL_OPEN Diagnostic

This is a lightweight CSV/JSON diagnostic only. No full backtest was run.

## Source Data

- executed_trades.csv: `backtests\reports\final\executed_trades.csv`
- summary.json: `backtests\reports\final\summary.json`
- rows read: 1104
- columns available: timestamp, symbol, strategy, direction, entry, stop, sl_distance, sl_distance_usd, sl_distance_pips, risk_label, tp1, tp2, tp3, tp4, rr_tp1, score, session, accepted, rejection_reasons, outcome, exit_time, exit_price, r_multiple, mae, mfe, bars_held
- relevant columns missing: close_price, final_price, last_price, max_bars, max_sim_bars, setup_mode

## Metric Revision Warning

- metric_revision_due_to_still_open_policy: true
- affected_strategies: strategy_1_adelin_scalp, strategy_2_liquidity_expansion, any_strategy_using_shared_simulator
- Old reports could treat STILL_OPEN with r_multiple=0 as metric-neutral.
- Future reports may change PF / WR / AvgR / MaxDD because unresolved trades close at available close.
- This does not mean Strategy 2.0 improved; it means metrics are more honest.
- This does not re-open Adelin edge interpretation; Adelin remains lockdown/research-only.

## Strategy 2.0 Totals

- total trades: 97
- closed trades: 52
- STILL_OPEN trades: 45
- STILL_OPEN percentage: 46.39%
- outcome distribution: `{"BE": 10, "SL": 21, "STILL_OPEN": 45, "TP2": 21}`
- average R all trades: -0.0716
- average R STILL_OPEN: 0.0
- STILL_OPEN r_multiple = 0: 45

## Simulated Policy Effect From CSV

- classification counts: `{"cannot_reclassify_missing_final_price": 45}`
- reclassifiable without full backtest: 0
- not reclassifiable: 45

## Cross-strategy STILL_OPEN Audit

| strategy | total | STILL_OPEN | rate | avg R STILL_OPEN | metric revision effective |
|---|---:|---:|---:|---:|---|
| strategy_1_adelin_scalp | 1007 | 0 | 0.00% | None | false |
| strategy_2_liquidity_expansion | 97 | 45 | 46.39% | 0.0 | true |

## MFE/MAE Range Estimate

estimate from MFE/MAE, not actual reclassification. True r_multiple requires running the simulator with the new TIMEOUT_CLOSE / END_OF_DATA_CLOSE policy on candle data. This lightweight diagnostic does not claim actual historical exits.

- count with MFE/MAE: 45
- count without MFE/MAE: 0
- optimistic mean/median: 0.2871 / 0.2487
- pessimistic mean/median: -0.4359 / -0.3318
- midpoint mean/median: -0.0744 / -0.0713
- range width mean/median: 0.723 / 0.6544
- range width > 1.5R: 1 (2.22%)

## Smoke Decision

- decision: `SMOKE_BACKTEST_RECOMMENDED`
- numeric triggers: missing_required_fields_gt_20pct, strategy_2_still_open_rate_gt_10pct, close_reason_or_actual_close_not_reliable_from_csv
- recommendation: If executed later, use a maximum 3-5 day, single-symbol, Strategy 2.0 only, report-only smoke backtest. Do not run a full 3-month backtest for this diagnostic.

## Warnings

- CLOSE_REASON_FIELD_NOT_AVAILABLE
- FINAL_CLOSE_FIELD_NOT_AVAILABLE_FOR_STILL_OPEN
- FULL_BACKTEST_NOT_RUN
