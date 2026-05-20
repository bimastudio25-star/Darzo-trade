# Strategy 3 Runtime Comparison Diagnostics

Status: diagnostic-only. Strategy 3 remains research/paper-only.

## Context

The post-H4-repair paper-vs-backtest comparison produced useful but incomplete alignment:

- all-detected match rate: `92.31%`
- accepted-only match rate: `93.10%`
- accepted-only gate: `< 95%`, so this is not a clean pass

H4 is not the active blocker anymore:

- H4 freshness: `fresh`
- H4 stale_by_bars: `0`
- post-repair H4 OHLC match rate: `1.0`
- remaining H4 mismatch: volume-only, non-blocking for this price-level comparison

## Safety

- no live trading
- no Telegram
- no orders
- no broker execution
- no `order_send`
- no Strategy 3 logic changes
- no VWAP, sigma, or cooldown changes
- diagnostics only

## Inputs

- comparison summary: `backtests/reports/strategy_3_shadow_vs_backtest_comparison_post_fix/comparison_summary.json`
- all detected comparison: `backtests/reports/strategy_3_shadow_vs_backtest_comparison_post_fix/comparison_all_detected.csv`
- accepted-only comparison: `backtests/reports/strategy_3_shadow_vs_backtest_comparison_post_fix/comparison_accepted_only.csv`
- mismatch details: `backtests/reports/strategy_3_shadow_vs_backtest_comparison_post_fix/mismatch_details.csv`
- paper signals: `backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv`
- scanner summary: `backtests/reports/strategy_3_paper_shadow_scanner/scanner_summary.json`
- pipeline summary: `backtests/reports/strategy_3_local_paper_pipeline/pipeline_summary.json`

## Mismatch Overview

The diagnostic analyzed 12 mismatch category rows from 8 source mismatch rows.

Classification summary:

- `LEVEL_PRE_REPAIR_DATA_CONTEXT_DRIFT`: 8
- `PRE_REPAIR_DATA_CONTEXT_SIGNAL_DIFF`: 3
- `COOLDOWN_PREVIOUS_SIGNAL_HISTORY_DIFF`: 1

Verdict flags:

- `RUNTIME_COMPARISON_DIAGNOSTIC_COMPLETE`
- `LEVEL_MISMATCH_ROOT_CAUSE_FOUND`
- `COOLDOWN_MISMATCH_ROOT_CAUSE_FOUND`
- `PRE_REPAIR_DATA_CONTEXT_EXPLAINS_MISMATCHES`
- `NO_LIVE_DEPLOYMENT_DECISION`
- `STRATEGY_3_REMAINS_PAPER_ONLY`

## Root-Cause Analysis

The mismatches are explained by comparing pre-repair paper rows against repaired local data.

The H4 repair completed at:

`2026-05-20T22:29:09.742322+00:00`

All mismatched paper rows were generated before that timestamp. The backtest side was rebuilt after the H4 repair, so it uses corrected H4 data. That makes the comparison useful as a diagnostic, but not a clean apples-to-apples validation for the pre-repair rows.

## Level Mismatches

Affected timestamps:

- `2026-05-20T02:00:00+00:00`
- `2026-05-20T11:15:00+00:00`
- `2026-05-20T11:45:00+00:00`

The mismatched rows have exact timestamp, direction, setup mode, band touched, and entry price alignment. The mismatch is in stop loss and take profit only, with max absolute level drift around `0.68`, which is too large to be rounding-only.

Classification:

`LEVEL_PRE_REPAIR_DATA_CONTEXT_DRIFT`

Interpretation:

The paper rows were generated before H4 was repaired. The current backtest path uses repaired H4 context. This is not evidence that Strategy 3 entry logic diverged; it is evidence that the comparison should segment or exclude paper rows generated under stale/repaired-later data context.

## Cooldown Mismatch

Affected timestamp:

`2026-05-20T03:30:00+00:00`

Classification:

`COOLDOWN_PREVIOUS_SIGNAL_HISTORY_DIFF`

Cause:

Backtest includes an extra accepted SHORT signal at:

`2026-05-20T01:45:00+00:00`

That changes the backtest same-symbol/same-direction cooldown history. The paper side does not include that SHORT signal, so the later `03:30` SHORT is accepted by paper but blocked by the reconstructed backtest path.

This is downstream of the pre-repair data-context signal difference, not a proven cooldown logic bug.

## Missing/Extra Signal Mismatch

Affected timestamps:

- extra in backtest: `2026-05-20T01:45:00+00:00`
- missing in accepted-only backtest: `2026-05-20T03:30:00+00:00`

Classification:

`PRE_REPAIR_DATA_CONTEXT_SIGNAL_DIFF`

Interpretation:

The extra/missing pair is the main accepted-only mismatch. It is consistent with the paper side having been generated before H4 repair while the backtest side was regenerated after H4 repair.

## Harmless Or True Divergence?

This is not harmless/reporting-only in the sense that the raw 64-row cumulative comparison should not be treated as a clean 95%+ validation set.

It is also not proven true Strategy 3 runtime/backtest divergence. The best current diagnosis is:

`pre-repair paper data-context contamination`

The current comparison should be treated as `PASS_WITH_LIMITATIONS`, not as a clean consistency pass.

## Recommendation

Next branch:

`fix/strategy-3-comparison-reporting-alignment`

Goal:

- segment paper signals by data-integrity era
- mark pre-H4-repair rows as not clean for post-repair validation
- compare only paper rows generated after the data context became clean
- avoid using the latest scanner summary flag as proof that every historical paper row is clean

Do not change Strategy 3. Do not change VWAP, sigma, or cooldown. Do not proceed to spread/slippage until a clean post-repair comparison reaches the required threshold or the comparison denominator is explicitly scoped to clean rows.
