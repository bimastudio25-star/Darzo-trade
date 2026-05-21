# Strategy 3 Data Ingestion Pipeline

Status: data infrastructure only. This branch does not make Strategy 3 live.

## Context

Strategy 3 scanner and shadow-vs-backtest comparison frameworks are ready, but local XAUUSD data currently ends at:

- M1: `2026-05-14T22:59:00+00:00`
- M5: `2026-05-14T22:55:00+00:00`
- M15: `2026-05-14T22:45:00+00:00`
- H1: `2026-05-14T22:00:00+00:00`
- H4: `2026-05-14T20:00:00+00:00`
- D1: `2026-05-14T00:00:00+00:00`

The paper scanner currently has 0 paper signals because it keeps evaluating the same latest candle. The bottleneck is fresh data availability.

## Purpose

The goal is to safely append fresh XAUUSD candles into:

- `data/XAUUSD/M1.csv`
- `data/XAUUSD/M5.csv`
- `data/XAUUSD/M15.csv`
- `data/XAUUSD/H1.csv`
- `data/XAUUSD/H4.csv`
- `data/XAUUSD/D1.csv`

The pipeline audits, validates, merges, deduplicates, sorts, backs up, and reports changes before any paper scanner rerun.

## Why Not Fake Historical Accumulation

Running the paper scanner historically over old data and comparing it to backtest output would be trivially close to 100% if both paths call the same Strategy 3 code. That does not validate incremental runtime behavior.

The real value comes from:

- fresh data arriving incrementally
- scanner observing the latest state
- paper signals accumulating over time
- later comparison checking whether runtime/shadow behavior matches backtest behavior

## Supported Workflow

Step A - Audit current data:

```powershell
python scripts/audit_xauusd_data.py --data-dir data --symbol XAUUSD --timeframes M1,M5,M15,H1,H4,D1 --output-dir backtests/reports/strategy_3_data_ingestion
```

Step B - Put broker-exported CSVs into:

```text
incoming_data/XAUUSD/
```

Accepted filenames:

- `M1.csv`, `M5.csv`, `M15.csv`, `H1.csv`, `H4.csv`, `D1.csv`
- `XAUUSD_M1.csv`, `XAUUSD_M5.csv`, `XAUUSD_M15.csv`, `XAUUSD_H1.csv`, `XAUUSD_H4.csv`, `XAUUSD_D1.csv`

Step C - Dry-run import:

```powershell
python scripts/import_xauusd_candles.py --source-dir incoming_data/XAUUSD --data-dir data --symbol XAUUSD --timeframes M1,M5,M15,H1,H4,D1 --output-dir backtests/reports/strategy_3_data_ingestion --backup --dry-run
```

Step D - Apply only after dry-run OK:

```powershell
python scripts/import_xauusd_candles.py --source-dir incoming_data/XAUUSD --data-dir data --symbol XAUUSD --timeframes M1,M5,M15,H1,H4,D1 --output-dir backtests/reports/strategy_3_data_ingestion --backup --apply
```

Step E - Run paper scanner:

```powershell
python scripts/run_strategy_3_paper_shadow_scanner.py --symbol XAUUSD --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_3_paper_shadow_scanner --cooldown-minutes 120 --dry-run
```

Step F - When 10-20 paper signals exist, rerun comparison:

```powershell
python scripts/compare_strategy_3_shadow_vs_backtest.py --paper-dir backtests/reports/strategy_3_paper_shadow_scanner --data-dir data --output-dir backtests/reports/strategy_3_shadow_vs_backtest_comparison --symbol XAUUSD --strategy strategy_3_vwap_1r --cooldown-minutes 120 --price-tolerance-usd 0.01 --timestamp-tolerance-seconds 0
```

## Safety

- no live trading
- no orders
- no Telegram
- no broker execution
- data-only pipeline
- dry-run by default unless `--apply` is explicitly passed
- apply mode creates backups by default unless `--no-backup` is explicitly passed
- duplicate timestamps keep existing rows by default
- incoming duplicates replace existing rows only with `--prefer-incoming`
- optional paper scanner rerun is off by default and must be explicitly requested with `--run-paper-scanner-after-ingest`

## Data Validation

The pipeline validates:

- duplicate timestamps
- monotonic timestamp order
- gaps versus timeframe interval
- missing OHLC values
- invalid OHLC rows:
  - high < low
  - open outside high/low
  - close outside high/low
- row count changes
- schema compatibility

Current project schema is preserved:

```text
time, open, high, low, close, tick_volume, spread
```

The local MT5-style files are headerless UTF-16 CSVs. Intraday timestamps use `yyyy.MM.dd HH:mm`; D1 uses `yyyy.MM.dd`.

## Output Files

Audit:

- `backtests/reports/strategy_3_data_ingestion/audit_summary.json`
- `backtests/reports/strategy_3_data_ingestion/audit_report.md`

Import:

- `backtests/reports/strategy_3_data_ingestion/ingestion_summary.json`
- `backtests/reports/strategy_3_data_ingestion/ingestion_report.md`

Backups after apply:

- `data_backups/XAUUSD/<timestamp>/<TF>.csv`

## Smoke Results

Audit smoke was run read-only:

- verdict: `DATA_AUDIT_WARNINGS`, `GAPS_DETECTED`
- duplicates: 0 on all TFs
- non-monotonic timestamps: 0 on all TFs
- invalid OHLC rows: 0 on all TFs
- latest common timestamp: `2026-05-14T00:00:00+00:00`

The gap warnings are expected for market closures/weekends and should be reviewed, not automatically treated as corruption.

Import dry-run smoke was run with `incoming_data/XAUUSD` absent:

- verdict: `INGESTION_DRY_RUN_OK`
- `INCOMING_DATA_MISSING`
- `NO_NEW_ROWS_FOUND`
- rows that would be added: 0
- data files modified: no

## Next Step After Successful Ingestion

1. Rerun audit.
2. Rerun paper scanner.
3. Accumulate 10-20 real paper signals.
4. Rerun shadow-vs-backtest comparison.
5. If match >= 95%, proceed to:

```text
feat/strategy-3-spread-slippage-model
```

## Deployment Warning

This branch solves the data availability bottleneck only. It does not make Strategy 3 live, deployable, or production-ready.
