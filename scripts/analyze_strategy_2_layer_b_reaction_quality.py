from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_layer_b_reaction_quality import (
    build_layer_b_reaction_quality,
    write_layer_b_outputs,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Strategy 2 Layer B reaction-quality diagnostics.")
    parser.add_argument("--input", default="backtests/reports/strategy_2_fully_invalidated_state_split/state_split_per_sample.csv")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_layer_b_reaction_quality")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_layer_b_reaction_quality.md")
    parser.add_argument("--pip-factor", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    result = build_layer_b_reaction_quality(
        args.input,
        data_dir=args.data_dir,
        symbol=args.symbol,
        pip_factor=args.pip_factor,
    )
    paths = write_layer_b_outputs(result, args.output_dir, docs_path=args.docs_path)
    return {
        "dry_run": bool(args.dry_run),
        "runtime_seconds": result.summary["runtime_seconds"],
        "samples_loaded": result.summary["samples_loaded"],
        "eligible_valid_long_count": result.summary["eligible_valid_long_count"],
        "eligible_valid_short_count": result.summary["eligible_valid_short_count"],
        "excluded_states": result.summary["excluded_states"],
        "reaction_descriptor_distribution": result.summary["reaction_descriptor_distribution"],
        "layer_b_candidate_label_distribution": result.summary["layer_b_candidate_label_distribution"],
        "missing_data_count": result.summary["missing_data_count"],
        "future_data_diagnostic_only_count": result.summary["future_data_diagnostic_only_count"],
        "future_data_features_are_diagnostic_only": result.summary["future_data_features_are_diagnostic_only"],
        "take_skip_decision_produced": result.summary["take_skip_decision_produced"],
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
