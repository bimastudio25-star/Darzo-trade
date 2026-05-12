from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from dazro_trade.analysis.scalping import (
    ScalpingConfig,
    SignalDeduplicator,
    build_zones,
    detect_zone_interactions_since_last_scan,
    evaluate_scalping_setup,
    zone_distance,
)
from dazro_trade.core.config import Settings
from dazro_trade.core.models import ScalpingDecision, SetupZone
from dazro_trade.notifications.telegram_bot import TelegramBot, format_scalping_decision
from dazro_trade.runtime.sessions import ROME_TZ, current_session_name, format_session_summary, next_session

log = logging.getLogger(__name__)


@dataclass
class ScannerStats:
    scans: int = 0
    signals_sent: int = 0
    setups_rejected: int = 0
    duplicate_skips: int = 0
    first_silent_scan_completed: bool = False
    last_internal_event: str = "-"
    last_filter_reason: str = "-"


@dataclass
class VirtualTrade:
    trade_id: str
    signal_key: str
    symbol: str
    direction: str
    zone_id: str
    signal_time: datetime
    entry_area_low: float
    entry_area_high: float
    stop_loss: float | None
    tp1: float | None
    tp2: float | None
    status: str = "PENDING_ENTRY"
    entry_time: datetime | None = None
    entry_price: float | None = None
    source: str | None = None


