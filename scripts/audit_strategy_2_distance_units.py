from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_unit_distance_audit import (
    build_unit_distance_audit,
    write_unit_distance_outputs,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 2 distance unit audit.")
    parser.add_argument("--input-dirs", nargs="+", required=True)
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_unit_distance_audit")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_unit_distance_audit.md")
    parser.add_argument("--pip-factor", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true", default=True, help="Safe report-only mode; still writes audit outputs.")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    result = build_unit_distance_audit(args.input_dirs, pip_factor=args.pip_factor)
    paths = write_unit_distance_outputs(result, args.output_dir, docs_path=args.docs_path)
    return {
        "dry_run": bool(args.dry_run),
        "runtime_seconds": result.summary["runtime_seconds"],
        "fields_audited": result.summary["fields_audited"],
        "unit_semantics_verdict": result.summary["unit_semantics_verdict"],
        "paired_usd_pips_fields_checked": result.summary["paired_usd_pips_fields_checked"],
        "paired_usd_pips_fields_matching": result.summary["paired_usd_pips_fields_matching"],
        "pair_mismatch_count": result.summary["pair_mismatch_count"],
        "r_profile_changes_after_correction": result.summary["r_profile_changes_after_correction"],
        "corrected_key_values": result.summary["corrected_key_values"],
        "recommended_follow_up_branch": result.summary["recommended_follow_up_branch"],
        "paths": paths,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(args)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
