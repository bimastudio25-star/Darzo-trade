from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_rulebook_v0_labeling import build_rulebook_v0_labeling, write_rulebook_v0_outputs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 2 rulebook v0 labeling.")
    parser.add_argument("--input-dir", default="backtests/reports/strategy_2_mechanical_spec_correction")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_rulebook_v0_labeling")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_rulebook_v0_labeling.md")
    parser.add_argument("--pip-factor", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    result = build_rulebook_v0_labeling(args.input_dir, pip_factor=args.pip_factor)
    paths = write_rulebook_v0_outputs(result, args.output_dir, docs_path=args.docs_path)
    return {
        "dry_run": bool(args.dry_run),
        "runtime_seconds": result.summary["runtime_seconds"],
        "containing_rows_loaded": result.summary["containing_rows_loaded"],
        "take_count": result.summary["take_count"],
        "skip_count": result.summary["skip_count"],
        "uncertain_count": result.summary["uncertain_count"],
        "not_computed_reaction_count": result.summary["not_computed_reaction_count"],
        "risk_zone_distribution": result.summary["risk_zone_distribution"],
        "manipulation_zone_distribution": result.summary["manipulation_zone_distribution"],
        "threshold_status_confirmation": result.summary["threshold_status_confirmation"],
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
