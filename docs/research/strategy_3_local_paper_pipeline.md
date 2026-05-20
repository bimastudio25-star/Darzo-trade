# Strategy 3 Local Paper Pipeline

Status: data/paper infrastructure only. This branch does not make Strategy 3 live, deployable, or execution-enabled.

## Purpose

The pipeline automates the boring but critical path needed to accumulate real Strategy 3 paper observations:

MT5 terminal -> Python MT5 collector -> `incoming_data/XAUUSD` -> import dry-run/apply -> data audit -> incremental paper scanner -> `paper_signals.csv`

It removes the manual CSV export bottleneck. It does not change Strategy 3 and does not validate edge by itself.

## Requirements

- MT5 terminal installed.
- MT5 terminal open.
- Account logged in.
- XAUUSD, or the broker-specific gold symbol, visible in Market Watch.
- Python package installed if local MT5 fetching is used:

```powershell
pip install MetaTrader5
```

## Broker Symbol Mapping

The project symbol remains `XAUUSD`. The broker symbol can differ:

```powershell
python scripts/fetch_xauusd_mt5_candles.py --symbol XAUUSD --symbol-broker XAUUSD --timeframes M1,M5,M15,H1,H4,D1 --output-dir incoming_data/XAUUSD --days-back 7 --dry-run
python scripts/fetch_xauusd_mt5_candles.py --symbol XAUUSD --symbol-broker XAUUSDm --timeframes M1,M5,M15,H1,H4,D1 --output-dir incoming_data/XAUUSD --days-back 7 --dry-run
python scripts/fetch_xauusd_mt5_candles.py --symbol XAUUSD --symbol-broker GOLD# --timeframes M1,M5,M15,H1,H4,D1 --output-dir incoming_data/XAUUSD --days-back 7 --dry-run
```

If symbol selection fails, the collector reports matching XAU/GOLD suggestions instead of silently falling back.

## Timezone Warnings

MT5 server timestamps can differ from UTC. The collector converts MT5 epoch timestamps to UTC and blocks writes when fetched bars are more than five minutes in the future, unless `--allow-timezone-warning` is explicitly passed.

This protects the later shadow-vs-backtest comparison from shifted candles.

## Closed-Candle Import

The MT5 collector imports closed candles only by default. A candle is considered closed when:

`candle_open_time + timeframe_duration <= now_utc - grace_seconds`

The default grace is five seconds. Current forming candles are skipped before overlap validation and before writing incoming CSVs.

This matters especially for higher timeframes:

- the current H4 candle can change for up to four hours;
- the current D1 candle can change all day;
- comparing those forming OHLC values against local historical CSVs can produce false overlap failures.

When a mismatch exists only on skipped forming candles, the collector records it as non-blocking:

- `FORMING_CANDLES_SKIPPED`
- `OVERLAP_MATCH_100_CLOSED_CANDLES`
- `HTF_FORMING_CANDLE_MISMATCH_IGNORED`

Use `--include-forming-candles` only for manual debugging. It should not be used for paper accumulation.

## Overlap Validation

Fetched MT5 candles are compared against the existing local `data/XAUUSD/<TF>.csv` files over the last 24 hours before the existing latest timestamp.

- 100% match: safe.
- >= 95% match: warning, still usable.
- < 95% match: blocked unless `--allow-overlap-mismatch` is explicitly passed.
- no overlap: warning only, useful for first fetches or data gaps.

Default OHLC tolerance is `0.10` USD.

Overlap validation is based on closed candles only by default. Current H4/D1 candles are intentionally ignored until they close, so lower-timeframe closed candles can continue advancing the paper scanner.

## Days-Back Safety

- Default: `--days-back 7`.
- More than 30 days: warning.
- More than 90 days: requires `--allow-large-fetch`.
- More than 365 days: refused.

This avoids accidental heavy M1 pulls from MT5.

## Safe First Manual Workflow

Step 1, collector dry-run:

```powershell
python scripts/fetch_xauusd_mt5_candles.py --symbol XAUUSD --symbol-broker XAUUSD --timeframes M1,M5,M15,H1,H4,D1 --output-dir incoming_data/XAUUSD --days-back 7 --dry-run
```

Step 2, write incoming CSVs only after dry-run is sane:

```powershell
python scripts/fetch_xauusd_mt5_candles.py --symbol XAUUSD --symbol-broker XAUUSD --timeframes M1,M5,M15,H1,H4,D1 --output-dir incoming_data/XAUUSD --days-back 7 --write
```

Step 3, import dry-run:

```powershell
python scripts/import_xauusd_candles.py --source-dir incoming_data/XAUUSD --data-dir data --symbol XAUUSD --timeframes M1,M5,M15,H1,H4,D1 --output-dir backtests/reports/strategy_3_data_ingestion --backup --dry-run
```

