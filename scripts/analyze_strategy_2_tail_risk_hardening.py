from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_tail_risk_hardening import (
    build_tail_risk_hardening,
    write_tail_risk_outputs,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 2 tail risk hardening diagnostics.")
    parser.add_argument("--input-dir", default="backtests/reports/strategy_2_m15_containing_next_diagnostic")
    parser.add_argument("--mechanical-dir", default="backtests/reports/strategy_2_mechanical_spec_correction")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_tail_risk_hardening")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_tail_risk_hardening.md")
    parser.add_argument("--pip-factor", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true", default=True, help="Safe report-only mode; still writes diagnostic outputs.")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    result = build_tail_risk_hardening(args.input_dir, args.mechanical_dir, pip_factor=args.pip_factor)
    paths = write_tail_risk_outputs(result, args.output_dir, docs_path=args.docs_path)
    return {
        "dry_run": bool(args.dry_run),
        "runtime_seconds": result.summary["runtime_seconds"],
        "samples_loaded": result.summary["samples_loaded"],
        "tail_bucket_counts": result.summary["tail_bucket_counts"],
        "strongest_tail_drivers": result.summary["strongest_tail_drivers"],
        "best_diagnostic_hypothesis": result.summary["best_diagnostic_hypothesis"],
        "r_profile_before": result.summary["r_profile_before"],
        "r_profile_after_best_hypothesis": result.summary["r_profile_after_best_hypothesis"],
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
