# Adelin v2 Direction Metadata Recovery

## Context

Phase 3 static chart labels were not usable as the primary manual labeling path.
The pre-entry/outcome diagnostic replay then analyzed the 40 existing Adelin v2
visual review samples and reported 19 insufficient rows.

Manual inspection confirmed the cause:

- the 19 insufficient rows had `UNKNOWN_DIRECTION_NO_DIRECTIONAL_REPLAY`;
- M1/M5/M15 coverage was present;
- this was not an OHLC gap, weekend, or missing-data problem;
- direction was missing in visual review metadata.

Without direction, the diagnostic replay cannot compute directional MFE/MAE,
SL path, or directional outcome tags.

## Method

The recovery layer is deterministic and pre-entry-only. It uses this priority
order:

1. Existing visual-pack direction metadata.
2. Explicit candidate/signal side metadata if available.
3. Unambiguous liquidity-side metadata.
4. Strict pre-decision M1/M5 sweep inference.
5. Entry/liquidity relation when explicitly available.
6. `UNKNOWN` if no defensible source exists.

For the actual 40-sample pack, existing metadata covered 21 rows and the 19
missing rows were recovered from strict pre-decision sweep inference.

The sweep inference uses only `[anchor - 60m, anchor)` candles, excludes the
anchor candle, excludes all post-anchor candles, and requires at least five
minutes between the detected sweep candle and the anchor. Upward sweep implies
`SHORT`; downward sweep implies `LONG`.

If conflicting pre-entry evidence exists, the row is marked
`CONFLICTING_DIRECTION_EVIDENCE` and remains unusable for directional replay.

## Direction Inference Governance

Frozen rule version:

`adelin_v2_pre_decision_sweep_v1`

Rule name:

`PRE_DECISION_SWEEP_INFERENCE`

Exact heuristic:

- Preserve existing visual-pack `LONG` or `SHORT` direction metadata as
  confidence `3`.
- For missing directions, use explicit candidate/signal side metadata if
  present.
- If no explicit side exists, use unambiguous liquidity-side metadata if
  present.
- If still unknown, inspect only M5 and M1 candles in
  `[decision_timestamp - 60m, decision_timestamp)`.
- The decision/anchor candle is excluded.
- All candles after `decision_timestamp` are excluded.
- A valid sweep candle must be at least 5 minutes before the decision timestamp.
- A sweep of high / upper liquidity maps to `SHORT`.
- A sweep of low / lower liquidity maps to `LONG`.
- The sweep must show pre-decision rejection or move-away by the configured
  rejection threshold.
- Multiple valid sweep events inside the same pre-entry window are resolved by
  the latest defensible sweep event.
- If independent pre-entry sources conflict, the final direction is `UNKNOWN`.
- If no valid pre-entry evidence exists, the final direction is `UNKNOWN`.

Allowed inputs:

- existing visual-pack direction metadata;
- explicit candidate/signal side metadata when present;
- unambiguous pre-entry liquidity-side metadata when present;
- M5 and M1 candles before the decision timestamp only;
- pre-anchor sweep candle, swept level, sweep extreme, and pre-anchor
  rejection/move-away evidence;
- explicit pre-entry entry/liquidity relation metadata when present.

Forbidden inputs:

- candles at or after `decision_timestamp`;
- post-entry price movement;
- MFE/MAE;
- TP/SL hits;
- win/loss;
- diagnostic replay outcome;
- matched-control result;
- manually invented direction.

Confidence governance:

- Confidence `3` means original existing metadata.
- Confidence `2` means inferred from pre-decision sweep evidence.
- Confidence `2` is weaker than confidence `3`; inferred directions must not be
  treated as equal to existing metadata.

Current governance baseline:

- 19 of 40 directions are inferred at confidence `2`.
- Phase 4 remains blocked until this methodology is explicitly accepted.
- Direction-recovered diagnostic outcomes are:
  - `FAST_FAILURE`: 27 / 40
  - `GOOD_FAST_REACTION`: 10 / 40
  - `MIXED_REACTION`: 2 / 40
  - `CHOP_AFTER_ENTRY`: 1 / 40

