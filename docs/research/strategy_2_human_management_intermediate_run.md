# Strategy 2 Human-Management Intermediate Diagnostic

Status: research-only diagnostic. No live trading, no Telegram trade alerts, no broker execution, no parameter optimization.

## Run Context

- branch: `feat/strategy-2-human-management-intermediate-run`
- source base commit: `4cfc670 Add human-style trade management M5 AI logger`
- symbol: `XAUUSD`
- strategy: `strategy_2_0` / `strategy_2_liquidity_expansion`
- timeframe set: `M1,M5,M15,H1,H4,D1`
- window: `2026-03-15` to `2026-05-14`
- sample-size policy:
  - `n < 10`: insufficient, do not interpret; no conclusions
  - `10 <= n < 30`: weak, show metrics but no conclusions
  - `30 <= n < 100`: moderate, interpretable but not validated
  - `n >= 100`: significant, stronger but still not live validation

Backtest command:

```bash
python backtest.py --symbol XAUUSD --from 2026-03-15 --to 2026-05-14 --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_2_human_management_intermediate --strategies strategy_2_0 --fast --progress-every-candles 200
```

Overlay command:

```bash
python scripts/analyze_human_trade_management_overlay.py --symbol XAUUSD --data-dir data --trades-path backtests/reports/strategy_2_human_management_intermediate/executed_trades.csv --output-dir backtests/reports/strategy_2_human_management_overlay_intermediate --be-trigger-usd 10 --partial-triggers-usd 15,20 --partial-fraction 0.50 --dry-run
```

Output paths:

- backtest: `backtests/reports/strategy_2_human_management_intermediate`
- overlay: `backtests/reports/strategy_2_human_management_overlay_intermediate`
- real executed trades: `backtests/reports/strategy_2_human_management_intermediate/executed_trades.csv`

## Safety Confirmation

- live trading enabled: `false`
- Telegram enabled/sent: `false`
- broker execution/order sending: `false`
- `order_send` called: `false`
- Strategy 2 entry logic changed: `false`
- Strategy 3 VWAP/cooldown/paper pipeline changed: `false`
- Adelin logic changed: `false`
- local AI judge: disabled by default; report-only when enabled

## Real Trade Export

The real trade export exists and contains `57` executed Strategy 2 trades. The export fields include:

`timestamp`, `symbol`, `strategy`, `direction`, `entry`, `stop`, `sl_distance`, `tp1`, `tp2`, `tp3`, `tp4`, `session`, `outcome`, `exit_time`, `exit_price`, `r_multiple`, `mae`, `mfe`, `bars_held`.

Overlay path availability:

- M1 path rows available for all overlay rows: yes
- M5 context rows available for all overlay rows: yes
- synthetic examples used: `false`
- local AI calls: disabled

## Baseline Strategy 2 Metrics

Authoritative baseline comes from the real backtest export and `summary.json`.

| metric | value |
|---|---:|
| trades | 57 |
| statistical label | moderate |
| PF | 0.8376 |
| WR | 0.4386 |
| AvgR | -0.0425 |
| MedianR | 0.0 |
| total_R | -2.4232 |
| MaxDD | 6.6376 |
| average win R | 0.4998 |
| average loss R | -0.6487 |
| average RR | 0.7705 |
| STILL_OPEN rate | 0.0 |
| TIMEOUT_CLOSE rate | 0.386 |
| END_OF_DATA_CLOSE rate | 0.0 |

Outcome distribution:

| outcome | count | rate |
|---|---:|---:|
| TP2 | 13 | 22.81% |
| SL | 13 | 22.81% |
| BE | 9 | 15.79% |
| TIMEOUT_CLOSE | 22 | 38.60% |
| END_OF_DATA_CLOSE | 0 | 0.00% |
| STILL_OPEN | 0 | 0.00% |

Prior limited 20-day comparison:

- prior approximate: 19 trades, PF about 0.82, AvgR about -0.05, total about -0.96R
- current 60-day: 57 trades, PF 0.8376, AvgR -0.0425, total -2.4232R
- interpretation: the 60-day run is similar to the limited run, so Strategy 2 weakness appears to persist. There is no clear regime-improvement explanation from this intermediate sample.

## Human-Management Overlay Variants

Baseline in the overlay is anchored to the real exported `r_multiple`. Other variants are research-only replay overlays on the same trades.

