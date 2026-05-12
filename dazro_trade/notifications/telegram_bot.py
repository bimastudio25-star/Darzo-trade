from __future__ import annotations

import logging
from typing import Any

from dazro_trade.core.config import Settings
from dazro_trade.core.models import ScalpingDecision

log = logging.getLogger(__name__)


def safe_text(value: Any) -> str:
    return str(value).replace("\x00", "").strip()


def format_signal_message(payload: dict) -> str:
    lines = [
        f"{safe_text(payload.get('direction', 'NONE'))} {safe_text(payload.get('symbol', ''))}",
        f"Entry: {payload.get('entry')} | SL: {payload.get('sl')} | TP: {payload.get('tp', payload.get('tp1'))}",
        f"RR: {payload.get('rr')} | Risk: {payload.get('risk_pct')} | Lot: {payload.get('lot_size')}",
        f"HTF bias: {payload.get('htf_bias', payload.get('h1_bias', 'unknown'))}",
        f"Line structure: {payload.get('line_structure_state', 'unknown')}",
        f"MSNR/retest: {payload.get('msnr_retest_state', 'unknown')}",
        f"Liquidity: {payload.get('liquidity_context', payload.get('liquidity_pools', 'unknown'))}",
        f"Sweep: {payload.get('sweep_state', 'none')}",
        f"CRT: {payload.get('crt_turtle_state', payload.get('crt_direction', 'none'))}",
        f"QB: {payload.get('quarterly_qb_state', payload.get('qb_alignment', 'neutral'))}",
        f"SMT: {payload.get('smt_state', payload.get('smt_status', 'neutral'))}",
        f"Macro: {payload.get('macro_state', payload.get('macro_status', 'uncertain'))}",
        f"Orderflow: {payload.get('orderflow_state', payload.get('orderflow_status', 'disabled'))}",
        f"Invalidation: {payload.get('invalidation_level')}",
        f"Confidence: {payload.get('confidence')}",
        f"Timestamp UTC: {payload.get('timestamp_utc', payload.get('timestamp'))}",
        "Disclaimer: Paper/demo signal only. No real-money execution.",
    ]
    return "\n".join(safe_text(line) for line in lines)


