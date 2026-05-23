# Adelin v2 Forward Collection Batch 001 Manual Shell

This folder contains the empty manual shell for `batch_001_manual`. It is ready for Adelin to fill future forward-collected Adelin v2 samples by hand.

This shell does not collect samples automatically. It does not read OHLC, does not compute H3/H4 proxy states, does not run replay, does not run backtest, does not run matched-control, does not unlock Phase 4, does not create scoring, does not create signals, does not enable Telegram operational alerts, does not call broker code, and does not use `order_send`.

## Files

- `batch_001_manual.csv`: header-only manual collection sheet.
- `batch_001_manual.json`: batch metadata and fail-closed eligibility rules.
- `batch_001_progress_summary.json`: progress placeholder; currently zero new validated samples.
- `batch_001_rejection_log.csv`: header-only rejection log for rows that fail primary eligibility.

## Current Status

- Existing confidence-3 / EXISTING_METADATA samples: 21.
- Target total confidence-3 samples: 60.
- Additional required confidence-3 samples: 39.
- Batch 001 new validated samples: 0.
- Status: `NO_NEW_CONFIDENCE3_SAMPLES_VALIDATED_YET`.

## How To Fill batch_001_manual.csv

Fill one row per future forward-collected Adelin v2 sample.

Primary eligible rows require:

- `direction_source = EXISTING_METADATA`
- `direction_confidence = 3`
- `evidence_capture_mode = FULL_REVIEW`
- review mode equivalent: `FULL_REVIEW`
- `collection_pipeline_relationship = HYBRID`
- direct `decision_timestamp`
- stable `sample_id`
- source lineage
- reference/entry metadata for later pre-entry H3/H4 computation
- `collected_pre_decision_only = true`
- `post_entry_data_used_for_inclusion = false`
- `h3_h4_state_known_at_collection = false`
- `outcome_used_for_inclusion = false`

RAPID_CAPTURE is allowed only as a non-primary draft. RAPID_CAPTURE rows must have `is_primary_eligible = false` until promoted to FULL_REVIEW and completed with all required metadata.

## Fail-Closed Rules

If a row is incomplete, uncertain, or violates any inclusion rule:

- set `is_primary_eligible = false`
- add a `rejection_reason`
- add details to `batch_001_rejection_log.csv`

Do not count empty rows, incomplete rows, RAPID_CAPTURE rows, inferred direction rows, missing timestamp rows, or duplicate rows as primary eligible.

## Forbidden Selection

Do not select rows based on:

- H3 state
- H4 state
- GOOD/FAST result
- outcome group
- TP/SL
- PnL
- R multiple
- future MFE/MAE
- future liquidity behavior
- post-entry behavior
- post-entry candles
- visual hindsight
- whether the setup worked

## Safety

Adelin v2 remains Level 0 / Diagnostic Research. Phase 4 remains blocked. Proxy execution remains blocked. Matched-control remains blocked. Live trading, operational Telegram alerts, broker execution, and `order_send` remain blocked.

## Next Step

Manually fill future Adelin v2 forward samples into `batch_001_manual.csv`. Proxy execution remains blocked until at least 39 additional eligible confidence-3 / EXISTING_METADATA samples are collected, total confidence-3 reaches at least 60, and the collection is reviewed under a separate approved branch.
