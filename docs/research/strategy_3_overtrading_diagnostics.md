# Strategy 3 Overtrading Diagnostics

Status: research-only diagnostic. NON considerare il PF positivo come edge validato.

## Source

- branch: `feat/strategy-3-overtrading-diagnostics`
- base commit: `7b14abf Add Strategy 3 VWAP 1R research scaffold`
- executed trades: `backtests/reports/strategy_3_vwap_1r_diagnostic_smoke/executed_trades.csv`
- summary: `backtests/reports/strategy_3_vwap_1r_diagnostic_smoke/summary.json`
- rows read: `94`
- diagnostic rerun trade count changed: `false`

## Original Smoke Reminder

- trades: `94`
- PF: `1.186`
- WR: `54.26%`
- AvgR: `0.0851`
- total_R: `8.0`
- MaxDD: `6.0R`
- warning: `STRATEGY_3_OVERTRADING_INITIAL`

## Statistical Floor

- `n < 10`: insufficient
- `10 <= n < 30`: weak
- `30 <= n < 100`: moderate
- `n >= 100`: significant

## NO_TRADE Leakage Check

- no_trade_executed_count: `0`
- no_trade_leakage_detected: `false`

## Trade Density

- total trades: `94`
- observed days: `3.8229`
- trades/day: `24.5886`
- max trades/day: `38`
- max trades/hour: `4`
- average gap minutes: `43.7097`
- median gap minutes: `15.0`
- OVERTRADING_DENSITY_CONFIRMED: `true`

## Breakdown By Setup Mode

| category | trades | WR | PF | AvgR | MedianR | total_R | category_significance | interpretation |
|---|---|---|---|---|---|---|---|---|
| trend_following | 48 | 0.5625 | 1.2857 | 0.125 | 1.0 | 6.0 | moderate | analyzable_hypothesis |
| reversal | 46 | 0.5217 | 1.0909 | 0.0435 | 1.0 | 2.0 | moderate | analyzable_hypothesis |

## Breakdown By Band Touched

| category | trades | WR | PF | AvgR | MedianR | total_R | category_significance | interpretation |
|---|---|---|---|---|---|---|---|---|
| vwap | 25 | 0.56 | 1.2727 | 0.12 | 1.0 | 3.0 | weak | directional_only |
| sigma_1_upper | 24 | 0.5417 | 1.1818 | 0.0833 | 1.0 | 2.0 | weak | directional_only |
| sigma_2_upper | 16 | 0.75 | 3.0 | 0.5 | 1.0 | 8.0 | weak | directional_only |
| sigma_1_lower | 15 | 0.4667 | 0.875 | -0.0667 | -1.0 | -1.0 | weak | directional_only |
| sigma_2_lower | 14 | 0.3571 | 0.5556 | -0.2857 | -1.0 | -4.0 | weak | directional_only |

## Breakdown By Session

| category | trades | WR | PF | AvgR | MedianR | total_R | category_significance | interpretation |
|---|---|---|---|---|---|---|---|---|
| London/New York overlap | 22 | 0.5455 | 1.2 | 0.0909 | 1.0 | 2.0 | weak | directional_only |
| Sydney + Tokyo | 20 | 0.5 | 1.0 | 0.0 | 0.0 | 0.0 | weak | directional_only |
| London | 19 | 0.6316 | 1.7143 | 0.2632 | 1.0 | 5.0 | weak | directional_only |
| Tokyo + London | 11 | 0.5455 | 1.2 | 0.0909 | 1.0 | 1.0 | weak | directional_only |
| New York | 10 | 0.5 | 1.0 | 0.0 | 0.0 | 0.0 | weak | directional_only |
| Sydney | 6 | 0.5 | 1.0 | 0.0 | 0.0 | 0.0 | insufficient | insufficient_sample |
| Tokyo | 6 | 0.5 | 1.0 | 0.0 | 0.0 | 0.0 | insufficient | insufficient_sample |

## Breakdown By Direction

| category | trades | WR | PF | AvgR | MedianR | total_R | category_significance | interpretation |
|---|---|---|---|---|---|---|---|---|
| LONG | 50 | 0.48 | 0.9231 | -0.04 | -1.0 | -2.0 | moderate | analyzable_hypothesis |
| SHORT | 44 | 0.6136 | 1.5882 | 0.2273 | 1.0 | 10.0 | moderate | analyzable_hypothesis |

## Reason Code Frequency

| reason_code | trades | WR | PF | AvgR | MedianR | total_R | category_significance | interpretation |
|---|---|---|---|---|---|---|---|---|
| liquidity_sweep | 94 | 0.5426 | 1.186 | 0.0851 | 1.0 | 8.0 | moderate | analyzable_hypothesis |
| number_theory_context | 94 | 0.5426 | 1.186 | 0.0851 | 1.0 | 8.0 | moderate | analyzable_hypothesis |
| target_1r | 94 | 0.5426 | 1.186 | 0.0851 | 1.0 | 8.0 | moderate | analyzable_hypothesis |
| setup_trend_following | 48 | 0.5625 | 1.2857 | 0.125 | 1.0 | 6.0 | moderate | analyzable_hypothesis |
| setup_reversal | 46 | 0.5217 | 1.0909 | 0.0435 | 1.0 | 2.0 | moderate | analyzable_hypothesis |
| vwap_band_vwap | 25 | 0.56 | 1.2727 | 0.12 | 1.0 | 3.0 | weak | directional_only |
| vwap_band_sigma_1_upper | 24 | 0.5417 | 1.1818 | 0.0833 | 1.0 | 2.0 | weak | directional_only |
| vwap_band_sigma_2_upper | 16 | 0.75 | 3.0 | 0.5 | 1.0 | 8.0 | weak | directional_only |
| vwap_band_sigma_1_lower | 15 | 0.4667 | 0.875 | -0.0667 | -1.0 | -1.0 | weak | directional_only |
| vwap_band_sigma_2_lower | 14 | 0.3571 | 0.5556 | -0.2857 | -1.0 | -4.0 | weak | directional_only |
| fvg_ifvg_context | 10 | 0.6 | 1.5 | 0.2 | 1.0 | 2.0 | weak | directional_only |
| volume_crack_context | 3 | 0.3333 | 0.5 | -0.3333 | -1.0 | -1.0 | insufficient | insufficient_sample |

