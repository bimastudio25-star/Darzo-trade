# Adelin v2 Confidence-3 Forward Collection Batch Template

## Purpose

This document defines the batch template and progress audit structure for Adelin v2 confidence-3 / EXISTING_METADATA forward collection.

This branch creates templates only. It does not collect samples, read OHLC, compute H3/H4 proxies, run replay, run backtest, run matched-control, unlock Phase 4, or create signals.

## Current Target

- Existing confidence-3 / EXISTING_METADATA samples: 21.
- Target total confidence-3 samples: 60.
- Additional required confidence-3 samples: 39.

The larger H3/H4 proxy diagnostic remains blocked until at least 39 additional eligible samples are collected, total confidence-3 reaches at least 60, and the collection is reviewed for clean lineage, direct timestamps, and absence of bias failure.

## Created Templates

The batch structure lives in:

- `backtests/reports/adelin_v2_confidence3_forward_collection_batches/batch_template.csv`
- `backtests/reports/adelin_v2_confidence3_forward_collection_batches/batch_template.json`
- `backtests/reports/adelin_v2_confidence3_forward_collection_batches/progress_summary_template.json`
- `backtests/reports/adelin_v2_confidence3_forward_collection_batches/rejection_log_template.csv`

`batch_template.csv` is a header-only future collection row template. `rejection_log_template.csv` includes a rejection reason catalog as template rows; those rows are not collected samples.

## Eligibility Rules

Primary eligibility requires:

- `direction_source = EXISTING_METADATA`
- `direction_confidence = 3`
- `evidence_capture_mode = FULL_REVIEW`
- `collection_pipeline_relationship = HYBRID`
- direct `decision_timestamp` metadata
- stable `sample_id` or approved unique identifier
- source lineage
- reference/entry metadata for later pre-entry H3/H4 computation
- `collected_pre_decision_only = true`
- `post_entry_data_used_for_inclusion = false`
- `h3_h4_state_known_at_collection = false`
- `outcome_used_for_inclusion = false`

RAPID_CAPTURE rows are not primary-eligible. A RAPID_CAPTURE row may be useful as an initial human note, but it must be promoted to FULL_REVIEW with all forward-collection metadata before it can count as a primary confidence-3 sample.

## Forbidden Selection

Forward collection must not select rows based on:

- H3 state
- H4 state
- GOOD/FAST outcome
- outcome group
- TP/SL hit
- PnL
- R multiple
- future MFE/MAE
- future liquidity behavior
- post-entry behavior
- post-entry candles
- visual hindsight
- whether the setup worked

The collection template is for metadata capture and audit only. It is not an H3/H4 proxy execution sheet.

## Batch Fields

Each future batch should record:

- `batch_id`
- collection start and end dates
- collector
- artifact path
- eligibility schema version and commit
- HYBRID collection pipeline relationship
- expected collection rate in samples per week
- actual collection rate in samples per week
- candidate row count
- eligible confidence-3 count
- rejected count
- duplicate count
- cumulative existing confidence-3 count
- cumulative new confidence-3 count
- cumulative total confidence-3 count
- remaining samples to target 60
- weeks without minimum progress
- batch decision

Allowed batch decisions:

- `FORWARD_COLLECTION_BATCH_ACCEPTED`
- `FORWARD_COLLECTION_BATCH_NEEDS_REVIEW`
- `FORWARD_COLLECTION_BATCH_REJECTED`

## Progress Policy

Actual collection rate must be tracked per batch.

The abandonment/progress threshold is 12 weeks without minimum progress. Minimum progress means at least 1 new eligible confidence-3 / EXISTING_METADATA sample in the period, unless manually reviewed.

If collection is stalled, the next review should consider `PAUSE_H3_H4_PATH` or require a new pre-registered collection strategy. Do not lower the target of 60 total confidence-3 samples in the batch template.

Progress summary statuses:

- `FORWARD_COLLECTION_NOT_STARTED`
- `FORWARD_COLLECTION_IN_PROGRESS`
- `FORWARD_COLLECTION_READY_FOR_REVIEW`
- `FORWARD_COLLECTION_STALLED`
- `PAUSE_H3_H4_PATH_RECOMMENDED`

## Rejection Log

The rejection log template requires:

- `sample_id`
- `batch_id`
- `source_artifact`
- `rejection_reason`
- `rejection_category`
- `rejection_detail`
- `reviewer_notes`

Required rejection reasons include:

- `DIRECTION_SOURCE_FIELD_ABSENT`
- `DIRECTION_CONFIDENCE_FIELD_ABSENT`
- `NON_PRIMARY_DIRECTION_SOURCE`
- `NON_PRIMARY_DIRECTION_CONFIDENCE`
- `DECISION_TIMESTAMP_MISSING`
- `DECISION_TIMESTAMP_AMBIGUOUS`
- `SAMPLE_ID_MISSING`
- `ID_RESOLUTION_AMBIGUOUS`
- `DUPLICATE_SAMPLE`
- `RAPID_CAPTURE_NOT_PRIMARY_ELIGIBLE`
- `SOURCE_LINEAGE_MISSING`
- `REFERENCE_PRICE_MISSING`
- `POST_ENTRY_DATA_USED_FOR_INCLUSION`
- `OUTCOME_USED_FOR_INCLUSION`
- `H3_H4_STATE_USED_FOR_SELECTION`
- `VISUAL_HINDSIGHT_SELECTION`
- `SCHEMA_VERSION_MISMATCH`
- `SCHEMA_RULE_CHANGED_WITHOUT_NEW_PLAN`
- `UNKNOWN_REJECTION_REASON`

## Safety

Adelin v2 remains Level 0 / Diagnostic Research.

This branch:

- does not collect samples
- does not read OHLC
- does not inspect `data/XAUUSD/*.csv`
- does not compute H3/H4 states
- does not run a proxy diagnostic
- does not run replay
- does not run backtest
- does not run matched-control
- does not unlock Phase 4
- does not modify runtime logic
- does not modify Strategy 2
- does not modify Strategy 3
- does not modify `data/XAUUSD/*.csv`
- does not enable live trading
- does not enable orders
- does not enable Telegram alerts
- does not enable broker execution
- does not call or introduce `order_send`
- does not create signals
- does not claim edge, profitability, or deployability

## Next Step

The first real forward collection batch may be created manually using this template.

Proxy execution remains blocked until:

- at least 39 additional eligible confidence-3 / EXISTING_METADATA samples are collected
- total confidence-3 samples are at least 60
- collection is reviewed
- lineage is clean
- timestamps are direct
- no bias failure is detected
- a separate proxy execution branch is explicitly approved
