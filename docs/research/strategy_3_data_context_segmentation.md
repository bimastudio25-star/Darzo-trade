# Strategy 3 Data Context Segmentation

## Problem

The clean-context paper-vs-backtest comparison excluded 64 legacy rows and compared 71 post-repair paper rows. The signal comparison matched perfectly, but clean validation was still blocked because those 71 rows contained 70 different row-level `data_context_hash` values.

That is expected for an accumulating local CSV workflow: a signal generated at 02:30 sees a shorter file than a signal generated at 22:30. A strict full-file hash therefore changes as future candles are appended, even when the historical rows used by the signal were never modified.

## Method

The comparison now keeps the raw full-file SHA-256 hash for audit, but adds prefix-compatible validation.

For each paper row with recorded timeframe context fields, the comparison reconstructs the current file prefix up to the paper row's recorded latest timestamp and checks that prefix against the hash recorded at signal time. The current metadata supports this for the recorded Strategy 3 context fields:

- `m15_hash` with `m15_latest_timestamp`
- `h4_hash` with `h4_latest_timestamp`

This proves that future appended bars changed the full-file hash without changing the historical prefix used by the signal. If a historical row changes before the cutoff, the prefix hash changes and clean validation remains blocked.

## Modes

- `strict_full_hash`: requires a single row-level full-file hash that matches the backtest context.
- `prefix_compatible`: allows multiple full-file row contexts only when every selected paper row is prefix-compatible.
- `sidecar_only`: diagnostic mode using scanner sidecar context only; it does not silently prove row-level compatibility.

The clean-context comparison uses `prefix_compatible` with `paper_latest_per_timeframe`.

## Verdict Rules

Clean runtime/backtest consistency can pass only when:

- legacy rows without `data_context_hash` are excluded;
- scanner sidecar context is coherent with current backtest data;
- every clean paper row is prefix-compatible or otherwise strictly matched;
- no prefix mismatch or required metadata insufficiency exists;
- accepted-only signal match rate is at least 95%;
- HTF freshness remains clean enough for scanner validation.

This is runtime/backtest consistency evidence only. It is not profitability evidence and it does not approve live trading.

## Next Step

If the segmented clean-context comparison remains 100% matched and prefix-compatible, Strategy 3 may proceed to VWAP trend-regime diagnostics or continue paper accumulation with the same data-context checks active.
