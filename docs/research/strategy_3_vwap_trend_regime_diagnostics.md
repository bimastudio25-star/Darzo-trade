# Strategy 3 VWAP Trend Regime Diagnostics

Strategy 3 remains Level 3 / Paper Candidate. This report is diagnostics-only and does not validate profitability or live readiness.

## Context

- context consistency gate passed: `True`
- clean diagnostic rows: `71`
- accepted/blocked: `26/45`
- all-detected match rate: `1.0`
- accepted-only match rate: `1.0`

## Blocked Rows

| block_reason | blocked_rows | pct_blocked_rows |
|---|---:|---:|
| STRATEGY_3_COOLDOWN_BLOCKED | 45 | 1.0 |

## Session Summary

| session | total | accepted | blocked | accepted_rate | small_n |
|---|---:|---:|---:|---:|---|
| London | 7 | 1 | 6 | 0.1429 | True |
| London/New York overlap | 18 | 6 | 12 | 0.3333 | False |
| New York | 14 | 5 | 9 | 0.3571 | False |
| Sydney | 9 | 3 | 6 | 0.3333 | True |
| Sydney + Tokyo | 15 | 7 | 8 | 0.4667 | False |
| Tokyo | 2 | 1 | 1 | 0.5 | True |
| Tokyo + London | 6 | 3 | 3 | 0.5 | True |

## Key Regime Buckets

| dimension | bucket | total | accepted | blocked | accepted_rate | small_n |
|---|---|---:|---:|---:|---:|---|
| direction | LONG | 47 | 16 | 31 | 0.3404 | False |
| direction | SHORT | 24 | 10 | 14 | 0.4167 | False |
| vwap_slope_bucket | down | 34 | 16 | 18 | 0.4706 | False |
| vwap_slope_bucket | flat | 5 | 1 | 4 | 0.2 | True |
| vwap_slope_bucket | up | 32 | 9 | 23 | 0.2812 | False |
| h4_bias | down | 38 | 11 | 27 | 0.2895 | False |
| h4_bias | up | 33 | 15 | 18 | 0.4545 | False |
| volatility_bucket | high_volatility | 24 | 9 | 15 | 0.375 | False |
| volatility_bucket | low_volatility | 24 | 9 | 15 | 0.375 | False |
| volatility_bucket | medium_volatility | 23 | 8 | 15 | 0.3478 | False |

## Candidate Hypotheses

- H4 up-context and downward VWAP-slope buckets show higher accepted fractions in this small sample, but this is a descriptive concentration only.
- London shows more cooldown blocking than other larger session buckets in this sample, but its row count is below the bucket threshold.
- Volatility tertiles are close to flat in accepted fraction, so this sample does not suggest a strong descriptive volatility split.
- Any future use of these observations must be pre-registered before changing Strategy 3 logic.

## Interpretation

- The 26 accepted rows are too few for robust performance or regime-level edge conclusions.
- Regime labels are descriptive only and use pre-decision data; post-entry outcome is not used to define any bucket.
- Any promising concentration must become a future pre-registered diagnostic or test before strategy behavior changes.

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

## Outputs

- `backtests\reports\strategy_3_vwap_trend_regime_diagnostics\regime_diagnostics_per_signal.csv`
- `backtests\reports\strategy_3_vwap_trend_regime_diagnostics\blocked_reason_summary.csv`
- `backtests\reports\strategy_3_vwap_trend_regime_diagnostics\accepted_vs_blocked_by_regime.csv`
- `backtests\reports\strategy_3_vwap_trend_regime_diagnostics\session_regime_summary.csv`
- `backtests\reports\strategy_3_vwap_trend_regime_diagnostics\regime_summary.json`

## Next Recommendation

Use these descriptive buckets only to design future pre-registered tests; continue paper observation before any Strategy 3 change.
