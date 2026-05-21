# Adelin v2 Gated Roadmap

Old Adelin is archived as non-deployable. Adelin v2 continues through a gated
research roadmap, not through runtime patching or intuition-driven rescue.

Every phase requires an entry gate, an output deliverable, an exit gate, and
explicit forbidden actions. No phase may jump into execution before gates are
met. Strategy 3 continues separately in its own worktree, and Strategy 2
continues separately through manual benchmark labels. Neither may be touched
by Adelin v2 roadmap work.

## Global principles

1. Old Adelin is not patched.
2. Adelin v2 must be measurable, deterministic, pre-entry, reproducible, no
   future data, and OOS-testable.
3. Continuation must not be used as a positive feature.
4. `HEURISTIC_ONLY` concepts cannot drive entries unless converted into
   measurable proxies in a future methodology branch.
5. No blind feature mining.
6. No candidate pack before a pre-registered plan.
7. No backtest before feature definitions and gates are locked.
8. No live trading, no Telegram trade alerts, no broker/order execution.
9. No copy-pasting Strategy 3 into Adelin.
10. No saving Adelin for ego; only evidence can advance it.

## Phase 0 - Archive old Adelin

Status:
Complete / maintained.

Entry gate:
- Existing historical evidence shows old Adelin is non-deployable.
- Old score is not predictive.
- Continuation-positive behavior is toxic.
- Rejection subset is not robust OOS.

Output deliverable:
- Old score retained only as historical reference.
- Telemetry retained.
- Safety flags retained.
- Diagnostic reports retained.
- Verdict: `ADELIN_OLD_ARCHIVED_AS_NON_DEPLOYABLE`.

Exit gate:
- Old Adelin is not used for deployment decisions.
- No future branch attempts to patch old score directly.

Forbidden in this phase:
- Raise `min_score`.
- Patch continuation by intuition.
- Run new backtests to search for magic subsets.
- Build Contextual Reaction Engine immediately.
- Claim rejection works from full-sample improvement alone.

Notes:
Old Adelin evidence is a safety constraint, not a tuning target.

## Phase 1 - Contextual measurability audit

Status:
Complete.

Branch:
`feat/adelin-v2-contextual-measurability-audit`

Commit:
`1123ea3 Add Adelin v2 contextual measurability audit`

Entry gate:
- Old Adelin archived.
- No live/deployment decision.

Output deliverable:
- Concept matrix CSV/JSON.
- Classification of concepts into:
  - `MEASURABLE_NOW`
  - `MEASURABLE_WITH_NEW_DATA`
  - `HEURISTIC_ONLY`
  - `DISCRETIONARY_ONLY`
  - `NOT_RELIABLY_MEASURABLE`

Known result:
- 29 concepts audited.
- 10 `MEASURABLE_NOW`.
- 2 `MEASURABLE_WITH_NEW_DATA`.
- 14 `HEURISTIC_ONLY`.
- 0 `DISCRETIONARY_ONLY`.
- 3 `NOT_RELIABLY_MEASURABLE`.

Exit gate:
- Kimi/reviewer PASS recorded.
- `HEURISTIC_ONLY` risk acknowledged.
- Continuation-positive banned.
- No backtest run.
- No runtime logic modified.

Forbidden in this phase:
- Run backtest.
- Generate candidates.
- Treat visual review as evidence.
- Use continuation as a positive feature.
- Modify Adelin runtime logic.

Notes:
The main warning is that 14 of 29 concepts are `HEURISTIC_ONLY`. They cannot
drive decisions until a future branch converts them into deterministic,
pre-entry, testable proxies.

## Phase 2 - Pre-registered context feature test plan

Status:
Next planned phase.

Entry gate:
- Phase 1 audit complete with PASS.
- v3 candidate-count open question documented.
- Only `MEASURABLE_NOW` concepts are allowed as primary test candidates.

Output deliverable:
- For each of the 10 `MEASURABLE_NOW` concepts:
  - `feature_name`
  - hypothesis
  - deterministic formula
  - required timeframes
  - required data
  - leakage risk
  - subjectivity risk
  - sample size requirement
  - temporal split
  - expected signal direction
  - PASS criteria
  - FAIL criteria
  - kill criteria
  - anti-leakage rules
