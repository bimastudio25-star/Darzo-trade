from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analysis.strategy_3_vwap_1r import Strategy3Diagnostics, evaluate_strategy_3_vwap_1r
from dazro_trade.backtest.data_loader import BacktestDataSlicer, load_csv_timeframes
from dazro_trade.runtime.sessions import current_session_name

STRATEGY_NAME = "strategy_3_vwap_1r"
REQUIRED_PAPER_FIELDS = [
    "signal_timestamp",
    "symbol",
    "strategy",
    "mode",
    "dry_run",
    "cooldown_minutes",
    "direction",
    "entry_price",
    "stop_loss",
    "take_profit",
    "setup_mode",
    "band_touched",
    "cooldown_accepted",
    "order_sent",
    "telegram_sent",
    "broker_called",
]
SAFETY_FIELDS = [
    "live_trading_enabled",
    "telegram_enabled",
    "order_execution_enabled",
    "broker_called",
    "telegram_sent",
    "order_sent",
]
SAFETY = {
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "order_execution_enabled": False,
    "broker_called": False,
    "telegram_sent": False,
    "order_sent": False,
}
MATCH_COLUMNS = [
    "paper_signal_timestamp",
    "backtest_signal_timestamp",
    "direction",
    "entry_price",
    "stop_loss",
    "take_profit",
    "setup_mode",
    "band_touched",
    "cooldown_accepted",
]
MISMATCH_COLUMNS = MATCH_COLUMNS + ["mismatch_categories", "details"]


@dataclass(frozen=True)
class CompareConfig:
    paper_dir: Path
    data_dir: str
    output_dir: Path
    symbol: str
    strategy: str
    cooldown_minutes: int
    price_tolerance_usd: float
    timestamp_tolerance_seconds: int
    warmup_buffer_hours: float = 2.0
    post_signal_buffer_minutes: float = 5.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Strategy 3 paper shadow signals against narrow backtest signals")
    parser.add_argument("--paper-dir", default="backtests/reports/strategy_3_paper_shadow_scanner")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_3_shadow_vs_backtest_comparison")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--strategy", default=STRATEGY_NAME)
    parser.add_argument("--cooldown-minutes", type=int, default=120)
    parser.add_argument("--price-tolerance-usd", type=float, default=0.01)
    parser.add_argument("--timestamp-tolerance-seconds", type=int, default=0)
    parser.add_argument("--warmup-buffer-hours", type=float, default=2.0)
    parser.add_argument("--post-signal-buffer-minutes", type=float, default=5.0)
    return parser.parse_args(argv)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _parse_ts(value: Any) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.to_pydatetime()


def load_paper_signals(paper_dir: Path) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    csv_path = paper_dir / "paper_signals.csv"
    summary_path = paper_dir / "scanner_summary.json"
    if not csv_path.exists():
        return [], REQUIRED_PAPER_FIELDS, {"missing_file": str(csv_path)}
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    scanner_summary: dict[str, Any] = {}
    if summary_path.exists():
        scanner_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    missing = [field for field in REQUIRED_PAPER_FIELDS if field not in fieldnames]
    return rows, missing, scanner_summary


def paper_window(rows: list[dict[str, Any]], cfg: CompareConfig) -> dict[str, str] | None:
    if not rows:
        return None
    times = [_parse_ts(row["signal_timestamp"]) for row in rows]
    earliest = min(times)
    latest = max(times)
    return {
        "backtest_from": (earliest - timedelta(hours=cfg.warmup_buffer_hours)).isoformat(),
        "backtest_to": (latest + timedelta(minutes=cfg.post_signal_buffer_minutes)).isoformat(),
        "earliest_paper_signal_timestamp": earliest.isoformat(),
        "latest_paper_signal_timestamp": latest.isoformat(),
    }


def _signal_row(
    *,
    when: datetime,
    signal: Any,
    cooldown_accepted: bool,
    cooldown_reason: str | None,
) -> dict[str, Any]:
    vwap = signal.confluences.get("vwap") if isinstance(signal.confluences, dict) else {}
    return {
        "signal_timestamp": when.isoformat(),
        "symbol": signal.symbol,
        "strategy": STRATEGY_NAME,
        "direction": signal.direction,
        "entry_price": float(signal.entry),
        "stop_loss": float(signal.stop),
        "take_profit": float(signal.tp1),
        "setup_mode": signal.setup_mode,
        "band_touched": signal.band_touched,
        "cooldown_accepted": cooldown_accepted,
        "cooldown_status": "accepted" if cooldown_accepted else "blocked",
        "cooldown_block_reason": cooldown_reason,
        "vwap_value": vwap.get("vwap") if isinstance(vwap, dict) else None,
        "sigma_1_upper": vwap.get("upper_1") if isinstance(vwap, dict) else None,
        "sigma_1_lower": vwap.get("lower_1") if isinstance(vwap, dict) else None,
        "sigma_2_upper": vwap.get("upper_2") if isinstance(vwap, dict) else None,
        "sigma_2_lower": vwap.get("lower_2") if isinstance(vwap, dict) else None,
    }


