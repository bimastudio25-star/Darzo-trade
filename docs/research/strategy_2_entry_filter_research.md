# Strategy 2 Entry Filter Research

Status: research-only. This report does not change Strategy 2, Strategy 3, Adelin, live trading, Telegram, or broker execution.

## Executive Summary

- Strategy 2 trades analyzed: `57`
- baseline PF / WR / AvgR / total_R: `0.8376` / `0.4386` / `-0.0425` / `-2.4232`
- taxonomy verdict: `TAXONOMY_DISCRIMINATING`
- best safe filter: `reject_target_space_lt_1R` n_kept=`12` PF=`1.0212` AvgR=`0.0065`
- verdict flags: `STRATEGY_2_REMAINS_RESEARCH_ONLY, NO_LIVE_DEPLOYMENT_DECISION, TAXONOMY_DISCRIMINATING, NO_PREDICTIVE_ENTRY_FILTER_FOUND, LEAKAGE_ATTEMPT_REJECTED, STRATEGY_2_ARCHIVE_RECOMMENDED`
- recommended next step: `focus Strategy 3 paper validation; pause/archive Strategy 2`

## Safety Confirmation

- no live trading
- no Telegram trade alerts
- no broker execution
- no `order_send`
- no Strategy 2 entry-logic changes
- no Strategy 3 logic/cooldown/VWAP/pipeline changes
- no Adelin changes
- no ML/classifier training

## Input Data

```json
{
  "command": "python scripts/analyze_strategy_2_entry_filter_research.py",
  "dry_run": true,
  "entry_quality_columns": [
    "trade_id",
    "symbol",
    "strategy",
    "direction",
    "signal_timestamp",
    "entry_timestamp",
    "entry_price",
    "stop_loss",
    "take_profit",
    "outcome",
    "r_multiple",
    "session",
    "entry_hour",
    "setup_mode",
    "first_m5_close_quality",
    "first_m5_close_score",
    "first_m5_close_reason_codes",
    "second_m5_close_quality",
    "second_m5_close_score",
    "second_m5_close_reason_codes",
    "third_m5_close_quality",
    "third_m5_close_score",
    "third_m5_close_reason_codes",
    "reaction_state_3_m5",
    "reaction_state_5_m5",
    "reaction_reason_codes_3_m5",
    "reaction_reason_codes_5_m5",
    "mfe_3_m5_usd",
    "mae_3_m5_usd",
    "mfe_3_m5_R",
    "mae_3_m5_R",
    "mfe_5_m5_usd",
    "mae_5_m5_usd",
    "mfe_5_m5_R",
    "mae_5_m5_R",
    "favorable_follow_through_3_m5",
    "favorable_follow_through_5_m5",
    "retest_detected",
    "retest_quality",
    "retest_timestamp",
    "retest_reason_codes",
    "be_hit_then_continuation",
    "entry_quality_label",
    "price_escaped_proxy",
    "late_entry_proxy",
    "target_space_proxy",
    "no_follow_through_proxy",
    "dirty_context_proxy",
    "entry_quality_reason_codes",
    "timeout_root_cause",
    "timeout_reason_codes",
    "timeout_mfe_R",
    "timeout_mae_R",
    "timeout_reached_be_trigger",
    "timeout_reached_partial_trigger",
    "timeout_chop_proxy",
    "timeout_target_too_far_proxy",
    "winner_loser_category",
    "diagnostic_bucket",
    "primary_blocker",
    "secondary_blocker"
  ],
  "entry_quality_rows_available": true,
  "entry_quality_trades_path": "backtests\\reports\\strategy_2_entry_quality_diagnostics\\strategy_2_entry_quality_trades.csv",
  "executed_columns": [
    "timestamp",
    "symbol",
    "strategy",
    "direction",
    "entry",
    "stop",
    "sl_distance",
    "sl_distance_usd",
    "sl_distance_pips",
    "risk_label",
    "tp1",
    "tp2",
    "tp3",
    "tp4",
    "rr_tp1",
    "score",
    "session",
    "accepted",
    "rejection_reasons",
    "setup_mode",
    "reason_codes",
    "confluences",
    "vwap",
    "vwap_distance",
    "vwap_distance_pips",
    "band_touched",
    "liquidity_context",
    "sweep_timeframe",
    "sweep_type",
    "sweep_price",
    "fvg_ifvg_context",
    "number_theory_context",
    "target_model",
    "research_only",
    "strategy_name",
    "risk_distance",
    "reward_distance",
    "rr",
    "outcome",
    "exit_time",
    "exit_price",
    "r_multiple",
    "mae",
    "mfe",
    "bars_held"
  ],
  "executed_trades_path": "backtests\\reports\\strategy_2_human_management_intermediate\\executed_trades.csv",
  "strategy3_columns": [
    "timestamp",
    "symbol",
    "strategy",
    "direction",
    "entry",
    "stop",
    "sl_distance",
    "sl_distance_usd",
    "sl_distance_pips",
    "risk_label",
    "tp1",
    "tp2",
    "tp3",
    "tp4",
    "rr_tp1",
    "score",
    "session",
    "accepted",
    "rejection_reasons",
    "setup_mode",
    "reason_codes",
    "confluences",
    "vwap",
    "vwap_distance",
    "vwap_distance_pips",
    "band_touched",
    "liquidity_context",
    "sweep_timeframe",
    "sweep_type",
    "sweep_price",
    "fvg_ifvg_context",
    "number_theory_context",
    "target_model",
    "research_only",
    "strategy_name",
    "risk_distance",
    "reward_distance",
    "rr",
    "outcome",
    "exit_time",
    "exit_price",
    "r_multiple",
    "mae",
    "mfe",
    "bars_held"
  ],
  "strategy3_source_path": "backtests\\reports\\strategy_3_entry_filter_calibration_smoke\\executed_trades.csv"
}
```

