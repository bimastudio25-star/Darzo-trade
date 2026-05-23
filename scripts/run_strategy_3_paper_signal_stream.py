from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STRATEGY_ID = "strategy_3_vwap_1r"
STRATEGY_VERSION = "paper_signal_stream_v1"
PROJECT_PIP_CONVENTION = "1_USD_10_PIPS"
PAPER_ONLY_DISCLAIMER = "PAPER_ONLY_RESEARCH_SIGNAL_NOT_TRADING_INSTRUCTION"
MESSAGE_PREFIX = "[PAPER SIGNAL — STRATEGY 3]"
MESSAGE_SUFFIX = "Paper-only signal for TradingView marking and weekly review. Not a trading instruction."
AMBIGUITY_POLICY_NOTE = "Ambiguous outcomes are excluded from decisive WR and are not counted as wins."
DEFAULT_OUTPUT_DIR = Path("backtests/reports/strategy_3_paper_signal_stream")
DEFAULT_DOCS_PATH = Path("docs/research/strategy_3_paper_signal_stream.md")
DEFAULT_AMBIGUITY_DIR = Path("backtests/reports/strategy_3_fill_model_ambiguity_governance")
DEFAULT_REGIME_PATH = Path("backtests/reports/strategy_3_vwap_trend_regime_diagnostics/regime_diagnostics_per_signal.csv")

FORBIDDEN_NOTIFICATION_PHRASES = [
    "BUY NOW",
    "SELL NOW",
    "ENTER NOW",
    "TRADE NOW",
    "APRI",
    "ENTRA",
    "SEGNALE OPERATIVO",
    "EXECUTE",
    "ORDER",
    "LIVE SIGNAL",
    "PROFIT GUARANTEED",
    "VALIDATED EDGE",
]

SAFETY = {
    "live_trading_enabled": False,
    "telegram_enabled_by_default": False,
    "broker_execution_enabled": False,
    "order_execution_enabled": False,
    "order_send_called": False,
    "signal_stream_is_paper_only": True,
    "lot_sizing_enabled": False,
    "account_risk_sizing_enabled": False,
    "real_trade_management_enabled": False,
    "strategy_3_runtime_logic_changed": False,
    "vwap_sigma_cooldown_logic_changed": False,
    "lifecycle_logic_changed": False,
    "ambiguity_policy_changed": False,
    "strategy_2_touched": False,
    "adelin_touched": False,
    "data_xauusd_mutated": False,
    "parameter_tuning_enabled": False,
    "deployment_recommendation_emitted": False,
}

EVENT_FIELDS = [
    "event_id",
    "observed_at_utc",
    "decision_timestamp",
    "symbol",
    "strategy_id",
    "strategy_version",
    "code_commit",
    "data_context_hash",
    "prefix_compatible",
    "signal_status",
    "block_reason",
    "cooldown_active",
    "cooldown_remaining_minutes",
    "direction",
    "entry_reference_price",
    "stop_loss",
    "take_profit",
    "risk_distance_usd",
    "risk_distance_pips",
    "project_pip_convention",
    "vwap_slope_bucket",
    "vwap_distance_bucket",
    "h1_bias",
    "h4_bias",
    "volatility_bucket",
    "session_bucket",
    "ambiguity_governance_gate",
    "paper_signal_stream_gate",
    "primary_outcome_policy",
    "ambiguous_outcome_policy",
    "paper_only",
    "alert_channel",
    "alert_delivery_status",
    "paper_only_disclaimer",
]

WEEKLY_REVIEW_FIELDS = [
    "event_id",
    "decision_timestamp",
    "signal_status",
    "block_reason",
    "direction",
    "entry_reference_price",
    "stop_loss",
    "take_profit",
    "risk_distance_usd",
    "risk_distance_pips",
    "bot_context_summary",
    "ambiguity_policy_note",
    "tradingview_marked",
    "human_decision",
    "human_reason",
    "screenshot_reference",
    "outcome_observed_manually",
    "end_of_week_notes",
]


