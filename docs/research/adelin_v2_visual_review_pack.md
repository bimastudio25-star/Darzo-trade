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

Optional inputs:

- `--trades-path` for an old executed-trades export,
- `--audit-path` for an Adelin v2 operational audit CSV,
- `--from-date` and `--to-date` to restrict candle windows,
- `--max-samples` to cap the pack size.

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

The pack now records lower-timeframe execution coverage for every sample:

- `REVIEWABLE_M1_M5`: M15 context plus M1 and M5 execution/reaction candles are present.
- `REVIEWABLE_M5_ONLY`: M15 context plus M5 candles are present, but M1 is missing.
- `WEAK_M1_ONLY`: M15 context plus M1 candles are present, but M5 is missing.
- `INSUFFICIENT_EXECUTION_DATA`: M15 context is missing, or both M1 and M5 are missing.

Default sample selection prefers `REVIEWABLE_M1_M5`, then `REVIEWABLE_M5_ONLY`, then `WEAK_M1_ONLY`. Insufficient samples are included only if needed to fill the pack and are clearly marked.

## 6. How The User Should Label

Open `index.html`, inspect each sample, then fill `manual_labels_template.csv`.

Use `YES`, `NO`, `MAYBE`, or `UNKNOWN` for manual context fields.

Check `execution_data_status` first. Do not label `INSUFFICIENT_EXECUTION_DATA` samples as A+; if both M1 and M5 are absent, the setup is not reviewable enough for Adelin v2 execution/reaction quality.

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

The correct next human action is to fill the manual label CSV and return it for profile comparison.

## 8. Next Branches

Possible next branches:

- `feat/adelin-v2-manual-label-profile-comparison`
- `feat/adelin-v2-reaction-zone-detectors`
- `feat/adelin-v2-liquidity-context-detectors`
- `feat/adelin-v2-paper-shadow-scanner`
