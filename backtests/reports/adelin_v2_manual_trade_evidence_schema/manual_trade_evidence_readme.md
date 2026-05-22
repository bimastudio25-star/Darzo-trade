# Adelin v2 Manual Trade Evidence Schema

This folder contains a schema and blank template for collecting human screenshot/manual trade examples. The rows are qualitative evidence only. They are not validation data, not backtest results, and not Phase 4 approval.

Files:

- `manual_trade_evidence_schema.json`: field definitions, enum values, safety flags, and forbidden validation-claim terms.
- `manual_trade_evidence_template.csv`: blank human-input template.
- `manual_trade_evidence_example_rows.csv`: fake rows showing valid formatting only.
- `manual_trade_evidence_validation_summary.json`: validator output for the blank template.
- `summary.json`: branch-level safety and intent summary.

Validation command:

```bash
python scripts/validate_adelin_v2_manual_trade_evidence.py --input-path backtests/reports/adelin_v2_manual_trade_evidence_schema/manual_trade_evidence_template.csv --schema-path backtests/reports/adelin_v2_manual_trade_evidence_schema/manual_trade_evidence_schema.json --output-path backtests/reports/adelin_v2_manual_trade_evidence_schema/manual_trade_evidence_validation_summary.json --allow-empty
```

Human reviewers should fill one row per manual trade/sample, include winners, losers, skipped, and unclear examples, and mark uncertainty honestly.
