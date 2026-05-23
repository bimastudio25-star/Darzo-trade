# Adelin v2 Confidence-3 Forward Collection Plan — Human Approval

## Context

- Branch: feat/adelin-v2-confidence3-forward-collection-plan
- Commit: eda54b8
- Reviewer: Adelin Bivol
- Date: 2026-05-23
- Decision: APPROVE

This approval applies only to the Adelin v2 confidence-3 / EXISTING_METADATA forward collection plan. It authorizes starting forward collection under the frozen eligibility schema. It does not authorize OHLC reads, H3/H4 proxy computation, proxy diagnostic execution, replay, backtest, matched-control replay, Phase 4, scoring, tuning, runtime changes, live trading, Telegram alerts, broker execution, `order_send`, profitability claims, or deployability claims.

## Approved Scope

Approved:

- forward collection planning
- starting the first forward collection batch only under the frozen eligibility schema
- collecting confidence-3 / EXISTING_METADATA samples
- using the HYBRID manual evidence relationship
- requiring FULL_REVIEW before primary eligibility
- tracking collection rate and progress
- stopping or pausing if collection is too slow or biased

Not approved:

- OHLC read
- H3/H4 proxy computation
- proxy diagnostic execution
- replay
- backtest
- matched-control
- Phase 4
- scoring
- tuning
- threshold changes
- H3 formula changes
- H4 state changes
- runtime changes
- Strategy 2 changes
- Strategy 3 changes
- `data/XAUUSD/*.csv` modification
- live trading
- Telegram alerts
- broker execution
- `order_send`
- profitability claims
- deployability claims

## Pre-Approval Checks

Target:

- 39 additional confidence-3 / EXISTING_METADATA samples are required.
- The existing 21 confidence-3 samples count toward the total target of 60.
- The target is not lowered by this approval.

Forward eligibility:

- `direction_source = EXISTING_METADATA` is required.
- `direction_confidence = 3` is required.
- direct `decision_timestamp` is required.
- stable ID is required.
- source lineage is required.
- reference/entry metadata is required for later pre-entry H3/H4 computation.
- FULL_REVIEW is required before primary eligibility.

Forbidden selection criteria:

- no H3/H4 state selection
- no GOOD/FAST selection
- no outcome selection
- no TP/SL selection
- no PnL selection
- no R multiple selection
- no MFE/MAE selection
- no post-entry behavior selection
- no visual hindsight selection

Collection controls:

- expected collection rate policy is present.
- actual rate per batch is required.
- abandonment/progress threshold is present.
- eligibility schema is frozen.
- schema/rule changes require a new pre-registered plan branch.
- manual evidence relationship is defined as HYBRID.
- RAPID_CAPTURE is not primary-eligible.
- FULL_REVIEW is required for primary eligibility.
- `direction_source` and `direction_confidence` are required before primary eligibility.

Safety:

- Adelin v2 remains Level 0 / Diagnostic Research.
- Phase 4 remains blocked.
- matched-control remains blocked.
- scoring remains blocked.
- runtime remains unchanged.
- live trading remains blocked.
- Telegram alerts remain blocked.
- broker execution remains blocked.
- `order_send` remains blocked.
- profitability claims remain blocked.

## Review Evidence

### 1. Does collection_plan.json contain any data/XAUUSD/*.csv paths?

Answer: NO.

Evidence: `rg` over the plan JSON files found zero `data/XAUUSD/*.csv` path references. The search result was `NO_XAUUSD_CSV_PATH_REFERENCES`.

### 2. Do JSON files contain forbidden keys as eligibility/selection criteria?

Answer: ALLOWED_GUARDRAIL.

Evidence: matches for outcome/post-entry concepts appear only in exclusion or guardrail contexts, including:

- `*_used_for_inclusion: false`
- `*_USED_FOR_INCLUSION` rejection reason codes
- `forbidden_selection_criteria` lists
- rejection/fail-closed descriptions

They are not eligibility or positive selection criteria.

### 3. Does test_adelin_v2_confidence3_forward_collection_plan.py import strategy/runtime/detectors/broker/Telegram/execution/live modules?

Answer: NO.

Evidence: imports are limited to:

- `from __future__ import annotations`
- `import json`
- `from pathlib import Path`

No strategy, runtime, detector, broker, Telegram, execution, or live modules are imported.

### 4. Does the markdown imply automatic Phase 4/live/signals/Telegram/order_send unlock?

Answer: NO.

Evidence: references are blocking or negative language, including:

