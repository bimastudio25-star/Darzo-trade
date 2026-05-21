# Adelin v2 Pre-entry Outcome Diagnostics Summary

Research-only diagnostic replay. This is not validation, not Phase 4 matched-control replay, and not a live decision.

- samples analyzed: 40
- sufficient data: 21
- insufficient data: 19
- output dir: `backtests\reports\adelin_v2_preentry_outcome_diagnostics`

## Verdict flags

- STATIC_LABELING_NOT_USABLE
- OBJECTIVE_REPLAY_DIAGNOSTICS_COMPLETE
- PRE_ENTRY_OUTCOME_SEPARATION_REPORTED
- FAILURE_MODES_REPORTED
- NO_PHASE_4_MATCHED_CONTROL_YET
- ADELIN_REMAINS_RESEARCH_ONLY
- NO_LIVE_DEPLOYMENT_DECISION

## Outcome distribution

- INSUFFICIENT_DATA: 19
- FAST_FAILURE: 16
- GOOD_FAST_REACTION: 5

## Top failure modes

- INSUFFICIENT_DATA: 19
- CONTINUATION_AGAINST_ENTRY: 15
- PRICE_CHOP_AFTER_ENTRY: 12
- REACTION_TOO_LATE: 8
- NO_IMMEDIATE_REACTION: 6
- STOP_TOO_WIDE: 4
- VOLUME_NOT_CONFIRMING_REVERSAL: 4
- TARGET_TOO_FAR: 1

## Top win modes

- CLEAN_TARGET_SPACE: 17
- FVG_IFVG_REACTION: 9
- ROUND_LEVEL_REACTION: 6
- FAST_REACTION: 5
- STRONG_MFE_LOW_MAE: 4
- CLEAN_SWEEP_REJECTION: 3

## Safety

- no old Adelin runtime changes
- no Strategy 2 or Strategy 3 changes
- no live trading
- no Telegram trade alerts
- no broker/order execution
- no candidate generation
- no matched-control replay
- no threshold tuning
