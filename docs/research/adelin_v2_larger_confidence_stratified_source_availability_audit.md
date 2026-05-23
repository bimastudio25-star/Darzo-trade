# Adelin v2 Larger Confidence-Stratified Source Availability Audit

## Context

The approved larger confidence-stratified H3/H4 proxy plan requires at least 60 total confidence-3 / EXISTING_METADATA samples before H3/H4 separator validity can be reviewed methodologically. The existing 21 confidence-3 samples already analyzed count toward that total, so at least 39 additional confidence-3 / EXISTING_METADATA samples are required.

This branch is a source-availability audit only. It does not approve proxy execution.

## Audit Question

Can the approved larger confidence-stratified H3/H4 proxy diagnostic reach at least 60 total confidence-3 / EXISTING_METADATA samples, including the existing 21 already analyzed, without reading OHLC and without changing sampling rules?

Answer:

No. The target is not currently met.

## Method

Only metadata/report artifacts were inspected. No OHLC files were read.

Eligibility required:

* direction_source = EXISTING_METADATA.
* direction_confidence = 3.
* decision timestamp present directly or reconstructable from metadata.
* direction LONG/SHORT present.
* stable sample identifier present.
* clear lineage.
* no duplicate of the existing 21 confidence-3 samples unless counted as already included.

Strict rule applied:

* Missing direction_source was rejected.
* direction_recovery_source was not treated as direction_source.
* Confidence-2 / PRE_DECISION_SWEEP_INFERENCE rows were not counted as primary evidence.
* H3/H4 states were not used for selection.
* Outcomes, TP/SL, PnL, R multiple, MFE/MAE, and future liquidity behavior were not used for selection.

## Artifacts Scanned

The audit scanned 13 Adelin v2 report artifacts:

* `backtests/reports/adelin_v2_h3_h4_proxy_diagnostic_execution/h3_h4_proxy_per_sample.csv`
* `backtests/reports/adelin_v2_direction_metadata_recovery/direction_recovery.csv`
* `backtests/reports/adelin_v2_good_vs_fast_failure_diagnostic_execution/comparison_results.csv`
* `backtests/reports/adelin_v2_good_vs_fast_failure_diagnostic_execution/human_review_priority.csv`
* `backtests/reports/adelin_v2_preentry_outcome_diagnostics_direction_recovered/sample_diagnostics.csv`
* `backtests/reports/adelin_v2_preentry_outcome_diagnostics/sample_diagnostics.csv`
* `backtests/reports/adelin_v2_expanded_candidate_window_pack/manual_labels_template.csv`
* `backtests/reports/adelin_v2_expanded_objective_outcome_replay/enriched_manual_labels_template.csv`
* `backtests/reports/adelin_v2_expanded_objective_outcome_replay/objective_outcome_replay.csv`
* `backtests/reports/adelin_v2_objective_outcome_replay/enriched_manual_labels_template.csv`
* `backtests/reports/adelin_v2_objective_outcome_replay/objective_outcome_replay.csv`
* `backtests/reports/adelin_v2_visual_review_pack/manual_labels_template.csv`
* `backtests/reports/adelin_v2_phase_3_visual_review_labels/manual_labels_template.csv`

## Results

Summary:

* Existing analyzed confidence-3 / EXISTING_METADATA count: 21.
* Additional available confidence-3 / EXISTING_METADATA count: 0.
* Total confidence-3 if included: 21.
* Required additional confidence-3 count: 39.
* Target >=60 met: no.
* Decision: INSUFFICIENT_CONFIDENCE_3_SOURCE_AVAILABILITY.

Duplicate handling:

* Unique duplicate existing samples detected: 21.
* Duplicate rows detected across other exact-source artifacts: 63.
* Duplicates were not counted as additional samples.

Rejected and ambiguous samples:

* Rejected rows: 2256.
* Ambiguous rows: 0.
* Main rejection reasons:
  * DIRECTION_SOURCE_FIELD_ABSENT: 2183.
  * NON_PRIMARY_DIRECTION_SOURCE: 73.

Timestamp audit:

* Direct timestamp count: 21.
* Reconstructed timestamp count: 0.
* Ambiguous timestamp count: 0.
* No timestamp reconstruction was used.
* Reconstruction method documentation is present as not applicable per eligible output row.

ID audit:

* Authoritative ID field: sample_id.
* ID resolution rule: use sample_id as authoritative when present; use candidate_id only if sample_id is absent; mark rows ambiguous if neither stable identifier exists; reject duplicates when sample_id already appears in the existing 21 or when sample_id + timestamp + direction + source + confidence repeats.
* Ambiguous ID-resolution count: 0.

## Source Policy Findings

Source A - existing unprocessed Adelin v2 artifacts:

Some existing artifacts contain useful sample metadata, but no additional confidence-3 / EXISTING_METADATA samples were found. Exact-source artifacts only reproduced the existing 21 confidence-3 samples or contained non-primary direction-source rows.

Source B - forward/new collection:

No forward/new collection artifact currently provides at least 39 additional confidence-3 / EXISTING_METADATA samples under the approved source rules.

Source C - broader historical OHLC mining:

Not used and not approved by this audit.

## Direction Source Findings

Missing direction_source was rejected rather than interpreted as EXISTING_METADATA.

The largest rejected artifacts had direction_guess or direction_confidence fields, but lacked exact direction_source. Under the approved plan, this is not enough for primary eligibility. This is especially important for expanded candidate and objective replay artifacts, where treating missing direction_source as EXISTING_METADATA would silently weaken the confidence-stratified design.

## Decision

Decision:

INSUFFICIENT_CONFIDENCE_3_SOURCE_AVAILABILITY

Rationale:

Only 21 confidence-3 / EXISTING_METADATA samples are available under the approved rules. The plan requires at least 60 total confidence-3 samples, so at least 39 additional samples are still missing.

This is not SOURCE_AVAILABILITY_PASS. It is not SOURCE_LINEAGE_AMBIGUOUS_FAIL_CLOSED, TIMESTAMP_RECONSTRUCTION_AMBIGUOUS_FAIL_CLOSED, or ID_RESOLUTION_AMBIGUOUS_FAIL_CLOSED, because no additional sample set passed far enough to create those failure modes.

## Safety

This audit did not:

* Read OHLC.
* Compute H3/H4 proxies.
* Execute proxy diagnostics.
* Run replay.
* Run backtest.
* Run matched-control.
* Run Phase 4.
* Modify runtime logic.
* Modify Strategy 2.
* Modify Strategy 3.
* Modify `data/XAUUSD/*.csv`.
* Enable live trading.
* Place orders.
* Send Telegram alerts.
* Call broker execution.
* Call or introduce order_send.
* Claim edge, profitability, or deployability.

## Next Step

The approved larger confidence-stratified H3/H4 proxy diagnostic cannot execute yet under the current sample gate. The next valid step is either:

* create a pre-registered forward/new collection plan for confidence-3 / EXISTING_METADATA Adelin v2 samples, or
* create a separate methodology proposal for how to add explicit direction_source metadata to existing unprocessed artifacts without reading OHLC or inferring from outcomes.