@dataclass(frozen=True)
class PaperSignalStreamConfig:
    symbol: str
    data_dir: Path
    paper_signals_path: Path
    scanner_summary_path: Path
    pipeline_summary_path: Path
    regime_diagnostics_path: Path
    ambiguity_governance_policy_path: Path
    ambiguity_governance_summary_path: Path
    output_dir: Path
    docs_path: Path
    dry_run: bool
    watch: bool
    poll_seconds: int
    max_watch_iterations: int | None
    enable_paper_telegram: bool
    notify_blocked: bool
    force_resend: bool
    allow_missing_governance_dry_run: bool
    include_legacy: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strategy 3 paper-only signal stream")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--paper-signals-path", default="backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv")
    parser.add_argument("--scanner-summary-path", default="backtests/reports/strategy_3_paper_shadow_scanner/scanner_summary.json")
    parser.add_argument("--pipeline-summary-path", default="backtests/reports/strategy_3_local_paper_pipeline/pipeline_summary.json")
    parser.add_argument("--regime-diagnostics-path", default=str(DEFAULT_REGIME_PATH))
    parser.add_argument("--ambiguity-governance-policy-path", default=str(DEFAULT_AMBIGUITY_DIR / "ambiguity_governance_policy.json"))
    parser.add_argument("--ambiguity-governance-summary-path", default=str(DEFAULT_AMBIGUITY_DIR / "ambiguity_governance_summary.json"))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--docs-path", default=str(DEFAULT_DOCS_PATH))
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false", help="Allow paper Telegram delivery when all explicit gates/env vars are present.")
    parser.add_argument("--watch", action="store_true", help="Poll paper signal outputs repeatedly. Still paper-only.")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--max-watch-iterations", type=int)
    parser.add_argument("--enable-paper-telegram", action="store_true", help="Enable paper-only Telegram delivery when env vars are configured.")
    parser.add_argument("--notify-blocked", action="store_true", help="Also notify blocked paper events. Default logs them locally only.")
    parser.add_argument("--force-resend", action="store_true", help="Allow re-rendering/re-sending accepted events already present in the local stream registry.")
    parser.add_argument("--allow-missing-governance-dry-run", action="store_true", help="Allow dry-run rendering if ambiguity governance files are missing.")
    parser.add_argument("--include-legacy", action="store_true", help="Include paper rows without data_context_hash. Default excludes legacy rows.")
    return parser.parse_args(argv)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "accepted"}


def _float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_price(value: Any) -> str:
    number = _float(value)
    if number is None:
        return ""
    return f"{number:.2f}"


def _code_commit() -> str:
    head = REPO_ROOT / ".git" / "HEAD"
    try:
        raw = head.read_text(encoding="utf-8").strip()
        if raw.startswith("ref:"):
            ref = raw.split(" ", 1)[1]
            ref_path = REPO_ROOT / ".git" / ref
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8").strip()[:12]
        return raw[:12]
    except OSError:
        return ""


def _event_id(row: dict[str, Any], status: str) -> str:
    raw = "|".join(
        [
            STRATEGY_ID,
            str(row.get("symbol") or ""),
            str(row.get("signal_timestamp") or row.get("decision_timestamp") or ""),
            str(row.get("direction") or ""),
            _format_price(row.get("entry_price") or row.get("entry_reference_price")),
            status,
        ]
    )
    return f"strategy3-paper-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _status(row: dict[str, Any]) -> str:
    cooldown_status = str(row.get("cooldown_status") or "").strip().lower()
    if cooldown_status == "accepted" or _bool(row.get("cooldown_accepted")):
        return "ACCEPTED"
    if cooldown_status == "blocked" or _bool(row.get("cooldown_blocked")) or row.get("cooldown_block_reason"):
        return "BLOCKED"
    return "NO_SIGNAL"


def _risk_distance(row: dict[str, Any]) -> float | None:
    entry = _float(row.get("entry_price") or row.get("entry_reference_price"))
    stop = _float(row.get("stop_loss") or row.get("sl"))
    fallback = _float(row.get("risk_distance_usd") or row.get("risk_distance"))
    if entry is not None and stop is not None:
        return round(abs(entry - stop), 6)
    if fallback is not None:
        return round(abs(fallback), 6)
    return None


def _load_regime_rows(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows = _read_csv(path)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("decision_time") or row.get("signal_timestamp") or ""), str(row.get("direction") or "").upper())
        out[key] = row
    return out


def _load_existing_event_ids(output_dir: Path) -> set[str]:
    rows = _read_csv(output_dir / "paper_signal_stream_events.csv")
    return {str(row.get("event_id")) for row in rows if row.get("event_id")}


def load_ambiguity_governance(cfg: PaperSignalStreamConfig) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    warnings: list[str] = []
    policy = _read_json(cfg.ambiguity_governance_policy_path)
    summary = _read_json(cfg.ambiguity_governance_summary_path)
    if not policy:
        warnings.append(f"AMBIGUITY_GOVERNANCE_POLICY_MISSING: {cfg.ambiguity_governance_policy_path}")
    if not summary:
        warnings.append(f"AMBIGUITY_GOVERNANCE_SUMMARY_MISSING: {cfg.ambiguity_governance_summary_path}")
    if not policy:
        policy = {
            "ambiguity_governance_gate": "MISSING",
            "paper_signal_stream_gate_policy": "BLOCKED_OR_WARNING_MISSING_GOVERNANCE",
            "primary_outcome_policy": "MISSING",
            "ambiguous_intrabar_policy": "MISSING",
            "live_gate": "BLOCKED",
            "deployment_gate": "BLOCKED",
            "order_send_gate": "BLOCKED",
            "broker_gate": "BLOCKED",
        }
    return policy, summary, warnings


