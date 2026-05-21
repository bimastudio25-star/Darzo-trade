# Strategy 3 Intermediate Validation

Status: research-only intermediate validation. This is not live validation, not deployment approval, and not a profitability claim.

## Config

- branch: `feat/strategy-3-intermediate-validation-run`
- base branch: `feat/strategy-3-limited-post-cooldown-run`
- base commit: `0de2751 Run Strategy 3 limited post-cooldown diagnostic`
- symbol: `XAUUSD`
- strategy: `strategy_3_vwap_1r`
- cooldown: `120m`
- requested range: `2026-03-15` to `2026-05-14`
- IS range: `2026-03-15` to `2026-04-24`
- OOS range: `2026-04-25` to `2026-05-14`
- output path: `backtests/reports/strategy_3_intermediate_validation`
- duration: `1891.31s`
- duration under 30 minutes: no

Command:

```powershell
$env:STRATEGY_3_COOLDOWN_MINUTES="120"; python backtest.py --symbol XAUUSD --from 2026-03-15 --to 2026-05-14 --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_3_intermediate_validation --strategies strategy_3_vwap_1r --fast --progress-every-candles 500
```

The environment variable was removed after the run.

## Scope Guardrails

- no tuning
- no new filters
- no entry rule changes
- no cooldown changes
- no VWAP filter changes
- no Strategy 2 changes
- no Adelin changes
- no Dynamic SL changes
- no simulator changes
- no `max_sim_bars` changes
- no Telegram live signals
- no live run
- no orders
- no multi-symbol run
- no multi-strategy run
- no full heavy 3-month run

## Full / IS / OOS Metrics

| Split | Date range | Trades | TP1 | SL | PF | WR | AvgR | MedianR | total_R | MaxDD | R/DD | trades/day |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Full | 2026-03-15 -> 2026-05-14 | 544 | 329 | 215 | 1.5302 | 60.48% | 0.2096 | 1.0 | 114.0 | 10.0 | 11.40 | 9.0667 |
| IS | 2026-03-15 -> 2026-04-24 | 369 | 217 | 152 | 1.4276 | 58.81% | 0.1762 | 1.0 | 65.0 | 10.0 | 6.50 | 9.0000 |
| OOS | 2026-04-25 -> 2026-05-14 | 175 | 112 | 63 | 1.7778 | 64.00% | 0.2800 | 1.0 | 49.0 | 5.0 | 9.80 | 8.7500 |

Outcome rates:

| Split | STILL_OPEN | TIMEOUT_CLOSE | END_OF_DATA_CLOSE | Longest loss streak |
|---|---:|---:|---:|---:|
| Full | 0.0% | 0.0% | 0.0% | 5 |
| IS | 0.0% | 0.0% | 0.0% | 5 |
| OOS | 0.0% | 0.0% | 0.0% | 5 |

## Cooldown Telemetry

- cooldown_enabled: `true`
- strategy_3_cooldown_minutes: `120`
- cooldown_accepted_count: `544`
- exported valid trades: `544`
- accepted/exported delta: `0`
- accepted/exported mismatch: `false`
- cooldown_blocked_count: `679`
- rejected reason `STRATEGY_3_COOLDOWN_BLOCKED`: `676`
- rejected reason `STRATEGY_3_COOLDOWN_BLOCKED;duplicate_signal_same_session_day`: `3`

Blocked by direction:

| direction | blocked |
|---|---:|
| LONG | 372 |
| SHORT | 307 |

Blocked by setup mode:

| setup_mode | blocked |
|---|---:|
| reversal | 349 |
| trend_following | 330 |

Blocked by band:

| band_touched | blocked |
|---|---:|
| sigma_1_upper | 190 |
| sigma_1_lower | 153 |
| vwap | 148 |
| sigma_2_lower | 103 |
| sigma_2_upper | 85 |

## Density

| Split | trades/day | max trades/day | max trades/hour | median gap |
|---|---:|---:|---:|---:|
| Full | 9.0667 | 17 | 2 | 120m |
| IS | 9.0000 | 17 | 2 | 120m |
| OOS | 8.7500 | 15 | 2 | 90m |

The density remains materially below the no-cooldown baseline and is stable across IS/OOS. The run exceeded the 30-minute time expectation by about 91 seconds, but completed successfully as a single-symbol, single-strategy, 60-day fast run.

