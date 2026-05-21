# Strategy 3 Limited Post-cooldown Diagnostic

Status: limited research/backtest diagnostic only. This is not live validation, not strategy optimization, and not a deployability claim.

## Config

- branch: `feat/strategy-3-limited-post-cooldown-run`
- base branch: `feat/strategy-3-add-cooldown`
- base commit: `447a2a2 Add Strategy 3 cooldown`
- symbol: `XAUUSD`
- strategy: `strategy_3_vwap_1r`
- cooldown: `120m`
- requested range: `2026-04-25` to `2026-05-14`
- effective first/last Strategy 3 evaluation: `2026-04-27T01:00:00+00:00` to `2026-05-13T22:45:00+00:00`
- output path: `backtests/reports/strategy_3_vwap_1r_limited_post_cooldown`
- duration: `586.84s`
- duration under 10 minutes: yes

Command:

```powershell
$env:STRATEGY_3_COOLDOWN_MINUTES="120"; python backtest.py --symbol XAUUSD --from 2026-04-25 --to 2026-05-14 --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_3_vwap_1r_limited_post_cooldown --strategies strategy_3_vwap_1r --fast --progress-every-candles 200
```

The environment variable was removed after the run.

## Outcome Distribution

| outcome | count |
|---|---:|
| TP1 | 108 |
| SL | 63 |
| BE | 0 |
| TIMEOUT_CLOSE | 0 |
| END_OF_DATA_CLOSE | 0 |
| STILL_OPEN | 0 |

## Metrics

- total signals: `400`
- valid trades: `171`
- rejected signals: `229`
- win rate: `63.16%`
- profit factor: `1.7143`
- average R: `0.2632`
- median R: `1.0`
- total R: `45.0`
- max drawdown R: `5.0`
- still_open_rate: `0.0`
- timeout_close_rate: `0.0`
- end_of_data_close_rate: `0.0`

This is a stronger limited sample than the 5-day smoke, but it is still not edge validation. It is single-symbol, single-strategy, same broad regime, and not OOS.

## Cooldown Telemetry

- cooldown_enabled: `true`
- strategy_3_cooldown_minutes: `120`
- cooldown_accepted_count: `172`
- cooldown_blocked_count: `228`
- exported valid trades: `171`
- rejected reason `STRATEGY_3_COOLDOWN_BLOCKED`: `228`
- rejected reason `duplicate_signal_same_session_day`: `1`

Blocked by direction:

| direction | blocked |
|---|---:|
| LONG | 117 |
| SHORT | 111 |

Blocked by setup mode:

| setup_mode | blocked |
|---|---:|
| trend_following | 114 |
| reversal | 114 |

Blocked by band:

| band_touched | blocked |
|---|---:|
| sigma_1_upper | 70 |
| vwap | 50 |
| sigma_1_lower | 47 |
| sigma_2_lower | 33 |
| sigma_2_upper | 28 |

## Density

- requested calendar days: `20`
- observed trade window: `17.7812` days
- trades/day, calendar: `8.55`
- trades/day, observed: `9.6169`
- max trades/day: `14`
- max trades/hour: `2`
- average gap: `142.1471m`
- median gap: `97.5m`
- min gap: `15m`
- max gap: `3105m`

Compared with the no-cooldown baseline density, overtrading remains materially reduced. Compared with the 5-day cooldown smoke, the density is slightly higher by calendar day but still mechanically controlled.

## Statistical Floor

- `n < 10`: insufficient
- `10 <= n < 30`: weak
- `30 <= n < 100`: moderate
- `n >= 100`: significant

No bucket-level edge is considered validated. Buckets below 30 trades are directional only.

## Setup Mode Breakdown

| setup_mode | trades | PF | WR | AvgR | total_R | category_significance |
|---|---:|---:|---:|---:|---:|---|
| reversal | 87 | 1.4857 | 59.77% | 0.1954 | 17.0 | moderate |
| trend_following | 84 | 2.0 | 66.67% | 0.3333 | 28.0 | moderate |

No executed trade had `setup_mode = no_trade`.

## Direction Breakdown

| direction | trades | PF | WR | AvgR | total_R | category_significance |
|---|---:|---:|---:|---:|---:|---|
| LONG | 85 | 1.6562 | 62.35% | 0.2471 | 21.0 | moderate |
| SHORT | 86 | 1.7742 | 63.95% | 0.2791 | 24.0 | moderate |

Directional asymmetry did not persist in this limited run. LONG and SHORT were both positive and similar.

## Band Breakdown

