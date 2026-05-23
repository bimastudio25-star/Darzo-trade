from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_layer_b_blinded_manual_validation_pack import (
    DEFAULT_SHUFFLE_SEED,
    EXPECTED_ROW_COUNT,
    build_strict_blinded_manual_validation_pack,
    write_strict_blinded_outputs,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a strict blinded Strategy 2 Layer B manual validation pack.")
    parser.add_argument(
        "--input",
        default="backtests/reports/strategy_2_layer_b_manual_validation_pack/manual_validation_pack.csv",
        help="Approved unblinded source pack. This script does not rerun Layer B.",
    )
    parser.add_argument(
        "--output-root",
        default="backtests/reports/strategy_2_layer_b_manual_validation_pack",
    )
    parser.add_argument("--shuffle-seed", type=int, default=DEFAULT_SHUFFLE_SEED)
    parser.add_argument("--expected-count", type=int, default=EXPECTED_ROW_COUNT)
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    result = build_strict_blinded_manual_validation_pack(
        args.input,
        shuffle_seed=args.shuffle_seed,
        expected_count=args.expected_count,
    )
    paths = write_strict_blinded_outputs(result, args.output_root)
    return {
        "dry_run": bool(args.dry_run),
        "input": str(Path(args.input)),
        "output_root": str(Path(args.output_root)),
        "layer_b_pipeline_rerun": False,
        "source_pack_row_count": result.summary["source_pack_row_count"],
        "blinded_row_count": result.summary["blinded_row_count"],
        "answer_key_row_count": result.summary["answer_key_row_count"],
        "shuffle_seed": result.summary["shuffle_seed"],
        "row_order_changed": result.summary["row_order_changed"],
        "descriptor_counts_hidden_in_answer_key": result.summary["descriptor_counts_hidden_in_answer_key"],
        "reentry_not_reached_count_inside_blinded_csv": result.summary["reentry_not_reached_count_inside_blinded_csv"],
        "missing_decision_time_count_inside_blinded_csv": result.summary["missing_decision_time_count_inside_blinded_csv"],
        "validation_gate_result": result.summary["validation_gate_result"],
        "blinding_gate_result": result.summary["blinding_gate_result"],
        "safety": result.summary["safety"],
        "paths": paths,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(json.dumps(run(args), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