## Statistical Floor

Category significance:

- `insufficient`: n < 10
- `weak`: 10 <= n < 30
- `moderate`: n >= 30
- `significant`: n >= 100

No edge is declared from any bucket. Buckets below 30 trades are directional diagnostics only.

## Setup Mode Breakdown

Full:

| setup_mode | trades | PF | WR | AvgR | total_R | MaxDD | R/DD | significance |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| reversal | 293 | 1.3629 | 57.68% | 0.1536 | 45.0 | 10.0 | 4.50 | significant |
| trend_following | 251 | 1.7582 | 63.75% | 0.2749 | 69.0 | 5.0 | 13.80 | significant |

IS:

| setup_mode | trades | PF | WR | AvgR | total_R | MaxDD | R/DD | significance |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| reversal | 205 | 1.3295 | 57.07% | 0.1415 | 29.0 | 10.0 | 2.90 | significant |
| trend_following | 164 | 1.5625 | 60.98% | 0.2195 | 36.0 | 5.0 | 7.20 | significant |

OOS:

| setup_mode | trades | PF | WR | AvgR | total_R | MaxDD | R/DD | significance |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| reversal | 88 | 1.4444 | 59.09% | 0.1818 | 16.0 | 4.0 | 4.00 | moderate |
| trend_following | 87 | 2.2222 | 68.97% | 0.3793 | 33.0 | 2.0 | 16.50 | moderate |

No `no_trade` leakage was observed.

## Direction Breakdown

Full:

| direction | trades | PF | WR | AvgR | total_R | MaxDD | R/DD | significance |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| LONG | 286 | 1.4034 | 58.39% | 0.1678 | 48.0 | 11.0 | 4.36 | significant |
| SHORT | 258 | 1.6875 | 62.79% | 0.2558 | 66.0 | 8.0 | 8.25 | significant |

IS:

| direction | trades | PF | WR | AvgR | total_R | MaxDD | R/DD | significance |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| LONG | 197 | 1.2907 | 56.35% | 0.1269 | 25.0 | 11.0 | 2.27 | significant |
| SHORT | 172 | 1.6061 | 61.63% | 0.2326 | 40.0 | 8.0 | 5.00 | significant |

OOS:

| direction | trades | PF | WR | AvgR | total_R | MaxDD | R/DD | significance |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| LONG | 89 | 1.6970 | 62.92% | 0.2584 | 23.0 | 5.0 | 4.60 | moderate |
| SHORT | 86 | 1.8667 | 65.12% | 0.3023 | 26.0 | 3.0 | 8.67 | moderate |

Directional asymmetry status: `not_returned`. LONG and SHORT are positive in Full, IS, and OOS; PF gaps remain below 0.5.

## Band Breakdown

Full:

| band_touched | trades | PF | WR | AvgR | total_R | MaxDD | R/DD | significance |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| sigma_1_lower | 123 | 1.1964 | 54.47% | 0.0894 | 11.0 | 7.0 | 1.57 | significant |
| sigma_1_upper | 129 | 1.5294 | 60.47% | 0.2093 | 27.0 | 9.0 | 3.00 | significant |
| sigma_2_lower | 80 | 1.3529 | 57.50% | 0.1500 | 12.0 | 8.0 | 1.50 | moderate |
| sigma_2_upper | 86 | 2.4400 | 70.93% | 0.4186 | 36.0 | 4.0 | 9.00 | moderate |
| vwap | 126 | 1.5714 | 61.11% | 0.2222 | 28.0 | 6.0 | 4.67 | significant |

IS:

| band_touched | trades | PF | WR | AvgR | total_R | MaxDD | R/DD | significance |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| sigma_1_lower | 83 | 1.0750 | 51.81% | 0.0361 | 3.0 | 7.0 | 0.43 | moderate |
| sigma_1_upper | 90 | 1.4324 | 58.89% | 0.1778 | 16.0 | 9.0 | 1.78 | moderate |
| sigma_2_lower | 52 | 1.2609 | 55.77% | 0.1154 | 6.0 | 8.0 | 0.75 | moderate |
| sigma_2_upper | 61 | 2.3889 | 70.49% | 0.4098 | 25.0 | 4.0 | 6.25 | moderate |
| vwap | 83 | 1.4412 | 59.04% | 0.1807 | 15.0 | 6.0 | 2.50 | moderate |

