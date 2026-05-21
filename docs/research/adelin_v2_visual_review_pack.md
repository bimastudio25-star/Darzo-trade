# Adelin v2 Visual Review Pack

Status: research-only manual labeling infrastructure.

## 1. Context

The Adelin v2 operational specification already exists in `docs/research/adelin_v2_operational_spec.md`.

This branch creates a visual review pack only. It does not validate Adelin v2, does not reactivate old Adelin, and does not create trade signals.

The previous operational-audit smoke found `0` trades in this worktree because `backtests/reports/final/executed_trades.csv` was missing. For that reason, this pack supports candidate-window mode from candle data. Candidate windows are for visual labeling only and are not trade signals.

## 2. Purpose

The purpose is to collect manual labels so future research can compare the intended Adelin v2 logic against historical candles.

The pack is designed to help identify:

- A+ reversal candidates,
- valid reversal candidates,
- dirty reversal or no-trade cases,
- gap/session contamination,
- shallow-liquidity traps,
- fresh rejection retests,
- missing reaction zones,
- missing target liquidity,
- continuation blocked cases,
- rare IFVG continuation candidates for future visual review only,
- early close candidates,
- unknown or insufficient-context examples.

## 3. Safety

This branch has no live behavior.

It does not:

- enable Adelin live,
- send Telegram messages,
- call a broker,
- create an order path,
- call `order_send`,
- modify Strategy 2,
- modify Strategy 3,
- modify VWAP,
- modify market data.

The generated summary includes explicit safety flags, all false.

## 4. How To Run

```powershell
python scripts/create_adelin_v2_visual_review_pack.py --symbol XAUUSD --data-dir data --output-dir backtests/reports/adelin_v2_visual_review_pack --max-samples 40 --dry-run
```

Expanded regime pack:

```powershell
python scripts/create_adelin_v2_visual_review_pack.py --symbol XAUUSD --data-dir data --output-dir backtests/reports/adelin_v2_expanded_candidate_window_pack --max-samples 300 --min-date-range-days 180 --min-sample-spacing-minutes 240 --max-samples-per-day 5 --max-samples-per-week 20 --dry-run
```

Optional inputs:

- `--trades-path` for an old executed-trades export,
- `--audit-path` for an Adelin v2 operational audit CSV,
- `--from-date` and `--to-date` to restrict candle windows,
- `--max-samples` to cap the pack size,
- `--min-date-range-days` to request broad historical coverage,
- `--max-samples-per-day` to avoid over-sampling one event/day,
- `--max-samples-per-week` to avoid over-sampling one ISO week,
- `--min-sample-spacing-minutes` to reduce duplicate/correlated anchors,
- `--target-session-balance` to round-robin across sessions without forcing fake samples.

Default behavior is safe and research-only.

## 5. Output Files

The output directory is `backtests/reports/adelin_v2_visual_review_pack`.

It contains:

- `index.html`: main review index,
- `examples/sample_001.html`, etc.: individual sample pages,
- `charts/sample_001.svg`, etc.: SVG-lite chart fallback because matplotlib is unavailable in this environment,
- `manual_labels_template.csv`: the CSV the reviewer fills manually,
- `review_pack_summary.json`: machine-readable run summary,
- `README_manual_review.md`: reviewer instructions and allowed-value guidance.

The pack records lower-timeframe execution coverage for every sample:

- `REVIEWABLE_M1_M5`: M15 or H1 context exists, M5 reaction candles exist, and M1 execution candles exist.
- `REVIEWABLE_M5_ONLY`: M15 or H1 context exists and M5 reaction candles exist, but M1 execution candles are missing.
- `WEAK_M1_ONLY`: M15 or H1 context exists and M1 execution candles exist, but M5 reaction candles are missing.
- `INSUFFICIENT_EXECUTION_DATA`: M15/H1 context is absent, both M5 and M1 are absent, or the sample cannot show reaction quality.

Default expanded sample selection requires `REVIEWABLE_M1_M5`: M15 or H1 context, M5 reaction candles, and M1 execution candles. Lower-quality missing-M1/M5 samples are excluded unless debug flags are passed, and those samples are not labelable as A+.

The expanded summary also reports candidate source, entry source, session, month, ATR(14) volatility bucket, date coverage, max samples per day/week, and spacing skips. Candidate windows remain visual review samples, not signals.

## 6. How The User Should Label

Open `index.html`, inspect each sample, then fill `manual_labels_template.csv`.

Use `YES`, `NO`, `MAYBE`, or `UNKNOWN` for manual context fields.

Check `execution_data_status` first. Prefer `REVIEWABLE_M1_M5`. `REVIEWABLE_M5_ONLY` is acceptable but lower quality. `WEAK_M1_ONLY` lacks the M5 reaction structure Adelin v2 needs. Do not label `INSUFFICIENT_EXECUTION_DATA` samples as A+.

Focus on:

- HTF and LTF liquidity class,
- whether meaningful liquidity was taken,
- whether the liquidity is shallow or deep,
- whether a valid pre-existing reaction zone exists,
- whether FVG/IFVG/volume crack/volume profile/old rejection/number theory confluence is real,
- whether there is target liquidity or a likely reaction target,
- whether the stop is feasible within the 20 pip normal / 40 pip maximum concept,
- whether price reacts quickly after entry,
- whether accumulation or M1 engulfing would justify early close,
- whether this is reversal-first or only a blocked/future continuation concept.

Suggested setup labels:

- `A_PLUS_REVERSAL`
- `VALID_REVERSAL`
- `DIRTY_REVERSAL`
- `NO_TRADE`
- `CONTINUATION_BLOCKED`
- `RARE_IFVG_CONTINUATION_CANDIDATE`
- `UNKNOWN`

## 7. Interpretation

Candidate windows are not signals.

They are qualitative hypothesis-generation samples. They do not prove profitability, deployability, or live readiness.

For the expanded pack, the correct next research action is objective outcome replay with entry-source/session-matched controls. Manual review can still be used later, but the expanded pack is designed to reduce sample-size noise before deeper qualitative work.

## 8. Pre-Registered Decision Criteria

The expanded pack records decision criteria before outcome replay. These are descriptive project gates, not statistical proof.

These criteria are copied verbatim into `decision_criteria.md` before replay:

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

Hard rule: do not reinterpret replay results ad hoc after seeing them.

## 9. Next Branches

Possible next branches:

- `feat/adelin-v2-manual-label-profile-comparison`
- `feat/adelin-v2-reaction-zone-detectors`
- `feat/adelin-v2-liquidity-context-detectors`
- `feat/adelin-v2-paper-shadow-scanner`
