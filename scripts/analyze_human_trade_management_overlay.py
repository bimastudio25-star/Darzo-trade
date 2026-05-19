from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analysis.human_trade_management import (
    PER_TRADE_EXPORT_FIELDS,
    HumanManagementConfig,
    TradeInput,
    build_synthetic_trade_examples,
    build_trade_management_record,
    metric_block_from_r,
)
from dazro_trade.analysis.local_ai_trade_judge import LocalAITradeJudge
from dazro_trade.analytics.strategy_2_hourly_session_diagnostics import (
    VARIANT_RESULT_FIELDS,
    build_strategy_2_hourly_session_diagnostics,
    sample_size_interpretation,
    sample_size_label,
    write_strategy_2_hourly_session_outputs,
)
from dazro_trade.backtest.data_loader import load_csv_timeframes


REQUIRED_TRADE_FIELDS = {"direction"}
ENTRY_FIELDS = ("entry_price", "entry")
STOP_FIELDS = ("stop_loss", "stop", "sl")
TP_FIELDS = ("original_take_profit", "take_profit", "tp1")
TIMESTAMP_FIELDS = ("entry_timestamp", "signal_timestamp", "timestamp", "time")
SAFETY = {
    "research_only": True,
    "dry_run": True,
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "order_execution_enabled": False,
    "broker_called": False,
    "telegram_sent": False,
    "order_sent": False,
    "order_send_called": False,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only human-style trade management overlay.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--trades-path", default="backtests/reports/final/executed_trades.csv")
    parser.add_argument("--output-dir", default="backtests/reports/human_style_trade_management_overlay")
    parser.add_argument("--be-trigger-usd", type=float, default=10.0)
    parser.add_argument("--partial-triggers-usd", default="15,20")
    parser.add_argument("--partial-fraction", type=float, default=0.50)
    parser.add_argument("--be-buffer-usd", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-trades", type=int, default=0)
    return parser.parse_args(argv)


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = fieldnames or (list(rows[0].keys()) if rows else [])
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_value(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if row.get(name) not in (None, ""):
            return row.get(name)
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.to_pydatetime()


def _trade_from_row(row: dict[str, Any], idx: int, symbol: str) -> tuple[TradeInput | None, list[str]]:
    missing: list[str] = []
    direction = row.get("direction")
    if not direction:
        missing.append("direction")
    entry = _to_float(_first_value(row, ENTRY_FIELDS))
    if entry is None:
        missing.append("entry_price")
    stop = _to_float(_first_value(row, STOP_FIELDS))
    if stop is None:
        missing.append("stop_loss")
    tp = _to_float(_first_value(row, TP_FIELDS))
    ts = _first_value(row, TIMESTAMP_FIELDS)
    if ts in (None, ""):
        missing.append("entry_timestamp")
    if missing:
        return None, missing
    return (
        TradeInput(
            trade_id=str(row.get("trade_id") or row.get("id") or idx),
            symbol=str(row.get("symbol") or symbol),
            strategy=str(row.get("strategy") or row.get("strategy_name") or "UNKNOWN"),
            direction=str(direction).upper(),  # type: ignore[arg-type]
            signal_timestamp=row.get("signal_timestamp") or ts,
            entry_timestamp=row.get("entry_timestamp") or ts,
            entry_price=float(entry),
            stop_loss=float(stop),
            original_take_profit=tp,
            protected_level=_to_float(row.get("protected_level")),
        ),
        [],
    )


def _slice_path(frame: pd.DataFrame | None, start: Any, *, minutes: int) -> pd.DataFrame | None:
    if frame is None or frame.empty:
        return None
    start_ts = _parse_timestamp(start)
    if start_ts is None:
        return None
    end_ts = start_ts + timedelta(minutes=minutes)
    mask = (frame["time"] >= pd.Timestamp(start_ts)) & (frame["time"] <= pd.Timestamp(end_ts))
    return frame.loc[mask].copy()


def _load_market_data(symbol: str, data_dir: str, limitations: list[str]) -> dict[str, pd.DataFrame]:
    try:
        return load_csv_timeframes(symbol, ["M1", "M5"], data_dir=data_dir)
    except Exception as exc:
        limitations.append(f"MARKET_DATA_LOAD_FAILED: {exc}")
        return {}


def _variant_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for variant, field in VARIANT_RESULT_FIELDS.items():
        values = [value for row in rows if (value := _to_float(row.get(field))) is not None]
        block = metric_block_from_r(values)
        block["statistical_label"] = sample_size_label(block["trades"])
        block["interpretation"] = sample_size_interpretation(block["trades"])
        block.update(
            {
                "BE_hit_rate": _rate(rows, "hit_be_10"),
                "BE_stopout_rate": _be_stopout_rate(rows, field),
                "partial_hit_rate": _rate(rows, "hit_partial_15") if variant == "partial_15" else _rate(rows, "hit_partial_20") if variant == "partial_20" else _rate_any(rows, ("hit_partial_15", "hit_partial_20")),
                "runner_opportunity_count": sum(1 for row in rows if row.get("runner_opportunity") not in (None, "", "STANDARD_TP")),
                "runner_hit_rate": _runner_hit_rate(rows, field),
            }
        )
        out[variant] = block
    if rows:
        out["path_availability"] = {
            "rows": len(rows),
            "m1_missing_rows": sum(1 for row in rows if "M1_PATH_DATA_MISSING" in str(row.get("decision_reason_codes") or "")),
            "m5_missing_rows": sum(1 for row in rows if "M5_CONTEXT_DATA_MISSING" in str(row.get("decision_reason_codes") or "")),
        }
    return out


def _rate(rows: list[dict[str, Any]], field: str) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if str(row.get(field)).lower() == "true") / len(rows), 4)


def _rate_any(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if any(str(row.get(field)).lower() == "true" for field in fields)) / len(rows), 4)


