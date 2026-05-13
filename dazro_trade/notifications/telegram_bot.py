from __future__ import annotations

import logging
from typing import Any

from dazro_trade.core.config import Settings
from dazro_trade.core.models import ScalpingDecision
from dazro_trade.core.symbols import price_to_pips

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
    operational = _is_operational_message(decision)
    if operational:
        entry_ref = decision.entry or _entry_midpoint(decision.entry_area)
        lines = [f"{decision.symbol} — {direction_label} VALID", ""]
        lines.append(f"Entry: {_fmt_price(entry_ref)}")
        if decision.entry_area:
            lines.append(f"Entry area: {_fmt_price(decision.entry_area[0])} - {_fmt_price(decision.entry_area[1])}")
        lines.append(f"SL: {_fmt_price(decision.stop)}")
        lines.append("")
        for target in decision.targets[:3]:
            lines.append(_format_target_line(target, theoretical=False, symbol=decision.symbol, entry=entry_ref))
        lines.extend(["", "Target validation:"])
        lines.extend(f"- {reason}" for reason in _target_validation_reasons(decision))
        lines.extend(_setup_footer(decision, include_missing=False))
        return "\n".join(safe_text(line) for line in lines if line is not None)

    if decision.state == "CONFIRMED_SWEEP":
        heading = f"{decision.symbol} — SWEEP CONFERMATA, ASPETTO TRIGGER"
    elif decision.state == "INVALIDATED":
        heading = f"{decision.symbol} — SETUP INVALIDATO"
    else:
        heading = f"{decision.symbol} — SETUP NON OPERATIVO"

    lines = [
        heading,
        "NO ENTRY",
        "",
        f"Stato: {decision.state}",
        f"Direzione possibile: {_possible_direction(decision)}",
        f"Motivo principale: {_main_reason(decision)}",
        "",
        f"Prezzo live: {_fmt_price(_live_price(decision))}",
    ]
    if zone is not None:
        lines.extend(
            [
                f"Zona osservata: {zone.zone_type} {_fmt_price(zone.low)} - {_fmt_price(zone.high)}",
                f"Livello sweep: {_fmt_price(zone.metadata.get('liquidity_level')) if zone.metadata.get('liquidity_level') is not None else '-'}",
                f"Tipo: {zone.zone_type}",
            ]
        )
    if decision.state == "INVALIDATED":
        lines.extend(
            [
                "",
                "Invalidazione:",
                f"- Prezzo live: {_fmt_price(_live_price(decision))}",
                f"- SL/invalidation: {_fmt_price(decision.invalidation or decision.stop)}",
                f"- Motivo: {_main_reason(decision)}",
            ]
        )
    if decision.state == "CONFIRMED_SWEEP":
        lines.extend(["", "Cosa e' successo:"])
        lines.extend(f"- {reason}" for reason in _sweep_happened_reasons(decision))
    lines.extend(
        [
            "",
            "Piano teorico non operativo:",
            f"Entry teorica solo dopo trigger: {_entry_area_text(decision.entry_area)}",
            f"SL teorico / invalidation: {_fmt_price(decision.stop or decision.invalidation)}",
            "TP teorici:",
        ]
    )
    theoretical_targets = decision.theoretical_targets or []
    entry_ref = decision.entry or _entry_midpoint(decision.entry_area)
    if _target_rr_insufficient(decision):
        lines.append("- Target/RR insufficiente: non valido come TP operativo")
    if theoretical_targets:
        lines.extend(_format_target_line(target, theoretical=True, symbol=decision.symbol, entry=entry_ref) for target in theoretical_targets[:3])
    else:
        lines.append("- nessun TP teorico pulito disponibile")
    lines.extend(["", "Manca:"])
    lines.extend(f"- {item}" for item in _missing_items(decision))
    lines.extend(_setup_footer(decision, include_missing=True))
    lines.extend(["", "NO ENTRY ANCORA.", "Disclaimer: Paper/demo signal only. No real-money execution."])
    return "\n".join(safe_text(line) for line in lines if line is not None)


def _is_operational_message(decision: ScalpingDecision) -> bool:
    validation_ok = not decision.target_validation or bool(decision.target_validation.get("valid", True))
    return decision.state in {"TRIGGERED", "REENTRY_VALID"} and decision.direction in {"LONG", "SHORT"} and validation_ok


def _entry_midpoint(entry_area: tuple[float, float] | None) -> float | None:
    if not entry_area:
        return None
    return round((entry_area[0] + entry_area[1]) / 2, 2)


def _entry_area_text(entry_area: tuple[float, float] | None) -> str:
    if not entry_area:
        return "-"
    return f"{_fmt_price(entry_area[0])} - {_fmt_price(entry_area[1])}"


def _live_price(decision: ScalpingDecision) -> Any:
    return decision.intraday_context.get("current_price") or decision.liquidity.get("price")


def _main_reason(decision: ScalpingDecision) -> str:
    if decision.rejection_reasons:
        return safe_text(decision.rejection_reasons[0])
    if decision.reason_codes:
        return safe_text(decision.reason_codes[0])
    return "waiting_for_trigger_before_entry"


