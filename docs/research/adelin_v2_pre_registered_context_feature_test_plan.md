# Adelin v2 Pre-registered Context Feature Test Plan

Status: Phase 2 planning-only. This branch defines what may be tested later,
before empirical results are seen. It does not execute tests.

## Scope

This plan is documentation and structured specification only.

- No empirical results.
- No detector execution.
- No strategy function calls.
- No Adelin backtest.
- No candidate pack.
- No matched-control replay.
- No expanded candidate pack.
- No runtime logic changes.
- No live trading.
- No Telegram trade alerts.
- No broker/order execution.

The purpose is to freeze future test definitions before any Phase 3 or Phase
4 work begins.

## Inputs

Planning inputs read:

- `docs/research/adelin_v2_roadmap_gated.md`
- `docs/research/adelin_v3_candidate_count_open_question.md`
- `docs/research/adelin_v2_contextual_measurability_audit.md`
- `backtests/reports/adelin_v2_contextual_measurability_audit/concept_matrix.csv`
- `backtests/reports/adelin_v2_contextual_measurability_audit/concept_matrix.json`

No chart review was used as evidence. The visual review pack remains a future
Phase 3 labeling surface only.

The Adelin v3 candidate-count drop remains an unresolved open question. The
documented stash SHA is
`91c61b47ccf3b2b820b583e29e3e438f14a38db2`; it was not applied, popped, or
dropped in this branch.

## Eligible concepts

Only concepts classified as `MEASURABLE_NOW` in the contextual measurability
audit are eligible for primary future test specs:

- H1 liquidity sweep
- FVG
- IFVG
- number theory
- round levels
- wick/body behavior
- displacement
- time-of-day context
- session context
- volatility regime

These concepts are measurable, but not automatically useful. Their formulas
must remain locked before any future outcome replay or backtest.

## Excluded concepts

The following classifications are explicitly excluded from primary executable
future feature tests in this plan:

- `MEASURABLE_WITH_NEW_DATA`
- `HEURISTIC_ONLY`
- `DISCRETIONARY_ONLY`
- `NOT_RELIABLY_MEASURABLE`

These are not valid for primary tests without a future measurable-proxy
methodology branch. If an idea depends on a `HEURISTIC_ONLY` concept, it must
be marked `FUTURE_PROXY_REQUIRED` and cannot be included in executable future
test specs.

Continuation remains banned as a positive feature. Exact forbidden
interpretation:

```text
Continuation is not evidence of trade quality and must not be used as a positive entry reason.
```

## Feature test specs

Structured specs were created here:

- `backtests/reports/adelin_v2_pre_registered_context_feature_test_plan/feature_test_specs.csv`
- `backtests/reports/adelin_v2_pre_registered_context_feature_test_plan/feature_test_specs.json`
- `backtests/reports/adelin_v2_pre_registered_context_feature_test_plan/summary.json`

Spec count: 10.

Every spec includes:

- `source_classification = MEASURABLE_NOW`
- `execution_locked = true`
- deterministic formula
- pre-entry availability
- leakage and subjectivity risk
- candidate/control definitions
- sample-size gates
- temporal split and OOS rule
- PASS / FAIL / KILL criteria
- anti-leakage rules
- required human signoff

No spec uses continuation as a positive feature.

## Future test families

These families are defined for later branches only. None are executed here.

### 1. Candidate vs matched-control reaction test

What it measures:
Whether a locked pre-entry feature improves immediate reaction quality versus
matched controls.

Data required:
Completed OHLC candles and timestamps for the locked timeframes of the
feature, plus future replay data only after candidate/control definitions are
frozen.

Controls:
Match by session, volatility bucket, time-of-day, month or temporal block,
source/context class where possible, and avoid same-window contamination.

PASS:
Candidate `fast_reaction_rate` improves by the pre-registered threshold and
`fast_sl20_rate` does not worsen.

FAIL:
Candidate and control rates are flat within the pre-registered tolerance.

KILL:
The effect appears only after changing definitions, chart picking, or using
post-entry information.

### 2. Runner quality test

What it measures:
Whether a locked feature improves runner behavior without relying on long
unbounded forward windows.

Data required:
Locked candidate/control windows plus capped forward replay metrics.

Controls:
Same matching requirements as the reaction test, with source/context class
matched when possible.

