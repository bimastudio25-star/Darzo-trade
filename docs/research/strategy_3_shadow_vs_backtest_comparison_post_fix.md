# Strategy 3 Shadow vs Backtest Comparison - Post H4 Repair

Status: research/paper-only runtime-vs-backtest consistency check. This report does not make Strategy 3 live-ready.

## Context

Strategy 3 paper validation was blocked while H4 was stale/quarantined. The Windows file-lock fix, H4 freshness diagnostics, H4 source diagnostic, and safe H4 repair are now in place.

The H4 repair replaced one material conflict row at `2026-05-19T00:00:00+00:00` and appended 10 missing closed H4 bars. Local H4 now reaches `2026-05-20T16:00:00+00:00`; post-repair OHLC overlap is `298/298 = 1.0`.

The current paper scanner output contains 64 cumulative Strategy 3 paper signals and the pipeline summary marks `paper_signals_clean_for_validation = true`.

## Safety

- no live trading
- no Telegram
- no orders
- no broker execution
- no `order_send`
- no Strategy 3 logic changes
- no VWAP, sigma, or cooldown changes

## Inputs

- paper signals: `backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv`
- scanner summary: `backtests/reports/strategy_3_paper_shadow_scanner/scanner_summary.json`
- pipeline summary: `backtests/reports/strategy_3_local_paper_pipeline/pipeline_summary.json`
- H4 repair report: `backtests/reports/strategy_3_h4_safe_repair/h4_repair_report.json`
- H4 post-repair diagnostic: `backtests/reports/strategy_3_h4_data_source_diagnostic_post_repair/h4_data_source_diagnostic.json`
- local data: `data/XAUUSD`

## Method

The comparison generated Strategy 3 backtest-comparable signals over the paper-signal window only, using XAUUSD, Strategy 3, cooldown 120 minutes, timestamp tolerance `0s`, and price tolerance `0.01 USD`.

Command:

```powershell
python scripts/compare_strategy_3_paper_vs_backtest.py --symbol XAUUSD --data-dir data --paper-signals-path backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv --scanner-summary-path backtests/reports/strategy_3_paper_shadow_scanner/scanner_summary.json --pipeline-summary-path backtests/reports/strategy_3_local_paper_pipeline/pipeline_summary.json --output-dir backtests/reports/strategy_3_shadow_vs_backtest_comparison_post_fix --cooldown-minutes 120 --timestamp-tolerance-seconds 0 --price-tolerance 0.01 --dry-run
```

Window:

- earliest paper signal: `2026-05-19T02:00:00+00:00`
- latest paper signal: `2026-05-20T22:00:00+00:00`
- backtest signal scan start: `2026-05-19T01:00:00+00:00`
- backtest signal scan end: `2026-05-20T22:05:00+00:00`
- data warmup start reported: `2026-05-18T02:00:00+00:00`

## Data Integrity

- H4 freshness: `fresh`
- H4 stale_by_bars: `0`
- H4 latest existing timestamp: `2026-05-20T16:00:00+00:00`
- H4 expected latest closed timestamp: `2026-05-20T16:00:00+00:00`
- post-repair OHLC match rate: `1.0`
- post-repair OHLCV match rate: `0.0369`
- mismatch type: `volume_only`
- H4 backup: `data\XAUUSD\H4.csv.backup.20260520T222909Z`

The remaining OHLCV mismatch is volume-only. It is non-blocking for this price-level runtime/backtest comparison.

## Results

| Metric | Value |
|---|---:|
| Paper detected signals | 64 |
| Paper accepted signals | 29 |
| Paper cooldown-blocked signals | 35 |
| Backtest detected signals | 65 |
| Backtest accepted signals | 29 |
| Backtest cooldown-blocked signals | 36 |
| All-detected match rate | 92.31% |
| Accepted-only match rate | 93.10% |

All-detected mismatch categories:

- `STOP_LOSS_MISMATCH`: 3
- `TAKE_PROFIT_MISMATCH`: 3
- `COOLDOWN_STATUS_MISMATCH`: 1
- `EXTRA_IN_BACKTEST`: 1

Accepted-only mismatch categories:

- `MISSING_IN_BACKTEST`: 1
- `EXTRA_IN_BACKTEST`: 1
- `STOP_LOSS_MISMATCH`: 1
- `TAKE_PROFIT_MISMATCH`: 1

Field-level accepted-only rates:

- direction: `100%`
- entry: `100%`
- stop loss: `96.43%`
- take profit: `96.43%`
- setup_mode: `100%`
- band_touched: `100%`
- cooldown status on paired signals: `100%`

Price mismatch stats:

- all-detected max absolute diff: `0.68`
- accepted-only max absolute diff: `0.68`

## Verdict Flags

- `PAPER_SIGNALS_CLEAN_FOR_VALIDATION`
- `SHADOW_BACKTEST_MINOR_MISMATCHES`
- `NO_LIVE_DEPLOYMENT_DECISION`
- `STRATEGY_3_REMAINS_PAPER_ONLY`

## Interpretation

This is not a clean >=95% runtime/backtest pass. It is also not a strategy failure. The accepted-only comparison is close, but the strict threshold was not met.

The comparison validates that most runtime/paper signals align with the backtest path after the H4 repair, but there are enough stop/target and one extra/missing accepted-signal asymmetry to require diagnostics before spread/slippage modeling.

This report does not validate profitability, edge, deployment, Telegram alerts, broker integration, or live readiness.

## Next Step

Recommended next branch:

`feat/strategy-3-runtime-comparison-diagnostics`

Focus:

- inspect the accepted-only extra/missing pair around `2026-05-20T01:45:00+00:00` and `2026-05-20T03:30:00+00:00`
- inspect stop/TP drift around the mismatched `2026-05-20` signals
- decide whether mismatches came from stale pre-repair paper rows, scanner state initialization, or a true runtime/backtest path divergence

Do not proceed to spread/slippage modeling until accepted-only consistency reaches at least 95% or the mismatch is explicitly explained and bounded.
