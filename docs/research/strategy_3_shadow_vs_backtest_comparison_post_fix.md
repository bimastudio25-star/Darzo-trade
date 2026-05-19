# Strategy 3 Shadow vs Backtest Comparison Post Fix

Status: research/paper-only runtime-vs-backtest consistency check. This report does not make Strategy 3 live-ready.

## Context

The closed-candle MT5 pipeline fix allowed Strategy 3 paper accumulation to advance after the local data update stalled on forming H4/D1 candles.

Latest local paper pipeline result:

- M1 rows added: 1135
- M5 rows added: 226
- M15 rows added: 74
- H1 rows added: 17
- H4 rows added: 0, quarantined/unchanged
- D1 rows added: 0, forming/unchanged
- scanner driver candles processed: 74
- paper signals detected: 27
- paper signals accepted after cooldown: 12
- cooldown-blocked signals: 15

The purpose of this branch is to verify that Strategy 3 paper/runtime scanner signals match the Strategy 3 backtest/research path on the same local data window.

## Input Files

- Paper signals: `backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv`
- Scanner summary: `backtests/reports/strategy_3_paper_shadow_scanner/scanner_summary.json`
- Data: `data/XAUUSD`
- Strategy: `strategy_3_vwap_1r`
- Cooldown: 120 minutes

## Safety Confirmation

- no live trading
- no Telegram trade signals
- no orders
- no broker execution
- no `order_send`
- no Strategy 3 entry logic changes
- no VWAP changes
- no cooldown changes

## Comparison Window

The comparison uses the scanner incremental state, not a signal-derived synthetic window:

- backtest_from: `2026-05-19T01:00:00+00:00`
- backtest_to: `2026-05-19T19:30:00+00:00`
- earliest paper signal: `2026-05-19T02:00:00+00:00`
- latest paper signal: `2026-05-19T16:00:00+00:00`
- timestamp tolerance: 0 seconds
- price tolerance: 0.01 USD

The comparison evaluates the same M15 driver-candle interval that the incremental scanner processed.

## All-Detected Comparison

| Metric | Value |
|---|---:|
| Paper signals | 27 |
| Backtest signals | 27 |
| Matched | 27 |
| Mismatched | 0 |
| Missing in backtest | 0 |
| Extra in backtest | 0 |
| Match rate | 100.00% |

## Accepted-Only Comparison

| Metric | Value |
|---|---:|
| Accepted paper signals | 12 |
| Accepted backtest signals | 12 |
| Matched | 12 |
| Mismatched | 0 |
| Missing in backtest | 0 |
| Extra in backtest | 0 |
| Match rate | 100.00% |

## Mismatch Table

No mismatches were found.

The comparison matched:

- timestamp
- direction
- entry price
- stop loss
- take profit
- setup_mode
- band_touched
- cooldown status
- VWAP/sigma context within strict tolerance

## HTF Caveat

The comparison is valid for the runtime data state that produced the paper signals, but HTF freshness still needs monitoring:

- H4 was quarantined/unchanged due overlap mismatch.
- D1 current forming candle was skipped.
- M1/M5/M15/H1 were updated correctly.

This caveat does not invalidate this runtime-vs-backtest comparison because both paths used the same local data state. It does mean HTF data repair/freshness should remain visible in future pipeline reports.

## Verdict

- `SHADOW_BACKTEST_MATCH_CONFIRMED`
- `RUNTIME_BACKTEST_CONSISTENCY_OK`
- `SHADOW_BACKTEST_ACCEPTED_MATCH_OK`
- `HTF_CONTEXT_CAVEAT_PRESENT`

Strategy 3 remains research/paper-only. This is a runtime consistency pass, not profitability validation and not deployment approval.

## Next Recommended Step

Continue paper accumulation with the closed-candle pipeline.

When more paper signals accumulate, rerun this comparison. If consistency remains high, the next research branch remains:

`feat/strategy-3-spread-slippage-model`

Do not proceed to live alerts, broker integration, or orders before spread/slippage realism and separate risk review.
