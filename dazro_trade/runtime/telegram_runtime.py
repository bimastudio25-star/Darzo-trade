from __future__ import annotations

import asyncio
import logging
from typing import Any

from dazro_trade.runtime.scanner import ScalpingScanner

log = logging.getLogger(__name__)

VISIBLE_COMMANDS: tuple[tuple[str, str], ...] = (
    ("status", "stato bot, MT5, sessione, scanner e candle clock"),
    ("analisi", "mostra l'ultima analisi interna del bot"),
    ("watch", "mostra zone attive monitorate"),
    ("scan", "forza una scansione manuale immediata"),
    ("plan", "piano operativo completo HTF"),
    ("trades", "segnali/trade salvati oggi"),
    ("stop", "ferma scanner automatico"),
    ("resume", "riattiva scanner automatico"),
    ("help", "mostra comandi"),
)

HIDDEN_COMMANDS = ("asia", "london", "addtrade", "cleartrades", "session", "health")


def build_help_text() -> str:
    lines = ["Comandi disponibili:"]
    for command, description in VISIBLE_COMMANDS:
        lines.append(f"/{command} - {description}")
    return "\n".join(lines)


class TelegramCommandRuntime:
    def __init__(self, scanner: ScalpingScanner):
        self.scanner = scanner
        self.scanner_task: asyncio.Task | None = None

    async def start_scanner_task(self) -> None:
        if self.scanner_task is None or self.scanner_task.done():
            self.scanner_task = asyncio.create_task(self.scanner.run_loop())

    async def stop_scanner_task(self) -> None:
        await self.scanner.shutdown()
        if self.scanner_task is not None:
            self.scanner_task.cancel()

    async def start(self, update: Any, context: Any) -> None:
        await self.start_scanner_task()
        await self._reply(update, "Dazro Signal Bot attivo\n\n" + self.scanner.format_status())

    async def help(self, update: Any, context: Any) -> None:
        await self._reply(update, build_help_text())

    async def status(self, update: Any, context: Any) -> None:
        await self._reply(update, self.scanner.format_status())

    async def analisi(self, update: Any, context: Any) -> None:
        if self.scanner.latest_analysis is None:
            await self.scanner.scan_once(manual=True)
        await self._reply(update, self.scanner.format_analysis())

    async def watch(self, update: Any, context: Any) -> None:
        await self._reply(update, self.scanner.format_watch())

    async def scan(self, update: Any, context: Any) -> None:
        result = await self.scanner.scan_once(manual=True)
        await self._reply(update, result["summary"])

    async def plan(self, update: Any, context: Any) -> None:
        if self.scanner.latest_analysis is None:
            await self.scanner.scan_once(manual=True)
        await self._reply(update, self.scanner.format_plan())

    async def trades(self, update: Any, context: Any) -> None:
        await self._reply(update, self.scanner.format_trades())

    async def stop(self, update: Any, context: Any) -> None:
        self.scanner.pause()
        await self._reply(update, "Scanner automatico fermato. Il bot Telegram resta attivo.")

    async def resume(self, update: Any, context: Any) -> None:
        self.scanner.resume()
        await self.start_scanner_task()
        await self._reply(update, f"Scanner automatico riattivato. Scan ogni {self.scanner.scan_interval_seconds} secondi. Primo scan silenzioso.")

    async def hidden(self, update: Any, context: Any) -> None:
        await self._reply(update, "Comando non piu attivo. Usa /plan o /watch.")

    @staticmethod
    async def _reply(update: Any, text: str) -> None:
        message = getattr(update, "message", None)
        if message is None:
            return
        await message.reply_text(text)


async def run_telegram_polling(scanner: ScalpingScanner) -> None:
    try:
        from telegram import BotCommand
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception as exc:
        raise RuntimeError("python-telegram-bot non disponibile. Installa requirements.txt") from exc

    if not scanner.settings.telegram_token:
        raise RuntimeError("TELEGRAM_TOKEN mancante")

    runtime = TelegramCommandRuntime(scanner)
    await runtime.start_scanner_task()
    app = ApplicationBuilder().token(scanner.settings.telegram_token).build()
    app.add_handler(CommandHandler("start", runtime.start))
    app.add_handler(CommandHandler("help", runtime.help))
    app.add_handler(CommandHandler("status", runtime.status))
    app.add_handler(CommandHandler("analisi", runtime.analisi))
    app.add_handler(CommandHandler("watch", runtime.watch))
    app.add_handler(CommandHandler("scan", runtime.scan))
    app.add_handler(CommandHandler("plan", runtime.plan))
    app.add_handler(CommandHandler("trades", runtime.trades))
    app.add_handler(CommandHandler("stop", runtime.stop))
    app.add_handler(CommandHandler("resume", runtime.resume))
    for command in HIDDEN_COMMANDS:
        app.add_handler(CommandHandler(command, runtime.hidden))
    await app.bot.set_my_commands([BotCommand(command, description) for command, description in VISIBLE_COMMANDS])
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    try:
        while not scanner.shutdown_requested:
            await asyncio.sleep(1)
    finally:
        await runtime.stop_scanner_task()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


__all__ = ["HIDDEN_COMMANDS", "TelegramCommandRuntime", "VISIBLE_COMMANDS", "build_help_text", "run_telegram_polling"]
