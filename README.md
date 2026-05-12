# Dazro Trade

Dazro Trade is a paper-trading and demo-readiness research system for XAUUSD structure, liquidity, CRT/Turtle Soup, macro context, optional orderflow, and AI-assisted review.

It does not guarantee profitability and must not be used with real money until extensively tested.

## What It Does

- Builds deterministic trade context before AI sees anything.
- Infers probable liquidity zones from price data.
- Detects close-based structure, BOS/CHOCH, MSNR retests, CRT, Turtle Soup, QB, SMT, macro, and optional DOM/orderflow context.
- Applies non-negotiable risk gates before paper/demo action.
- Stores paper trades and rejects in SQLite.
- Sends optional Telegram paper/demo signal messages.
- Allows optional MT5 demo execution only when explicitly enabled and safety checks pass.

## What It Does Not Do

- It does not trade real money.
- It does not let AI invent signals.
- It does not see true institutional liquidity on XAUUSD spot/CFD.
- It does not make profitability claims.

## Architecture

Core package layout:

- `dazro_trade/core`: typed config and `SignalContext`
- `dazro_trade/structure`: close-based BOS, CHOCH, line structure, MSNR
- `dazro_trade/liquidity`: inferred pools, sweeps, acceptance, rejection
- `dazro_trade/analysis`: CRT and Turtle Soup
- `dazro_trade/quarterly`: Quarterly Theory and QB context
- `dazro_trade/smt`: divergence helpers
- `dazro_trade/macro`: news, sentiment, DXY, yields
- `dazro_trade/orderflow`: optional MT5 DOM snapshots and low-confidence metrics
- `dazro_trade/ai`: Anthropic/OpenAI engines, strict schemas, provider router
- `dazro_trade/risk`: validation, sizing, risk manager
- `dazro_trade/paper`: SQLite ledger and replay
- `dazro_trade/execution`: MT5 demo-only executor
- `dazro_trade/notifications`: Telegram formatting/sending
- `dazro_trade/runtime`: CLI, scanner, sessions, and Telegram command runtime

## Live Monitor Mode

The live path is:

```text
MT5 -> Python scanner -> scoring/risk filters -> Telegram
```

MultiCharts is not required for live operation. It can be used later for research, validation, and backtesting.

The scanner is selective by design:

- H4/H1 are context only: bias, liquidity map, QB, premium/discount, and targets.
- M15 is the main intraday setup timeframe.
- M5 confirms structure, displacement, and acceptance/rejection.
- M1 is the execution trigger.
- A signal is sent only when the setup reaches `TRIGGERED`.
- Internal analysis, watch zones, touched zones, invalidated zones, and no-trade notes stay silent unless requested manually.

Setup states:

- `WATCH`: interesting zone, not operational.
- `ARMED`: price is close and LTF confluence is forming.
- `TRIGGERED`: M15/M5/M1 chain is confirmed and Telegram may send one signal.
- `ENTERED`: entry area was already touched; do not chase.
- `INVALIDATED`: technical invalidation broke.
- `EXPIRED`: setup is stale.

## Telegram Commands

Visible commands:

- `/status` - bot, MT5, session, scanner, and latest error.
- `/analisi` - latest internal analysis, shown only on request.
- `/watch` - active operational zones.
- `/scan` - immediate manual scan with one report.
- `/plan` - HTF plan, sessions, and nearby/remote zones.
- `/trades` - signals and virtual trade tracking for the day.
- `/stop` - pause the automatic scanner only.
- `/resume` - resume scanner; first scan is silent.
- `/help` - show commands.

Hidden/deprecated commands such as `/asia`, `/london`, `/session`, `/health`, `/addtrade`, and `/cleartrades` are not shown in `/help`. If called manually, the Telegram runtime redirects the user to `/plan` or `/watch`.

## Environment Setup

Create a local `.env` from the placeholder file:

```powershell
Copy-Item .env.example .env
```

Fill only the keys you need. Do not commit `.env`; it is ignored by `.gitignore`.

Important defaults:

```env
PAPER_MODE=true
DEMO_EXECUTION=false
LIVE_EXECUTION=false
ORDERFLOW_ENABLED=false
AI_ENABLED=true
TELEGRAM_ENABLED=true
```

## API Keys

- OpenAI: create an API key in the OpenAI dashboard and set `OPENAI_API_KEY`.
- Anthropic: create an Anthropic API key and set `ANTHROPIC_API_KEY`.
- Telegram: create a bot with BotFather, set `TELEGRAM_TOKEN`, then set `TELEGRAM_CHAT_ID`.
- News/Tavily/FRED: optional keys used only when those providers are enabled.

If AI is disabled with `AI_ENABLED=false`, OpenAI and Anthropic keys are not required. If Telegram is disabled with `TELEGRAM_ENABLED=false`, Telegram keys are not required.

## Paper Mode

Paper mode is the default. Signals are validated, optionally reviewed, and stored in the SQLite ledger at `LEDGER_DB_PATH`.

```powershell
python main.py --paper --once
```

## Demo Mode

Demo execution is disabled by default. To attempt demo orders:

- Set `DEMO_EXECUTION=true`.
- Keep `LIVE_EXECUTION=false`.
- Provide MT5 demo credentials.
- Keep paper ledger enabled.
- Ensure risk validation accepts the signal.

If account type cannot be verified as demo, execution is rejected.

## Testing

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run tests:

```powershell
python -m pytest
```

All external services are mocked in tests. Tests run without API keys.

## Logging

Set `LOG_LEVEL=INFO` or pass:

```powershell
python main.py --log-level DEBUG --once
```

Rejected setups include explicit reason codes. Telegram failures and optional provider failures do not crash runtime.

## Limitations

- Deterministic modules are conservative and intentionally prefer rejection over weak setups.
- Orderflow from MT5 DOM is low confidence for XAUUSD CFD/spot and can only confirm, reject, or slightly adjust confidence.
- Macro classification avoids overconfident keyword-only decisions and degrades to uncertain when providers fail.
- AI is an audit/review layer only; deterministic logic and risk management remain authoritative.

## Roadmap

- Add richer multi-timeframe backtesting and replay tools.
- Expand broker/account verification for demo safety.
- Add more fixtures for volatile macro sessions and illiquid periods.
