# Adelin v2 Operational Audit Foundation

Status: research-only. This document describes the audit foundation added for Adelin v2 and records the initial smoke result from this branch.

## 1. What Was Built

This branch adds:

- `docs/research/adelin_v2_operational_spec.md`, the formal Adelin v2 operating definition.
- `dazro_trade/analytics/adelin_v2_operational_audit.py`, an import-safe research label model and classifier.
- `scripts/analyze_adelin_v2_operational_audit.py`, a CLI script that reads old Adelin exports and writes CSV/JSON/markdown diagnostics.
- `tests/test_adelin_v2_operational_audit.py`, focused tests for classifier behavior, script output, strategy filtering, and import safety.

The audit output path is `backtests/reports/adelin_v2_operational_audit`.

## 2. Why Old Adelin Is Not Being Re-Enabled

Old Adelin remains research-only because the old score was not predictive, continuation entries were toxic, and rejection-only evidence was not robust enough out of sample.

This branch does not change live settings, does not enable Telegram signals, and does not add any broker/order execution path.

## 3. What Adelin v2 Really Means

Adelin v2 is a multi-timeframe liquidity reaction reversal model on XAUUSD.

It is not the same thing as the old Strategy 1 implementation and not a simple H1 high/low sweep model. The intended setup requires meaningful liquidity to be taken into a valid reaction zone, with multi-timeframe context and a feasible tight stop. The target is next liquidity or the next likely reaction/reversal area.

## 4. What The Audit Can Classify Now

Using only fields available in an old export, the first audit can classify:

- old continuation rows as `NO_TRADE_CONTINUATION_BLOCKED`,
- missing v2 context as `UNKNOWN_INSUFFICIENT_DATA`,
- stop distances over 40 pips as too wide,
- rejection non-continuation rows as visual-review candidates, not A+ trades,
- number-theory confluence near levels ending in 0 using a conservative default threshold of 5 pips,
- Strategy 2 and Strategy 3 rows as non-target rows when a mixed export has strategy fields.

## 5. What The Audit Cannot Classify Yet

Existing historical Adelin exports do not contain enough context to fully classify Adelin v2 logic. This audit is a structural gap analysis, not final validation.

The audit cannot fully validate:

- HTF and LTF internal/external liquidity alignment,
- whether liquidity was shallow or deep,
- whether a reaction zone was pre-existing and valid,
- volume crack or volume profile context unless exported,
- gap contamination unless exported,
- news/spread/slippage execution quality,
- post-entry reaction, accumulation, or M1 engulfing behavior unless exported.

Missing evidence remains a limitation. It is not converted into confidence.

## 6. Smoke / Audit Run

Command executed:

```powershell
python scripts/analyze_adelin_v2_operational_audit.py --symbol XAUUSD --data-dir data --trades-path backtests/reports/final/executed_trades.csv --output-dir backtests/reports/adelin_v2_operational_audit --dry-run
```

Result:

- `backtests/reports/final/executed_trades.csv` was not present in this branch worktree.
- trades loaded: `0`
- trades audited: `0`
- continuation blocked count: `0`
- unknown/missing context count: `0`
- reversal candidates count: `0`
- key limitations: `TRADE_EXPORT_PATH_MISSING`, `NO_ADELIN_TRADES_AUDITED`

Files written:

- `backtests/reports/adelin_v2_operational_audit/adelin_v2_trade_audit.csv`
- `backtests/reports/adelin_v2_operational_audit/adelin_v2_audit_summary.json`
- `backtests/reports/adelin_v2_operational_audit/adelin_v2_operational_audit.md`

## 7. Why Continuation Remains Blocked

The old continuation mode is treated as toxic. The v2 continuation exception is rare and requires a future IFVG-specific research module:

- price already took liquidity and reversed,
- uncollected liquidity remains,
- price fails or absorbs before the target,
- price retests an IFVG,
- continuation may be considered toward missed liquidity.

That exception is not implemented as an active signal in this branch.

## 8. Why No Live Deployment Is Allowed

This branch only creates the operational definition and first structural audit. It does not show profitability, deployability, execution quality, or live safety.

Before any live discussion, Adelin v2 needs visual examples, v2-specific labels, bounded backtests, paper shadow validation, and a spread/slippage/news model.

## 9. Next Steps

Recommended next branches:

- `feat/adelin-v2-visual-review-pack`
- `feat/adelin-v2-reaction-zone-detectors`
- `feat/adelin-v2-liquidity-context-detectors`
- `feat/adelin-v2-paper-shadow-scanner`

Do not implement those in this branch.
