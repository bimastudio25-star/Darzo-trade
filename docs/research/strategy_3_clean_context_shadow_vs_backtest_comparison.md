# Strategy 3 Clean-Context Shadow vs Backtest Comparison

## Context

This comparison was run after the H4 repair, data-context checks, and market-session HTF freshness fixes.

Legacy paper rows without `data_context_hash` were excluded. Only post-repair/context-tagged Strategy 3 paper rows were compared against a narrow backtest window.

Strategy 3 remains paper-only. This report validates runtime/backtest consistency only; it does not validate profitability and does not approve live trading.

## Safety

- no live trading
- no Telegram
- no orders
- no broker execution
- no Strategy 3 entry logic changes
- no VWAP, sigma, or cooldown changes

## Inputs

- `backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv`
- `backtests/reports/strategy_3_paper_shadow_scanner/scanner_summary.json`
- `backtests/reports/strategy_3_paper_shadow_scanner/paper_signals_data_context.json`
- `backtests/reports/strategy_3_local_paper_pipeline/pipeline_summary.json`
- `data/XAUUSD`

## Segmentation

- total paper rows: 135
- legacy rows excluded: 64
- context-tagged rows compared: 71
- context-tagged accepted: 26
- context-tagged blocked: 45
- clean row span: `2026-05-21T02:30:00+00:00` to `2026-05-22T22:30:00+00:00`
- unique row-level `data_context_hash` values: 70

The scanner sidecar data context matched the current backtest data context, but the per-row context hashes were not a single hash. This means the signal-level comparison is useful, but clean validation is blocked until data-context segmentation semantics are made explicit.

## Data Integrity

- H4 freshness: fresh
- H4 stale_by_bars: 0
- H4 post-repair OHLC match rate: 1.0
- H4 OHLCV mismatch remains volume-only and non-blocking
- D1 remains warning-only under the market-session freshness rules

## Results

- paper detected/accepted/blocked: 71 / 26 / 45
- backtest detected/accepted/blocked: 71 / 26 / 45
- all-detected match rate: 1.0
- accepted-only match rate: 1.0
- mismatch summary: none

## Verdict Flags

- `SCANNER_SIDECAR_DATA_CONTEXT_MATCH`
- `LEGACY_ROWS_EXCLUDED`
- `CLEAN_CONTEXT_ONLY`
- `MULTIPLE_DATA_CONTEXTS_REQUIRE_SEGMENTATION`
- `COMPARISON_NOT_CLEAN_VALIDATION`
- `DATA_CONTEXT_MISMATCH`
- `PAPER_SIGNALS_NOT_CLEAN_FOR_VALIDATION`
- `CLEAN_CONTEXT_SIGNAL_MATCH_OK_DIAGNOSTIC`
- `NO_LIVE_DEPLOYMENT_DECISION`
- `STRATEGY_3_REMAINS_PAPER_ONLY`

## Interpretation

The runtime scanner and backtest path produced identical Strategy 3 signals over the post-repair context-tagged paper rows. That is strong consistency evidence.

However, clean validation is not declared because the paper rows contain many row-level data context hashes. This is probably caused by append-only data growth across repeated pipeline runs, but the current raw-file hash policy treats each append as a new full data context.

The comparison therefore remains diagnostic rather than a clean gate-pass.

## Next Recommended Branch

`fix/strategy-3-data-context-segmentation`

That branch should define whether append-only context changes can be validated by segment, prefix hash, or timestamp-bounded data context before proceeding to VWAP regime diagnostics or spread/slippage modeling.
