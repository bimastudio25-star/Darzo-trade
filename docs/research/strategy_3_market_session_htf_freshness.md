# Strategy 3 Market Session HTF Freshness

## Problem

After post-H4-repair paper accumulation, the pipeline and scanner summaries disagreed:

- `scanner_summary.json` treated H4 `2026-05-22T20:00:00Z` as fresh and did not block scanning.
- `pipeline_summary.json` treated H4 as `stale_blocking` because it expected `2026-05-23T00:00:00Z`.
- The final run happened on Saturday while the latest lower timeframe data ended on Friday night.

This was a reporting and freshness-reference issue, not a Strategy 3 logic issue.

## Root Cause

The scanner evaluated HTF freshness against the latest M15 driver context, while the pipeline evaluated it against wall-clock UTC from the MT5 fetch run. During a weekend or market-closed period, wall-clock time can move past the latest tradable XAUUSD candle. A naive wall-clock check can therefore expect H4/H1 candles that cannot exist yet in local market data.

## Fix

HTF freshness now reports a market reference context:

- `now_utc`
- `latest_m1_timestamp`
- `latest_m15_timestamp`
- `market_reference_timestamp`
- `market_open_assumed`
- `freshness_reference_mode`
- `expected_latest_closed_timestamp_by_timeframe`

When lower timeframe data is stale relative to wall-clock time, freshness uses `MARKET_CLOSED_LAST_AVAILABLE` and computes H1/H4 expectations from the latest available lower timeframe candle instead of from wall-clock time. This keeps Friday H4 `20:00Z` and H1 `22:00Z` fresh when the latest lower timeframe data ends at Friday close.

D1 remains warning-only unless a future Strategy 3 preflight explicitly requires fresh current-day D1 context. A multi-day D1 lag is visible as `stale_warning`, but it does not silently become an H4/H1 scanner block.

## Summary Consistency

The local paper pipeline now separates:

- fetch/overlap warnings;
- scanner HTF blocking status;
- scanner status;
- clean-validation status.

It also writes:

- `htf_freshness_status_for_scanner`
- `scanner_htf_blocking_status`
- `summary_consistency_status`
- `summary_consistency_issues`
- `paper_signals_clean_for_validation_reason`

If a summary says `no_new_driver_candles_to_process`, it cannot also claim the scanner was blocked by stale HTF unless the scanner actually reported that block. If blocking contradictions remain, `paper_signals_clean_for_validation` is forced to `false`.

## Safety

This change is infrastructure/reporting only:

- no Strategy 3 entry logic changes;
- no VWAP, sigma, or cooldown changes;
- no live trading;
- no Telegram alerts;
- no orders;
- no broker execution.

## Next Step

Once pipeline and scanner summaries agree, rerun the context-aware paper-vs-backtest comparison on post-repair/context-tagged paper rows only. If D1 remains materially stale or becomes strategy-critical, create a dedicated D1 diagnostic branch before treating paper validation as clean.