OOS:

| band_touched | trades | PF | WR | AvgR | total_R | MaxDD | R/DD | significance |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| sigma_1_lower | 40 | 1.5000 | 60.00% | 0.2000 | 8.0 | 4.0 | 2.00 | moderate |
| sigma_1_upper | 39 | 1.7857 | 64.10% | 0.2821 | 11.0 | 3.0 | 3.67 | moderate |
| sigma_2_lower | 28 | 1.5455 | 60.71% | 0.2143 | 6.0 | 2.0 | 3.00 | weak |
| sigma_2_upper | 25 | 2.5714 | 72.00% | 0.4400 | 11.0 | 2.0 | 5.50 | weak |
| vwap | 43 | 1.8667 | 65.12% | 0.3023 | 13.0 | 2.0 | 6.50 | moderate |

Sigma 1 lower status: `resolved_but_monitor`. It is positive in Full/IS/OOS and does not trigger the `PF < 0.8` fragility rule, but IS is thin at PF 1.075 and R/DD 0.43.

Band asymmetry status: `not_blocking`. No band with n >= 30 has PF < 0.8, and no single band explains all profit.

## Session Breakdown

Session is available in the exported trade telemetry. The weakest notable cell is New York in IS: 62 trades, PF 0.9375, AvgR -0.0323, total_R -2. This is a diagnostic observation only; no session filter was added.

Full notable sessions:

| session | trades | PF | AvgR | total_R | significance |
|---|---:|---:|---:|---:|---|
| London/New York overlap | 118 | 1.3137 | 0.1186 | 14.0 | significant |
| Sydney+Tokyo | 120 | 1.3077 | 0.1167 | 14.0 | significant |
| Sydney | 54 | 2.1765 | 0.3704 | 20.0 | moderate |
| Tokyo+London | 53 | 2.3125 | 0.3962 | 21.0 | moderate |
| New York | 89 | 1.2821 | 0.1236 | 11.0 | moderate |

## Reason Codes

The most common reason codes are structural and non-discriminating because they appear on every emitted trade:

| reason_code | count | PF | AvgR | total_R | significance |
|---|---:|---:|---:|---:|---|
| liquidity_sweep | 544 | 1.5302 | 0.2096 | 114.0 | significant |
| number_theory_context | 544 | 1.5302 | 0.2096 | 114.0 | significant |
| target_1r | 544 | 1.5302 | 0.2096 | 114.0 | significant |
| setup_reversal | 293 | 1.3629 | 0.1536 | 45.0 | significant |
| setup_trend_following | 251 | 1.7582 | 0.2749 | 69.0 | significant |
| vwap_band_sigma_1_upper | 129 | 1.5294 | 0.2093 | 27.0 | significant |
| vwap_band_vwap | 126 | 1.5714 | 0.2222 | 28.0 | significant |
| vwap_band_sigma_1_lower | 123 | 1.1964 | 0.0894 | 11.0 | significant |
| vwap_band_sigma_2_upper | 86 | 2.4400 | 0.4186 | 36.0 | moderate |
| vwap_band_sigma_2_lower | 80 | 1.3529 | 0.1500 | 12.0 | moderate |
| fvg_ifvg_context | 39 | 1.7857 | 0.2821 | 11.0 | moderate |
| volume_crack_context | 19 | 3.7500 | 0.5789 | 11.0 | weak |

No reason-code subset is promoted to an entry filter in this branch.

## PF Degradation

Reference limited 20d:

- PF_limited_20d: `1.7143`
- MaxDD_limited_20d: `5R`

Intermediate:

- PF_full_60d: `1.5302`
- PF_IS: `1.4276`
- PF_OOS: `1.7778`

Classification: `normal_regression_still_interesting`. The Full PF regressed from 1.7143 to 1.5302 as sample increased, which is expected. IS and OOS both remain above 1.40, which qualifies as a strong intermediate research signal under the predefined table.

## Drawdown Scaling

- limited MaxDD: `5R`
- intermediate Full MaxDD: `10R`
- IS MaxDD: `10R`
- OOS MaxDD: `5R`
- Full total_R / MaxDD: `11.40`
- IS total_R / MaxDD: `6.50`
- OOS total_R / MaxDD: `9.80`

Scaling verdict: `normal`. MaxDD doubled while the sample expanded from 171 to 544 trades and stayed below the 15R normal-scaling threshold.

