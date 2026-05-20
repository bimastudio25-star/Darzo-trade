# Strategy 2 Auto Filter Hypothesis Diagnostics

## Context

The Strategy 2 statistical sample recorder is the input for this diagnostic pass. The M15 HH:45 selection was already corrected upstream. The global sample pool is still intentionally broad: the body of the manipulation-depth distribution is plausible, while the raw max excursion tail drives an unusable structural stop profile.

The manual sample label pack exists, but this branch intentionally uses no manual labels. It compares body samples and deep-tail samples to generate descriptive filter hypotheses only.

## Safety

- Research-only diagnostic output.
- No live trading, broker calls, order_send, orders, Telegram, signals, or runtime registration.
- No parameter optimization, grid search, ML classifier, or profit-factor selection.
- Market CSV files are read-only and not written.
- Strategy 3 is outside this branch and is not touched.

## Method

- Body buckets: manipulation_depth_usd <= 8, <= 10, <= 12.
- Tail buckets: manipulation_depth_usd > 12, > 15, > 20.
- Top-tail review: top 10 samples by manipulation_depth_usd.
- Features analyzed: manipulation, expansion, direction, session/hour/day, H1 reference type/range, M15 sequence validity, reaction confirmation/latency, and derived ratios.
- Missing or unavailable features: distribution_latency, h1_high, h1_low, move_already_consumed.
- Hypotheses use descriptive thresholds only: p25/p90 feature splits, existing 8/10/12/15/20 USD guardrails, and simple session/hour groupings.

## Results

- Samples loaded: 3401
- Valid samples: 438
- Body <=8 USD: 369
- Body <=10 USD: 389
- Body <=12 USD: 394
- Tail >12 USD: 44
- Tail >15 USD: 31
- Tail >20 USD: 22
- Top-tail max manipulation USD: 62.8

## Distinguishing Features

- Weak expansion/manipulation ratio was the strongest descriptive split in this run.
- Small or negative target space after sweep also concentrated deep-tail samples.
- Dominant H1 reference samples carried materially higher deep-tail concentration than previous H1 samples.
- Missing reaction confirmation removed fewer total samples but captured a meaningful slice of the tail with limited body removal.
- Session-level concentration was weak in this run; hour-level buckets were more descriptive but carry higher overfit risk.

## Strongest Hypotheses

### HYPOTHESIS_002

- Rule: Remove samples where expansion/manipulation ratio is at or below valid-sample p25 (2.1582).
- Samples kept: 328
- Samples removed: 110
- Tail removed: 88.64%
- Body removed: 18.02%
- Risk of overfit: LOW
- Verdict: PROMISING_DIAGNOSTIC

### HYPOTHESIS_006

- Rule: Remove samples where target_space_after_sweep is at or below valid-sample p25 (3.0225).
- Samples kept: 328
- Samples removed: 110
- Tail removed: 79.55%
- Body removed: 19.04%
- Risk of overfit: LOW
- Verdict: PROMISING_DIAGNOSTIC

### HYPOTHESIS_004

- Rule: Remove H1 reference types with tail rate at least 5 pct points above overall: dominant_h1.
- Samples kept: 328
- Samples removed: 110
- Tail removed: 75.0%
- Body removed: 19.54%
- Risk of overfit: MEDIUM
- Verdict: PROMISING_DIAGNOSTIC

### HYPOTHESIS_005

- Rule: Remove samples without reaction confirmation.
- Samples kept: 408
- Samples removed: 30
- Tail removed: 34.09%
- Body removed: 3.81%
- Risk of overfit: LOW
- Verdict: PROMISING_DIAGNOSTIC

### HYPOTHESIS_007

- Rule: Remove hour buckets with tail rate at least 8 pct points above overall: [1, 5, 17].
- Samples kept: 373
- Samples removed: 65
- Tail removed: 29.55%
- Body removed: 13.2%
- Risk of overfit: HIGH
- Verdict: PROMISING_DIAGNOSTIC

## Hypothesis Table

| Hypothesis | Rule | Kept | Removed | Tail removed | Body removed | Risk | Verdict |
|---|---|---:|---:|---:|---:|---|---|
| HYPOTHESIS_002 | Remove samples where expansion/manipulation ratio is at or below valid-sample p25 (2.1582). | 328 | 110 | 88.64% | 18.02% | LOW | PROMISING_DIAGNOSTIC |
| HYPOTHESIS_006 | Remove samples where target_space_after_sweep is at or below valid-sample p25 (3.0225). | 328 | 110 | 79.55% | 19.04% | LOW | PROMISING_DIAGNOSTIC |
| HYPOTHESIS_004 | Remove H1 reference types with tail rate at least 5 pct points above overall: dominant_h1. | 328 | 110 | 75.0% | 19.54% | MEDIUM | PROMISING_DIAGNOSTIC |
| HYPOTHESIS_005 | Remove samples without reaction confirmation. | 408 | 30 | 34.09% | 3.81% | LOW | PROMISING_DIAGNOSTIC |
| HYPOTHESIS_007 | Remove hour buckets with tail rate at least 8 pct points above overall: [1, 5, 17]. | 373 | 65 | 29.55% | 13.2% | HIGH | PROMISING_DIAGNOSTIC |
| HYPOTHESIS_001 | Remove samples where h1_reference_range is above the valid-sample p90 (48.991). | 394 | 44 | 27.27% | 8.12% | LOW | PROMISING_DIAGNOSTIC |
| HYPOTHESIS_003 | No session bucket had enough excess deep-tail concentration for a descriptive split. | 0 | 0 | 0.0% | 0.0% | LOW | INSUFFICIENT_DATA |

## Weak Or Rejected Diagnostics

- HYPOTHESIS_003: INSUFFICIENT_DATA - No session bucket had enough excess deep-tail concentration for a descriptive split.

## Limitations

- No manual labels are used.
- No proof of a user A+ filter is claimed.
- No performance validation or trading edge is claimed.
- No Strategy 2 signal generation is performed.
- Reaction/anatomy features may still be incomplete.
- Hypotheses are candidates only and should be audited visually before any runtime consideration.

## Verdict Flags

- AUTO_FILTER_HYPOTHESIS_DIAGNOSTICS_COMPLETE
- BODY_TAIL_COMPARISON_COMPLETE
- BODY_OF_DISTRIBUTION_PLAUSIBLE
- RAW_MAX_EXCURSION_TAIL_CONFIRMED
- USER_LABELS_STILL_RECOMMENDED
- STRATEGY_2_REMAINS_RESEARCH_ONLY
- NO_LIVE_DEPLOYMENT_DECISION
- DEEP_TAIL_DRIVERS_IDENTIFIED
- REACTION_FEATURES_MISSING

## Next Strategy 2-only Branch

- feat/strategy-2-a-plus-filter-hypothesis-audit