def _be_stopout_rate(rows: list[dict[str, Any]], r_field: str) -> float:
    if not rows:
        return 0.0
    stopped = 0
    for row in rows:
        if str(row.get("hit_be_10")).lower() != "true":
            continue
        value = _to_float(row.get(r_field))
        if value is not None and abs(value) < 0.0001:
            stopped += 1
    return round(stopped / len(rows), 4)


def _runner_hit_rate(rows: list[dict[str, Any]], r_field: str) -> float | None:
    runner_rows = [row for row in rows if row.get("runner_opportunity") not in (None, "", "STANDARD_TP")]
    if not runner_rows:
        return None
    hits = 0
    for row in runner_rows:
        result_r = _to_float(row.get(r_field))
        target_r = _to_float(row.get("dynamic_target_R"))
        if result_r is not None and target_r is not None and result_r >= target_r:
            hits += 1
    return round(hits / len(runner_rows), 4)


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Human-Style Trade Management Overlay",
        "",
        "Status: research-only dry-run overlay. No live trading, broker order, Telegram alert, or strategy entry rule was changed.",
        "",
        "## Source",
        "",
        f"- trades path: `{summary['source']['trades_path']}`",
        f"- data dir: `{summary['source']['data_dir']}`",
        f"- rows read: `{summary['source']['rows_read']}`",
        f"- rows analyzed: `{summary['source']['rows_analyzed']}`",
        f"- synthetic examples used: `{str(summary['source']['synthetic_examples_used']).lower()}`",
        "",
        "## Safety",
        "",
    ]
    for key, value in summary["safety"].items():
        lines.append(f"- {key}: `{str(value).lower()}`")
    lines.extend(
        [
            "",
            "## Variant Metrics",
            "",
            "| variant | trades | PF | WR | AvgR | MedianR | total_R | MaxDD |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for variant, metrics in summary["variant_metrics"].items():
        if variant == "path_availability":
            continue
        lines.append(
            f"| {variant} | {metrics.get('trades')} | {metrics.get('PF')} | {metrics.get('WR')} | "
            f"{metrics.get('AvgR')} | {metrics.get('MedianR')} | {metrics.get('total_R')} | {metrics.get('MaxDD')} |"
        )
    lines.extend(["", "## Limitations", ""])
    limitations = summary.get("limitations") or ["none"]
    for limitation in limitations:
        lines.append(f"- {limitation}")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- +10/+15/+20 are XAUUSD price movement thresholds, not account-dollar P/L.",
            "- +15/+20 are partial/protection zones, not maximum final TP.",
            "- The Strategy 2 14:00-16:00 window remains a benchmark hypothesis, not a live filter.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_overlay(args: argparse.Namespace) -> dict[str, str]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    partial_triggers = tuple(float(part.strip()) for part in str(args.partial_triggers_usd).split(",") if part.strip())
    config = HumanManagementConfig(
        be_trigger_usd=args.be_trigger_usd,
        partial_triggers_usd=partial_triggers or (15.0, 20.0),
        partial_close_fraction=args.partial_fraction,
        be_buffer_usd=args.be_buffer_usd,
    )
    limitations: list[str] = []
    trades_path = Path(args.trades_path)
    rows: list[dict[str, str]] = []
    columns: list[str] = []
    analyzed_rows: list[dict[str, Any]] = []
    synthetic = False

    if not trades_path.exists():
        limitations.append(f"TRADES_FILE_MISSING: {trades_path}")
        synthetic = True
        analyzed_rows = build_synthetic_trade_examples(config)
    else:
        rows, columns = _read_csv(trades_path)
        missing_static = sorted(REQUIRED_TRADE_FIELDS - set(columns))
        if missing_static:
            limitations.append(f"TRADES_FILE_MISSING_REQUIRED_FIELDS: {','.join(missing_static)}")
        market = _load_market_data(args.symbol, args.data_dir, limitations)
        m1 = market.get("M1")
        m5 = market.get("M5")
        if m1 is None or m1.empty:
            limitations.append("M1_PATH_DATA_NOT_AVAILABLE")
        if m5 is None or m5.empty:
            limitations.append("M5_CONTEXT_DATA_NOT_AVAILABLE")
        local_ai = LocalAITradeJudge()
        selected_rows = rows[: args.max_trades] if args.max_trades and args.max_trades > 0 else rows
        for idx, row in enumerate(selected_rows):
            trade, missing = _trade_from_row(row, idx, args.symbol)
            if trade is None:
                limitations.append(f"ROW_{idx}_MISSING_FIELDS: {','.join(missing)}")
                continue
            m1_path = _slice_path(m1, trade.entry_timestamp, minutes=config.max_path_bars) if m1 is not None else None
            m5_path = _slice_path(m5, trade.entry_timestamp, minutes=5 * max(1, config.max_path_bars // 5)) if m5 is not None else None
            ai_payload = {
                "trade_id": trade.trade_id,
                "symbol": trade.symbol,
                "strategy": trade.strategy,
                "direction": trade.direction,
                "entry_price": trade.entry_price,
                "stop_loss": trade.stop_loss,
                "original_take_profit": trade.original_take_profit,
                "be_trigger_usd": config.be_trigger_usd,
                "partial_triggers_usd": config.partial_triggers_usd,
                "m1_path_rows": 0 if m1_path is None else len(m1_path),
                "m5_context_rows": 0 if m5_path is None else len(m5_path),
            }
            ai_result = local_ai.judge(ai_payload).to_dict()
            record = build_trade_management_record(
                trade,
                m1_candles=m1_path,
                m5_candles=m5_path,
                config=config,
                ai_judge_result=ai_result,
            )
            exported_baseline_r = _to_float(row.get("r_multiple"))
            if exported_baseline_r is not None:
                record["result_baseline_R"] = round(exported_baseline_r, 4)
            analyzed_rows.append(record)
        if not analyzed_rows:
            synthetic = True
            limitations.append("NO_ROWS_ANALYZED_FROM_TRADES_FILE_SYNTHETIC_EXAMPLES_USED")
            analyzed_rows = build_synthetic_trade_examples(config)

    variant_metrics = _variant_metrics(analyzed_rows)
    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "trades_path": str(trades_path),
            "data_dir": args.data_dir,
            "rows_read": len(rows),
            "columns_available": columns,
            "rows_analyzed": len(analyzed_rows),
            "synthetic_examples_used": synthetic,
        },
        "config": {
            "be_trigger_usd": config.be_trigger_usd,
            "partial_triggers_usd": list(config.partial_triggers_usd),
            "partial_close_fraction": config.partial_close_fraction,
            "be_buffer_usd": config.be_buffer_usd,
        },
        "safety": SAFETY,
        "limitations": limitations,
        "variant_metrics": variant_metrics,
    }
    trade_csv = output_dir / "human_management_trades.csv"
    trade_jsonl = output_dir / "human_management_trades.jsonl"
    summary_json = output_dir / "human_management_summary.json"
    report_md = output_dir / "human_management_report.md"
    _write_csv(trade_csv, analyzed_rows, fieldnames=PER_TRADE_EXPORT_FIELDS)
    _write_jsonl(trade_jsonl, analyzed_rows)
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    report_md.write_text(render_report(summary), encoding="utf-8")

    s2_report = build_strategy_2_hourly_session_diagnostics(analyzed_rows, PER_TRADE_EXPORT_FIELDS, source_path=str(trades_path))
    s2_paths = write_strategy_2_hourly_session_outputs(s2_report, output_dir)
    return {
        "human_management_trades_csv": str(trade_csv),
        "human_management_trades_jsonl": str(trade_jsonl),
        "human_management_summary_json": str(summary_json),
        "human_management_report_md": str(report_md),
        **s2_paths,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = run_overlay(args)
    print(json.dumps(paths, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