def select_signal_rows(rows: list[dict[str, Any]], cfg: PaperSignalStreamConfig) -> tuple[list[dict[str, Any]], int]:
    strategy_rows = [
        row
        for row in rows
        if str(row.get("strategy") or STRATEGY_ID) == STRATEGY_ID and str(row.get("symbol") or cfg.symbol) == cfg.symbol
    ]
    if cfg.include_legacy:
        return strategy_rows, 0
    clean = [row for row in strategy_rows if str(row.get("data_context_hash") or "").strip()]
    return clean, len(strategy_rows) - len(clean)


def validate_notification_message(message: str) -> list[str]:
    errors: list[str] = []
    if not message.startswith(MESSAGE_PREFIX):
        errors.append("MISSING_PAPER_SIGNAL_PREFIX")
    if not message.endswith(MESSAGE_SUFFIX):
        errors.append("MISSING_PAPER_ONLY_SUFFIX")
    upper = message.upper()
    for phrase in FORBIDDEN_NOTIFICATION_PHRASES:
        if phrase in upper:
            errors.append(f"FORBIDDEN_PHRASE:{phrase}")
    return errors


def build_notification_message(event: dict[str, Any]) -> str:
    lines = [
        MESSAGE_PREFIX,
        f"Symbol: {event.get('symbol')}",
        f"Direction: {event.get('direction')}",
        f"Decision time: {event.get('decision_timestamp')}",
        f"Entry reference: {event.get('entry_reference_price')}",
        f"Stop loss: {event.get('stop_loss')}",
        f"Take profit: {event.get('take_profit')}",
        f"Risk: {event.get('risk_distance_usd')} USD / {event.get('risk_distance_pips')} pips",
        f"Event ID: {event.get('event_id')}",
        f"Signal status: {event.get('signal_status')}",
        "Paper-only status: paper research notification only",
        f"Ambiguity policy: {AMBIGUITY_POLICY_NOTE}",
        MESSAGE_SUFFIX,
    ]
    return "\n".join(lines)


def _telegram_configured() -> bool:
    return bool(os.environ.get("STRATEGY3_PAPER_TELEGRAM_BOT_TOKEN") and os.environ.get("STRATEGY3_PAPER_TELEGRAM_CHAT_ID"))


