from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_human_trade_alignment import (
    DEFAULT_CONFIG,
    build_human_trade_alignment_pack,
    write_human_trade_alignment_outputs,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Strategy 2 human-trade alignment pack.")
    parser.add_argument(
        "--bot-source",
        default="backtests/reports/strategy_2_layer_b_reaction_quality/layer_b_reaction_features_per_sample.csv",
        help="Pre-generated Strategy 2 Layer B source CSV. This script does not rerun Layer B.",
    )
    parser.add_argument(
        "--human-trades",
        default="backtests/reports/strategy_2_human_trade_alignment/human_trades_template.csv",
        help="Human trades CSV. If missing or empty, only template/config/README/summary are generated.",
    )
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_human_trade_alignment")
    parser.add_argument("--symbol", default=DEFAULT_CONFIG["symbol"])
    parser.add_argument("--max-signal-lead-minutes", type=float, default=DEFAULT_CONFIG["max_signal_lead_minutes"])
    parser.add_argument("--max-signal-lag-minutes", type=float, default=DEFAULT_CONFIG["max_signal_lag_minutes"])
    parser.add_argument("--near-entry-minutes", type=float, default=DEFAULT_CONFIG["near_entry_minutes"])
    parser.add_argument("--max-entry-price-distance-usd", type=float, default=DEFAULT_CONFIG["max_entry_price_distance_usd"])
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    config = {
        **DEFAULT_CONFIG,
        "symbol": args.symbol,
        "max_signal_lead_minutes": args.max_signal_lead_minutes,
        "max_signal_lag_minutes": args.max_signal_lag_minutes,
        "near_entry_minutes": args.near_entry_minutes,
        "max_entry_price_distance_usd": args.max_entry_price_distance_usd,
    }
    result = build_human_trade_alignment_pack(
        args.bot_source,
        human_trades_path=args.human_trades,
        output_dir=args.output_dir,
        config=config,
    )
    paths = write_human_trade_alignment_outputs(result, args.output_dir)
    return {
        "dry_run": bool(args.dry_run),
        "bot_source": str(Path(args.bot_source)),
        "human_trades": str(Path(args.human_trades)),
        "output_dir": str(Path(args.output_dir)),
        "real_human_trades_provided": result.summary["real_human_trades_provided"],
        "status": result.summary.get("status", "REAL_HUMAN_TRADES_ANALYZED"),
        "bot_candidates_loaded": result.summary["bot_candidates_loaded"],
        "alignment_metrics_generated": result.summary["alignment_metrics_generated"],
        "paths": paths,
        "safety": result.summary["safety"],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(json.dumps(run(args), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
