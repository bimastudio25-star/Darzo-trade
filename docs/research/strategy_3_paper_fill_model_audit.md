# Strategy 3 Paper Fill-Model Audit

This audit is diagnostic only. It does not change Strategy 3, send signals, enable Telegram, place orders, call broker execution, or approve live trading.

## Objective

Audit whether the current paper lifecycle outcome metrics are robust to fill assumptions before any paper signal stream work.

## Why This Is Required

The lifecycle tracker currently uses `PAPER_REFERENCE_FILL_AT_SIGNAL`. Before a signal stream can even be considered for paper-only use, the project needs to know whether the descriptive WR/R profile is stable under plausible alternative fill assumptions.

## Alignment With Existing Assumptions

- backtest assumption detected: Backtest runner builds Strategy 3 BacktestSignal from Strategy3Signal.entry and passes future M1 candles strictly after the driver cutoff to simulate_trade_outcome.
- paper scanner assumption detected: Paper scanner serializes Strategy3Signal.entry as entry_price/current_price with no pending-entry state or entry touch lifecycle.
- lifecycle assumption detected: Lifecycle tracker uses PAPER_REFERENCE_FILL_AT_SIGNAL and evaluates forward closed candles strictly after the decision timestamp.
- alignment: `ALIGNED`
- governance: `AUDIT_REQUIRED_BEFORE_SIGNAL_STREAM`

## Tested Fill Models

- `PAPER_REFERENCE_FILL_AT_SIGNAL`: accepted signal fills at the paper reference entry at the decision timestamp; forward tracking starts after the decision timestamp.
- `PAPER_PENDING_ENTRY_TOUCH`: entry fills only if a later closed candle touches the entry reference level.
- `CONSERVATIVE_NEXT_CANDLE_FILL_OR_TOUCH`: entry fills from the next closed candle onward, but first-fill candle TP/SL interaction is ambiguous rather than favorable.

## Outcome Comparison

| fill_model | entry_filled | entry_not_triggered | TP | SL | ambiguous | decisive_WR | total_R |
|---|---:|---:|---:|---:|---:|---:|---:|
| PAPER_REFERENCE_FILL_AT_SIGNAL | 26 | 0 | 18 | 6 | 2 | 0.75 | 12.0 |
| PAPER_PENDING_ENTRY_TOUCH | 26 | 0 | 18 | 6 | 2 | 0.75 | 12.0 |
| CONSERVATIVE_NEXT_CANDLE_FILL_OR_TOUCH | 26 | 0 | 11 | 4 | 11 | 0.733333 | 7.0 |

## Sensitivity

- sensitivity status: `HIGH`
- changed outcomes reference vs pending: `0`
- changed outcomes reference vs conservative: `9`
- WR delta reference vs pending: `0.0`
- WR delta reference vs conservative: `-0.016667`
- total R delta reference vs pending: `0.0`
- total R delta reference vs conservative: `-5.0`

Sensitivity labels are audit labels only, not strategy rules.

## Gates

- fill model audit gate: `BLOCKED`
- paper signal stream gate: `BLOCKED`
- live gate: `BLOCKED`
- deployment gate: `BLOCKED`
- order_send gate: `BLOCKED`
- broker gate: `BLOCKED`

## Limitations

- sample remains `INSUFFICIENT_N`
- outcome comparison is descriptive only
- no outcome result may be used to change Strategy 3 in this branch
- this does not validate edge or profitability
- this does not authorize Telegram signal stream yet

## Safety

- no live trading
- no Telegram
- no signal stream
- no orders
- no broker execution
- no order_send
- no lot size or account risk sizing
- no Strategy 3 VWAP/sigma/cooldown/entry/TP/SL/filter changes
- no Strategy 2 touch
- no Adelin touch
- no data/XAUUSD/*.csv mutation

## Next Recommendation

If sensitivity is LOW and the audit gate passes, the next branch may define a paper-only signal-stream governance plan. If sensitivity is MEDIUM/HIGH, keep accumulating paper evidence and resolve fill-model governance before any signal stream work.
