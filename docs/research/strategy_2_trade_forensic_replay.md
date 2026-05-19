# Strategy 2 Trade Forensic Replay

Status: research-only autopsy. No live trading, no Telegram alerts, no broker execution, no strategy changes.

## Executive Summary

- trades analyzed: `57`
- average / median SL distance: `70.6395` / `51.04` USD
- average / median TP distance: `50.2656` / `42.49` USD
- average planned R:R: `0.807`
- trades reaching +10/+15/+20: `42` / `41` / `37`
- human review required: `50`

## Safety Confirmation

- no live trading
- no Telegram
- no orders
- no broker execution
- no order_send
- no Strategy 2, Strategy 3, or Adelin logic changes
- no optimization and no ML

## Input Files And Data Availability

```json
{
  "entry_filter_dir": "backtests\\reports\\strategy_2_entry_filter_research",
  "entry_quality_dir": "backtests\\reports\\strategy_2_entry_quality_diagnostics",
  "m15_loaded": true,
  "m1_loaded": true,
  "missing_path_rows": 0,
  "symbol": "XAUUSD",
  "trades_analyzed": 57,
  "trades_path": "backtests\\reports\\strategy_2_human_management_intermediate\\executed_trades.csv"
}
```

## TP/SL Distribution

```json
{
  "average_planned_rr": 0.807,
  "average_sl_distance": 70.6395,
  "average_tp_distance": 50.2656,
  "max_planned_rr": 1.3416,
  "max_sl_distance": 205.51,
  "max_tp_distance": 102.91,
  "median_planned_rr": 0.7917,
  "median_sl_distance": 51.04,
  "median_tp_distance": 42.49,
  "min_planned_rr": 0.3506,
  "min_sl_distance": 28.58,
  "min_tp_distance": 26.75
}
```

## Outcome By TP/SL Bucket

| dimension | category | trades | sample_label | interpretation | PF | WR | AvgR | MedianR | total_R | MaxDD |
|---|---|---|---|---|---|---|---|---|---|---|
| stop_size_bucket | stop_ge_45 | 42 | moderate | interpretable, but not validated | 0.6004 | 0.4286 | -0.1073 | 0.0 | -4.5061 | 5.7799 |
| stop_size_bucket | stop_30_to_45 | 14 | weak | show metrics, but no conclusions | 1.5718 | 0.5 | 0.1488 | 0.1356 | 2.0829 | 1.232 |
| stop_size_bucket | stop_15_to_30 | 1 | insufficient | do not interpret; no conclusions | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| target_size_bucket | target_30_to_45 | 29 | weak | show metrics, but no conclusions | 1.7282 | 0.4828 | 0.1142 | 0.0 | 3.311 | 1.232 |
| target_size_bucket | target_ge_45 | 23 | weak | show metrics, but no conclusions | 0.2714 | 0.3478 | -0.2969 | -0.0295 | -6.829 | 6.829 |
| target_size_bucket | target_15_to_30 | 5 | insufficient | do not interpret; no conclusions | 2.0948 | 0.6 | 0.219 | 0.5556 | 1.0948 | 1.0 |
| rr_bucket | rr_below_0_75 | 24 | weak | show metrics, but no conclusions | 1.6348 | 0.5417 | 0.0681 | 0.0553 | 1.6342 | 2.1666 |
| rr_bucket | rr_0_75_to_1 | 21 | weak | show metrics, but no conclusions | 0.5248 | 0.3333 | -0.1969 | -0.1425 | -4.1348 | 4.1348 |
| rr_bucket | rr_1_to_1_5 | 12 | weak | show metrics, but no conclusions | 1.0212 | 0.4167 | 0.0065 | 0.0 | 0.0774 | 2.232 |

## MFE/MAE Distribution

```json
{
  "average_mae_R": 0.6042,
  "average_mae_usd": 35.3458,
  "average_mfe_R": 0.4886,
  "average_mfe_usd": 27.6268,
  "median_mae_R": 0.3824,
  "median_mae_usd": 24.23,
  "median_mfe_R": 0.4382,
  "median_mfe_usd": 28.85
}
```

## Threshold Reach Counts