- Document only.
- No empirical results.

Exit gate:
- All selected feature tests have complete specs.
- Human review/sign-off recorded.
- Required sample size for Phase 3 labels estimated.
- Execution remains locked.

Forbidden in this phase:
- Generate candidate pack.
- Run backtest.
- Run matched control.
- Modify detector modules.
- Call detector functions.
- Call strategy functions.
- Read OHLC data beyond optional shape/column inspection.
- Produce empirical results.

Notes:
This phase exists to prevent scope creep into execution.

## Phase 3 - Visual review labels

Status:
Future / human work.

Entry gate:
- Phase 2 plan completed and signed off.
- Label schema exists.
- Features to observe are pre-declared.

Output deliverable:
- Manual labels CSV filled from:
  `backtests/reports/adelin_v2_visual_review_pack/manual_labels_template.csv`
- Review index:
  `backtests/reports/adelin_v2_visual_review_pack/index.html`
- Labels include:
  - quality `A+` / `A` / `B` / `C` / `INVALID`
  - `TAKE` / `SKIP` / `UNCERTAIN`
  - reason
  - visible feature
  - doubtful feature
  - visual outcome: reaction / runner / dead reaction / chop

Exit gate:
- Minimum label count reached.
- Mixed examples included: good, bad, invalid, uncertain.
- Labels reviewed for consistency.
- No labels used as proof of profitability.

Forbidden in this phase:
- Treat visual review as statistical evidence.
- Tune detectors from charts.
- Select only beautiful examples.
- Run backtest.
- Generate candidate pack.

Notes:
Visual review can describe context, but it cannot validate edge.

## Phase 4 - Matched control replay

Status:
Future.

Entry gate:
- Phase 2 feature test plan signed off.
- Phase 3 labels reviewed.
- Candidate/control definitions frozen before execution.

Output deliverable:
- Candidate windows vs matched control windows.
- Controls matched by:
  - session
  - volatility bucket
  - time-of-day
  - source type where possible
  - comparable context
- Metrics:
  - `fast_reaction_rate`
  - `runner_rate`
  - `fast_sl20_rate`
  - `mfe_20m`
  - `mae_20m`
  - `time_to_reaction`
  - `session_bucket`
  - `volatility_bucket`
  - `source_type`

Exit gate:
- Candidate outperforms control.
- N sufficient.
- `fast_sl20` does not worsen.
- No single regime/session bucket collapse.
- Verdict says continue / stop / inconclusive.

Forbidden in this phase:
- Compare only cherry-picked candidates.
- Change definitions after seeing results.
- Use post-entry information in candidate selection.
- Treat weak N as validation.
- Make deployment decision.

Notes:
Matched controls are descriptive diagnostics, not live-readiness evidence.

## Phase 5 - Expanded candidate pack

Status:
Future, only if Phase 4 is promising.

Entry gate:
- Phase 4 shows a visible effect worth expanding.
- Source-level effect is pre-declared.
- No critical leakage found.

Output deliverable:
- Expanded candidate/control report with:
  - broad historical coverage
  - max 5 samples per day
  - wide spacing, target 240 minutes
  - samples per month distribution
  - volatility bucket distribution
  - session distribution
  - candidate vs control metrics

Exit gate:
- CONTINUE only if:
  - source with N >= 80 has `fast_reaction >= control + 7pp`
  - OR `runner_rate >= control + 5pp`
  - AND `fast_sl20` does not worsen
- STOP if:
  - all sources with N >= 80 show useful differences < 3pp
  - OR candidate `fast_sl20 >= control fast_sl20`
- Only one repeat allowed if effect appears promising but N is too small.

Forbidden in this phase:
- Infinite loop of "one more pack".
- Change thresholds after seeing results.
- Ignore correlated same-day samples.
- Overweight one session/month/regime.

Notes:
Expansion is allowed only after locked criteria justify it.

## Phase 6 - Feature set candidate

Status:
Future, only if Phase 5 passes.

