# Strategy 3 OOS Forward Validation

Status: research/paper validation only. Strategy 3 remains non-deployable live.

## Metadata

- branch: `feat/strategy-3-oos-forward-validation`
- base branch: `feat/strategy-3-intermediate-validation-run`
- base commit: `75de3a5 Run Strategy 3 intermediate validation`
- current commit: pending at report creation
- date created: `2026-05-18`
- symbol: `XAUUSD`
- strategy: `strategy_3_vwap_1r`
- cooldown: `120m`
- mode: fast/report-only backtest
- safety status: no live, no Telegram live signals, no orders

## Repository Audit

- initial branch: `feat/strategy-3-intermediate-validation-run`
- initial commit: `75de3a5 Run Strategy 3 intermediate validation`
- initial status: clean
- base branch aligned with origin: yes
- validation branch created: `feat/strategy-3-oos-forward-validation`

## Data Availability Audit

The local XAUUSD CSV files are UTF-16 encoded and use the first column as timestamp. Intraday files use `yyyy.MM.dd HH:mm`; `D1.csv` uses `yyyy.MM.dd`.

| TF | path | exists | rows | first timestamp | last timestamp | rows after 2026-05-14 | rows before 2026-01-29 |
|---|---|---:|---:|---|---|---:|---:|
| M1 | `data/XAUUSD/M1.csv` | true | 100000 | 2026-01-29 16:19 | 2026-05-14 22:59 | 0 | 0 |
| M5 | `data/XAUUSD/M5.csv` | true | 100000 | 2024-12-09 22:55 | 2026-05-14 22:55 | 0 | 79813 |
| M15 | `data/XAUUSD/M15.csv` | true | 47125 | 2024-05-14 01:00 | 2026-05-14 22:45 | 0 | 40394 |
| H1 | `data/XAUUSD/H1.csv` | true | 7059 | 2025-03-03 01:00 | 2026-05-14 22:00 | 0 | 5374 |
| H4 | `data/XAUUSD/H4.csv` | true | 1857 | 2025-03-03 00:00 | 2026-05-14 20:00 | 0 | 1407 |
| D1 | `data/XAUUSD/D1.csv` | true | 310 | 2025-03-03 | 2026-05-14 | 0 | 235 |

- latest common available date across all required TFs: `2026-05-14`
- earliest common usable full day across all required TFs: `2026-01-30`
- forward validation possible after `2026-05-14`: no
- pure pre-`2026-01-29` past-OOS possible across all TFs: no, because M1 starts at `2026-01-29 16:19`
- fallback pre-intermediate past-OOS possible: yes, `2026-01-30 -> 2026-03-14`

## Forward Validation

Forward validation was not run.

- requested forward start: `2026-05-15`
- latest common available date: `2026-05-14`
- exact reason: no complete forward day exists after `2026-05-14` across `M1,M5,M15,H1,H4,D1`
- verdict: `STRATEGY_3_FORWARD_DATA_NOT_AVAILABLE`

No forward results were faked. No partial-data forward sample was reported.

## Plan B: Historical Past-OOS Stress Test

Because forward data was unavailable, a fallback historical past-OOS stress test was run on the earliest clean common window before the intermediate validation period.

- date range: `2026-01-30 -> 2026-03-14`
- relationship to intermediate validation: fully before `2026-03-15 -> 2026-05-14`
- output path: `backtests/reports/strategy_3_past_oos_validation`
- runtime: `1367.59s`
- cooldown: `120m`

Command:

```powershell
$env:STRATEGY_3_COOLDOWN_MINUTES="120"; python backtest.py --symbol XAUUSD --from 2026-01-30 --to 2026-03-14 --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_3_past_oos_validation --strategies strategy_3_vwap_1r --fast --progress-every-candles 500
```

The environment variable was removed after the run.

### Metrics

| metric | value |
|---|---:|
| total trades | 379 |
| TP1 | 197 |
| SL | 182 |
| PF | 1.0824 |
| WR | 51.98% |
| AvgR | 0.0396 |
| MedianR | 1.0 |
| total_R | +15.0 |
| MaxDD | 17.0 |
| R/DD | 0.8824 |
| STILL_OPEN | 0 |
| TIMEOUT_CLOSE | 0 |
| END_OF_DATA_CLOSE | 0 |
| still_open_rate | 0.0 |
| timeout_close_rate | 0.0 |
| end_of_data_close_rate | 0.0 |

