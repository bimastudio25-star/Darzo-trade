# Adelin v2 Manual Trade Evidence Schema

## Context

Manual screenshots and discretionary trade examples can help identify concepts that Adelin v2 does not yet measure well. Recent human examples around XAUUSD/XAGUSD include M1 entries, tight stops, sweep/reaction behavior, volume profile and liquidity zones, swing high/low concepts, HTF/LTF levels, and possible fast reaction or failure examples.

These examples are useful as qualitative manual evidence only. They are not validation data and must not be used to claim edge, profitability, deployability, or Phase 4 readiness.

## Purpose

The purpose of this schema is to collect manual examples consistently before any future qualitative comparison with Adelin v2 candidates.

The template records:

- screenshot identity and source context;
- manual trade fields, if visible;
- liquidity, swing, volume profile, round-level, FVG/iFVG, target-space, and reaction context;
- human reasoning and discretionary notes;
- confidence and evidence quality.

## Non-Purpose

This branch is not:

- a backtest;
- an outcome replay;
- matched-control replay;
- Phase 4;
- strategy scoring;
- feature optimization;
- live-trading approval;
- deployment evidence.

No screenshots were analyzed or auto-labeled. No OHLC data was read.

## Human Workflow

1. Save screenshots in an agreed folder outside the schema itself, or record their existing paths.
2. Fill one row per trade/sample in `manual_trade_evidence_template.csv`.
3. Include M1/M5/M15/HTF screenshots when available.
4. Include entry, SL, TP, and target levels only if visible or explicitly known.
5. Write the human reasoning in plain language.
6. Mark uncertainty honestly using `UNCLEAR`, `UNKNOWN`, `PARTIAL`, or `NOT_APPLICABLE`.
7. Include bad, failed, skipped, and unclear trades, not only winners.
8. Run the validator before using the file for any later review.

Validator command:

```bash
python scripts/validate_adelin_v2_manual_trade_evidence.py --input-path backtests/reports/adelin_v2_manual_trade_evidence_schema/manual_trade_evidence_template.csv --schema-path backtests/reports/adelin_v2_manual_trade_evidence_schema/manual_trade_evidence_schema.json --output-path backtests/reports/adelin_v2_manual_trade_evidence_schema/manual_trade_evidence_validation_summary.json --allow-empty
```

## Evidence Quality

`HIGH` means the screenshot set includes clear price levels, timestamp, primary timeframe, relevant context, and enough metadata to separate pre-entry reasoning from any visible outcome.

`MEDIUM` means the example is usable but has at least one missing or ambiguous element, such as incomplete HTF context or partial outcome visibility.

`LOW` means the example can still be useful for qualitative concept discovery, but it is too incomplete for structured comparison.

`UNUSABLE` means the row should be excluded from future comparison because metadata, price levels, timestamp, or context are not reliable enough.

## Leakage Warning

Outcome screenshots can be recorded, but future comparisons must separate pre-entry context from post-entry outcome. A human `result_label` is a qualitative note only. It is not validation, not a replay label, and not a trading signal.

Any future comparison must explicitly separate:

- what was visible before entry;
- what was known only after entry;
- what was discretionary interpretation;
- what can be converted into a deterministic pre-entry metric.

## Future Use

Manual evidence may later help design measurable feature proxies or identify concepts the bot currently misses. It cannot by itself validate Adelin v2.

A later branch may compare collected manual evidence against Adelin v2 concepts only after:

- the manual evidence file is complete and validated;
- examples include winners, losers, skipped, and unclear cases;
- leakage risks are reviewed;
- a separate comparison plan is pre-registered.

## Safety

- No OHLC data was read.
- No screenshots were analyzed.
- No screenshots were auto-labeled.
- No backtest or replay was run.
- No matched-control replay was run.
- No Adelin runtime logic was modified.
- Strategy 2 was untouched.
- Strategy 3 was untouched.
- Phase 4 remains blocked.
- No live trading was enabled.
- No orders were placed.
- No Telegram trade alerts were sent.
- No broker execution was called.
- The v3 stash was not applied or popped.