Step 4, apply only after reading the dry-run report:

```powershell
python scripts/import_xauusd_candles.py --source-dir incoming_data/XAUUSD --data-dir data --symbol XAUUSD --timeframes M1,M5,M15,H1,H4,D1 --output-dir backtests/reports/strategy_3_data_ingestion --backup --apply
```

Step 5, audit:

```powershell
python scripts/audit_xauusd_data.py --data-dir data --symbol XAUUSD --timeframes M1,M5,M15,H1,H4,D1 --output-dir backtests/reports/strategy_3_data_ingestion
```

Step 6, incremental paper scanner:

```powershell
python scripts/run_strategy_3_paper_shadow_scanner.py --symbol XAUUSD --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_3_paper_shadow_scanner --cooldown-minutes 120 --dry-run --incremental
```

For the first incremental run, if no scanner state exists yet, initialize with the known checkpoint:

```powershell
python scripts/run_strategy_3_paper_shadow_scanner.py --symbol XAUUSD --timeframes M1,M5,M15,H1,H4,D1 --data-dir data --output-dir backtests/reports/strategy_3_paper_shadow_scanner --cooldown-minutes 120 --dry-run --incremental --from-timestamp 2026-05-14T22:45:00+00:00
```

## One-Command Local Pipeline

Safe no-apply:

```powershell
python scripts/run_strategy_3_local_paper_pipeline.py --symbol XAUUSD --symbol-broker XAUUSD --once --no-apply
```

One run with apply after manual validation:

```powershell
python scripts/run_strategy_3_local_paper_pipeline.py --symbol XAUUSD --symbol-broker XAUUSD --once --apply
```

Overnight loop after the first manual cycle is trusted:

```powershell
python scripts/run_strategy_3_local_paper_pipeline.py --symbol XAUUSD --symbol-broker XAUUSD --loop --interval-minutes 15 --apply
```

PowerShell wrapper:

```powershell
.\scripts\run_strategy_3_local_paper_pipeline.ps1 -Symbol XAUUSD -SymbolBroker XAUUSD -Loop -IntervalMinutes 15 -Apply
```

## HTF Freshness Gate

Strategy 3 uses D1/H4/H1 context. The pipeline now writes an H4 quarantine diagnostic and the paper scanner blocks clean Strategy 3 paper signals when H4 is stale or quarantined.

D1 can legitimately lag by one day while the current daily candle is forming. H4 should normally advance to the latest completed 4-hour candle. If H4 remains stale, scanner output is marked:

`STRATEGY_3_SCANNER_BLOCKED_STALE_HTF_CONTEXT`

Reports:

- `backtests/reports/strategy_3_h4_quarantine_diagnostic/h4_quarantine_report.json`
- `backtests/reports/strategy_3_h4_quarantine_diagnostic/h4_quarantine_report.md`

Do not treat paper signals as clean validation evidence while `paper_signals_clean_for_validation` is false.

## What Adelin Must Leave Open

- MT5 terminal open.
- Account logged in.
- PC awake.
- Terminal running.
- No sleep mode.

## What To Send Next Day

- `backtests/reports/strategy_3_local_paper_pipeline/pipeline_run.md`
- `backtests/reports/strategy_3_local_paper_pipeline/pipeline_summary.json`
- `backtests/reports/strategy_3_data_ingestion/ingestion_report.md`
- `backtests/reports/strategy_3_data_ingestion/audit_report.md`
- `backtests/reports/strategy_3_paper_shadow_scanner/scanner_run.md`
- `backtests/reports/strategy_3_paper_shadow_scanner/scanner_state.json`
- `backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv`

## Safety

- data-only collection
- no `mt5.order_send`
- no broker execution
- no Telegram trade signals
- no live trading
- no Strategy 3 changes
- no cooldown changes
- no VWAP or sigma-band changes
- no spread/slippage model in this branch

## Next Steps

After 10-20 real paper signals:

```powershell
python scripts/compare_strategy_3_shadow_vs_backtest.py --paper-dir backtests/reports/strategy_3_paper_shadow_scanner --data-dir data --output-dir backtests/reports/strategy_3_shadow_vs_backtest_comparison --symbol XAUUSD --strategy strategy_3_vwap_1r --cooldown-minutes 120 --price-tolerance-usd 0.01 --timestamp-tolerance-seconds 0
```

If match rate is at least 95%, proceed to:

`feat/strategy-3-spread-slippage-model`

Only much later, after spread/slippage and paper observation pass, should Telegram paper alerts or broker/micro-live work be considered.
