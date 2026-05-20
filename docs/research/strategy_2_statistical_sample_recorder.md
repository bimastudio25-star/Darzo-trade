# Strategy 2 Statistical Sample Recorder

## Context

Previous Strategy 2 diagnostics showed the current implementation was misaligned with the written Liquidity Expansion Model. A naive global Max Excursion profile produced unrealistic 200+ USD stops, which is not the intended workflow.

This branch rebuilds the statistical sample collection process only. It does not deploy a strategy and does not change runtime behavior.

## Corrected Interpretation

- M15 x:45 means the candle whose open minute is 45 inside each H1 hour, not one fixed daily 00:45 candle.
- A valid sample is an H1 context that manipulates beyond the H1 liquidity level and then distributes in the opposite direction.
- Valid no-entry samples still count toward MAE if manipulation was smaller than the current average MAE.
- MAE is the average manipulation depth among valid samples.
- Risky SL is max manipulation among valid samples.
- Conservative SL is max manipulation * 1.25.
- TPs are quartiles of expansion projected from the H1 liquidity level, not from entry.
- BE after TP1 remains a model rule, but this recorder does not simulate live management.

## Safety

- Strategy 3 untouched.
- data/XAUUSD/*.csv untouched.
- No live trading.
- No Telegram.
- No broker execution.
- No order_send.
- No orders.
- Research-only.

## Method

- Evaluate previous H1 and deterministic dominant H1 references.
- Select the M15 x:45 candle by timestamp minute == 45 inside each H1 hour.
- Invalidate LONG if M15 x:45 high is taken before the H1 low sweep.
- Invalidate SHORT if M15 x:45 low is taken before the H1 high sweep.
- Measure manipulation depth from the H1 liquidity level before distribution.
- Include valid no-entry samples in the MAE dataset.
- Measure expansion from the H1 liquidity level after sweep.
- Produce quartile TP and R:R diagnostics without optimization.

## Results



- H1 contexts analyzed: `3401`
- valid samples: `438`
- valid triggered samples: `116`
- valid no-entry samples: `322`
- M15 x:45 valid/invalid: `629` / `2437`

## Invalid Samples

```json
{
  "INVALID_INSUFFICIENT_DATA": 335,
  "INVALID_MOVE_ALREADY_CONSUMED": 11,
  "INVALID_NO_CLEAR_MANIPULATION": 20,
  "INVALID_NO_DISTRIBUTION": 160,
  "INVALID_OPPOSITE_M15_X45_TAKEN_FIRST": 2437
}
```

## MAE Profile

```json
{
  "average_pips": 46.471,
  "average_price": 4.6471,
  "average_usd": 4.6471,
  "count": 438,
  "max_pips": 628.0,
  "max_price": 62.8,
  "max_usd": 62.8,
  "median_pips": 18.55,
  "median_price": 1.855,
  "median_usd": 1.855,
  "p25_price": 0.73,
  "p50_price": 1.855,
  "p75_price": 4.83,
  "p80_price": 6.082,
  "p85_price": 8.2435,
  "p90_price": 11.851,
  "p95_price": 19.602
}
```

## Max Excursion / SL Profile

```json
{
  "conservative_stop_distance_pips": 785.0,
  "conservative_stop_distance_price": 78.5,
  "conservative_stop_distance_usd": 78.5,
  "global_xauusd_max_excursion_used": false,
  "p75_conservative_stop_price": 6.0375,
  "p85_conservative_stop_price": 10.3044,
  "p90_conservative_stop_price": 14.8138,
  "p95_conservative_stop_price": 24.5025,
  "pct_manipulation_gt_12_usd": 0.1005,
  "pct_manipulation_gt_15_usd": 0.0708,
  "pct_manipulation_gt_20_usd": 0.0502,
  "pct_manipulation_le_10_usd": 0.8881,
  "pct_manipulation_le_12_usd": 0.8995,
  "pct_manipulation_le_8_usd": 0.8425,
  "profile_risk_too_large": true,
  "risky_stop_distance_pips": 628.0,
  "risky_stop_distance_price": 62.8,
  "risky_stop_distance_usd": 62.8
}
```

## Expansion / TP Profile

```json
{
  "expansion_profile": {
    "average_pips": 158.054,
    "average_price": 15.8054,
    "average_usd": 15.8054,
    "count": 438,
    "max_pips": 1326.3,
    "max_price": 132.63,
    "max_usd": 132.63,
    "median_pips": 121.35,
    "median_price": 12.135,
    "median_usd": 12.135,
    "p25_price": 6.83,
    "p50_price": 12.135,
    "p75_price": 20.06,
    "p80_price": 22.786,
    "p85_price": 26.676,
    "p90_price": 31.872,
    "p95_price": 45.0425
  },
  "tp_profile": {
    "adaptive_tp1_distance_pips": 158.054,
    "adaptive_tp1_distance_price": 15.8054,
    "adaptive_tp1_used": true,
    "p90_quartiles_price": {
      "tp1": 7.968,
      "tp2": 15.936,
      "tp3": 23.904,
      "tp4": 31.872
    },
    "p95_quartiles_price": {
      "tp1": 11.2606,
      "tp2": 22.5212,
      "tp3": 33.7819,
      "tp4": 45.0425
    },
    "tp1_distance_pips": 331.575,
    "tp1_distance_price": 33.1575,
    "tp2_distance_pips": 663.15,
    "tp2_distance_price": 66.315,
    "tp3_distance_pips": 994.725,
    "tp3_distance_price": 99.4725,
    "tp4_distance_pips": 1326.3,
    "tp4_distance_price": 132.63,
    "tp_anchor_is_entry": false,
    "tp_anchor_level": "H1_LIQUIDITY_LEVEL"
  }
}
```

## R:R Diagnostic

```json
{
  "adaptive_TP1_R_conservative_stop": 0.2605,
  "adaptive_TP1_R_risky_stop": 0.3257,
  "conservative_stop_distance_price": 78.5,
  "conservative_stop_rr": {
    "tp1_R": 0.4816,
    "tp2_R": 0.904,
    "tp3_R": 1.3264,
    "tp4_R": 1.7488
  },
  "mae_entry_distance_price": 4.6471,
  "risky_stop_distance_price": 62.8,
  "risky_stop_rr": {
    "tp1_R": 0.602,
    "tp2_R": 1.13,
    "tp3_R": 1.658,
    "tp4_R": 2.1859
  },
  "rr_flags": [
    "TP1_R_TOO_SMALL",
    "TP2_R_BELOW_1",
    "RR_STRUCTURALLY_UNFAVORABLE"
  ],
  "rr_structurally_valid": false
}
```

## Verdict Flags

- `STATISTICAL_SAMPLE_RECORDER_BUILT`
- `M15_X45_FILTER_CORRECTED`
- `GLOBAL_MAX_EXCURSION_REJECTED`
- `MAE_FROM_VALID_MANIPULATION_SAMPLES`
- `VALID_NO_ENTRY_SAMPLES_INCLUDED`
- `MAX_EXCURSION_FROM_VALID_SAMPLE_SET`
- `CONSERVATIVE_SL_MAX_EXCURSION_PLUS_25`
- `TP_ANCHORED_TO_H1_CONFIRMED`
- `REACTION_CONFIRMATION_NOT_FULLY_MODELED`
- `PROFILE_RISK_TOO_LARGE`
- `LOW_SAMPLE_CONTEXT`
- `STRATEGY_2_REMAINS_RESEARCH_ONLY`
- `NO_LIVE_DEPLOYMENT_DECISION`


## Unit Conversion

- price distance and USD distance are the same XAUUSD price movement in this report.
- pips are reported separately using pip_factor `10.0`.

## Raw Summary JSON

```json
{
  "h1_contexts_analyzed": 3401,
  "status_counts": {
    "INVALID_INSUFFICIENT_DATA": 335,
    "INVALID_MOVE_ALREADY_CONSUMED": 11,
    "INVALID_NO_CLEAR_MANIPULATION": 20,
    "INVALID_NO_DISTRIBUTION": 160,
    "INVALID_OPPOSITE_M15_X45_TAKEN_FIRST": 2437,
    "VALID_SAMPLE_NO_ENTRY_MANIPULATED_LESS": 322,
    "VALID_SAMPLE_TRADE_TRIGGERED": 116
  },
  "valid_no_entry_samples": 322,
  "valid_samples": 438,
  "valid_triggered_samples": 116,
  "verdict_flags": [
    "STATISTICAL_SAMPLE_RECORDER_BUILT",
    "M15_X45_FILTER_CORRECTED",
    "GLOBAL_MAX_EXCURSION_REJECTED",
    "MAE_FROM_VALID_MANIPULATION_SAMPLES",
    "VALID_NO_ENTRY_SAMPLES_INCLUDED",
    "MAX_EXCURSION_FROM_VALID_SAMPLE_SET",
    "CONSERVATIVE_SL_MAX_EXCURSION_PLUS_25",
    "TP_ANCHORED_TO_H1_CONFIRMED",
    "REACTION_CONFIRMATION_NOT_FULLY_MODELED",
    "PROFILE_RISK_TOO_LARGE",
    "LOW_SAMPLE_CONTEXT",
    "STRATEGY_2_REMAINS_RESEARCH_ONLY",
    "NO_LIVE_DEPLOYMENT_DECISION"
  ]
}
```

## Next Step

Recommended Strategy 2-only next branch: `feat/strategy-2-manual-sample-label-pack` if manual chart review is needed, or `feat/strategy-2-reaction-confirmation-model` if the reaction proxy needs refinement.
