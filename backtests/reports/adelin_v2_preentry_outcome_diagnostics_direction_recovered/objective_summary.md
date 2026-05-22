# Adelin v2 Pre-entry Outcome Diagnostics Summary

Research-only diagnostic replay. This is not validation, not Phase 4 matched-control replay, and not a live decision.

- samples analyzed: 40
- sufficient data: 40
- insufficient data: 0
- output dir: `backtests\reports\adelin_v2_preentry_outcome_diagnostics_direction_recovered`

## Verdict flags

- STATIC_LABELING_NOT_USABLE
- OBJECTIVE_REPLAY_DIAGNOSTICS_COMPLETE
- PRE_ENTRY_OUTCOME_SEPARATION_REPORTED
- FAILURE_MODES_REPORTED
- NO_PHASE_4_MATCHED_CONTROL_YET
- ADELIN_REMAINS_RESEARCH_ONLY
- NO_LIVE_DEPLOYMENT_DECISION

## Outcome distribution

- FAST_FAILURE: 27
- GOOD_FAST_REACTION: 10
- MIXED_REACTION: 2
- CHOP_AFTER_ENTRY: 1

## Top failure modes

- CONTINUATION_AGAINST_ENTRY: 24
- PRICE_CHOP_AFTER_ENTRY: 19
- REACTION_TOO_LATE: 15
- NO_IMMEDIATE_REACTION: 11
- STOP_TOO_WIDE: 7
- VOLUME_NOT_CONFIRMING_REVERSAL: 7
- TARGET_TOO_FAR: 1

## Top win modes

- CLEAN_TARGET_SPACE: 33
- FVG_IFVG_REACTION: 23
- ROUND_LEVEL_REACTION: 15
- FAST_REACTION: 10
- CLEAN_SWEEP_REJECTION: 7
- STRONG_MFE_LOW_MAE: 7

## Safety

- no old Adelin runtime changes
- no Strategy 2 or Strategy 3 changes
- no live trading
- no Telegram trade alerts
- no broker/order execution
- no candidate generation
- no matched-control replay
- no threshold tuning