def build_backtest_comparable_signals(cfg: CompareConfig, window: dict[str, str]) -> list[dict[str, Any]]:
    market_data = load_csv_timeframes(
        cfg.symbol,
        ["M1", "M5", "M15", "H1", "H4", "D1"],
        data_dir=cfg.data_dir,
        date_from=_parse_ts(window["backtest_from"]),
        date_to=_parse_ts(window["backtest_to"]),
    )
    slicer = BacktestDataSlicer(
        market_data,
        fast_mode=True,
        lookback_by_timeframe={"M1": 2000, "M5": 2000, "M15": 1000, "H1": 1000, "H4": 500, "D1": 500},
    )
    driver = slicer.frame("M15")
    if driver.empty:
        return []
    start = _parse_ts(window["backtest_from"])
    end = _parse_ts(window["backtest_to"])
    times = pd.to_datetime(driver["time"], utc=True)
    driver_times = [ts.to_pydatetime() for ts in times[(times >= pd.Timestamp(start)) & (times <= pd.Timestamp(end))]]
    diagnostics = Strategy3Diagnostics()
    last_by_key: dict[tuple[str, str], datetime] = {}
    out: list[dict[str, Any]] = []
    for when in driver_times:
        signal = evaluate_strategy_3_vwap_1r(
            slicer.slice_up_to(when),
            symbol=cfg.symbol,
            now_utc=when,
            diagnostics=diagnostics,
        )
        if signal is None:
            continue
        key = (cfg.symbol, signal.direction)
        last = last_by_key.get(key)
        accepted = last is None or when - last >= timedelta(minutes=cfg.cooldown_minutes)
        reason = None if accepted else "STRATEGY_3_COOLDOWN_BLOCKED"
        if accepted:
            last_by_key[key] = when
        out.append(_signal_row(when=when, signal=signal, cooldown_accepted=accepted, cooldown_reason=reason))
    return out


def _find_timestamp_match(
    paper: dict[str, Any],
    backtest_rows: list[dict[str, Any]],
    used: set[int],
    tolerance_seconds: int,
) -> tuple[int | None, dict[str, Any] | None]:
    p_ts = _parse_ts(paper["signal_timestamp"])
    best_idx = None
    best_delta = None
    for idx, row in enumerate(backtest_rows):
        if idx in used:
            continue
        delta = abs((_parse_ts(row["signal_timestamp"]) - p_ts).total_seconds())
        if delta <= tolerance_seconds and (best_delta is None or delta < best_delta):
            best_idx = idx
            best_delta = delta
    if best_idx is None:
        return None, None
    return best_idx, backtest_rows[best_idx]


