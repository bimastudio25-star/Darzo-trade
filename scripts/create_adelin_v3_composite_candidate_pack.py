from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.adelin_v3_composite_detector import (
    DEFAULT_OUTPUT_DIR,
    AdelinV3Config,
    generate_v3_candidate_pack,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the research-only Adelin v3 composite multi-condition candidate pack"
    )
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--from-date", default=None)
    parser.add_argument("--to-date", default=None)
    parser.add_argument("--max-candidates", type=int, default=500)
    parser.add_argument("--max-examples", type=int, default=120)
    parser.add_argument("--sweep-lookback-minutes", type=int, default=60)
    parser.add_argument("--min-sweep-anchor-delay-minutes", type=int, default=5)
    parser.add_argument("--min-spacing-minutes", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def _parse_date(value: str | None):
    if not value:
        return None
    from datetime import datetime, timezone

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def config_from_args(args: argparse.Namespace) -> AdelinV3Config:
    return AdelinV3Config(
        symbol=args.symbol,
        data_dir=Path(args.data_dir),
        output_dir=Path(args.output_dir),
        from_date=_parse_date(args.from_date),
        to_date=_parse_date(args.to_date),
        max_candidates=args.max_candidates,
        max_examples=args.max_examples,
        sweep_lookback_minutes=args.sweep_lookback_minutes,
        min_sweep_anchor_delay_minutes=args.min_sweep_anchor_delay_minutes,
        min_spacing_minutes=args.min_spacing_minutes,
        dry_run=bool(args.dry_run),
    )


def main(argv: list[str] | None = None) -> int:
    summary = generate_v3_candidate_pack(config_from_args(parse_args(argv)))
    print(
        json.dumps(
            {
                "output_dir": summary["output_dir"],
                "candidate_count": summary["candidate_count"],
                "candidate_pack_verdict": summary["candidate_pack_verdict"],
                "source_counts": summary["source_counts"],
                "direction_counts": summary["direction_counts"],
                "reaction_zone_counts": summary["reaction_zone_counts"],
                "liquidity_confluence_counts": summary["liquidity_confluence_counts"],
                "session_counts": summary["session_counts"],
                "rejection_counts": summary["rejection_counts"],
                "limitations": summary["limitations"],
                "recommended_next_step": summary["recommended_next_step"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
