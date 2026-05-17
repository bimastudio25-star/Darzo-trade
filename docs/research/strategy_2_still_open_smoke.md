# Strategy 2.0 STILL_OPEN Smoke Diagnostic

Status: simulator mechanics smoke only. This is not an edge validation and not a live-deployability assessment.

## Smoke Parameters

- strategy: `strategy_2_liquidity_expansion`
- symbol: `XAUUSD`
- requested date range: `2026-05-10` to `2026-05-14`
- effective evaluation window from diagnostics: `2026-05-11T01:00:00+00:00` to `2026-05-13T22:45:00+00:00`
- M1 candles loaded: `3960`
- M5 candles loaded: `792`
- M15 driver candles loaded: `264`
- output path: `backtests/reports/strategy_2_still_open_smoke`
- approximate duration: `8.3` seconds

Command used:

```powershell
python backtest.py --symbol XAUUSD --from 2026-05-10 --to 2026-05-14 --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_2_still_open_smoke --strategies strategy_2_0 --fast --progress-every-candles 200
```

## Outcome Distribution

| outcome | count |
|---|---:|
| SL | 1 |
| TP1 | 0 |
| TP2 | 1 |
| TP3 | 0 |
| TP4 | 0 |
| BE | 1 |
| TIMEOUT_CLOSE | 1 |
| END_OF_DATA_CLOSE | 0 |
| STILL_OPEN | 0 |

## Metrics

- total trades: `4`
- win rate: `25.00%`
- profit factor: `0.6501`
- average R: `-0.0969`
- median R: `-0.0539`
- max drawdown R: `1.0`
- total R: `-0.3877`
- still_open_rate: `0.0`
- timeout_close_rate: `0.25`
- end_of_data_close_rate: `0.0`
- metric_revision_due_to_still_open_policy: `true`

## Mechanic Check

- STILL_OPEN disappeared or dropped near zero: yes, `0/4`.
- TIMEOUT_CLOSE assigned correctly: yes, `1/4`.
- END_OF_DATA_CLOSE assigned correctly: not observed in this tiny sample.
- r_multiple calculated on new outcome: yes, TIMEOUT_CLOSE had `r_multiple=-0.1079`.
- timeout_close_rate populated: yes, `0.25`.
- end_of_data_close_rate populated: yes, `0.0`.
- metric_revision_due_to_still_open_policy present: yes.

## Comparison With Pre-fix Diagnostic

Previous final report diagnostic:

- Strategy 2.0 total trades: `97`
- STILL_OPEN: `45`
- STILL_OPEN rate: `46.39%`
- all 45 STILL_OPEN had `r_multiple=0`

Post-policy smoke:

- Strategy 2.0 total trades: `4`
- STILL_OPEN: `0`
- STILL_OPEN rate: `0.0%`
- TIMEOUT_CLOSE: `1`
- TIMEOUT_CLOSE r_multiple: `-0.1079`

This confirms the simulator mechanics on a limited sample. It does not prove or disprove Strategy 2.0 edge.

## Sample Warning

This smoke produced only `4` trades. PF, WR, AvgR, and MaxDD are sanity-check numbers only and are not statistically interpretable. The purpose was to verify the simulator mechanics:

- whether STILL_OPEN is removed or near zero;
- whether TIMEOUT_CLOSE / END_OF_DATA_CLOSE can be assigned;
- whether r_multiple is calculated on unresolved trades at cutoff;
- whether the new rates and metric revision fields appear in reports.

Do not use this smoke to claim that Strategy 2.0 is profitable, deployable, or edge-confirmed.

## Verdict

- `SIMULATOR_FIX_CONFIRMED`
- `STRATEGY_2_MECHANICS_OK_SAMPLE_TOO_SMALL_FOR_EDGE`

`MAX_SIM_BARS_REVIEW_NEEDED` is not triggered by this smoke: timeout_close_rate is `25%`, below the 40-50% review threshold. Caveat: TIMEOUT_CLOSE r_multiple is the value at cutoff, not necessarily the true final runner outcome. Any max_sim_bars review would be strategy-specific and belongs in a separate branch, not here.

## Next Step

No strategy optimization in this branch.

If more confidence is needed, run a slightly broader but still limited Strategy 2.0-only report-only backtest, not a full 3-month run. Keep it single-symbol and bounded, and use it only to validate simulator/report mechanics unless a separate research task explicitly asks for edge evaluation.
