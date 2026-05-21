# Strategy 2 Unit Distance Audit

## Context

This audit checks whether Strategy 2 values such as Max Excursion, conservative SL, expansion, and TP distances are raw XAUUSD price-distance values or pips. It does not change strategy logic or rewrite historical reports.

## Safety

- Strategy 3 untouched.
- data/XAUUSD/*.csv untouched.
- No live trading, Telegram, broker execution, orders, signal generation, or optimization.

## Conversion Rule

- pip_factor used: 10.0
- pips = price_distance * pip_factor
- price_distance = pips / pip_factor
- `*_usd` in these reports should be read as XAUUSD price-distance units, not account-currency dollars.

## Verdict

- Unit semantics: `RAW_DISTANCE_VALUES_ARE_XAUUSD_PRICE_DISTANCE_NOT_PIPS`
- Pair mismatches: 0
- R-profile changes after correction: NO; R ratios use consistent distance units. Absolute labels need clarification.

## Audit Answers

1. Raw `*_usd` values are interpreted as XAUUSD price-distance values, not pips and not account-currency PnL dollars.
2. With `pip_factor=10`, `pips = price_distance * 10` and `price_distance = pips / 10`.
3. No `*_usd`/`*_pips` pair mismatches were found. The audit did not find evidence that pips were stored as USD; it found that the `USD` label is ambiguous and should be normalized.
4. R calculations use consistent distance units, so the R-profile does not change under unit relabeling.
5. Corrected SL/TP values are shown below in both XAUUSD price-distance and pips.

## Corrected Key Values

| Field | Raw value | Price distance | Pips | Corrected label | Source |
|---|---:|---:|---:|---|---|
| max_excursion_usd | 180.93 | 180.93 | 1809.3 | XAUUSD price-distance units, not account-currency dollars | backtests/reports/strategy_2_m15_containing_next_diagnostic/containing_diagnostic_summary.json |
| conservative_sl_usd | 226.1625 | 226.1625 | 2261.625 | XAUUSD price-distance units, not account-currency dollars | backtests/reports/strategy_2_m15_containing_next_diagnostic/containing_diagnostic_summary.json |
| tp1_distance_usd | 16.7975 | 16.7975 | 167.975 | XAUUSD price-distance units, not account-currency dollars | backtests/reports/strategy_2_m15_containing_next_diagnostic/containing_diagnostic_summary.json |
| tp2_distance_usd | 33.595 | 33.595 | 335.95 | XAUUSD price-distance units, not account-currency dollars | backtests/reports/strategy_2_m15_containing_next_diagnostic/containing_diagnostic_summary.json |
| tp3_distance_usd | 50.3925 | 50.3925 | 503.925 | XAUUSD price-distance units, not account-currency dollars | backtests/reports/strategy_2_m15_containing_next_diagnostic/containing_diagnostic_summary.json |
| tp4_distance_usd | 67.19 | 67.19 | 671.9 | XAUUSD price-distance units, not account-currency dollars | backtests/reports/strategy_2_m15_containing_next_diagnostic/containing_diagnostic_summary.json |
| mae_avg_usd | 12.798 | 12.798 | 127.98 | XAUUSD price-distance units, not account-currency dollars | backtests/reports/strategy_2_m15_containing_next_diagnostic/containing_diagnostic_summary.json |
| mae_median_usd | 6.96 | 6.96 | 69.6 | XAUUSD price-distance units, not account-currency dollars | backtests/reports/strategy_2_m15_containing_next_diagnostic/containing_diagnostic_summary.json |
| mae_p90_usd | 27.854 | 27.854 | 278.54 | XAUUSD price-distance units, not account-currency dollars | backtests/reports/strategy_2_m15_containing_next_diagnostic/containing_diagnostic_summary.json |
| mae_p95_usd | 41.592 | 41.592 | 415.92 | XAUUSD price-distance units, not account-currency dollars | backtests/reports/strategy_2_m15_containing_next_diagnostic/containing_diagnostic_summary.json |
| max_expansion_usd | 67.19 | 67.19 | 671.9 | XAUUSD price-distance units, not account-currency dollars | backtests/reports/strategy_2_m15_containing_next_diagnostic/containing_diagnostic_summary.json |

## R-Profile

R calculations are dimensionless. If all distances are converted consistently, R values do not change. The issue is label clarity: absolute distances should be shown as both XAUUSD price-distance and pips.

## Affected Reports

- backtests/reports/strategy_2_m15_containing_next_diagnostic
- backtests/reports/strategy_2_tail_risk_hardening

## Follow-Up

- Recommended follow-up branch: `fix/strategy-2-distance-label-normalization`
- Proposed fix: normalize report labels from ambiguous `USD` wording to `price_distance_usd` plus explicit pips.
