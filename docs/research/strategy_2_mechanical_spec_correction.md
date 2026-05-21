# Strategy 2 Mechanical Spec Correction

Research-only diagnostic report. Fixed HH:45/x:45 M15 logic is superseded by three deterministic current-M15 models.

## Context

Previous Strategy 2 statistical recorder outputs used a fixed HH:45/x:45 M15 sequence filter. The user clarified that the relevant M15 is dynamic while price moves toward the H1 liquidity level, and that reaction/candle confirmation is not a mandatory entry gate. This report corrects that mechanical interpretation and compares the old x:45 result against three deterministic current-M15 approximations.

## Safety

- Strategy 3 untouched.
- data/XAUUSD/*.csv untouched.
- No live trading, Telegram, broker execution, orders, or runtime registration.

## Corrected Rules

- H1 context uses previous H1 and/or first-pass dominant H1 range detection.
- Dominant H1 requires full containment: internal high < outer high and internal low > outer low.
- A level take by 1 pip is enough.
- If both H1 high and low are taken in the same context, only the first side is considered; same-bar ambiguity is rejected.
- M15 models: containing, preceding, approach_window.
- Long is invalid when the relevant/current M15 high is taken before the H1 low.
- Short is invalid when the relevant/current M15 low is taken before the H1 high.
- Entry requires average MAE reached inside the same H1 candle as the level take, then range re-entry by 1 pip.
- Re-entry is a price touch, not a candle close.
- Reaction confirmation is ex-post metadata only and is not an entry gate.
- Conservative SL remains Max Excursion * 1.25.
- TP remains anchored to H1 liquidity level; standard TP1 fallback is deferred.

## M15 Model Definitions

- containing: M15 candle whose open time contains the H1 level-take timestamp.
- preceding: last M15 candle fully closed before the H1 level-take timestamp.
- approach_window: all M15 candles from H1 context open through the H1 level-take timestamp.

## Method

For each H1 context and selected H1 reference, the audit detects the first H1 high/low take using a 1-pip threshold, applies each M15 model, evaluates same-H1 MAE reach and same-H1 range re-entry, and records manipulation/expansion distributions. The old x:45 recorder output is loaded only for overlap comparison.

## Results

- H1 contexts analyzed: 934
- Old x45 valid count: 438

| M15 model | corrected samples | current-M15 valid | entry triggered | no-entry | overlap old | old valid/new invalid | old invalid/new valid | MAE avg | max excursion | conservative SL | <=8 | <=10 | <=12 | >12 | >20 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| approach_window | 260 | 270 | 134 | 126 | 235 | 203 | 25 | 13.1645 | 180.93 | 226.1625 | 136 | 162 | 170 | 90 | 49 |
| containing | 269 | 279 | 134 | 135 | 241 | 197 | 28 | 12.798 | 180.93 | 226.1625 | 145 | 171 | 179 | 90 | 49 |
| preceding | 469 | 484 | 252 | 217 | 292 | 146 | 177 | 14.2746 | 180.93 | 226.1625 | 222 | 269 | 292 | 177 | 104 |

## Verdict Flags

- MECHANICAL_SPEC_CORRECTION_COMPLETE
- FIXED_X45_M15_SUPERSEDED
- CURRENT_M15_MODELS_IMPLEMENTED
- M15_MODEL_COMPARISON_COMPLETE
- OLD_NEW_M15_COMPARISON_COMPLETE
- ENTRY_REQUIRES_MAE_AND_RANGE_REENTRY
- SAME_H1_ENTRY_WINDOW_DEFINED
- REACTION_CONFIRMATION_REMOVED_AS_GATE
- H1_DOMINANT_RULE_DOCUMENTED
- STANDARD_TP1_FALLBACK_DEFERRED
- STRATEGY_2_REMAINS_RESEARCH_ONLY
- NO_LIVE_DEPLOYMENT_DECISION

## Limitations

- The user must still choose which current-M15 interpretation best matches the intended mechanical idea.
- No manual labels are used.
- No profitability, deployment, or live-readiness conclusion is made.
- Dominant H1 handling is a deterministic first pass using full containment.
- The large Max Excursion / conservative SL values are reported honestly and are not clamped.

## Next Strategy 2-Only Step

- feat/strategy-2-m15-model-selection-review
