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

## Summary

- total_samples: `40`
- source_modes_used: `CANDIDATE_WINDOW_MODE`
- limitations: `MATPLOTLIB_UNAVAILABLE_USING_SVG_CHARTS, NO_TRADES_PATH_AVAILABLE`
