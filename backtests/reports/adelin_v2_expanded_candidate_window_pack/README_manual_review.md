# Adelin v2 Manual Visual Review

Status: research-only. Candidate windows are for visual labeling only and are not trade signals.

## How To Review

1. Open `index.html`.
2. Inspect each sample page and chart.
3. Fill `manual_labels_template.csv`.
4. Use `YES`, `NO`, `MAYBE`, or `UNKNOWN` for binary/manual context fields.
5. Do not treat any candidate window as a trade alert or live signal.

## Suggested Label Values

- setup labels: `A_PLUS_REVERSAL`, `VALID_REVERSAL`, `DIRTY_REVERSAL`, `NO_TRADE`, `CONTINUATION_BLOCKED`, `RARE_IFVG_CONTINUATION_CANDIDATE`, `UNKNOWN`
- liquidity classes: `HTF_EXTERNAL`, `HTF_INTERNAL`, `LTF_EXTERNAL`, `LTF_INTERNAL`, `MULTI_TF_ALIGNED`, `SHALLOW_INTERNAL`, `DEEP_VALID`, `UNKNOWN`
- reaction zones: `FVG`, `IFVG`, `VOLUME_CRACK`, `VOLUME_PROFILE_SWING`, `OLD_REJECTION`, `OLD_RANGE_REJECTION`, `NUMBER_THEORY`, `NONE`, `UNKNOWN`

## Review Focus

- Was meaningful liquidity taken?
- Was the liquidity shallow or deep?
- Was a valid pre-existing reaction zone touched?
- Is number theory only confluence, not the whole thesis?
- Is there a target liquidity pool or likely reaction target?
- Would a 20 pip normal / 40 pip max stop fit behind local structure?
- Did price react quickly, accumulate, or engulf against the setup?
- Check `execution_data_status` first. Skip or down-rank samples with insufficient M1/M5 execution data.
- Review `candidate_source_type`, `entry_level_source`, session, month, and volatility bucket before comparing outcomes.

## Summary

- total_samples: `300`
- date_range_coverage_days: `111`
- max_samples_per_day: `5`
- min_sample_spacing_minutes: `240`
- candidate_source_counts: `{'ROUND_LEVEL': 127, 'SWEEP_EXTREME': 127, 'SWEPT_LIQUIDITY_LEVEL': 22, 'UNKNOWN': 24}`
- entry_level_source_counts: `{'ROUND_LEVEL': 127, 'SWEEP_EXTREME': 127, 'SWEPT_LIQUIDITY_LEVEL': 22, 'UNKNOWN': 24}`
- session_distribution: `{'ASIA': 71, 'ASIA_OPEN': 27, 'LONDON': 73, 'LONDON_OPEN': 8, 'NEW_YORK': 49, 'NEW_YORK_OPEN': 14, 'OTHER': 58}`
- volatility_bucket_distribution: `{'HIGH': 86, 'LOW': 69, 'MID': 145}`
- reviewable_samples: `300`
- reviewable_m1_m5_count: `300`
- insufficient_execution_data_count: `0`
- source_modes_used: `CANDIDATE_WINDOW_MODE`
- expanded_pack_generation_verdict: `INCONCLUSIVE`
- expanded_pack_generation_verdict_reason: `LOCAL_DATA_COVERAGE_111_DAYS_BELOW_REQUESTED_180`
- limitations: `INSUFFICIENT_EXECUTION_DATA_SAMPLES_SKIPPED, LOCAL_DATA_COVERAGE_BELOW_REQUESTED_MIN_DATE_RANGE, MATPLOTLIB_UNAVAILABLE_USING_SVG_CHARTS, NO_TRADES_PATH_AVAILABLE`

## Pre-Registered Decision Criteria

Decision criteria are recorded before expanded outcome replay. They are descriptive project gates, not proof of edge.

- continue refinement if a useful source group clears a fast-reaction, runner, or fast-SL-reduction threshold against matched controls.
- stop/archive if useful source groups are flat and fast SL is not better, or if fast SL is materially worse across all useful sources.
- repeat expansion once only for visible but underpowered effects with fewer than 300 generated candidates due to data constraints.
