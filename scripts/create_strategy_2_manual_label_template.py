from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analysis.strategy_2_manual_sample_labels import write_template
from dazro_trade.analytics.strategy_2_manual_benchmark import write_manual_benchmark_doc, write_manual_benchmark_template
from dazro_trade.analytics.strategy_2_manual_sample_label_audit import write_research_doc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Strategy 2 manual label templates.")
    parser.add_argument("--schema", choices=["manual_benchmark", "sample_label_pack"], default="manual_benchmark")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_manual_benchmark")
    parser.add_argument("--format", choices=["csv", "jsonl", "both"], default="both")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_manual_benchmark.md")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, str]:
    if args.schema == "sample_label_pack":
        paths = write_template(Path(args.output_dir), output_format=args.format)
        paths["docs_md"] = write_research_doc(Path(args.docs_path))
        return paths
    paths = write_manual_benchmark_template(Path(args.output_dir))
    paths["docs_md"] = write_manual_benchmark_doc(Path(args.docs_path))
    return paths


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(json.dumps(run(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