- "remains blocked"
- "does not unlock"
- "does not enable"
- "Future OHLC reads, H3/H4 proxy execution, matched-control replay, Phase 4, scoring, live, Telegram, broker execution, and `order_send` remain blocked unless separately planned, reviewed, and approved."

`FORWARD_COLLECTION_READY_FOR_PROXY_EXECUTION` explicitly does not unlock Phase 4 or immediate proxy execution.

### 5. Is schema freeze enforced?

Answer: PROCEDURAL_AND_TEST_GUARDED. See the Schema Freeze Clarification section below for the full breakdown.

## Schema Freeze Clarification

Classification: PROCEDURAL_AND_TEST_GUARDED, not TECHNICALLY_ENFORCED.

Evidence inspected:

- `backtests/reports/adelin_v2_confidence3_forward_collection_plan/eligibility_schema.json`
- `backtests/reports/adelin_v2_confidence3_forward_collection_plan/collection_plan.json`
- `backtests/reports/adelin_v2_confidence3_forward_collection_plan/rejection_reasons.json`
- `tests/test_adelin_v2_confidence3_forward_collection_plan.py`

What exists:

- `eligibility_schema.json` declares `schema_version: "1.0"` at the root of the eligibility schema.
- `eligibility_schema.json` declares `eligibility_schema_frozen_at_plan_commit: true`.
- `eligibility_schema.json` declares `any_change_requires_new_pre_registered_plan_branch: true`.
- `eligibility_schema.json` declares `plan_base_commit: "59b3c8e"` as a commit pointer.
- `manual_evidence_schema_reference.schema_version: "1.1"` is a cross-link to the referenced manual trade evidence schema and is not an alternate version of the eligibility schema itself.
- `rejection_reasons.json` includes a `SCHEMA_VERSION_MISSING_OR_MISMATCHED` rejection code for future collected samples.
- `test_eligibility_schema_freeze_and_hybrid_manual_pipeline` asserts the freeze flags (`eligibility_schema_frozen_at_plan_commit`, `any_change_requires_new_pre_registered_plan_branch`) and the HYBRID promotion rules.

What does not exist in this branch:

- No `schema_hash`, `checksum`, `fingerprint`, `sha256`, `md5`, or `digest` field in any plan JSON.
- No `hashlib` import or hash assertion in `tests/test_adelin_v2_confidence3_forward_collection_plan.py`.
- No test asserts the exact value of `schema_version` ("1.0") or compares the schema content to a canonical fingerprint.

Final interpretation:

- The freeze is procedural and test-guarded: the JSON declares the freeze policy, and tests assert the freeze policy flags and the eligibility rules.
- The freeze is not technically immutable: there is no schema hash or fingerprint that a test asserts byte-for-byte, so the JSON content could in principle change without breaking the current tests if the asserted flags and rule values remain in place.
- This is acceptable for a Level 0 / Diagnostic Research plan-only approval and must not be overstated as technical immutability.
- Adding a schema hash or canonical fingerprint enforcement is deferred and would require a separate pre-registered branch defining canonicalization rules (key order, whitespace) and the assertion mechanism.

Scope of this clarification:

- This clarification does not change the eligibility schema, the rejection reasons, the collection plan, the tests, or the runtime.
- This clarification does not approve OHLC reads, H3/H4 proxy computation, proxy diagnostic execution, replay, backtest, matched-control, Phase 4, scoring, tuning, runtime changes, live trading, Telegram alerts, broker execution, `order_send`, profitability claims, or deployability claims.
- Approval remains collection-only under the frozen eligibility schema.

## Forward Collection Conditions

Forward collection may begin only if:

- eligibility schema remains frozen
- collection uses the HYBRID manual evidence relationship
- RAPID_CAPTURE samples are not primary-eligible
- FULL_REVIEW is required for primary eligibility
- `direction_source = EXISTING_METADATA`
- `direction_confidence = 3`
- direct `decision_timestamp` is present
- no outcome, post-entry, H3, or H4 selection is used
- actual collection rate is recorded per batch
- abandonment/progress threshold is monitored

## Next Required Step

Next step:

- begin the first forward collection batch under the frozen schema
- or create a batch template/progress audit structure if not already available

Proxy execution remains blocked until:

- at least 39 additional confidence-3 / EXISTING_METADATA samples are collected
- total confidence-3 is at least 60
- collection is reviewed
- lineage is clean
- timestamps are direct
- no bias failure is detected
- a separate proxy execution branch is explicitly approved

Phase 4 remains blocked. Matched-control remains blocked. Scoring remains blocked. Live trading, Telegram alerts, broker execution, `order_send`, profitability claims, and deployability claims remain blocked.
