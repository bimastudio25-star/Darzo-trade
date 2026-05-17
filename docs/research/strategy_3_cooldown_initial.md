# Strategy 3 Cooldown Initial

Status: research-only mechanics test. This is not edge validation, not optimization, and not a live/deployability claim.

## Branch

- branch: `feat/strategy-3-add-cooldown`
- base branch: `feat/strategy-3-overtrading-diagnostics`
- base commit: `a5759a5 Add Strategy 3 overtrading diagnostics`

## Why Cooldown Now

The previous overtrading diagnostic found:

- `94` Strategy 3 trades in the 2026-05-10 to 2026-05-14 smoke window.
- active-window density: `24.59` trades/day.
- max trades/day: `38`.
- max trades/hour: `4`.
- median gap: `15m`.
- primary diagnostic verdict: `MISSING_COOLDOWN`.

The cooldown is a neutral operational gate. It does not change VWAP, sweep detection, band logic, setup classification, TP/SL, or the simulator.

## Cooldown Design

- parameter: `strategy_3_cooldown_minutes`
- env override: `STRATEGY_3_COOLDOWN_MINUTES`
- default: `60`
- sensitivity values tested: `30`, `60`, `120`
- scope: same `symbol` and same `direction`
- implementation point: Strategy 3 backtest evaluator wrapper in `dazro_trade/backtest/runner.py`
- blocked reason code: `STRATEGY_3_COOLDOWN_BLOCKED`

The gate runs after a Strategy 3 candidate is generated and converted to `BacktestSignal`, but before the simulator receives it. Blocked candidates are exported as rejected signals and counted in Strategy 3 diagnostics.

## Smoke Commands

```powershell
$env:STRATEGY_3_COOLDOWN_MINUTES="30"
python backtest.py --symbol XAUUSD --from 2026-05-10 --to 2026-05-14 --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_3_vwap_1r_cooldown_30m_smoke --strategies strategy_3_vwap_1r --fast --progress-every-candles 200

$env:STRATEGY_3_COOLDOWN_MINUTES="60"
python backtest.py --symbol XAUUSD --from 2026-05-10 --to 2026-05-14 --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_3_vwap_1r_cooldown_60m_smoke --strategies strategy_3_vwap_1r --fast --progress-every-candles 200

$env:STRATEGY_3_COOLDOWN_MINUTES="120"
python backtest.py --symbol XAUUSD --from 2026-05-10 --to 2026-05-14 --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_3_vwap_1r_cooldown_120m_smoke --strategies strategy_3_vwap_1r --fast --progress-every-candles 200
```

Durations:

- 30m: `43.01s`
- 60m: `43.54s`
- 120m: `45.31s`

## Baseline vs ABC

| Config | trades | trades/day | reduction% | PF | WR | AvgR | total_R | MaxDD | median_gap | cooldown_blocked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline no cooldown | 94 | 18.8 | 0.0% | 1.186 | 54.26% | 0.0851 | 8.0 | 6.0R | 15m | 0 |
| Cooldown 30m | 73 | 14.6 | 22.3% | 1.0278 | 50.68% | 0.0137 | 1.0 | 7.0R | 30m | 21 |
| Cooldown 60m | 53 | 10.6 | 43.6% | 1.2083 | 54.72% | 0.0943 | 5.0 | 5.0R | 60m | 41 |
| Cooldown 120m | 39 | 7.8 | 58.5% | 1.2941 | 56.41% | 0.1282 | 5.0 | 4.0R | 97.5m | 55 |

STILL_OPEN, TIMEOUT_CLOSE, and END_OF_DATA_CLOSE remained `0` in all three cooldown smoke runs.

## Acceptance Criteria

- Preferred target: 15-30 trades, PF >= 1.10, total_R > 0.
- Acceptable target: 30-45 trades, PF >= 1.00, AvgR >= 0, total_R >= 0, reduction >= 50%, STILL_OPEN = 0.

Result:

- 30m: insufficient reduction, trade count remains high.
- 60m: mechanically cleaner, but still above the acceptable trade-count range.
- 120m: acceptable range, positive metrics, still not an edge claim.

The 120m config is the best candidate by the stated criteria, not because it has the highest PF. It is the only tested value that reduces trade count into the acceptable range while keeping mechanics stable and metrics non-destructive.

## Cooldown Telemetry

