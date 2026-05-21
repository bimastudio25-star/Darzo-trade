# Strategy 2 M15 Model Selection Review

## Context

The fixed HH:45/x:45 M15 interpretation has been superseded. The mechanical correction branch implemented three deterministic current-M15 models: containing, preceding, and approach_window. This review compares them without choosing a model by entry count alone.

## Safety

- Strategy 3 untouched.
- data/XAUUSD/*.csv untouched.
- No live trading, Telegram, broker execution, orders, optimization, ML, or runtime registration.

## Method

- Inputs are the read-only mechanical correction outputs.
- Scorecard uses tail risk, p95 MAE, agreement, sample adequacy, and mechanical fit.
- Entry count is reported but not used as a positive score criterion.
- No PnL, PF, grid search, or model training is used.
- Unit conversion: pips = USD/price distance * 10.0.

## Scorecard

| Model | Score | Valid | Entry reported | >20 tail % | p95 USD | Agreement |
|---|---:|---:|---:|---:|---:|---:|
| containing | 69.0244 | 269 | 134 | 18.22 | 41.592 | 0.752 |
| approach_window | 66.0101 | 260 | 134 | 18.85 | 42.566 | 0.7572 |
| preceding | 39.1207 | 469 | 252 | 22.17 | 43.124 | 0.5426 |

## Tail Risk

| Model | <=8 | <=10 | <=12 | >12 | >20 | p95 USD | Max USD | Conservative SL USD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| containing | 145 | 171 | 179 | 90 | 49 | 41.592 | 180.93 | 226.1625 |
| preceding | 222 | 269 | 292 | 177 | 104 | 43.124 | 180.93 | 226.1625 |
| approach_window | 136 | 162 | 170 | 90 | 49 | 42.566 | 180.93 | 226.1625 |

## Old X45 Comparison

| Model | Old valid | Corrected valid | Overlap | Old valid/new invalid | Old invalid/new valid |
|---|---:|---:|---:|---:|---:|
| containing | 438 | 269 | 241 | 197 | 28 |
| preceding | 438 | 469 | 292 | 146 | 177 |
| approach_window | 438 | 260 | 235 | 203 | 25 |

## H1 Reference Breakdown

| Model | H1 reference | Valid | Entry | >12 tail % | >20 tail % | Max USD |
|---|---|---:|---:|---:|---:|---:|
| containing | dominant_h1 | 8 | 6 | 62.5 | 50.0 | 42.56 |
| containing | previous_h1 | 261 | 128 | 32.57 | 17.24 | 180.93 |
| preceding | dominant_h1 | 20 | 14 | 40.0 | 35.0 | 42.56 |
| preceding | previous_h1 | 449 | 238 | 37.64 | 21.6 | 180.93 |
| approach_window | dominant_h1 | 8 | 6 | 62.5 | 50.0 | 42.56 |
| approach_window | previous_h1 | 252 | 128 | 33.73 | 17.86 | 180.93 |

## Recommendation

- Recommendation: `INCONCLUSIVE`
- Rationale: preceding has materially higher sample and entry counts, but that is not sufficient evidence; it is also more permissive and carries larger tail exposure. Containing and approach_window are more conservative and close enough that model selection remains inconclusive; targeted disagreement review is the safer next diagnostic.

## Disagreement Groups

| Group | Count | >12 tail % | >20 tail % | Entry % |
|---|---:|---:|---:|---:|
| valid_in_containing_only | 9 | 0.0 | 0.0 | 0.0 |
| valid_in_preceding_only | 211 | 41.71 | 26.07 | 56.87 |
| valid_in_approach_window_only | 0 | 0.0 | 0.0 | 0.0 |
| valid_in_all_three | 258 | 34.5 | 18.99 | 51.16 |
| invalid_in_all_three | 609 | 0.0 | 0.0 | 0.0 |
| containing_approach_agree_preceding_differs | 213 | 41.86 | 25.58 | 57.67 |
| preceding_containing_agree_approach_differs | 0 | 0.0 | 0.0 | 0.0 |
| preceding_approach_agree_containing_differs | 9 | 0.0 | 0.0 | 0.0 |

## Limitations

- No manual labels are included.
- No visual user selection has been performed.
- No live/signal validation is made.
- The current-M15 phrase remains approximated mechanically.
- Exit logic remains incomplete.

## Verdict Flags

- M15_MODEL_SELECTION_REVIEW_COMPLETE
- PRECEDING_ENTRY_COUNT_NOT_SUFFICIENT_EVIDENCE
- TAIL_RISK_PERSISTS_ALL_MODELS
- UNIT_CONVERSION_CLARIFIED
- VISUAL_REVIEW_CANDIDATES_EXPORTED
- STRATEGY_2_REMAINS_RESEARCH_ONLY
- NO_LIVE_DEPLOYMENT_DECISION
- PRECEDING_MODEL_MORE_PERMISSIVE
- CONTAINING_MODEL_MORE_CONSERVATIVE
- APPROACH_WINDOW_MODEL_MORE_CONSERVATIVE
- MODEL_SELECTION_INCONCLUSIVE

## Next Strategy 2-Only Step

- feat/strategy-2-m15-disagreement-visual-review