| variant | trades | label | PF | WR | AvgR | MedianR | total_R | MaxDD | BE hit rate | BE stopout rate | partial hit rate | runner opps | runner hit rate |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 57 | moderate | 0.8376 | 0.4386 | -0.0425 | 0.0 | -2.4232 | 6.6376 | 0.7193 | 0.1579 | 0.7018 | 0 | n/a |
| hard BE +10 | 57 | moderate | 0.64 | 0.2982 | -0.061 | 0.0 | -3.476 | 4.969 | 0.7193 | 0.4386 | 0.7018 | 0 | n/a |
| M5-confirmed BE +10 | 57 | moderate | 0.64 | 0.2982 | -0.061 | 0.0 | -3.476 | 4.969 | 0.7193 | 0.4386 | 0.7018 | 0 | n/a |
| structural BE | 57 | moderate | 0.64 | 0.2982 | -0.061 | 0.0 | -3.476 | 4.969 | 0.7193 | 0.4386 | 0.7018 | 0 | n/a |
| partial +15 | 57 | moderate | 0.7009 | 0.5088 | -0.0507 | 0.0044 | -2.8882 | 4.7059 | 0.7193 | 0.2281 | 0.7018 | 0 | n/a |
| partial +20 | 57 | moderate | 0.6382 | 0.3684 | -0.0613 | 0.0 | -3.4933 | 4.8374 | 0.7193 | 0.3684 | 0.6316 | 0 | n/a |
| exit bad M5 | 57 | moderate | 0.814 | 0.4912 | -0.0265 | 0.0 | -1.5119 | 4.0438 | 0.7193 | 0.2281 | 0.7018 | 0 | n/a |
| hold healthy retest | 57 | moderate | 0.7603 | 0.5263 | -0.0406 | 0.0538 | -2.3146 | 4.26 | 0.7193 | 0.2105 | 0.7018 | 0 | n/a |
| runner liquidity | 57 | moderate | 0.7009 | 0.5088 | -0.0507 | 0.0044 | -2.8882 | 4.7059 | 0.7193 | 0.2281 | 0.7018 | 0 | n/a |

## Variant Comparison

| comparison | PF delta | total_R delta | interpretation |
|---|---:|---:|---|
| baseline vs hard BE +10 | -0.1976 | -1.0528 | not improved; hard BE appears too early in this overlay |
| baseline vs M5-confirmed BE +10 | -0.1976 | -1.0528 | same as hard BE; likely fallback/data-limitation artifact |
| baseline vs structural BE | -0.1976 | -1.0528 | same as hard BE; no protected structure levels were supplied |
| baseline vs partial +15 | -0.1367 | -0.4650 | not improved |
| baseline vs partial +20 | -0.1994 | -1.0701 | not improved |
| baseline vs exit bad M5 | -0.0236 | +0.9113 | smaller loss and lower MaxDD, but PF remains below baseline and below 1.0 |
| baseline vs hold healthy retest | -0.0773 | +0.1086 | slight total_R improvement, PF weaker than baseline |
| baseline vs runner liquidity | -0.1367 | -0.4650 | not a real runner test; no dynamic liquidity targets were supplied |

No overlay variant reaches PF >= 1.1 with sample >= 30. The management layer does not fix Strategy 2 in this intermediate run.

## Hourly Diagnostics

Every hourly bucket has `n < 10`, so every hour is statistically insufficient. Metrics are shown only for audit.

| hour | trades | label | PF | WR | AvgR | total_R | MaxDD |
|---|---:|---|---:|---:|---:|---:|---:|
| 01:00 | 8 | insufficient | 0.277 | 0.5 | -0.3615 | -2.8921 | 3.0 |
| 02:00 | 4 | insufficient | 0.3744 | 0.25 | -0.3491 | -1.3964 | 1.3964 |
| 03:00 | 1 | insufficient | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 04:00 | 5 | insufficient | 0.6063 | 0.4 | -0.0878 | -0.4389 | 1.0854 |
| 05:00 | 3 | insufficient | 2.802 | 0.3333 | 0.1271 | 0.3813 | 0.2116 |
| 08:00 | 4 | insufficient | 1.7454 | 0.75 | 0.1864 | 0.7454 | 1.0 |
| 11:00 | 1 | insufficient | inf | 1.0 | 0.0881 | 0.0881 | 0.0 |
| 12:00 | 1 | insufficient | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 13:00 | 1 | insufficient | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 14:00 | 3 | insufficient | 0.0464 | 0.3333 | -0.4499 | -1.3496 | 1.4152 |
| 15:00 | 4 | insufficient | 0.8357 | 0.25 | -0.0411 | -0.1643 | 1.0 |
| 16:00 | 5 | insufficient | 0.9826 | 0.2 | -0.0039 | -0.0197 | 1.1311 |
| 17:00 | 5 | insufficient | inf | 0.8 | 0.5295 | 2.6475 | 0.0 |
| 18:00 | 3 | insufficient | 5.9263 | 0.6667 | 0.234 | 0.702 | 0.1425 |
| 19:00 | 2 | insufficient | 6.684 | 0.5 | 0.4101 | 0.8202 | 0.1443 |
| 20:00 | 2 | insufficient | 0.8564 | 0.5 | -0.0295 | -0.059 | 0.4108 |
| 21:00 | 3 | insufficient | 0.4975 | 0.3333 | -0.187 | -0.5611 | 1.0 |
| 22:00 | 2 | insufficient | 0.0734 | 0.5 | -0.4633 | -0.9266 | 1.0 |