## Taxonomy Calibration Against Strategy 3

- Strategy 3 source: `backtests\reports\strategy_3_entry_filter_calibration_smoke\executed_trades.csv`
- Strategy 3 sample size: `39`
- Strategy 3 TRADE_NOW count/rate: `11` / `0.2821`
- Strategy 3 NO_TRADE count/rate: `28` / `0.7179`
- Strategy 2 NO_TRADE rate: `0.9825`

Strategy 2 labels:

```json
{
  "NO_TRADE_DIRTY_SETUP": 21,
  "NO_TRADE_INSUFFICIENT_TARGET_SPACE": 5,
  "NO_TRADE_PRICE_ESCAPED": 14,
  "NO_TRADE_REACTION_ALREADY_DEAD": 16,
  "TRADE_NOW": 1
}
```

Strategy 3 labels:

```json
{
  "NO_TRADE_DIRTY_SETUP": 5,
  "NO_TRADE_PRICE_ESCAPED": 13,
  "NO_TRADE_REACTION_ALREADY_DEAD": 10,
  "TRADE_NOW": 11
}
```

## Calibration Verdict

`TAXONOMY_DISCRIMINATING`

## Pre-Entry Feature Audit

- feature rows: `57`
- audit rows: `1083`
- unsafe audit rows: `57`

Only the deliberate post-entry `reaction_state_5_m5` audit rows are unsafe. They are retained to prove leakage detection and are rejected as filter inputs.

## Leakage Prevention Rules

- Filter features must have `feature_latest_timestamp <= entry_timestamp`.
- First/second/third M5 closes after entry, MFE/MAE, retest, outcome, and REACTION_ALIVE are forbidden as live-filter inputs.
- `REACTION_ALIVE` may appear only as a target label for correlation notes.

## Rule-Based Filters Tested

