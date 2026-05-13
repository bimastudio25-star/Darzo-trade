from __future__ import annotations

from typing import Any

from dazro_trade.core.symbols import get_symbol_spec


def _money_from_pips(pips: float, symbol: str = "XAUUSD") -> float:
    return round(float(pips) * get_symbol_spec(symbol).pip_size, 2)


def _score_bar(score: int) -> str:
    filled = max(0, min(10, round(score / 10)))
    return "[" + "#" * filled + "." * (10 - filled) + "]"


def format_adelin_signal(signal: dict[str, Any], result: dict[str, Any] | None = None) -> str:
    symbol = str(signal.get("symbol", "XAUUSD"))
    mode = str(signal.get("setup_mode", "NO_TRADE"))
    score = int(signal.get("score", 0) or 0)
    lines = [
        f"{symbol} - STRATEGY 1.0 (ADELIN ENGINE) - {mode}",
        "Strategia: LIQ + VP + Number Theory + FVG/IFVG",
        "Paper/Demo - non reale.",
    ]
    if mode == "VWAP_STD_RESEARCH_1R":
        lines.extend(["VWAP_STD_RESEARCH_1R - PAPER ONLY", "NON E' SETUP A+."])
    lines.extend(
        [
            f"Direzione: {signal.get('direction', '-')}",
            f"Score: {score}/100 {_score_bar(score)}",
            f"Entry zone: {_zone(signal.get('entry_zone'))}",
            f"Entry mid: {_price(signal.get('entry'))}",
            f"SL: {_price(signal.get('sl'))} - {signal.get('sl_pips', '-')} pips / {_money_from_pips(float(signal.get('sl_pips', 0) or 0), symbol):.2f}$",
        ]
    )
    for label in ("tp1", "tp2"):
        target = signal.get(label)
        if isinstance(target, dict):
            pips = float(target.get("distance_pips", 0) or 0)
            lines.append(f"{label.upper()}: {_price(target.get('price'))} - {pips:g} pips / {_money_from_pips(pips, symbol):.2f}$ - RR {target.get('rr', '-')} - {target.get('basis', '-')}")
    lines.extend(
        [
            "",
            "Confluence:",
            f"- Liquidity swept: {_liquidity(signal)}",
            f"- Volume crack/LVN: {_reason(signal.get('volume_confluence'))}",
            f"- Number Theory: {_reason(signal.get('number_theory'))}",
            f"- FVG/IFVG: {_reason(signal.get('fvg'))}",
            f"- Sweep: {_reason(signal.get('sweep'))}",
            f"- Sessione: {signal.get('session', '-')}",
            f"- Spread: {signal.get('spread_pips', '-')} pips",
            "",
            "VP:",
            format_vp_summary(result or {}),
            "",
            "Paper/Demo - non reale. No live-money execution.",
        ]
    )
    return "\n".join(lines)


def format_rejection_summary(result: dict[str, Any]) -> str:
    lines = [
        "STRATEGY 1.0 (ADELIN ENGINE) - NO TRADE",
        "Strategia: LIQ + VP + Number Theory + FVG/IFVG",
        f"Setup mode: {result.get('setup_mode', 'NO_TRADE')}",
        "Motivi:",
    ]
    rejected = result.get("rejected") or ["no_valid_signal"]
    lines.extend(f"- {item}" for item in rejected[:12])
    if result.get("score_detail"):
        detail = result["score_detail"]
        lines.extend(["", f"Score: {detail.get('score', 0)}/100", f"Verdict: {detail.get('verdict', '-')}"])
    lines.extend(["", "Paper/Demo - non reale."])
    return "\n".join(lines)


def format_vp_summary(result: dict[str, Any]) -> str:
    summary = result.get("vp_summary") if "vp_summary" in result else result
    if not summary:
        return "- VP non disponibile"
    lines = [
        f"- Profili: {', '.join(summary.get('profiles', [])[:6]) if summary.get('profiles') else '-'}",
        f"- POC principale: {summary.get('best_poc', '-')}",
        f"- Nota: {summary.get('volume_note', 'tick_volume MT5 proxy')}",
    ]
    daily = summary.get("daily") or {}
    if daily:
        lines.append(f"- Daily POC/VAH/VAL: {daily.get('poc', '-')} / {daily.get('vah', '-')} / {daily.get('val', '-')}")
    return "\n".join(lines)


def _zone(value: Any) -> str:
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return f"{_price(value[0])} - {_price(value[1])}"
    return "-"


def _price(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):.2f}"


def _reason(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("reason") or value.get("type") or value.get("level_name") or value.get("confluence") or "-")
    return str(value or "-")


def _liquidity(signal: dict[str, Any]) -> str:
    swept = signal.get("liquidity_swept") or {}
    if isinstance(swept, dict):
        return f"{swept.get('name', swept.get('level_name', '-'))} {swept.get('level', '-')}"
    return str(swept or "-")


__all__ = ["format_adelin_signal", "format_rejection_summary", "format_vp_summary"]