### Cooldown Telemetry

- cooldown_enabled: `true`
- strategy_3_cooldown_minutes: `120`
- cooldown_accepted_count: `379`
- exported valid trades: `379`
- accepted/exported delta: `0`
- cooldown_blocked_count: `490`

Blocked by direction:

| direction | blocked |
|---|---:|
| LONG | 257 |
| SHORT | 233 |

Blocked by setup mode:

| setup_mode | blocked |
|---|---:|
| trend_following | 264 |
| reversal | 226 |

Blocked by band:

| band_touched | blocked |
|---|---:|
| sigma_1_upper | 144 |
| vwap | 120 |
| sigma_1_lower | 111 |
| sigma_2_upper | 60 |
| sigma_2_lower | 55 |

### Density

- calendar days: `44`
- active days: `43`
- trades/day calendar: `8.6136`
- trades/day active: `8.8140`
- max trades/day: `17`
- max trades/hour: `2`
- median gap: `105m`
- average gap: `162.26m`

### Setup Breakdown

| setup_mode | trades | TP1 | SL | PF | WR | AvgR | total_R | MaxDD | significance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| reversal | 213 | 102 | 111 | 0.9189 | 47.89% | -0.0423 | -9.0 | 26.0 | significant |
| trend_following | 166 | 95 | 71 | 1.3380 | 57.23% | 0.1446 | 24.0 | 7.0 | significant |

### Direction Breakdown

| direction | trades | TP1 | SL | PF | WR | AvgR | total_R | MaxDD | significance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| SHORT | 190 | 100 | 90 | 1.1111 | 52.63% | 0.0526 | 10.0 | 14.0 | significant |
| LONG | 189 | 97 | 92 | 1.0543 | 51.32% | 0.0265 | 5.0 | 11.0 | significant |

### Band Breakdown

| band_touched | trades | TP1 | SL | PF | WR | AvgR | total_R | MaxDD | significance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| vwap | 97 | 60 | 37 | 1.6216 | 61.86% | 0.2371 | 23.0 | 4.0 | moderate |
| sigma_1_upper | 89 | 45 | 44 | 1.0227 | 50.56% | 0.0112 | 1.0 | 7.0 | moderate |
| sigma_1_lower | 68 | 29 | 39 | 0.7436 | 42.65% | -0.1471 | -10.0 | 12.0 | moderate |
| sigma_2_upper | 67 | 34 | 33 | 1.0303 | 50.75% | 0.0149 | 1.0 | 10.0 | moderate |
| sigma_2_lower | 58 | 29 | 29 | 1.0000 | 50.00% | 0.0000 | 0.0 | 10.0 | moderate |

### Past-OOS Verdict

- sample >= 20: yes
- PF > 1.05: yes, but barely
- AvgR >= 0: yes, barely
- total_R >= 0: yes
- STILL_OPEN regression: no
- accepted/exported mismatch: no
- drawdown note: MaxDD `17R` versus total_R `15R`, weak reward/drawdown

Verdict flag: `STRATEGY_3_PAST_OOS_VALIDATION_POSITIVE`, with weak/regime caveat.

Interpretation: this past-OOS stress test does not collapse, but it is much weaker than the `2026-03-15 -> 2026-05-14` intermediate validation. The result increases confidence that Strategy 3 is not purely isolated to one window, but it also shows regime sensitivity, especially reversal and sigma_1_lower fragility.

## Comparison vs Intermediate OOS

| Window | Trades | PF | WR | AvgR | total_R | MaxDD | R/DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| Intermediate OOS 2026-04-25 -> 2026-05-14 | 175 | 1.7778 | 64.00% | 0.2800 | 49.0 | 5.0 | 9.80 |
| Past-OOS 2026-01-30 -> 2026-03-14 | 379 | 1.0824 | 51.98% | 0.0396 | 15.0 | 17.0 | 0.88 |

