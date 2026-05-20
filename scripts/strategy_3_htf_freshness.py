from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_xauusd_data import TIMEFRAME_INTERVALS, read_candle_csv, validate_frame
from scripts.fetch_xauusd_mt5_candles import _existing_overlap

HTF_TIMEFRAMES = ["D1", "H4", "H1"]


def _as_utc_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _iso(value: Any) -> str | None:
    ts = _as_utc_timestamp(value)
    return ts.isoformat() if ts is not None else None


def _latest_timestamp(frame: pd.DataFrame) -> pd.Timestamp | None:
    if frame.empty or "time" not in frame.columns:
        return None
    times = pd.to_datetime(frame["time"], utc=True, errors="coerce").dropna()
    return times.max() if not times.empty else None


def _floor_to_timeframe(ts: pd.Timestamp, timeframe: str) -> pd.Timestamp:
    ts = ts.tz_convert("UTC") if ts.tzinfo is not None else ts.tz_localize("UTC")
    if timeframe == "D1":
        return ts.normalize()
    if timeframe == "H4":
        return ts.replace(hour=(ts.hour // 4) * 4, minute=0, second=0, microsecond=0, nanosecond=0)
    if timeframe == "H1":
        return ts.replace(minute=0, second=0, microsecond=0, nanosecond=0)
    if timeframe == "M15":
        return ts.replace(minute=(ts.minute // 15) * 15, second=0, microsecond=0, nanosecond=0)
    if timeframe == "M5":
        return ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0, nanosecond=0)
    if timeframe == "M1":
        return ts.replace(second=0, microsecond=0, nanosecond=0)
    raise ValueError(f"unsupported_timeframe={timeframe}")


def expected_latest_closed_timestamp(now_utc: datetime | pd.Timestamp, timeframe: str, grace_seconds: int = 5) -> pd.Timestamp:
    ts = _as_utc_timestamp(now_utc)
    if ts is None:
        raise ValueError("now_utc_required")
    duration = TIMEFRAME_INTERVALS[timeframe]
    threshold = ts - pd.Timedelta(seconds=max(0, grace_seconds))
    current_open = _floor_to_timeframe(ts, timeframe)
    if current_open + duration <= threshold:
        return current_open
    return current_open - duration


def _read_frame(path: Path) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    if not path.exists():
        return pd.DataFrame(), ["FILE_MISSING"], {"exists": False}
    try:
        read = read_candle_csv(path)
        validation = validate_frame(read.frame, path.stem)
        return read.frame, [], {"exists": True, "schema": read.schema, **validation}
    except Exception as exc:
        return pd.DataFrame(), ["DATA_READ_FAILED"], {"exists": True, "error": str(exc)}


def _overlap_detail(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    timeframe: str,
    tolerance: float,
    collector_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    detail = (
        (collector_summary or {})
        .get("overlap_validation", {})
        .get("details_by_timeframe", {})
        .get(timeframe)
    )
    if detail:
        return dict(detail)
    if existing.empty or incoming.empty:
        return {
            "verdict": "OVERLAP_NO_DATA",
            "overlap_rows_existing": 0 if existing.empty else int(len(existing)),
            "overlap_rows_fetched": 0 if incoming.empty else int(len(incoming)),
            "overlap_matched_rows": 0,
            "overlap_mismatched_rows": 0,
            "overlap_match_rate": None,
            "worst_ohlc_diff": None,
            "first_mismatch_timestamp": None,
            "last_mismatch_timestamp": None,
            "mismatch_example_existing_ohlcv": None,
            "mismatch_example_incoming_ohlcv": None,
            "overlap_validation_basis": "closed_candles_only",
        }
    return _existing_overlap(existing, incoming, timeframe, tolerance, closed_only=True)


def _stale_bar_count(latest: pd.Timestamp | None, expected: pd.Timestamp, timeframe: str) -> int | None:
    if latest is None:
        return None
    if latest >= expected:
        return 0
    interval = TIMEFRAME_INTERVALS[timeframe]
    return max(1, int((expected - latest) / interval))


def _freshness_status(
    *,
    timeframe: str,
    latest_existing: pd.Timestamp | None,
    expected_closed: pd.Timestamp,
    stale_by_bars: int | None,
    quarantined: bool,
) -> str:
    if latest_existing is None:
        return "missing"
    if quarantined and stale_by_bars and stale_by_bars > 0:
        return "stale_blocking"
    if quarantined:
        return "quarantined"
    if stale_by_bars and stale_by_bars > 0:
        return "stale_blocking" if timeframe in {"H4", "H1"} else "stale_warning"
    if timeframe == "D1" and latest_existing == expected_closed:
        return "acceptable_closed_candle_lag"
    return "fresh"


def _recommend_h4_action(item: dict[str, Any], tolerance: float) -> str:
    verdict = item.get("overlap_verdict")
    worst = item.get("worst_ohlc_diff")
    is_stale = bool(item.get("is_stale"))
    if not is_stale and verdict in {"OVERLAP_MATCH_100", "OVERLAP_MATCH_100_CLOSED_CANDLES", "OVERLAP_MATCH_GT_95", "OVERLAP_NO_DATA"}:
        return "safe_apply"
    if verdict == "OVERLAP_MATCH_LT_95" and worst is not None and float(worst) > tolerance:
        return "scanner_block_until_fresh"
    if is_stale:
        return "manual_review_required"
    return "quarantine_keep_existing"


def analyze_htf_freshness(
    *,
    data_dir: Path,
    symbol: str,
    incoming_dir: Path | None = None,
    collector_summary: dict[str, Any] | None = None,
    market_data: dict[str, pd.DataFrame] | None = None,
    now_utc: datetime | pd.Timestamp | None = None,
    timeframes: list[str] | None = None,
    grace_seconds: int = 5,
    overlap_price_tolerance_usd: float = 0.10,
) -> dict[str, Any]:
    timeframes = timeframes or list(HTF_TIMEFRAMES)
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    now_ts = _as_utc_timestamp(now_utc)
    if now_ts is None:
        raise ValueError("now_utc_required")

    quarantined = set((collector_summary or {}).get("timeframes_quarantined_by_overlap", []) or [])
    latest_closed_from_collector = (collector_summary or {}).get("latest_closed_timestamp_by_timeframe", {}) or {}
    skipped_from_collector = (collector_summary or {}).get("forming_candles_skipped_by_timeframe", {}) or {}

    items: list[dict[str, Any]] = []
    stale_timeframes: list[str] = []
    quarantined_timeframes: list[str] = sorted(quarantined)
    for tf in timeframes:
        existing_path = data_dir / symbol / f"{tf}.csv"
        incoming_path = (incoming_dir / f"{tf}.csv") if incoming_dir else None
        if market_data and tf in market_data:
            existing = market_data[tf].copy()
            existing_meta = {"exists": True, **validate_frame(existing, tf)}
        else:
            existing, _, existing_meta = _read_frame(existing_path)
        incoming = pd.DataFrame()
        incoming_meta: dict[str, Any] = {"exists": False}
        if incoming_path is not None and incoming_path.exists():
            incoming, _, incoming_meta = _read_frame(incoming_path)

        latest_existing = _latest_timestamp(existing)
        latest_incoming = _latest_timestamp(incoming)
        latest_closed_incoming = _as_utc_timestamp(latest_closed_from_collector.get(tf)) or latest_incoming
        expected_closed = expected_latest_closed_timestamp(now_ts, tf, grace_seconds)
        stale_by_bars = _stale_bar_count(latest_existing, expected_closed, tf)
        is_stale = stale_by_bars is not None and stale_by_bars > 0
        if is_stale:
            stale_timeframes.append(tf)

        overlap = _overlap_detail(existing, incoming, tf, overlap_price_tolerance_usd, collector_summary)
        status = _freshness_status(
            timeframe=tf,
            latest_existing=latest_existing,
            expected_closed=expected_closed,
            stale_by_bars=stale_by_bars,
            quarantined=tf in quarantined,
        )
        worst = overlap.get("worst_ohlc_diff")
        material_mismatch = worst is not None and float(worst) > overlap_price_tolerance_usd
        quarantine_reason = None
        if tf in quarantined:
            quarantine_reason = "HTF_OVERLAP_MISMATCH_QUARANTINED"
        elif overlap.get("verdict") == "OVERLAP_MATCH_LT_95":
            quarantine_reason = "OVERLAP_MATCH_LT_95"

        item = {
            "timeframe": tf,
            "existing_csv_path": str(existing_path),
            "incoming_csv_path": str(incoming_path) if incoming_path else None,
            "latest_existing_timestamp": _iso(latest_existing),
            "latest_incoming_timestamp": _iso(latest_incoming),
            "latest_closed_incoming_timestamp": _iso(latest_closed_incoming),
            "expected_latest_closed_timestamp": _iso(expected_closed),
            "forming_candles_skipped": int(skipped_from_collector.get(tf, 0) or 0),
            "overlap_window_size": overlap.get("overlap_rows_existing"),
            "overlap_matches": overlap.get("overlap_matched_rows"),
            "overlap_mismatches": overlap.get("overlap_mismatched_rows"),
            "overlap_match_rate": overlap.get("overlap_match_rate"),
            "overlap_verdict": overlap.get("verdict"),
            "first_mismatch_timestamp": overlap.get("first_mismatch_timestamp"),
            "last_mismatch_timestamp": overlap.get("last_mismatch_timestamp"),
            "mismatch_example_existing_ohlcv": overlap.get("mismatch_example_existing_ohlcv"),
            "mismatch_example_incoming_ohlcv": overlap.get("mismatch_example_incoming_ohlcv"),
            "worst_ohlc_diff": overlap.get("worst_ohlc_diff"),
            "material_ohlc_mismatch": material_mismatch,
            "quarantine_reason": quarantine_reason,
            "is_stale": is_stale,
            "stale_by_seconds": float((expected_closed - latest_existing).total_seconds()) if latest_existing is not None and latest_existing < expected_closed else 0.0,
            "stale_by_bars": stale_by_bars,
            "freshness_status": status,
            "existing_validation": existing_meta,
            "incoming_validation": incoming_meta,
        }
        if tf == "H4":
            item["recoverable"] = not material_mismatch and overlap.get("verdict") in {"OVERLAP_MATCH_100", "OVERLAP_MATCH_100_CLOSED_CANDLES", "OVERLAP_MATCH_GT_95", "OVERLAP_NO_DATA"}
            item["recommended_action"] = _recommend_h4_action(item, overlap_price_tolerance_usd)
        if tf == "D1":
            item["closed_candle_lag_expected"] = latest_existing == expected_closed
        items.append(item)

    h4_item = next((item for item in items if item["timeframe"] == "H4"), {})
    d1_item = next((item for item in items if item["timeframe"] == "D1"), {})
    h4_blocking = h4_item.get("freshness_status") in {"stale_blocking", "missing"} or bool(h4_item.get("quarantine_reason"))
    summary_status = "stale_blocking" if h4_blocking else ("stale_warning" if stale_timeframes else "fresh")
    return {
        "run_started_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "now_utc": now_ts.isoformat(),
        "timeframes": items,
        "htf_freshness_status": summary_status,
        "stale_timeframes": stale_timeframes,
        "quarantined_timeframes": quarantined_timeframes,
        "h4_quarantine_status": h4_item.get("freshness_status"),
        "h4_latest_existing_timestamp": h4_item.get("latest_existing_timestamp"),
        "h4_expected_latest_closed_timestamp": h4_item.get("expected_latest_closed_timestamp"),
        "h4_stale_by_bars": h4_item.get("stale_by_bars"),
        "h4_quarantine_reason": h4_item.get("quarantine_reason"),
        "h4_recommended_action": h4_item.get("recommended_action"),
        "d1_closed_candle_lag_expected": bool(d1_item.get("closed_candle_lag_expected")),
        "scanner_blocked_due_to_stale_htf": bool(h4_blocking),
        "paper_signals_clean_for_validation": not bool(h4_blocking),
        "safety": {
            "data_modified": False,
            "live_trading_enabled": False,
            "telegram_enabled": False,
            "order_execution_enabled": False,
            "broker_called": False,
            "telegram_sent": False,
            "order_sent": False,
        },
    }


def write_h4_quarantine_report(diagnostic: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_json = output_dir / "h4_quarantine_report.json"
    report_md = output_dir / "h4_quarantine_report.md"
    report_json.write_text(json.dumps(diagnostic, indent=2, sort_keys=True, default=str), encoding="utf-8")
    h4 = next((item for item in diagnostic.get("timeframes", []) if item.get("timeframe") == "H4"), {})
    d1 = next((item for item in diagnostic.get("timeframes", []) if item.get("timeframe") == "D1"), {})
    lines = [
        "# Strategy 3 H4 Quarantine Diagnostic",
        "",
        "This report is data integrity diagnostics only. No live trading, Telegram signal, broker execution, or Strategy 3 logic change is involved.",
        "",
        f"- symbol: `{diagnostic.get('symbol')}`",
        f"- now_utc: `{diagnostic.get('now_utc')}`",
        f"- htf_freshness_status: `{diagnostic.get('htf_freshness_status')}`",
        f"- stale_timeframes: `{', '.join(diagnostic.get('stale_timeframes', []))}`",
        f"- quarantined_timeframes: `{', '.join(diagnostic.get('quarantined_timeframes', []))}`",
        "",
        "## H4",
        "",
        f"- latest_existing_timestamp: `{h4.get('latest_existing_timestamp')}`",
        f"- latest_closed_incoming_timestamp: `{h4.get('latest_closed_incoming_timestamp')}`",
        f"- expected_latest_closed_timestamp: `{h4.get('expected_latest_closed_timestamp')}`",
        f"- stale_by_bars: `{h4.get('stale_by_bars')}`",
        f"- quarantine_reason: `{h4.get('quarantine_reason')}`",
        f"- overlap_verdict: `{h4.get('overlap_verdict')}`",
        f"- overlap_match_rate: `{h4.get('overlap_match_rate')}`",
        f"- worst_ohlc_diff: `{h4.get('worst_ohlc_diff')}`",
        f"- first_mismatch_timestamp: `{h4.get('first_mismatch_timestamp')}`",
        f"- last_mismatch_timestamp: `{h4.get('last_mismatch_timestamp')}`",
        f"- material_ohlc_mismatch: `{h4.get('material_ohlc_mismatch')}`",
        f"- recoverable: `{h4.get('recoverable')}`",
        f"- recommended_action: `{h4.get('recommended_action')}`",
        "",
        "## D1",
        "",
        f"- latest_existing_timestamp: `{d1.get('latest_existing_timestamp')}`",
        f"- expected_latest_closed_timestamp: `{d1.get('expected_latest_closed_timestamp')}`",
        f"- closed_candle_lag_expected: `{d1.get('closed_candle_lag_expected')}`",
        "",
        "## Mismatch Example",
        "",
        f"- existing: `{h4.get('mismatch_example_existing_ohlcv')}`",
        f"- incoming: `{h4.get('mismatch_example_incoming_ohlcv')}`",
        "",
    ]
    report_md.write_text("\n".join(lines), encoding="utf-8")


def create_h4_backup_before_recovery(h4_path: Path, timestamp: datetime | None = None) -> Path:
    if not h4_path.exists():
        raise FileNotFoundError(str(h4_path))
    timestamp = timestamp or datetime.now(timezone.utc)
    backup = h4_path.with_name(f"{h4_path.name}.backup.{timestamp:%Y%m%dT%H%M%SZ}")
    backup.write_bytes(h4_path.read_bytes())
    return backup
