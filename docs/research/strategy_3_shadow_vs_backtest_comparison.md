# Strategy 3 Shadow vs Backtest Comparison

Status: research/paper-only comparison framework. Strategy 3 remains non-deployable.

## Context

Strategy 3 VWAP 1R is promising but not live-deployable:

- intermediate validation: 544 trades, PF 1.5302, AvgR +0.2096, total_R +114R
- IS PF: 1.4276
- OOS PF: 1.7778
- mechanics stable: accepted/exported cooldown delta 0, STILL/TIMEOUT/END_OF_DATA 0/0/0
- past-OOS stress test: positive but weak, PF 1.0824, AvgR +0.0396, total_R +15R
- past-OOS warnings: sigma_1_lower fragility returned, reversal weak

The paper shadow scanner exists and is safe. Its first smoke run produced 0 signals on the latest available M15 candle:

- latest data timestamp: `2026-05-14T22:45:00+00:00`
- signals found / accepted / blocked: `0 / 0 / 0`
- no-signal reason: `no_strategy_3_signal_on_latest_driver_candle`

This comparison framework is required before Telegram wiring, broker integration, live alerts, or any real execution work.

## Purpose

The goal is to verify runtime/shadow scanner consistency with backtest behavior.

Main question:

Does the Strategy 3 paper/runtime scanner produce the same signals the Strategy 3 backtest path would produce on the same data?

If runtime and backtest produce different signals, historical PF is not operationally reliable.

## How To Run

```powershell
python scripts/compare_strategy_3_shadow_vs_backtest.py --paper-dir backtests/reports/strategy_3_paper_shadow_scanner --data-dir data --output-dir backtests/reports/strategy_3_shadow_vs_backtest_comparison --symbol XAUUSD --strategy strategy_3_vwap_1r --cooldown-minutes 120 --price-tolerance-usd 0.01 --timestamp-tolerance-seconds 0
```

## Output Files

The comparison writes to:

`backtests/reports/strategy_3_shadow_vs_backtest_comparison`

Files:

- `comparison_summary.json`
- `comparison_report.md`
- `matched_signals.csv`, when a comparison is performed
- `mismatched_signals.csv`, when a comparison is performed
- `missing_in_backtest.csv`, when a comparison is performed
- `extra_in_backtest.csv`, when a comparison is performed

## Comparison Window Logic

When paper signals exist:

- `backtest_from = earliest paper signal timestamp - 2h`
- `backtest_to = latest paper signal timestamp + 5min`

Reasons:

- VWAP convergence
- cooldown state initialization
- enough Strategy 3 context to reproduce runtime behavior
- avoid missing edge timestamps

This is intentionally narrow. It is not a full backtest and not a 3-month historical run.

## Tolerances

Defaults:

- `price_tolerance_usd = 0.01`
- `timestamp_tolerance_seconds = 0`
- cooldown status must match exactly

For XAUUSD, 0.01 USD is intentionally stricter than a 1-pip tolerance so rounding or precision bugs are visible.

## Match Rate Formula

```text
match_rate = matched_count / max(paper_signals_count, backtest_signals_count)
```

Edge cases:

- 0 paper / 0 backtest: `match_rate = null`, not meaningful yet
- 0 paper / >0 backtest: severe divergence, scanner missed signals
- >0 paper / 0 backtest: severe divergence, scanner generated signals the backtest cannot reproduce

## No-Signal Behavior

If `paper_signals.csv` has 0 rows, this is not a failure. The framework returns:

- `SHADOW_COMPARISON_NO_PAPER_SIGNALS_YET`
- `FRAMEWORK_READY`
- `NO_BACKTEST_COMPARISON_PERFORMED`

This means the scanner/comparison infrastructure is ready, but runtime-vs-backtest consistency cannot be judged yet.

## Smoke Result

Command:

```powershell
python scripts/compare_strategy_3_shadow_vs_backtest.py --paper-dir backtests/reports/strategy_3_paper_shadow_scanner --data-dir data --output-dir backtests/reports/strategy_3_shadow_vs_backtest_comparison --symbol XAUUSD --strategy strategy_3_vwap_1r --cooldown-minutes 120 --price-tolerance-usd 0.01 --timestamp-tolerance-seconds 0
```

Result:

- runtime: `0.86s` wall-clock
- paper_signals_count: `0`
- backtest_signals_count: `0`
- match_rate: `null`
- comparison_window: `null`
- verdict flags:
  - `SHADOW_COMPARISON_NO_PAPER_SIGNALS_YET`
  - `FRAMEWORK_READY`
  - `NO_BACKTEST_COMPARISON_PERFORMED`

No backtest comparison was performed because no paper signals existed. No results were faked.

## Paper Signal Accumulation Workflow

1. When new XAUUSD data arrives, rerun:

```powershell
python scripts/run_strategy_3_paper_shadow_scanner.py --symbol XAUUSD --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_3_paper_shadow_scanner --cooldown-minutes 120 --dry-run
```

2. Minimum useful frequency: 1 scanner run per day.

3. Target sample before meaningful comparison: 10-20 paper signals minimum.

4. Expected accumulation time: 1-3 weeks, depending on market conditions. With cooldown 120m, a rough expectation may be 1-2 signals/day, but this is not guaranteed.

5. Once paper signals accumulate, rerun the comparison script. No new branch is required for simple reruns.

6. Until paper signals exist, this framework can only confirm schema, safety, and readiness.

## Match Thresholds

- >= 95%: acceptable consistency
- 80-95%: review required
- < 80%: likely runtime/backtest pipeline bug

## Safety

The comparison script never:

- enables live trading
- sends orders
- calls broker execution code
- sends Telegram
- requires live data
- runs multi-symbol
- runs multi-strategy
- changes Strategy 3 logic

## Next Steps

If no paper signals:

- accumulate shadow data by rerunning the paper scanner when fresh data arrives.

If match >= 95%:

- `feat/strategy-3-spread-slippage-model`

If match is 80-95%:

- `feat/strategy-3-runtime-diagnostics`

If match is < 80%:

- fix runtime/backtest pipeline before any further work.

## Deployment Warning

Strategy 3 remains research/paper-only. This branch does not enable live trading, Telegram live signals, broker integration, spread/slippage modeling, or real orders.
