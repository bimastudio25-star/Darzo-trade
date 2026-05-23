# Strategy 3 Paper Signal Stream

This is a paper-only notification and logging layer. It is not live trading, not a broker connector, not an order system, and not a deployment approval.

## Purpose

The stream lets Adelin mark accepted Strategy 3 paper signals manually on TradingView while the bot records accepted, blocked, no-signal, and error events locally for weekly review.

## How To Run

Dry-run one-shot:

```powershell
python scripts/run_strategy_3_paper_signal_stream.py --symbol XAUUSD --data-dir data --output-dir backtests/reports/strategy_3_paper_signal_stream --dry-run
```

Watch mode, still paper-only:

```powershell
python scripts/run_strategy_3_paper_signal_stream.py --symbol XAUUSD --watch --poll-seconds 60 --dry-run
```

Optional paper-only Telegram transport requires explicit enablement and environment variables:

```powershell
$env:STRATEGY3_PAPER_TELEGRAM_BOT_TOKEN = '<token>'
$env:STRATEGY3_PAPER_TELEGRAM_CHAT_ID = '<chat_id>'
python scripts/run_strategy_3_paper_signal_stream.py --symbol XAUUSD --enable-paper-telegram --no-dry-run
```

Secrets must stay in environment variables only. They are never written to reports, logs, docs, or git.

## Outputs

- `paper_signal_stream_events.csv`
- `paper_signal_stream_events.jsonl`
- `paper_signal_stream_latest_state.json`
- `paper_signal_stream_session_summary.json`
- `weekly_manual_review_template.csv`
- `paper_signal_stream.md`

## Current Session Summary

- events observed: `71`
- accepted / blocked / no signal / error: `26 / 45 / 0 / 0`
- cooldown blocked: `45`
- alerts sent / suppressed / failed: `0 / 71 / 0`
- Telegram enabled / configured: `False / False`

## Ambiguity Policy

- ambiguity governance gate: `WARNING`
- paper signal stream gate: `WARNING`
- primary outcome policy: `REFERENCE_PRIMARY_WITH_AMBIGUOUS_EXCLUDED_FROM_DECISIVE_WR`
- ambiguous outcome policy: `AMBIGUOUS_NOT_COUNTED_AS_WIN_AND_EXCLUDED_FROM_DECISIVE_WR`
- note: Ambiguous outcomes are excluded from decisive WR and are not counted as wins.

## Example Paper Message

```text
[PAPER SIGNAL — STRATEGY 3]
Symbol: XAUUSD
Direction: LONG
Decision time: 2026-05-21T02:30:00+00:00
Entry reference: 4538.58
Stop loss: 4537.76
Take profit: 4539.40
Risk: 0.82 USD / 8.2 pips
Event ID: strategy3-paper-44f07146d4bff17f
Signal status: ACCEPTED
Paper-only status: paper research notification only
Ambiguity policy: Ambiguous outcomes are excluded from decisive WR and are not counted as wins.
Paper-only signal for TradingView marking and weekly review. Not a trading instruction.
```

## Prohibited Use

- no live trading
- no broker execution
- no order_send
- no orders
- no lot size or account risk sizing
- no automatic closing
- no Strategy 3 logic changes
- no cooldown, VWAP, sigma, entry, TP, SL, or filter changes
- no edge, profitability, live-readiness, or Paper Validated claim

## Gates

- live gate: `BLOCKED`
- deployment gate: `BLOCKED`
- order_send gate: `BLOCKED`
- broker gate: `BLOCKED`
- allowed next action: `OBSERVE_MARK_ON_TRADINGVIEW_AND_REVIEW_WEEKLY`

## Weekly TradingView Workflow

1. Open `weekly_manual_review_template.csv`.
2. Mark accepted paper signals on TradingView manually.
3. Fill `tradingview_marked`, `human_decision`, screenshot reference, and end-of-week notes.
4. Keep ambiguous outcomes excluded from decisive WR and never count them as wins.
