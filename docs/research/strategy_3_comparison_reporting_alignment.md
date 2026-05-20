# Strategy 3 Comparison Reporting Alignment

Status: infrastructure/reporting alignment only. Strategy 3 remains paper-only.

## Context

The post-H4-repair comparison found:

- all-detected match rate: `92.31%`
- accepted-only match rate: `93.10%`
- verdict: `SHADOW_BACKTEST_MINOR_MISMATCHES`

Runtime comparison diagnostics then showed the mismatch source was not a proven Strategy 3 logic divergence. The likely root cause was data-context contamination:

- paper signals were generated before the H4 safe repair
- backtest signals were regenerated after the H4 safe repair
- H4 was fresh at comparison time, but older paper rows did not carry a data-context fingerprint

That meant the comparison could not automatically know whether paper and backtest used the same underlying data files.

## Purpose

This branch adds data-context versioning to prevent contaminated comparisons from being treated as clean validation.

A paper-vs-backtest comparison is clean only when:

- paper signals contain a data-context hash
- the current backtest data context hash matches it
- H4/HTF freshness remains clean
- accepted-only match rate meets the configured threshold

## Data-Context Method

The utility is:

`scripts/strategy_3_data_context.py`

For XAUUSD Strategy 3 it hashes and summarizes:

- `M1`
- `M5`
- `M15`
- `H1`
- `H4`
- `D1`

For every timeframe file it records:

- file path
- exists
- file size
- raw SHA-256 hash
- row count if parseable
- first timestamp if parseable
- latest timestamp if parseable
- detected encoding
- header presence
- parse warnings

The combined context hash is built from stable per-timeframe file metadata and raw file hashes. Raw bytes are hashed, so UTF-16/no-header H4 changes are visible even if parsing still succeeds.

## Scanner Metadata

`scripts/run_strategy_3_paper_shadow_scanner.py` now writes:

- `data_context` in `scanner_summary.json`
- `data_context_hash` in `scanner_summary.json`
- sidecar `paper_signals_data_context.json`
- per-signal fields:
  - `data_context_hash`
  - `h4_hash`
  - `h4_latest_timestamp`
  - `m15_hash`
  - `m15_latest_timestamp`

The scanner remains dry-run/paper-only.

## Comparison Metadata

`scripts/compare_strategy_3_paper_vs_backtest.py` now:

1. Loads paper data context from scanner summary or sidecar.
2. Computes current backtest data context from `data/XAUUSD`.
3. Compares paper and backtest hashes.
4. Writes:
   - `data_context_paper.json` when available
   - `data_context_backtest.json`
   - `data_context_diff.json`
5. Blocks clean validation if context is missing or mismatched.

If paper context is missing, the comparison still runs as diagnostics but emits:

- `DATA_CONTEXT_MISSING`
- `COMPARISON_NOT_CLEAN_VALIDATION`

If paper and backtest context differ, it emits:

- `DATA_CONTEXT_MISMATCH`
- `COMPARISON_NOT_CLEAN_VALIDATION`
- `PRE_REPAIR_DATA_CONTEXT_CONTAMINATION_POSSIBLE`

`--allow-data-context-mismatch` keeps the comparison diagnostic-only. It does not convert a mismatched context into clean validation.

## Current Dry-Run Result

Command:

```powershell
python scripts/compare_strategy_3_paper_vs_backtest.py --symbol XAUUSD --data-dir data --paper-signals-path backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv --scanner-summary-path backtests/reports/strategy_3_paper_shadow_scanner/scanner_summary.json --pipeline-summary-path backtests/reports/strategy_3_local_paper_pipeline/pipeline_summary.json --output-dir backtests/reports/strategy_3_shadow_vs_backtest_comparison_reporting_alignment --cooldown-minutes 120 --timestamp-tolerance-seconds 0 --price-tolerance 0.01 --dry-run
```

Result:

- existing paper data context: missing
- backtest data context hash: created
- data_context_match: `false`
- data_context_missing: `true`
- clean validation verdict: blocked

Verdict flags:

- `DATA_CONTEXT_MISSING`
- `COMPARISON_NOT_CLEAN_VALIDATION`
- `PAPER_SIGNALS_NOT_CLEAN_FOR_VALIDATION`
- `SHADOW_BACKTEST_MINOR_MISMATCHES`
- `NO_LIVE_DEPLOYMENT_DECISION`
- `STRATEGY_3_REMAINS_PAPER_ONLY`

## Scanner Smoke

The alignment smoke scanner wrote data context successfully under:

`backtests/reports/strategy_3_paper_shadow_scanner_alignment_smoke`

Result:

- data_context_hash present
- sidecar `paper_signals_data_context.json` present
- H4 fresh
- paper_signals_clean_for_validation: `true`
- no live, no Telegram, no orders

## Safety

- no Strategy 3 entry logic changes
- no VWAP changes
- no sigma band changes
- no cooldown value or logic changes
- no live trading
- no Telegram
- no orders
- no broker execution

## Next Step

Continue accumulating new paper signals after H4 repair. Rerun comparison only when the paper signal set has a matching data context or when the report explicitly segments legacy/pre-repair rows away from clean validation metrics.

Do not proceed to spread/slippage modeling until a clean, data-context-matched comparison reaches the required threshold.