The past-OOS window is positive but materially weaker. This is not a failure of mechanics; it is a regime/stress warning and should prevent any live-deploy interpretation.

## Auto-Rerun Script

Path: `scripts/run_strategy_3_forward_validation.ps1`

What it does:

- reads latest timestamps from `data/XAUUSD/M1.csv`, `M5.csv`, `M15.csv`, `H1.csv`, `H4.csv`, and `D1.csv`
- chooses the minimum latest common date
- exits without running if latest common date is not after `2026-05-14`
- sets `STRATEGY_3_COOLDOWN_MINUTES=120`
- runs `backtest.py` from `2026-05-15` to the latest common date
- uses `strategy_3_vwap_1r` only
- uses `XAUUSD` only
- clears `STRATEGY_3_COOLDOWN_MINUTES` after execution

Safety guarantees:

- no live flags
- no Telegram flags
- no broker/order flags
- no multi-symbol
- no multi-strategy

Dry run on current data exits with:

`STRATEGY_3_FORWARD_DATA_NOT_AVAILABLE: latest common date is not after 2026-05-14. No backtest run.`

## Decision Matrix

| Outcome | Next branch |
|---|---|
| STRATEGY_3_FORWARD_DATA_NOT_AVAILABLE + STRATEGY_3_PAST_OOS_VALIDATION_POSITIVE | feat/strategy-3-paper-shadow-scanner |
| STRATEGY_3_FORWARD_DATA_NOT_AVAILABLE + STRATEGY_3_PAST_OOS_VALIDATION_WEAK | feat/strategy-3-regime-stress-test |
| STRATEGY_3_FORWARD_DATA_NOT_AVAILABLE + Plan B not possible | Wait for new data; infrastructure ready |
| FORWARD_VALIDATION_POSITIVE_EARLY with sample >= 20 | feat/strategy-3-paper-shadow-scanner |
| FORWARD_VALIDATION_WEAK_OR_REGIME_DEPENDENT | feat/strategy-3-regime-diagnostics |
| FORWARD_SAMPLE_TOO_SMALL with sample < 20 | Continue forward observation until 20+ trades |

Applied decision: `feat/strategy-3-paper-shadow-scanner`, but paper-only. The past-OOS result is positive by threshold, yet weak enough that the paper-shadow branch should include explicit regime and band diagnostics, not live execution.

## Final Verdict Flags

Forward:

- `STRATEGY_3_FORWARD_DATA_NOT_AVAILABLE`
- `FRAMEWORK_READY`
- `NO_VALIDATION_PERFORMED`

Past-OOS:

- `STRATEGY_3_PAST_OOS_VALIDATION_POSITIVE`

Warnings:

- `PAST_OOS_WEAK_REGIME_CAVEAT`
- `SIGMA_1_LOWER_FRAGILITY_RETURNS_IN_PAST_OOS`
- `REVERSAL_WEAK_IN_PAST_OOS`

Not triggered:

- `FORWARD_SAMPLE_TOO_SMALL`
- `MECHANICS_CHECK_ONLY`
- `FORWARD_VALIDATION_POSITIVE_EARLY`
- `STRATEGY_3_REMAINS_PROMISING_PAPER_ONLY`
- `FORWARD_VALIDATION_WEAK_OR_REGIME_DEPENDENT`
- `STILL_OPEN_REGRESSION_REVIEW_REQUIRED`
- `COOLDOWN_EXPORT_MISMATCH_REVIEW_REQUIRED`
- `DRAWDOWN_WARNING`
- `STRATEGY_3_PAST_OOS_VALIDATION_WEAK`
- `STRATEGY_3_PAST_OOS_VALIDATION_INCONCLUSIVE`
- `STRATEGY_3_PAST_OOS_DATA_NOT_AVAILABLE`

## Non-Deployment Statement

Strategy 3 remains research/paper-only. No real orders, no live deployment, and no Telegram live signal deployment were enabled in this branch.

The next useful branch is `feat/strategy-3-paper-shadow-scanner`, not live trading. That branch should monitor paper signals only, compare real-time/paper observations against backtest expectations, and collect spread/slippage diagnostics without broker execution.