## Robustness Checks

- IS/OOS consistency: positive in both splits.
- PF consistency: IS 1.4276, OOS 1.7778.
- AvgR consistency: IS 0.1762, OOS 0.2800.
- total_R consistency: IS +65R, OOS +49R.
- Direction consistency: LONG and SHORT positive in both splits.
- Setup consistency: trend_following and reversal positive in both splits.
- Band consistency: all bands positive in Full/IS/OOS where sample is at least weak; sigma_1_lower is the weakest but not a blocker.
- Density stability: trades/day remains near 9 and max trades/hour remains 2.
- Simulator policy: no STILL_OPEN, TIMEOUT_CLOSE, or END_OF_DATA_CLOSE regression.

## Comparison vs Limited 20d

| Window | Trades | PF | WR | AvgR | total_R | MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| Limited 20d 2026-04-25 -> 2026-05-14 | 171 | 1.7143 | 63.16% | 0.2632 | 45.0 | 5.0 |
| Intermediate 60d 2026-03-15 -> 2026-05-14 | 544 | 1.5302 | 60.48% | 0.2096 | 114.0 | 10.0 |
| IS 2026-03-15 -> 2026-04-24 | 369 | 1.4276 | 58.81% | 0.1762 | 65.0 | 10.0 |
| OOS 2026-04-25 -> 2026-05-14 | 175 | 1.7778 | 64.00% | 0.2800 | 49.0 | 5.0 |

OOS includes the previously positive limited window, so it is not a pure unseen OOS validation. The useful result is that the earlier IS window does not destroy the strategy and remains positive.

## Anomaly Detection

- trade_count < 200: false
- trade_count > 900: false
- runtime > 30 minutes: true, completed at 1891.31s instead of aborting
- high STILL_OPEN: false
- accepted/exported mismatch: false
- cooldown telemetry missing: false

Runtime note: this should be monitored before expanding beyond 60 days. This run was still single-symbol, single-strategy, 60-day, fast mode.

## Survivorship / Validation Caveat

Even with `STRATEGY_3_INTERMEDIATE_STRONG_SIGNAL`, this is not validated edge and not live approval.

This run covers 60 days of XAUUSD only and likely captures only a few market regimes. It does not prove behavior across:

- high-impact news volatility
- NFP
- FOMC
- CPI
- geopolitical shock windows
- prolonged consolidation
- multi-day strong trends
- realistic spread/slippage stress
- live feed differences
- real-time latency

Next validation must be research/paper only. Possible next steps:

1. `feat/strategy-3-oos-forward-validation`
   Paper trading real-time / forward test, no real orders.
2. `feat/strategy-3-stress-test-historical`
   Historical stress windows if suitable data exists.
3. Paper Telegram signal wiring only after explicit approval, with no broker execution.

Do not call this production-ready, live-ready, deployable, or validated for real trading.

## Verdict

- `INTERMEDIATE_VALIDATION_COMPLETE`: true
- `MECHANICS_STABLE_INTERMEDIATE`: true
- `STRATEGY_3_INTERMEDIATE_STRONG_SIGNAL`: true, research-only
- `STRATEGY_3_INTERMEDIATE_PROMISING`: true, implied by stronger signal
- `STRATEGY_3_INTERMEDIATE_WEAK_DEGRADATION`: false
- `STRATEGY_3_REGIME_DEPENDENT`: false
- `STRATEGY_3_WEAK_INTERMEDIATE`: false
- `STRATEGY_3_INCONCLUSIVE_INTERMEDIATE`: false
- `BAND_ASYMMETRY_RETURNS`: false
- `DIRECTIONAL_ASYMMETRY_RETURNS`: false
- `SETUP_MODE_ASYMMETRY`: false
- `STRATEGY_3_DRAWDOWN_WARNING`: false
- `STRATEGY_3_DRAWDOWN_EXPLODED_ON_LARGER_SAMPLE`: false
- `ACCEPTED_EXPORTED_COUNT_MISMATCH_NEEDS_REVIEW`: false
- `STILL_OPEN_POLICY_REGRESSION_SUSPECTED`: false

Recommended next branch: `feat/strategy-3-oos-forward-validation`.

This next branch should be paper/forward validation only:

- no real orders
- no live deployment
- no broker execution
- no claim of validated edge
- compare paper signals against realized outcomes
