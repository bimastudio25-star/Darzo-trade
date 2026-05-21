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
    parser.add_argument("--max-samples", type=int, default=300)
    parser.add_argument("--min-date-range-days", type=int, default=180)
    parser.add_argument("--max-samples-per-day", type=int, default=5)
    parser.add_argument("--min-sample-spacing-minutes", type=int, default=240)
    parser.add_argument(
        "--target-session-balance",
        action="store_true",
        default=False,
        help="Try to round-robin candidate selection across sessions. Disabled by default to avoid fake balance.",
    )
    parser.add_argument("--include-candidate-windows", action="store_true", default=True)
    parser.add_argument("--include-trade-review", action="store_true", default=True)
    parser.add_argument(
        "--allow-weak-m1-only",
        action="store_true",
        default=False,
        help="Allow weak samples with M1 but no M5 reaction context. Disabled by default.",
    )
    parser.add_argument(
        "--include-insufficient-execution-debug",
        action="store_true",
        default=False,
        help="Include non-labelable insufficient execution data samples for debugging only.",
    )
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
        min_date_range_days=args.min_date_range_days,
        max_samples_per_day=args.max_samples_per_day,
        min_sample_spacing_minutes=args.min_sample_spacing_minutes,
        target_session_balance=bool(args.target_session_balance),
        include_candidate_windows=bool(args.include_candidate_windows),
        include_trade_review=bool(args.include_trade_review),
        allow_weak_m1_only=bool(args.allow_weak_m1_only),
        include_insufficient_execution_debug=bool(args.include_insufficient_execution_debug),
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
                "total_samples_generated": summary["total_samples_generated"],
                "date_range_coverage_days": summary["date_range_coverage_days"],
                "candidate_source_counts": summary["candidate_source_counts"],
                "entry_level_source_counts": summary["entry_level_source_counts"],
                "session_distribution": summary["session_distribution"],
                "samples_per_month_distribution": summary["samples_per_month_distribution"],
                "volatility_bucket_distribution": summary["volatility_bucket_distribution"],
                "samples_skipped_missing_execution": summary["samples_skipped_missing_execution"],
                "samples_skipped_duplicate_spacing": summary["samples_skipped_duplicate_spacing"],
                "samples_skipped_max_per_day": summary["samples_skipped_max_per_day"],
                "expanded_pack_generation_verdict": summary["expanded_pack_generation_verdict"],
                "expanded_pack_generation_verdict_reason": summary["expanded_pack_generation_verdict_reason"],
                "reviewable_samples": summary["reviewable_samples"],
                "reviewable_m1_m5_count": summary["reviewable_m1_m5_count"],
                "reviewable_m5_only_count": summary["reviewable_m5_only_count"],
                "weak_m1_only_count": summary["weak_m1_only_count"],
                "insufficient_execution_data_count": summary["insufficient_execution_data_count"],
                "samples_skipped_due_to_missing_ltf_data": summary["samples_skipped_due_to_missing_ltf_data"],
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
