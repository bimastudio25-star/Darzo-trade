from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_layer_b_manual_validation_pack import (
    build_layer_b_manual_validation_pack,
    write_manual_validation_pack_outputs,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Strategy 2 Layer B manual validation pack.")
    parser.add_argument(
        "--input",
        default="backtests/reports/strategy_2_layer_b_reaction_quality/layer_b_reaction_features_per_sample.csv",
        help="Pre-generated corrected Layer B reaction feature CSV. This script does not rerun Layer B.",
    )
    parser.add_argument(
        "--mechanical-input",
        default="backtests/reports/strategy_2_mechanical_spec_correction/corrected_mechanical_samples.csv",
        help="Optional read-only mechanical CSV used only to enrich manual-review columns.",
    )
    parser.add_argument(
        "--output-dir",
        default="backtests/reports/strategy_2_layer_b_manual_validation_pack",
    )
    parser.add_argument("--expected-count", type=int, default=135)
    parser.add_argument("--expected-fast-count", type=int, default=56)
    parser.add_argument("--expected-chop-count", type=int, default=79)
    parser.add_argument("--allow-count-mismatch", action="store_true")
    parser.add_argument("--pip-factor", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    expected_descriptor_counts = {
        "FAST_REENTRY": int(args.expected_fast_count),
        "CHOP_AFTER_SWEEP_CANDIDATE": int(args.expected_chop_count),
    }
    result = build_layer_b_manual_validation_pack(
        args.input,
        mechanical_path=args.mechanical_input,
        expected_count=args.expected_count,
        expected_descriptor_counts=expected_descriptor_counts,
        allow_count_mismatch=bool(args.allow_count_mismatch),
        pip_factor=args.pip_factor,
    )
    paths = write_manual_validation_pack_outputs(result, args.output_dir)
    return {
        "dry_run": bool(args.dry_run),
        "input": str(Path(args.input)),
        "mechanical_input": str(Path(args.mechanical_input)),
        "output_dir": str(Path(args.output_dir)),
        "layer_b_pipeline_rerun": False,
        "total_source_rows_loaded": result.summary["total_source_rows_loaded"],
        "layer_a_valid_count": result.summary["layer_a_valid_count"],
        "pack_row_count": result.summary["pack_row_count"],
        "excluded_reentry_not_reached_count": result.summary["excluded_reentry_not_reached_count"],
        "excluded_not_enough_data_count": result.summary["excluded_not_enough_data_count"],
        "excluded_missing_decision_time_bug_count": result.summary["excluded_missing_decision_time_bug_count"],
        "descriptor_counts_in_pack": result.summary["descriptor_counts_in_pack"],
        "validation_gate_result": result.summary["validation_gate_result"],
        "safety": result.summary["safety"],
        "paths": paths,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(json.dumps(run(args), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
