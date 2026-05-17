# Strategy 3 VWAP 1R Initial Research Scaffold

Status: research-only / backtest-only. Not live, not deployable, not optimized.

## Branch And Base

- branch: `feat/strategy-3-vwap-1r`
- base commit: `de056ab Run Strategy 2 limited post-policy diagnostic`

## Files Changed

- `dazro_trade/analysis/strategy_3_vwap_1r.py`
- `dazro_trade/backtest/runner.py`
- `backtest.py`
- `tests/test_strategy_3_vwap_1r.py`
- `docs/research/strategy_3_vwap_1r_initial.md`

## Modules Reused

- VWAP snapshot and standard deviation bands: `dazro_trade.analysis.vwap`
- Liquidity map and nearby level matching: `dazro_trade.adelin.liquidity_map`
- M1/M5 sweep and post-liquidity FVG/IFVG context: `dazro_trade.adelin.sweep_detector`
- Volume crack / LVN confluence: `dazro_trade.adelin.volume_profile`
- Number theory context: `dazro_trade.adelin.number_theory`
- Shared simulator and metrics: `dazro_trade.backtest.simulator`, `dazro_trade.backtest.metrics`

## Modules Created

- `dazro_trade.analysis.strategy_3_vwap_1r`

## Strategy Description

Strategy 3 is a separate Strategy 3 VWAP 1R research scaffold. It is intentionally light and measurable:

- M15 is the driver timeframe.
- M5/M1 provide sweep/reaction context.
- H1/H4/D1 provide context for liquidity maps only.
- Signals require a liquidity sweep, nearby VWAP/band context, valid 1R target geometry, and a nearby liquidity level.
- The strategy is selectable only by explicit CLI alias and is not included in default `all`, to avoid changing existing backtest behavior by surprise.

CLI strategy name:

`strategy_3_vwap_1r`

Alias:

`vwap_1r`

## Initial Entry Rules

The initial scaffold emits a signal only when:

- a liquidity sweep is detected through the existing M5/M1 sweep detector;
- the swept liquidity level is within the configured max distance from current price;
- price is close to VWAP / 1 sigma / 2 sigma band;
- setup classification is not `no_trade`;
- stop and 1R target are valid under the initial risk bounds.

Setup modes:

- `reversal`
- `trend_following`
- `no_trade`

## SL/TP Rules

- target model: fixed `1R`
- stop: technical stop beyond swept level/structure plus buffer
- no trailing
- no dynamic SL
- no partial exits
- no live execution

## Signal Telemetry

Each backtest signal carries metadata:

- `setup_mode`
- `reason_codes`
- `confluences`
- `vwap_distance_pips`
- `band_touched`
- `liquidity_context`
- `fvg_ifvg_context`
- `number_theory_context`
- `target_model=1R`
- `research_only=true`

## Smoke Command

```powershell
python backtest.py --symbol XAUUSD --from 2026-05-10 --to 2026-05-14 --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_3_vwap_1r_smoke --strategies strategy_3_vwap_1r --fast --progress-every-candles 200
```

Smoke duration: `39.13` seconds.

## Smoke Result

Output path:

`backtests/reports/strategy_3_vwap_1r_smoke`

Outcome distribution:

| outcome | count |
|---|---:|
| TP1 | 29 |
| SL | 25 |
| STILL_OPEN | 0 |
| TIMEOUT_CLOSE | 0 |
| END_OF_DATA_CLOSE | 0 |

Metrics:

- total signals: `55`
- total trades: `54`
- rejected signals: `1`
- PF: `1.16`
- WR: `53.70%`
- AvgR: `0.0741`
- MedianR: `1.0`
- MaxDD: `6.0R`
- total_R: `4.0R`
- still_open_rate: `0.0`
- timeout_close_rate: `0.0`
- end_of_data_close_rate: `0.0`

Diagnostics:

- evaluation_count: `264`
- signals_emitted: `55`
- setup_modes: `reversal=25`, `trend_following=30`, `no_trade=147`
- rejected_reasons: `liquidity_sweep_missing=61`, `vwap_context_no_trade=147`, `liquidity_level_too_far=1`

## Warnings

- `STRATEGY_3_OVERTRADING_INITIAL_SMOKE`: 54 trades in the initial 5-day smoke is too many for a clean first research scaffold.
- The positive PF/AvgR from this smoke is not deployability evidence.
- The strategy is not OOS validated.
- The strategy is not optimized.
- The strategy is not connected to live runtime, Telegram, or orders.
- A high trade count means the initial confluence gate is likely too permissive, but this branch intentionally does not optimize filters.

## Next Steps

Recommended next branch:

`feat/strategy-3-vwap-1r-tighten-research-gates`

Scope for that branch should remain research-only:

- reduce overtrading with explicit, testable gates;
- preserve 1R target model;
- avoid live deployment;
- keep Strategy 1/2 untouched;
- compare a small fixed window before any intermediate validation.
