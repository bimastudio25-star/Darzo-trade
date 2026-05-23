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

Answer: DOCUMENTED_AND_TESTED.

Evidence: `eligibility_schema.json` declares:

- `eligibility_schema_frozen_at_plan_commit: true`
- `any_change_requires_new_pre_registered_plan_branch: true`

Test coverage asserts this in:

- `test_eligibility_schema_freeze_and_hybrid_manual_pipeline`

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
