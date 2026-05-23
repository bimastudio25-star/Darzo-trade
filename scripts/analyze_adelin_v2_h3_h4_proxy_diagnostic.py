"""Run the bounded Adelin v2 H3/H4 proxy diagnostic execution.

The execution is research-only. It validates the human-approved H3/H4 proxy
plan, reads existing direction-resolved Adelin v2 sample metadata, reads M1/M5
OHLC only for pre-decision proxy computation, and writes descriptive reports.
It does not run Phase 4, matched controls, backtests, runtime logic, live
trading, Telegram alerts, broker execution, or order_send.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.adelin_v2_h3_h4_proxy_diagnostic import DiagnosticConfig, run_diagnostic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-path",
        type=Path,
        default=DiagnosticConfig.sample_path,
        help="Existing direction-resolved Adelin v2 sample metadata CSV.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DiagnosticConfig.output_dir,
        help="Output directory for H3/H4 diagnostic artifacts.",
    )
    parser.add_argument(
        "--doc-path",
        type=Path,
        default=DiagnosticConfig.doc_path,
        help="Research markdown report path.",
    )
    parser.add_argument("--data-dir", type=Path, default=DiagnosticConfig.data_dir)
    parser.add_argument("--symbol", default=DiagnosticConfig.symbol)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_diagnostic(
        DiagnosticConfig(
            sample_path=args.sample_path,
            output_dir=args.output_dir,
            doc_path=args.doc_path,
            data_dir=args.data_dir,
            symbol=args.symbol,
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("precheck_passed") is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