def send_paper_telegram(message: str) -> tuple[bool, str]:
    token = os.environ.get("STRATEGY3_PAPER_TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("STRATEGY3_PAPER_TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False, "TELEGRAM_NOT_CONFIGURED"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        with urllib.request.urlopen(url, data=payload, timeout=10) as response:
            if 200 <= response.status < 300:
                return True, "TELEGRAM_PAPER_SENT"
            return False, f"TELEGRAM_HTTP_{response.status}"
    except Exception as exc:  # pragma: no cover - network failures are environment-specific
        return False, f"TELEGRAM_FAILED:{type(exc).__name__}"


def build_event(
    *,
    row: dict[str, Any],
    regime: dict[str, Any],
    policy: dict[str, Any],
    status: str,
    observed_at: str,
    code_commit: str,
) -> dict[str, Any]:
    risk_usd = _risk_distance(row)
    signal_time = str(row.get("signal_timestamp") or row.get("decision_time") or "")
    cooldown_active = status == "BLOCKED" and str(row.get("cooldown_block_reason") or row.get("block_reason") or "").strip() != ""
    return {
        "event_id": _event_id(row, status),
        "observed_at_utc": observed_at,
        "decision_timestamp": signal_time,
        "symbol": str(row.get("symbol") or ""),
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "code_commit": code_commit,
        "data_context_hash": str(row.get("data_context_hash") or ""),
        "prefix_compatible": regime.get("context_prefix_compatible") or bool(str(row.get("data_context_hash") or "").strip()),
        "signal_status": status,
        "block_reason": "" if status == "ACCEPTED" else str(row.get("cooldown_block_reason") or row.get("block_reason") or ""),
        "cooldown_active": cooldown_active,
        "cooldown_remaining_minutes": "",
        "direction": str(row.get("direction") or "").upper(),
        "entry_reference_price": _format_price(row.get("entry_price") or row.get("entry_reference_price")),
        "stop_loss": _format_price(row.get("stop_loss") or row.get("sl")),
        "take_profit": _format_price(row.get("take_profit") or row.get("tp1") or row.get("target")),
        "risk_distance_usd": round(risk_usd, 6) if risk_usd is not None else "",
        "risk_distance_pips": round(risk_usd * 10.0, 6) if risk_usd is not None else "",
        "project_pip_convention": PROJECT_PIP_CONVENTION,
        "vwap_slope_bucket": regime.get("vwap_slope_bucket", ""),
        "vwap_distance_bucket": regime.get("vwap_distance_sigma_bucket") or regime.get("vwap_distance_bucket") or "",
        "h1_bias": regime.get("h1_bias", ""),
        "h4_bias": regime.get("h4_bias", ""),
        "volatility_bucket": regime.get("volatility_bucket", ""),
        "session_bucket": regime.get("session_bucket") or row.get("session") or "",
        "ambiguity_governance_gate": policy.get("ambiguity_governance_gate", "MISSING"),
        "paper_signal_stream_gate": policy.get("paper_signal_stream_gate_policy", policy.get("paper_signal_stream_gate", "MISSING")),
        "primary_outcome_policy": policy.get("primary_outcome_policy", "MISSING"),
        "ambiguous_outcome_policy": policy.get("ambiguous_intrabar_policy", "MISSING"),
        "paper_only": True,
        "alert_channel": "FILE_ONLY",
        "alert_delivery_status": "FILE_ONLY",
        "paper_only_disclaimer": PAPER_ONLY_DISCLAIMER,
    }


def _notification_allowed(cfg: PaperSignalStreamConfig, event: dict[str, Any], existing_event_ids: set[str], governance_missing: bool) -> tuple[bool, str]:
    status = event["signal_status"]
    if governance_missing and not (cfg.dry_run and cfg.allow_missing_governance_dry_run):
        return False, "GOVERNANCE_MISSING_SUPPRESSED"
    if status == "BLOCKED" and not cfg.notify_blocked:
        return False, "BLOCKED_LOCAL_LOG_ONLY"
    if status not in {"ACCEPTED", "BLOCKED"}:
        return False, "LOCAL_LOG_ONLY"
    if event["event_id"] in existing_event_ids and not cfg.force_resend:
        return False, "DUPLICATE_SUPPRESSED"
    return True, ""


def deliver_notification(cfg: PaperSignalStreamConfig, event: dict[str, Any], existing_event_ids: set[str], governance_missing: bool) -> tuple[dict[str, Any], str]:
    allowed, reason = _notification_allowed(cfg, event, existing_event_ids, governance_missing)
    if not allowed:
        event["alert_channel"] = "FILE_ONLY"
        event["alert_delivery_status"] = reason
        return event, ""
    message = build_notification_message(event)
    safety_errors = validate_notification_message(message)
    if safety_errors:
        event["alert_channel"] = "FILE_ONLY"
        event["alert_delivery_status"] = "MESSAGE_SAFETY_CHECK_FAILED:" + ";".join(safety_errors)
        return event, message
    if cfg.dry_run:
        event["alert_channel"] = "DRY_RUN"
        event["alert_delivery_status"] = "DRY_RUN"
        return event, message
    if cfg.enable_paper_telegram:
        if not _telegram_configured():
            event["alert_channel"] = "TELEGRAM_PAPER"
            event["alert_delivery_status"] = "TELEGRAM_NOT_CONFIGURED"
            return event, message
        ok, status = send_paper_telegram(message)
        event["alert_channel"] = "TELEGRAM_PAPER"
        event["alert_delivery_status"] = status
        return event, message if ok else message
    event["alert_channel"] = "CONSOLE"
    event["alert_delivery_status"] = "CONSOLE_ONLY"
    return event, message


def _no_signal_event(observed_at: str, policy: dict[str, Any], code_commit: str) -> dict[str, Any]:
    raw = f"{STRATEGY_ID}|NO_SIGNAL|{observed_at}"
    return {
        "event_id": f"strategy3-paper-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}",
        "observed_at_utc": observed_at,
        "decision_timestamp": "",
        "symbol": "",
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "code_commit": code_commit,
        "data_context_hash": "",
        "prefix_compatible": "",
        "signal_status": "NO_SIGNAL",
        "block_reason": "",
        "cooldown_active": False,
        "cooldown_remaining_minutes": "",
        "direction": "",
        "entry_reference_price": "",
        "stop_loss": "",
        "take_profit": "",
        "risk_distance_usd": "",
        "risk_distance_pips": "",
        "project_pip_convention": PROJECT_PIP_CONVENTION,
        "vwap_slope_bucket": "",
        "vwap_distance_bucket": "",
        "h1_bias": "",
        "h4_bias": "",
        "volatility_bucket": "",
        "session_bucket": "",
        "ambiguity_governance_gate": policy.get("ambiguity_governance_gate", "MISSING"),
        "paper_signal_stream_gate": policy.get("paper_signal_stream_gate_policy", "MISSING"),
        "primary_outcome_policy": policy.get("primary_outcome_policy", "MISSING"),
        "ambiguous_outcome_policy": policy.get("ambiguous_intrabar_policy", "MISSING"),
        "paper_only": True,
        "alert_channel": "FILE_ONLY",
        "alert_delivery_status": "LOCAL_LOG_ONLY",
        "paper_only_disclaimer": PAPER_ONLY_DISCLAIMER,
    }


def _error_event(observed_at: str, policy: dict[str, Any], code_commit: str, message: str) -> dict[str, Any]:
    row = _no_signal_event(observed_at, policy, code_commit)
    row["signal_status"] = "ERROR"
    row["block_reason"] = message
    row["alert_delivery_status"] = "ERROR_LOCAL_LOG_ONLY"
    return row


def _risk_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    distances = [float(event["risk_distance_usd"]) for event in events if event.get("risk_distance_usd") not in {"", None}]
    if not distances:
        return {"count": 0}
    return {
        "count": len(distances),
        "median_usd": round(float(median(distances)), 6),
        "mean_usd": round(float(mean(distances)), 6),
        "max_usd": round(max(distances), 6),
        "median_pips": round(float(median(distances)) * 10.0, 6),
        "mean_pips": round(float(mean(distances)) * 10.0, 6),
        "max_pips": round(max(distances) * 10.0, 6),
    }


def _count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "")
        counts[key] = counts.get(key, 0) + 1
    return counts