```json
{
  "almost_hit_sl": 5,
  "almost_hit_tp": 9,
  "reached_0_5R": 25,
  "reached_1R": 4,
  "reached_2R": 1,
  "reached_plus_10": 42,
  "reached_plus_15": 41,
  "reached_plus_20": 37
}
```

## TIMEOUT_CLOSE Forensic Breakdown

| timeout_root_cause | trades | sample_label | interpretation | PF | WR | AvgR | MedianR | total_R | MaxDD | avg_mfe_R | avg_mae_R | reached_plus_10 | reached_plus_15 | reached_plus_20 | almost_hit_tp |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TIMEOUT_NO_FOLLOW_THROUGH | 9 | insufficient | do not interpret; no conclusions | 0.1567 | 0.2222 | -0.1092 | -0.1167 | -0.983 | 1.1656 | 0.1568 | 0.5269 | 3 | 2 | 2 | 1 |
| TIMEOUT_TARGET_TOO_FAR | 7 | insufficient | do not interpret; no conclusions | 1.0451 | 0.5714 | 0.0049 | 0.0881 | 0.034 | 0.6224 | 0.4216 | 0.2967 | 7 | 7 | 7 | 3 |
| TIMEOUT_ENTRY_TOO_LATE | 4 | insufficient | do not interpret; no conclusions | inf | 1.0 | 0.2532 | 0.184 | 1.0128 | 0.0 | 0.4645 | 0.575 | 3 | 3 | 2 | 0 |
| TIMEOUT_PRICE_CHOP | 2 | insufficient | do not interpret; no conclusions | inf | 1.0 | 0.3427 | 0.3427 | 0.6855 | 0.0 | 0.8052 | 0.3189 | 2 | 2 | 2 | 2 |

## TP Realism And SL Realism

TP realism:

```json
{
  "TP_BLOCKED_BY_OBSTACLE": 25,
  "TP_REALISTIC": 13,
  "TP_TOO_FAR": 19
}
```

SL realism:

```json
{
  "SL_STRUCTURALLY_PROTECTED": 13,
  "SL_TOO_TIGHT": 2,
  "SL_TOO_WIDE": 42
}
```

## Failure-Mode Taxonomy

```json
{
  "CHOP_TIMEOUT": 2,
  "DIRTY_SETUP": 13,
  "ENTRY_TOO_LATE": 14,
  "NO_FOLLOW_THROUGH": 3,
  "REACTION_DEAD": 16,
  "STOP_TOO_WIDE": 3,
  "TARGET_TOO_AMBITIOUS": 6
}
```

## Trades Requiring Human Review

- review required count: `50`
```json
{
  "HIGH": 21,
  "MEDIUM": 29
}
```

## Human Labeling Pack Instructions

Use `strategy_2_human_label_pack.csv` for manual screenshot review. Fill only the human columns after inspecting before-entry, after-entry, and exit screenshots. Leave blank when unsure.

## Key Questions Answered

1. Average and median SL size: `70.6395` / `51.04` USD.
2. Average and median TP size: `50.2656` / `42.49` USD.
3. Average planned R:R: `0.807`.
4. Losing trades immediate invalidation vs slow failure: `22` / `1`.
5. TIMEOUT_CLOSE almost-hit TP vs never reached 0.5R: `6` / `17`.
6. Trades reaching +10/+15/+20 before failing: `20` / `19` / `16`.
7. BE/partial support from MFE: `True`.
8. TP targets too ambitious count: `19`.
9. Stops too tight count: `2`.
10. Manual review first: high priority rows in `strategy_2_human_label_pack.csv`.
11. Missing data for human-vs-bot: screenshots, human-marked entry/SL/TP zones, protected structure/liquidity levels, and manual rationale.

## What This Proves

This report proves only what happened inside this 57-trade historical Strategy 2 sample: planned distances, path movement, timeout behavior, and forensic labels.

## What This Does Not Prove

It does not validate Strategy 2, create an edge, optimize parameters, or justify live deployment.

## Recommended Next Step

Use the human label pack to manually inspect the highest-priority trades. If the manual review does not reveal a repeatable human-vs-bot execution gap, keep Strategy 2 paused and focus on Strategy 3 paper validation.
