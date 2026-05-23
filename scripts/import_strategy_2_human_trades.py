from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_human_trade_import_normalizer import (
    DEFAULT_INPUT_DIR,
    DEFAULT_OUTPUT_DIR,
    import_strategy_2_human_trades,
    write_import_outputs,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize Strategy 2 human trade exports.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", help="Single raw MT5/broker export file.")
    group.add_argument("--input-dir", help="Directory containing raw MT5/broker export files.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--symbol-filter", default="XAUUSD")
    parser.add_argument("--strategy-tag-filter", default=None)
    parser.add_argument("--timezone-assumption", default="broker/server time unknown")
    parser.add_argument("--decimal-separator", choices=["auto", "dot", "comma"], default="auto")
    parser.add_argument("--overwrite", choices=["true", "false"], default="true")
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    overwrite = str(args.overwrite).lower() == "true"
    result = import_strategy_2_human_trades(
        input_path=args.input,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        symbol_filter=args.symbol_filter,
        strategy_tag_filter=args.strategy_tag_filter,
        timezone_assumption=args.timezone_assumption,
        decimal_separator=args.decimal_separator,
        overwrite=overwrite,
    )
    paths = write_import_outputs(result, args.output_dir, overwrite=overwrite)
    return {
        "dry_run": bool(args.dry_run),
        "input": args.input,
        "input_dir": args.input_dir or str(DEFAULT_INPUT_DIR),
        "output_dir": str(Path(args.output_dir)),
        "normalized_rows": len(result.normalized),
        "invalid_rows": len(result.errors),
        "files_processed": result.summary["files_processed"],
        "detected_encodings": result.summary["detected_encodings"],
        "detected_delimiters": result.summary["detected_delimiters"],
        "decimal_styles": result.summary["decimal_styles"],
        "detected_export_granularities": result.summary["detected_export_granularities"],
        "alignment_metrics_generated": result.summary["alignment_metrics_generated"],
        "safety": result.summary["safety"],
        "paths": paths,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        print(json.dumps(run(args), indent=2, sort_keys=True, default=str))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "IMPORT_FAILED_CLOSED",
                    "error_type": exc.__class__.__name__,
                    "error_message": str(exc),
                    "fabricated_human_trades": False,
                    "alignment_run": False,
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
