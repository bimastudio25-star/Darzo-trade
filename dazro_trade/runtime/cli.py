from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import replace

from dazro_trade.core.config import load_settings
from dazro_trade.paper.replay import replay_ledger
from dazro_trade.runtime.engine import RuntimeEngine
from dazro_trade.runtime.scanner import ScalpingScanner
from dazro_trade.runtime.telegram_runtime import run_telegram_polling


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dazro-trade")
    parser.add_argument("--paper", action="store_true", help="Force paper mode")
    parser.add_argument("--demo", action="store_true", help="Enable demo execution safety checks")
    parser.add_argument("--once", action="store_true", help="Run one evaluation cycle")
    parser.add_argument("--no-telegram", action="store_true")
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--log-level", default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--replay", default=None, help="Replay/debug a paper ledger database")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    updates = {}
    if args.paper:
        updates["paper_mode"] = True
    if args.demo:
        updates["demo_execution"] = True
    if args.no_telegram:
        updates["telegram_enabled"] = False
    if args.no_ai:
        updates["ai_enabled"] = False
    if args.log_level:
        updates["log_level"] = args.log_level
    if args.symbol:
        updates["mt5_symbol"] = args.symbol
    if updates:
        settings = replace(settings, **updates)

    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    if args.replay:
        for row in replay_ledger(args.replay):
            print(row)
        return 0
    engine = RuntimeEngine(settings)
    engine.boot()
    scanner = ScalpingScanner(settings)
    if args.once:
        result = asyncio.run(scanner.scan_once(manual=True))
        print(result["summary"])
        return 0
    if settings.telegram_enabled:
        if settings.telegram_token:
            asyncio.run(run_telegram_polling(scanner))
        else:
            logging.warning("Telegram enabled but TELEGRAM_TOKEN is missing; scanner will not start polling.")
            print("TELEGRAM_TOKEN mancante. Usa --once per test manuale o configura .env.")
    else:
        logging.info("Telegram disabled; runtime booted without polling.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
