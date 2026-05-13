from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, fields as dataclass_fields
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from dazro_trade.adelin import format_adelin_signal, format_rejection_summary, format_vp_summary, run_adelin_scan
from dazro_trade.analysis.reentry import evaluate_reentry
from dazro_trade.analysis.scalping import (
    ScalpingConfig,
    SignalDeduplicator,
    build_zones,
    detect_zone_interactions_since_last_scan,
    evaluate_scalping_setup,
    zone_distance,
)
from dazro_trade.analysis.statistical_scalp import StatisticalScalpSignal, evaluate_statistical_scalp
from dazro_trade.analysis.liquidity_expansion import LiquidityExpansionSignal, evaluate_liquidity_expansion
from dazro_trade.runtime.coordinator import CoordinatorDecision, combine_strategy_results
from dazro_trade.risk.manager import RiskManager
from dazro_trade.core.config import Settings
from dazro_trade.core.models import ScalpingDecision, SetupZone
from dazro_trade.core.symbols import get_symbol_spec, pips_to_price, price_to_pips
from dazro_trade.notifications.telegram_bot import TelegramBot, format_scalping_decision
from dazro_trade.runtime.sessions import ROME_TZ, current_session_name, format_session_summary, next_session

log = logging.getLogger(__name__)


def _scalping_config_from_settings(settings: Settings) -> ScalpingConfig:
    values = {}
    for item in dataclass_fields(ScalpingConfig):
        if hasattr(settings, item.name):
            values[item.name] = getattr(settings, item.name)
    return ScalpingConfig(**values)


