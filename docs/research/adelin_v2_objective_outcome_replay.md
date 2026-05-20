# Adelin v2 Objective Outcome Replay

## Context

Adelin v2 remains research-only. The visual review pack provides 40 reviewable M1/M5/M15/H1 candidate windows, but static chart review alone can introduce subjective noise. This replay layer measures what happened after those windows with deterministic rules and a matched random-control baseline.

This is not validation, signal generation, ML training, or live-readiness work.

## Purpose

The replay asks narrow diagnostic questions:

- Did candidate windows react quickly after the proposed liquidity/reaction area?
- Did they reach +100 pips within the first 15 minutes more often than controls?
- Did they hit 20/40 pip stop thresholds before any useful reaction?
- Did they chop around entry or return to breakeven after a +100 pip move?
- Are runner labels meaningful against a random-control baseline?

The control group is a baseline comparison only, not proof of edge.

## Safety

The replay module only reads visual-pack metadata and historical candle CSVs. It does not enable Adelin live, import broker/order execution, send Telegram messages, or modify Strategy 2, Strategy 3, VWAP, or market data.

Summary outputs include explicit safety flags:

- `live_trading_enabled: false`
- `telegram_enabled: false`
- `broker_execution_enabled: false`
- `order_execution_enabled: false`
- `strategy_2_touched: false`
- `strategy_3_touched: false`
- `data_modified: false`

## Pip Size

The replay first resolves XAUUSD pip size from the project symbol registry in `dazro_trade.core.symbols`. In this repo, XAUUSD uses `pip_size = 0.10`, meaning 1 pip equals 0.1 USD.

If a future symbol lacks a project convention, a documented fallback can be used, but the selected `pip_size` and `pip_size_source` are always written to CSV/JSON/markdown outputs.

## Replay Rules

Default command:

```bash
python scripts/analyze_adelin_v2_objective_outcome_replay.py --symbol XAUUSD --data-dir data --visual-pack-dir backtests/reports/adelin_v2_visual_review_pack --output-dir backtests/reports/adelin_v2_objective_outcome_replay --forward-hours 4 --direction-lookback-minutes 30 --reaction-fast-minutes 15 --reaction-slow-minutes 30 --include-control-random 40 --dry-run
```

The default forward window is 4 hours. Forward windows above 4h may overstate runner quality on XAUUSD because large eventual movement can make weak samples look better than they were.

## Direction Inference

Direction is inferred deterministically from reversal logic:

- M5 is checked first.
- M1 is checked second only if M5 is unclear.
- An upward sweep of a recent local high implies `SHORT`.
- A downward sweep of a recent local low implies `LONG`.
- If no clear sweep exists, the row is labeled `UNKNOWN_DIRECTION`.

The replay does not invent direction when the lookback window is ambiguous.

## Entry Hypothesis

Version 1 uses only `ROUND_LEVEL_TOUCH_ENTRY`.

If the visual sample has a number-theory or round level, that level is used as the transparent entry hypothesis. If not, the nearest round level at the anchor price may be used only when it is within the conservative threshold. Otherwise the row is labeled `UNKNOWN_ENTRY_LEVEL`.

`ANCHOR_CLOSE_ENTRY` and sweep-extreme entry variants are intentionally excluded from this branch.

## Outcome Labels

Outcome labels are deterministic and prioritize missing prerequisites, fast stop-outs, reaction speed, dirty/chop behavior, breakeven management, and runner behavior within the 4h window.

Key labels include:

- `UNKNOWN_ENTRY_LEVEL`
- `UNKNOWN_DIRECTION`
- `UNKNOWN_INSUFFICIENT_FORWARD_DATA`
- `FAST_SL_20`
- `FAST_SL_40`
- `NO_REACTION`
- `GOOD_FAST_REACTION`
- `GOOD_SLOW_REACTION`
- `GOOD_REACTION_BUT_DIRTY_ACCUMULATION`
- `MFE_GOOD_BUT_BE_REQUIRED`
- `RUNNER_CANDIDATE`
- `STRONG_RUNNER`

## Control Group

The matched control group uses the same symbol, available date range, M1/M5/M15/H1 coverage requirements, round-level entry hypothesis, and direction-inference rules. It avoids exact overlap with candidate anchors and attempts to preserve session distribution where possible.

The output compares candidate and control rates for fast reaction, fast 20-pip stop, runner candidates, and unknown rows.

## Output Files

Output directory:

`backtests/reports/adelin_v2_objective_outcome_replay`

Files:

- `objective_outcome_replay.csv`
- `objective_outcome_replay_summary.json`
- `objective_outcome_replay.md`
- `index.html`
- `enriched_manual_labels_template.csv`

## Interpretation

Candidate windows remain candidate windows, not signals. The control group is only a baseline diagnostic. This branch does not validate profitability, deployability, or live readiness.

## Next Step

Recommended next branch:

`feat/adelin-v2-outcome-profile-review`

That branch can compare objective replay behavior against any filled manual labels and decide which detector work is worth implementing next.
