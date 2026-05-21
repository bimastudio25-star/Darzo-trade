# Adelin v2 Expanded Candidate Window Pack

Status: research-only diagnostic sampling.

## Context

The first Adelin v2 visual review pack produced 40 reviewable samples. That was enough to prove the infrastructure, but too small for deeper inference. The matched-control replay showed why: source groups such as `ROUND_LEVEL`, `SWEEP_EXTREME`, and `SWEPT_LIQUIDITY_LEVEL` had small candidate counts, so further profiling of the 40-sample pack would add noise.

This expanded pack increases sample size and broadens date/regime coverage before any new detector decision is made.

## Purpose

The expanded pack creates up to 300 candidate windows by default, with support for up to 500 through `--max-samples`. It records source, entry-level, session, month, volatility, execution coverage, and spacing metadata so outcome replay can compare candidate windows against matched controls.

Candidate windows are not signals. They are not validation and not profitability evidence.

## Safety

The expanded generator does not enable Adelin live, send Telegram messages, call a broker, create orders, modify Strategy 2, modify Strategy 3, modify VWAP, or modify market data.

## How To Run

```powershell
python scripts/create_adelin_v2_visual_review_pack.py --symbol XAUUSD --data-dir data --output-dir backtests/reports/adelin_v2_expanded_candidate_window_pack --max-samples 300 --min-date-range-days 180 --max-samples-per-day 5 --min-sample-spacing-minutes 240 --dry-run
```

## Regime Rules

- Request at least 180 calendar days of sample coverage when local data allows it.
- Use full available data and report a limitation if local data contains less than 180 days.
- Do not create more than 5 samples per day by default.
- Keep candidate anchors at least 240 minutes apart by default.
- Require M15 or H1 context, M5 reaction window, and M1 execution window by default.
- Do not fake samples to fill the pack.

## Anti-Lookahead

Candidate source, direction, and entry-level metadata are derived only from candles available up to the anchor timestamp. Forward candles can be displayed in the review chart, but they are not used to decide whether a candidate enters the pack.

`SWEEP_EXTREME` metadata uses a pre-anchor sweep check: anchor candle excluded, post-anchor candles excluded, and the sweep must be at least 5 minutes before anchor.

## Volatility Buckets

The generator uses a simple daily range bucket:

- bottom 33%: `LOW_VOLATILITY`,
- middle 33%: `MID_VOLATILITY`,
- top 33%: `HIGH_VOLATILITY`.

It uses D1 when available, otherwise daily high-low aggregation from H1 or M15. If volatility cannot be computed, the summary reports a limitation.

## Pre-Registered Decision Criteria

Useful source group: candidate `N >= 80`.

Continue detector refinement if at least one useful source meets one of:

- fast reaction rate >= matched control + `0.07`,
- runner rate >= matched control + `0.05`,
- fast SL20 rate <= matched control - `0.10` and fast reaction is no worse than matched control - `0.03`.

Stop/archive if all useful sources are flat on fast reaction and runner behavior and candidate fast SL20 is not better, or if fast SL20 is worse by `0.05` or more on all useful sources.

Repeat expansion once only if a visible but underpowered effect appears and total generated candidates are below 300 due to data constraints.

Allowed verdict values:

- `CONTINUE_DETECTOR_REFINEMENT`
- `STOP_ARCHIVE_ADELIN_V2_DETECTOR`
- `REPEAT_EXPANSION_ONCE`
- `INCONCLUSIVE_DATA_QUALITY_LIMITATION`

## Next Step

After generation, run objective outcome replay with entry-source/session-matched controls against `backtests/reports/adelin_v2_expanded_candidate_window_pack`. Decide according to the pre-registered criteria and do not keep iterating without those criteria.