@dataclass
class ScannerStats:
    scans: int = 0
    signals_sent: int = 0
    setups_rejected: int = 0
    duplicate_skips: int = 0
    stat_scalps_sent: int = 0
    liquidity_expansion_sent: int = 0
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
    stop_hit_time: datetime | None = None
    stop_hit_price: float | None = None
    reentry_state: str = "-"
    reentry_reason_codes: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    strategy: str = "v1"
    tp3: float | None = None
    tp4: float | None = None
    tp1_hit: bool = False
    tp2_hit: bool = False
    tp3_hit: bool = False
    tp4_hit: bool = False
    be_activated: bool = False
    original_stop_loss: float | None = None
    strategy_payload: dict = field(default_factory=dict)


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
        self.scalping_config = scalping_config or _scalping_config_from_settings(settings)
        self.deduplicator = SignalDeduplicator()
        self.risk = RiskManager(settings)
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
        self.last_bid: float | None = None
        self.last_ask: float | None = None
        self.last_tick_snapshot: dict[str, Any] = {}
        self.last_tick_time: datetime | None = None
        self.last_symbol: str = settings.mt5_symbol
        self.last_market_data: dict[str, pd.DataFrame] = {}
        self.latest_analysis: ScalpingDecision | None = None
        self.latest_adelin_result: dict[str, Any] | None = None
        self.latest_liquidity_expansion_signal: LiquidityExpansionSignal | None = None
        self.latest_coordinator_decision: CoordinatorDecision | None = None
        self.latest_zones: list[SetupZone] = []
        self.trades: list[VirtualTrade] = []
        self.stats = ScannerStats()
        self.reaction_alerts: dict[str, datetime] = {}
        self.reaction_cluster_confirmed_counts: dict[str, int] = {}
        self.zone_alert_memory: dict[str, dict[str, Any]] = {}
        self.reaction_alert_session_counts: dict[str, int] = {}
        self.reentry_alert_memory: dict[str, datetime] = {}
        self.session_behaviour_alert_memory: dict[str, datetime] = {}
        self.session_behaviour_session_counts: dict[str, int] = {}
        self.stat_scalp_session_counts: dict[str, int] = {}
        self.adelin_sent_keys: set[str] = set()
        self.adelin_session_counts: dict[str, int] = {}
        self.liquidity_expansion_session_counts: dict[str, int] = {}

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
            timezone_name=self.settings.timezone,
            broker_time_offset_hours=self.settings.broker_time_offset_hours,
        )
        self._apply_tick_freshness_gate(decision, now)
        decision.intraday_context.update(
            {
                "bid": self.last_bid,
                "ask": self.last_ask,
                "last_tick_time": self._fmt_dt(self.last_tick_time),
            }
        )
        self.latest_analysis = decision
        adelin_result = None
        if self.settings.adelin_enabled:
            adelin_result = run_adelin_scan(
                mt5=self.mt5_handler,
                market_data=market_data,
                news_events=[],
                pip=get_symbol_spec(self.last_symbol).pip_size,
                settings=self.settings,
                current_price=self.last_price,
                spread_pips=float(self.last_spread or 0.0),
                now_utc=now,
                session_name=session,
            )
            self.latest_adelin_result = adelin_result
        self.stats.scans += 1
        self.stats.last_internal_event = decision.state
        self.stats.last_filter_reason = decision.rejection_reasons[0] if decision.rejection_reasons else "-"
        self._track_virtual_entries(market_data, now, previous_scan)
        self.last_scan = now

        sent = False
        was_first_silent_scan = self.first_silent_scan_pending
        if not manual:
            lex_signal = None
            if self.settings.liquidity_expansion_enabled and not was_first_silent_scan:
                lex_signal = self._compute_liquidity_expansion_signal(market_data, session, now)
            self.latest_liquidity_expansion_signal = lex_signal
            if self.settings.strategy_coordinator_enabled and not was_first_silent_scan:
                coord = combine_strategy_results(
                    adelin_result,
                    lex_signal,
                    zone_tolerance_pips=self.settings.strategy_a_plus_plus_tolerance_pips,
                    conflict_tolerance_pips=self.settings.strategy_conflict_tolerance_pips,
                    symbol=self.last_symbol,
                )
                self.latest_coordinator_decision = coord
                sent = self._dispatch_coordinator(coord, adelin_result, lex_signal, session, now)
            else:
                if not was_first_silent_scan and self._maybe_send_adelin_signal(adelin_result, session, now):
                    sent = True
                if lex_signal is not None:
                    self._send_liquidity_expansion(lex_signal, session, now)
            if not sent and self.settings.auto_signal_old_scalping and not was_first_silent_scan:
                sent = self._maybe_send_automatic_signal(decision, session)
        if self.settings.statistical_scalp_enabled and not manual and not was_first_silent_scan:
            self._maybe_send_statistical_scalp(market_data, session, now)
        if decision.state in {"WATCH", "ARMED", "ENTERED"} and decision.rejection_reasons:
            self.stats.setups_rejected += 1
        return {
            "ok": True,
            "signal_sent": sent,
            "manual": manual,
            "decision": decision.to_dict(),
            "adelin": adelin_result,
            "summary": self.format_scan_report(decision),
        }

    async def collect_market_data(self) -> dict[str, pd.DataFrame]:
        await self.initialize()
        data: dict[str, pd.DataFrame] = {}
        if self.mt5_handler is None:
            self.last_error = self.last_error or "MT5 handler not available"
            return data
        counts = {"M1": 1500, "M5": 1500, "M15": 1500, "H1": 1000, "H4": 500, "D1": 300}
        for timeframe, count in counts.items():
            try:
                data[timeframe] = self.mt5_handler.get_candles(timeframe, count)
                frame = data[timeframe]
                last_time = frame["time"].iloc[-1] if frame is not None and len(frame) and "time" in frame.columns else None
                log.info("MT5 CANDLES timeframe=%s count=%s last_time=%s live=%s", timeframe, len(frame) if frame is not None else 0, last_time, self._is_live_candle(timeframe, last_time))
            except Exception as exc:
                log.warning("mt5_candles_failed timeframe=%s error=%s", timeframe, exc)
                data[timeframe] = pd.DataFrame()
        try:
            spec = get_symbol_spec(self.last_symbol)
            if hasattr(self.mt5_handler, "get_tick_snapshot"):
                snapshot = self.mt5_handler.get_tick_snapshot()
                self.last_tick_snapshot = snapshot
                if snapshot.get("ok"):
                    self.last_bid = snapshot.get("bid")
                    self.last_ask = snapshot.get("ask")
                    self.last_price = float(snapshot["mid"])
                    self.last_spread = float(snapshot["spread_pips"])
                    self.last_tick_time = self._tick_time(snapshot.get("time"))
                else:
                    self.last_error = snapshot.get("reason", "tick_unavailable")
                    self.last_price = self._infer_price(data)
                    self.last_spread = 999.0
                    self.last_tick_time = None
            else:
                self.last_price = float(self.mt5_handler.get_price())
                self.last_spread, _ = self.mt5_handler.get_spread_pips(spec.pip_size)
                self.last_tick_time = datetime.now(timezone.utc)
            self.last_market_update = datetime.now(timezone.utc)
            log.info("MT5 DATA OK symbol=%s bid=%s ask=%s mid=%s spread_pips=%s", self.last_symbol, self.last_bid, self.last_ask, self.last_price, self.last_spread)
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("mt5_snapshot_failed: %s", exc)
        return data

    def _apply_tick_freshness_gate(self, decision: ScalpingDecision, now: datetime) -> None:
        if self.mt5_handler is None:
            return
        if not self.last_tick_snapshot.get("ok"):
            decision.state = "WATCH"
            decision.score = 0
            decision.confidence = 0.0
            decision.rejection_reasons.insert(0, "tick_unavailable")
            decision.reason_codes.append("tick_unavailable")
            return
        if self.last_tick_time is None or (now - self.last_tick_time).total_seconds() > 10:
            decision.state = "WATCH"
            decision.score = 0
            decision.confidence = 0.0
            decision.rejection_reasons.insert(0, "stale_price_data")
            decision.reason_codes.append("stale_price_data")

    @staticmethod
    def _tick_time(value: Any) -> datetime | None:
        if value is None:
            return datetime.now(timezone.utc)
        try:
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(float(value), tz=timezone.utc)
            ts = pd.Timestamp(value).to_pydatetime()
            return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
        except Exception:
            return None

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
            if self._maybe_send_session_behaviour_alert(decision, session):
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

    def _maybe_send_adelin_signal(self, result: dict[str, Any] | None, session: str, now: datetime) -> bool:
        if not result or self.paused or not self.auto_signals_enabled:
            return False
        signal = result.get("signal")
        if not signal:
            if self.settings.adelin_send_rejection_debug:
                self.stats.last_filter_reason = ", ".join(result.get("rejected", [])[:3]) or "adelin_no_trade"
            return False
        if signal.get("setup_mode") == "VWAP_STD_RESEARCH_1R" and not self.settings.adelin_send_vwap_research:
            return False
        count = self.adelin_session_counts.get(session, 0)
        if count >= self.settings.max_daily_signals:
            return False
        key = self._adelin_signal_key(signal, session, now)
        if key in self.adelin_sent_keys:
            self.stats.duplicate_skips += 1
            return False
        text = format_adelin_signal(signal, result)
        send_result = self.telegram_bot.send_text(text)
        if send_result.get("ok"):
            self.adelin_sent_keys.add(key)
            self.adelin_session_counts[session] = count + 1
            self.stats.signals_sent += 1
            if signal.get("setup_mode") != "VWAP_STD_RESEARCH_1R":
                self._create_virtual_trade_from_adelin(signal, key, now)
            log.info("adelin_signal_sent key=%s", key)
            return True
        return False

    @staticmethod
    def _adelin_signal_key(signal: dict[str, Any], session: str, now: datetime) -> str:
        return ":".join(
            [
                str(signal.get("symbol", "XAUUSD")),
                str(signal.get("setup_mode", "-")),
                str(signal.get("direction", "-")),
                str(round(float(signal.get("entry", 0) or 0), 1)),
                str(round(float(signal.get("sl", 0) or 0), 1)),
                session,
                now.date().isoformat(),
            ]
        )

    def _create_virtual_trade_from_adelin(self, signal: dict[str, Any], signal_key: str, now: datetime) -> None:
        zone = signal.get("entry_zone") or (signal.get("entry"), signal.get("entry"))
        if not isinstance(zone, (tuple, list)) or len(zone) != 2:
            return
        trade = VirtualTrade(
            trade_id=f"vt-{len(self.trades) + 1}",
            signal_key=signal_key,
            symbol=str(signal.get("symbol", self.last_symbol)),
            direction=str(signal.get("direction", "WAIT")),
            zone_id=str(signal.get("setup_mode", "ADELIN")),
            signal_time=now,
            entry_area_low=float(zone[0]),
            entry_area_high=float(zone[1]),
            stop_loss=float(signal["sl"]) if signal.get("sl") is not None else None,
            tp1=float(signal["tp1"]["price"]) if isinstance(signal.get("tp1"), dict) else None,
            tp2=float(signal["tp2"]["price"]) if isinstance(signal.get("tp2"), dict) else None,
            source="ADELIN",
        )
        self.trades.append(trade)

    def _maybe_send_statistical_scalp(self, market_data: dict[str, pd.DataFrame], session: str, now: datetime) -> bool:
        if self.first_silent_scan_pending or self.paused:
            return False
        m5 = market_data.get("M5")
        if self.last_price is None or m5 is None or len(m5) == 0:
            return False
        signal = evaluate_statistical_scalp(
            m5_df=m5,
            current_price=float(self.last_price),
            symbol=self.last_symbol,
            tolerance_pips_to_band=self.settings.statistical_scalp_band_tolerance_pips,
            min_abs_z=self.settings.statistical_scalp_min_abs_z,
            nt_tolerance_pips=self.settings.number_theory_tolerance_pips,
            now_utc=now,
        )
        if signal is None:
            return False
        count = self.stat_scalp_session_counts.get(session, 0)
        if count >= self.settings.statistical_scalp_max_per_session:
            return False
        dedup_key = f"stat:{self.last_symbol}:{round(signal.entry, 1)}:{session}:{now.date().isoformat()}"
        if dedup_key in self.deduplicator.sent_keys:
            return False
        self.deduplicator.sent_keys.add(dedup_key)
        result = self.telegram_bot.send_text(self._format_statistical_scalp(signal))
        if result.get("ok"):
            self.stat_scalp_session_counts[session] = count + 1
            self.stats.stat_scalps_sent += 1
            log.info("stat_scalp_sent key=%s", dedup_key)
            return True
        return False

    @staticmethod
    def _format_statistical_scalp(signal: StatisticalScalpSignal) -> str:
        tier = next((reason.split("=", 1)[1] for reason in signal.reason_codes if reason.startswith("nt_tier=")), "none")
        lines = [
            f"{signal.symbol} - VWAP_STD_RESEARCH_1R - PAPER ONLY",
            f"Direzione: {signal.direction}",
            f"Entry: {signal.entry:.2f}",
            f"Stop: {signal.stop:.2f}",
            f"TP (1R): {signal.tp:.2f}",
            f"z-score: {signal.z_score}",
            f"VWAP: {signal.vwap:.2f}",
            "Confluence:",
            "- statistical_mean_reversion",
            "- vwap_2sigma_extension",
            f"- number_theory_{tier}",
            "Disclaimer: Paper/demo signal only. No real-money execution.",
        ]
        return "\n".join(lines)

    def _compute_liquidity_expansion_signal(self, market_data: dict[str, pd.DataFrame], session: str, now: datetime) -> LiquidityExpansionSignal | None:
        if self.first_silent_scan_pending or self.paused:
            return None
        if self.last_price is None:
            return None
        if self.last_spread is not None and self.last_spread > self.settings.liquidity_expansion_max_spread_pips:
            log.info("liquidity_expansion_skipped reason=spread_too_high spread=%s", self.last_spread)
            return None
        required = ("M1", "M5", "M15", "H1")
        for tf in required:
            frame = market_data.get(tf)
            if frame is None or len(frame) == 0:
                return None
        signal = evaluate_liquidity_expansion(
            market_data["M1"],
            market_data["M5"],
            market_data["M15"],
            market_data["H1"],
            current_price=self.last_price,
            symbol=self.last_symbol,
            lookback_h1=self.settings.liquidity_expansion_lookback_h1,
            range_in_range_max_pips=self.settings.liquidity_expansion_range_in_range_max_pips,
            m15_reference_timezone=self.settings.liquidity_expansion_m15_reference_timezone,
            now_utc=now,
        )
        if signal is None:
            return None
        if signal.rr_tp1 < self.settings.liquidity_expansion_min_rr_tp1:
            log.info("liquidity_expansion_skipped reason=rr_tp1_below_floor rr=%s floor=%s", signal.rr_tp1, self.settings.liquidity_expansion_min_rr_tp1)
            return None
        count = self.liquidity_expansion_session_counts.get(session, 0)
        if count >= self.settings.liquidity_expansion_max_per_session:
            log.info("liquidity_expansion_skipped reason=session_cap session=%s count=%s", session, count)
            return None
        return signal

    def _send_liquidity_expansion(self, signal: LiquidityExpansionSignal, session: str, now: datetime) -> bool:
        level = signal.reference.h1_ref_low if signal.direction == "LONG" else signal.reference.h1_ref_high
        dedup_key = f"liqexp:{self.last_symbol}:{signal.direction}:{round(level, 1)}:{session}:{now.date().isoformat()}"
        if dedup_key in self.deduplicator.sent_keys:
            return False
        lot_size: float | None = None
        if self.settings.liquidity_expansion_require_risk_ok:
            risk_payload = {
                "signal_id": dedup_key,
                "entry": signal.entry,
                "sl": signal.stop,
                "tp": signal.tp1,
                "tp1": signal.tp1,
                "direction": "BUY" if signal.direction == "LONG" else "SELL",
            }
            risk = self.risk.validate(risk_payload, spread=self.last_spread or 0.0, session=session)
            if not risk.get("accepted", False):
                log.info("liquidity_expansion_rejected_by_risk reasons=%s", risk.get("rejection_reasons"))
                return False
            lot_size = risk.get("lot_size")
        text = self._format_liquidity_expansion_message(signal, lot_size=lot_size)
        result = self.telegram_bot.send_text(text)
        if not result.get("ok"):
            log.warning("liquidity_expansion_send_failed key=%s result=%s", dedup_key, result)
            return False
        count = self.liquidity_expansion_session_counts.get(session, 0)
        self.deduplicator.sent_keys.add(dedup_key)
        self.liquidity_expansion_session_counts[session] = count + 1
        self.stats.liquidity_expansion_sent += 1
        if self.settings.liquidity_expansion_require_risk_ok:
            self.risk.register_signal(dedup_key)
        self.trades.append(VirtualTrade(
            trade_id=f"vt-{len(self.trades) + 1}",
            signal_key=dedup_key,
            symbol=self.last_symbol,
            direction=signal.direction,
            zone_id=f"h1_level_{round(level, 2)}",
            signal_time=signal.timestamp_utc,
            entry_area_low=signal.entry,
            entry_area_high=signal.entry,
            stop_loss=signal.stop,
            tp1=signal.tp1,
            tp2=signal.tp2,
            status="ENTERED",
            entry_time=signal.timestamp_utc,
            entry_price=signal.entry,
            source="liquidity_expansion",
            strategy="liquidity_expansion",
            tp3=signal.tp3,
            tp4=signal.tp4,
            original_stop_loss=signal.stop,
            strategy_payload={
                "candle_model": signal.candle_model,
                "trigger": signal.trigger_kind,
                "rr_tp1": signal.rr_tp1,
                "rr_tp4": signal.rr_tp4,
                "h1_source": signal.reference.h1_source,
                "m15_source": signal.reference.m15_source,
                "stats_samples": signal.stats.samples,
            },
        ))
        log.info("liquidity_expansion_sent key=%s rr_tp1=%s", dedup_key, signal.rr_tp1)
        return True

    def _maybe_send_liquidity_expansion(self, market_data: dict[str, pd.DataFrame], session: str, now: datetime) -> bool:
        signal = self._compute_liquidity_expansion_signal(market_data, session, now)
        if signal is None:
            return False
        return self._send_liquidity_expansion(signal, session, now)

    def _dispatch_coordinator(
        self,
        coord: CoordinatorDecision,
        adelin_result: dict[str, Any] | None,
        lex_signal: LiquidityExpansionSignal | None,
        session: str,
        now: datetime,
    ) -> bool:
        mode = coord.combined_mode
        if mode == "NO_TRADE":
            return False
        if mode == "STRATEGY_1_ONLY":
            return self._maybe_send_adelin_signal(adelin_result, session, now)
        if mode == "STRATEGY_2_ONLY":
            return self._send_liquidity_expansion(lex_signal, session, now) if lex_signal else False
        if mode == "A_PLUS_PLUS":
            return self._send_a_plus_plus(coord, adelin_result, lex_signal, session, now)
        if mode == "CONFLICT":
            if self.settings.send_strategy_conflict_alert:
                self._send_strategy_conflict_alert(coord, session, now)
            return False
        if mode == "INDEPENDENT_BOTH":
            policy = self.settings.strategy_independent_both_policy
            if policy == "send_both":
                sent_a = self._maybe_send_adelin_signal(adelin_result, session, now)
                sent_b = self._send_liquidity_expansion(lex_signal, session, now) if lex_signal else False
                return sent_a or sent_b
            if policy == "send_first":
                if self._maybe_send_adelin_signal(adelin_result, session, now):
                    return True
                return self._send_liquidity_expansion(lex_signal, session, now) if lex_signal else False
            if policy == "send_best":
                rr_1 = self._adelin_rr_tp1(adelin_result)
                rr_2 = lex_signal.rr_tp1 if lex_signal else 0.0
                if rr_1 >= rr_2:
                    return self._maybe_send_adelin_signal(adelin_result, session, now)
                return self._send_liquidity_expansion(lex_signal, session, now) if lex_signal else False
            return False
        return False

    @staticmethod
    def _adelin_rr_tp1(adelin_result: dict[str, Any] | None) -> float:
        if not adelin_result:
            return 0.0
        signal = adelin_result.get("signal") or {}
        tp1 = signal.get("tp1") or {}
        if isinstance(tp1, dict):
            try:
                return float(tp1.get("rr", 0) or 0)
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def _send_a_plus_plus(
        self,
        coord: CoordinatorDecision,
        adelin_result: dict[str, Any] | None,
        lex_signal: LiquidityExpansionSignal | None,
        session: str,
        now: datetime,
    ) -> bool:
        if not coord.strategy_1_signal or lex_signal is None:
            return False
        s1 = coord.strategy_1_signal
        level = lex_signal.reference.h1_ref_low if lex_signal.direction == "LONG" else lex_signal.reference.h1_ref_high
        dedup_key = f"aplusplus:{self.last_symbol}:{lex_signal.direction}:{round(level, 1)}:{session}:{now.date().isoformat()}"
        if dedup_key in self.deduplicator.sent_keys:
            return False
        if self.settings.liquidity_expansion_require_risk_ok:
            risk_payload = {
                "signal_id": dedup_key,
                "entry": s1.get("entry"),
                "sl": s1.get("sl"),
                "tp": (s1.get("tp1") or {}).get("price") if isinstance(s1.get("tp1"), dict) else s1.get("tp1"),
                "direction": "BUY" if lex_signal.direction == "LONG" else "SELL",
            }
            risk = self.risk.validate(risk_payload, spread=self.last_spread or 0.0, session=session)
            if not risk.get("accepted", False):
                log.info("a_plus_plus_rejected_by_risk reasons=%s", risk.get("rejection_reasons"))
                return False
        text = self._format_a_plus_plus_message(s1, lex_signal, coord)
        result = self.telegram_bot.send_text(text)
        if not result.get("ok"):
            log.warning("a_plus_plus_send_failed key=%s result=%s", dedup_key, result)
            return False
        self.deduplicator.sent_keys.add(dedup_key)
        self.stats.signals_sent += 1
        self.stats.liquidity_expansion_sent += 1
        if self.settings.liquidity_expansion_require_risk_ok:
            self.risk.register_signal(dedup_key)
        adelin_entry = float(s1.get("entry") or lex_signal.entry)
        adelin_stop = float(s1.get("sl") or lex_signal.stop)
        adelin_tp1 = (s1.get("tp1") or {}).get("price") if isinstance(s1.get("tp1"), dict) else s1.get("tp1")
        adelin_tp2 = (s1.get("tp2") or {}).get("price") if isinstance(s1.get("tp2"), dict) else s1.get("tp2")
        self.trades.append(VirtualTrade(
            trade_id=f"vt-{len(self.trades) + 1}",
            signal_key=dedup_key,
            symbol=self.last_symbol,
            direction=lex_signal.direction,
            zone_id=f"a_plus_plus_{round(level, 2)}",
            signal_time=lex_signal.timestamp_utc,
            entry_area_low=adelin_entry,
            entry_area_high=adelin_entry,
            stop_loss=adelin_stop,
            tp1=float(adelin_tp1) if adelin_tp1 is not None else lex_signal.tp1,
            tp2=float(adelin_tp2) if adelin_tp2 is not None else lex_signal.tp2,
            status="ENTERED",
            entry_time=lex_signal.timestamp_utc,
            entry_price=adelin_entry,
            source="coordinator",
            strategy="A_PLUS_PLUS",
            tp3=lex_signal.tp3,
            tp4=lex_signal.tp4,
            original_stop_loss=adelin_stop,
            strategy_payload={
                "combined_mode": "A_PLUS_PLUS",
                "distance_pips": coord.distance_pips,
                "strategy_1": s1,
                "strategy_2": {
                    "entry": lex_signal.entry,
                    "stop": lex_signal.stop,
                    "tp1": lex_signal.tp1,
                    "tp2": lex_signal.tp2,
                    "tp3": lex_signal.tp3,
                    "tp4": lex_signal.tp4,
                    "rr_tp1": lex_signal.rr_tp1,
                    "rr_tp4": lex_signal.rr_tp4,
                    "trigger_kind": lex_signal.trigger_kind,
                    "candle_model": lex_signal.candle_model,
                },
            },
        ))
        log.info("a_plus_plus_sent key=%s distance_pips=%s", dedup_key, coord.distance_pips)
        return True

    def _send_strategy_conflict_alert(self, coord: CoordinatorDecision, session: str, now: datetime) -> bool:
        dedup_key = f"conflict:{self.last_symbol}:{session}:{now.date().isoformat()}:{round(coord.distance_pips or 0, 1)}"
        if dedup_key in self.deduplicator.sent_keys:
            return False
        s1 = coord.strategy_1_signal or {}
        s2 = coord.strategy_2_signal or {}
        lines = [
            f"{self.last_symbol} - STRATEGY CONFLICT",
            f"Strategy 1.0: {s1.get('direction', '-')} @ {s1.get('entry', '-')}",
            f"Strategy 2.0: {s2.get('direction', '-')} @ {s2.get('entry', '-')}",
            f"Distance: {coord.distance_pips} pips",
            "",
            "Auto-signals soppressi su questa zona. Decisione manuale richiesta.",
            "Disclaimer: Paper/demo signal only. No real-money execution.",
        ]
        result = self.telegram_bot.send_text("\n".join(lines))
        if result.get("ok"):
            self.deduplicator.sent_keys.add(dedup_key)
            log.info("strategy_conflict_alert_sent key=%s", dedup_key)
            return True
        return False

    @staticmethod
    def _format_a_plus_plus_message(adelin_signal: dict[str, Any], lex_signal: LiquidityExpansionSignal, coord: CoordinatorDecision) -> str:
        direction = lex_signal.direction
        tp1 = adelin_signal.get("tp1") or {}
        tp2 = adelin_signal.get("tp2") or {}
        lines = [
            f"{lex_signal.symbol} - A++ SETUP (STRATEGY 1.0 + 2.0 CONFLUENCE)",
            f"Direzione: {direction}",
            f"Distance fra entry 1.0 e 2.0: {coord.distance_pips} pips",
            "",
            "STRATEGY 1.0 (Adelin):",
            f"Entry: {adelin_signal.get('entry')}",
            f"Stop: {adelin_signal.get('sl')} ({adelin_signal.get('sl_pips', '-')} pips)",
            f"TP1: {tp1.get('price', '-')} (RR {tp1.get('rr', '-')})",
            f"TP2: {tp2.get('price', '-')} (RR {tp2.get('rr', '-')})",
            "",
            "STRATEGY 2.0 (Liquidity Expansion):",
            f"H1 level: {('LOW' if direction == 'LONG' else 'HIGH')} {lex_signal.reference.h1_ref_low if direction == 'LONG' else lex_signal.reference.h1_ref_high}",
            f"Entry: {lex_signal.entry} | Stop: {lex_signal.stop}",
            f"TP1-TP4: {lex_signal.tp1} / {lex_signal.tp2} / {lex_signal.tp3} / {lex_signal.tp4}",
            f"RR TP1: {lex_signal.rr_tp1} | RR TP4: {lex_signal.rr_tp4}",
            "",
            "Confluenza Strategia 1.0 + Strategia 2.0",
            "Gestione: alla presa del TP1 lo stop e' spostato a BE automaticamente (lato Strategy 2.0).",
            "Disclaimer: Paper/demo signal only. No real-money execution.",
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_liquidity_expansion_message(signal: LiquidityExpansionSignal, *, lot_size: float | None) -> str:
        ref = signal.reference
        level_name = "LOW" if signal.direction == "LONG" else "HIGH"
        level_value = ref.h1_ref_low if signal.direction == "LONG" else ref.h1_ref_high
        lines = [
            f"{signal.symbol} - LIQUIDITY EXPANSION MODEL (STRATEGY 2.0)",
            f"Direzione: {signal.direction}",
            f"Modello candela: {signal.candle_model}",
            f"Livello H1: {level_name} {level_value} (fonte: {ref.h1_source})",
            f"Filtro M15 :45: source={ref.m15_source} high={ref.m15_ref_high} low={ref.m15_ref_low} -> sequenza valida",
            f"Entry: {signal.entry} (trigger: {signal.trigger_kind})",
            f"Stop: {signal.stop} (Max Excursion x 1.25)",
            f"TP1: {signal.tp1} ({signal.tp1_basis})",
            f"TP2: {signal.tp2} (quartile_50)",
            f"TP3: {signal.tp3} (quartile_75)",
            f"TP4: {signal.tp4} (quartile_100)",
            f"Stats H1: mae_avg={signal.stats.mae_avg_pips} pips | max_exc={signal.stats.max_excursion_pips} pips | avg_exp={signal.stats.avg_expansion_pips} pips | max_exp={signal.stats.max_expansion_pips} pips | samples={signal.stats.samples}",
            f"RR TP1: {signal.rr_tp1} | RR TP4: {signal.rr_tp4}",
        ]
        if lot_size is not None:
            lines.append(f"Lot size suggerito: {lot_size}")
        lines.extend([
            "Gestione: alla presa del TP1 lo stop e' spostato a BE automaticamente.",
            "Reason codes:",
        ])
        for code in signal.reason_codes:
            lines.append(f"- {code}")
        lines.append("Disclaimer: Paper/demo signal only. No real-money execution.")
        return "\n".join(lines)

    def _maybe_send_session_behaviour_alert(self, decision: ScalpingDecision, session: str) -> bool:
        if not self.settings.time_behaviour_alerts:
            return False
        event = decision.intraday_context.get("session_candle", {}) if decision.intraday_context else {}
        time_ctx = decision.intraday_context.get("time_behaviour", {}) if decision.intraday_context else {}
        classification = event.get("classification", "NO_CLEAR_SESSION_BEHAVIOUR")
        time_window = time_ctx.get("time_window", "unknown")
        if classification == "NO_CLEAR_SESSION_BEHAVIOUR" and time_window not in {"pre_london", "pre_ny"}:
            return False
        if classification == "NO_CLEAR_SESSION_BEHAVIOUR" and not self.settings.send_session_prep_alerts:
            return False
        if "MANIPULATION" in classification and not self.settings.send_session_manipulation_alerts:
            return False
        if "OPEN_DRIVE" in classification and not self.settings.send_open_drive_alerts:
            return False
        count = self.session_behaviour_session_counts.get(session, 0)
        if count >= self.settings.max_session_behaviour_alerts_per_session:
            return False
        level = event.get("swept_level_name") or time_window
        key = f"{session}:{time_window}:{classification}:{level}:{datetime.now(timezone.utc).date().isoformat()}"
        last = self.session_behaviour_alert_memory.get(key)
        if last and (datetime.now(timezone.utc) - last) < timedelta(minutes=self.settings.session_behaviour_alert_cooldown_minutes):
            return False
        text = self._format_session_behaviour_alert(decision, event, time_ctx, classification)
        result = self.telegram_bot.send_text(text)
        if result.get("ok"):
            self.session_behaviour_alert_memory[key] = datetime.now(timezone.utc)
            self.session_behaviour_session_counts[session] = count + 1
            log.info("session_behaviour_alert_sent key=%s", key)
            return True
        return False

    @staticmethod
    def _format_session_behaviour_alert(decision: ScalpingDecision, event: dict, time_ctx: dict, classification: str) -> str:
        if classification == "NO_CLEAR_SESSION_BEHAVIOUR":
            title = f"{decision.symbol} - SESSION PREP"
            body = [
                f"Fase: {time_ctx.get('session_name', time_ctx.get('time_window', '-'))}",
                "Zone da osservare: vedere /watch e /plan.",
                "NO ENTRY.",
            ]
        elif "OPEN_DRIVE" in classification or "ACCEPTED_BREAKOUT" in classification:
            title = f"{decision.symbol} - OPEN DRIVE CONTINUATION"
            body = [
                f"Comportamento: {classification}",
                f"Livello: {event.get('swept_level_name')} {event.get('swept_level')}",
                "No reversal contro breakout accettato.",
                "Cerco solo pullback coerente o no trade.",
            ]
        else:
            title = f"{decision.symbol} - SESSION OPEN BEHAVIOUR"
            body = [
                f"Comportamento: {classification}",
                f"Livello preso: {event.get('swept_level_name')} {event.get('swept_level')}",
                f"Candela: wick={event.get('wick_ratio')} body={event.get('body_ratio')} close={event.get('close_location')}",
                "Serve: M1/M5 CHOCH, displacement, FVG/IFVG, target valido.",
                "NO ENTRY ANCORA.",
            ]
        reasons = event.get("reason_codes", [])[:8]
        return "\n".join([title, "", *body, "", "Reason codes:", *[f"- {reason}" for reason in reasons], "Disclaimer: Paper/demo signal only. No real-money execution."])

    def _maybe_send_reaction_alert(self, decision: ScalpingDecision, session: str) -> bool:
        if self.settings.send_triggered_only:
            return False
        sweeps = decision.liquidity.get("sweeps", []) if decision.liquidity else []
        if decision.state not in {"WATCH", "APPROACHING", "ARMED", "SWEEPING_INTRABAR", "CONFIRMED_SWEEP"} or not sweeps:
            return False
        cluster = self._reaction_cluster(decision, sweeps)
        if cluster is not None:
            return self._send_reaction_cluster_alert(decision, cluster, session)
        sweep = sweeps[0]
        if sweep.get("status") not in {"WATCH", "APPROACHING", "ARMED", "SWEEPING_INTRABAR", "CONFIRMED_SWEEP"}:
            return False
        pool = self._pool_for_sweep(sweep.get("pool_id")) or self._pool_for_sweep_in_decision(decision, sweep.get("pool_id"))
        distance_pips = float(pool.get("distance_pips", 0) if pool else 0)
        milestone = self._alert_milestone(distance_pips, sweep.get("status"))
        if milestone is None:
            return False
        if milestone == "far_prep":
            far_count = sum(1 for memory in self.zone_alert_memory.values() if memory.get("session") == session and "far_prep" in memory.get("milestones_sent", set()))
            if far_count >= self.settings.max_far_prep_alerts_per_session:
                return False
        count = self.reaction_alert_session_counts.get(session, 0)
        if count >= self.settings.max_reaction_alerts_per_session:
            return False
        zone_id = sweep.get("pool_id") or "unknown"
        memory = self.zone_alert_memory.setdefault(zone_id, {"session": session, "milestones_sent": set(), "last_alert_time": None, "count": 0})
        if memory.get("session") != session:
            memory = {"session": session, "milestones_sent": set(), "last_alert_time": None, "count": 0}
            self.zone_alert_memory[zone_id] = memory
        if milestone in memory["milestones_sent"]:
            return False
        if memory["count"] >= self.settings.max_alerts_per_zone_per_session:
            return False
        key = f"{decision.symbol}:{zone_id}:{milestone}:{session}"
        now = datetime.now(timezone.utc)
        last = memory.get("last_alert_time") or self.reaction_alerts.get(key)
        if last and (now - last) < timedelta(minutes=self.settings.reaction_alert_cooldown_minutes):
            log.info("reaction_alert_skipped_cooldown key=%s", key)
            return False
        text = self._format_reaction_alert(decision, sweep, pool, milestone)
        result = self.telegram_bot.send_text(text)
        if result.get("ok"):
            self.reaction_alerts[key] = now
            memory["milestones_sent"].add(milestone)
            memory["last_alert_time"] = now
            memory["count"] += 1
            self.reaction_alert_session_counts[session] = count + 1
            log.info("reaction_alert_sent key=%s", key)
            return True
        return False

    def _alert_milestone(self, distance_pips: float, sweep_status: str | None) -> str | None:
        if distance_pips > 500:
            return None
        if sweep_status == "CONFIRMED_SWEEP":
            return "confirmed_sweep"
        if sweep_status == "SWEEPING_INTRABAR":
            return "sweep_intrabar" if self.settings.send_sweep_intrabar_alerts else None
        if distance_pips <= self.settings.imminent_reaction_distance_pips and self.settings.send_armed_reaction_alerts:
            return "imminent_50"
        if distance_pips <= self.settings.armed_alert_distance_pips and self.settings.send_armed_reaction_alerts:
            return "armed_80"
        if distance_pips <= self.settings.approaching_alert_distance_pips and self.settings.send_approaching_alerts:
            return "approaching_150"
        if distance_pips <= self.settings.far_prep_alert_distance_pips and self.settings.allow_far_prep_alerts:
            return "far_prep"
        return None

    def _reaction_cluster(self, decision: ScalpingDecision, sweeps: list[dict]) -> dict | None:
        items = []
        for sweep in sweeps:
            status = sweep.get("status")
            if status not in {"WATCH", "APPROACHING", "ARMED", "SWEEPING_INTRABAR", "CONFIRMED_SWEEP"}:
                continue
            level = sweep.get("level")
            if level is None:
                continue
            pool = self._pool_for_sweep(sweep.get("pool_id")) or self._pool_for_sweep_in_decision(decision, sweep.get("pool_id"))
            direction = self._possible_reaction_direction(sweep, pool)
            items.append({"sweep": sweep, "pool": pool, "level": float(level), "direction": direction})
        if len(items) < 2:
            return None
        items = sorted(items, key=lambda item: item["level"])
        low = min(item["level"] for item in items)
        high = max(item["level"] for item in items)
        directions = {item["direction"] for item in items if item["direction"] != "UNCLEAR"}
        multiplier = 2 if len(directions) > 1 else 1
        tolerance = pips_to_price(decision.symbol, self.settings.reaction_cluster_tolerance_pips * multiplier)
        if high - low > tolerance:
            return None
        direction_label = "UNCLEAR / LIQUIDITY SEARCH" if len(directions) != 1 else f"{next(iter(directions))} candidate"
        return {"low": low, "high": high, "items": items, "direction": direction_label, "statuses": [item["sweep"].get("status") for item in items]}

    def _send_reaction_cluster_alert(self, decision: ScalpingDecision, cluster: dict, session: str) -> bool:
        key = f"{decision.symbol}:reaction_cluster:{round(cluster['low'], 1)}:{round(cluster['high'], 1)}:{session}"
        now = datetime.now(timezone.utc)
        last = self.reaction_alerts.get(key)
        if last and (now - last) < timedelta(minutes=self.settings.reaction_cluster_cooldown_minutes):
            decision.reason_codes.append("duplicate_reaction_alert_suppressed")
            return False
        if "CONFIRMED_SWEEP" in cluster["statuses"]:
            count = self.reaction_cluster_confirmed_counts.get(key, 0)
            if count >= self.settings.max_confirmed_sweep_alerts_per_cluster:
                decision.reason_codes.append("confirmed_sweep_cluster_waiting_trigger")
                return False
        text = self._format_reaction_cluster_alert(decision, cluster)
        result = self.telegram_bot.send_text(text)
        if result.get("ok"):
            self.reaction_alerts[key] = now
            if "CONFIRMED_SWEEP" in cluster["statuses"]:
                self.reaction_cluster_confirmed_counts[key] = self.reaction_cluster_confirmed_counts.get(key, 0) + 1
            decision.reason_codes.append("reaction_alert_clustered")
            self.stats.signals_sent += 1
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
    def _pool_for_sweep_in_decision(decision: ScalpingDecision, pool_id: str | None) -> dict | None:
        if not pool_id:
            return None
        for pool in decision.liquidity.get("pools", []):
            if pool.get("id") == pool_id:
                return pool
        return None

    @staticmethod
    def _possible_reaction_direction(sweep: dict, pool: dict | None = None) -> str:
        text = " ".join(
            [
                str(sweep.get("direction", "")),
                str(sweep.get("reason_codes", "")),
                str(pool.get("side", "") if pool else ""),
                str(pool.get("pool_type", "") if pool else ""),
            ]
        ).lower()
        if "bearish_reversal" in text or "buy_side" in text or "high" in text or "possible_short_after_buy_side_sweep" in text:
            return "SHORT"
        if "bullish_reversal" in text or "sell_side" in text or "low" in text or "possible_long_after_sell_side_sweep" in text:
            return "LONG"
        return "UNCLEAR"

    @staticmethod
    def _format_reaction_cluster_alert(decision: ScalpingDecision, cluster: dict) -> str:
        low = cluster["low"]
        high = cluster["high"]
        reasons = ["reaction_alert_clustered"]
        if cluster["direction"] == "UNCLEAR / LIQUIDITY SEARCH":
            reasons.extend(["direction_unclear_two_sided_sweep", "liquidity_search_waiting_direction"])
        lines = [
            f"{decision.symbol} — LIQUIDITY REACTION CLUSTER",
            "NO ENTRY",
            "",
            f"Area: {low:.2f} - {high:.2f}",
            "Stato: sweep/reaction area",
            f"Direzione: {cluster['direction']}",
            "",
            "Piano teorico:",
            f"Scenario LONG sopra {low:.2f} solo dopo CHOCH/FVG bullish.",
            f"Scenario SHORT sotto {high:.2f} solo dopo CHOCH/FVG bearish.",
            "",
            "Manca:",
            "- direzione chiara",
            "- CHOCH",
            "- FVG/IFVG",
            "",
            "Reason codes:",
            *[f"- {reason}" for reason in reasons],
            "Disclaimer: Paper/demo signal only. No real-money execution.",
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_reaction_alert(decision: ScalpingDecision, sweep: dict, pool: dict | None, milestone: str = "armed") -> str:
        pool_type = pool.get("pool_type") if pool else "liquidity"
        distance = pool.get("distance_pips") if pool else "-"
        current_price = decision.intraday_context.get("current_price") or decision.liquidity.get("price")
        if pool and pool.get("level") is not None and current_price is not None:
            try:
                distance = round(price_to_pips(decision.symbol, abs(float(pool["level"]) - float(current_price))), 1)
            except (TypeError, ValueError):
                pass
        confluences = []
        if pool:
            confluences.extend(pool.get("confluences", []))
        confluences.extend(sweep.get("reason_codes", []))
        title = {
            "far_prep": "ZONA IN PREPARAZIONE",
            "approaching_150": "ZONA IN AVVICINAMENTO",
            "armed_80": "REACTION AREA VICINA",
            "imminent_50": "REACTION AREA IMMINENTE",
            "sweep_intrabar": "SWEEP IN CORSO",
            "confirmed_sweep": "SWEEP CONFERMATA, ASPETTO TRIGGER",
        }.get(milestone, "POSSIBILE REAZIONE LIQUIDITY")
        possible_direction = f"{ScalpingScanner._possible_reaction_direction(sweep, pool)} candidate"
        if possible_direction.startswith("UNCLEAR"):
            possible_direction = "UNCLEAR / LIQUIDITY SEARCH"
        lines = [f"{decision.symbol} - {title}", "NO ENTRY", f"Direzione possibile: {possible_direction}", f"Livello: {sweep.get('level')}", f"Tipo: {pool_type}", f"Distanza: {distance} pips", f"Stato: {sweep.get('status')}", "Confluence:"]
        lines.extend(f"- {item}" for item in confluences[:8])
        if decision.theoretical_targets or decision.entry_area or decision.stop:
            lines.extend(["Piano teorico non operativo:", f"- Entry teorica: {decision.entry_area[0]:.2f} - {decision.entry_area[1]:.2f}" if decision.entry_area else "- Entry teorica: solo dopo trigger", f"- SL teorico: {decision.stop if decision.stop is not None else '-'}", "TP teorici:"])
            if decision.theoretical_targets:
                for target in decision.theoretical_targets[:3]:
                    lines.append(f"- {target.get('label')} teorico: {target.get('price')} - {target.get('basis')} - {ScalpingScanner._target_distance_text(decision, target)}")
            else:
                lines.append("- target validation finale ancora da confermare")
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

    @staticmethod
    def _target_distance_text(decision: ScalpingDecision, target: dict) -> str:
        entry = decision.entry
        if entry is None and decision.entry_area:
            entry = round((decision.entry_area[0] + decision.entry_area[1]) / 2, 2)
        price = target.get("price")
        if entry is not None and price is not None:
            try:
                distance = abs(float(price) - float(entry))
                pips = price_to_pips(decision.symbol, distance)
                return f"{pips:.1f}".rstrip("0").rstrip(".") + f" pips / {distance:.2f}$"
            except (TypeError, ValueError):
                pass
        return f"{target.get('distance_pips', '-')} pips"

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
            if trade.status == "PENDING_ENTRY":
                self._update_pending_trade(trade, market_data, now, previous_scan)
            elif trade.status == "ENTERED":
                previous_status = trade.status
                self._update_trade_outcome(trade, market_data, now)
                if trade.status != previous_status:
                    self._maybe_send_reentry_alert(trade)
            if trade.status == "STOP_HIT" and self.settings.enable_reentry_analysis:
                previous_reentry = trade.reentry_state
                self._update_reentry(trade, market_data, now)
                if trade.reentry_state != previous_reentry:
                    self._maybe_send_reentry_alert(trade)

    def _update_pending_trade(self, trade: VirtualTrade, market_data: dict[str, pd.DataFrame], now: datetime, previous_scan: datetime | None) -> None:
        frame = market_data.get("M1")
        if frame is None or len(frame) == 0:
            return
        recent = frame.copy()
        if "time" in recent.columns and previous_scan is not None:
            recent = recent[(pd.to_datetime(recent["time"], utc=True) >= pd.Timestamp(previous_scan)) & (pd.to_datetime(recent["time"], utc=True) <= pd.Timestamp(now))]
        if len(recent) == 0:
            recent = frame.tail(5)
        for _, candle in recent.iterrows():
            high = float(candle["h"] if "h" in candle else candle.get("high"))
            low = float(candle["l"] if "l" in candle else candle.get("low"))
            when = candle["time"].to_pydatetime() if "time" in candle and hasattr(candle["time"], "to_pydatetime") else now
            if trade.direction == "LONG":
                entry_touched = low <= trade.entry_area_high and high >= trade.entry_area_low
                stop_touched = trade.stop_loss is not None and low <= trade.stop_loss
            else:
                entry_touched = high >= trade.entry_area_low and low <= trade.entry_area_high
                stop_touched = trade.stop_loss is not None and high >= trade.stop_loss
            if stop_touched:
                trade.status = "INVALIDATED_BEFORE_ENTRY"
                trade.reason_codes.append("setup_invalidated_before_entry")
                if entry_touched:
                    trade.reason_codes.append("ambiguous_intrabar_path_assume_conservative_stop")
                trade.stop_hit_price = trade.stop_loss
                trade.stop_hit_time = when
                return
            if entry_touched:
                trade.status = "ENTERED"
                trade.entry_time = when
                trade.entry_price = (trade.entry_area_low + trade.entry_area_high) / 2
                trade.source = "M1"
                return

    def _update_trade_outcome(self, trade: VirtualTrade, market_data: dict[str, pd.DataFrame], now: datetime) -> None:
        if trade.status != "ENTERED":
            return
        frame = market_data.get("M1")
        if frame is None or len(frame) == 0 or trade.stop_loss is None:
            return
        recent = frame.tail(5)
        for _, candle in recent.iterrows():
            high = float(candle["h"])
            low = float(candle["l"])
            when = candle["time"].to_pydatetime() if "time" in candle and hasattr(candle["time"], "to_pydatetime") else now
            if trade.strategy == "liquidity_expansion":
                self._update_liquidity_expansion_outcome(trade, candle_high=high, candle_low=low, when=when)
                if trade.status in {"TP4_HIT", "STOP_HIT", "BE_HIT"}:
                    return
                continue
            if trade.direction == "LONG":
                if low <= trade.stop_loss:
                    trade.status = "STOP_HIT"
                    trade.stop_hit_price = trade.stop_loss
                    trade.stop_hit_time = when
                    trade.reentry_state = "REENTRY_WATCH"
                    trade.reason_codes.append("stop_hit_after_entry")
                    trade.reentry_reason_codes = ["ambiguous_intrabar_path_assume_conservative_stop"] if trade.tp1 and high >= trade.tp1 else []
                    return
                if trade.tp1 and high >= trade.tp1:
                    trade.status = "TP1_HIT"
                    return
            if trade.direction == "SHORT":
                if high >= trade.stop_loss:
                    trade.status = "STOP_HIT"
                    trade.stop_hit_price = trade.stop_loss
                    trade.stop_hit_time = when
                    trade.reentry_state = "REENTRY_WATCH"
                    trade.reason_codes.append("stop_hit_after_entry")
                    trade.reentry_reason_codes = ["ambiguous_intrabar_path_assume_conservative_stop"] if trade.tp1 and low <= trade.tp1 else []
                    return
                if trade.tp1 and low <= trade.tp1:
                    trade.status = "TP1_HIT"
                    return

    def _update_liquidity_expansion_outcome(self, trade: VirtualTrade, *, candle_high: float, candle_low: float, when: datetime) -> None:
        if trade.stop_loss is None or trade.entry_price is None:
            return
        direction = trade.direction
        if direction == "LONG" and candle_low <= trade.stop_loss:
            trade.status = "BE_HIT" if trade.be_activated else "STOP_HIT"
            trade.stop_hit_price = trade.stop_loss
            trade.stop_hit_time = when
            return
        if direction == "SHORT" and candle_high >= trade.stop_loss:
            trade.status = "BE_HIT" if trade.be_activated else "STOP_HIT"
            trade.stop_hit_price = trade.stop_loss
            trade.stop_hit_time = when
            return
        tps = [trade.tp1, trade.tp2, trade.tp3, trade.tp4]
        hits = [trade.tp1_hit, trade.tp2_hit, trade.tp3_hit, trade.tp4_hit]
        labels = ["TP1_HIT", "TP2_HIT", "TP3_HIT", "TP4_HIT"]
        attr_names = ["tp1_hit", "tp2_hit", "tp3_hit", "tp4_hit"]
        for idx, (tp, hit, label, attr) in enumerate(zip(tps, hits, labels, attr_names)):
            if tp is None or hit:
                continue
            reached = (direction == "LONG" and candle_high >= tp) or (direction == "SHORT" and candle_low <= tp)
            if reached:
                setattr(trade, attr, True)
                trade.status = label
                if idx == 0:
                    trade.stop_loss = trade.entry_price
                    trade.be_activated = True

    def _update_reentry(self, trade: VirtualTrade, market_data: dict[str, pd.DataFrame], now: datetime) -> None:
        if trade.stop_hit_time is None or trade.stop_loss is None:
            return
        if now - trade.stop_hit_time > timedelta(minutes=self.settings.reentry_max_wait_minutes):
            trade.reentry_state = "NO_REENTRY"
            trade.reentry_reason_codes.append("reentry_window_expired")
            return
        context = evaluate_reentry(
            symbol=trade.symbol,
            original_signal_id=trade.signal_key,
            direction=trade.direction,
            original_entry=(trade.entry_area_low + trade.entry_area_high) / 2,
            original_stop=trade.stop_loss,
            stop_hit_price=trade.stop_hit_price or trade.stop_loss,
            stop_hit_time=trade.stop_hit_time,
            current_price=float(self.last_price or 0.0),
            m1=market_data.get("M1"),
            m5=market_data.get("M5"),
            vwap_snapshot=(self.latest_analysis.liquidity.get("vwap") if self.latest_analysis else None),
            liquidity_pools=(self.latest_analysis.liquidity.get("pools", []) if self.latest_analysis else []),
            spread_pips=float(self.last_spread or 0.0),
            settings=self.settings,
        )
        trade.reentry_state = context.state
        trade.reentry_reason_codes = context.reason_codes

    def _maybe_send_reentry_alert(self, trade: VirtualTrade) -> bool:
        alert_state = trade.reentry_state if trade.status == "STOP_HIT" and trade.reentry_state in {"REENTRY_CANDIDATE", "REENTRY_VALID", "NO_REENTRY"} else trade.status
        if alert_state not in {"STOP_HIT", "REENTRY_CANDIDATE", "REENTRY_VALID", "NO_REENTRY"}:
            return False
        key = f"{trade.trade_id}:{alert_state}"
        if key in self.reentry_alert_memory:
            return False
        result = self.telegram_bot.send_text(self._format_reentry_alert(trade, alert_state))
        if result.get("ok"):
            self.reentry_alert_memory[key] = datetime.now(timezone.utc)
            log.info("reentry_alert_sent key=%s", key)
            return True
        return False

    @staticmethod
    def _format_reentry_alert(trade: VirtualTrade, alert_state: str) -> str:
        reasons = trade.reentry_reason_codes or trade.reason_codes
        if alert_state == "STOP_HIT":
            lines = [
                f"{trade.symbol} - STOP HIT",
                f"Vecchio setup: {trade.direction}",
                f"Stop: {trade.stop_loss}",
                f"Prezzo stop: {trade.stop_hit_price}",
                "Stato: REENTRY_WATCH",
                "Valuto se era stop sweep o invalidazione reale.",
                "NO REENTRY ANCORA.",
            ]
        elif alert_state == "REENTRY_CANDIDATE":
            lines = [
                f"{trade.symbol} - REENTRY CANDIDATE",
                "Lo stop e' stato preso, ma il prezzo sta rientrando nella direzione originale.",
                "Stato: REENTRY_CANDIDATE",
                "Serve ancora:",
                "- CHOCH M1/M5",
                "- FVG/IFVG",
                "- nuovo retest",
                "- target valido",
                "- volatilita ok",
                "NO ENTRY ANCORA.",
            ]
        elif alert_state == "REENTRY_VALID":
            lines = [
                f"{trade.symbol} - REENTRY VALID",
                f"Direzione: {trade.direction}",
                "Motivi:",
                *[f"- {reason}" for reason in reasons[:8]],
                "Stato: REENTRY_VALID",
            ]
        else:
            lines = [
                f"{trade.symbol} - NO REENTRY",
                "Stop preso, ma non conviene rientrare.",
                "Motivi:",
                *[f"- {reason}" for reason in reasons[:8]],
                "Non rientrare.",
            ]
        lines.append("Disclaimer: Paper/demo signal only. No real-money execution.")
        return "\n".join(lines)

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
                f"Adelin: {'on' if self.settings.adelin_enabled else 'off'} | ultimo mode: {(self.latest_adelin_result or {}).get('setup_mode', '-')}",
                "Report automatici analisi: disattivi",
                f"Alert automatici: approaching={'on' if self.settings.send_approaching_alerts else 'off'} | armed={'on' if self.settings.send_armed_reaction_alerts else 'off'} | sweep={'on' if self.settings.send_sweep_intrabar_alerts else 'off'} | triggered_only={'on' if self.settings.send_triggered_only else 'off'} | cooldown={self.settings.reaction_alert_cooldown_minutes}m",
                f"Scan ogni: {self.scan_interval_seconds} secondi",
                f"Ultimo scan: {self._fmt_dt(self.last_scan)}",
                f"Prossimo scan stimato: {self._fmt_dt(self.next_scan_at)}",
                f"Primo scan silenzioso: {'completato' if self.stats.first_silent_scan_completed else 'non completato'}",
                f"Max segnali per scan: {self.max_alerts_per_scan}",
                f"Ultimo aggiornamento dati: {self._fmt_dt(self.last_market_update)}",
                f"Watch zone attive: {len([z for z in self.latest_zones if z.role != 'HTF_CONTEXT' and float(z.metadata.get('distance_pips', 99999)) <= 150])}",
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
        header = "\n".join(
            [
                "ANALISI INTERNA",
                f"Prezzo: {self.last_price if self.last_price is not None else '-'}",
                f"Bid/Ask: {self.last_bid if self.last_bid is not None else '-'} / {self.last_ask if self.last_ask is not None else '-'}",
                f"Spread pips: {self.last_spread if self.last_spread is not None else '-'}",
                f"Ultimo update dati: {self._fmt_dt(self.last_market_update)}",
                "",
            ]
        )
        adelin = "\n\nADELIN\n" + (format_adelin_signal(self.latest_adelin_result["signal"], self.latest_adelin_result) if self.latest_adelin_result and self.latest_adelin_result.get("signal") else format_rejection_summary(self.latest_adelin_result or {"rejected": ["not_run"], "setup_mode": "NO_TRADE"}))
        coordinator_section = "\n\n" + self._format_coordinator_section()
        return header + format_scalping_decision(self.latest_analysis) + adelin + coordinator_section

    def _format_coordinator_section(self) -> str:
        adelin = self.latest_adelin_result or {}
        adelin_signal = adelin.get("signal")
        adelin_status = "valid" if adelin_signal else "no_trade"
        adelin_mode = (adelin_signal or {}).get("setup_mode") or adelin.get("setup_mode") or "NO_TRADE"
        adelin_rejected = adelin.get("rejected") or []
        lex = self.latest_liquidity_expansion_signal
        lex_status = "valid" if lex else "no_trade"
        coord = self.latest_coordinator_decision
        lines = [
            "COORDINATOR",
            f"Strategy 1.0 (Adelin): {adelin_status} | setup_mode={adelin_mode}",
            f"Strategy 2.0 (Liquidity Expansion): {lex_status}",
        ]
        if coord is not None:
            lines.append(f"Coordinator mode: {coord.combined_mode}")
            if coord.distance_pips is not None:
                lines.append(f"Distance 1.0 vs 2.0: {coord.distance_pips} pips")
            if coord.suppress_reason:
                lines.append(f"Suppress reason: {coord.suppress_reason}")
            if coord.warnings:
                lines.append("Warnings:")
                for w in coord.warnings[:6]:
                    lines.append(f"- {w}")
        else:
            lines.append("Coordinator mode: not_run")
        if adelin_rejected:
            lines.append("Strategy 1.0 rejected reasons:")
            for r in adelin_rejected[:5]:
                lines.append(f"- {r}")
        return "\n".join(lines)

    def format_watch(self) -> str:
        operative = [z for z in self.latest_zones if z.role != "HTF_CONTEXT" and float(z.metadata.get("distance_pips", 99999)) <= 150]
        session_behaviour = (self.latest_analysis.intraday_context.get("session_candle", {}) if self.latest_analysis else {}).get("classification", "-")
        if not operative:
            return f"Watch zone operative: 0\nSession behaviour: {session_behaviour}\nZone HTF lontane disponibili solo come contesto in /plan.\nNO ENTRY se non TRIGGERED."
        lines = ["WATCH ZONE OPERATIVE", f"Session behaviour: {session_behaviour}", "NO ENTRY se non TRIGGERED."]
        for idx, zone in enumerate(operative[:5], start=1):
            lines.extend(
                [
                    "",
                    f"{idx}. {zone.timeframe} {zone.zone_type}",
                    f"Range: {zone.low:.2f} - {zone.high:.2f}",
                    f"Stato: {zone.state}",
                    f"Ruolo: {zone.role}",
                    f"Distanza: {zone.metadata.get('distance_pips', '-')} pips",
                    f"Classificazione: {zone.metadata.get('classification', '-')}",
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
                lines.append("\nLiquidity 100-500 pips in reaction map:")
                for pool in reaction:
                    lines.append(f"- {pool.get('timeframe')} {pool.get('pool_type')} {pool.get('level')} distanza={pool.get('distance_pips')} pips ({pool.get('distance_band')})")
        if self.latest_adelin_result:
            debug = self.latest_adelin_result.get("debug", {})
            levels = debug.get("liquidity_map", [])[:6]
            if levels:
                lines.append("\nAdelin liquidity / VP watch:")
                for level in levels:
                    lines.append(f"- {level.get('timeframe')} {level.get('name')} {level.get('level')} {level.get('side')}")
            lines.extend(["", "Adelin VP:", format_vp_summary(self.latest_adelin_result)])
        return "\n".join(lines)

    def format_scan_report(self, decision: ScalpingDecision | None = None) -> str:
        if not (decision or self.latest_analysis):
            return "Nessuna analisi disponibile."
        lines = ["SCAN MANUALE", "", format_scalping_decision(decision or self.latest_analysis)]
        if self.latest_adelin_result:
            lines.extend(["", "ADELIN", format_adelin_signal(self.latest_adelin_result["signal"], self.latest_adelin_result) if self.latest_adelin_result.get("signal") else format_rejection_summary(self.latest_adelin_result)])
        return "\n".join(lines)

    def format_plan(self) -> str:
        lines = ["PIANO OPERATIVO", "", format_session_summary()]
        if self.latest_analysis:
            lines.extend(["", format_scalping_decision(self.latest_analysis)])
        if self.latest_adelin_result:
            lines.extend(["", "ADELIN VP SUMMARY", format_vp_summary(self.latest_adelin_result)])
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
                    f"Stop hit: {trade.stop_hit_price or '-'} at {self._fmt_dt(trade.stop_hit_time)}",
                    f"Reentry: {trade.reentry_state}",
                    f"Motivo reentry: {', '.join(trade.reentry_reason_codes[:5]) if trade.reentry_reason_codes else '-'}",
                    f"Motivi trade: {', '.join(trade.reason_codes[:5]) if trade.reason_codes else '-'}",
                    f"SL: {trade.stop_loss} | TP1: {trade.tp1} | TP2: {trade.tp2}",
                ]
            )
        return "\n".join(lines)

    @staticmethod
    def _is_live_candle(timeframe: str, last_time: Any) -> bool:
        if last_time is None:
            return False
        try:
            ts = pd.Timestamp(last_time).to_pydatetime().astimezone(timezone.utc)
        except Exception:
            return False
        minutes = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}.get(timeframe, 1)
        return datetime.now(timezone.utc) < ts + timedelta(minutes=minutes)

    @staticmethod
    def _fmt_dt(value: datetime | None) -> str:
        if value is None:
            return "mai"
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


__all__ = ["ScalpingScanner", "ScannerStats", "VirtualTrade"]