No hourly bucket has enough trades to support the 14:00-16:00 hypothesis or any hour-specific filter.

## Session Diagnostics

| session | trades | label | PF | WR | AvgR | total_R | MaxDD |
|---|---:|---|---:|---:|---:|---:|---:|
| Asia | 21 | weak | 0.425 | 0.381 | -0.207 | -4.3461 | 4.3461 |
| London | 6 | insufficient | 1.8335 | 0.6667 | 0.1389 | 0.8335 | 1.0 |
| NewYork | 25 | weak | 1.6072 | 0.44 | 0.1031 | 2.5771 | 2.1396 |
| LateUS | 5 | insufficient | 0.2972 | 0.4 | -0.2975 | -1.4877 | 2.0 |

The New York session is an interesting observation only, not statistically interpretable under the mandatory floor because `n = 25 < 30`.

## Dedicated 14:00-16:00 Analysis

| scope | trades | label | PF | WR | AvgR | MedianR | total_R | MaxDD |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| full day | 57 | moderate | 0.8376 | 0.4386 | -0.0425 | 0.0 | -2.4232 | 6.6376 |
| 14:00-16:00 | 7 | insufficient | 0.3732 | 0.2857 | -0.2163 | 0.0 | -1.5139 | 1.5139 |

Verdict for this window: `SESSION_HYPOTHESIS_INCONCLUSIVE_SAMPLE_TOO_SMALL`.

The 14:00-16:00 bucket has only 7 trades and is weaker than full day in this run. It must not be treated as supported.

## Red Flags And Limitations

- `TIMEOUT_CLOSE` rate is 38.60%, close to the 40% review threshold but below the exact `MAX_SIM_BARS_REVIEW_NEEDED` rule.
- `STILL_OPEN` rate is 0.00%; no still-open policy regression was detected.
- Hard BE, M5-confirmed BE, and structural BE are identical in this run, which suggests overlay data limitations: no structural protected levels were supplied and M5-confirmed BE collapsed to the same effective behavior.
- Runner liquidity produced zero runner opportunities because no dynamic liquidity target context was supplied to the overlay. The runner variant is therefore not a historical liquidity-run test yet.
- Hourly buckets are all insufficient.
- Session buckets are weak or insufficient.
- The 14:00-16:00 bucket is insufficient and negative.
- The overlay is a research replay on exported trades, not a strategy-entry change and not a live execution model.

## Verdict Flags

- `STRATEGY_2_WEAK_NOT_FIXED_BY_MANAGEMENT`
- `SESSION_HYPOTHESIS_INCONCLUSIVE_SAMPLE_TOO_SMALL`
- `STRATEGY_2_REMAINS_RESEARCH_ONLY`
- `NO_LIVE_DEPLOYMENT_DECISION`

Not triggered:

- `REAL_TRADE_EXPORT_MISSING`
- `NO_HISTORICAL_OVERLAY_EVIDENCE`
- `INTERMEDIATE_INCONCLUSIVE_INSUFFICIENT_SAMPLE`
- `STILL_OPEN_POLICY_REGRESSION`
- `MAX_SIM_BARS_REVIEW_NEEDED`
- `HUMAN_MANAGEMENT_OVERLAY_PROMISING_BUT_SAMPLE_MODERATE`
- `SESSION_HYPOTHESIS_SUPPORTED_NEEDS_LARGER_SAMPLE`

## Next Step

Recommended next step: improve the overlay input richness before a larger run by exporting/providing dynamic liquidity targets, protected structure levels, and explicit M5 management event outcomes. Then run a controlled intermediate follow-up before considering the separate full 3-month diagnostic branch.