PASS:
Candidate `runner_rate` improves by the pre-registered threshold and does not
come with worse fast-failure risk.

FAIL:
Runner rate is similar to matched controls.

KILL:
Runner quality depends on extending replay windows after seeing results.

### 3. Fast-failure risk test

What it measures:
Whether the feature reduces fast adverse movement such as `FAST_SL_20`.

Data required:
Locked candidate/control definitions and forward replay for SL-hit timing.

Controls:
Match by session, volatility bucket, time-of-day, month or temporal block,
and source/context class where possible.

PASS:
Candidate `fast_sl20_rate <= control fast_sl20_rate - 0.10` while
`fast_reaction_rate` is not worse by more than 0.03.

FAIL:
Fast failure is unchanged or only improves in one narrow bucket.

KILL:
Fast failure worsens, or the improvement requires continuation-positive
interpretation.

### 4. Regime stability test

What it measures:
Whether the feature effect survives across session, time-of-day, volatility,
month, and trend/range context if available.

Data required:
Pre-entry regime tags and candidate/control replay outputs.

Controls:
Controls must be matched or stratified by the regime bucket being tested.

PASS:
The effect remains directionally consistent across major buckets and no major
bucket shows a fast-failure disaster.

FAIL:
The effect is concentrated in one bucket without enough support elsewhere.

KILL:
Any useful-looking result collapses when session or volatility matching is
applied.

### 5. OOS stability test

What it measures:
Whether the locked feature survives a temporal out-of-sample segment.

Data required:
The same locked candidate/control definitions on a pre-registered temporal
split.

Controls:
Controls in OOS must use the same matching rules as the in-sample diagnostic.

PASS:
OOS retains the pre-registered directional effect with sufficient N.

FAIL:
OOS becomes flat or underpowered.

KILL:
OOS collapses, or the formula is changed after observing OOS results.

## Anti-leakage rules

All future tests must obey:

- No post-entry data in candidate definition.
- No future candle outcome in feature computation.
- No changing formula after seeing outcome.
- No same-window contamination between candidate/control.
- No lookahead from HTF candles not closed.
- No chart-based cherry picking.
- No continuation-positive bias.
- No visual review label may be treated as proof of profitability.

## Candidate vs control rules

Controls should match where possible:

- session
- volatility bucket
- time-of-day
- month or temporal block
- source/context class
- trend/range regime if available

Unmatched controls may be used only for debug diagnostics and must not support
a PASS decision.

## Sample-size gates

- `n >= 100` is the minimum weak diagnostic gate.
- `n >= 300` is the minimum serious validation gate.
- Lower N may only be `INCONCLUSIVE`, never PASS.

If a future feature cannot reach the weak diagnostic gate, it should not be
rescued by loosening definitions after seeing data.

## Kill criteria

Stop or archive the feature path if any of the following occurs:

- No feature shows candidate-control improvement >= the pre-registered
  threshold.
- Fast failure worsens.
- Effect exists only in one regime/session/month.
- OOS collapses.
- Metric depends on continuation-positive interpretation.
- Formula requires unavailable future data.
- Human signoff is not provided.

## Human gate

No future execution branch may start until
`docs/research/adelin_v2_feature_test_human_signoff_template.md` is completed.

The signoff must confirm:

- only `MEASURABLE_NOW` concepts are used;
- `HEURISTIC_ONLY` concepts are excluded or marked `FUTURE_PROXY_REQUIRED`;
- no empirical results were generated in planning;
- each feature is deterministic and pre-entry;
- anti-leakage rules, PASS/FAIL/KILL criteria, and sample-size gates are
  accepted;
- continuation is not used as a positive feature;
- execution remains locked.

## Next phase

Phase 3 - Visual review labels.

Do not start candidate generation or matched-control replay until:

- the human signoff template is completed;
- this feature test plan is reviewed;
- the label schema is confirmed.

## Safety statement

No backtest was run.

No candidate pack was generated.

No matched-control replay was run.

No detector was executed.

No strategy function was called.

No runtime logic was modified.

Strategy 3 was untouched.

Strategy 2 was untouched.

`data/XAUUSD/*.csv` was untouched.

No OHLC data was read.

No live trading was enabled.

No orders were created or sent.

No Telegram trade alerts were sent.

No broker execution was called.
