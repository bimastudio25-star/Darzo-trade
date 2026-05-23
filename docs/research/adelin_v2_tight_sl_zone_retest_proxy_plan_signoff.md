# Adelin v2 H3/H4 Proxy Plan — Human Signoff Template

## Context

This signoff template is for approving or rejecting the pre-registered H3/H4 proxy plan for future bounded diagnostic execution only.

This document does not approve Phase 4, matched-control replay, live trading, runtime changes, scoring, tuning, Telegram alerts, broker execution, order_send, or profitability claims.

Approved-for-review proxy concepts:

H3:

* TIGHT_SL_BEHIND_SPIKE_OR_SWING
* formula frozen in commit 56dcff0
* candidate reference price to nearest valid pre-decision invalidation extreme
* LONG uses swing/sweep low
* SHORT uses swing/sweep high
* normalization uses pre-decision local range
* primary normalizer: M1 last 30 closed candles before decision
* fallback normalizer: M5 last 12 closed candles before decision
* fixed thresholds:

  * TIGHT <= 0.25
  * MEDIUM > 0.25 and <= 0.50
  * WIDE > 0.50

H4:

* ZONE_RETEST_OR_RECLAIM
* states:

  * NO_ZONE_AVAILABLE
  * INSIDE_ZONE
  * RETEST_HELD
  * RECLAIM_CONFIRMED
  * RETEST_FAILED_PRE_DECISION

## Checklist

* [x] I approve the H3 tight-SL proxy formula.
* [x] I approve the fixed H3 thresholds 0.25 and 0.50.
* [x] I understand percentile thresholds are forbidden.
* [x] I understand threshold tuning from GOOD/FAST results is forbidden.
* [x] I approve the H3 missing-data states:

  * UNKNOWN_REFERENCE_PRICE
  * NO_VALID_INVALIDATION_EXTREME
  * INVALID_GEOMETRY
  * INSUFFICIENT_PRE_DECISION_RANGE

* [x] I approve the H4 categorical pre-entry states.
* [x] I understand future execution must use pre-entry candles only.
* [x] I understand post-entry candles are forbidden.
* [x] I understand TP/SL hit, PnL, R multiple, future MFE/MAE, future liquidity behavior, outcome-derived thresholds, and non-directional max-move replay are forbidden.
* [x] I understand the next branch may run only a bounded H3/H4 proxy diagnostic execution if this signoff is approved.
* [x] I understand this signoff does not approve Phase 4, matched-control replay, live trading, runtime changes, scoring, tuning, Telegram alerts, orders, broker execution, order_send, or profitability claims.

## Decision

Reviewer: Adelin Bivol

Date: 2026-05-23

Decision: APPROVE

## Notes

Human reviewer approves bounded H3/H4 proxy diagnostic execution only.

H3 coverage verified: TIGHT_SL_BEHIND_SPIKE_OR_SWING, formula frozen at commit 56dcff0, M1 30-candle primary normalizer, M5 12-candle fallback, fixed thresholds 0.25/0.50, all four missing-data states present.

H4 coverage verified: ZONE_RETEST_OR_RECLAIM, all five pre-entry categorical states present.

This approval does not approve Phase 4, matched-control replay, runtime changes, scoring, tuning, Telegram alerts, live trading, broker execution, order_send, or profitability claims. Phase 4 remains blocked.
