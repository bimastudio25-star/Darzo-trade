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

The first replay run exposed an important limitation: 33 of 40 candidate rows were labeled `UNKNOWN_ENTRY_LEVEL`. That meant only 7 candidate rows had a usable v1 entry level, so the candidate-vs-control comparison was descriptive but too under-covered to interpret as strategy evidence.

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
python scripts/analyze_adelin_v2_objective_outcome_replay.py --symbol XAUUSD --data-dir data --visual-pack-dir backtests/reports/adelin_v2_visual_review_pack --output-dir backtests/reports/adelin_v2_objective_outcome_replay --forward-hours 4 --direction-lookback-minutes 30 --reaction-fast-minutes 15 --reaction-slow-minutes 30 --include-control-random 800 --control-match-entry-source --control-match-session --control-random-seed 42 --sweep-control-lookback-minutes 60 --sweep-control-min-anchor-delay-minutes 5 --dry-run
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

Version 1 keeps one replay hypothesis type, `ROUND_LEVEL_TOUCH_ENTRY`, but now records the entry-level source more explicitly.

Supported entry-level sources:

- `ROUND_LEVEL`: high confidence when explicitly present in visual metadata, medium confidence when the anchor price is conservatively near a round level.
- `SWEEP_EXTREME`: low/medium confidence heuristic from the deterministic M1/M5 sweep that inferred direction. For a long it uses the downward sweep low; for a short it uses the upward sweep high.
- `SWEPT_LIQUIDITY_LEVEL`: low/medium confidence heuristic when an explicit swept-liquidity level exists, or when the inferred sweep level is available but the sweep extreme is not.
- `UNKNOWN`: no defensible entry level.

`FVG_BOUNDARY`, `IFVG_BOUNDARY`, `REACTION_ZONE_LEVEL`, and `ANCHOR_LEVEL` are reserved source classes. This branch does not extract FVG/IFVG levels because those detectors are not implemented and tested yet.

If an entry level conflicts with the deterministic reversal direction, the row is marked with `ENTRY_DIRECTION_CONFLICT` and directional replay is not forced.

The replay writes `entry_level_source`, `entry_price`, `entry_level_confidence`, `entry_level_reason_codes`, and `entry_level_is_heuristic` for every row.

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

The matched control group uses the same symbol, available date range, M1/M5/M15/H1 coverage requirements, entry-level source type, and session regime. It avoids exact overlap with candidate anchors.

The previous control comparison was structurally weak because candidates were mostly `SWEEP_EXTREME` while controls were all `ROUND_LEVEL`. This branch makes entry-source matching and session matching default behavior.

Session matching is mandatory by default because XAUUSD behavior changes materially across Asia, London, New York, and late-day regimes. If a control cannot match the target candidate session, it is skipped unless `--allow-unmatched-session-controls` is explicitly used for debugging.

`--include-control-random` now defaults to `800` because the candidate groups are small. More controls stabilize descriptive baseline rates, but they do not create statistical proof.

The output compares candidate and control rates for fast reaction, fast 20-pip stop, runner candidates, and unknown rows.

Reports now include:

- entry-level source counts,
- session distributions,
- control generation attempts/success by source and session,
- control skip reasons,
- unknown entry-level count and rate,
- candidate/control known-entry counts,
- outcome counts by entry-level source,
- candidate-vs-control metrics for all rows,
- candidate-vs-control metrics for known-entry rows,
- entry-source matched metrics,
- entry-source and session matched metrics,
- descriptive effect sizes for fast reaction and fast SL20.

Entry-source/session-matched controls improve baseline quality but are still descriptive and not validation.

## Anti-Lookahead Controls

For `SWEEP_EXTREME` controls, sweep detection uses only candles in `[anchor - 60 minutes, anchor)`.

The control generator:

- excludes the anchor candle,
- excludes all post-anchor candles,
- requires the sweep candle to be at least 5 minutes before the anchor,
- verifies rejection or move-away using only pre-anchor candles,
- infers direction from the pre-anchor sweep only,
- sets the entry to the pre-anchor sweep extreme.

Controls are never selected by future favorable movement.

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

Reducing `UNKNOWN_ENTRY_LEVEL` is useful only when the new level is transparent and defensible. Sweep-extreme entries are heuristic replay anchors, not trade recommendations.

Even with matched controls, candidate sample sizes remain small:

- `SWEEP_EXTREME` candidates are roughly two dozen rows,
- `ROUND_LEVEL` candidates are fewer than ten rows,
- `SWEPT_LIQUIDITY_LEVEL` candidates are too few and do not yet have a defensible matched-control generator.

Do not report statistical significance. Do not claim edge. Report descriptive rates and effect sizes only.

## Next Step

Recommended next branch:

`feat/adelin-v2-outcome-profile-review`

That branch can compare objective replay behavior against any filled manual labels and decide which detector work is worth implementing next.
