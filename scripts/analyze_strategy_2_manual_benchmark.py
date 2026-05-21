from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_manual_benchmark import build_manual_benchmark_analysis, write_manual_benchmark_outputs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Strategy 2 manual benchmark labels.")
    parser.add_argument("--labels-path", default="backtests/reports/strategy_2_manual_benchmark/manual_labels_template.csv")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_manual_benchmark")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_manual_benchmark.md")
    parser.add_argument("--pip-factor", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    result = build_manual_benchmark_analysis(args.labels_path, pip_factor=args.pip_factor)
    paths = write_manual_benchmark_outputs(result, args.output_dir, docs_path=args.docs_path)
    return {
        "dry_run": bool(args.dry_run),
        "labels_path": str(Path(args.labels_path)),
        "output_dir": str(Path(args.output_dir)),
        "total_samples": result.summary["total_samples"],
        "take_count": result.summary["take_count"],
        "skip_count": result.summary["skip_count"],
        "uncertain_count": result.summary["uncertain_count"],
        "validation_valid": result.summary["validation_valid"],
        "validation_error_count": result.summary["validation_error_count"],
        "validation_warning_count": result.summary["validation_warning_count"],
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
