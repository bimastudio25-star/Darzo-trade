from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_layer_b_not_enough_data_audit import (
    build_not_enough_data_audit,
    write_not_enough_data_audit_outputs,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Strategy 2 Layer B NOT_ENOUGH_DATA clustering.")
    parser.add_argument("--input", default="backtests/reports/strategy_2_layer_b_reaction_quality/layer_b_reaction_features_per_sample.csv")
    parser.add_argument("--state-split", default="backtests/reports/strategy_2_fully_invalidated_state_split/state_split_per_sample.csv")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_layer_b_not_enough_data_audit")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_layer_b_not_enough_data_audit.md")
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    result = build_not_enough_data_audit(
        args.input,
        state_split_path=args.state_split,
        data_dir=args.data_dir,
        symbol=args.symbol,
    )
    paths = write_not_enough_data_audit_outputs(result, args.output_dir, docs_path=args.docs_path)
    return {
        "dry_run": bool(args.dry_run),
        "runtime_seconds": result.summary["runtime_seconds"],
        "samples_processed": result.summary["samples_processed"],
        "original_layer_a_valid_samples": result.summary["original_layer_a_valid_samples"],
        "layer_b_eligible_samples": result.summary["layer_b_eligible_samples"],
        "layer_b_measurable_samples": result.summary["layer_b_measurable_samples"],
        "reentry_not_reached_count": result.summary["reentry_not_reached_count"],
        "not_enough_data_count": result.summary["not_enough_data_count"],
        "not_enough_data_rate": result.summary["not_enough_data_rate"],
        "descriptor_distribution_after_reclassification": result.summary["descriptor_distribution"],
        "measurable_descriptor_distribution": result.summary["measurable_descriptor_distribution"],
        "not_enough_data_by_direction": result.summary["not_enough_data_by_direction"],
        "not_enough_data_by_session": result.summary["not_enough_data_by_session"],
        "not_enough_data_by_weekday": result.summary["not_enough_data_by_weekday"],
        "top_h1_contexts": result.summary["top_h1_contexts"],
        "likely_cause_breakdown": result.summary["likely_cause_breakdown"],
        "critical_conclusion": result.summary["critical_conclusion"],
        "recommended_next_step": result.summary["recommended_next_step"],
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
