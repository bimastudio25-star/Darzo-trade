# Strategy 2 Visual Review Pack

## Purpose

This branch creates a research-only visual manual review pack for Strategy 2 auto-filter hypothesis validation.

The pack lets the user inspect selected Strategy 2 statistical samples in static HTML pages with chart images, then fill a prefilled manual-label CSV without manually searching the same timestamps in MT5.

## Why Visual Review Is Needed

The statistical sample recorder found a plausible body of Strategy 2 manipulation samples, but the raw max-tail manipulation drove unusable stop profiles. The auto-filter hypothesis diagnostics found useful descriptive candidates, especially low expansion/manipulation ratio and low target space after sweep, but those hypotheses are not deployable filters.

Manual chart review is needed to see whether:
- body samples removed by HYP_002 are actually acceptable;
- deep-tail samples removed by HYP_002 are obviously bad;
- low target-space cases match discretionary rejection logic;
- dominant H1 cases are structurally different;
- missing-reaction examples are genuinely weak or just under-modeled.

## Inputs

Read-only inputs:
- `data/XAUUSD/*.csv`
- `backtests/reports/strategy_2_statistical_sample_recorder/h1_liquidity_samples.csv`
- `backtests/reports/strategy_2_auto_filter_hypothesis_diagnostics/filter_hypotheses.csv`
- `backtests/reports/strategy_2_auto_filter_hypothesis_diagnostics/body_tail_comparison.csv`
- `backtests/reports/strategy_2_auto_filter_hypothesis_diagnostics/top_tail_samples.csv`
- `backtests/reports/strategy_2_manual_sample_label_pack/manual_sample_template.csv`

If hypothesis CSVs are missing, the script recomputes HYP_002 and HYP_006 p25 thresholds in memory from the statistical sample recorder output.

## Outputs

Output directory:

`backtests/reports/strategy_2_manual_visual_review_pack`

Main files:
- `index.html`
- `manual_samples_prefilled.csv`
- `review_pack_summary.json`
- `README_review_pack.md`
- `samples/S2_REVIEW_001.html`
- `charts/S2_REVIEW_001_context.png`

PNG charts are generated with matplotlib when available. If chart generation fails for a sample, the HTML page and prefilled CSV row are still produced.

## Safety

- Strategy 3 untouched.
- `data/XAUUSD/*.csv` untouched and used only as read-only input.
- No live trading.
- No Telegram.
- No broker execution.
- No `order_send`.
- No orders.
- No Strategy 2 runtime registration.
- No signal generation.
- No optimization.
- No ML classifier.

## How To Run

```powershell
python scripts/create_strategy_2_visual_review_pack.py --symbol XAUUSD --data-dir data --auto-samples-path backtests/reports/strategy_2_statistical_sample_recorder/h1_liquidity_samples.csv --hypotheses-dir backtests/reports/strategy_2_auto_filter_hypothesis_diagnostics --output-dir backtests/reports/strategy_2_manual_visual_review_pack --max-samples 40 --pip-factor 10 --dry-run
```

Then open:

`backtests/reports/strategy_2_manual_visual_review_pack/index.html`

## Sample Selection

The default pack selects up to 40 samples:
- body kept by HYP_002;
- body samples removed by HYP_002, to inspect possible false positives;
- tail samples removed by HYP_002;
- extreme-tail samples above 20 USD, including the largest manipulation if available;
- HYP_006 low target-space examples;
- HYP_004 dominant-H1 examples;
- HYP_005 missing-reaction examples.

The goal is not to select easy cases. The pack intentionally includes ambiguous cases.

## What The User Should Label

Fill these fields in `manual_samples_prefilled.csv`:
- `user_grade`
- `reaction_quality`
- `candle_anatomy_quality`
- `avoid_reason`
- `user_reasoning`
- `manual_trade_taken`

Allowed user grades:
- `A_PLUS`
- `A`
- `B`
- `C`
- `NO_TRADE`
- `INVALID`
- `UNCERTAIN`

## Later Use

After the user fills the CSV, a later Strategy 2-only branch can compare labeled A+/A samples against the automatic body/tail pool and test whether the descriptive hypotheses match the trader's actual discretionary logic.

Next Strategy 2-only branch:

`feat/strategy-2-manual-sample-profile-comparison`