| filter_name | feature_safety_status | rule_definition | n_total | n_kept | n_rejected | kept_sample_label | rejected_sample_label | baseline_PF | kept_PF | rejected_PF | baseline_WR | kept_WR | rejected_WR | baseline_AvgR | kept_AvgR | rejected_AvgR | baseline_total_R | kept_total_R | rejected_total_R | kept_MaxDD | n_kept_ge_30 | kept_PF_gt_1 | kept_PF_ge_1_10 | improvement_logically_explainable | exploratory | rejected_for_leakage | caveats |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| reject_price_escape_pre_entry | safe_pre_entry | reject when price_escape_pre_entry_proxy is true | 57 | 43 | 14 | moderate | weak | 0.8376 | 0.7467 | 1.1438 | 0.4386 | 0.4186 | 0.5 | -0.0425 | -0.0678 | 0.0351 | -2.4232 | -2.9142 | 0.491 | 4.7343 | True | False | False | False | False | False |  |
| reject_dirty_pre_entry_m5_or_m15 | safe_pre_entry | reject when last closed M5 is bad/invalidating or last closed M15 context is dead | 57 | 0 | 57 | insufficient | moderate | 0.8376 | None | 0.8376 | 0.4386 | 0.0 | 0.4386 | -0.0425 | None | -0.0425 | -2.4232 | 0.0 | -2.4232 | 0.0 | False | False | False | False | False | False | kept sample below 30; exploratory only |
| reject_target_space_lt_1R | safe_pre_entry | reject when target_space_R < 1.0 using target/stop known at entry | 57 | 12 | 45 | weak | moderate | 0.8376 | 1.0212 | 0.7782 | 0.4386 | 0.4167 | 0.4444 | -0.0425 | 0.0065 | -0.0556 | -2.4232 | 0.0774 | -2.5006 | 2.232 | False | True | False | True | False | False | kept sample below 30; exploratory only |
| reject_recent_m15_dead_context | safe_pre_entry | reject when the last 3 closed M15 candles show adverse or low-body context | 57 | 4 | 53 | insufficient | moderate | 0.8376 | 0.3003 | 0.9208 | 0.4386 | 0.5 | 0.434 | -0.0425 | -0.3498 | -0.0193 | -2.4232 | -1.3994 | -1.0238 | 1.4444 | False | False | False | False | False | False | kept sample below 30; exploratory only |
| reject_pre_entry_overextension | safe_pre_entry | reject when favorable displacement over last 3 closed M15 candles is >= 0.75R | 57 | 57 | 0 | moderate | insufficient | 0.8376 | 0.8376 | None | 0.4386 | 0.4386 | 0.0 | -0.0425 | -0.0425 | None | -2.4232 | -2.4232 | 0.0 | 6.6376 | True | False | False | False | False | False |  |
| reject_too_close_to_pre_entry_obstacle | safe_pre_entry | reject when nearest prior M15 swing obstacle before target is closer than 1R | 57 | 1 | 56 | insufficient | moderate | 0.8376 | 0.0 | 0.8376 | 0.4386 | 0.0 | 0.4464 | -0.0425 | 0.0 | -0.0433 | -2.4232 | 0.0 | -2.4232 | 0.0 | False | False | False | False | False | False | kept sample below 30; exploratory only |
| exploratory_keep_14_16_only | safe_pre_entry | reject entries outside the 14:00-16:00 hypothesis window | 57 | 7 | 50 | insufficient | moderate | 0.8376 | 0.3732 | 0.9273 | 0.4386 | 0.2857 | 0.46 | -0.0425 | -0.2163 | -0.0182 | -2.4232 | -1.5139 | -0.9093 | 1.5139 | False | False | False | False | True | False | hour/session buckets are same-sample exploratory; kept sample below 30; exploratory only; exploratory rule; not suitable for live filtering |
| exploratory_dirty_or_target_space | safe_pre_entry | reject when dirty_context_pre_entry_proxy is true or target_space_R < 1.0 | 57 | 0 | 57 | insufficient | moderate | 0.8376 | None | 0.8376 | 0.4386 | 0.0 | 0.4386 | -0.0425 | None | -0.0425 | -2.4232 | 0.0 | -2.4232 | 0.0 | False | False | False | False | True | False | max two simple conditions; exploratory; kept sample below 30; exploratory only; exploratory rule; not suitable for live filtering |
| rejected_post_entry_reaction_alive_filter | unsafe_future_data_rejected | reject when reaction_state_5_m5 is not REACTION_ALIVE | 57 | 15 | 42 | weak | moderate | 0.8376 | 3.3672 | 0.5874 | 0.4386 | 0.5333 | 0.4048 | -0.0425 | 0.2119 | -0.1334 | -2.4232 | 3.1784 | -5.6016 | 1.1408 | False | True | True | False | False | True | REACTION_ALIVE is a post-entry label and cannot be a live filter; Rejected: candidate uses post-entry/future data.; kept sample below 30; exploratory only |

## Reaction-Alive Predictability Analysis

