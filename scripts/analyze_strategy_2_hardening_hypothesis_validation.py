from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_hardening_hypothesis_validation import (
    build_hypothesis_validation,
    write_hypothesis_validation_outputs,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 2 hardening hypothesis validation.")
    parser.add_argument("--tail-dir", default="backtests/reports/strategy_2_tail_risk_hardening")
    parser.add_argument("--containing-dir", default="backtests/reports/strategy_2_m15_containing_next_diagnostic")
    parser.add_argument("--mechanical-dir", default="backtests/reports/strategy_2_mechanical_spec_correction")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_hardening_hypothesis_validation")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_hardening_hypothesis_validation.md")
    parser.add_argument("--pip-factor", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true", default=True, help="Safe report-only mode; still writes diagnostic outputs.")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    result = build_hypothesis_validation(args.tail_dir, args.containing_dir, args.mechanical_dir, pip_factor=args.pip_factor)
    paths = write_hypothesis_validation_outputs(result, args.output_dir, docs_path=args.docs_path)
    return {
        "dry_run": bool(args.dry_run),
        "runtime_seconds": result.summary["runtime_seconds"],
        "samples_loaded": result.summary["samples_loaded"],
        "ex_post_upper_bound_result": result.summary["ex_post_upper_bound_result"],
        "proxy_candidates_evaluated": result.summary["proxy_candidates_evaluated"],
        "leakage_features_rejected": result.summary["leakage_features_rejected"],
        "best_pre_entry_proxy": result.summary["best_pre_entry_proxy"],
        "r_profile_raw": result.summary["r_profile_raw"],
        "r_profile_after_best_proxy": result.summary["r_profile_after_best_proxy"],
        "final_verdict": result.summary["final_verdict"],
        "verdict_flags": result.summary["verdict_flags"],
        "paths": paths,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(args)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