class ScalpingScanner:
    def __init__(
        self,
        settings: Settings,
        *,
        mt5_handler: Any | None = None,
        telegram_bot: TelegramBot | None = None,
        scalping_config: ScalpingConfig | None = None,
    ):
        self.settings = settings
        self.mt5_handler = mt5_handler
        self.telegram_bot = telegram_bot or TelegramBot(settings)
        self.scalping_config = scalping_config or ScalpingConfig()
        self.deduplicator = SignalDeduplicator()
        self.paused = False
        self.shutdown_requested = False
        self.scan_interval_seconds = 120
        self.auto_signals_enabled = True
        self.send_auto_analysis_reports = False
        self.send_auto_watch_reports = False
        self.send_auto_zone_events = False
        self.send_auto_no_trade_messages = False
        self.max_alerts_per_scan = 1
        self.first_silent_scan_pending = True
        self.started_at = datetime.now(timezone.utc)
        self.last_scan: datetime | None = None
        self.next_scan_at: datetime | None = None
        self.last_market_update: datetime | None = None
        self.last_error: str | None = None
        self.last_price: float | None = None
        self.last_spread: float | None = None
        self.last_symbol: str = settings.mt5_symbol
        self.last_market_data: dict[str, pd.DataFrame] = {}
        self.latest_analysis: ScalpingDecision | None = None
        self.latest_zones: list[SetupZone] = []
        self.trades: list[VirtualTrade] = []
        self.stats = ScannerStats()
        self.reaction_alerts: dict[str, datetime] = {}
        self.reaction_alert_session_counts: dict[str, int] = {}

    async def initialize(self) -> None:
        if self.mt5_handler is not None:
            return
        try:
            from mt5_handler import MT5Handler

            handler = MT5Handler(self.settings.mt5_login, self.settings.mt5_password, self.settings.mt5_server)
            if handler.connect():
                handler.resolve_symbol([self.settings.mt5_symbol, "XAUUSD", "XAUUSD.", "XAUUSDm", "GOLD"])
                self.mt5_handler = handler
                self.last_symbol = handler.symbol or self.settings.mt5_symbol
                log.info("scanner_mt5_initialized symbol=%s", self.last_symbol)
            else:
                self.last_error = "MT5 initialize failed"
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("scanner_initialize_failed: %s", exc)

    async def shutdown(self) -> None:
        self.shutdown_requested = True
        if self.mt5_handler is not None and hasattr(self.mt5_handler, "shutdown"):
            self.mt5_handler.shutdown()

    async def run_loop(self) -> None:
        log.info("scanner_started")
        while not self.shutdown_requested:
            try:
                if self.paused:
                    await asyncio.sleep(5)
                    continue
                await self.scan_once(manual=False)
                self.next_scan_at = datetime.now(timezone.utc) + timedelta(seconds=self.scan_interval_seconds)
                await asyncio.sleep(self.scan_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                log.error("scanner_loop_error: %s", exc, exc_info=True)
                await asyncio.sleep(30)
        log.info("scanner_stopped")

    async def scan_once(self, *, manual: bool = False) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        previous_scan = self.last_scan
        market_data = await self.collect_market_data()
        self.last_market_data = market_data
        self.last_price = self.last_price or self._infer_price(market_data)
        session = current_session_name(now)
        self.latest_zones = build_zones(
            market_data,
            symbol=self.last_symbol,
            current_price=float(self.last_price or 0.0),
            config=self.scalping_config,
        )
        decision = evaluate_scalping_setup(
            market_data,
            symbol=self.last_symbol,
            current_price=self.last_price,
            spread=float(self.last_spread or 0.0),
            max_spread=self.settings.max_spread_pips,
            now_utc=now,
            last_scan_time=previous_scan,
            session_name=session,
            config=self.scalping_config,
        )
        self.latest_analysis = decision
        self.stats.scans += 1
        self.stats.last_internal_event = decision.state
        self.stats.last_filter_reason = decision.rejection_reasons[0] if decision.rejection_reasons else "-"
        self._track_virtual_entries(market_data, now, previous_scan)
        self.last_scan = now

        sent = False
        if not manual:
            sent = self._maybe_send_automatic_signal(decision, session)
        if decision.state in {"WATCH", "ARMED", "ENTERED"} and decision.rejection_reasons:
            self.stats.setups_rejected += 1
        return {
            "ok": True,
            "signal_sent": sent,
            "manual": manual,
            "decision": decision.to_dict(),
            "summary": self.format_scan_report(decision),
        }

    async def collect_market_data(self) -> dict[str, pd.DataFrame]:
        await self.initialize()
        data: dict[str, pd.DataFrame] = {}
        if self.mt5_handler is None:
            self.last_error = self.last_error or "MT5 handler not available"
            return data
        counts = {"M1": 1500, "M5": 1500, "M15": 1500, "H1": 1000, "H4": 500}
        for timeframe, count in counts.items():
            try:
                data[timeframe] = self.mt5_handler.get_candles(timeframe, count)
            except Exception as exc:
                log.warning("mt5_candles_failed timeframe=%s error=%s", timeframe, exc)
                data[timeframe] = pd.DataFrame()
        try:
            self.last_price = float(self.mt5_handler.get_price())
            self.last_spread, _ = self.mt5_handler.get_spread_pips(0.1)
            self.last_market_update = datetime.now(timezone.utc)
            log.info("mt5_data_updated symbol=%s price=%s spread=%s", self.last_symbol, self.last_price, self.last_spread)
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("mt5_snapshot_failed: %s", exc)
        return data

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False
        self.first_silent_scan_pending = True

    def _maybe_send_automatic_signal(self, decision: ScalpingDecision, session: str) -> bool:
        if self.first_silent_scan_pending:
            self.first_silent_scan_pending = False
            self.stats.first_silent_scan_completed = True
            log.info("first_silent_scan_completed")
            return False
        if not self.auto_signals_enabled or not decision.telegram_allowed:
            if self._maybe_send_reaction_alert(decision, session):
                return True
            if decision.state != "TRIGGERED":
                log.info("no_trade_internal reason=%s", self.stats.last_filter_reason)
            return False
        if self.deduplicator.is_duplicate(decision, session_name=session):
            self.stats.duplicate_skips += 1
            log.info("signal_skipped_duplicate signal=%s", decision.signal_id)
            return False
        key = self.deduplicator.mark_sent(decision, session_name=session)
        decision.signal_id = key
        text = format_scalping_decision(decision)
        result = self.telegram_bot.send_text(text)
        if result.get("ok"):
            self.stats.signals_sent += 1
            self._create_virtual_trade(decision, key)
            log.info("signal_sent key=%s", key)
            return True
        log.warning("signal_send_failed key=%s result=%s", key, result)
        return False

    def _maybe_send_reaction_alert(self, decision: ScalpingDecision, session: str) -> bool:
        if self.settings.send_triggered_only or not self.settings.send_armed_reaction_alerts:
            return False
        sweeps = decision.liquidity.get("sweeps", []) if decision.liquidity else []
        if decision.state not in {"ARMED", "WATCH"} or not sweeps:
            return False
        sweep = sweeps[0]
        if sweep.get("status") not in {"ARMED", "SWEEPING_INTRABAR", "CONFIRMED_SWEEP"}:
            return False
        pool = self._pool_for_sweep(sweep.get("pool_id"))
        distance_pips = float(pool.get("distance_pips", 0) if pool else 0)
        if distance_pips < self.settings.min_reaction_distance_pips and sweep.get("status") == "ARMED":
            return False
        count = self.reaction_alert_session_counts.get(session, 0)
        if count >= self.settings.max_reaction_alerts_per_session:
            return False
        key = f"{decision.symbol}:{sweep.get('pool_id')}:{sweep.get('status')}:{session}"
        now = datetime.now(timezone.utc)
        last = self.reaction_alerts.get(key)
        if last and (now - last) < timedelta(minutes=self.settings.reaction_alert_cooldown_minutes):
            log.info("reaction_alert_skipped_cooldown key=%s", key)
            return False
        text = self._format_reaction_alert(decision, sweep, pool)
        result = self.telegram_bot.send_text(text)
        if result.get("ok"):
            self.reaction_alerts[key] = now
            self.reaction_alert_session_counts[session] = count + 1
            log.info("reaction_alert_sent key=%s", key)
            return True
        return False

    def _pool_for_sweep(self, pool_id: str | None) -> dict | None:
        if self.latest_analysis is None or not pool_id:
            return None
        for pool in self.latest_analysis.liquidity.get("pools", []):
            if pool.get("id") == pool_id:
                return pool
        return None

    @staticmethod
    def _format_reaction_alert(decision: ScalpingDecision, sweep: dict, pool: dict | None) -> str:
        pool_type = pool.get("pool_type") if pool else "liquidity"
        distance = pool.get("distance_pips") if pool else "-"
        confluences = []
        if pool:
            confluences.extend(pool.get("confluences", []))
        confluences.extend(sweep.get("reason_codes", []))
        lines = [
            f"{decision.symbol} - POSSIBILE REAZIONE LIQUIDITY",
            f"Livello: {sweep.get('level')}",
            f"Tipo: {pool_type}",
            f"Distanza: {distance} pips",
            f"Stato: {sweep.get('status')}",
            "Confluence:",
        ]
        lines.extend(f"- {item}" for item in confluences[:8])
        lines.extend(
            [
                "Serve conferma:",
                "- close back inside",
                "- M1/M5 CHoCH",
                "- FVG/IFVG dopo sweep",
                "NO ENTRY ANCORA.",
                "Disclaimer: Paper/demo signal only. No real-money execution.",
            ]
        )
        return "\n".join(lines)

    def _create_virtual_trade(self, decision: ScalpingDecision, signal_key: str) -> None:
        if decision.primary_zone is None or not decision.entry_area:
            return
        trade = VirtualTrade(
            trade_id=f"vt-{len(self.trades) + 1}",
            signal_key=signal_key,
            symbol=decision.symbol,
            direction=decision.direction,
            zone_id=decision.primary_zone.id,
            signal_time=decision.timestamp_utc,
            entry_area_low=decision.entry_area[0],
            entry_area_high=decision.entry_area[1],
            stop_loss=decision.stop,
            tp1=decision.targets[0]["price"] if decision.targets else None,
            tp2=decision.targets[1]["price"] if len(decision.targets) > 1 else None,
        )
        self.trades.append(trade)

    def _track_virtual_entries(self, market_data: dict[str, pd.DataFrame], now: datetime, previous_scan: datetime | None) -> None:
        for trade in self.trades:
            if trade.status != "PENDING_ENTRY":
                continue
            zone = SetupZone(
                id=trade.zone_id,
                symbol=trade.symbol,
                timeframe="M1",
                zone_type="entry_area",
                role="ENTRY_TRIGGER",
                state="WATCH",
                direction="BUY" if trade.direction == "LONG" else "SELL",
                low=trade.entry_area_low,
                high=trade.entry_area_high,
            )
            interaction = detect_zone_interactions_since_last_scan(
                zone,
                market_data.get("M1"),
                market_data.get("M5"),
                last_scan_time=previous_scan,
                now_utc=now,
            )
            if interaction.entry_area_touched:
                trade.status = "ENTERED"
                trade.entry_time = interaction.last_touch_time or now
                trade.entry_price = interaction.touch_price
                trade.source = interaction.source_timeframe

    def _infer_price(self, market_data: dict[str, pd.DataFrame]) -> float:
        for timeframe in ("M1", "M5", "M15", "H1", "H4"):
            df = market_data.get(timeframe)
            if df is not None and len(df) and "c" in df.columns:
                return float(df["c"].iloc[-1])
        return 0.0

    def format_status(self) -> str:
        now = datetime.now(timezone.utc)
        next_info = next_session(now)
        return "\n".join(
            [
                "Dazro Trade Bot",
                f"Bot: {'IN PAUSA' if self.paused else 'ATTIVO'}",
                f"MT5 connesso: {'si' if self.mt5_handler is not None else 'no'}",
                f"Simbolo: {self.last_symbol}",
                f"Prezzo attuale: {self.last_price if self.last_price is not None else '-'}",
                f"Spread: {self.last_spread if self.last_spread is not None else '-'}",
                f"Ora UTC: {now:%Y-%m-%d %H:%M} UTC",
                f"Ora Italia: {now.astimezone(ROME_TZ):%Y-%m-%d %H:%M} Europe/Rome",
                f"Sessione attuale: {current_session_name(now)}",
                f"Prossima sessione: {next_info['name']} | {next_info['start_local']:%Y-%m-%d %H:%M} {next_info['timezone']} | {next_info['start_utc']:%H:%M} UTC",
                f"Scanner loop vivo: {'no' if self.shutdown_requested else 'si'}",
                f"Scanner automatico: {'no' if self.paused else 'si'}",
                "Report automatici analisi: disattivi",
                "Auto watch alerts: disattivi",
                f"Scan ogni: {self.scan_interval_seconds} secondi",
                f"Ultimo scan: {self._fmt_dt(self.last_scan)}",
                f"Prossimo scan stimato: {self._fmt_dt(self.next_scan_at)}",
                f"Primo scan silenzioso: {'completato' if self.stats.first_silent_scan_completed else 'non completato'}",
                f"Max segnali per scan: {self.max_alerts_per_scan}",
                f"Ultimo aggiornamento dati: {self._fmt_dt(self.last_market_update)}",
                f"Watch zone attive: {len([z for z in self.latest_zones if z.role != 'HTF_CONTEXT' and (z.distance_from_price or 999) <= 8])}",
                f"Setup scartati oggi: {self.stats.setups_rejected}",
                f"Segnali inviati oggi: {self.stats.signals_sent}",
                f"Ultimo segnale inviato: {self.trades[-1].signal_key if self.trades else '-'}",
                f"Ultimo evento interno: {self.stats.last_internal_event}",
                f"Motivo filtro principale: {self.stats.last_filter_reason}",
                f"Ultimo errore: {self.last_error or '-'}",
            ]
        )

    def format_analysis(self) -> str:
        if self.latest_analysis is None:
            return "Nessuna analisi interna disponibile. Usa /scan per calcolare subito."
        return "ANALISI INTERNA\n\n" + format_scalping_decision(self.latest_analysis)

    def format_watch(self) -> str:
        operative = [z for z in self.latest_zones if z.role != "HTF_CONTEXT" and (z.distance_from_price or 9999) <= 8]
        if not operative:
            return "Watch zone operative: 0\nZone HTF lontane disponibili solo come contesto in /plan."
        lines = ["WATCH ZONE OPERATIVE"]
        for idx, zone in enumerate(operative[:5], start=1):
            lines.extend(
                [
                    "",
                    f"{idx}. {zone.timeframe} {zone.zone_type}",
                    f"Range: {zone.low:.2f} - {zone.high:.2f}",
                    f"Stato: {zone.state}",
                    f"Ruolo: {zone.role}",
                    f"Distanza: {zone.distance_from_price}",
                    f"Zona toccata: {'si' if zone.touched else 'no'}",
                    f"Entry area toccata: {'si' if zone.entry_area_touched else 'no'}",
                    f"Motivi: {', '.join(zone.reason_codes) if zone.reason_codes else '-'}",
                ]
            )
        remote = len([z for z in self.latest_zones if z.role == "HTF_CONTEXT" and (z.distance_from_price or 0) > 8])
        if remote:
            lines.append(f"\nZone HTF di contesto non operative: {remote}")
        if self.latest_analysis:
            reaction = self.latest_analysis.liquidity.get("reaction_pools", [])[:5]
            if reaction:
                lines.append("\nLiquidity 80+ pips in reaction map:")
                for pool in reaction:
                    lines.append(f"- {pool.get('timeframe')} {pool.get('pool_type')} {pool.get('level')} distanza={pool.get('distance_pips')} pips ({pool.get('distance_band')})")
        return "\n".join(lines)

    def format_scan_report(self, decision: ScalpingDecision | None = None) -> str:
        return "SCAN MANUALE\n\n" + format_scalping_decision(decision or self.latest_analysis) if (decision or self.latest_analysis) else "Nessuna analisi disponibile."

    def format_plan(self) -> str:
        lines = ["PIANO OPERATIVO", "", format_session_summary()]
        if self.latest_analysis:
            lines.extend(["", format_scalping_decision(self.latest_analysis)])
        remote = [z for z in self.latest_zones if z.role == "HTF_CONTEXT"]
        if remote:
            lines.extend(["", "Contesto HTF lontano/non operativo:"])
            for zone in remote[:5]:
                lines.append(f"- {zone.timeframe} {zone.zone_type} {zone.low:.2f}-{zone.high:.2f} distanza={zone.distance_from_price}")
        return "\n".join(lines)

    def format_trades(self) -> str:
        if not self.trades:
            return "Segnali oggi: 0"
        lines = ["SEGNALI/TRADES VIRTUALI"]
        for trade in self.trades:
            lines.extend(
                [
                    "",
                    f"{trade.symbol} {trade.direction}",
                    f"Segnale: {self._fmt_dt(trade.signal_time)}",
                    f"Entry area: {trade.entry_area_low:.2f} - {trade.entry_area_high:.2f}",
                    f"Stato: {trade.status}",
                    f"Entry rilevata: {self._fmt_dt(trade.entry_time)}",
                    f"Fonte: {trade.source or '-'}",
                    f"SL: {trade.stop_loss} | TP1: {trade.tp1} | TP2: {trade.tp2}",
                ]
            )
        return "\n".join(lines)

    @staticmethod
    def _fmt_dt(value: datetime | None) -> str:
        if value is None:
            return "mai"
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


__all__ = ["ScalpingScanner", "ScannerStats", "VirtualTrade"]
