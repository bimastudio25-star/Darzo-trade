from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_containing_model_diagnostic import (
    build_containing_diagnostic,
    write_containing_diagnostic_outputs,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 2 containing M15 model diagnostic.")
    parser.add_argument("--input-dir", default="backtests/reports/strategy_2_mechanical_spec_correction")
    parser.add_argument("--selection-dir", default="backtests/reports/strategy_2_m15_model_selection_review")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_m15_containing_next_diagnostic")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_m15_containing_next_diagnostic.md")
    parser.add_argument("--pip-factor", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true", default=True, help="Safe report-only mode; still writes diagnostic outputs.")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    result = build_containing_diagnostic(args.input_dir, args.selection_dir, pip_factor=args.pip_factor)
    paths = write_containing_diagnostic_outputs(result, args.output_dir, docs_path=args.docs_path)
    containing_risk = next(row for row in result.summary["risk_profile"] if row["m15_filter_model"] == "containing")
    containing_tp_r = next(row for row in result.summary["tp_r_profile"] if row["m15_filter_model"] == "containing")
    return {
        "dry_run": bool(args.dry_run),
        "runtime_seconds": result.summary["runtime_seconds"],
        "primary_model": result.summary["primary_model"],
        "sensitivity_model": result.summary["sensitivity_model"],
        "containing_samples_loaded": result.summary["containing_samples_loaded"],
        "approach_window_samples_loaded": result.summary["approach_window_samples_loaded"],
        "containing_entry_count": result.summary["containing_entry_count"],
        "approach_window_entry_count": result.summary["approach_window_entry_count"],
        "sl_risk_profile": containing_risk,
        "tp_r_profile": containing_tp_r,
        "tail_risk_verdict": result.summary["tail_risk_verdict"],
        "r_profile_verdict": result.summary["r_profile_verdict"],
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
