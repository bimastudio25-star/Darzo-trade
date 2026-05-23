# Adelin v2 Tight SL and Zone Retest Proxy Plan

## Context

The Adelin v2 manual screenshot concept audit is complete. It audited 12 concepts: 3 measurable now, 7 measurable with existing OHLC proxies, 1 requiring new data, and 1 heuristic-only concept.

Volume profile is deferred because it requires a separate data feasibility and methodology study. This plan focuses on two high-leverage concepts that are missing or insufficiently covered:

- H3: `TIGHT_SL_BEHIND_SPIKE_OR_SWING`
- H4: `ZONE_RETEST_OR_RECLAIM`

Phase 4 remains blocked.

## Purpose

This branch pre-registers deterministic OHLC proxy formulas before any future execution. It defines what a later branch may compute, what inputs are allowed, what inputs are forbidden, and how leakage and threshold tuning must be prevented.

## Non-Purpose

This branch does not execute the proxies, read OHLC, collect samples, generate candidates, run replay, run backtest, run matched-control, modify runtime logic, create scoring, create live-entry filters, or validate Adelin v2.

## H3 Proxy Spec

Concept: `TIGHT_SL_BEHIND_SPIKE_OR_SWING`

Proxy name: `tight_sl_local_invalidation_proxy`

Human concept: a discretionary entry is more attractive when invalidation sits close behind a local spike, sweep extreme, or completed swing structure.

Formula plan:

- Use completed pre-decision M1 and M5 candles only.
- For LONG, find the nearest qualifying local low or sweep low below the candidate reference price.
- For SHORT, find the nearest qualifying local high or sweep high above the candidate reference price.
- Compute invalidation distance in USD and pips.
- Normalize invalidation distance by a fixed pre-decision local range proxy.

Future output fields:

- `tight_sl_band`
- `invalidation_distance_usd`
- `invalidation_distance_pips`
- `invalidation_distance_to_recent_range_ratio`
- `invalidation_source_timeframe`
- `invalidation_source_type`
- `proxy_computable`
- `proxy_limitations`

## H4 Proxy Spec

Concept: `ZONE_RETEST_OR_RECLAIM`

Proxy name: `pre_decision_zone_retest_reclaim_proxy`

Human concept: a discretionary entry may improve when price reclaims, retests, or holds a pre-defined zone or level before the decision.

Formula plan:

- Freeze zone boundaries before `decision_timestamp`.
- Candidate zones may come from numeric levels, completed swing zones, or completed FVG/iFVG zones.
- A retest occurs when a completed pre-decision M1/M5 candle touches the zone after first interaction and closes without invalidating the side implied by direction.
- A reclaim occurs when price moves through a zone boundary and a completed pre-decision candle closes back on the trade side of that boundary.

Future output fields:

- `zone_retest_reclaim_category`
- `zone_source`
- `zone_low`
- `zone_high`
- `zone_width_pips`
- `distance_to_zone_pips`
- `pre_decision_touch_count`
- `last_pre_decision_close_relation`
- `proxy_computable`
- `proxy_limitations`

## Allowed Inputs

Allowed future execution inputs:

- completed pre-decision OHLC candles only;
- `decision_timestamp`;
- candidate reference price;
- direction;
- source/session metadata for stratification;
- frozen numeric-level, swing-zone, and FVG/iFVG zone definitions.

No post-entry candle may be used to define H3 or H4.

## Forbidden Inputs

Forbidden:

- post-entry candles;
- TP hit;
- SL hit;
- PnL;
- R multiple;
- future MFE/MAE;
- outcome-derived thresholds;
- later swing levels created after decision;
- future liquidity behavior;
- manual cherry-picking;
- non-directional max move replay;
- GOOD/FAST outcome group for threshold selection.

## Threshold Policy

Thresholds must not be optimized from prior GOOD/FAST results.

Allowed policies:

- H3 uses pre-registered descriptive bands:
  - `TIGHT`: normalized distance `<= 1.0`
  - `MEDIUM`: normalized distance `> 1.0` and `<= 2.0`
  - `WIDE`: normalized distance `> 2.0`
- H3 also records `<=2.0 USD / <=20 pips` as a descriptive reference only.
- H4 uses categorical states:
  - `NO_ZONE_AVAILABLE`
  - `INSIDE_ZONE`
  - `RETEST_HELD`
  - `RECLAIM_CONFIRMED`
  - `RETEST_FAILED_PRE_DECISION`

Forbidden:

- choosing thresholds after observing GOOD/FAST separation;
- changing bands during execution;
- selecting the best-performing band as a final rule;
- tuning zone width after seeing outcomes.

## Leakage Guards

Any future execution branch must record:

- `pre_entry_only = true`
- `post_entry_data_used = false`
- `leakage_check_passed = true`

If either proxy requires post-entry information, it must be rejected as leakage.

## Future Execution Requirements

A separate future branch is required to execute this plan. That branch may only:

- load the signed proxy specs;
- compute H3/H4 on pre-decision OHLC only;
- write computability and leakage reports;
- produce descriptive diagnostic tables.

It must not run Phase 4, matched-control replay, live filters, scoring, threshold optimization, profitability claims, or runtime integration.

## Decision Matrix

- `PROXY_MEASURABLE_AND_STABLE`: allow bounded diagnostic execution only; no Phase 4.
- `PROXY_NOT_COMPUTABLE_RELIABLY`: reject or defer; no Phase 4.
- `POST_ENTRY_LEAKAGE_DETECTED`: reject as leakage; no Phase 4.
- `ARBITRARY_THRESHOLD_TUNING_REQUIRED`: reject or require new plan; no Phase 4.
- `HIGH_MANUAL_DISAGREEMENT`: keep research-only or redefine in a new plan; no Phase 4.

## Safety

- Plan-only.
- No OHLC read.
- No samples collected.
- No replay, backtest, or matched-control run.
- No runtime logic modified.
- Strategy 2 untouched.
- Strategy 3 untouched.
- No live trading.
- No orders.
- No Telegram alerts.
- No broker execution.
- No v3 stash apply/pop.
- Phase 4 remains blocked.