def build_weekly_review_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if event["signal_status"] == "NO_SIGNAL":
            continue
        context = ", ".join(
            part
            for part in [
                f"session={event.get('session_bucket')}" if event.get("session_bucket") else "",
                f"vwap_slope={event.get('vwap_slope_bucket')}" if event.get("vwap_slope_bucket") else "",
                f"vwap_distance={event.get('vwap_distance_bucket')}" if event.get("vwap_distance_bucket") else "",
                f"h1={event.get('h1_bias')}" if event.get("h1_bias") else "",
                f"h4={event.get('h4_bias')}" if event.get("h4_bias") else "",
                f"volatility={event.get('volatility_bucket')}" if event.get("volatility_bucket") else "",
            ]
        )
        rows.append(
            {
                "event_id": event["event_id"],
                "decision_timestamp": event["decision_timestamp"],
                "signal_status": event["signal_status"],
                "block_reason": event["block_reason"],
                "direction": event["direction"],
                "entry_reference_price": event["entry_reference_price"],
                "stop_loss": event["stop_loss"],
                "take_profit": event["take_profit"],
                "risk_distance_usd": event["risk_distance_usd"],
                "risk_distance_pips": event["risk_distance_pips"],
                "bot_context_summary": context,
                "ambiguity_policy_note": AMBIGUITY_POLICY_NOTE,
                "tradingview_marked": "NO",
                "human_decision": "HUMAN_UNCERTAIN",
                "human_reason": "",
                "screenshot_reference": "",
                "outcome_observed_manually": "",
                "end_of_week_notes": "",
            }
        )
    return rows


