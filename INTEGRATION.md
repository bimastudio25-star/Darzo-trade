# Adelin Integration

Adelin is integrated as the priority paper/demo strategy path for XAUUSD scalp research.

- Package: `dazro_trade/adelin/`
- Runtime hook: `ScalpingScanner.scan_once`
- Telegram send path: `TelegramBot.send_text`
- Execution mode: paper/demo only, no live-money execution

Strategy modes:

- `LIQ_VP_NT_FVG_A_PLUS`: liquidity sweep, post-liquidity FVG/IFVG, volume crack/LVN, Number Theory, clean target/RR, spread ok, entry available.
- `LIQ_VP_NT_FVG_SCALP`: minimum liquidity/FVG/target/spread hard filters with score 65-84 or missing A+ ideal filters.
- `VWAP_STD_RESEARCH_1R`: paper-only VWAP two-sigma research channel, never formatted as A+.
- `NO_TRADE`: no operational signal; rejection reasons are returned for logs/manual commands.

XAUUSD pip convention:

- `pip_size = 0.10`
- `10 pips = $1`
- `50 pips = $5`
- `100 pips = $10`

Volume profile uses MT5 `tick_volume` as a proxy, not true futures volume.
