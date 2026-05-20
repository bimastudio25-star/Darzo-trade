from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analysis.strategy_2_manual_sample_labels import build_manual_label_analysis
from dazro_trade.analytics.strategy_2_manual_sample_label_audit import write_manual_label_analysis_outputs, write_research_doc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Strategy 2 manual sample labels against automatic samples.")
    parser.add_argument("--labels-path", default="backtests/reports/strategy_2_manual_sample_label_pack/manual_samples.csv")
    parser.add_argument("--auto-samples-path", default="backtests/reports/strategy_2_statistical_sample_recorder/h1_liquidity_samples.csv")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_manual_sample_label_pack")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_manual_sample_label_pack.md")
    parser.add_argument("--pip-factor", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, str]:
    report = build_manual_label_analysis(
        labels_path=Path(args.labels_path),
        auto_samples_path=Path(args.auto_samples_path),
        pip_factor=args.pip_factor,
    )
    paths = write_manual_label_analysis_outputs(report, Path(args.output_dir))
    paths["docs_md"] = write_research_doc(Path(args.docs_path))
    return paths


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(json.dumps(run(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