def compare_signals(
    paper_rows: list[dict[str, Any]],
    backtest_rows: list[dict[str, Any]],
    *,
    price_tolerance_usd: float = 0.01,
    timestamp_tolerance_seconds: int = 0,
) -> dict[str, Any]:
    matched: list[dict[str, Any]] = []
    mismatched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    used_backtest: set[int] = set()
    categories: dict[str, int] = {}

    def bump(name: str) -> None:
        categories[name] = categories.get(name, 0) + 1

    for paper in paper_rows:
        idx, backtest = _find_timestamp_match(paper, backtest_rows, used_backtest, timestamp_tolerance_seconds)
        if backtest is None or idx is None:
            bump("MISSING_IN_BACKTEST")
            missing.append(paper)
            continue
        used_backtest.add(idx)
        row_categories: list[str] = []
        details: dict[str, Any] = {}

        def mismatch(name: str, paper_value: Any, backtest_value: Any) -> None:
            row_categories.append(name)
            details[name] = {"paper": paper_value, "backtest": backtest_value}
            bump(name)

        if str(paper.get("direction")) != str(backtest.get("direction")):
            mismatch("DIRECTION_MISMATCH", paper.get("direction"), backtest.get("direction"))
        for paper_key, backtest_key, category in (
            ("entry_price", "entry_price", "ENTRY_PRICE_MISMATCH"),
            ("stop_loss", "stop_loss", "STOP_LOSS_MISMATCH"),
            ("take_profit", "take_profit", "TAKE_PROFIT_MISMATCH"),
        ):
            if abs(float(paper.get(paper_key) or 0) - float(backtest.get(backtest_key) or 0)) > price_tolerance_usd:
                mismatch(category, paper.get(paper_key), backtest.get(backtest_key))
        if str(paper.get("setup_mode")) != str(backtest.get("setup_mode")):
            mismatch("SETUP_MODE_MISMATCH", paper.get("setup_mode"), backtest.get("setup_mode"))
        if str(paper.get("band_touched")) != str(backtest.get("band_touched")):
            mismatch("BAND_TOUCHED_MISMATCH", paper.get("band_touched"), backtest.get("band_touched"))
        if _bool(paper.get("cooldown_accepted")) != bool(backtest.get("cooldown_accepted")):
            mismatch("COOLDOWN_STATUS_MISMATCH", paper.get("cooldown_accepted"), backtest.get("cooldown_accepted"))
        for key in ("vwap_value", "sigma_1_upper", "sigma_1_lower", "sigma_2_upper", "sigma_2_lower"):
            if paper.get(key) not in (None, "") and backtest.get(key) is not None:
                if abs(float(paper.get(key)) - float(backtest.get(key))) > price_tolerance_usd:
                    mismatch("VWAP_CONTEXT_MISMATCH", paper.get(key), backtest.get(key))
                    break
        base = {
            "paper_signal_timestamp": paper.get("signal_timestamp"),
            "backtest_signal_timestamp": backtest.get("signal_timestamp"),
            "direction": paper.get("direction"),
            "entry_price": paper.get("entry_price"),
            "stop_loss": paper.get("stop_loss"),
            "take_profit": paper.get("take_profit"),
            "setup_mode": paper.get("setup_mode"),
            "band_touched": paper.get("band_touched"),
            "cooldown_accepted": paper.get("cooldown_accepted"),
        }
        if row_categories:
            mismatched.append({**base, "mismatch_categories": ";".join(row_categories), "details": json.dumps(details, sort_keys=True)})
        else:
            matched.append(base)

    extra = [row for idx, row in enumerate(backtest_rows) if idx not in used_backtest]
    if extra:
        categories["EXTRA_IN_BACKTEST"] = categories.get("EXTRA_IN_BACKTEST", 0) + len(extra)
    denom = max(len(paper_rows), len(backtest_rows))
    match_rate = (len(matched) / denom) if denom else None
    return {
        "matched": matched,
        "mismatched": mismatched,
        "missing": missing,
        "extra": extra,
        "mismatch_categories": categories,
        "match_rate": match_rate,
    }