| band_touched | trades | PF | WR | AvgR | total_R | category_significance |
|---|---:|---:|---:|---:|---:|---|
| vwap | 40 | 1.5 | 60.00% | 0.2 | 8.0 | moderate |
| sigma_1_upper | 39 | 2.0 | 66.67% | 0.3333 | 13.0 | moderate |
| sigma_1_lower | 41 | 1.4118 | 58.54% | 0.1707 | 7.0 | moderate |
| sigma_2_upper | 25 | 2.5714 | 72.00% | 0.44 | 11.0 | weak |
| sigma_2_lower | 26 | 1.6 | 61.54% | 0.2308 | 6.0 | weak |

## Band Asymmetry Tracking

The previous 5-day smoke showed `sigma_1_lower` fragile. In this limited run:

- sigma_1_lower trades: `41`
- sigma_1_lower PF: `1.4118`
- sigma_1_lower AvgR: `0.1707`
- verdict: `SIGMA_1_LOWER_WEAK_SAMPLE_RESOLVED`

Band asymmetry is not confirmed as a blocker in this limited window. Upper bands still look stronger, but lower bands did not collapse.

## Smoke 120m vs Limited

| Window | Days | Trades | Trades/day | PF | WR | AvgR | total_R | MaxDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Smoke 120m 2026-05-10 -> 2026-05-14 | 5 | 39 | 7.8 | 1.2941 | 56.41% | 0.1282 | 5.0 | 4.0 |
| Limited 120m 2026-04-25 -> 2026-05-14 | 20 | 171 | 8.55 | 1.7143 | 63.16% | 0.2632 | 45.0 | 5.0 |

The smoke window is included inside the limited window, so this is not OOS.

## Limited Subset 2026-05-10 to 2026-05-14

Standalone smoke 120m:

- trades: `39`
- PF: `1.2941`
- WR: `56.41%`
- AvgR: `0.1282`
- total_R: `5.0`

Same date subset inside limited:

- trades: `39`
- expected range `32-39`: respected
- PF: `1.6`
- WR: `61.54%`
- AvgR: `0.2308`
- total_R: `9.0`

The subset count exactly matches the standalone smoke count. Individual timestamps differ: `11` standalone smoke timestamps were not present and `11` limited-subset timestamps were extra. This is plausible for a stateful cooldown plus different warmup/lookback context. Because count stayed inside the expected range and did not exceed the standalone smoke, this is not treated as a cross-window policy regression.

Cross-window caveats:

- not OOS;
- smoke is included in the limited window;
- cooldown is stateful;
- earlier trades before 2026-05-10 can affect cooldown state;
- warmup/lookback can change candidate timing.

## Anomaly Detection

- trade_count < 80: no
- trade_count > 300: no
- duration > 10 minutes: no, `586.84s`
- STILL_OPEN regression: no
- cooldown telemetry missing: no
- subset smoke count outside 32-39: no

No anomaly trigger fired.

## Verdict

- `LIMITED_POST_COOLDOWN_RUN_COMPLETE`
- `MECHANICS_STABLE_POST_COOLDOWN`
- `OVERTRADING_REDUCED_IN_LIMITED`
- `STRATEGY_3_INTERESTING_FOR_INTERMEDIATE_VALIDATION`

Not triggered:

- `STRATEGY_3_INTERESTING_BUT_NEEDS_BAND_QUALITY_WORK`
- `STRATEGY_3_WEAK_AFTER_COOLDOWN`
- `STRATEGY_3_INCONCLUSIVE_SAMPLE_TOO_SMALL`
- `BAND_ASYMMETRY_PERSISTS`
- `DIRECTIONAL_ASYMMETRY_PERSISTS`
- `STILL_OPEN_POLICY_REGRESSION_SUSPECTED`
- `CROSS_WINDOW_INCONSISTENCY_NEEDS_INVESTIGATION`
- `EXPECTED_STATEFUL_COOLDOWN_BOUNDARY_EFFECT`

## Next Step

Recommended next branch:

`feat/strategy-3-intermediate-validation-run`

Reason: mechanics are stable, sample is `171` trades, PF is above `1.15`, AvgR and total_R are positive, MaxDD did not explode, and neither band nor direction asymmetry appears to be the only source of the result. This still does not validate edge or justify live deployment.

## What Was Not Done

- no tuning;
- no new filters;
- no entry changes;
- no VWAP filter changes;
- no sweep/liquidity detector changes;
- no Strategy 2 changes;
- no Adelin changes;
- no Dynamic SL changes;
- no simulator changes;
- no max_sim_bars changes;
- no live run;
- no Telegram;
- no orders;
- no full 3-month backtest;
- no multi-symbol;
- no multi-strategy.
