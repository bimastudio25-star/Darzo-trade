# Adelin v2 Contextual Measurability Audit

Status: research-only audit. This document is not a backtest, not a rewrite,
not a deployment decision, and not evidence that Adelin is revived.

## Verdict flags

- ADELIN_REMAINS_RESEARCH_ONLY
- NO_LIVE_DEPLOYMENT_DECISION
- NO_BACKTEST_RUN
- NO_RUNTIME_LOGIC_CHANGE
- CONTINUATION_POSITIVE_FEATURE_BANNED
- CONTEXTUAL_MEASURABILITY_AUDIT_COMPLETE

## Why Adelin remains research-only

Adelin / Strategy 1 is not an active trading candidate. The current known
historical evidence is weak: roughly 1007 baseline trades, about 27.71% win
rate, profit factor around 0.7665, negative AvgR, and max drawdown around
172R. These figures do not support deployment, and this audit does not try to
repair or optimize them.

The correct next research question is narrower: which contextual ideas can be
measured deterministically before entry without leaking future information?

## Why the current score failed

The old Adelin score is not trusted because the score distribution was too
narrow and not predictive. A score that cannot separate materially different
trade quality cannot be used as proof that a setup is valid. It also cannot be
used to dismiss the intended discretionary Adelin idea, because the old
implementation may have been misaligned with that idea.

This audit therefore treats the old score as a failed feature, not as a
foundation for optimization.

## Continuation rule

Continuation behavior remains banned as a positive feature. The old
continuation behavior was toxic, and using continuation as a positive signal
would invite strategy drift and selection bias. If continuation is studied at
all, it must be reframed only as a negative/risk/no-trade context.

## Concept matrix summary

The concept matrix was written to:

- `backtests/reports/adelin_v2_contextual_measurability_audit/concept_matrix.csv`
- `backtests/reports/adelin_v2_contextual_measurability_audit/concept_matrix.json`

Summary:

- MEASURABLE_NOW: 10
- MEASURABLE_WITH_NEW_DATA: 2
- HEURISTIC_ONLY: 14
- DISCRETIONARY_ONLY: 0
- NOT_RELIABLY_MEASURABLE: 3

The zero count for `DISCRETIONARY_ONLY` is intentional: each audited concept
can either be proxied, measured now, measured with new data, or rejected as
not reliably pre-entry measurable. The audit does not claim those proxies are
good enough for trading.

## Measurable now

These concepts can be converted into deterministic pre-entry metrics with
available candle/timestamp data:

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

These are measurable, but not automatically useful. Every future test must
pre-register definitions, thresholds, timeframes, and source hierarchy before
outcome replay.

## Measurable with new data

These concepts need stronger data quality before they can be treated as
reliable metrics:

- volume profile
- volume cracks

The core missing issue is volume quality. Broker tick volume can be useful for
some diagnostics, but it is not the same as centralized real volume. Any
future volume-profile or volume-crack test must explicitly document the data
source and run broker/data sensitivity checks.

## Heuristic-only concepts

These can be approximated with deterministic proxies, but the proxy is not the
same as discretionary judgment:

- HTF liquidity
- LTF liquidity
- internal liquidity
- external liquidity
- M15 sequence validity
- reaction zones
- rejection quality
- reclaim quality
- accumulation before expansion
- compression before expansion
- multi-timeframe alignment
- candle close quality
- failed continuation
- trend/range regime

These concepts require strict anti-leakage controls because it is easy to
smuggle post-entry behavior into the definition. The correct use is hypothesis
generation, not immediate signal generation.

## Not reliably pre-entry measurable

These concepts are not valid pre-entry features in their ordinary form:

- immediate expansion
- runner expansion
- continuation behavior

Immediate expansion and runner expansion are outcome measurements, not
pre-entry evidence. Continuation behavior is banned as a positive feature and
may only be used as negative/risk context.

## Data needed for future validation

A future Adelin research test would need:

- clean OHLC data across D1/H4/H1/M15/M5/M1;
- explicit XAUUSD pip conversion rules;
- broker spread/slippage assumptions if execution is evaluated;
- timestamp/session normalization;
- optional reliable tick or real volume for volume profile and volume cracks;
- pre-registered derived feature definitions;
- source/session/regime stratification;
- OOS validation split.

Visual review can help describe examples, but visual review is not evidence
of edge and must not be treated as validation.

## Anti-leakage rules

Any future Adelin test must obey:

- use only pre-anchor data for candidate features;
- do not use post-entry MFE, MAE, runner movement, expansion, or reaction as
  entry features;
- compute swing, FVG, IFVG, volume, and session labels strictly from data
  available before the anchor;
- pre-register feature thresholds before replay;
- keep continuation-positive bias banned;
- use temporal split and OOS validation;
- report by source, session, and volatility regime;
- do not use live trading, Telegram trade alerts, broker execution, or order
  execution in research branches.

## Kill criteria before any future Adelin backtest

Before any future Adelin backtest is allowed, the research plan must satisfy:

- pre-registered features;
- temporal split;
- no continuation-positive bias;
- no post-entry features;
- sample-size gates;
- OOS validation;
- no live trading;
- no Telegram trade alerts;
- no broker execution.

Suggested gates to document before a future test:

- `n >= 100` for a weak diagnostic;
- `n >= 300` for serious validation;
- OOS PF > 1.15;
- AvgR > 0.10;
- max drawdown controlled;
- no single regime bucket collapse.

If these gates cannot be defined before testing, the correct action is to
pause the research, not to backtest and reinterpret results after the fact.

## Explicit non-actions

No Adelin backtest was run.

No Adelin runtime logic was modified.

No Strategy 2 logic was modified.

No Strategy 3 logic or paper/live collector was modified.

No data files under `data/XAUUSD/*.csv` were modified.

No deployment decision was made.
