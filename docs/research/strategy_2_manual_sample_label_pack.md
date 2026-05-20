# Strategy 2 Manual Sample Label Pack

## Context

The statistical sample recorder was built successfully. The M15 HH:45/x:45 filter was corrected, TP anchoring to the H1 liquidity level was confirmed, and the broad automatic valid sample pool showed an unusable raw max SL because the tail reached 62.8 USD. The body of the distribution remains plausible because most samples were <=8 USD and <=12 USD. The missing part is user/A+ filtering.

## Purpose

This branch creates a manual sample label schema so user-labeled trades, missed trades, rejected setups, and invalid examples can be compared with the automatic sample pool. It does not create final deterministic filters or live signals.

## Safety

- Strategy 3 untouched.
- data/XAUUSD/*.csv untouched.
- No live trading.
- No Telegram.
- No broker execution.
- No order_send.
- No orders.
- Research-only.

## Label Schema

Required minimum fields:
- manual_sample_id
- symbol
- h1_timestamp or approximate timestamp
- direction
- user_grade
- manual_trade_taken
- notes or user_reasoning

Recommended fields:
- h1_high/h1_low/liquidity level
- manual entry/SL/TP
- reaction_quality
- candle_anatomy_quality
- avoid_reason
- screenshot_ref

The schema also supports M15 x:45 fields, manipulation/expansion values in USD and pips, TP distances, setup model, compression state, move-consumed state, and reviewer notes.

## How To Use

1. Generate the template:
   `python scripts/create_strategy_2_manual_label_template.py --output-dir backtests/reports/strategy_2_manual_sample_label_pack --format both`
2. Create `manual_samples.csv` from the template.
3. Fill 10-30 samples minimum; 30+ preferred.
4. Include A+ winners, losers, BE trades, valid no-entry samples, rejected setups, and invalid examples.
5. Do not include only winners.
6. Run:
   `python scripts/analyze_strategy_2_manual_sample_labels.py --labels-path backtests/reports/strategy_2_manual_sample_label_pack/manual_samples.csv --auto-samples-path backtests/reports/strategy_2_statistical_sample_recorder/h1_liquidity_samples.csv --output-dir backtests/reports/strategy_2_manual_sample_label_pack --dry-run`

## Analysis Method

- Validate partial manual labels without requiring every optional field.
- Match manual labels to automatic samples by timestamp, direction, and liquidity level when available.
- Build manual subset profiles for A_PLUS, A_PLUS+A, A_PLUS+A+B, NO_TRADE, and INVALID.
- Compare each subset against the automatic global sample pool.
- Analyze the deep-tail automatic samples where manipulation_depth_usd > 12.

## Expected Outputs

- manual_label_validation.json
- manual_profile_summary.json
- manual_vs_global_comparison.csv
- deep_tail_analysis.csv
- manual_sample_label_report.md

## Verdict Flags

- MANUAL_SAMPLE_LABEL_PACK_BUILT
- MANUAL_LABEL_SCHEMA_CREATED
- MANUAL_LABEL_TEMPLATE_CREATED
- GLOBAL_VALID_SAMPLE_POOL_TOO_BROAD
- DEEP_TAIL_DRIVES_RAW_MAX_EXCURSION
- BODY_OF_DISTRIBUTION_PLAUSIBLE
- USER_A_PLUS_FILTER_REQUIRED
- UNIT_CONVERSION_GUARDED
- STRATEGY_2_REMAINS_RESEARCH_ONLY
- NO_LIVE_DEPLOYMENT_DECISION

## Next Step

Strategy 2-only next branch: `feat/strategy-2-manual-sample-profile-comparison` after real manual labels are provided.
