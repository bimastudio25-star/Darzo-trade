# Strategy 2.0 Limited Post-policy Diagnostic

Status: limited mechanics run only. This is not live validation, not strategy optimization, and not a deployability claim.

## Config

- strategy: `strategy_2_liquidity_expansion`
- symbol: `XAUUSD`
- requested date range: `2026-04-25` to `2026-05-14`
- effective evaluation window from diagnostics: `2026-04-27T01:00:00+00:00` to `2026-05-13T22:45:00+00:00`
- output path: `backtests/reports/strategy_2_limited_post_policy`
- approximate duration: `37.5` seconds
- duration under 10 minutes: yes
- M1 candles loaded: `17160`
- M5 candles loaded: `3432`
- M15 driver candles loaded: `1144`

Command used:

```powershell
python backtest.py --symbol XAUUSD --from 2026-04-25 --to 2026-05-14 --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_2_limited_post_policy --strategies strategy_2_0 --fast --progress-every-candles 200
```

## Outcome Distribution

| outcome | count |
|---|---:|
| SL | 5 |
| TP1 | 0 |
| TP2 | 5 |
| TP3 | 0 |
| TP4 | 0 |
| BE | 4 |
| TIMEOUT_CLOSE | 5 |
| END_OF_DATA_CLOSE | 0 |
| STILL_OPEN | 0 |

## Metrics

- total signals: `22`
- total trades: `19`
- rejected signals: `3`
- win rate: `36.84%`
- profit factor: `0.8216`
- average R: `-0.0507`
- median R: `0.0`
- max drawdown R: `2.5322`
- total R: `-0.9640`
- still_open_rate: `0.0`
- timeout_close_rate: `0.2632`
- end_of_data_close_rate: `0.0`
- metric_revision_due_to_still_open_policy: `true`

## Mechanics Checks

- STILL_OPEN remains zero or near zero: yes, `0/19`.
- TIMEOUT_CLOSE is populated: yes, `5/19`.
- END_OF_DATA_CLOSE appears only if coherent: yes, none observed in this window.
- r_multiple is populated for TIMEOUT_CLOSE: yes, timeout closes had non-zero or computed R values.
- metric_revision_due_to_still_open_policy is present: yes.
- timeout_close_rate is below the 40-50% max_sim_bars review threshold: yes, `26.32%`.

## Cross-window Comparison

| Window | Days | Trades | PF | WR | AvgR |
|---|---:|---:|---:|---:|---:|
| Smoke 2026-05-10 -> 2026-05-14 | 5 | 4 | 0.6501 | 25.00% | -0.0969 |
| Limited 2026-04-25 -> 2026-05-14 | 20 | 19 | 0.8216 | 36.84% | -0.0507 |

Caveat: the 5-day smoke window is included in the limited window, so this is not an OOS comparison.

The four smoke timestamps were found in the limited run and kept the same outcome classes:

| timestamp | smoke outcome | limited outcome | smoke R | limited R |
|---|---|---|---:|---:|
| 2026-05-12T04:45:00+00:00 | SL | SL | -1.0 | -1.0 |
| 2026-05-12T18:30:00+00:00 | TP2 | TP2 | 0.7202 | 0.7069 |
| 2026-05-12T21:45:00+00:00 | TIMEOUT_CLOSE | TIMEOUT_CLOSE | -0.1079 | -0.1167 |
| 2026-05-13T15:30:00+00:00 | BE | BE | 0.0 | 0.0 |

`CROSS_WINDOW_INCONSISTENCY_DETECTED`: prices, stop distances, R values, and one exit timestamp differ between smoke and limited for the overlapping trades. This looks consistent with different warmup/lookback context caused by changing the start date, rather than random state or simulator policy regression. It should be remembered if future validation compares overlapping windows.

## Sample Warning

This limited run produced `19` trades. That is enough to check simulator mechanics, but still not enough for a live or deployability conclusion. PF, WR, AvgR, and MaxDD are diagnostic sanity checks only.

Do not use this run to claim Strategy 2.0 is profitable, deployable, or edge-confirmed.

## Verdict

- `MECHANICS_STABLE_POST_POLICY`
- `STRATEGY_2_WEAK_AFTER_POLICY`

Not triggered:

- `STILL_OPEN_POLICY_REGRESSION`
- `MAX_SIM_BARS_REVIEW_NEEDED`
- `STRATEGY_2_INTERESTING_BUT_NEEDS_INTERMEDIATE_RUN`
- `INCONCLUSIVE_SAMPLE_TOO_SMALL`

## Next Step

Per the decision matrix, mechanics are stable but Strategy 2.0 is weak after the policy on this limited run. Recommended next branch:

`feat/strategy-3-vwap-1r`

Do not tune `max_sim_bars` in this branch. Do not run full 3-month validation without a separate intermediate-run decision.
