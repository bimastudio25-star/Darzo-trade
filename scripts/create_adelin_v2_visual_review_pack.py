from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.adelin_v2_visual_review_pack import (
    DEFAULT_OUTPUT_DIR,
    VisualReviewPackConfig,
    create_visual_review_pack,
)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the research-only Adelin v2 visual review pack")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--trades-path", default=None)
    parser.add_argument("--audit-path", default=None)
    parser.add_argument("--from-date", default=None)
    parser.add_argument("--to-date", default=None)
    parser.add_argument("--max-samples", type=int, default=40)
    parser.add_argument("--include-candidate-windows", action="store_true", default=True)
    parser.add_argument("--include-trade-review", action="store_true", default=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Explicit safety flag. The pack is research-only even when this flag is omitted.",
    )
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> VisualReviewPackConfig:
    return VisualReviewPackConfig(
        symbol=args.symbol,
        data_dir=Path(args.data_dir),
        output_dir=Path(args.output_dir),
        trades_path=Path(args.trades_path) if args.trades_path else None,
        audit_path=Path(args.audit_path) if args.audit_path else None,
        from_date=_parse_datetime(args.from_date),
        to_date=_parse_datetime(args.to_date),
        max_samples=args.max_samples,
        include_candidate_windows=bool(args.include_candidate_windows),
        include_trade_review=bool(args.include_trade_review),
        dry_run=bool(args.dry_run),
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = create_visual_review_pack(config_from_args(args))
    print(
        json.dumps(
            {
                "output_dir": summary["output_dir"],
                "source_modes_used": summary["source_modes_used"],
                "trades_loaded": summary["trades_loaded"],
                "audit_rows_loaded": summary["audit_rows_loaded"],
                "candidate_windows_generated": summary["candidate_windows_generated"],
                "total_samples": summary["total_samples"],
                "reviewable_samples": summary["reviewable_samples"],
                "reviewable_m1_m5_count": summary["reviewable_m1_m5_count"],
                "reviewable_m5_only_count": summary["reviewable_m5_only_count"],
                "weak_m1_only_count": summary["weak_m1_only_count"],
                "insufficient_execution_data_count": summary["insufficient_execution_data_count"],
                "charts_generated": summary["charts_generated"],
                "html_pages_generated": summary["html_pages_generated"],
                "limitations": summary["limitations"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
