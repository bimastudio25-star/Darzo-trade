from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_live_observation_scanner import diagnose_mt5_feed, parse_max_bars


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose Strategy 2 read-only MT5 feed freshness.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--max-bars", default="M1=2000,M5=1000,M15=500,H1=300")
    parser.add_argument("--mt5-terminal-path", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = diagnose_mt5_feed(
            symbol=args.symbol,
            max_bars=parse_max_bars(args.max_bars),
            mt5_terminal_path=args.mt5_terminal_path,
        )
    except Exception as exc:
        print(json.dumps({"diagnostic_status": "ERROR", "error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
