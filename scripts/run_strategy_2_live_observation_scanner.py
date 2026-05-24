from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_live_observation_scanner import (
    DEFAULT_OUTPUT_DIR,
    parse_max_bars,
    result_to_dict,
    run_live_observation_scanner,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Strategy 2 XAUUSD live observation scanner in output-only mode."
    )
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--heartbeat-only", action="store_true")
    parser.add_argument("--max-bars", default="M1=2000,M5=1000,M15=500,H1=300")
    parser.add_argument("--closed-candle-only", action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_live_observation_scanner(
            symbol=args.symbol,
            output_dir=args.output_dir,
            max_bars=parse_max_bars(args.max_bars),
            closed_candle_only=bool(args.closed_candle_only),
            heartbeat_only=bool(args.heartbeat_only),
            dry_run=bool(args.dry_run),
        )
    except Exception as exc:
        print(json.dumps({"scanner_status": "ERROR", "error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result_to_dict(result), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