def _fmt_price(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return safe_text(value)


def format_scalping_decision(decision: ScalpingDecision) -> str:
    zone = decision.primary_zone
    direction_label = {"LONG": "LONG", "SHORT": "SHORT", "WAIT": "WAIT"}.get(decision.direction, "WAIT")
    if decision.state == "TRIGGERED" and decision.direction in {"LONG", "SHORT"}:
        heading = f"{decision.symbol} - SETUP {'BUY' if decision.direction == 'LONG' else 'SELL'} VALIDO"
    else:
        heading = f"{decision.symbol} - DECISIONE OPERATIVA"
    lines: list[str] = [
        heading,
        "",
        "Bias HTF:",
        f"- H4: {decision.htf_context.get('h4_bias', 'neutral')}",
        f"- H1: {decision.htf_context.get('h1_bias', 'neutral')}",
        f"- Quarterly Block: {decision.htf_context.get('quarterly_block', 'not_configured')}",
        f"- Premium/Discount: {decision.htf_context.get('premium_discount', 'unknown')}",
        "",
        "Intraday:",
        f"- M15: {decision.intraday_context.get('m15_bias', 'neutral')}",
        f"- M5: {decision.intraday_context.get('m5_bias', 'neutral')}",
        f"- M1: {decision.intraday_context.get('m1_bias', 'neutral')}",
        "",
        "Liquidity:",
        f"- External: {decision.liquidity.get('external_low', '-')} / {decision.liquidity.get('external_high', '-')}",
        f"- Internal: {decision.liquidity.get('price_vs_range', 'unknown')}",
        f"- Sweep rilevato: {decision.liquidity.get('m15_sweep', 'none')}",
    ]
    reaction_pools = decision.liquidity.get("reaction_pools", []) or []
    sweeps = decision.liquidity.get("sweeps", []) or []
    if reaction_pools:
        lines.append("- Reaction levels 80+ pips:")
        for pool in reaction_pools[:3]:
            lines.append(f"  {pool.get('timeframe')} {pool.get('pool_type')} {pool.get('level')} ({pool.get('distance_pips')} pips, {pool.get('distance_band')})")
    if sweeps:
        lines.append("- Sweep status:")
        for sweep in sweeps[:3]:
            lines.append(f"  {sweep.get('status')} {sweep.get('level')} score={sweep.get('score')}")
    if decision.liquidity.get("vwap"):
        vw = decision.liquidity["vwap"]
        lines.append(f"- VWAP: {vw.get('vwap')} | z-score {vw.get('z_score')} | 2sigma {vw.get('upper_2')}/{vw.get('lower_2')}")
    if decision.liquidity.get("volume_profile"):
        vp = decision.liquidity["volume_profile"]
        cracks = vp.get("volume_cracks") or []
        lines.append(f"- Volume profile: POC {vp.get('poc')} | cracks {cracks[:2]}")
    lines.extend(
        [
            "",
            "Setup:",
        f"- Tipo: {decision.setup_type}",
        f"- Direzione: {direction_label}",
        f"- Stato: {decision.state}",
        f"- Score: {decision.score}/100",
        f"- Confidenza: {decision.confidence}",
        ]
    )
    if zone is not None:
        lines.extend(
            [
                f"- Zona operativa: {zone.zone_type}",
                f"- Timeframe zona: {zone.timeframe}",
                f"- Range: {_fmt_price(zone.low)} - {_fmt_price(zone.high)}",
                f"- Ruolo: {zone.role}",
                f"- Distanza prezzo: {_fmt_price(zone.distance_from_price)}",
                f"- Zona toccata: {'si' if zone.touched else 'no'}",
                f"- Entry gia toccata: {'si' if zone.entry_area_touched else 'no'}",
            ]
        )
    if decision.entry_area:
        lines.append(f"- Entry area: {_fmt_price(decision.entry_area[0])} - {_fmt_price(decision.entry_area[1])}")
    lines.extend(
        [
            f"- Stop: {_fmt_price(decision.stop)}",
            f"- Invalidazione: {_fmt_price(decision.invalidation)}",
        ]
    )
    for target in decision.targets:
        lines.append(f"- {target.get('label')}: {_fmt_price(target.get('price'))} ({target.get('basis')})")

    present = decision.intraday_context.get("confirmations_present", [])
    missing = decision.intraday_context.get("confirmations_missing", [])
    if present:
        lines.extend(["", "Conferme presenti:"])
        lines.extend(f"- {safe_text(item)}" for item in present)
    if missing:
        lines.extend(["", "Conferme mancanti:"])
        lines.extend(f"- {safe_text(item)}" for item in missing)
    if decision.rejection_reasons:
        lines.extend(["", "Note:"])
        lines.extend(f"- {safe_text(item)}" for item in decision.rejection_reasons[:6])
    if decision.events:
        lines.extend(["", "Eventi rilevati:"])
        for event in decision.events[:5]:
            lines.append(f"- {event.get('type')} {event.get('timeframe')} {event.get('zone_type')} ({event.get('state')})")
    lines.extend(["", "Disclaimer: Paper/demo signal only. No real-money execution."])
    return "\n".join(safe_text(line) for line in lines)


class TelegramBot:
    def __init__(self, settings: Settings, client: Any | None = None):
        self.settings = settings
        self.client = client

    def send_signal(self, payload: dict) -> dict:
        if not self.settings.telegram_enabled:
            return {"ok": False, "reason": "telegram_disabled"}
        if not self.settings.telegram_token or not self.settings.telegram_chat_id:
            return {"ok": False, "reason": "telegram_credentials_missing"}
        message = format_signal_message(payload)
        try:
            client = self.client
            if client is None:
                import requests

                response = requests.post(
                    f"https://api.telegram.org/bot{self.settings.telegram_token}/sendMessage",
                    json={"chat_id": self.settings.telegram_chat_id, "text": message},
                    timeout=10,
                )
                return {"ok": response.ok, "status_code": response.status_code}
            result = client.send_message(chat_id=self.settings.telegram_chat_id, text=message)
            return {"ok": True, "result": result}
        except Exception as exc:
            log.warning("Telegram notification failed: %s", exc)
            return {"ok": False, "reason": "telegram_send_failed"}

    def send_text(self, text: str) -> dict:
        if not self.settings.telegram_enabled:
            return {"ok": False, "reason": "telegram_disabled"}
        if not self.settings.telegram_token or not self.settings.telegram_chat_id:
            return {"ok": False, "reason": "telegram_credentials_missing"}
        try:
            client = self.client
            if client is None:
                import requests

                response = requests.post(
                    f"https://api.telegram.org/bot{self.settings.telegram_token}/sendMessage",
                    json={"chat_id": self.settings.telegram_chat_id, "text": safe_text(text)},
                    timeout=10,
                )
                return {"ok": response.ok, "status_code": response.status_code}
            result = client.send_message(chat_id=self.settings.telegram_chat_id, text=safe_text(text))
            return {"ok": True, "result": result}
        except Exception as exc:
            log.warning("Telegram text notification failed: %s", exc)
            return {"ok": False, "reason": "telegram_send_failed"}
