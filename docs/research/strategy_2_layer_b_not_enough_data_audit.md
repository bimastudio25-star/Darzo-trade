# Strategy 2 Layer B NOT_ENOUGH_DATA Clustering Audit

## Context

Layer B diagnostics originally produced 51/186 Layer A-valid samples as `NOT_ENOUGH_DATA`. The denominator audit separates no-entry/no-reentry attrition from true missing-data cases.

## Method

- Inputs: Layer B reaction feature export, Layer A state split, and read-only XAUUSD M1 data.
- Grouping dimensions: direction, hour, UTC session bucket, weekday, H1 context, dataset boundary proximity, candle availability, and likely cause.
- Session buckets: ASIA 00:00-07:59 UTC, LONDON 08:00-12:59 UTC, NY 13:00-20:59 UTC, OFF_HOURS 21:00-23:59 UTC.
- No Strategy 2 reaction rule changes were made.

## Findings

- samples processed: `1089`
- original Layer A valid samples: `186`
- measurable Layer B samples: `135`
- REENTRY_NOT_REACHED count: `51`
- NOT_ENOUGH_DATA count/rate: `0` / `0.0`
- descriptor distribution after reclassification: `{'CHOP_AFTER_SWEEP_CANDIDATE': 79, 'FAST_REENTRY': 56, 'NO_ENTRY_REENTRY_NOT_REACHED': 51}`
- measurable descriptor distribution: `{'CHOP_AFTER_SWEEP_CANDIDATE': 79, 'FAST_REENTRY': 56}`

### Direction

| direction_candidate | eligible_count | not_enough_data_count | not_enough_data_rate |
| --- | --- | --- | --- |
| LONG | 99 | 0 | 0.0 |
| SHORT | 87 | 0 | 0.0 |

### Session

| session_bucket | eligible_count | not_enough_data_count | not_enough_data_rate |
| --- | --- | --- | --- |
| ASIA | 77 | 0 | 0.0 |
| LONDON | 38 | 0 | 0.0 |
| NY | 56 | 0 | 0.0 |
| OFF_HOURS | 15 | 0 | 0.0 |

### Weekday

| weekday | eligible_count | not_enough_data_count | not_enough_data_rate |
| --- | --- | --- | --- |
| Friday | 26 | 0 | 0.0 |
| Monday | 45 | 0 | 0.0 |
| Thursday | 37 | 0 | 0.0 |
| Tuesday | 37 | 0 | 0.0 |
| Wednesday | 41 | 0 | 0.0 |

### Top H1 Contexts

| h1_context_id | eligible_count | not_enough_data_count | not_enough_data_rate |
| --- | --- | --- | --- |
| XAUUSD_20260316000000+0000 | 1 | 0 | 0.0 |
| XAUUSD_20260316070000+0000 | 1 | 0 | 0.0 |
| XAUUSD_20260316130000+0000 | 1 | 0 | 0.0 |
| XAUUSD_20260317080000+0000 | 1 | 0 | 0.0 |
| XAUUSD_20260317120000+0000 | 1 | 0 | 0.0 |
| XAUUSD_20260318030000+0000 | 1 | 0 | 0.0 |
| XAUUSD_20260318130000+0000 | 1 | 0 | 0.0 |
| XAUUSD_20260318140000+0000 | 1 | 0 | 0.0 |
| XAUUSD_20260318150000+0000 | 1 | 0 | 0.0 |
| XAUUSD_20260318210000+0000 | 1 | 0 | 0.0 |

### Cause Breakdown

_No rows._

### NOT_ENOUGH_DATA Vs Available Descriptor

| group | sample_count | avg_available_candle_count | median_available_candle_count | avg_expected_candle_count | avg_missing_candle_count | avg_data_window_seconds | missing_decision_time_count | near_dataset_boundary_count | weekend_or_market_gap_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NOT_ENOUGH_DATA | 0 | nan | nan | nan | nan | nan | 0 | 0 | 0 |
| AVAILABLE_DESCRIPTOR | 135 | 15.2296 | 8.0 | 15.2296 | 0.0 | 853.7778 | 0 | 0 | 5 |

## Critical Conclusion

`NOT_ENOUGH_DATA_RECLASSIFIED_AS_REENTRY_NOT_REACHED`

Recommended next step: rerun manual validation planning with REENTRY_NOT_REACHED outside the measurable Layer B denominator.

## Safety

- Strategy 3 untouched.
- Adelin untouched.
- data/XAUUSD/*.csv untouched.
- No live trading, broker execution, orders, Telegram, optimization, ML, backtest, PnL, signal generation, manual validation pack, or reaction-rule change.

## Verdict Flags

- `LAYER_B_NOT_ENOUGH_DATA_AUDITED`
- `NOT_ENOUGH_DATA_CLUSTERING_ANALYZED`
- `NO_REACTION_RULE_CHANGE`
- `NO_PERFORMANCE_CLAIM`
- `STRATEGY_2_REMAINS_RESEARCH_ONLY`
- `NO_DEPLOYMENT_DECISION`
