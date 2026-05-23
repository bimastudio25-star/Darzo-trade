# Adelin v2 Confidence-3 Forward Collection Plan

## Context

The larger confidence-stratified H3/H4 proxy diagnostic plan requires at least 60 total confidence-3 / EXISTING_METADATA samples. The source-availability audit at commit `59b3c8e` found only the existing 21 analyzed confidence-3 samples and no additional eligible confidence-3 samples in the approved artifacts.

That audit scanned 13 artifacts and 2340 rows. It rejected 2256 rows, including 2183 rows where `direction_source` was absent and 73 rows with a non-primary direction source. The decision was `INSUFFICIENT_CONFIDENCE_3_SOURCE_AVAILABILITY`.

This plan defines a forward/new collection path for at least 39 additional confidence-3 / EXISTING_METADATA samples. It is plan-only. It does not collect samples, read OHLC, compute H3/H4, run replay, run backtest, run matched-control, or unlock Phase 4.

## Objective

Target:

- Minimum total confidence-3 / EXISTING_METADATA samples: 60.
- Existing analyzed confidence-3 samples counted toward the target: 21.
- Additional forward/new confidence-3 samples required: 39.

This target must not be lowered by a future execution branch. If fewer than 39 additional confidence-3 samples are collected, the correct decision is `FORWARD_COLLECTION_IN_PROGRESS` or `PAUSE_H3_H4_PATH`, not proxy execution.

## Forward Collection Definition

A forward-collected sample is primary-eligible only if it is recorded after this plan is approved and contains direct pre-decision metadata:

- `direction_source = EXISTING_METADATA`
- `direction_confidence = 3`
- `direction` explicitly present as `LONG` or `SHORT`
- direct `decision_timestamp`
- `sample_id` or another stable unique identifier
- source artifact lineage
- reference/entry metadata needed for later pre-entry H3/H4 computation
- collected without using H3/H4 proxy result
- collected without using outcome result
- collected without using TP/SL hit, PnL, R multiple, future MFE/MAE, future liquidity behavior, or post-entry candles

Forward collection must be based on pre-decision metadata only.

## Direction Source Policy

`direction_source` must be explicitly present. Missing `direction_source` must be rejected with `DIRECTION_SOURCE_FIELD_ABSENT`; it must never be interpreted as `EXISTING_METADATA`.

Primary evidence requires:

- `direction_source = EXISTING_METADATA`
- `direction_confidence = 3`

Not primary:

- `PRE_DECISION_SWEEP_INFERENCE`
- any inferred or recovered direction
- missing `direction_source`
- missing `direction_confidence`
- `direction_confidence < 3`

Confidence-2 samples may be logged as secondary/sensitivity context, but they must not count toward the 39 additional primary samples.

## Timestamp Policy

Forward-collected primary samples must have a direct `decision_timestamp`.

For this plan:

- reconstructed timestamps are not primary-eligible
- timestamps must not be inferred from OHLC
- timestamps must not be inferred from post-entry outcomes
- missing timestamps are rejected as `DECISION_TIMESTAMP_MISSING`
- ambiguous timestamps are rejected as `DECISION_TIMESTAMP_AMBIGUOUS`

## Sample ID Policy

Each collected sample must include:

- `sample_id` or stable unique identifier
- source artifact
- collection batch id
- collection timestamp
- decision timestamp
- direction
- direction source
- direction confidence

The preferred authoritative ID field is `sample_id`. If `sample_id` is unavailable, a future collection review may use `candidate_id` or source artifact row id only if the ID is stable and documented. Ambiguous ID resolution is rejected with `ID_RESOLUTION_AMBIGUOUS`.

Duplicates are rejected or marked duplicate and do not count toward the 39 additional samples.

## Collection Batches

Each batch must record:

- `batch_id`
- collection start and end dates
- artifact path
- collector/source
- number of candidate samples
- number of eligible confidence-3 samples
- number rejected
- rejection reasons
- whether any rule changed
- expected collection rate in samples per week
- actual collection rate in samples per week
- cumulative eligible confidence-3 count
- cumulative remaining to target
- weeks without minimum progress

If collection rules change, start a new batch and document the change. Do not silently mix batches with different rules.

## Collection Rate And Abandonment Policy

Collection feasibility must be tracked instead of assumed.

- Actual rate must be recorded per batch.
- Abandonment/progress threshold: 12 weeks without minimum progress.
- Minimum progress definition: at least 1 new eligible confidence-3 / EXISTING_METADATA sample in the period, unless manually reviewed.

Feasibility examples:

- If Adelin v2 produces 5 confidence-3 samples per week, 39 additional samples may take about 8 weeks.
- If Adelin v2 produces 1 confidence-3 sample per week, 39 additional samples may take about 39 weeks.

If there is no meaningful progress for the threshold period, a future review must consider `PAUSE_H3_H4_PATH` or revise the collection strategy through a new pre-registered plan.

## Eligibility Schema Freeze