def verdict_flags(
    *,
    paper_count: int,
    backtest_count: int | None,
    match_rate: float | None,
    missing_schema: list[str],
    safety_regression: bool,
) -> list[str]:
    flags: list[str] = []
    if paper_count == 0 and (backtest_count is None or backtest_count == 0):
        flags.extend(["SHADOW_COMPARISON_NO_PAPER_SIGNALS_YET", "FRAMEWORK_READY", "NO_BACKTEST_COMPARISON_PERFORMED"])
    elif paper_count == 0 and backtest_count and backtest_count > 0:
        flags.extend(["BACKTEST_GENERATES_BUT_SCANNER_DOES_NOT", "RUNTIME_BACKTEST_PIPELINE_BUG_LIKELY"])
    elif paper_count > 0 and backtest_count == 0:
        flags.extend(["SCANNER_GENERATES_BUT_BACKTEST_DOES_NOT", "RUNTIME_BACKTEST_PIPELINE_BUG_LIKELY"])
    elif match_rate is not None and match_rate >= 0.95:
        flags.extend(["SHADOW_BACKTEST_MATCH_CONFIRMED", "RUNTIME_BACKTEST_CONSISTENCY_OK"])
    elif match_rate is not None and match_rate >= 0.80:
        flags.extend(["SHADOW_BACKTEST_PARTIAL_MISMATCH", "RUNTIME_BACKTEST_REVIEW_REQUIRED"])
    else:
        flags.extend(["SHADOW_BACKTEST_MAJOR_DIVERGENCE", "RUNTIME_BACKTEST_PIPELINE_BUG_LIKELY"])
    if safety_regression:
        flags.append("SAFETY_REGRESSION_BLOCKER")
    if missing_schema:
        flags.append("SHADOW_SIGNAL_SCHEMA_INCOMPLETE")
    return flags


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def _write_outputs(output_dir: Path, summary: dict[str, Any], comparison: dict[str, Any] | None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "comparison_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    if comparison is not None:
        _write_csv(output_dir / "matched_signals.csv", comparison["matched"], MATCH_COLUMNS)
        _write_csv(output_dir / "mismatched_signals.csv", comparison["mismatched"], MISMATCH_COLUMNS)
        _write_csv(output_dir / "missing_in_backtest.csv", comparison["missing"], list(comparison["missing"][0].keys()) if comparison["missing"] else REQUIRED_PAPER_FIELDS)
        _write_csv(output_dir / "extra_in_backtest.csv", comparison["extra"], list(comparison["extra"][0].keys()) if comparison["extra"] else MATCH_COLUMNS)
    flags = ", ".join(summary["verdict_flags"])
    window = summary.get("comparison_window")
    report = [
        "# Strategy 3 Shadow vs Backtest Comparison",
        "",
        "This is a paper/research comparison only. No live trading, Telegram, broker, or order path was used.",
        "",
        f"- paper_signals_count: `{summary['paper_signals_count']}`",
        f"- backtest_signals_count: `{summary['backtest_signals_count']}`",
        f"- matched_count: `{summary['matched_count']}`",
        f"- match_rate: `{summary['match_rate']}`",
        f"- verdict_flags: `{flags}`",
        f"- comparison_window: `{window}`",
        "",
    ]
    if summary["paper_signals_count"] == 0:
        report.extend([
            "No paper signals are available yet. This is not a failure; rerun the paper shadow scanner after new data arrives, then rerun this comparison once 10-20 paper signals have accumulated.",
            "",
        ])
    (output_dir / "comparison_report.md").write_text("\n".join(report), encoding="utf-8")


def run_comparison(cfg: CompareConfig) -> dict[str, Any]:
    started = perf_counter()
    run_started_at = _utc_now()
    paper_rows, missing_schema, scanner_summary = load_paper_signals(cfg.paper_dir)
    safety_regression = any(_bool(row.get(field)) for row in paper_rows for field in ("order_sent", "telegram_sent", "broker_called"))
    comparison_window = paper_window(paper_rows, cfg) if not missing_schema else None
    backtest_rows: list[dict[str, Any]] | None = None
    comparison: dict[str, Any] | None = None

    if paper_rows and comparison_window and not missing_schema:
        backtest_rows = build_backtest_comparable_signals(cfg, comparison_window)
        comparison = compare_signals(
            paper_rows,
            backtest_rows,
            price_tolerance_usd=cfg.price_tolerance_usd,
            timestamp_tolerance_seconds=cfg.timestamp_tolerance_seconds,
        )
    elif paper_rows and missing_schema:
        comparison = {
            "matched": [],
            "mismatched": [],
            "missing": [],
            "extra": [],
            "mismatch_categories": {"SCHEMA_MISSING_FIELD": len(missing_schema)},
            "match_rate": 0,
        }

    paper_count = len(paper_rows)
    backtest_count = len(backtest_rows) if backtest_rows is not None else (0 if paper_count == 0 else None)
    matched_count = len(comparison["matched"]) if comparison else 0
    missing_count = len(comparison["missing"]) if comparison else 0
    extra_count = len(comparison["extra"]) if comparison else 0
    mismatched_count = len(comparison["mismatched"]) if comparison else 0
    match_rate = comparison["match_rate"] if comparison else None
    flags = verdict_flags(
        paper_count=paper_count,
        backtest_count=backtest_count,
        match_rate=match_rate,
        missing_schema=missing_schema,
        safety_regression=safety_regression,
    )
    summary = {
        "run_started_at": run_started_at,
        "run_finished_at": _utc_now(),
        "runtime_seconds": round(perf_counter() - started, 4),
        "paper_dir": str(cfg.paper_dir),
        "output_dir": str(cfg.output_dir),
        "symbol": cfg.symbol,
        "strategy": cfg.strategy,
        "cooldown_minutes": cfg.cooldown_minutes,
        "warmup_buffer_hours": cfg.warmup_buffer_hours,
        "post_signal_buffer_minutes": cfg.post_signal_buffer_minutes,
        "price_tolerance_usd": cfg.price_tolerance_usd,
        "timestamp_tolerance_seconds": cfg.timestamp_tolerance_seconds,
        "paper_signals_count": paper_count,
        "backtest_signals_count": backtest_count,
        "matched_count": matched_count,
        "mismatched_count": mismatched_count,
        "missing_in_backtest_count": missing_count,
        "extra_in_backtest_count": extra_count,
        "match_rate": match_rate,
        "mismatch_categories": comparison["mismatch_categories"] if comparison else {},
        "missing_schema_fields": missing_schema,
        "verdict_flags": flags,
        "comparison_window": comparison_window,
        "scanner_summary_run_id": scanner_summary.get("scanner_run_id"),
        "safety": dict(SAFETY),
    }
    _write_outputs(cfg.output_dir, summary, comparison)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = CompareConfig(
        paper_dir=Path(args.paper_dir),
        data_dir=args.data_dir,
        output_dir=Path(args.output_dir),
        symbol=args.symbol,
        strategy=args.strategy,
        cooldown_minutes=int(args.cooldown_minutes),
        price_tolerance_usd=float(args.price_tolerance_usd),
        timestamp_tolerance_seconds=int(args.timestamp_tolerance_seconds),
        warmup_buffer_hours=float(args.warmup_buffer_hours),
        post_signal_buffer_minutes=float(args.post_signal_buffer_minutes),
    )
    summary = run_comparison(cfg)
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