def build_summary(
    *,
    cfg: PaperSignalStreamConfig,
    events: list[dict[str, Any]],
    all_rows_count: int,
    legacy_excluded: int,
    warnings: list[str],
    notification_messages: list[str],
    runtime_seconds: float,
    telegram_configured: bool,
) -> dict[str, Any]:
    accepted = [event for event in events if event["signal_status"] == "ACCEPTED"]
    blocked = [event for event in events if event["signal_status"] == "BLOCKED"]
    no_signal = [event for event in events if event["signal_status"] == "NO_SIGNAL"]
    errors = [event for event in events if event["signal_status"] == "ERROR"]
    sent = [event for event in events if event["alert_delivery_status"] == "TELEGRAM_PAPER_SENT"]
    failed = [event for event in events if str(event["alert_delivery_status"]).startswith(("TELEGRAM_FAILED", "MESSAGE_SAFETY_CHECK_FAILED"))]
    suppressed = [event for event in events if event not in sent and event not in failed]
    latest_accepted = max((str(event["decision_timestamp"]) for event in accepted if event.get("decision_timestamp")), default="")
    return {
        "run_finished_at": _utc_now(),
        "runtime_seconds": round(runtime_seconds, 4),
        "dry_run": cfg.dry_run,
        "strategy": STRATEGY_ID,
        "symbol": cfg.symbol,
        "inputs": {
            "paper_signals_path": str(cfg.paper_signals_path),
            "scanner_summary_path": str(cfg.scanner_summary_path),
            "pipeline_summary_path": str(cfg.pipeline_summary_path),
            "regime_diagnostics_path": str(cfg.regime_diagnostics_path),
            "ambiguity_governance_policy_path": str(cfg.ambiguity_governance_policy_path),
            "ambiguity_governance_summary_path": str(cfg.ambiguity_governance_summary_path),
            "data_dir": str(cfg.data_dir),
        },
        "selection": {
            "total_paper_rows_available": all_rows_count,
            "legacy_excluded": legacy_excluded,
            "events_observed": len(events),
            "include_legacy": cfg.include_legacy,
        },
        "events_observed": len(events),
        "accepted_count": len(accepted),
        "blocked_count": len(blocked),
        "no_signal_count": len(no_signal),
        "error_count": len(errors),
        "cooldown_blocked_count": sum(1 for event in blocked if event.get("block_reason") == "STRATEGY_3_COOLDOWN_BLOCKED"),
        "alerts_sent": len(sent),
        "alerts_suppressed": len(suppressed),
        "alerts_failed": len(failed),
        "accepted_by_direction": _count_by(accepted, "direction"),
        "blocked_by_reason": _count_by(blocked, "block_reason"),
        "risk_distance_summary": {
            "accepted": _risk_summary(accepted),
            "blocked": _risk_summary(blocked),
            "all_events": _risk_summary([event for event in events if event["signal_status"] in {"ACCEPTED", "BLOCKED"}]),
        },
        "ambiguity_policy_summary": {
            "ambiguity_governance_gate": events[0].get("ambiguity_governance_gate") if events else "MISSING",
            "paper_signal_stream_gate": events[0].get("paper_signal_stream_gate") if events else "MISSING",
            "primary_outcome_policy": events[0].get("primary_outcome_policy") if events else "MISSING",
            "ambiguous_outcome_policy": events[0].get("ambiguous_outcome_policy") if events else "MISSING",
            "ambiguity_policy_note": AMBIGUITY_POLICY_NOTE,
        },
        "telegram_enabled": cfg.enable_paper_telegram,
        "telegram_configured": telegram_configured,
        "watch_mode": cfg.watch,
        "notify_blocked": cfg.notify_blocked,
        "force_resend": cfg.force_resend,
        "notification_message_count": len(notification_messages),
        "notification_safety_errors": [err for msg in notification_messages for err in validate_notification_message(msg)],
        "warnings": warnings,
        "gates": {
            "ambiguity_governance_gate": events[0].get("ambiguity_governance_gate") if events else "MISSING",
            "paper_signal_stream_gate": events[0].get("paper_signal_stream_gate") if events else "MISSING",
            "live_gate": "BLOCKED",
            "deployment_gate": "BLOCKED",
            "order_send_gate": "BLOCKED",
            "broker_gate": "BLOCKED",
            "allowed_next_action": "OBSERVE_MARK_ON_TRADINGVIEW_AND_REVIEW_WEEKLY",
        },
        "latest_state": {
            "latest_run_time_utc": _utc_now(),
            "latest_event_id": events[-1]["event_id"] if events else "",
            "latest_signal_status": events[-1]["signal_status"] if events else "NO_SIGNAL",
            "latest_accepted_signal_timestamp": latest_accepted,
            "total_events_logged": len(events),
            "accepted_logged": len(accepted),
            "blocked_logged": len(blocked),
            "no_signal_logged": len(no_signal),
            "errors_logged": len(errors),
            "alerts_sent": len(sent),
            "alerts_suppressed": len(suppressed),
            "alerts_failed": len(failed),
            "telegram_enabled": cfg.enable_paper_telegram,
            "telegram_configured": telegram_configured,
            "ambiguity_governance_gate": events[0].get("ambiguity_governance_gate") if events else "MISSING",
            "paper_signal_stream_gate": events[0].get("paper_signal_stream_gate") if events else "MISSING",
            "live_gate": "BLOCKED",
            "deployment_gate": "BLOCKED",
            "order_send_gate": "BLOCKED",
            "broker_gate": "BLOCKED",
            "allowed_next_action": "OBSERVE_MARK_ON_TRADINGVIEW_AND_REVIEW_WEEKLY",
        },
        "verdict_flags": [
            "PAPER_SIGNAL_STREAM_CREATED",
            "PAPER_ONLY_NOTIFICATION_LAYER",
            "LOCAL_EVENT_LOG_CREATED",
            "AMBIGUITY_POLICY_INCLUDED",
            "TELEGRAM_DISABLED_BY_DEFAULT",
            "NO_LIVE_DEPLOYMENT_DECISION",
            "STRATEGY_3_REMAINS_PAPER_ONLY",
        ],
        "safety": dict(SAFETY),
    }


