# Strategy 3 H4 Data Source Diagnostic

## Problem

Strategy 3 paper validation is paused because H4 is stale and quarantined.

Current observed state:

- local H4 latest: `2026-05-19T00:00:00+00:00`
- expected latest closed H4: `2026-05-20T16:00:00+00:00`
- stale_by_bars: `10`
- scanner verdict: `STRATEGY_3_SCANNER_BLOCKED_STALE_HTF_CONTEXT`
- `paper_signals_clean_for_validation`: `false`

## Why This Matters

Strategy 3 uses D1/H4/H1 context in the paper scanner path. If H4 remains stale, paper-vs-backtest comparison can falsely pass because both paths may consume the same stale H4 file. Paper signals must not be treated as clean validation evidence until H4 is fresh and overlap-safe.

## Diagnostic Method

The diagnostic script compares local `data/XAUUSD/H4.csv` against read-only MT5 H4 candles for the broker symbol.

Command:

```powershell
python scripts/diagnose_strategy_3_h4_data_source.py --symbol XAUUSD --symbol-broker XAUUSD --data-dir data --output-dir backtests/reports/strategy_3_h4_data_source_diagnostic --lookback-bars 300 --dry-run
```

The script:

- loads local H4
- fetches H4 from MT5
- removes forming candles by default
- compares OHLC separately from tick volume/spread
- tests timezone shifts from -3h to +3h
- writes candidate files under reports only
- does not modify `data/XAUUSD/H4.csv` unless `--apply-rebuild` is explicitly passed and the recommendation is apply-safe

## Results

Dry-run result with 300 MT5 H4 bars:

- local rows: `1870`
- local latest: `2026-05-19T00:00:00+00:00`
- MT5 raw rows: `300`
- MT5 closed rows: `298`
- MT5 latest closed: `2026-05-20T16:00:00+00:00`
- forming candles removed: `2`
- overlap count: `288`
- OHLC match count: `287`
- OHLC match rate: `0.9965`
- OHLCV match rate: `0.0`
- first OHLC mismatch: `2026-05-19T00:00:00+00:00`
- worst OHLC diff: `19.18`
- worst OHLC diff timestamp: `2026-05-19T00:00:00+00:00`
- best timezone shift: `0`
- best shift match rate: `0.9965`
- timezone shift suspected: `false`

Interpretation:

- H4 timestamps are aligned to 4-hour UTC boundaries.
- MT5 history is sufficient for diagnosis.
- The mismatch is not caused by H4 forming candles.
- The mismatch is not a timezone/boundary shift.
- Most overlap OHLC matches, but one closed H4 candle has a material OHLC conflict at `2026-05-19T00:00:00+00:00`.
- OHLCV mismatch rate is 100% because local older rows often have spread `0` while MT5 has spread `4`; that is not the blocking issue.

## Recommendation

`MT5_H4_SOURCE_MISMATCH_MANUAL_REVIEW`

No automatic H4 repair was applied.

Candidate files were written for inspection:

- `backtests/reports/strategy_3_h4_data_source_diagnostic/h4_mt5_candidate.csv`
- `backtests/reports/strategy_3_h4_data_source_diagnostic/h4_append_candidate.csv`
- `backtests/reports/strategy_3_h4_data_source_diagnostic/h4_overlap_mismatches.csv`
- `backtests/reports/strategy_3_h4_data_source_diagnostic/h4_data_source_diagnostic.json`
- `backtests/reports/strategy_3_h4_data_source_diagnostic/h4_data_source_diagnostic.md`

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
- no `data/XAUUSD/H4.csv` rewrite

## Decision Matrix

| Outcome | Next branch |
|---|---|
| `LOCAL_H4_STALE_APPEND_SAFE` | apply append with backup branch |
| `LOCAL_H4_CORRUPT_REBUILD_CANDIDATE` | manual review candidate, then rebuild branch |
| `VOLUME_ONLY_MISMATCH_RELAX_VOLUME_OVERLAP` | adjust overlap validation safely |
| `TIMEZONE_BOUNDARY_MISMATCH` | fix timestamp normalization branch |
| `MT5_H4_SOURCE_MISMATCH_MANUAL_REVIEW` | inspect broker/feed manually |
| `INSUFFICIENT_MT5_HISTORY` | increase lookback/history download |
| `DO_NOT_RECOVER_UNSAFE` | keep scanner blocked |

## Next Step

Keep Strategy 3 paper validation blocked. Manually inspect the single material H4 conflict at `2026-05-19T00:00:00+00:00` before any H4 append/rebuild branch.
