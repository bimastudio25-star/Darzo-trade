# Adelin v2 Operational Audit

Status: research-only structural gap analysis.

Existing historical Adelin exports do not contain enough context to fully classify Adelin v2 logic. This audit is a structural gap analysis, not final validation.

## Scope

- No live strategy was created.
- No broker/order execution path was called.
- No Telegram signal path was called.
- Strategy 2, Strategy 3, VWAP, and market data are not modified by this script.
- `--dry-run` keeps this first version structural and disables any market-data enrichment.

## Source

- source_path: `backtests\reports\final\executed_trades.csv`
- source_selection: `explicit_trades_path`
- source_exists: `False`
- source_rows_loaded: `0`

## Summary

- total_old_adelin_trades_loaded: `0`
- trades_audited: `0`
- continuation_blocked_count: `0`
- unknown_insufficient_data_count: `0`
- possible_reversal_count: `0`
- dirty_reversal_count: `0`
- number_theory_confluence_count: `0`
- reaction_zone_available_count: `0`

## Data Limitations

- `NO_ADELIN_TRADES_AUDITED`
- `TRADE_EXPORT_PATH_MISSING`

## Sample Classifications

| trade_id | time | direction | label | reasons | limitations |
|---|---|---|---|---|---|
| | | | no Adelin rows audited | | |

## Interpretation

This output should be used to decide what evidence is missing from historical exports and visual-review packs. It is not a profitability claim and it does not make Adelin deployable.
