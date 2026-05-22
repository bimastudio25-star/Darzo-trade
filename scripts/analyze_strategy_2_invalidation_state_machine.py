from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_invalidation_state_machine import build_invalidation_state_machine, write_state_machine_outputs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strategy 2 research-only hard invalidation state machine.")
    parser.add_argument("--input", default="backtests/reports/strategy_2_rulebook_v0_labeling/rulebook_v0_per_sample.csv")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_invalidation_state_machine")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_invalidation_state_machine.md")
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    result = build_invalidation_state_machine(args.input)
    paths = write_state_machine_outputs(result, args.output_dir, docs_path=args.docs_path)
    return {
        "dry_run": bool(args.dry_run),
        "runtime_seconds": result.summary["runtime_seconds"],
        "samples_processed": result.summary["samples_processed"],
        "valid_long_count": result.summary["valid_long_count"],
        "valid_short_count": result.summary["valid_short_count"],
        "invalidated_long_count": result.summary["invalidated_long_count"],
        "invalidated_short_count": result.summary["invalidated_short_count"],
        "fully_invalidated_count": result.summary["fully_invalidated_count"],
        "reactivation_blocked_count": result.summary["reactivation_blocked_count"],
        "sticky_invalidation_confirmed": result.summary["sticky_invalidation_confirmed"],
        "verdict_flags": result.summary["verdict_flags"],
        "safety": result.summary["safety"],
        "paths": paths,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(json.dumps(run(args), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
