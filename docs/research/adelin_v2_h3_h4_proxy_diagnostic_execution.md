# Adelin v2 H3/H4 Proxy Diagnostic Execution

## Context

This bounded diagnostic executes the human-approved H3/H4 proxy computation on existing Adelin v2 samples. It is not Phase 4, matched-control replay, backtest, runtime scoring, or deployment preparation.

## Inputs

* Sample artifact: `backtests\reports\adelin_v2_preentry_outcome_diagnostics_direction_recovered\sample_diagnostics.csv`
* OHLC scope: `data/XAUUSD/M1.csv` and `data/XAUUSD/M5.csv` were loaded; only candles with `time < decision_timestamp` were used per sample.
* Signoff decision: APPROVE

## Counts

* Total samples: 40
* Executable samples: 40
* Skipped samples: 0
* Leakage failures: 0

## H3 State Counts

* MEDIUM: 4
* NO_VALID_INVALIDATION_EXTREME: 5
* TIGHT: 31

## H4 State Counts

* INSIDE_ZONE: 23
* NO_ZONE_AVAILABLE: 1
* RECLAIM_CONFIRMED: 6
* RETEST_FAILED_PRE_DECISION: 10

## Safety

* Pre-entry only: true
* Post-entry data used: false
* Matched-control replay run: false
* Phase 4 unlocked: false
* Runtime logic changed: false
* Live/orders/Telegram/broker/order_send: false

## Limitations

* H4 zone availability depends on existing pre-entry metadata fields such as FVG/iFVG zone bounds and numeric levels.
* H3 invalidation extreme selection is deterministic but remains a research proxy, not a trading rule.
* The output is descriptive diagnostic evidence only and does not unlock Phase 4.

## Verdict

H3/H4 proxy distributions were computed for research review only. Phase 4 remains blocked, and no edge, profitability, deployability, scoring, or live-signal claim is made.
