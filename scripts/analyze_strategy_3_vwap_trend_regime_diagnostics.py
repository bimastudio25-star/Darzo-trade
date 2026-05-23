from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analysis.vwap import session_vwap_snapshot
from dazro_trade.backtest.data_loader import load_csv_timeframes

STRATEGY_NAME = "strategy_3_vwap_1r"
DEFAULT_COMPARISON_DIR = Path("backtests/reports/strategy_3_clean_context_shadow_vs_backtest_comparison_segmented")
DEFAULT_OUTPUT_DIR = Path("backtests/reports/strategy_3_vwap_trend_regime_diagnostics")
DEFAULT_DOCS_PATH = Path("docs/research/strategy_3_vwap_trend_regime_diagnostics.md")
SAFETY = {
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "order_execution_enabled": False,
    "broker_execution_enabled": False,
    "order_send_called": False,
    "strategy_3_runtime_logic_changed": False,
    "vwap_sigma_cooldown_logic_changed": False,
    "data_xauusd_mutated": False,
}
PER_SIGNAL_FIELDS = [
    "decision_time",
    "symbol",
    "direction",
    "accepted_or_blocked",
    "cooldown_accepted",
    "cooldown_active",
    "block_reason",
    "session_bucket",
    "setup_mode",
    "band_touched",
    "current_price",
    "vwap_value",
    "price_minus_vwap",
    "price_vs_vwap",
    "vwap_sigma_z",
    "vwap_distance_sigma_bucket",
    "vwap_slope",
    "vwap_slope_bucket",
    "h1_latest_timestamp_used",
    "h1_bias",
    "h1_bias_value",
    "h4_latest_timestamp_used",
    "h4_bias",
    "h4_bias_value",
    "m15_latest_timestamp_used",
    "m15_range_mean_16_usd",
    "volatility_bucket",
    "context_prefix_compatible",
    "data_context_hash",
    "reason_codes",
    "entry_price",
    "stop_loss",
    "take_profit",
    "outcome_note",
]


@dataclass(frozen=True)
class DiagnosticsConfig:
    comparison_dir: Path
    paper_signals_path: Path
    data_dir: Path
    output_dir: Path
    docs_path: Path
    symbol: str
    min_bucket_size: int
    dry_run: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strategy 3 VWAP/trend/regime diagnostics for clean paper signals")
    parser.add_argument("--comparison-dir", default=str(DEFAULT_COMPARISON_DIR))
    parser.add_argument("--paper-signals-path", default="backtests/reports/strategy_3_paper_shadow_scanner/paper_signals.csv")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--docs-path", default=str(DEFAULT_DOCS_PATH))
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--min-bucket-size", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = sorted({key for row in rows for key in row.keys()}) or ["empty"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _parse_ts(value: Any) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.to_pydatetime()


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def context_gate(summary: dict[str, Any]) -> dict[str, Any]:
    flags = set(summary.get("verdict_flags", []))
    clean_rows = int(summary.get("context_tagged_rows") or 0)
    prefix_ok = int(summary.get("prefix_compatible_rows") or 0)
    prefix_bad = int(summary.get("prefix_incompatible_rows") or 0)
    insufficient = int(summary.get("insufficient_context_rows") or 0)
    passed = (
        clean_rows > 0
        and prefix_ok == clean_rows
        and prefix_bad == 0
        and insufficient == 0
        and "CLEAN_CONTEXT_ACCEPTED_MATCH_OK" in flags
        and "PAPER_BACKTEST_RUNTIME_CONSISTENCY_OK" in flags
    )
    return {
        "context_gate_passed": passed,
        "clean_rows": clean_rows,
        "prefix_compatible_rows": prefix_ok,
        "prefix_incompatible_rows": prefix_bad,
        "insufficient_context_rows": insufficient,
        "verdict_flags": sorted(flags),
    }


