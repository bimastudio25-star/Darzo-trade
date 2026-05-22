# Adelin v2 Manual Screenshot Concept Audit

## Context

Manual screenshots from Nicolas/academy and Adelin suggest discretionary concepts that are not fully covered by current Adelin v2 features. These screenshots are qualitative reference material only. They were not auto-labeled, analyzed by computer vision, or used as validation data.

Adelin v2 remains research-only. Phase 4 matched-control replay remains blocked.

## Purpose

This audit translates human-visible screenshot concepts into a measurable research taxonomy:

- concepts that are already measurable;
- concepts that could be measured with existing OHLC-derived proxies;
- concepts that need new data, such as volume profile or tick/real volume;
- concepts that remain heuristic-only;
- gaps in current Adelin v2 feature coverage.

## Non-Purpose

This branch does not analyze screenshots, infer trade quality, validate Adelin v2, run replay, run backtest, run matched-control, create scoring, create live filters, or modify runtime logic.

No OHLC data was read.

## Concept Taxonomy

| Concept | Coverage | Measurability | Priority | Note |
|---|---|---|---|---|
| `PRE_DECISION_SWEEP_HIGH_LOW` | PARTIAL | MEASURABLE_NOW | HIGH | Related to direction governance, but not a standalone feature. |
| `FAST_M1_REACTION_AFTER_SWEEP` | PARTIAL | MEASURABLE_WITH_EXISTING_OHLC_PROXY | HIGH | Must stay pre-decision if used as context; post-entry reaction is diagnostic only. |
| `TIGHT_SL_BEHIND_SPIKE_OR_SWING` | MISSING | MEASURABLE_WITH_EXISTING_OHLC_PROXY | HIGH | Needs frozen invalidation-distance proxy. |
| `SWING_HIGH_LOW_ZONE_PROXIMITY` | PARTIAL | MEASURABLE_WITH_EXISTING_OHLC_PROXY | HIGH | Needs zone-width definition. |
| `HTF_LTF_LEVEL_CONFLUENCE` | PARTIAL | MEASURABLE_WITH_EXISTING_OHLC_PROXY | HIGH | Current HTF liquidity proxy is not full HTF/LTF confluence. |
| `VOLUME_PROFILE_ZONE_PROXIMITY` | MISSING | MEASURABLE_WITH_NEW_DATA | HIGH | Requires volume-profile data/methodology. |
| `PRICE_INSIDE_REACTION_ZONE` | PARTIAL | MEASURABLE_WITH_EXISTING_OHLC_PROXY | HIGH | Current FVG/iFVG proximity does not fully capture zone boundaries. |
| `CLEAN_TARGET_SPACE_TO_NEXT_ZONE` | PARTIAL | MEASURABLE_WITH_EXISTING_OHLC_PROXY | MEDIUM | Must avoid future target outcome. |
| `DIRTY_REACTION_CHOP_AFTER_ENTRY` | PARTIAL | HEURISTIC_ONLY | LOW | Diagnostic/outcome concept only; not a clean pre-entry feature. |
| `ZONE_RETEST_OR_RECLAIM` | MISSING | MEASURABLE_WITH_EXISTING_OHLC_PROXY | HIGH | Needs frozen zone and reclaim semantics. |
| `ROUND_OR_NUMERIC_LEVEL_CONFLUENCE` | COVERED | MEASURABLE_NOW | MEDIUM | Covered by numeric-level governance; 005 remains stratification-only. |
| `SESSION_CONTEXT_ASIA_TO_NY_WINDOW` | COVERED | MEASURABLE_NOW | LOW | Covered as timestamp/session context. |

## Measurability Classification

- `MEASURABLE_NOW`: 3 concepts
- `MEASURABLE_WITH_EXISTING_OHLC_PROXY`: 7 concepts
- `MEASURABLE_WITH_NEW_DATA`: 1 concept
- `HEURISTIC_ONLY`: 1 concept
- `NOT_RELIABLY_MEASURABLE`: 0 concepts