| Config | accepted | blocked | blocked LONG | blocked SHORT | blocked reversal | blocked trend_following |
|---|---:|---:|---:|---:|---:|---:|
| 30m | 73 | 21 | 10 | 11 | 9 | 12 |
| 60m | 53 | 41 | 22 | 19 | 16 | 25 |
| 120m | 39 | 55 | 30 | 25 | 24 | 31 |

Blocked by band:

| Config | vwap | sigma_1_upper | sigma_1_lower | sigma_2_upper | sigma_2_lower |
|---|---:|---:|---:|---:|---:|
| 30m | 8 | 3 | 3 | 4 | 3 |
| 60m | 12 | 11 | 4 | 8 | 6 |
| 120m | 16 | 12 | 8 | 11 | 8 |

## Direction Pre/Post

| Config | LONG trades | LONG PF | LONG total_R | SHORT trades | SHORT PF | SHORT total_R |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 50 | 0.9231 | -2.0 | 44 | 1.5882 | 10.0 |
| 30m | 40 | 0.9048 | -2.0 | 33 | 1.2 | 3.0 |
| 60m | 28 | 0.8667 | -2.0 | 25 | 1.7778 | 7.0 |
| 120m | 20 | 1.2222 | 2.0 | 19 | 1.375 | 3.0 |

Do not disable LONG or SHORT in this branch. Direction asymmetry is reduced at 120m, but this is still a 5-day smoke sample.

## Setup Mode Pre/Post

| Config | trend trades | trend PF | trend total_R | reversal trades | reversal PF | reversal total_R |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 48 | 1.2857 | 6.0 | 46 | 1.0909 | 2.0 |
| 30m | 36 | 1.25 | 4.0 | 37 | 0.85 | -3.0 |
| 60m | 23 | 1.5556 | 5.0 | 30 | 1.0 | 0.0 |
| 120m | 17 | 1.8333 | 5.0 | 22 | 1.0 | 0.0 |

## Band Pre/Post

| Config | vwap PF/R | s1 upper PF/R | s1 lower PF/R | s2 upper PF/R | s2 lower PF/R |
|---|---|---|---|---|---|
| Baseline | 1.2727 / 3.0 | 1.1818 / 2.0 | 0.875 / -1.0 | 3.0 / 8.0 | 0.5556 / -4.0 |
| 30m | 1.125 / 1.0 | 1.1 / 1.0 | 0.7143 / -2.0 | 2.0 / 4.0 | 0.5714 / -3.0 |
| 60m | 1.6 / 3.0 | 1.1667 / 1.0 | 0.8333 / -1.0 | 3.0 / 4.0 | 0.6 / -2.0 |
| 120m | 2.0 / 3.0 | 1.4 / 2.0 | 0.4 / -3.0 | 4.0 / 3.0 | 1.0 / 0.0 |

Band asymmetry persists: lower sigma_1 remains weak and upper bands still carry most of the positive result. This is diagnostic only; no band filter was applied.

## Verdict

- `COOLDOWN_IMPLEMENTED`
- `COOLDOWN_ISOLATED_OK`
- `ABC_COOLDOWN_TEST_COMPLETE`
- `OVERTRADING_REDUCED`
- `OVERTRADING_REDUCED_TO_ACCEPTABLE_RANGE`
- `COOLDOWN_MECHANICALLY_VALID`
- `EDGE_STILL_NOT_VALIDATED`
- `BAND_ASYMMETRY_PERSISTS`

Not triggered:

- `COOLDOWN_ALONE_NOT_SUFFICIENT`
- `COOLDOWN_TOO_AGGRESSIVE`
- `DIRECTIONAL_ASYMMETRY_PERSISTS` on the 120m candidate

## Next Step

Recommended next branch:

`feat/strategy-3-limited-post-cooldown-run`

Reason: 120m reaches the acceptable operational range on the 5-day smoke without breaking mechanics. The next step should be a limited post-cooldown run, not a full 3-month backtest and not parameter optimization.

## What Was Not Done

- no tuning beyond the prescribed 30/60/120 sensitivity test
- no direction filter
- no band tightening
- no session filter
- no Strategy 2 change
- no Adelin change
- no Dynamic SL change
- no simulator change
- no max_sim_bars change
- no live run
- no Telegram
- no orders
- no full 3-month backtest
- no multi-symbol
- no multi-strategy