def write_report(output_dir: Path, docs_path: Path, summary: dict[str, Any], example_message: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    gates = summary["gates"]
    lines = [
        "# Strategy 3 Paper Signal Stream",
        "",
        "This is a paper-only notification and logging layer. It is not live trading, not a broker connector, not an order system, and not a deployment approval.",
        "",
        "## Purpose",
        "",
        "The stream lets Adelin mark accepted Strategy 3 paper signals manually on TradingView while the bot records accepted, blocked, no-signal, and error events locally for weekly review.",
        "",
        "## How To Run",
        "",
        "Dry-run one-shot:",
        "",
        "```powershell",
        "python scripts/run_strategy_3_paper_signal_stream.py --symbol XAUUSD --data-dir data --output-dir backtests/reports/strategy_3_paper_signal_stream --dry-run",
        "```",
        "",
        "Watch mode, still paper-only:",
        "",
        "```powershell",
        "python scripts/run_strategy_3_paper_signal_stream.py --symbol XAUUSD --watch --poll-seconds 60 --dry-run",
        "```",
        "",
        "Optional paper-only Telegram transport requires explicit enablement and environment variables:",
        "",
        "```powershell",
        "$env:STRATEGY3_PAPER_TELEGRAM_BOT_TOKEN = '<token>'",
        "$env:STRATEGY3_PAPER_TELEGRAM_CHAT_ID = '<chat_id>'",
        "python scripts/run_strategy_3_paper_signal_stream.py --symbol XAUUSD --enable-paper-telegram --no-dry-run",
        "```",
        "",
        "Secrets must stay in environment variables only. They are never written to reports, logs, docs, or git.",
        "",
        "## Outputs",
        "",
        "- `paper_signal_stream_events.csv`",
        "- `paper_signal_stream_events.jsonl`",
        "- `paper_signal_stream_latest_state.json`",
        "- `paper_signal_stream_session_summary.json`",
        "- `weekly_manual_review_template.csv`",
        "- `paper_signal_stream.md`",
        "",
        "## Current Session Summary",
        "",
        f"- events observed: `{summary['events_observed']}`",
        f"- accepted / blocked / no signal / error: `{summary['accepted_count']} / {summary['blocked_count']} / {summary['no_signal_count']} / {summary['error_count']}`",
        f"- cooldown blocked: `{summary['cooldown_blocked_count']}`",
        f"- alerts sent / suppressed / failed: `{summary['alerts_sent']} / {summary['alerts_suppressed']} / {summary['alerts_failed']}`",
        f"- Telegram enabled / configured: `{summary['telegram_enabled']} / {summary['telegram_configured']}`",
        "",
        "## Ambiguity Policy",
        "",
        f"- ambiguity governance gate: `{gates['ambiguity_governance_gate']}`",
        f"- paper signal stream gate: `{gates['paper_signal_stream_gate']}`",
        f"- primary outcome policy: `{summary['ambiguity_policy_summary']['primary_outcome_policy']}`",
        f"- ambiguous outcome policy: `{summary['ambiguity_policy_summary']['ambiguous_outcome_policy']}`",
        f"- note: {AMBIGUITY_POLICY_NOTE}",
        "",
        "## Example Paper Message",
        "",
        "```text",
        example_message or "No accepted signal message was rendered in this run.",
        "```",
        "",
        "## Prohibited Use",
        "",
        "- no live trading",
        "- no broker execution",
        "- no order_send",
        "- no orders",
        "- no lot size or account risk sizing",
        "- no automatic closing",
        "- no Strategy 3 logic changes",
        "- no cooldown, VWAP, sigma, entry, TP, SL, or filter changes",
        "- no edge, profitability, live-readiness, or Paper Validated claim",
        "",
        "## Gates",
        "",
        f"- live gate: `{gates['live_gate']}`",
        f"- deployment gate: `{gates['deployment_gate']}`",
        f"- order_send gate: `{gates['order_send_gate']}`",
        f"- broker gate: `{gates['broker_gate']}`",
        f"- allowed next action: `{gates['allowed_next_action']}`",
        "",
        "## Weekly TradingView Workflow",
        "",
        "1. Open `weekly_manual_review_template.csv`.",
        "2. Mark accepted paper signals on TradingView manually.",
        "3. Fill `tradingview_marked`, `human_decision`, screenshot reference, and end-of-week notes.",
        "4. Keep ambiguous outcomes excluded from decisive WR and never count them as wins.",
        "",
    ]
    rendered = "\n".join(lines)
    (output_dir / "paper_signal_stream.md").write_text(rendered, encoding="utf-8")
    docs_path.write_text(rendered, encoding="utf-8")


def run_stream_once(cfg: PaperSignalStreamConfig) -> dict[str, Any]:
    started = time.perf_counter()
    observed_at = _utc_now()
    code_commit = _code_commit()
    policy, _governance_summary, warnings = load_ambiguity_governance(cfg)
    governance_missing = policy.get("ambiguity_governance_gate") == "MISSING"
    telegram_configured = _telegram_configured()
    existing_event_ids = _load_existing_event_ids(cfg.output_dir)
    regime_rows = _load_regime_rows(cfg.regime_diagnostics_path)
    all_rows = _read_csv(cfg.paper_signals_path)
    events: list[dict[str, Any]] = []
    messages: list[str] = []

    if not cfg.paper_signals_path.exists():
        events.append(_error_event(observed_at, policy, code_commit, f"PAPER_SIGNALS_MISSING: {cfg.paper_signals_path}"))
        legacy_excluded = 0
    else:
        selected_rows, legacy_excluded = select_signal_rows(all_rows, cfg)
        if not selected_rows:
            events.append(_no_signal_event(observed_at, policy, code_commit))
        for row in selected_rows:
            status = _status(row)
            key = (str(row.get("signal_timestamp") or ""), str(row.get("direction") or "").upper())
            event = build_event(
                row=row,
                regime=regime_rows.get(key, {}),
                policy=policy,
                status=status,
                observed_at=observed_at,
                code_commit=code_commit,
            )
            event, message = deliver_notification(cfg, event, existing_event_ids, governance_missing)
            if message:
                messages.append(message)
                event["notification_message"] = message
            events.append(event)

    summary = build_summary(
        cfg=cfg,
        events=events,
        all_rows_count=len(all_rows),
        legacy_excluded=legacy_excluded,
        warnings=warnings,
        notification_messages=messages,
        runtime_seconds=time.perf_counter() - started,
        telegram_configured=telegram_configured,
    )
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(cfg.output_dir / "paper_signal_stream_events.csv", events, EVENT_FIELDS)
    _write_jsonl(cfg.output_dir / "paper_signal_stream_events.jsonl", events)
    _write_json(cfg.output_dir / "paper_signal_stream_latest_state.json", summary["latest_state"])
    _write_json(cfg.output_dir / "paper_signal_stream_session_summary.json", summary)
    _write_csv(cfg.output_dir / "weekly_manual_review_template.csv", build_weekly_review_rows(events), WEEKLY_REVIEW_FIELDS)
    write_report(cfg.output_dir, cfg.docs_path, summary, messages[0] if messages else "")
    return summary


def run_stream(cfg: PaperSignalStreamConfig) -> dict[str, Any]:
    if not cfg.watch:
        return run_stream_once(cfg)
    iterations = 0
    latest: dict[str, Any] = {}
    while True:
        latest = run_stream_once(cfg)
        iterations += 1
        if cfg.max_watch_iterations is not None and iterations >= cfg.max_watch_iterations:
            return latest
        time.sleep(max(1, cfg.poll_seconds))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = PaperSignalStreamConfig(
        symbol=str(args.symbol),
        data_dir=Path(args.data_dir),
        paper_signals_path=Path(args.paper_signals_path),
        scanner_summary_path=Path(args.scanner_summary_path),
        pipeline_summary_path=Path(args.pipeline_summary_path),
        regime_diagnostics_path=Path(args.regime_diagnostics_path),
        ambiguity_governance_policy_path=Path(args.ambiguity_governance_policy_path),
        ambiguity_governance_summary_path=Path(args.ambiguity_governance_summary_path),
        output_dir=Path(args.output_dir),
        docs_path=Path(args.docs_path),
        dry_run=bool(args.dry_run),
        watch=bool(args.watch),
        poll_seconds=int(args.poll_seconds),
        max_watch_iterations=args.max_watch_iterations,
        enable_paper_telegram=bool(args.enable_paper_telegram),
        notify_blocked=bool(args.notify_blocked),
        force_resend=bool(args.force_resend),
        allow_missing_governance_dry_run=bool(args.allow_missing_governance_dry_run),
        include_legacy=bool(args.include_legacy),
    )
    print(json.dumps(run_stream(cfg), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