## Results

- Total samples: 40
- Existing direction count: 21
- Missing direction count: 19
- Recovered direction count: 19
- Final known direction count: 40
- Final unknown direction count: 0
- Direction source counts:
  - `EXISTING_METADATA`: 21
  - `PRE_DECISION_SWEEP_INFERENCE`: 19
- Confidence counts:
  - `3`: 21
  - `2`: 19
- Final direction distribution:
  - `LONG`: 20
  - `SHORT`: 20
  - `UNKNOWN`: 0
- Post-entry data used for direction recovery: 0 rows

## Diagnostic Rerun

The pre-entry/outcome diagnostics were rerun with the recovered final direction
table.

Before recovery:

- Sufficient data: 21
- Insufficient data: 19
- `UNKNOWN_DIRECTION_NO_DIRECTIONAL_REPLAY`: 19
- Outcomes:
  - `INSUFFICIENT_DATA`: 19
  - `FAST_FAILURE`: 16
  - `GOOD_FAST_REACTION`: 5

After recovery:

- Sufficient data: 40
- Insufficient data: 0
- `UNKNOWN_DIRECTION_NO_DIRECTIONAL_REPLAY`: 0
- Outcomes:
  - `FAST_FAILURE`: 27
  - `GOOD_FAST_REACTION`: 10
  - `MIXED_REACTION`: 2
  - `CHOP_AFTER_ENTRY`: 1

Top failure tags after recovery:

- `CONTINUATION_AGAINST_ENTRY`: 24
- `PRICE_CHOP_AFTER_ENTRY`: 19
- `REACTION_TOO_LATE`: 15
- `NO_IMMEDIATE_REACTION`: 11
- `STOP_TOO_WIDE`: 7
- `VOLUME_NOT_CONFIRMING_REVERSAL`: 7

Top win tags after recovery:

- `CLEAN_TARGET_SPACE`: 33
- `FVG_IFVG_REACTION`: 23
- `ROUND_LEVEL_REACTION`: 15
- `FAST_REACTION`: 10
- `CLEAN_SWEEP_REJECTION`: 7
- `STRONG_MFE_LOW_MAE`: 7

## Tag Semantics

Failure and win tags are multi-label fields separated by `|`. Counts are not
mutually exclusive outcome buckets. A sample can have both a reaction tag and a
failure-mode tag when the path is dirty or late.

## Non-Directional Replay

Non-directional replay was not used as the primary diagnostic.

Reason: taking the best movement in either direction changes the semantics of
directional reversal diagnostics and can create optimistic bias. Directional
MFE/MAE must remain based on a pre-entry direction source.

## Verdict Flags

- `DIRECTION_METADATA_RECOVERY_COMPLETE`
- `PRE_ENTRY_ONLY_DIRECTION_RECOVERY`
- `UNKNOWN_DIRECTION_COUNT_REPORTED`
- `NO_POST_ENTRY_DIRECTION_INFERENCE`
- `DIAGNOSTIC_TAGS_MULTI_LABEL_CONFIRMED`
- `PHASE_4_STILL_BLOCKED`
- `ADELIN_REMAINS_RESEARCH_ONLY`
- `NO_LIVE_DEPLOYMENT_DECISION`
- `NON_DIRECTIONAL_REPLAY_NOT_USED_AS_PRIMARY`
- `DIRECTION_COVERAGE_IMPROVED`

## Safety

No old Adelin runtime logic was modified. Strategy 2 and Strategy 3 were not
touched. No live trading was enabled. No Telegram trade alerts were sent. No
broker or order execution path was called. No candidate pack was generated. No
matched-control replay or Phase 4 work was started. The v3 stash was not
applied or popped.

## Next Action

Review the direction-recovered diagnostics and decide whether the cleaned
40-row diagnostic sample is methodologically acceptable for a pre-registered
next diagnostic step.

Phase 4 remains blocked until direction coverage and sample validity are
accepted in a new pre-registered plan.
