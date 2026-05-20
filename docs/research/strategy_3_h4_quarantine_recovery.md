# Strategy 3 H4 Quarantine Recovery

## Problem

The local paper pipeline advanced M1/M5/M15/H1 data through 2026-05-20, but H4 remained at `2026-05-19T00:00:00+00:00` while the MT5 collector reported closed H4 candles through `2026-05-20T16:00:00+00:00`.

The pipeline also reported:

- `OVERLAP_MATCH_LT_95`
- `HTF_OVERLAP_MISMATCH_QUARANTINED`
- `DATA_AUDIT_WARNINGS`
- `GAPS_DETECTED`

D1 remaining at `2026-05-19T00:00:00+00:00` can be expected during the 2026-05-20 trading day because the current D1 candle is still forming and closed-candle-only ingestion should skip it.

## Why This Matters

Strategy 3 paper scanning uses HTF context that includes D1, H4, and H1. If H4 is stale or quarantined, paper signals should not be treated as clean validation evidence. Runtime-vs-backtest comparison can falsely look consistent if both paths read the same stale H4 file.

## Fix

This branch adds HTF freshness diagnostics and scanner gating:

- H4/D1/H1 freshness is checked against the expected latest closed candle.
- H4 overlap diagnostics include mismatch counts, timestamps, and OHLCV examples.
- D1 previous-day lag is explicitly treated as expected when the current daily candle is still forming.
- The paper scanner blocks Strategy 3 emission when H4 is stale or quarantined.
- Blocked scanner output is marked with `STRATEGY_3_SCANNER_BLOCKED_STALE_HTF_CONTEXT`.
- Blocked/stale output is not clean paper-validation evidence.

## H4 Recovery Policy

Automatic H4 recovery is intentionally conservative.

Safe append/recovery is allowed only when overlap is valid or non-material. If H4 overlap has a material closed-candle mismatch, the pipeline keeps existing H4 quarantined and blocks clean paper validation until the mismatch is reviewed or repaired with backup.

If recovery is performed in a later step, `data/XAUUSD/H4.csv` must be backed up first as:

`data/XAUUSD/H4.csv.backup.<timestamp>`

## Reports

The H4 diagnostic report is written to:

`backtests/reports/strategy_3_h4_quarantine_diagnostic/h4_quarantine_report.json`

`backtests/reports/strategy_3_h4_quarantine_diagnostic/h4_quarantine_report.md`

The local pipeline summary now includes:

- `htf_freshness_status`
- `stale_timeframes`
- `quarantined_timeframes`
- `h4_quarantine_status`
- `h4_latest_existing_timestamp`
- `h4_expected_latest_closed_timestamp`
- `h4_stale_by_bars`
- `scanner_blocked_due_to_stale_htf`
- `paper_signals_clean_for_validation`
- `d1_closed_candle_lag_expected`

## Safety

No Strategy 3 entry logic changed.
No VWAP, sigma band, cooldown, Strategy 2, Adelin, Dynamic SL, simulator, broker execution, order sending, Telegram trade signal, or live trading path changed.

## Next Step

If H4 is recovered and fresh, resume:

`feat/strategy-3-paper-signals-comparison-post-fix`

If H4 remains stale or quarantined, continue HTF data ingestion diagnostics and do not treat paper signals as clean validation evidence.