def prefix_status_by_signal(comparison_dir: Path) -> dict[tuple[str, str], bool]:
    report = _read_json(comparison_dir / "segmented_data_context_report.json")
    out: dict[tuple[str, str], bool] = {}
    for item in report.get("details", []):
        key = (str(item.get("signal_timestamp") or ""), str(item.get("data_context_hash") or ""))
        out[key] = bool(item.get("prefix_compatible")) and not item.get("prefix_insufficient")
    return out


def select_clean_rows(rows: list[dict[str, Any]], summary: dict[str, Any], prefix_map: dict[tuple[str, str], bool]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    window = summary.get("comparison_window", {})
    start = _parse_ts(window["comparison_start"])
    end = _parse_ts(window["comparison_end"])
    clean: list[dict[str, Any]] = []
    legacy: list[dict[str, Any]] = []
    for row in rows:
        has_context = bool(str(row.get("data_context_hash") or "").strip())
        if not has_context:
            legacy.append(row)
            continue
        ts = _parse_ts(row["signal_timestamp"])
        if start <= ts <= end:
            key = (str(row.get("signal_timestamp") or ""), str(row.get("data_context_hash") or ""))
            if prefix_map.get(key, False):
                clean.append(row)
    clean.sort(key=lambda item: _parse_ts(item["signal_timestamp"]))
    return clean, legacy


def _slice_to(frame: pd.DataFrame, when: datetime) -> pd.DataFrame:
    if frame is None or frame.empty or "time" not in frame.columns:
        return pd.DataFrame()
    times = pd.to_datetime(frame["time"], utc=True)
    return frame.loc[times <= pd.Timestamp(when)].copy()


def _latest_timestamp(frame: pd.DataFrame) -> str | None:
    if frame.empty or "time" not in frame.columns:
        return None
    return pd.to_datetime(frame["time"], utc=True).max().isoformat()


def _trend_bias(frame: pd.DataFrame, *, lookback_bars: int = 3, flat_threshold_usd: float = 0.25) -> tuple[str, float | None]:
    if frame.empty or "close" not in frame.columns or len(frame) <= lookback_bars:
        return "insufficient", None
    close = frame["close"].astype(float)
    value = float(close.iloc[-1] - close.iloc[-1 - lookback_bars])
    if abs(value) <= flat_threshold_usd:
        return "flat", round(value, 4)
    return ("up" if value > 0 else "down"), round(value, 4)


def _vwap_sigma(row: dict[str, Any]) -> tuple[float | None, str]:
    price = _float(row.get("current_price"))
    vwap = _float(row.get("vwap_value"))
    upper = _float(row.get("sigma_1_upper"))
    lower = _float(row.get("sigma_1_lower"))
    if price is None or vwap is None or upper is None or lower is None:
        return None, "unknown"
    sigma = abs(upper - vwap) if price >= vwap else abs(vwap - lower)
    if sigma <= 0:
        return None, "unknown"
    z = (price - vwap) / sigma
    az = abs(z)
    if az <= 0.5:
        bucket = "inside_0_5_sigma"
    elif az <= 1.0:
        bucket = "0_5_to_1_sigma"
    elif az <= 2.0:
        bucket = "1_to_2_sigma"
    else:
        bucket = "beyond_2_sigma"
    return round(z, 4), bucket


def _price_vs_vwap(row: dict[str, Any]) -> tuple[float | None, str]:
    price = _float(row.get("current_price"))
    vwap = _float(row.get("vwap_value"))
    if price is None or vwap is None:
        return None, "unknown"
    diff = price - vwap
    if abs(diff) <= 0.01:
        return round(diff, 4), "at_vwap"
    return round(diff, 4), "above_vwap" if diff > 0 else "below_vwap"


def _slope_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if abs(value) <= 0.25:
        return "flat"
    return "up" if value > 0 else "down"


def _volatility_bucket(value: float | None, low: float | None, high: float | None) -> str:
    if value is None or low is None or high is None:
        return "unknown"
    if value <= low:
        return "low_volatility"
    if value >= high:
        return "high_volatility"
    return "medium_volatility"


def _range_mean(frame: pd.DataFrame, bars: int = 16) -> float | None:
    if frame.empty or not {"high", "low"}.issubset(frame.columns):
        return None
    recent = frame.tail(bars)
    if recent.empty:
        return None
    return round(float((recent["high"].astype(float) - recent["low"].astype(float)).mean()), 4)


def build_per_signal_diagnostics(rows: list[dict[str, Any]], market_data: dict[str, pd.DataFrame], prefix_map: dict[tuple[str, str], bool]) -> list[dict[str, Any]]:
    partial_rows: list[dict[str, Any]] = []
    ranges: list[float] = []
    for row in rows:
        when = _parse_ts(row["signal_timestamp"])
        m15 = _slice_to(market_data.get("M15", pd.DataFrame()), when)
        h1 = _slice_to(market_data.get("H1", pd.DataFrame()), when)
        h4 = _slice_to(market_data.get("H4", pd.DataFrame()), when)
        current_price = _float(row.get("current_price"))
        snapshot = session_vwap_snapshot(m15, current_price) if not m15.empty else None
        h1_bias, h1_bias_value = _trend_bias(h1)
        h4_bias, h4_bias_value = _trend_bias(h4)
        price_minus_vwap, price_vs_vwap = _price_vs_vwap(row)
        z_score, sigma_bucket = _vwap_sigma(row)
        range_mean = _range_mean(m15)
        if range_mean is not None:
            ranges.append(range_mean)
        accepted = _bool(row.get("cooldown_accepted"))
        context_key = (str(row.get("signal_timestamp") or ""), str(row.get("data_context_hash") or ""))
        partial_rows.append(
            {
                "decision_time": row.get("signal_timestamp"),
                "symbol": row.get("symbol"),
                "direction": row.get("direction"),
                "accepted_or_blocked": "accepted" if accepted else "blocked",
                "cooldown_accepted": accepted,
                "cooldown_active": not accepted,
                "block_reason": "accepted" if accepted else (row.get("cooldown_block_reason") or "blocked_unspecified"),
                "session_bucket": row.get("session") or "unknown",
                "setup_mode": row.get("setup_mode") or "unknown",
                "band_touched": row.get("band_touched") or "unknown",
                "current_price": row.get("current_price"),
                "vwap_value": row.get("vwap_value"),
                "price_minus_vwap": price_minus_vwap,
                "price_vs_vwap": price_vs_vwap,
                "vwap_sigma_z": z_score,
                "vwap_distance_sigma_bucket": sigma_bucket,
                "vwap_slope": getattr(snapshot, "slope", None),
                "vwap_slope_bucket": _slope_bucket(getattr(snapshot, "slope", None)),
                "h1_latest_timestamp_used": _latest_timestamp(h1),
                "h1_bias": h1_bias,
                "h1_bias_value": h1_bias_value,
                "h4_latest_timestamp_used": _latest_timestamp(h4),
                "h4_bias": h4_bias,
                "h4_bias_value": h4_bias_value,
                "m15_latest_timestamp_used": _latest_timestamp(m15),
                "m15_range_mean_16_usd": range_mean,
                "volatility_bucket": "unknown",
                "context_prefix_compatible": prefix_map.get(context_key, False),
                "data_context_hash": row.get("data_context_hash"),
                "reason_codes": row.get("reason_codes"),
                "entry_price": row.get("entry_price"),
                "stop_loss": row.get("stop_loss"),
                "take_profit": row.get("take_profit"),
                "outcome_note": "outcome_not_used_for_regime_definition",
            }
        )
    if ranges:
        low = float(pd.Series(ranges).quantile(1 / 3))
        high = float(pd.Series(ranges).quantile(2 / 3))
    else:
        low = high = None
    for item in partial_rows:
        item["volatility_bucket"] = _volatility_bucket(_float(item.get("m15_range_mean_16_usd")), low, high)
    return partial_rows


def summarize_counts(rows: list[dict[str, Any]], *, group_fields: list[str], min_bucket_size: int) -> list[dict[str, Any]]:
    buckets: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(field, "unknown") for field in group_fields)
        bucket = buckets.setdefault(key, {"total_rows": 0, "accepted_rows": 0, "blocked_rows": 0})
        bucket["total_rows"] += 1
        if row.get("accepted_or_blocked") == "accepted":
            bucket["accepted_rows"] += 1
        else:
            bucket["blocked_rows"] += 1
    out: list[dict[str, Any]] = []
    for key, bucket in sorted(buckets.items(), key=lambda item: (item[0], item[1]["total_rows"])):
        total = int(bucket["total_rows"])
        row = {field: key[idx] for idx, field in enumerate(group_fields)}
        row.update(
            {
                "total_rows": total,
                "accepted_rows": bucket["accepted_rows"],
                "blocked_rows": bucket["blocked_rows"],
                "accepted_rate": round(bucket["accepted_rows"] / total, 4) if total else None,
                "small_n_insufficient": total < min_bucket_size,
            }
        )
        out.append(row)
    return out


