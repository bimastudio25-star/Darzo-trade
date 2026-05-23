# Strategy 3 Paper Lifecycle Outcome Tracker

This tracker is paper-only. It does not send alerts, enable Telegram, call broker execution, place orders, size positions, or change Strategy 3 logic.

## Objective

Track accepted Strategy 3 paper signals after detection and classify their report-only lifecycle and outcome using forward closed candles.

## Inputs

- paper signals: `backtests\reports\strategy_3_paper_shadow_scanner\paper_signals.csv`
- evidence refresh summary: `backtests\reports\strategy_3_paper_evidence_refresh\paper_evidence_refresh_summary.json`
- dashboard summary: `backtests\reports\strategy_3_paper_accumulation_dashboard\paper_accumulation_summary.json`
- data directory: `data`

## Methodology

- fill model: `PAPER_REFERENCE_FILL_AT_SIGNAL`
- fill model reason: Strategy 3 paper scanner records entry_price as current_price/reference price at the decision timestamp; backtest simulation evaluates forward M1 after the cutoff.
- forward timeframe used: `M1`
- forward candles start: `strictly_after_signal_decision_timestamp`
- timeout policy source: `BACKTEST_MAX_SIM_BARS_480`
- max forward bars: `480`
- ambiguous intrabar policy: TP and SL touched inside the same candle are AMBIGUOUS_INTRABAR and excluded from decisive win rate.
- pip convention: `1_USD_10_PIPS`

## Lifecycle States

- `SIGNAL_ACCEPTED`
- `SIGNAL_BLOCKED`
- `ENTRY_FILLED`
- `ENTRY_NOT_TRIGGERED`
- `PAPER_POSITION_OPEN`
- `TP_HIT`
- `SL_HIT`
- `TIMEOUT_CLOSE`
- `STILL_OPEN`
- `AMBIGUOUS_INTRABAR`
- `INSUFFICIENT_FORWARD_DATA`
- `OUTCOME_RECORDED`

## Results

- tracked signals: `71`
- legacy excluded: `64`
- accepted/blocked: `26/45`
- entry filled: `26`
- TP/SL/timeout: `18/6/0`
- still open: `0`
- ambiguous intrabar: `2`
- insufficient forward data: `0`
- median risk distance: `1.35` USD / `13.5` pips

## Win Rate Definitions

- gross win rate: `0.692308` using denominator `accepted_signals`
- decisive win rate TP vs SL only: `0.75` using denominator `tp_hit_count + sl_hit_count`
- interpretation: `DESCRIPTIVE_ONLY_SMALL_N`

AMBIGUOUS_INTRABAR, STILL_OPEN, INSUFFICIENT_FORWARD_DATA, ENTRY_NOT_TRIGGERED, and TIMEOUT_CLOSE are not silently counted as wins.

## Gates

- lifecycle gate: `PASSED`
- sample gate: `INSUFFICIENT_N`
- paper validated gate: `BLOCKED`
- live gate: `BLOCKED`
- deployment gate: `BLOCKED`
- order_send gate: `BLOCKED`
- broker gate: `BLOCKED`

## Sample Limitations

Outcome data is post-signal evidence only. It must not be used to redefine signal validity, regime labels, filters, cooldown, or entry/TP/SL logic in this branch.

## Safety

- no live trading
- no Telegram
- no orders
- no broker execution
- no order_send
- no signal stream
- no lot size or account risk sizing
- no Strategy 3 VWAP/sigma/cooldown/entry/TP/SL/filter changes
- no Strategy 2 touch
- no Adelin touch
- no data/XAUUSD/*.csv mutation

## Next Recommendation

Continue paper accumulation and refresh lifecycle outcomes after additional clean accepted signals. Treat all outcome metrics as descriptive only until the sample is materially larger.
