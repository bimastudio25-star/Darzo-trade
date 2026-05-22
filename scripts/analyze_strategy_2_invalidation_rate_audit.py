from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_invalidation_rate_audit import build_invalidation_rate_audit, write_invalidation_rate_outputs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Strategy 2 hard invalidation rate.")
    parser.add_argument("--input-dir", default="backtests/reports/strategy_2_invalidation_state_machine")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_invalidation_rate_audit")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_invalidation_rate_audit.md")
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    result = build_invalidation_rate_audit(args.input_dir)
    paths = write_invalidation_rate_outputs(result, args.output_dir, docs_path=args.docs_path)
    return {
        "dry_run": bool(args.dry_run),
        "runtime_seconds": result.summary["runtime_seconds"],
        "samples_processed": result.summary["samples_processed"],
        "valid_rate": result.summary["valid_rate"],
        "invalidation_rate": result.summary["invalidation_rate"],
        "fully_invalidated_rate": result.summary["fully_invalidated_rate"],
        "sticky_invalidation_confirmed": result.summary["sticky_invalidation_confirmed"],
        "h1_context_reset_confirmed": result.summary["h1_context_reset_confirmed"],
        "critical_assessment": result.summary["critical_assessment"],
        "directionality": result.summary["directionality"],
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