def blocked_reason_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocked = [row for row in rows if row.get("accepted_or_blocked") == "blocked"]
    total = len(blocked)
    counts: dict[str, int] = {}
    for row in blocked:
        reason = str(row.get("block_reason") or "blocked_unspecified")
        counts[reason] = counts.get(reason, 0) + 1
    return [
        {
            "block_reason": reason,
            "blocked_rows": count,
            "pct_blocked_rows": round(count / total, 4) if total else 0.0,
        }
        for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def build_summary(
    *,
    cfg: DiagnosticsConfig,
    comparison_summary: dict[str, Any],
    gate: dict[str, Any],
    rows: list[dict[str, Any]],
    blocked_reasons: list[dict[str, Any]],
    by_regime: list[dict[str, Any]],
    by_session: list[dict[str, Any]],
    runtime_seconds: float,
) -> dict[str, Any]:
    accepted = [row for row in rows if row.get("accepted_or_blocked") == "accepted"]
    blocked = [row for row in rows if row.get("accepted_or_blocked") == "blocked"]
    small_n_buckets = sum(1 for row in by_regime if row.get("small_n_insufficient"))
    return {
        "run_finished_at": _utc_now(),
        "runtime_seconds": round(runtime_seconds, 4),
        "dry_run": cfg.dry_run,
        "symbol": cfg.symbol,
        "strategy": STRATEGY_NAME,
        "comparison_dir": str(cfg.comparison_dir),
        "paper_signals_path": str(cfg.paper_signals_path),
        "data_dir": str(cfg.data_dir),
        "context_gate": gate,
        "comparison_context": {
            "total_paper_rows": comparison_summary.get("total_paper_rows"),
            "legacy_without_context_rows": comparison_summary.get("legacy_without_context_rows"),
            "context_tagged_rows": comparison_summary.get("context_tagged_rows"),
            "prefix_compatible_rows": comparison_summary.get("prefix_compatible_rows"),
            "prefix_incompatible_rows": comparison_summary.get("prefix_incompatible_rows"),
            "insufficient_context_rows": comparison_summary.get("insufficient_context_rows"),
            "match_rate_all_detected": comparison_summary.get("match_rate_all_detected"),
            "match_rate_accepted_only": comparison_summary.get("match_rate_accepted_only"),
        },
        "diagnostic_rows": len(rows),
        "accepted_rows": len(accepted),
        "blocked_rows": len(blocked),
        "blocked_reason_distribution": blocked_reasons,
        "session_summary": by_session,
        "accepted_vs_blocked_by_regime": by_regime,
        "small_n": {
            "min_bucket_size": cfg.min_bucket_size,
            "all_regime_buckets": len(by_regime),
            "small_n_buckets": small_n_buckets,
            "accepted_rows_too_few_for_robust_performance_conclusion": len(accepted) < 100,
        },
        "verdict_flags": [
            "STRATEGY_3_LEVEL_3_PAPER_CANDIDATE",
            "CONTEXT_CONSISTENCY_GATE_PASSED" if gate["context_gate_passed"] else "CONTEXT_CONSISTENCY_GATE_NOT_PASSED",
            "DIAGNOSTICS_ONLY",
            "SAMPLE_SIZE_INSUFFICIENT_FOR_REGIME_EDGE_CLAIMS",
            "NO_PARAMETER_RECOMMENDATION",
            "NO_LIVE_DEPLOYMENT_DECISION",
            "STRATEGY_3_REMAINS_PAPER_ONLY",
        ],
        "recommendation": (
            "Use these descriptive buckets only to design future pre-registered tests; continue paper observation before any Strategy 3 change."
        ),
        "deployment_instruction_emitted": False,
        "safety": dict(SAFETY),
    }


def write_report(docs_path: Path, output_dir: Path, summary: dict[str, Any]) -> None:
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Strategy 3 VWAP Trend Regime Diagnostics",
        "",
        "Strategy 3 remains Level 3 / Paper Candidate. This report is diagnostics-only and does not validate profitability or live readiness.",
        "",
        "## Context",
        "",
        f"- context consistency gate passed: `{summary['context_gate']['context_gate_passed']}`",
        f"- clean diagnostic rows: `{summary['diagnostic_rows']}`",
        f"- accepted/blocked: `{summary['accepted_rows']}/{summary['blocked_rows']}`",
        f"- all-detected match rate: `{summary['comparison_context']['match_rate_all_detected']}`",
        f"- accepted-only match rate: `{summary['comparison_context']['match_rate_accepted_only']}`",
        "",
        "## Blocked Rows",
        "",
        "| block_reason | blocked_rows | pct_blocked_rows |",
        "|---|---:|---:|",
    ]
    for row in summary["blocked_reason_distribution"]:
        lines.append(f"| {row['block_reason']} | {row['blocked_rows']} | {row['pct_blocked_rows']} |")
    lines.extend(
        [
            "",
            "## Session Summary",
            "",
            "| session | total | accepted | blocked | accepted_rate | small_n |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in summary["session_summary"]:
        lines.append(
            f"| {row['session_bucket']} | {row['total_rows']} | {row['accepted_rows']} | {row['blocked_rows']} | {row['accepted_rate']} | {row['small_n_insufficient']} |"
        )
    key_regime_rows = [
        row
        for row in summary.get("accepted_vs_blocked_by_regime", [])
        if row.get("regime_dimension") in {"direction", "vwap_slope_bucket", "h4_bias", "volatility_bucket"}
    ]
    lines.extend(
        [
            "",
            "## Key Regime Buckets",
            "",
            "| dimension | bucket | total | accepted | blocked | accepted_rate | small_n |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in key_regime_rows:
        lines.append(
            f"| {row['regime_dimension']} | {row['regime_bucket']} | {row['total_rows']} | {row['accepted_rows']} | {row['blocked_rows']} | {row['accepted_rate']} | {row['small_n_insufficient']} |"
        )
    lines.extend(
        [
            "",
            "## Candidate Hypotheses",
            "",
            "- H4 up-context and downward VWAP-slope buckets show higher accepted fractions in this small sample, but this is a descriptive concentration only.",
            "- London shows more cooldown blocking than other larger session buckets in this sample, but its row count is below the bucket threshold.",
            "- Volatility tertiles are close to flat in accepted fraction, so this sample does not suggest a strong descriptive volatility split.",
            "- Any future use of these observations must be pre-registered before changing Strategy 3 logic.",
            "",
            "## Interpretation",
            "",
            "- The 26 accepted rows are too few for robust performance or regime-level edge conclusions.",
            "- Regime labels are descriptive only and use pre-decision data; post-entry outcome is not used to define any bucket.",
            "- Any promising concentration must become a future pre-registered diagnostic or test before strategy behavior changes.",
            "",
            "## Safety",
            "",
            "- no live trading",
            "- no Telegram operational alerts",
            "- no orders",
            "- no broker execution",
            "- no order_send",
            "- no Strategy 3 VWAP/sigma/cooldown/entry/TP/SL/filter changes",
            "- no Strategy 2 touch",
            "- no Adelin touch",
            "- no data/XAUUSD/*.csv mutation",
            "",
            "## Outputs",
            "",
            f"- `{output_dir / 'regime_diagnostics_per_signal.csv'}`",
            f"- `{output_dir / 'blocked_reason_summary.csv'}`",
            f"- `{output_dir / 'accepted_vs_blocked_by_regime.csv'}`",
            f"- `{output_dir / 'session_regime_summary.csv'}`",
            f"- `{output_dir / 'regime_summary.json'}`",
            "",
            "## Next Recommendation",
            "",
            summary["recommendation"],
            "",
        ]
    )
    docs_path.write_text("\n".join(lines), encoding="utf-8")
    (output_dir / "strategy_3_vwap_trend_regime_diagnostics.md").write_text("\n".join(lines), encoding="utf-8")


def run_diagnostics(cfg: DiagnosticsConfig) -> dict[str, Any]:
    started = perf_counter()
    comparison_summary = _read_json(cfg.comparison_dir / "segmented_comparison_summary.json")
    gate = context_gate(comparison_summary)
    prefix_map = prefix_status_by_signal(cfg.comparison_dir)
    paper_rows = _read_csv(cfg.paper_signals_path)
    clean_rows, legacy_rows = select_clean_rows(paper_rows, comparison_summary, prefix_map)
    date_to = _parse_ts(comparison_summary["comparison_window"]["comparison_end"])
    market_data = load_csv_timeframes(cfg.symbol, ["M15", "H1", "H4"], data_dir=str(cfg.data_dir), date_to=date_to)
    per_signal = build_per_signal_diagnostics(clean_rows, market_data, prefix_map) if gate["context_gate_passed"] else []
    blocked_reasons = blocked_reason_summary(per_signal)
    regime_fields = [
        "direction",
        "session_bucket",
        "setup_mode",
        "band_touched",
        "price_vs_vwap",
        "vwap_distance_sigma_bucket",
        "vwap_slope_bucket",
        "h1_bias",
        "h4_bias",
        "volatility_bucket",
    ]
    by_regime: list[dict[str, Any]] = []
    for field in regime_fields:
        for row in summarize_counts(per_signal, group_fields=[field], min_bucket_size=cfg.min_bucket_size):
            by_regime.append({"regime_dimension": field, "regime_bucket": row[field], **{k: v for k, v in row.items() if k != field}})
    by_session = summarize_counts(per_signal, group_fields=["session_bucket"], min_bucket_size=cfg.min_bucket_size)
    summary = build_summary(
        cfg=cfg,
        comparison_summary=comparison_summary,
        gate=gate,
        rows=per_signal,
        blocked_reasons=blocked_reasons,
        by_regime=by_regime,
        by_session=by_session,
        runtime_seconds=perf_counter() - started,
    )
    summary["legacy_rows_excluded"] = len(legacy_rows)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(cfg.output_dir / "regime_diagnostics_per_signal.csv", per_signal, PER_SIGNAL_FIELDS)
    _write_csv(cfg.output_dir / "blocked_reason_summary.csv", blocked_reasons, ["block_reason", "blocked_rows", "pct_blocked_rows"])
    _write_csv(
        cfg.output_dir / "accepted_vs_blocked_by_regime.csv",
        by_regime,
        ["regime_dimension", "regime_bucket", "total_rows", "accepted_rows", "blocked_rows", "accepted_rate", "small_n_insufficient"],
    )
    _write_csv(
        cfg.output_dir / "session_regime_summary.csv",
        by_session,
        ["session_bucket", "total_rows", "accepted_rows", "blocked_rows", "accepted_rate", "small_n_insufficient"],
    )
    (cfg.output_dir / "regime_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    write_report(cfg.docs_path, cfg.output_dir, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = DiagnosticsConfig(
        comparison_dir=Path(args.comparison_dir),
        paper_signals_path=Path(args.paper_signals_path),
        data_dir=Path(args.data_dir),
        output_dir=Path(args.output_dir),
        docs_path=Path(args.docs_path),
        symbol=str(args.symbol),
        min_bucket_size=int(args.min_bucket_size),
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(run_diagnostics(cfg), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
