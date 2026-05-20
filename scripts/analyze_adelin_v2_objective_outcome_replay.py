from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.adelin_v2_objective_outcome_replay import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_VISUAL_PACK_DIR,
    ObjectiveReplayConfig,
    run_objective_replay,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the research-only Adelin v2 objective outcome replay with a matched control baseline"
    )
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--visual-pack-dir", default=str(DEFAULT_VISUAL_PACK_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--forward-hours", type=float, default=4.0)
    parser.add_argument("--direction-lookback-minutes", type=int, default=30)
    parser.add_argument("--reaction-fast-minutes", type=int, default=15)
    parser.add_argument("--reaction-slow-minutes", type=int, default=30)
    parser.add_argument("--include-control-random", type=int, default=40)
    parser.add_argument("--pip-size", type=float, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Explicit safety flag. The replay is diagnostic-only even when this flag is omitted.",
    )
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> ObjectiveReplayConfig:
    return ObjectiveReplayConfig(
        symbol=args.symbol,
        data_dir=Path(args.data_dir),
        visual_pack_dir=Path(args.visual_pack_dir),
        output_dir=Path(args.output_dir),
        forward_hours=args.forward_hours,
        direction_lookback_minutes=args.direction_lookback_minutes,
        reaction_fast_minutes=args.reaction_fast_minutes,
        reaction_slow_minutes=args.reaction_slow_minutes,
        include_control_random=args.include_control_random,
        pip_size_override=args.pip_size,
        dry_run=bool(args.dry_run),
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_objective_replay(config_from_args(args))
    print(
        json.dumps(
            {
                "output_dir": summary["output_dir"],
                "pip_size_source": summary["pip_size_source"],
                "pip_size": summary["pip_size"],
                "forward_hours": summary["forward_hours"],
                "total_candidate_samples_loaded": summary["total_candidate_samples_loaded"],
                "candidate_samples_replayed": summary["candidate_samples_replayed"],
                "control_samples_generated": summary["control_samples_generated"],
                "control_samples_replayed": summary["control_samples_replayed"],
                "rows_written": summary["rows_written"],
                "candidate_known_entry_count": summary["candidate_known_entry_count"],
                "control_known_entry_count": summary["control_known_entry_count"],
                "candidate_unknown_entry_level_count": summary["candidate_unknown_entry_level_count"],
                "control_unknown_entry_level_count": summary["control_unknown_entry_level_count"],
                "candidate_entry_level_source_counts": summary["candidate_entry_level_source_counts"],
                "control_entry_level_source_counts": summary["control_entry_level_source_counts"],
                "candidate_outcome_label_counts": summary["candidate_outcome_label_counts"],
                "control_outcome_label_counts": summary["control_outcome_label_counts"],
                "candidate_outcome_counts_by_entry_level_source": summary["candidate_outcome_counts_by_entry_level_source"],
                "control_outcome_counts_by_entry_level_source": summary["control_outcome_counts_by_entry_level_source"],
                "candidate_vs_control": summary["candidate_vs_control"],
                "candidate_vs_control_known_entry": summary["candidate_vs_control_known_entry"],
                "candidate_vs_control_round_level": summary["candidate_vs_control_round_level"],
                "candidate_vs_control_sweep_extreme": summary["candidate_vs_control_sweep_extreme"],
                "limitations": summary["limitations"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