def _possible_direction(decision: ScalpingDecision) -> str:
    if decision.intraday_context.get("possible_direction"):
        return safe_text(decision.intraday_context["possible_direction"])
    if decision.primary_zone and decision.primary_zone.metadata.get("possible_direction"):
        return safe_text(decision.primary_zone.metadata["possible_direction"])
    if decision.direction in {"LONG", "SHORT"}:
        return f"{decision.direction} candidate"
    directions = set()
    for sweep in decision.liquidity.get("sweeps", []) or []:
        text = " ".join(str(sweep.get(key, "")) for key in ("direction", "pool_type", "reason_codes")).lower()
        if "bearish_reversal" in text or "buy_side" in text or "high" in text or "possible_short_after_buy_side_sweep" in text:
            directions.add("SHORT")
        if "bullish_reversal" in text or "sell_side" in text or "low" in text or "possible_long_after_sell_side_sweep" in text:
            directions.add("LONG")
    if len(directions) > 1:
        return "UNCLEAR / LIQUIDITY SEARCH"
    if directions:
        return f"{directions.pop()} candidate"
    return "UNCLEAR / LIQUIDITY SEARCH"


def _format_target_line(target: dict, *, theoretical: bool, symbol: str, entry: float | None) -> str:
    label = target.get("label", "TP")
    if theoretical and "teorico" not in str(label).lower():
        label = f"{label} teorico"
    return f"- {label}: {_fmt_price(target.get('price'))} - {target.get('basis', '-')} - {_target_distance_text(target, symbol=symbol, entry=entry)} - RR {target.get('rr', '-')}"


def _target_distance_text(target: dict, *, symbol: str, entry: float | None) -> str:
    price = target.get("price")
    if entry is not None and price is not None:
        try:
            distance = abs(float(price) - float(entry))
            pips = price_to_pips(symbol, distance)
            return f"{_fmt_decimal(pips)} pips / {distance:.2f}$"
        except (TypeError, ValueError):
            pass
    raw = target.get("distance_pips", "-")
    return f"{raw} pips"


def _fmt_decimal(value: float) -> str:
    return f"{float(value):.1f}".rstrip("0").rstrip(".")


def _target_validation_reasons(decision: ScalpingDecision) -> list[str]:
    reasons = list((decision.target_validation or {}).get("reason_codes") or [])
    reasons.extend(reason for reason in decision.reason_codes if reason.startswith(("official_", "target_", "vwap_", "normal_", "preferred_")))
    return _dedupe(reasons)[:8] or ["official_tp_ladder_valid"]


def _target_rr_insufficient(decision: ScalpingDecision) -> bool:
    validation = decision.target_validation or {}
    if validation.get("valid", True):
        return False
    reasons = set(validation.get("reason_codes") or [])
    reasons.update(decision.reason_codes)
    return bool(reasons & {"official_tp1_too_close", "target_too_close_for_official_tp", "rr_below_minimum_normal", "rr_below_minimum_vwap_scalp", "target_rr_insufficient"})


def _missing_items(decision: ScalpingDecision) -> list[str]:
    missing = list(decision.intraday_context.get("confirmations_missing") or [])
    missing.extend(decision.rejection_reasons)
    if not any("CHOCH" in item.upper() or "choch" in item.lower() for item in missing):
        missing.append("M1/M5 CHOCH")
    if not any("FVG" in item.upper() or "IFVG" in item.upper() for item in missing):
        missing.append("FVG/IFVG valido")
    missing.append("retest entry area")
    missing.append("target validation finale")
    return _dedupe([safe_text(item) for item in missing])[:8]


def _sweep_happened_reasons(decision: ScalpingDecision) -> list[str]:
    reasons = list(decision.reason_codes)
    reasons.extend((decision.primary_zone.reason_codes if decision.primary_zone else []) or [])
    out = [reason for reason in reasons if reason in {"close_back_inside", "m5_displacement", "sell-side liquidity swept", "buy-side liquidity swept"} or "sweep" in reason]
    if not out:
        out = ["liquidity swept", "close back inside"]
    return _dedupe(out)[:5]


def _setup_footer(decision: ScalpingDecision, *, include_missing: bool) -> list[str]:
    lines = [
        "",
        "Setup:",
        f"- Tipo: {decision.setup_type}",
        f"- Direzione: {decision.direction}",
        f"- Stato: {decision.state}",
        f"- Score: {decision.score}/100",
        f"- Confidenza: {decision.confidence}",
    ]
    if include_missing and decision.rejection_reasons:
        lines.extend(["", "Note:"])
        lines.extend(f"- {safe_text(item)}" for item in decision.rejection_reasons[:6])
    if decision.events:
        lines.extend(["", "Eventi rilevati:"])
        for event in decision.events[:5]:
            lines.append(f"- {event.get('type')} {event.get('timeframe')} {event.get('zone_type')} ({event.get('state')})")
    return lines


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


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
