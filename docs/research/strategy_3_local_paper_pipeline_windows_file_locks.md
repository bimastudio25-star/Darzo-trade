# Strategy 3 Local Paper Pipeline Windows File Locks

Status: operational reliability fix only. No Strategy 3 signal logic changed.

## Problem

The loop/apply pipeline hit a Windows replace failure:

`PermissionError: [WinError 5] Accesso negato: 'data\\XAUUSD\\M5.csv.tmp' -> 'data\\XAUUSD\\M5.csv'`

Typical causes on Windows:

- the CSV is open in Excel or a VSCode preview;
- another Python pipeline instance is still running;
- OneDrive sync temporarily locked the file;
- antivirus or indexing briefly locked the file;
- the target file is read-only.

## Fix

The ingestion writer now uses:

- unique temp files such as `M5.csv.<pid>.<timestamp>.<id>.tmp`;
- write + flush + fsync before replacement;
- atomic `os.replace`;
- retry/backoff on `PermissionError` or WinError 5;
- default 8 replace attempts;
- initial sleep 0.25s;
- max sleep 2.0s;
- structured `CsvReplacePermissionError` if the replace remains locked.

If replacement still fails:

- the original target CSV is left untouched;
- the temp file is preserved for debugging;
- ingestion reports `INGESTION_FILE_LOCKED`, `FILE_LOCKED_DURING_REPLACE`, and `PARTIAL_APPLY_FAILED`;
- pipeline reports `LOCAL_PIPELINE_FILE_LOCKED_RETRY_NEXT_LOOP`;
- scanner is skipped for that cycle.

Loop mode does not crash the whole process for this condition. It records the failed cycle and retries on the next interval.

## Single-Instance Guard

Loop mode writes:

`backtests/reports/strategy_3_local_paper_pipeline/pipeline.lock`

If a lock file already exists, the pipeline exits with `DUPLICATE_PIPELINE_LOCK_DETECTED` unless `--force-pipeline-lock` is used. Use force only after confirming no other pipeline process is running.

PowerShell wrapper:

```powershell
.\scripts\run_strategy_3_local_paper_pipeline.ps1 -Symbol XAUUSD -SymbolBroker XAUUSD -Loop -IntervalMinutes 15 -Apply -ForcePipelineLock
```

## OneDrive Warning

Because the repository is under OneDrive, pipeline summaries include:

`ONEDRIVE_PATH_FILE_LOCK_RISK`

This is warning-only. It does not fail the pipeline. For overnight runs, consider pausing OneDrive sync or moving repo/data outside OneDrive.

## Recovery Commands

Check duplicate Python/pipeline processes:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match "python|run_strategy_3_local_paper_pipeline|strategy_3" } |
  Select-Object ProcessId, CommandLine
```

Clear read-only flag:

```powershell
attrib -R data\XAUUSD\M5.csv
```

Operational advice:

- close Excel or CSV previews;
- close VSCode preview tabs on `data/XAUUSD/*.csv`;
- stop duplicate Python pipeline processes;
- pause OneDrive sync while the pipeline runs;
- avoid opening candle CSVs during apply cycles.

## Safety

- no Strategy 3 entry logic changes
- no VWAP changes
- no sigma-band changes
- no cooldown changes
- no Strategy 2 changes
- no Adelin changes
- no live trading
- no Telegram trade alerts
- no broker execution
- no `order_send`
