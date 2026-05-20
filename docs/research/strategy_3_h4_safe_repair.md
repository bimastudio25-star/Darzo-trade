# Strategy 3 H4 Safe Repair

## Problem

Strategy 3 paper validation was blocked because local H4 context was stale and quarantined:

- local H4 latest: `2026-05-19T00:00:00+00:00`
- expected/MT5 latest closed H4: `2026-05-20T16:00:00+00:00`
- stale_by_bars: `10`
- scanner status: `STRATEGY_3_SCANNER_BLOCKED_STALE_HTF_CONTEXT`
- `paper_signals_clean_for_validation`: `false`

The H4 file format matters. `data/XAUUSD/H4.csv` is UTF-16, comma-separated, and has no canonical header row. The repair therefore preserves UTF-16/no-header layout and the existing column order:

`time, open, high, low, close, tick_volume, spread`

## Why Repair Is Narrow

The prior diagnostic found:

- overlap count: `288`
- OHLC match rate: `0.9965`
- OHLC matches: `287/288`
- single material OHLC conflict: `2026-05-19T00:00:00+00:00`
- worst OHLC diff: `19.18`
- best timezone shift: `0h`
- timezone shift suspected: `false`
- MT5 H4 has closed candles through `2026-05-20T16:00:00+00:00`

This supports a narrow repair only if safety checks pass:

- replace exactly the conflict row
- append only missing closed H4 bars after the local latest timestamp
- create backup before apply
- never change Strategy 3 logic

## Repair Method

Dry-run:

```powershell
python scripts/repair_strategy_3_h4_data.py --symbol XAUUSD --data-dir data --diagnostic-dir backtests/reports/strategy_3_h4_data_source_diagnostic --output-dir backtests/reports/strategy_3_h4_safe_repair --dry-run
```

Apply, only after dry-run passes:

```powershell
python scripts/repair_strategy_3_h4_data.py --symbol XAUUSD --data-dir data --diagnostic-dir backtests/reports/strategy_3_h4_data_source_diagnostic --output-dir backtests/reports/strategy_3_h4_safe_repair --apply
```

The script writes:

- `h4_repair_report.json`
- `h4_repair_report.md`
- `H4.repaired_candidate.csv`
- `h4_repair_diff.csv`

Apply mode backs up:

`data/XAUUSD/H4.csv.backup.<timestamp>`

## Safety Checks

The repair aborts if:

- OHLC match rate is below `0.99`
- more than one material OHLC mismatch exists
- material mismatch timestamp is not the expected conflict timestamp
- timezone shift is suspected
- MT5 H4 is not fresher than local H4
- candidate H4 has duplicates, non-monotonic timestamps, or invalid OHLC
- local H4 has duplicates, non-monotonic timestamps, or invalid OHLC
- the MT5 candidate lacks the conflict timestamp
- there are no missing closed H4 bars to append

## Result

Dry-run result:

- status: `DRY_RUN_REPAIR_CANDIDATE_CREATED`
- safety checks: passed
- rows replaced: `1`
- rows appended: `10`
- old latest H4: `2026-05-19T00:00:00+00:00`
- candidate latest H4: `2026-05-20T16:00:00+00:00`

Apply result:

- status: `REPAIR_APPLIED_H4_FRESH`
- backup: `data/XAUUSD/H4.csv.backup.20260520T222909Z`
- rows replaced: `1`
- rows appended: `10`
- new latest H4: `2026-05-20T16:00:00+00:00`
- preserved format: UTF-16, no header
- post-repair freshness: `fresh`
- scanner blocked: `false`
- `paper_signals_clean_for_validation`: `true`

Post-repair H4 diagnostic:

- OHLC overlap count: `298`
- OHLC match rate: `1.0`
- OHLCV match rate: `0.0369`
- mismatch type: `volume_only`
- timezone shift suspected: `false`

Pipeline smoke:

- verdict: `LOCAL_PIPELINE_OK`
- H4 freshness: `fresh`
- H4 stale_by_bars: `0`
- scanner blocked: `false`
- new paper signals this run: `2`
- paper signals total after run: `64`

The detailed repair report is written in:

`backtests/reports/strategy_3_h4_safe_repair/h4_repair_report.md`

Post-repair validation must be checked with:

```powershell
python scripts/diagnose_strategy_3_h4_data_source.py --symbol XAUUSD --symbol-broker XAUUSD --data-dir data --output-dir backtests/reports/strategy_3_h4_data_source_diagnostic_post_repair --lookback-bars 300 --dry-run
```

If H4 is fresh and overlap-safe, the scanner can resume via the existing freshness logic. If not, scanner remains blocked.

## Safety

- no Strategy 3 logic changes
- no VWAP/sigma/cooldown changes
- no Strategy 2 changes
- no Adelin changes
- no live trading
- no Telegram
- no orders
- no broker execution
- no `order_send`

## Next Step

If H4 is fresh after repair:

`feat/strategy-3-paper-signals-comparison-post-fix`

If H4 remains blocked:

manual H4 data-source review or alternative H4 source branch.