Entry gate:
- Phase 4/5 passed with adequate evidence.
- Feature list frozen.
- Max feature count agreed.

Output deliverable:
- A non-trading deterministic candidate-signal rule.
- Maximum 3-5 features.
- Example structure:

```text
IF HTF liquidity context valid
AND sweep/reaction metric valid
AND displacement/reclaim quality valid
AND session/regime not banned
THEN candidate_signal
ELSE no_signal
```

Exit gate:
- Rule is deterministic.
- Rule has no future data.
- Rule is simple enough to test.
- Rule is not optimized to historical quirks.

Forbidden in this phase:
- More than 5 initial features.
- Weighted score without evidence.
- ML/AI deciding entries.
- Live trading.
- Telegram trade alerts.
- Broker/order execution.

Notes:
The output is still not a trading strategy.

## Phase 7 - Lightweight backtest

Status:
Future, only after pre-registered feature set.

Entry gate:
- Phase 6 feature set frozen.
- Backtest windows and metrics pre-registered.
- No parameter tuning allowed during run.

Output deliverable:
- Smoke run 3-5 days.
- Limited run 15-20 days.
- One-month validation.
- Separate OOS validation if previous gates pass.

Exit gate:
- Sample at least 50-100 for weak diagnostic.
- PF > 1.15.
- AvgR > 0.10.
- MaxDD controlled.
- OOS does not collapse.
- No single regime bucket disaster.

Forbidden in this phase:
- Full 3-month run first.
- Tune after seeing smoke.
- Multi-symbol.
- Multi-strategy.
- Live.
- Telegram trade alerts.
- Broker/order execution.

Notes:
This is the first phase where a backtest may be discussed, and only after
feature definitions are frozen.

## Phase 8 - Adelin paper scanner

Status:
Future, only if lightweight backtest passes.

Entry gate:
- Phase 7 passes.
- Runtime signal contract defined.
- Safety controls defined.

Output deliverable:
- Paper-only scanner.
- No Telegram trade alerts.
- No orders.
- No broker.
- Signal contract.
- Data context hash.
- Paper signal logs.
- Scanner summary.

Exit gate:
- Paper scanner runs safely.
- Signals are logged.
- No live path is reachable.
- Output is ready for runtime/backtest comparison.

Forbidden in this phase:
- Live trading.
- Telegram trade alerts.
- Broker/order execution.
- Spread/slippage claims.
- Strategy tuning.

Notes:
This is paper observation only, not deployment.

## Phase 9 - Runtime/backtest match

Status:
Future, only after paper scanner.

Entry gate:
- Phase 8 paper scanner stable.
- Enough paper signals accumulated.
- Backtest comparison window locked.

Output deliverable:
- Runtime vs backtest comparison.
- Timestamp match.
- Direction match.
- Entry/SL/TP match.
- Context hash match.
- Cooldown/state match if applicable.

Exit gate:
- Strict match rate threshold met.
- Mismatches explained.
- No hidden runtime divergence.
- If mismatch is critical, return to diagnostics instead of proceeding.

Forbidden in this phase:
- Ignore mismatches.
- Proceed to live with unverified runtime/backtest divergence.
- Change logic to fit paper logs after seeing mismatch.

Notes:
Runtime/backtest mismatch is a stop condition, not a nuisance.

## Phase 10 - Eventual micro-live

Status:
Very future / locked.

Entry gate:
- Feature pre-registered.
- Backtest positive.
- OOS positive.
- Paper scanner stable.
- Runtime/backtest match high.
- Spread/slippage modeled.
- Drawdown acceptable.
- Human approval.

Output deliverable:
- If ever reached, a separate micro-live plan.
- Risk limits.
- Kill switch.
- No scale-up assumptions.

Exit gate:
- Not applicable in this documentation branch.

Forbidden in this phase:
- Start from current Adelin state.
- Skip paper scanner.
- Skip runtime/backtest match.
- Skip spread/slippage.
- Use Telegram trade alerts before explicit approval.
- Place broker orders before explicit approval.

Notes:
This phase is locked and cannot be reached from the current state.