## Confluence Breakdown

| confluence | trades | WR | PF | AvgR | MedianR | total_R | category_significance | interpretation |
|---|---|---|---|---|---|---|---|---|
| number_theory:confluence_true | 94 | 0.5426 | 1.186 | 0.0851 | 1.0 | 8.0 | moderate | analyzable_hypothesis |
| vwap:present | 94 | 0.5426 | 1.186 | 0.0851 | 1.0 | 8.0 | moderate | analyzable_hypothesis |
| volume:confluence_false | 91 | 0.5495 | 1.2195 | 0.0989 | 1.0 | 9.0 | moderate | analyzable_hypothesis |
| volume:confluence_true | 3 | 0.3333 | 0.5 | -0.3333 | -1.0 | -1.0 | insufficient | insufficient_sample |

## Cluster Diagnostics

- average trade gap minutes: `43.7097`
- median trade gap minutes: `15.0`
- gap < 15m count: `0`
- gap < 30m count: `49`
- max trades same hour: `4`
- max trades same session/direction/band: `5`
- POTENTIAL_DUPLICATE_CLUSTER: `true`
- MISSING_COOLDOWN: `true`

## Cluster Impact Metric

- all trades: PF `1.186`, AvgR `0.0851`, total_R `8.0`
- dedupped 15m: kept `94`, removed `0`, PF `1.186`, AvgR `0.0851`, total_R `8.0`, delta_PF `0.0`
- dedupped 60m: kept `53`, removed `41`, PF `1.2083`, AvgR `0.0943`, total_R `5.0`, delta_PF `-0.0223`
- DUPLICATE_CONTEXT_ENTRIES_DETECTED: `false`

## Distance Diagnostics

- mean vwap_distance: `9.0309`
- median vwap_distance: `7.7`
- min/max vwap_distance: `0.0` / `24.8`

| category | trades | WR | PF | AvgR | MedianR | total_R | category_significance | interpretation |
|---|---|---|---|---|---|---|---|---|
| near_vwap | 25 | 0.56 | 1.2727 | 0.12 | 1.0 | 3.0 | weak | directional_only |
| sigma_1_area | 39 | 0.5128 | 1.0526 | 0.0256 | 1.0 | 1.0 | moderate | analyzable_hypothesis |
| sigma_2_area | 30 | 0.5667 | 1.3077 | 0.1333 | 1.0 | 4.0 | moderate | analyzable_hypothesis |

## Liquidity Context Diagnostics

| category | trades | WR | PF | AvgR | MedianR | total_R | category_significance | interpretation |
|---|---|---|---|---|---|---|---|---|
| internal_liquidity | 79 | 0.5316 | 1.1351 | 0.0633 | 1.0 | 5.0 | moderate | analyzable_hypothesis |
| swept_recent_low | 50 | 0.48 | 0.9231 | -0.04 | -1.0 | -2.0 | moderate | analyzable_hypothesis |
| swept_recent_high | 44 | 0.6136 | 1.5882 | 0.2273 | 1.0 | 10.0 | moderate | analyzable_hypothesis |
| external_liquidity | 14 | 0.5714 | 1.3333 | 0.1429 | 1.0 | 2.0 | weak | directional_only |
| session_liquidity | 1 | 1.0 | inf | 1.0 | 1.0 | 1.0 | insufficient | insufficient_sample |

## A-priori Hypothesis

- VWAP_TOUCH_TOO_PERMISSIVE confermata: `true`
- MISSING_COOLDOWN confermata: `true`
- DUPLICATE_CONTEXT_ENTRIES confermata: `false`
- entrambe VWAP touch/cooldown confermate: `true`
- nessuna confermata: `false`

## Final Diagnosis

- primary verdict: `MISSING_COOLDOWN`
- secondary verdicts: `OVERTRADING_DIAGNOSTICS_COMPLETE, VWAP_TOUCH_TOO_PERMISSIVE, SIGMA_1_TOO_NOISY, TREND_FOLLOWING_TOO_FREQUENT, EDGE_NOT_DIAGNOSTICALLY_STABLE`
- next branch: `feat/strategy-3-add-cooldown`

## What Was Not Done

- no tuning
- no entry changes
- no filter changes
- no live
- no Telegram
- no full backtest
- no multi-symbol
- no multi-strategy

## Limits

- 5-day smoke only
- subset sizes are often weak or moderate, not validation-grade
- no OOS validation
- no live/deploy conclusion