The eligibility schema is frozen with this plan. The branch is based on commit `59b3c8e`; the final branch commit records the approved schema in git history.

Rules:

- Do not change eligibility criteria during collection.
- If eligibility criteria must change, create a new pre-registered plan branch.
- Do not retroactively apply changed eligibility to prior batches without explicit methodology review.
- Do not silently mix samples collected under different eligibility schemas.

## Manual Evidence Schema Relationship

Selected relationship: `HYBRID`.

Justification: the existing manual evidence schema and RAPID_CAPTURE / FULL_REVIEW workflow are useful for human capture ergonomics, but the confidence-3 forward collection target requires stricter metadata than qualitative manual evidence. The hybrid path reuses the capture workflow while adding required forward-collection fields before any row can count as primary evidence.

Hybrid rules:

- RAPID_CAPTURE rows are draft capture only.
- RAPID_CAPTURE rows are not primary-eligible.
- A row must be promoted to FULL_REVIEW before primary eligibility.
- FULL_REVIEW must include `direction_source`, `direction_confidence`, direct `decision_timestamp`, source lineage, batch metadata, and schema version metadata.
- Missing `direction_source` rejects primary eligibility.
- Missing `direction_confidence` rejects primary eligibility.
- Missing direct `decision_timestamp` rejects primary eligibility.

## Forbidden Selection Criteria

Do not select samples based on:

- H3 state
- H4 state
- GOOD/FAST result
- outcome group
- TP/SL
- PnL
- R multiple
- future MFE/MAE
- future liquidity behavior
- post-entry candles
- visual hindsight
- whether the setup worked
- only attractive examples
- manual balancing of H3/H4 states
- optimized sample selection

Do not select only attractive examples. Do not balance H3/H4 states manually. Do not optimize sample selection.

## Allowed Selection Criteria

Allowed:

- sample belongs to Adelin v2 candidate/research workflow
- sample has direct metadata required by the schema
- sample was captured according to forward collection rules
- direction was explicitly known at decision time
- no post-entry data used for inclusion

## Future Collection Schema

Future collection output must support CSV and JSON and include:

- `sample_id`
- `batch_id`
- `source_artifact`
- `collection_timestamp`
- `decision_timestamp`
- `symbol`
- `timeframe_context`
- `direction`
- `direction_source`
- `direction_confidence`
- `reference_price` or `entry_reference`
- `source_lineage`
- `collected_pre_decision_only = true`
- `post_entry_data_used_for_inclusion = false`
- `h3_h4_state_known_at_collection = false`
- `outcome_used_for_inclusion = false`
- `collection_pipeline_relationship`
- `evidence_capture_mode`, such as RAPID_CAPTURE or FULL_REVIEW when using the hybrid pipeline
- `eligibility_schema_version`
- `eligibility_schema_commit`
- `rejection_reason` for rejected rows

## Acceptance Criteria

Future collection is acceptable only if:

- additional confidence-3 / EXISTING_METADATA samples are at least 39
- total confidence-3 including the existing 21 is at least 60
- `direction_source` is present for all primary samples
- `direction_confidence` is present for all primary samples
- `decision_timestamp` is direct metadata for all primary samples
- duplicate count is documented
- rejected samples are documented
- actual collection rate is reported per batch
- eligibility schema version is reported per batch
- no H3/H4 proxy computation occurs during collection
- no OHLC is read during collection unless separately approved
- no outcome-based selection is used
- Phase 4 remains blocked
- matched-control remains blocked
- scoring remains blocked
- live, order_send, broker execution, and Telegram remain blocked

## Decision Outcomes

`FORWARD_COLLECTION_READY_FOR_PROXY_EXECUTION` means at least 39 additional confidence-3 samples were collected, total confidence-3 is at least 60, lineage is clean, timestamps are direct, no outcome selection was used, and proxy execution may be planned separately. It does not unlock Phase 4 or immediate proxy execution.

`FORWARD_COLLECTION_IN_PROGRESS` means some valid samples were collected, but fewer than 39 additional samples exist. Continue collection. No proxy execution.

`FORWARD_COLLECTION_SCHEMA_FAILURE` means required metadata is missing or inconsistent. Repair the collection schema before continuing.

`FORWARD_COLLECTION_BIAS_FAILURE` means samples were selected using outcome, H3/H4 state, hindsight, or post-entry data. Invalidate the affected batch.

`PAUSE_H3_H4_PATH` means forward collection is too slow or not feasible. Keep Adelin research-only and do not proceed to proxy execution.

## Safety

Adelin v2 remains Level 0 / Diagnostic Research.

This branch:

- does not read OHLC
- does not compute H3/H4 proxies
- does not execute a proxy diagnostic
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
- does not call or introduce broker execution or `order_send`
- does not claim edge, profitability, or deployability

Future OHLC reads, H3/H4 proxy execution, matched-control replay, Phase 4, scoring, live, Telegram, broker execution, and `order_send` remain blocked unless separately planned, reviewed, and approved.