`VOLUME_PROFILE_ZONE_PROXIMITY` is not marked measurable now because this audit did not verify suitable volume-profile data, binning, or indicator support.

`DIRTY_REACTION_CHOP_AFTER_ENTRY` is not an entry feature. It remains diagnostic/outcome-side unless a separate future branch reframes it as a pre-entry risk proxy.

## Current Feature Coverage Map

Covered or mostly covered:

- `ROUND_OR_NUMERIC_LEVEL_CONFLUENCE` maps to numeric level confluence and `tight_numeric_level_touch_band` stratification.
- `SESSION_CONTEXT_ASIA_TO_NY_WINDOW` maps to session/hour context.

Partially covered:

- `PRE_DECISION_SWEEP_HIGH_LOW` maps to direction recovery and H1 sweep concepts, but is not standalone.
- `FAST_M1_REACTION_AFTER_SWEEP` maps to fast-reaction diagnostics and M1 candle anatomy, but leakage boundaries are critical.
- `SWING_HIGH_LOW_ZONE_PROXIMITY` and `HTF_LTF_LEVEL_CONFLUENCE` partly map to `liquidity_htf_recent_level`.
- `PRICE_INSIDE_REACTION_ZONE` partly maps to `fvg_ifvg_near_20p`.
- `CLEAN_TARGET_SPACE_TO_NEXT_ZONE` partly maps to target-space proxy if available.
- `DIRTY_REACTION_CHOP_AFTER_ENTRY` maps only to diagnostic tags.

Missing:

- `TIGHT_SL_BEHIND_SPIKE_OR_SWING`
- `VOLUME_PROFILE_ZONE_PROXIMITY`
- `ZONE_RETEST_OR_RECLAIM`

## Missing Feature Candidates

High-priority missing or partial-coverage candidates:

- `PRE_DECISION_SWEEP_HIGH_LOW`
- `FAST_M1_REACTION_AFTER_SWEEP`
- `TIGHT_SL_BEHIND_SPIKE_OR_SWING`
- `SWING_HIGH_LOW_ZONE_PROXIMITY`
- `HTF_LTF_LEVEL_CONFLUENCE`
- `VOLUME_PROFILE_ZONE_PROXIMITY`
- `PRICE_INSIDE_REACTION_ZONE`
- `ZONE_RETEST_OR_RECLAIM`

These are candidates for future methodology/planning only. They are not runtime features and not evidence of edge.

## Data Requirements

OHLC-only candidates:

- pre-decision sweep high/low;
- fast M1 reaction if bounded to pre-decision context;
- tight SL behind spike/swing;
- swing high/low zone proximity;
- HTF/LTF level confluence;
- price inside OHLC-defined reaction zones;
- clean target space to next OHLC-defined zone;
- zone retest or reclaim;
- numeric level and session context.

New data or indicator candidates:

- volume profile zone proximity, requiring a frozen profile method and tick/volume data support.

Heuristic-only or diagnostic-only:

- dirty reaction/chop after entry.

## Future Use

Future branches may use this audit to create pre-registered feature plans. Any such branch must:

- freeze definitions before empirical execution;
- separate pre-entry context from post-entry outcome;
- document required data and leakage risk;
- avoid scoring, live filters, and threshold tuning;
- keep Phase 4 blocked until a separate methodology gate is approved.

## Safety

- No screenshots were auto-labeled.
- Screenshots were not used as validation.
- No OHLC data was read.
- No replay, backtest, or matched-control was run.
- No runtime logic was modified.
- Strategy 2 was untouched.
- Strategy 3 was untouched.
- Phase 4 remains blocked.
- No live trading was enabled.
- No orders were placed.
- No Telegram alerts were sent.
- No broker execution was called.
- The v3 stash was not applied or popped.
