# Strategy 2 Rulebook v0 Labeling

## Context

The containing M15 model is the current Strategy 2 research model. Previous ex-post separators are not deployable, the manual benchmark exists but is not filled yet, and a transparent deterministic rulebook is needed before manual validation.

## Safety

- Strategy 3 untouched.
- data/XAUUSD/*.csv untouched.
- No live trading, Telegram, broker execution, orders, signals, optimization, or runtime registration.

## Method

- Labels are TAKE / SKIP / UNCERTAIN using explicit decision-time rules only.
- Hard SKIP is limited to objective pre-entry invalidations such as invalid M15 sequence, no H1 sweep, or confirmed no range re-entry.
- `INVALID_NO_DISTRIBUTION` remains diagnostic-only because it is not proven decision-time safe.
- `risk_zone` and `manipulation_zone` are separate classifications.
- Unit handling uses `pip_factor=10.0`: USD/price distance = pips / pip_factor; when pips are present they are used as the explicit source for converted USD distance.
- Reaction quality is not derived automatically in v0; default `reaction_quality_tag` is `NOT_COMPUTED`.
- All thresholds have status `USER_TBD` and require manual benchmark validation.
- This report includes no performance metrics and no TAKE-vs-SKIP outcome comparison.

## Results

- containing rows loaded: `1089`
- containing valid-for-MAE count: `269`
- TAKE count: `0`
- SKIP count: `954`
- UNCERTAIN count: `135`
- NOT_COMPUTED reaction count: `1089`
- UNCERTAIN caused by NOT_COMPUTED reaction count: `135`
- risk_zone distribution: `{"DEEP_TAIL": 87, "EXTREME_TAIL": 121, "LARGE": 151, "STANDARD": 482, "UNKNOWN": 248}`
- manipulation_zone distribution: `{"ACCEPTABLE": 207, "DEEP": 133, "EXTREME": 78, "IDEAL": 223, "SHALLOW": 118, "UNKNOWN": 248, "VERY_DEEP": 82}`
- threshold status values: `{"USER_TBD": 1089}`

## Honest Limitations

- This is not a performance baseline.
- This is not a backtest.
- This is not a signal generator.
- Most samples are expected to be UNCERTAIN because reaction quality defaults to NOT_COMPUTED.
- There is no reaction-quality derivation from M1/M5 in v0.
- There is no edge claim and no deployment decision.

## Verdict Flags

- `RULEBOOK_V0_LABELING_COMPLETE`
- `ALL_THRESHOLDS_USER_TBD`
- `REACTION_QUALITY_NOT_COMPUTED_BY_DEFAULT`
- `MOST_SAMPLES_UNCERTAIN_EXPECTED`
- `NO_PERFORMANCE_CLAIM`
- `NO_DEPLOYMENT_DECISION`
- `MANUAL_VALIDATION_REQUIRED`
- `STRATEGY_2_REMAINS_RESEARCH_ONLY`

## Next Strategy 2-Only Step

- `feat/strategy-2-rulebook-v0-manual-validation`
- or `feat/strategy-2-reaction-quality-derivation`
