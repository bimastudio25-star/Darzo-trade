# Strategy 2 M15 Containing Next Diagnostic

## Context

The M15 model selection review was intentionally inconclusive because static visual review could not reliably confirm the user's discretionary intent. For this next diagnostic, `containing` is selected as the primary research model because it is the closest deterministic match to the current M15 while price is taking the H1 liquidity level. `approach_window` remains a conservative sensitivity check. `preceding` is rejected for now as too permissive and tail-heavy.

## Safety

- Strategy 3 untouched.
- data/XAUUSD/*.csv untouched.
- No live trading, Telegram, broker execution, orders, optimization, signal generation, runtime registration, or ML.

## Method

- Primary model: `containing`.
- Sensitivity model: `approach_window`.
- Entry mechanics: H1 level taken, average MAE reached, and re-entry into the H1 range.
- Risk mechanics: Max Excursion from valid samples, conservative SL = Max Excursion * 1.25.
- TP mechanics: TP1/TP2/TP3/TP4 are quartiles of max expansion and are anchored to the H1 liquidity level, not entry.
- Unit conversion: pips = USD/price distance * 10.0. Do not call USD values pips.

## Counts And Entry Mechanics

| Model | Role | Rows | Valid | Entry | No-entry | Invalid | H1 take | MAE reached | Re-entry |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| containing | primary | 1089 | 269 | 134 | 135 | 820 | 841 | 563 | 402 |
| approach_window | sensitivity | 1089 | 260 | 134 | 126 | 829 | 841 | 563 | 402 |

## Risk / SL Profile

| Model | Avg MAE USD | Median | p75 | p90 | p95 | Max Excursion | Conservative SL | >12 | >20 | >40 | >100 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| containing | 12.798 | 6.96 | 14.82 | 27.854 | 41.592 | 180.93 | 226.1625 | 90 | 49 | 15 | 4 |
| approach_window | 13.1645 | 7.23 | 15.04 | 28.17 | 42.566 | 180.93 | 226.1625 | 90 | 49 | 15 | 4 |

## TP / Theoretical R Profile

| Model | Avg expansion | Median expansion | Max expansion | TP1 | TP2 | TP3 | TP4 | Effective risk | TP1_R | TP2_R | TP3_R | TP4_R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| containing | 14.5616 | 11.39 | 67.19 | 16.7975 | 33.595 | 50.3925 | 67.19 | 213.3645 | 0.1387 | 0.2174 | 0.2962 | 0.3749 |
| approach_window | 14.3569 | 11.15 | 67.19 | 16.7975 | 33.595 | 50.3925 | 67.19 | 212.998 | 0.1407 | 0.2195 | 0.2984 | 0.3773 |

## Containing vs Approach Window

- Valid overlap: 260
- Containing-only valid samples: 9
- Approach-window-only valid samples: 0
- Shared entries: 134
- Conclusion: approach_window does not materially change primary containing conclusions

## Verdict

- Tail risk verdict: `TAIL_RISK_REMAINS_STRUCTURAL`
- R profile verdict: `R_PROFILE_STRUCTURALLY_WEAK`
- Containing is acceptable as the next research diagnostic model only, with no live/runtime decision.

## Limitations

- No manual labels.
- No live validation.
- No final deployment model selection.
- Exit management remains simplified; BE-at-TP1 and H1-close BE are documented descriptively, not used as proof.
- Tail risk may remain structural.

## Verdict Flags

- CONTAINING_SELECTED_FOR_NEXT_DIAGNOSTIC
- PRECEDING_REJECTED_AS_TOO_PERMISSIVE_FOR_NOW
- APPROACH_WINDOW_RETAINED_AS_SENSITIVITY_CHECK
- MECHANICAL_ENTRY_PROFILE_BUILT
- TP_FROM_H1_CONFIRMED
- STRATEGY_2_REMAINS_RESEARCH_ONLY
- NO_LIVE_DEPLOYMENT_DECISION
- TAIL_RISK_REMAINS_STRUCTURAL
- R_PROFILE_STRUCTURALLY_WEAK

## Next Strategy 2-Only Step

- feat/strategy-2-containing-mechanical-smoke
