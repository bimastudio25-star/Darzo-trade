# Human-Style Trade Management, M5 Logger, and Local AI Judge

Status: research-only. This branch does not create or enable a live trading system.

## Purpose

This branch adds a report-only framework for studying human-style trade management on existing Darzo Trade exports. It evaluates trades candle by candle, labels M5 decision quality, logs reaction/retest/runner context, prepares future human labels, and compares Strategy 2 management variants by hour/session.

It does not place orders, send Telegram trade alerts, activate live filters, or change strategy entry logic.

## Why This Exists

The current rigid bot model is close to:

`entry -> fixed SL -> fixed TP`

Human Strategy 2-like execution appears to include active management:

- BE/protection after about +10.00 XAUUSD favorable movement.
- Partial profits around +15.00 and +20.00 XAUUSD favorable movement.
- M5 candle close judgement.
- Retest awareness after favorable movement.
- Re-entry awareness after BE and healthy retest.
- Runners toward liquidity or structure when context supports continuation.

These are benchmark hypotheses to measure, not validated truths.

## Price Movement, Not Account Dollars

The +10/+15/+20 thresholds are XAUUSD price movement thresholds. They are not fixed account-dollar profit. Account P/L depends on lot size, contract size, spread, commission, and slippage.

## +20 Is Not Maximum TP

+15/+20 are partial/protection zones. They are not the final maximum target.

Final targets can be dynamic:

- internal or external liquidity;
- HTF high/low;
- previous day/session high/low;
- VWAP/sigma targets;
- structure targets;
- trend or reversal runner context.

The new runner detector exports `runner_opportunity`, `liquidity_target_price`, `dynamic_target_distance_usd`, `dynamic_target_R`, reason codes, and blockers.

## BE Caveat

Hard BE can prematurely exit good trades. That is why this branch compares:

- hard BE at +10;
- M5-confirmed BE at +10;
- structural BE at +10;
- retest-aware hold after a healthy return to entry/structure.

When structure data is missing, structural BE falls back to hard BE and records that limitation.

## M5 Close Quality

`evaluate_m5_close_quality(...)` labels M5 closes as:

- `GOOD_CLOSE`: directional close with useful body, strong close location, and retained displacement.
- `ACCEPTABLE_CLOSE`: not perfect, but not invalidating.
- `BAD_CLOSE`: weak or adverse close, large rejection wick, poor body, or absorbed displacement.
- `INVALIDATING_CLOSE`: close through an invalidation/key level or severe absorption.

The output includes a score and reason codes.

## Reaction

`evaluate_reaction_state(...)` labels early post-entry reaction as:

- `REACTION_ALIVE`: favorable acceptance, follow-through, and preserved higher-low/lower-high structure.
- `REACTION_WEAK`: stalled or indecisive reaction.
- `REACTION_DEAD`: absorbed displacement, adverse close sequence, or broken expected structure.

## Retest

`evaluate_retest_quality(...)` distinguishes:

- `HEALTHY_RETEST`: price returns after favorable movement, holds the level, and confirms continuation.
- `FAILED_RETEST`: price closes through level/invalidation or fails to react.
- `RETEST_PENDING`: level held, but confirmation is not yet available.
- `NO_RETEST`: no valid return to the watched level.

A return to entry after +10 is not automatically bad. It can be a healthy retest, a BE stopout before continuation, or a true failure depending on the close and next-candle confirmation.

## Entry Quality Scaffold

`evaluate_entry_quality(...)` adds report-only labels:

- `TRADE_NOW`
- `WAIT_RETEST`
- `NO_TRADE_PRICE_ESCAPED`
- `NO_TRADE_DIRTY_SETUP`
- `NO_TRADE_INSUFFICIENT_TARGET_SPACE`

These labels do not block live trades. They are exported for research and future supervised comparison.

## Strategy 2 Human Benchmark

A human Strategy 2-like trader reports about 3.36 average RR and 62% WR, with the current best window around 14:00-16:00. These are unverified benchmark hypotheses.

The important behavioral difference is that the human trader reportedly uses BE/protection, partials, M5 judgement, retest handling, and runners instead of rigid full TP/SL. The diagnostics test whether this management layer and the 14:00-16:00 window help explain the gap.

The branch exports:

- `strategy_2_hourly_session_breakdown.csv`
- `strategy_2_hourly_session_summary.json`
- `strategy_2_14_16_report.md`
- `strategy_2_management_variants.csv`
- `strategy_2_management_variants_summary.json`

No 14:00-16:00 live filter is activated.

## Local AI Judge

`dazro_trade/analysis/local_ai_trade_judge.py` is optional and disabled by default:

- `DARZO_LOCAL_AI_ENABLED=false`
- `DARZO_LOCAL_AI_PROVIDER=ollama`
- `DARZO_LOCAL_AI_BASE_URL=http://localhost:11434`
- `DARZO_LOCAL_AI_MODEL=qwen3:8b`
- `DARZO_LOCAL_AI_TIMEOUT_SECONDS=30`

The AI judge receives structured trade/candle data and must return strict JSON with M5 close quality, reaction state, retest quality, runner opportunity, suggested action, confidence, reason codes, and notes.

It cannot trade, send Telegram alerts, modify rules, or decide live orders. Invalid JSON is logged as `ai_judge_status = invalid_json` and the report continues.

## Human Labels

The per-trade export prepares empty columns for future manual comparison:

- `human_would_enter`
- `human_would_skip`
- `human_would_hold`
- `human_would_exit`
- `human_would_partial`
- `human_would_let_run`
- `human_would_reenter`
- `human_decision`
- `human_reason`
- screenshots before/after/final

It also prepares comparison fields for bot vs AI vs human and error categories such as `entered_but_human_would_skip`, `moved_BE_too_early`, `failed_to_reenter_after_BE`, `missed_runner`, `missed_healthy_retest`, and `ignored_bad_m5_close`.

## Report Command

```bash
python scripts/analyze_human_trade_management_overlay.py --symbol XAUUSD --data-dir data --trades-path backtests/reports/final/executed_trades.csv --output-dir backtests/reports/human_style_trade_management_overlay --be-trigger-usd 10 --partial-triggers-usd 15,20 --partial-fraction 0.50 --dry-run
```

If the trade export is missing or lacks required fields, the script writes limitations and still produces synthetic unit-level examples. It does not run a heavy backtest.

## Future Full 3-Month Validation

After smoke, limited, and intermediate validation prove the modules are working, a deliberate full 3-month, 24-hour XAUUSD diagnostic backtest should be run in a separate branch.

The purpose is diagnostic explanation, not blind optimization:

- identify best and worst hours;
- verify or reject the 14:00-16:00 hypothesis;
- compare Strategy 2 full TP/SL baseline vs BE/partial/M5/retest/runner overlays;
- classify winners and losers by reason codes;
- explain whether failures come from bad hour/session, chased price, dirty setup, no target space, bad M5 close ignored, dead reaction, failed retest, hard BE too early, missed runner, target problems, liquidity target problems, or spread/slippage sensitivity.

Do not run that full backtest in this branch.

## Possible Next Branches

- `feat/local-ai-m5-trade-judge-runtime-paper`
- `feat/strategy-2-human-management-intermediate-run`
- `feat/full-3month-diagnostic-after-management-modules`
