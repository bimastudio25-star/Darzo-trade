# Adelin v2 Confidence-3 Forward Collection Batch 001 Manual Shell

## Purpose

This branch creates the first manual shell for Adelin v2 confidence-3 / EXISTING_METADATA forward collection.

It does not collect samples. It does not read OHLC. It does not compute H3/H4 proxy states. It does not run replay, backtest, matched-control, Phase 4, scoring, or signal generation.

## Batch 001 Files

Created under `backtests/reports/adelin_v2_confidence3_forward_collection_batches/`:

- `batch_001_manual.csv`
- `batch_001_manual.json`
- `batch_001_progress_summary.json`
- `batch_001_rejection_log.csv`
- `README_batch_001_manual.md`

`batch_001_manual.csv` is header-only. It contains no human-filled sample rows yet.

## Current Status

- Existing confidence-3 / EXISTING_METADATA samples: 21.
- Target total confidence-3 samples: 60.
- Additional required confidence-3 samples: 39.
- Batch 001 new validated samples: 0.
- Status: `NO_NEW_CONFIDENCE3_SAMPLES_VALIDATED_YET`.

The manual shell is fail-closed. Empty or incomplete rows do not count as primary eligible.

## Primary Eligibility

Primary eligible rows require:

- `direction_source = EXISTING_METADATA`
- `direction_confidence = 3`
- review mode / `evidence_capture_mode = FULL_REVIEW`
- direct `decision_timestamp`
- stable `sample_id`
- source lineage
- reference/entry metadata for later pre-entry H3/H4 computation
- `collection_pipeline_relationship = HYBRID`
- `collected_pre_decision_only = true`
- `post_entry_data_used_for_inclusion = false`
- `h3_h4_state_known_at_collection = false`
- `outcome_used_for_inclusion = false`

RAPID_CAPTURE rows are allowed only as non-primary drafts. They are not primary eligible until promoted to FULL_REVIEW and completed with the required metadata.

## Rejection Logging

Use `batch_001_rejection_log.csv` for rows that fail eligibility. Common reasons include:

- missing `direction_source`
- missing `direction_confidence`
- non-primary direction source
- non-primary confidence
- missing or ambiguous direct decision timestamp
- missing sample ID
- ambiguous ID resolution
- duplicate sample
- RAPID_CAPTURE not primary eligible
- missing lineage
- missing reference/entry metadata
- post-entry data used for inclusion
- outcome used for inclusion
- H3/H4 state used for selection
- visual hindsight selection
- schema version mismatch

## Forbidden Selection

Manual collection must not use:

- H3 state
- H4 state
- GOOD/FAST result
- TP/SL
- PnL
- R multiple
- future MFE/MAE
- post-entry behavior
- future liquidity behavior
- visual hindsight
- whether the setup worked

## Safety

This branch:

- does not read OHLC
- does not inspect or modify `data/XAUUSD/*.csv`
- does not compute H3/H4 proxy states
- does not run replay
- does not run backtest
- does not run matched-control
- does not unlock Phase 4
- does not create scoring
- does not modify runtime logic
- does not modify Strategy 2
- does not modify Strategy 3
- does not enable live trading
- does not enable orders
- does not enable Telegram operational signals
- does not call broker code or `order_send`
- does not put secrets in code, docs, or logs
- does not claim edge, profitability, or deployability

Adelin v2 remains Level 0 / Diagnostic Research.

## Next Step

Adelin can manually fill future eligible samples into `batch_001_manual.csv`.

Proxy execution remains blocked until:

- at least 39 additional eligible confidence-3 / EXISTING_METADATA samples are collected
- total confidence-3 reaches at least 60
- collection is reviewed
- lineage is clean
- timestamps are direct
- no outcome, H3/H4, post-entry, or hindsight selection is detected
- a separate proxy execution branch is explicitly approved
