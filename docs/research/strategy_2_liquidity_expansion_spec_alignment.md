# Strategy 2 Liquidity Expansion Spec Alignment

## Executive Summary

This branch is a research-only specification audit plus an isolated Strategy 2.1 mechanics prototype. It does not recover Strategy 2 live, does not optimize parameters, and does not make a deployment decision.

## Source Spec Recap

- Model: XAUUSD Liquidity Expansion Model.
- Reference levels: previous H1 high/low, with M15 :45 high/low as sequence filter.
- Entry: average MAE deviation beyond the H1 liquidity level, with candle-anatomy confirmation.
- Stop: H1 liquidity level plus Max Excursion * 1.25.
- Targets: TP1/TP2/TP3/TP4 quartiles anchored to the H1 level, not actual entry.
- Management: move stop to BE at TP1; runner can continue to later quartiles.
- Risk sanity: SL over 12 USD is flagged as too large for this scalping model.

## Current Strategy 2.0 Forensic Mismatch

- Prior forensic sample: 57 trades from 2026-03-15 to 2026-05-14.
- Average SL: 70.6395 USD; median SL: 51.04 USD.
- Average TP: 50.2656 USD; median TP: 42.49 USD.
- Average planned R:R: 0.807.
- Only 4/57 reached 1R and only 1/57 reached 2R.

## TP/SL Audit

- trades audited: `57`
- current SL avg/median/min/max: `70.6395` / `51.04` / `28.58` / `205.51`
- expected SL avg/median/min/max from stats profile: `226.1625` / `226.1625` / `226.1625` / `226.1625`
- SL > 12 USD count/rate: `57` / `1.0`
- current planned R:R average: `0.807`
- expected R:R to TP1/TP2/TP3/TP4: `0.1008`, `0.2602`, `0.3652`, `0.4702`

## H1 And M15 Alignment

- H1 level identified rate: `1.0`
- M15 00:45 computable rate: `1.0`
- liquidity sequence valid rate: `1.0`

## MAE / SL / TP Alignment

- entry near MAE rate: `0.3158`
- SL Max Excursion +25 alignment rate: `0.0351`
- TP H1-anchored rate: `0.1404`
- TP appears entry-anchored rate: `0.0`

## Stats Profile

```json
{
  "average_expansion": 10.8973,
  "average_mae": 12.7783,
  "calibration_from": "2026-03-15T00:00:00+00:00",
  "calibration_to": "2026-05-09T00:00:00+00:00",
  "effective_risk_from_mae_entry": 238.9408,
  "effective_risk_gt_12": true,
  "max_excursion": 180.93,
  "max_expansion": 90.46,
  "median_expansion": 7.42,
  "median_mae": 7.625,
  "p75_mae": 15.1275,
  "p90_mae": 28.69,
  "samples": 826,
  "suggested_sl_distance": 226.1625,
  "tp_quartile_distance": 22.615
}
```

## Strategy 2.1 Research-Only Model Design

The Strategy 2.1 prototype is isolated in analysis code and is not registered into live/runtime paths. It builds H1-anchored entries, Max Excursion +25 stops, H1-anchored quartile targets, TP1 break-even management, and default no-trade behavior when effective risk exceeds 12 USD.

## Smoke Results

- setups found: `132`
- trades taken: `0`
- no-trades: `132`
- no-trade reasons: `{'RISK_TOO_LARGE': 13, 'NO_TRADE_H1_LIQUIDITY_NOT_TAKEN': 76, 'NO_TRADE_MAE_NOT_REACHED': 29, 'opposite_m15_level_taken_before_h1': 13, 'NO_TRADE_CONFIRMATION_MISSING': 1}`
- average SL: `213.3842`
- median SL: `213.3842`
- SL > 12 count/rate: `13` / `1.0`
- planned R:R to TP1/TP2/TP3/TP4: `None`, `None`, `None`, `None`
- outcomes: `{'NO_TRADE': 132}`

## Safety Confirmation

- No live trading was enabled.
- No Telegram alerts were sent.
- No broker orders were placed.
- Strategy 2.0 was not modified in place.
- Strategy 3 and Adelin were untouched.
- Strategy 2.1 remains research-only and isolated from runtime by default.

## Limitations

- The local PDF was not found, so the embedded spec was used.
- Stats are calibration-profile mechanics, not validation.
- Smoke results are small-sample mechanics only.
- Dominant H1 range-in-range detection is not forced when unsafe.
- Candle anatomy confirmation is intentionally simple and report-only.

## Verdict

- `SOURCE_PDF_NOT_AVAILABLE_USED_EMBEDDED_SPEC`
- `STRATEGY_2_0_SPEC_MISMATCH_CONFIRMED`
- `CURRENT_TP_SL_ANCHORING_WRONG`
- `CURRENT_SL_TOO_LARGE_FOR_SCALPING_MODEL`
- `CURRENT_RR_STRUCTURALLY_UNFAVORABLE`
- `MAE_ENTRY_MODEL_MISSING_OR_FAILED`
- `STRATEGY_2_REMAINS_RESEARCH_ONLY`
- `NO_LIVE_DEPLOYMENT_DECISION`
- `STRATEGY_2_1_SPEC_MODEL_ADDED_RESEARCH_ONLY`
- `STRATEGY_2_1_SAMPLE_TOO_SMALL`
- `SPEC_MODEL_RISK_TOO_LARGE`
- `SPEC_MODEL_MECHANICS_OK_SAMPLE_TOO_SMALL`

## Recommended Next Step

If the spec profile remains mechanically too risky, repair the statistical profile and source-spec extraction before any larger Strategy 2 test. Otherwise, run a limited Strategy 2.1 research validation on a clearly separated sample.
