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

With the default weekly guardrail:

```powershell
python scripts/create_adelin_v2_visual_review_pack.py --symbol XAUUSD --data-dir data --output-dir backtests/reports/adelin_v2_expanded_candidate_window_pack --max-samples 300 --min-date-range-days 180 --min-sample-spacing-minutes 240 --max-samples-per-day 5 --max-samples-per-week 20 --dry-run
```

## Regime Rules

- Request at least 180 calendar days of sample coverage when local data allows it.
- Use full available data and report a limitation if local data contains less than 180 days.
- Do not create more than 5 samples per day by default.
- Do not create more than 20 samples per ISO week by default.
- Keep candidate anchors at least 240 minutes apart by default.
- Require M15 or H1 context, M5 reaction window, and M1 execution window by default.
- Do not fake samples to fill the pack.

## Anti-Lookahead

Candidate source, direction, and entry-level metadata are derived only from candles available up to the anchor timestamp. Forward candles can be displayed in the review chart, but they are not used to decide whether a candidate enters the pack.

`SWEEP_EXTREME` metadata uses a pre-anchor sweep check: anchor candle excluded, post-anchor candles excluded, and the sweep must be at least 5 minutes before anchor.

## Volatility Buckets

The generator uses daily ATR(14) from data strictly up to the day before the anchor date.

- below the 25th percentile: `LOW`,
- 25th to below 75th percentile: `MID`,
- 75th percentile and above: `HIGH`.

It uses D1 when available, otherwise daily aggregation from H1 or M15. If ATR cannot be computed, the summary reports a limitation. The pack reports `atr_p25`, `atr_p75`, `daily_atr_at_anchor`, and `volatility_imbalance_warning`.

## Pre-Registered Decision Criteria

The criteria below are copied into `decision_criteria.md` and `review_pack_summary.json` before outcome replay. There should be no ad-hoc reinterpretation after seeing replay results.

----- BEGIN PRE-REGISTERED CRITERIA -----

CONTEXT:
We will evaluate Adelin v2 candidate detector quality by comparing
candidate metrics vs entry-source-matched + session-matched controls,
stratified by entry source.

Required minimum sample sizes per source for inference:
- SWEEP_EXTREME: candidate N >= 80
- ROUND_LEVEL:   candidate N >= 50
- SWEPT_LIQUIDITY_LEVEL: candidate N >= 50

VERDICT = CONTINUE_DETECTOR_REFINEMENT
IF AT LEAST ONE of the following holds on any source meeting min N:
  (a) candidate fast_reaction_rate >= control fast_reaction_rate + 0.07
  (b) candidate runner_rate (>= 500 pips MFE) >= control runner_rate + 0.05
  (c) candidate fast_sl20_rate <= control fast_sl20_rate - 0.10

VERDICT = STOP_ARCHIVE_DETECTOR
IF FOR ALL sources meeting min N:
  |candidate_fast_reaction - control_fast_reaction| <= 0.03
  AND candidate_fast_sl20_rate >= control_fast_sl20_rate - 0.03
  AND candidate_runner_rate <= control_runner_rate + 0.02

VERDICT = REPEAT_EXPANSION_ONCE
IF effect size (|candidate - control|) >= 0.05 on at least one metric
BUT no source has candidate N >= min N required.
Maximum one repeat. Target on repeat: 500 samples.

VERDICT = INCONCLUSIVE
For any other case. Default action: pause Adelin v2, document, do not iterate.

----- END PRE-REGISTERED CRITERIA -----

Operationally:

- `CONTINUE_DETECTOR_REFINEMENT`: continue detector implementation research only.
- `STOP_ARCHIVE_DETECTOR`: archive this detector path unless new evidence is introduced externally.
- `REPEAT_EXPANSION_ONCE`: repeat once at 500 samples, then stop using the same criteria.
- `INCONCLUSIVE`: pause Adelin v2, document, and avoid further tuning.

## Next Step

After generation, run objective outcome replay with entry-source/session-matched controls against `backtests/reports/adelin_v2_expanded_candidate_window_pack`. Decide according to the pre-registered criteria and do not keep iterating without those criteria.
