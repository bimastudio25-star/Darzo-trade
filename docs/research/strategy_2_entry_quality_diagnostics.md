# Strategy 2 Entry Quality Diagnostics

Status: research-only diagnostic. No live trading, no Telegram alerts, no broker execution, no strategy-entry changes.

## Executive Summary

- trades analyzed: `57`
- baseline PF / AvgR / total_R: `0.8376` / `-0.0425` / `-2.4232`
- decision matrix result: `CLEAR_GOOD_ENTRY_SUBSET_FOUND`
- next step: `feat/strategy-2-entry-filter-research`
- verdict flags: `CLEAR_GOOD_ENTRY_SUBSET_FOUND, STRATEGY_2_REMAINS_RESEARCH_ONLY, NO_LIVE_DEPLOYMENT_DECISION`
- best candidate subset: `reaction_state_5_m5=REACTION_ALIVE n=15 label=weak PF=3.3672 AvgR=0.2119`

## Input Data And Safety

- trades path: `backtests\reports\strategy_2_human_management_intermediate\executed_trades.csv`
- M1 loaded: `true`
- M5 loaded: `true`
- missing M5 rows: `0`
- live/order/Telegram enabled: `false`

## Baseline Recap

| trades | sample_label | PF | WR | AvgR | MedianR | total_R | MaxDD |
|---|---|---|---|---|---|---|---|
| 57 | moderate | 0.8376 | 0.4386 | -0.0425 | 0.0 | -2.4232 | 6.6376 |

## M5 Close Quality Distribution

### First M5 Close By Outcome

| outcome | distribution |
|---|---|
| BE | {"ACCEPTABLE_CLOSE": 1, "BAD_CLOSE": 7, "GOOD_CLOSE": 1} |
| SL | {"ACCEPTABLE_CLOSE": 2, "BAD_CLOSE": 9, "INVALIDATING_CLOSE": 2} |
| TIMEOUT_CLOSE | {"ACCEPTABLE_CLOSE": 4, "BAD_CLOSE": 14, "GOOD_CLOSE": 4} |
| TP2 | {"ACCEPTABLE_CLOSE": 1, "BAD_CLOSE": 10, "GOOD_CLOSE": 2} |

### Second M5 Close By Outcome

| outcome | distribution |
|---|---|
| BE | {"ACCEPTABLE_CLOSE": 3, "BAD_CLOSE": 5, "GOOD_CLOSE": 1} |
| SL | {"ACCEPTABLE_CLOSE": 1, "BAD_CLOSE": 8, "GOOD_CLOSE": 2, "INVALIDATING_CLOSE": 2} |
| TIMEOUT_CLOSE | {"ACCEPTABLE_CLOSE": 2, "BAD_CLOSE": 16, "GOOD_CLOSE": 4} |
| TP2 | {"ACCEPTABLE_CLOSE": 3, "BAD_CLOSE": 5, "GOOD_CLOSE": 5} |

### Third M5 Close By Outcome

| outcome | distribution |
|---|---|
| BE | {"ACCEPTABLE_CLOSE": 1, "BAD_CLOSE": 6, "GOOD_CLOSE": 2} |
| SL | {"ACCEPTABLE_CLOSE": 2, "BAD_CLOSE": 8, "GOOD_CLOSE": 1, "INVALIDATING_CLOSE": 2} |
| TIMEOUT_CLOSE | {"ACCEPTABLE_CLOSE": 6, "BAD_CLOSE": 14, "GOOD_CLOSE": 2} |
| TP2 | {"ACCEPTABLE_CLOSE": 3, "BAD_CLOSE": 5, "GOOD_CLOSE": 5} |

## Reaction State Distribution

### Reaction After 3 M5 Candles

| outcome | distribution |
|---|---|
| BE | {"REACTION_ALIVE": 2, "REACTION_DEAD": 2, "REACTION_WEAK": 5} |
| SL | {"REACTION_ALIVE": 2, "REACTION_DEAD": 4, "REACTION_WEAK": 7} |
| TIMEOUT_CLOSE | {"REACTION_ALIVE": 5, "REACTION_DEAD": 7, "REACTION_WEAK": 10} |
| TP2 | {"REACTION_ALIVE": 8, "REACTION_DEAD": 3, "REACTION_WEAK": 2} |

### Reaction After 5 M5 Candles

| outcome | distribution |
|---|---|
| BE | {"REACTION_ALIVE": 4, "REACTION_DEAD": 1, "REACTION_WEAK": 4} |
| SL | {"REACTION_ALIVE": 1, "REACTION_DEAD": 5, "REACTION_WEAK": 7} |
| TIMEOUT_CLOSE | {"REACTION_ALIVE": 5, "REACTION_DEAD": 9, "REACTION_WEAK": 8} |
| TP2 | {"REACTION_ALIVE": 5, "REACTION_DEAD": 4, "REACTION_WEAK": 4} |

## Retest Distribution

### Retest Quality By Outcome

