# Strategy 3 Paper Evidence Refresh Runner

This refresh runner is not a trading system. It does not emit trade instructions, authorize live trading, send Telegram alerts, place orders, change cooldown, or add filters.

## Purpose

The runner coordinates existing Strategy 3 paper evidence reports into a repeatable audit snapshot: clean-context comparison status, VWAP/regime diagnostics availability, paper accumulation dashboard metrics, risk-distance summaries, and final evidence gates.

## Key Metrics

- total paper rows: `135`
- legacy rows excluded: `64`
- clean context rows: `71`
- clean accepted/blocked: `26/45`
- clean acceptance rate: `0.3662`
- cooldown blocked count: `45`
- sample status: `INSUFFICIENT_N`

## Context And Comparison

- context gate: `PASSED`
- context gate reason: `prefix-compatible clean context rows available`
- prefix compatible/incompatible: `71/0`
- paper/backtest match status: `MATCHED`
- all-detected match rate: `1.0`
- accepted-only match rate: `1.0`

## Accumulation Projection

- first clean signal: `2026-05-21T02:30:00+00:00`
- latest clean signal: `2026-05-22T22:30:00+00:00`
- days since first clean signal: `1.8333`
- accepted rows/day: `14.1818`
- projected days to 100 accepted: `5.22`
- projected days to 200 accepted: `12.27`

## Risk Distance

- pip convention: `PROJECT_PIP_CONVENTION: 1 USD = 10 pips`
- accepted median: `1.35` USD / `13.5` pips
- accepted p90: `4.705` USD / `47.05` pips
- accepted max: `6.27` USD / `62.7` pips

Risk distance statistics are descriptive only. Large SL outliers require review, not automatic parameter changes.

## Gates

- sample gate: `INSUFFICIENT_N`
- pre-registered diagnostic gate: `BLOCKED`
- cooldown change gate: `BLOCKED`
- live gate: `BLOCKED`
- deployment gate: `BLOCKED`
- live readiness: `BLOCKED`
- allowed next action: `PAPER_ACCUMULATION_ONLY`

## Weekly Run

```powershell
python scripts/run_strategy_3_paper_evidence_refresh.py --dry-run
```

Use this after the paper pipeline has accumulated new Strategy 3 rows and after the clean-context comparison/regime reports have been refreshed when needed.

## Warnings

- none

## Safety

- no live trading
- no Telegram operational alerts
- no orders
- no broker execution
- no order_send
- no Strategy 3 VWAP/sigma/cooldown/entry/TP/SL/filter changes
- no Strategy 2 touch
- no Adelin touch
- no data/XAUUSD/*.csv mutation

## Next Recommendation

Continue Strategy 3 paper accumulation only. Re-run this refresh weekly or after meaningful new clean-context paper rows arrive; do not use it to change strategy parameters.
