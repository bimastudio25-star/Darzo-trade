# Adelin v3 Composite Multi-Condition Detector Specification

Status: draft research-only foundation. Adelin v2 detector is paused after the locked `INCONCLUSIVE` verdict.

Adelin v3 is a materially new hypothesis. It does not test isolated proxies such as `ROUND_LEVEL` or `SWEEP_EXTREME` by themselves. A setup is valid only if all hard conditions C1-C5 are satisfied simultaneously with pre-anchor data.

This specification does not enable live trading, Telegram, broker execution, orders, Strategy 2, Strategy 3, or VWAP changes.

## Core Principle

Adelin v3 is a reversal model:

1. Price sweeps an aged Daily or H1 swing liquidity level.
2. Price continues beyond that swept level.
3. Price reaches a reaction zone beyond the level.
4. The reaction zone is the hypothesized cause of reversal.
5. Entry is near the reaction zone, not from a standalone sweep or round-number proxy.

## C1 - Sweepable Level Source

The swept level must be a swing high or swing low from one of:

- Daily swing, priority `HIGH`, age at least 24 hours from formation.
- H1 swing, priority `MEDIUM`, age at least 6 hours from formation.

M5 and M15 swings are not setup-grade C1 levels.

Anti-lookahead: the swing level must be known before anchor. The detector uses confirmed fractal swing points and requires `known_at < anchor`.

## C2 - Reaction Zone Present

At least one reaction zone must exist within 50 pips, or 5.0 USD on XAUUSD, beyond the swept level:

- Long: reaction zone is below the swept low.
- Short: reaction zone is above the swept high.

Supported first-pass reaction zone proxies:

- `FVG`: M5 three-candle fair value gap, minimum 5 pips. For a candidate touch, the gap must be unmitigated before the last completed pre-anchor touch candle.
- `IFVG`: same gap structure, already mitigated, retested from the opposite side by the last completed pre-anchor M5 candle.
- `VOLUME_CRACK`: M5 candle with volume at least 2.5 times the previous 20 M5 average and body at least 70% of range, breaking through the swept level.
- `LVN_SANDWICH`: rolling 24-hour M5 volume profile, 5-pip bins, at least two consecutive LVN bins between HVN bins.

The IFVG retest definition is strict: the last completed pre-anchor M5 candle must touch or retest the IFVG zone. A retest that happens only in the anchor candle is rejected.

## C3 - Number Theory Confluence

The C1 swept level must be within 20 pips, or 2.0 USD on XAUUSD, of a round number.

Round number means the last digit of the four significant price digits is `0`, such as `4900`, `4910`, or `4830`. Levels like `4825` and `4917` are not round numbers.

## C4 - Multi-Timeframe Liquidity Confluence

At least one configuration must hold:

- Config A: H4 internal liquidity and M5 or M1 external liquidity are within 10 pips.
- Config B: Daily swing high or low and M15 sweep level are within 15 pips.

The current detector implements deterministic approximations of these definitions. Missing confluence is a hard rejection.

## C5 - Direction Inference

Corrected rule:

- Long means price swept the low of the C1 level and the reaction zone is below the swept low, beyond the level in the same direction as the sweep.
- Short means price swept the high of the C1 level and the reaction zone is above the swept high, beyond the level in the same direction as the sweep.
- If both the high and low of the H1 reference are taken within the same hour, consider only the level taken first.

Direction must be computable using only pre-anchor data.

## C6 - Continuation Filter

No continuation filter is applied in v3. The composite structure itself is intended to bias the detector toward reversals.

## Soft Metadata

Session is logged but not used as a filter:

- Asia open: 01:30-03:00 UTC
- London open: 08:30-10:00 UTC
- New York open: 14:30-16:00 UTC

News is not filtered. A future branch may tag news, but it must not invalidate candidates by default.

## Post-Entry Management For Future Replay

These rules are for outcome replay only, not candidate generation:

- Default SL: 20 pips.
- Max SL: 40 pips.
- If reaction zone width exceeds 20 pips, SL is the opposite edge of the reaction zone, capped at 40 pips.
- BE trigger: +100 pips MFE or one positive H1 close.
- TP: runner to next opposing liquidity or opposing reaction zone.
- Manual-close proxy: M1 engulfing against the trade after at least 30 minutes of accumulation.

## Anti-Lookahead Rules

All conditions must be verifiable with timestamps strictly before anchor:

- Swing level age is computed from candle formation and known timestamps.
- FVG, IFVG, volume crack, and LVN sandwich use pre-anchor M5 candles only.
- The volume profile window is `[anchor - 24h, anchor)`, with completed pre-anchor candles only.
- Sweep candle close must be at least 5 minutes before anchor.
- Direction is inferred from the pre-anchor sequence only.

## Pre-Registered Future Replay Criteria

When matched-control replay is run on v3 candidates:

```text
VERDICT = CONTINUE_REFINEMENT
IF any of (with N >= 30 candidates):
  (a) candidate fast_reaction_rate >= control + 0.10
  (b) candidate runner_rate >= control + 0.07
  (c) candidate fast_sl20_rate <= control - 0.10

VERDICT = STOP_ARCHIVE_V3
IF for all metrics with N >= 30:
  |candidate - control| <= 0.04

VERDICT = INSUFFICIENT_SAMPLE
IF N < 30 candidates.
Default action: pause v3, no further iteration without a different hypothesis.

VERDICT = INCONCLUSIVE
Otherwise. Default action: pause.
```

If the candidate pack has fewer than 30 candidates, do not run matched-control replay.

## Output Pack

The foundation branch writes:

- `candidate_pack.csv`
- `generation_summary.json`
- `rejection_breakdown.csv`
- `decision_criteria.md`
- `index.html`
- `README.md`
- `examples/*.html`
- `charts/*.svg`

Candidate windows are not signals. This branch makes no profitability or validation claim.
