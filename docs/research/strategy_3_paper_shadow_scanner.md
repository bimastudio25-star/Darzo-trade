# Strategy 3 Paper Shadow Scanner

Status: research/paper-only scanner. This branch does not make Strategy 3 deployable.

## Context

Strategy 3 VWAP 1R is currently the strongest Darzo Trade research candidate:

- intermediate validation: 544 trades, PF 1.5302, AvgR +0.2096, total_R +114R
- IS: PF 1.4276, AvgR +0.1762, total_R +65R
- OOS: PF 1.7778, AvgR +0.2800, total_R +49R
- mechanics stable: STILL_OPEN/TIMEOUT/END_OF_DATA all 0
- cooldown accepted/exported delta: 0

Forward data after `2026-05-14` was not available in the local dataset. A fallback past-OOS stress test on `2026-01-30 -> 2026-03-14` was positive but weak:

- 379 trades
- PF 1.0824
- AvgR +0.0396
- total_R +15R
- MaxDD 17R
- sigma_1_lower fragility returned
- reversal was weak

Interpretation: Strategy 3 remains promising, but probably regime-sensitive. The correct next step is paper-only shadow observation, not live deployment.

## Safety

This scanner is deliberately local and inert:

- no live trading
- no broker orders
- no Telegram signals
- dry-run only
- local logging only
- Strategy 3 remains research/paper-only
- no Strategy 3 entry rules changed
- no VWAP logic changed
- no cooldown logic or value changed

## How To Run

```powershell
python scripts/run_strategy_3_paper_shadow_scanner.py --symbol XAUUSD --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_3_paper_shadow_scanner --cooldown-minutes 120 --dry-run
```

Default behavior evaluates only the latest M15 driver candle. This keeps the scanner runtime-like instead of turning it into another backtest.

## Output Files

The scanner writes to:

`backtests/reports/strategy_3_paper_shadow_scanner`

Files:

- `paper_signals.csv`
- `paper_signals.jsonl`
- `scanner_summary.json`
- `scanner_run.md`

If no signal is detected, this is not a failure. The scanner still writes all output files, with CSV headers and a summary explaining the no-signal reason.

## Metadata Fields

Paper signal rows include:

- run metadata: `scanner_run_id`, `generated_at`, `mode`, `dry_run`
- identity: `symbol`, `strategy`, `signal_timestamp`
- signal levels: `direction`, `entry_price`, `stop_loss`, `take_profit`, `risk_distance`, `expected_R`
- setup: `setup_mode`, `band_touched`, `reason_codes`, `score`
- VWAP context: `vwap_value`, `sigma_1_upper`, `sigma_1_lower`, `sigma_2_upper`, `sigma_2_lower`, `distance_to_vwap`, `distance_to_band`
- market context: `session`, `timeframe`, `source_timeframe`, `latest_data_timestamp`, `data_rows_used`
- cooldown: `cooldown_status`, `cooldown_accepted`, `cooldown_blocked`, `cooldown_block_reason`, `last_signal_timestamp_same_symbol_direction`
- safety: `order_sent`, `telegram_sent`, `broker_called`, `live_trading_enabled`, `order_execution_enabled`, `telegram_enabled`

The fields are intentionally close to backtest exports so a later branch can compare runtime-like paper signals against backtest signals.

## Smoke Run

Command:

```powershell
python scripts/run_strategy_3_paper_shadow_scanner.py --symbol XAUUSD --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_3_paper_shadow_scanner --cooldown-minutes 120 --dry-run
```

Result:

- runtime: 4.5s wall-clock, scanner internal runtime 1.1902s
- latest M15 data timestamp: `2026-05-14T22:45:00+00:00`
- signals_detected: 0
- signals_accepted: 0
- signals_blocked_by_cooldown: 0
- no_signal_reason: `no_strategy_3_signal_on_latest_driver_candle`
- strategy diagnostic rejection: `liquidity_sweep_missing`

No-signal is acceptable. It means the latest available M15 context did not meet Strategy 3 conditions.

## Interpretation

A paper signal is not:

- a trade recommendation
- a live alert
- a deployable trade
- evidence that Strategy 3 is production-ready

A paper signal is only evidence for future runtime/backtest consistency checks.

## Success Criteria

- scanner runs without error
- scanner writes output files
- scanner never calls Telegram
- scanner never calls broker/order execution
- scanner exports comparable metadata
- no-signal case is handled cleanly
- import is safe and does not start a scan

## Failure Criteria

- scanner needs live/broker code to run
- scanner sends Telegram
- scanner places or prepares orders
- scanner modifies Strategy 3 rules
- scanner cannot produce comparable metadata
- scanner produces runtime behavior that cannot be compared later to backtest

## Next Branches

If scanner works:

- `feat/strategy-3-shadow-vs-backtest-comparison`

If scanner detects runtime instability:

- `feat/strategy-3-runtime-diagnostics`

If enough paper data accumulates and runtime/backtest comparison reaches at least 95%:

- `feat/strategy-3-spread-slippage-model`

## Future Comparison Questions

The next comparison branch should answer:

1. Does the scanner produce the same signals the backtest would produce?
2. Are timestamps aligned?
3. Are entry/SL/TP levels aligned?
4. Is cooldown behavior identical?
5. Are setup_mode and band_touched aligned?
6. Are no-signal periods also consistent?
7. Are VWAP and sigma bands identical between runtime and backtest?
8. Does the runtime use the same lookback/warmup assumptions as the backtest?

## Deployment Warning

Strategy 3 remains research/paper-only. This branch does not enable live trading, Telegram live signal deployment, broker integration, or real orders.