| outcome | distribution |
|---|---|
| BE | {"FAILED_RETEST": 1, "NO_RETEST": 7, "RETEST_PENDING": 1} |
| SL | {"FAILED_RETEST": 1, "NO_RETEST": 11, "RETEST_PENDING": 1} |
| TIMEOUT_CLOSE | {"FAILED_RETEST": 1, "NO_RETEST": 21} |
| TP2 | {"NO_RETEST": 13} |

## Entry-Quality Labels

```json
{
  "NO_TRADE_DIRTY_SETUP": 21,
  "NO_TRADE_INSUFFICIENT_TARGET_SPACE": 5,
  "NO_TRADE_PRICE_ESCAPED": 14,
  "NO_TRADE_REACTION_ALREADY_DEAD": 16,
  "TRADE_NOW": 1
}
```

## Timeout Root-Cause Diagnostics

| timeout_root_cause | trades | sample_label | interpretation | PF | WR | AvgR | MedianR | total_R | MaxDD | avg_timeout_mfe_R | avg_timeout_mae_R | reached_be_trigger_count | reached_partial_trigger_count |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TIMEOUT_NO_FOLLOW_THROUGH | 19 | weak | observation only | 1.5646 | 0.5789 | 0.0468 | 0.0656 | 0.8901 | 0.6216 | 0.3649 | 0.467 | 12 | 11 |
| TIMEOUT_UNKNOWN | 3 | insufficient | no conclusion | 0.5891 | 0.3333 | -0.0469 | -0.1311 | -0.1408 | 0.2116 | 0.2989 | 0.1688 | 3 | 3 |

## Winner / Loser Taxonomy

```json
{
  "BE_AFTER_WEAK_REACTION": 9,
  "LOSER_BAD_M5_CLOSE_IGNORED": 3,
  "LOSER_IMMEDIATE_INVALIDATION": 6,
  "LOSER_PRICE_CHASED": 4,
  "TIMEOUT_NO_FOLLOW_THROUGH": 19,
  "TIMEOUT_UNKNOWN": 3,
  "WINNER_CLEAN_FOLLOW_THROUGH": 3,
  "WINNER_SLOW_GRIND": 7,
  "WINNER_UNKNOWN": 3
}
```

## Diagnostic Buckets Ranked By AvgR

Best buckets:

| dimension | category | trades | sample_label | interpretation | PF | WR | AvgR | MedianR | total_R | MaxDD |
|---|---|---|---|---|---|---|---|---|---|---|
| diagnostic_bucket | WINNER_UNKNOWN | 3 | insufficient | no conclusion | inf | 1.0 | 0.9602 | 0.9463 | 2.8807 | 0.0 |
| diagnostic_bucket | WINNER_CLEAN_FOLLOW_THROUGH | 3 | insufficient | no conclusion | inf | 1.0 | 0.7234 | 0.7069 | 2.1701 | 0.0 |
| diagnostic_bucket | WINNER_SLOW_GRIND | 7 | insufficient | no conclusion | inf | 1.0 | 0.6824 | 0.6418 | 4.7767 | 0.0 |
| diagnostic_bucket | TIMEOUT_NO_FOLLOW_THROUGH | 19 | weak | observation only | 1.5646 | 0.5789 | 0.0468 | 0.0656 | 0.8901 | 0.6216 |
| diagnostic_bucket | BE_AFTER_WEAK_REACTION | 9 | insufficient | no conclusion | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

Worst buckets:

| dimension | category | trades | sample_label | interpretation | PF | WR | AvgR | MedianR | total_R | MaxDD |
|---|---|---|---|---|---|---|---|---|---|---|
| diagnostic_bucket | LOSER_BAD_M5_CLOSE_IGNORED | 3 | insufficient | no conclusion | 0.0 | 0.0 | -1.0 | -1.0 | -3.0 | 3.0 |
| diagnostic_bucket | LOSER_PRICE_CHASED | 4 | insufficient | no conclusion | 0.0 | 0.0 | -1.0 | -1.0 | -4.0 | 4.0 |
| diagnostic_bucket | LOSER_IMMEDIATE_INVALIDATION | 6 | insufficient | no conclusion | 0.0 | 0.0 | -1.0 | -1.0 | -6.0 | 6.0 |
| diagnostic_bucket | TIMEOUT_UNKNOWN | 3 | insufficient | no conclusion | 0.5891 | 0.3333 | -0.0469 | -0.1311 | -0.1408 | 0.2116 |
| diagnostic_bucket | BE_AFTER_WEAK_REACTION | 9 | insufficient | no conclusion | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

## Statistical Caveats

- Buckets with `n < 10` are insufficient and must not be interpreted.
- Buckets with `10 <= n < 30` are weak observations only.
- Buckets with `n >= 30` are interpretable but not validated.
- Nothing in this report is live-ready or validated.

## Decision Matrix Result

- result: `CLEAR_GOOD_ENTRY_SUBSET_FOUND`
- reason codes: `best_bucket=REACTION_ALIVE, sample_label=weak`
- recommended next step: `feat/strategy-2-entry-filter-research`

## Recommended Next Step

feat/strategy-2-entry-filter-research
