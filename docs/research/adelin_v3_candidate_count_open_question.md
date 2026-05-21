# Adelin v3 Candidate Count Drop Open Question

This is an unresolved open question, not evidence. Do not trust either the
31-candidate count or the 3-candidate count until root cause is diagnosed.

## Observed context

Branch where the issue was observed:
`feat/adelin-v3-composite-detector-foundation`

Audit branch completed before this documentation branch:
`feat/adelin-v2-contextual-measurability-audit`

Audit commit:
`1123ea3 Add Adelin v2 contextual measurability audit`

Dirty folder observed before the audit branch:
`backtests/reports/adelin_v3_composite_candidate_pack/*`

Observed change:

```text
generation_summary.json changed from:
31 candidates / READY_FOR_MATCHED_CONTROL_REPLAY

to:
3 candidates / INSUFFICIENT_SAMPLE
```

The dirty report changes were stashed before the audit and were not mixed into
the Adelin v2 contextual measurability audit branch.

## Stash record

Current stash list at documentation time:

```text
stash@{0}: On feat/adelin-v3-composite-detector-foundation: preexisting adelin v3 composite candidate pack report changes before contextual measurability audit
```

Matching stash reference at documentation time:
`stash@{0}`

Important: `stash@{0}` is not stable. Use the SHA and message below for a
durable record.

Matching stash SHA:
`91c61b47ccf3b2b820b583e29e3e438f14a38db2`

Matching stash message:
`preexisting adelin v3 composite candidate pack report changes before contextual measurability audit`

Stash stat summary:

```text
59 files changed, 3136 insertions(+), 3167 deletions(-)
```

Affected tracked report paths included:

- `backtests/reports/adelin_v3_composite_candidate_pack/README.md`
- `backtests/reports/adelin_v3_composite_candidate_pack/candidate_pack.csv`
- `backtests/reports/adelin_v3_composite_candidate_pack/generation_summary.json`
- `backtests/reports/adelin_v3_composite_candidate_pack/index.html`
- `backtests/reports/adelin_v3_composite_candidate_pack/rejection_breakdown.csv`
- `backtests/reports/adelin_v3_composite_candidate_pack/charts/v3_sample_*.svg`
- `backtests/reports/adelin_v3_composite_candidate_pack/examples/v3_sample_*.html`

The stash was not applied, popped, dropped, or cleared in this branch.

## Possible causes to investigate later

- Bug.
- Threshold tightening.
- Anti-lookahead/windowing change.
- Data-window change.
- Candidate filtering change.
- Report overwrite from partial run.
- Stale output artifact.
- Cache/report contamination.

## Rules for future investigation

- Do not trust either the 31 count or the 3 count until root cause is
  diagnosed.
- Do not resume v3 without a pre-registered plan.
- Do not apply, pop, or drop the stash in this branch.
- Do not run v3 candidate generation in this branch.
- Do not use this unresolved discrepancy as evidence for or against Adelin v3.

## Safety statement

No backtest was run.

No candidate pack was generated.

No matched-control replay was run.

No stash was applied or popped.

No runtime logic was modified.

Strategy 3 was untouched.

Strategy 2 was untouched.

`data/XAUUSD/*.csv` was untouched.

No live trading was enabled.

No orders were created or sent.

No Telegram trade alerts were sent.

No broker execution was called.
