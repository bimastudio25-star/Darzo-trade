from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_fully_invalidated_state_split import (
    build_fully_invalidated_state_split,
    write_state_split_outputs,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split Strategy 2 overloaded FULLY_INVALIDATED taxonomy.")
    parser.add_argument("--input-dir", default="backtests/reports/strategy_2_invalidation_state_machine")
    parser.add_argument("--audit-dir", default="backtests/reports/strategy_2_invalidation_rate_audit")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_fully_invalidated_state_split")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_fully_invalidated_state_split.md")
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    result = build_fully_invalidated_state_split(args.input_dir, args.audit_dir)
    paths = write_state_split_outputs(result, args.output_dir, docs_path=args.docs_path)
    return {
        "dry_run": bool(args.dry_run),
        "runtime_seconds": result.summary["runtime_seconds"],
        "samples_processed": result.summary["total_samples"],
        "old_fully_invalidated_count": result.summary["old_fully_invalidated_count"],
        "true_dual_direction_invalidated_count": result.summary["true_dual_direction_invalidated_count"],
        "h1_context_already_consumed_count": result.summary["h1_context_already_consumed_count"],
        "mae_not_reached_count": result.summary["mae_not_reached_count"],
        "structure_invalid_count": result.summary["structure_invalid_count"],
        "unknown_invalidation_state_count": result.summary["unknown_invalidation_state_count"],
        "sticky_violations": result.summary["sticky_violations"],
        "cross_h1_contamination_flags": result.summary["cross_h1_contamination_flags"],
        "direction_violations": result.summary["direction_violations"],
        "critical_conclusion": result.summary["critical_conclusion"],
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
