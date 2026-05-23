# Strategy 2 Layer B NOT_ENOUGH_DATA Clustering Audit

## Context

Layer B diagnostics produced 51/186 eligible samples as `NOT_ENOUGH_DATA`. Manual validation should wait until this missing-data cluster is understood.

## Method

- Inputs: Layer B reaction feature export, Layer A state split, and read-only XAUUSD M1 data.
- Grouping dimensions: direction, hour, UTC session bucket, weekday, H1 context, dataset boundary proximity, candle availability, and likely cause.
- Session buckets: ASIA 00:00-07:59 UTC, LONDON 08:00-12:59 UTC, NY 13:00-20:59 UTC, OFF_HOURS 21:00-23:59 UTC.
- No Strategy 2 reaction rule changes were made.

## Findings

- samples processed: `1089`
- Layer B eligible samples: `186`
- NOT_ENOUGH_DATA count/rate: `51` / `0.2742`
- descriptor distribution: `{'CHOP_AFTER_SWEEP_CANDIDATE': 79, 'FAST_REENTRY': 56, 'NOT_ENOUGH_DATA': 51}`

### Direction

| direction_candidate | eligible_count | not_enough_data_count | not_enough_data_rate |
| --- | --- | --- | --- |
| LONG | 99 | 27 | 0.2727 |
| SHORT | 87 | 24 | 0.2759 |

### Session

| session_bucket | eligible_count | not_enough_data_count | not_enough_data_rate |
| --- | --- | --- | --- |
| ASIA | 77 | 21 | 0.2727 |
| LONDON | 38 | 14 | 0.3684 |
| NY | 56 | 12 | 0.2143 |
| OFF_HOURS | 15 | 4 | 0.2667 |

### Weekday

| weekday | eligible_count | not_enough_data_count | not_enough_data_rate |
| --- | --- | --- | --- |
| Friday | 26 | 7 | 0.2692 |
| Monday | 45 | 13 | 0.2889 |
| Thursday | 37 | 11 | 0.2973 |
| Tuesday | 37 | 10 | 0.2703 |
| Wednesday | 41 | 10 | 0.2439 |

### Top H1 Contexts

| h1_context_id | eligible_count | not_enough_data_count | not_enough_data_rate |
| --- | --- | --- | --- |
| XAUUSD_20260420010000+0000 | 2 | 2 | 1.0 |
| XAUUSD_20260427010000+0000 | 2 | 2 | 1.0 |
| XAUUSD_20260428080000+0000 | 2 | 2 | 1.0 |
| XAUUSD_20260430020000+0000 | 2 | 2 | 1.0 |
| XAUUSD_20260318030000+0000 | 1 | 1 | 1.0 |
| XAUUSD_20260318140000+0000 | 1 | 1 | 1.0 |
| XAUUSD_20260319060000+0000 | 1 | 1 | 1.0 |
| XAUUSD_20260319210000+0000 | 1 | 1 | 1.0 |
| XAUUSD_20260320110000+0000 | 1 | 1 | 1.0 |
| XAUUSD_20260327040000+0000 | 1 | 1 | 1.0 |

### Cause Breakdown

| likely_not_enough_data_cause | count | rate |
| --- | --- | --- |
| WINDOW_TOO_SHORT | 51 | 1.0 |

### NOT_ENOUGH_DATA Vs Available Descriptor

| group | sample_count | avg_available_candle_count | median_available_candle_count | avg_expected_candle_count | avg_missing_candle_count | avg_data_window_seconds | missing_decision_time_count | near_dataset_boundary_count | weekend_or_market_gap_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NOT_ENOUGH_DATA | 51 | 0.0 | 0.0 | 0.0 | 0.0 | nan | 51 | 0 | 0 |
| AVAILABLE_DESCRIPTOR | 135 | 15.2296 | 8.0 | 15.2296 | 0.0 | 853.7778 | 0 | 0 | 5 |

## Critical Conclusion

`WINDOW_CONFIGURATION_ISSUE`

Recommended next step: fix data-window/reporting issue before manual validation.

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
