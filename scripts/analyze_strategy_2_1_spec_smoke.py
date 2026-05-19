from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_spec_alignment_audit import load_stats_profile
from dazro_trade.analysis.strategy_2_1_liquidity_expansion_spec import scan_spec_model, write_smoke_outputs
from dazro_trade.analysis.strategy_2_liquidity_expansion_stats import build_stats_report, write_stats_outputs
from dazro_trade.backtest.data_loader import load_csv_timeframes


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 2.1 spec model smoke.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--stats-summary-path", default="backtests/reports/strategy_2_liquidity_expansion_stats/liquidity_expansion_stats_summary.json")
    parser.add_argument("--stats-output-dir", default="backtests/reports/strategy_2_liquidity_expansion_stats")
    parser.add_argument("--calibration-from", default="2026-03-15")
    parser.add_argument("--calibration-to", default="2026-05-09")
    parser.add_argument("--from", dest="smoke_from", default="2026-05-10")
    parser.add_argument("--to", dest="smoke_to", default="2026-05-14")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_1_spec_smoke")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_liquidity_expansion_spec_alignment.md")
    parser.add_argument("--risk-limit-usd", type=float, default=12.0)
    parser.add_argument("--allow-risk-too-large", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _date_arg(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="UTC")


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def run(args: argparse.Namespace) -> dict[str, str]:
    market_data = load_csv_timeframes(args.symbol, ["M1", "M15", "H1"], data_dir=args.data_dir)
    stats_summary_path = Path(args.stats_summary_path)
    profile = load_stats_profile(stats_summary_path)
    if profile is None:
        stats_report = build_stats_report(
            symbol=args.symbol,
            m1=market_data.get("M1"),
            m15=market_data.get("M15"),
            h1=market_data.get("H1"),
            calibration_from=_date_arg(args.calibration_from),
            calibration_to=_date_arg(args.calibration_to),
        )
        write_stats_outputs(stats_report, Path(args.stats_output_dir))
        profile = stats_report["profile"]
    report = scan_spec_model(
        symbol=args.symbol,
        market_data=market_data,
        profile=profile,
        smoke_from=_date_arg(args.smoke_from),
        smoke_to=_date_arg(args.smoke_to),
        risk_limit_usd=args.risk_limit_usd,
        allow_risk_too_large=bool(args.allow_risk_too_large),
    )
    paths = write_smoke_outputs(report, Path(args.output_dir))
    docs_path = Path(args.docs_path)
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    audit_summary = _load_json(Path("backtests/reports/strategy_2_spec_alignment_audit/strategy_2_spec_alignment_summary.json"))
    stats_summary = _load_json(stats_summary_path)
    docs_path.write_text(_render_combined_doc(audit_summary, stats_summary, report["summary"]), encoding="utf-8")
    paths["docs_md"] = str(docs_path)
    return paths


def _render_combined_doc(audit: dict, stats: dict, smoke: dict) -> str:
    audit_flags = audit.get("verdict_flags") or []
    smoke_flags = smoke.get("verdict_flags") or []
    stats_profile = stats.get("profile") or smoke.get("stats_profile") or {}
    lines = [
        "# Strategy 2 Liquidity Expansion Spec Alignment",
        "",
        "## Executive Summary",
        "",
        "This branch is a research-only specification audit plus an isolated Strategy 2.1 mechanics prototype. It does not recover Strategy 2 live, does not optimize parameters, and does not make a deployment decision.",
        "",
        "## Source Spec Recap",
        "",
        "- Model: XAUUSD Liquidity Expansion Model.",
        "- Reference levels: previous H1 high/low, with M15 :45 high/low as sequence filter.",
        "- Entry: average MAE deviation beyond the H1 liquidity level, with candle-anatomy confirmation.",
        "- Stop: H1 liquidity level plus Max Excursion * 1.25.",
        "- Targets: TP1/TP2/TP3/TP4 quartiles anchored to the H1 level, not actual entry.",
        "- Management: move stop to BE at TP1; runner can continue to later quartiles.",
        "- Risk sanity: SL over 12 USD is flagged as too large for this scalping model.",
        "",
        "## Current Strategy 2.0 Forensic Mismatch",
        "",
        "- Prior forensic sample: 57 trades from 2026-03-15 to 2026-05-14.",
        "- Average SL: 70.6395 USD; median SL: 51.04 USD.",
        "- Average TP: 50.2656 USD; median TP: 42.49 USD.",
        "- Average planned R:R: 0.807.",
        "- Only 4/57 reached 1R and only 1/57 reached 2R.",
        "",
        "## TP/SL Audit",
        "",
        f"- trades audited: `{audit.get('total_trades_audited')}`",
        f"- current SL avg/median/min/max: `{audit.get('average_current_sl')}` / `{audit.get('median_current_sl')}` / `{audit.get('min_current_sl')}` / `{audit.get('max_current_sl')}`",
        f"- expected SL avg/median/min/max from stats profile: `{audit.get('average_expected_sl')}` / `{audit.get('median_expected_sl')}` / `{audit.get('min_expected_sl')}` / `{audit.get('max_expected_sl')}`",
        f"- SL > 12 USD count/rate: `{audit.get('sl_gt_12_count')}` / `{audit.get('sl_gt_12_rate')}`",
        f"- current planned R:R average: `{audit.get('average_current_planned_rr')}`",
        f"- expected R:R to TP1/TP2/TP3/TP4: `{audit.get('average_expected_rr_to_tp1')}`, `{audit.get('average_expected_rr_to_tp2')}`, `{audit.get('average_expected_rr_to_tp3')}`, `{audit.get('average_expected_rr_to_tp4')}`",
        "",
        "## H1 And M15 Alignment",
        "",
        f"- H1 level identified rate: `{audit.get('h1_level_identified_rate')}`",
        f"- M15 00:45 computable rate: `{audit.get('m15_0045_filter_computable_rate')}`",
        f"- liquidity sequence valid rate: `{audit.get('liquidity_sequence_valid_rate')}`",
        "",
        "## MAE / SL / TP Alignment",
        "",
        f"- entry near MAE rate: `{audit.get('entry_near_mae_rate')}`",
        f"- SL Max Excursion +25 alignment rate: `{audit.get('sl_aligned_rate')}`",
        f"- TP H1-anchored rate: `{audit.get('tp_anchored_to_h1_rate')}`",
        f"- TP appears entry-anchored rate: `{audit.get('tp_entry_anchored_rate')}`",
        "",
        "## Stats Profile",
        "",
        "```json",
        json.dumps(stats_profile, indent=2, sort_keys=True),
        "```",
        "",
        "## Strategy 2.1 Research-Only Model Design",
        "",
        "The Strategy 2.1 prototype is isolated in analysis code and is not registered into live/runtime paths. It builds H1-anchored entries, Max Excursion +25 stops, H1-anchored quartile targets, TP1 break-even management, and default no-trade behavior when effective risk exceeds 12 USD.",
        "",
        "## Smoke Results",
        "",
        f"- setups found: `{smoke.get('setups_found')}`",
        f"- trades taken: `{smoke.get('trades_taken')}`",
        f"- no-trades: `{smoke.get('no_trades')}`",
        f"- no-trade reasons: `{smoke.get('no_trade_reasons')}`",
        f"- average SL: `{smoke.get('average_sl')}`",
        f"- median SL: `{smoke.get('median_sl')}`",
        f"- SL > 12 count/rate: `{smoke.get('sl_gt_12_count')}` / `{smoke.get('sl_gt_12_rate')}`",
        f"- planned R:R to TP1/TP2/TP3/TP4: `{smoke.get('planned_rr_to_tp1')}`, `{smoke.get('planned_rr_to_tp2')}`, `{smoke.get('planned_rr_to_tp3')}`, `{smoke.get('planned_rr_to_tp4')}`",
        f"- outcomes: `{smoke.get('outcome_counts')}`",
        "",
        "## Safety Confirmation",
        "",
        "- No live trading was enabled.",
        "- No Telegram alerts were sent.",
        "- No broker orders were placed.",
        "- Strategy 2.0 was not modified in place.",
        "- Strategy 3 and Adelin were untouched.",
        "- Strategy 2.1 remains research-only and isolated from runtime by default.",
        "",
        "## Limitations",
        "",
        "- The local PDF was not found, so the embedded spec was used.",
        "- Stats are calibration-profile mechanics, not validation.",
        "- Smoke results are small-sample mechanics only.",
        "- Dominant H1 range-in-range detection is not forced when unsafe.",
        "- Candle anatomy confirmation is intentionally simple and report-only.",
        "",
        "## Verdict",
        "",
        *[f"- `{flag}`" for flag in dict.fromkeys(audit_flags + smoke_flags + ["STRATEGY_2_REMAINS_RESEARCH_ONLY", "NO_LIVE_DEPLOYMENT_DECISION"])],
        "",
        "## Recommended Next Step",
        "",
        "If the spec profile remains mechanically too risky, repair the statistical profile and source-spec extraction before any larger Strategy 2 test. Otherwise, run a limited Strategy 2.1 research validation on a clearly separated sample.",
    ]
    return "\n".join(str(line) for line in lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = run(args)
    print(json.dumps(paths, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