| feature_name | feature_value | n | reaction_alive_count | reaction_alive_rate | sample_label | PF | WR | AvgR | total_R | notes |
|---|---|---|---|---|---|---|---|---|---|---|
| last_m5_close_quality_pre_entry | GOOD_CLOSE | 4 | 2 | 0.5 | insufficient | 0.4962 | 0.5 | -0.2519 | -1.0076 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| derived_session | Asia | 21 | 7 | 0.3333 | weak | 0.425 | 0.381 | -0.207 | -4.3461 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| derived_session | London | 6 | 2 | 0.3333 | insufficient | 1.8335 | 0.6667 | 0.1389 | 0.8335 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| price_escape_pre_entry_proxy | False | 43 | 13 | 0.3023 | moderate | 0.7467 | 0.4186 | -0.0678 | -2.9142 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| recent_m15_dead_context_proxy | True | 53 | 15 | 0.283 | moderate | 0.9208 | 0.434 | -0.0193 | -1.0238 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| hour_14_16_window | False | 50 | 14 | 0.28 | moderate | 0.9273 | 0.46 | -0.0182 | -0.9093 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| last_m5_close_quality_pre_entry | BAD_CLOSE | 41 | 11 | 0.2683 | moderate | 0.9033 | 0.439 | -0.0239 | -0.9816 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| too_close_to_obstacle_proxy | True | 56 | 15 | 0.2679 | moderate | 0.8376 | 0.4464 | -0.0433 | -2.4232 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| target_space_lt_1R | True | 45 | 12 | 0.2667 | moderate | 0.7782 | 0.4444 | -0.0556 | -2.5006 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| direction | LONG | 30 | 8 | 0.2667 | moderate | 0.6466 | 0.4667 | -0.1094 | -3.2819 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| dirty_context_pre_entry_proxy | True | 57 | 15 | 0.2632 | moderate | 0.8376 | 0.4386 | -0.0425 | -2.4232 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| overextension_proxy | False | 57 | 15 | 0.2632 | moderate | 0.8376 | 0.4386 | -0.0425 | -2.4232 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| direction | SHORT | 27 | 7 | 0.2593 | weak | 1.1525 | 0.4074 | 0.0318 | 0.8587 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| target_space_lt_1R | False | 12 | 3 | 0.25 | weak | 1.0212 | 0.4167 | 0.0065 | 0.0774 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| derived_session | NewYork | 25 | 6 | 0.24 | weak | 1.6072 | 0.44 | 0.1031 | 2.5771 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| last_m5_close_quality_pre_entry | ACCEPTABLE_CLOSE | 12 | 2 | 0.1667 | weak | 0.8433 | 0.4167 | -0.0362 | -0.434 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| price_escape_pre_entry_proxy | True | 14 | 2 | 0.1429 | weak | 1.1438 | 0.5 | 0.0351 | 0.491 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| hour_14_16_window | True | 7 | 1 | 0.1429 | insufficient | 0.3732 | 0.2857 | -0.2163 | -1.5139 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| derived_session | LateUS | 5 | 0 | 0.0 | insufficient | 0.2972 | 0.4 | -0.2975 | -1.4877 | REACTION_ALIVE is used only as a target label, not as a filter input. |
| recent_m15_dead_context_proxy | False | 4 | 0 | 0.0 | insufficient | 0.3003 | 0.5 | -0.3498 | -1.3994 | REACTION_ALIVE is used only as a target label, not as a filter input. |

## Statistical Caveats

- `n < 10`: insufficient; no conclusion.
- `10 <= n < 30`: weak observation only.
- `n >= 30`: interpretable but not validated.
- No filter is live-ready, deployable, or validated.

## Decision Matrix

```json
{
  "best_reaction_alive_association": {
    "AvgR": -0.0678,
    "PF": 0.7467,
    "WR": 0.4186,
    "feature_name": "price_escape_pre_entry_proxy",
    "feature_value": "False",
    "n": 43,
    "notes": "REACTION_ALIVE is used only as a target label, not as a filter input.",
    "reaction_alive_count": 13,
    "reaction_alive_rate": 0.3023,
    "sample_label": "moderate",
    "total_R": -2.9142
  },
  "best_usable_filter": {
    "baseline_AvgR": -0.0425,
    "baseline_PF": 0.8376,
    "baseline_WR": 0.4386,
    "baseline_total_R": -2.4232,
    "caveats": "kept sample below 30; exploratory only",
    "exploratory": false,
    "feature_safety_status": "safe_pre_entry",
    "filter_name": "reject_target_space_lt_1R",
    "improvement_logically_explainable": true,
    "kept_AvgR": 0.0065,
    "kept_MaxDD": 2.232,
    "kept_PF": 1.0212,
    "kept_PF_ge_1_10": false,
    "kept_PF_gt_1": true,
    "kept_WR": 0.4167,
    "kept_sample_label": "weak",
    "kept_total_R": 0.0774,
    "n_kept": 12,
    "n_kept_ge_30": false,
    "n_rejected": 45,
    "n_total": 57,
    "rejected_AvgR": -0.0556,
    "rejected_PF": 0.7782,
    "rejected_WR": 0.4444,
    "rejected_for_leakage": false,
    "rejected_sample_label": "moderate",
    "rejected_total_R": -2.5006,
    "rule_definition": "reject when target_space_R < 1.0 using target/stop known at entry"
  },
  "next_step": "focus Strategy 3 paper validation; pause/archive Strategy 2",
  "verdict_flags": [
    "STRATEGY_2_REMAINS_RESEARCH_ONLY",
    "NO_LIVE_DEPLOYMENT_DECISION",
    "TAXONOMY_DISCRIMINATING",
    "NO_PREDICTIVE_ENTRY_FILTER_FOUND",
    "LEAKAGE_ATTEMPT_REJECTED",
    "STRATEGY_2_ARCHIVE_RECOMMENDED"
  ]
}
```

## Final Recommendation

focus Strategy 3 paper validation; pause/archive Strategy 2
