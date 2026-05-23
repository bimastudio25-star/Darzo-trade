# Strategy 3 Fill-Model Ambiguity Governance

This branch is governance/diagnostic only. It does not change Strategy 3, enable Telegram, send signals, place orders, call broker execution, tune parameters, or approve live trading.

## Why This Exists

The fill-model audit found that reference and pending-touch outcomes match, but conservative first-eligible-candle ambiguity changes several outcomes. This report freezes how ambiguous paper outcomes are reported before any paper signal-stream work.

## Source Fill-Model Audit

- fill model alignment: `ALIGNED`
- fill model sensitivity: `HIGH`
- fill model audit gate: `BLOCKED`

## Ambiguity Counts

- accepted signals: `26`
- ambiguity candidates: `11`
- primary ambiguous count/rate: `2` / `0.076923`
- conservative changed count/rate: `9` / `0.346154`

| ambiguity_type | count |
|---|---:|
| CONSERVATIVE_POLICY_ARTIFACT | 9 |
| TRUE_TP_SL_SAME_CANDLE | 2 |

## Impact Summary

| mode | deterministic | ambiguous | TP | SL | decisive_WR | total_R | interpretation |
|---|---:|---:|---:|---:|---:|---:|---|
| REFERENCE_PRIMARY | 24 | 2 | 18 | 6 | 0.75 | 12.0 | PRIMARY_DESCRIPTIVE_ONLY_SMALL_N |
| AMBIGUOUS_EXCLUDED_PRIMARY | 15 | 0 | 11 | 4 | 0.733333 | 7.0 | PRIMARY_AMBIGUOUS_EXCLUDED_DESCRIPTIVE_ONLY_SMALL_N |
| CONSERVATIVE_DIAGNOSTIC_ONLY | 26 | 11 | 11 | 15 | 0.423077 | -4.0 | CONSERVATIVE_DIAGNOSTIC_ONLY_NOT_PRIMARY |

## Frozen Governance Policy

- primary outcome policy: `REFERENCE_PRIMARY_WITH_AMBIGUOUS_EXCLUDED_FROM_DECISIVE_WR`
- ambiguous intrabar policy: `AMBIGUOUS_NOT_COUNTED_AS_WIN_AND_EXCLUDED_FROM_DECISIVE_WR`
- same-candle entry/exit policy: `COUNT_AS_AMBIGUOUS_ONLY_UNTIL_TICK_OR_BROKER_FILL_DATA_EXISTS`
- conservative mode policy: `CONSERVATIVE_LOSS_DIAGNOSTIC_ONLY_NOT_PRIMARY`
- tick data requirement policy: `TICK_DATA_REQUIRED_TO_RESOLVE_INTRABAR_ORDERING; M1_IS_NOT_ENOUGH_FOR_PATH_ORDER`

## Gates

- ambiguity governance gate: `WARNING`
- paper signal stream gate: `WARNING`
- live gate: `BLOCKED`
- deployment gate: `BLOCKED`
- order_send gate: `BLOCKED`
- broker gate: `BLOCKED`

## Limitations

- M1 OHLC data cannot resolve true intrabar path ordering.
- Tick data, bid/ask spread, and broker fill rules would materially improve confidence.
- Ambiguous cases are not reinterpreted as wins.
- Conservative-loss mode is stress-test only and is not the primary outcome metric.
- No Strategy 3 rule is changed by this governance report.

## Safety

- no live trading
- no Telegram
- no signal stream
- no orders
- no broker execution
- no order_send
- no lot sizing or account risk sizing
- no Strategy 3 VWAP/sigma/cooldown/entry/TP/SL/filter changes
- no Strategy 2 touch
- no Adelin touch
- no data/XAUUSD/*.csv mutation

## Next Recommendation

Keep Strategy 3 paper-only. If a future signal-stream governance branch is opened, it must explicitly carry ambiguity labels and must not promote the strategy to live trading.
