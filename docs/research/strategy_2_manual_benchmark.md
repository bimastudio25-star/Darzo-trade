# Strategy 2 Manual Benchmark Pack

## Context

Strategy 2 Liquidity Expansion remains research-only. The automated implementation has not reproduced the user's discretionary TAKE/SKIP quality, and previous tail-risk separators were post-hoc diagnostics only. This pack records manual benchmark decisions without turning them into strategy logic.

## Purpose

Capture manual TAKE, SKIP, and UNCERTAIN labels with reasons, screenshots, pre-entry context, and optional outcomes. A later branch can attempt to mechanize measurable reasons without leakage.

## Safety

- Strategy 3 untouched.
- Adelin untouched.
- data/XAUUSD/*.csv untouched.
- No live trading.
- No Telegram trade alerts.
- No broker execution.
- No orders.
- No signal generation.
- No optimization or target win-rate objective.

## Schema

Required TAKE fields: entry_price, stop_loss, tp1, direction, h1_liquidity_level_price, decision_time, user_reason_text.

Required SKIP fields: user_reason_text. Entry, SL, TP, and outcome fields are optional for SKIP samples.

Pre-entry fields exclude actual_outcome, final_r_multiple, gross_win_flag, decisive_win_flag, and be_flag. Outcomes are report-only and are not required for validation.

## How To Use

1. Generate the template: `python scripts/create_strategy_2_manual_label_template.py --schema manual_benchmark --output-dir backtests/reports/strategy_2_manual_benchmark`
2. Save a filled copy as `manual_labels.csv` in the same output directory.
3. Include TAKE, SKIP, and UNCERTAIN examples. Do not include only winners.
4. Run: `python scripts/analyze_strategy_2_manual_benchmark.py --labels-path backtests/reports/strategy_2_manual_benchmark/manual_labels.csv --output-dir backtests/reports/strategy_2_manual_benchmark --dry-run`

## Current Results

- total samples: `0`
- TAKE count: `0`
- SKIP count: `0`
- UNCERTAIN count: `0`
- quality distribution: `{}`
- samples with screenshots: `0`
- average SL distance: `None` price units / `None` pips
- SL >12 warnings: `0`
- TP anchor valid/invalid/unknown: `0` / `0` / `0`
- BE-after-TP1 coverage: `{}`
- top measurable tags: `[]`
- top discretionary tags: `[]`

## Outcome Metrics

- gross WR including BE/timeouts: `None`
- decisive WR excluding BE: `None`
- BE rate: `None`
- PF: `None`
- AvgR: `None`

BE is reported separately and is not collapsed into wins.

## Validation

- valid: `True`
- rows loaded: `0`
- errors: `0`
- warnings: `0`

## Verdict Flags

- `STRATEGY_2_MANUAL_BENCHMARK_FOUNDATION_CREATED`
- `STRATEGY_2_MANUAL_SAMPLE_TOO_SMALL_FOR_EDGE`
- `STRATEGY_2_NO_SKIP_CONTROL_GROUP`
- `STRATEGY_2_OUTCOME_DATA_INCOMPLETE`
- `STRATEGY_2_MANUAL_SELECTION_NEEDS_MECHANIZATION`
- `STRATEGY_2_MANUAL_SELECTION_NOT_YET_MECHANIZED`
- `STRATEGY_2_REMAINS_RESEARCH_ONLY`
- `NO_LIVE_DEPLOYMENT_DECISION`

## Next Step

Strategy 2-only next branch: `feat/strategy-2-manual-benchmark-replay-check` after the user provides filled manual labels.
