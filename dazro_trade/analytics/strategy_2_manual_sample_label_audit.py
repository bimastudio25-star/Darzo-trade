from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def write_manual_label_analysis_outputs(report: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "validation_json": str(output_dir / "manual_label_validation.json"),
        "profile_summary_json": str(output_dir / "manual_profile_summary.json"),
        "manual_vs_global_csv": str(output_dir / "manual_vs_global_comparison.csv"),
        "deep_tail_csv": str(output_dir / "deep_tail_analysis.csv"),
        "feature_differences_csv": str(output_dir / "manual_feature_differences.csv"),
        "matches_csv": str(output_dir / "manual_auto_sample_matches.csv"),
        "report_md": str(output_dir / "manual_sample_label_report.md"),
    }
    validation = {key: value for key, value in report["validation"].items() if key != "normalized_rows"}
    Path(paths["validation_json"]).write_text(json.dumps(validation, indent=2, sort_keys=True, default=str), encoding="utf-8")
    summary = {
        "manual_profiles": report["manual_profiles"],
        "global_profile": report["global_profile"],
        "verdict_flags": report["verdict_flags"],
        "safety": report["safety"],
    }
    Path(paths["profile_summary_json"]).write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    _write_csv(Path(paths["manual_vs_global_csv"]), report["manual_vs_global_comparison"])
    _write_csv(Path(paths["deep_tail_csv"]), report["deep_tail_analysis"])
    _write_csv(Path(paths["feature_differences_csv"]), report["feature_differences"])
    _write_csv(Path(paths["matches_csv"]), report["matches"])
    Path(paths["report_md"]).write_text(render_manual_label_report(report), encoding="utf-8")
    return paths


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def render_manual_label_report(report: dict[str, Any]) -> str:
    validation = report["validation"]
    global_profile = report["global_profile"]
    manual_profiles = report["manual_profiles"]
    lines = [
        "# Strategy 2 Manual Sample Label Pack Analysis",
        "",
        "Research-only manual label comparison. No live trading, no orders, no Telegram, no runtime registration.",
        "",
        "## Validation",
        "",
        f"- rows loaded: `{validation['rows_loaded']}`",
        f"- real label rows: `{validation['real_label_rows']}`",
        f"- example rows: `{validation['example_rows']}`",
        f"- valid schema: `{validation['valid']}`",
        f"- manual labels not provided yet: `{validation['manual_labels_not_provided_yet']}`",
        "",
        "## Manual Profiles",
        "",
        "```json",
        json.dumps(manual_profiles, indent=2, sort_keys=True, default=str),
        "```",
        "",
        "## Automatic Global Profile",
        "",
        "```json",
        json.dumps(
            {
                "count": global_profile.get("count"),
                "avg_manipulation_usd": global_profile.get("avg_manipulation_usd"),
                "max_manipulation_usd": global_profile.get("max_manipulation_usd"),
                "p95_manipulation_usd": global_profile.get("p95_manipulation_usd"),
                "avg_expansion_usd": global_profile.get("avg_expansion_usd"),
                "profile_risk_too_large": global_profile.get("profile_risk_too_large"),
            },
            indent=2,
            sort_keys=True,
        ),
        "```",
        "",
        "## Deep Tail",
        "",
        "```json",
        json.dumps(report["deep_tail_analysis"], indent=2, sort_keys=True, default=str),
        "```",
        "",
        "## Verdict Flags",
        "",
        "\n".join(f"- `{flag}`" for flag in report["verdict_flags"]),
    ]
    return "\n".join(lines) + "\n"


def render_research_doc() -> str:
    return """# Strategy 2 Manual Sample Label Pack

## Context

The statistical sample recorder was built successfully. The M15 HH:45/x:45 filter was corrected, TP anchoring to the H1 liquidity level was confirmed, and the broad automatic valid sample pool showed an unusable raw max SL because the tail reached 62.8 USD. The body of the distribution remains plausible because most samples were <=8 USD and <=12 USD. The missing part is user/A+ filtering.

## Purpose

This branch creates a manual sample label schema so user-labeled trades, missed trades, rejected setups, and invalid examples can be compared with the automatic sample pool. It does not create final deterministic filters or live signals.

## Safety

- Strategy 3 untouched.
- data/XAUUSD/*.csv untouched.
- No live trading.
- No Telegram.
- No broker execution.
- No order_send.
- No orders.
- Research-only.

## Label Schema

Required minimum fields:
- manual_sample_id
- symbol
- h1_timestamp or approximate timestamp
- direction
- user_grade
- manual_trade_taken
- notes or user_reasoning

Recommended fields:
- h1_high/h1_low/liquidity level
- manual entry/SL/TP
- reaction_quality
- candle_anatomy_quality
- avoid_reason
- screenshot_ref

The schema also supports M15 x:45 fields, manipulation/expansion values in USD and pips, TP distances, setup model, compression state, move-consumed state, and reviewer notes.

## How To Use

1. Generate the template:
   `python scripts/create_strategy_2_manual_label_template.py --output-dir backtests/reports/strategy_2_manual_sample_label_pack --format both`
2. Create `manual_samples.csv` from the template.
3. Fill 10-30 samples minimum; 30+ preferred.
4. Include A+ winners, losers, BE trades, valid no-entry samples, rejected setups, and invalid examples.
5. Do not include only winners.
6. Run:
   `python scripts/analyze_strategy_2_manual_sample_labels.py --labels-path backtests/reports/strategy_2_manual_sample_label_pack/manual_samples.csv --auto-samples-path backtests/reports/strategy_2_statistical_sample_recorder/h1_liquidity_samples.csv --output-dir backtests/reports/strategy_2_manual_sample_label_pack --dry-run`

## Analysis Method

- Validate partial manual labels without requiring every optional field.
- Match manual labels to automatic samples by timestamp, direction, and liquidity level when available.
- Build manual subset profiles for A_PLUS, A_PLUS+A, A_PLUS+A+B, NO_TRADE, and INVALID.
- Compare each subset against the automatic global sample pool.
- Analyze the deep-tail automatic samples where manipulation_depth_usd > 12.

## Expected Outputs

- manual_label_validation.json
- manual_profile_summary.json
- manual_vs_global_comparison.csv
- deep_tail_analysis.csv
- manual_sample_label_report.md

## Verdict Flags

- MANUAL_SAMPLE_LABEL_PACK_BUILT
- MANUAL_LABEL_SCHEMA_CREATED
- MANUAL_LABEL_TEMPLATE_CREATED
- GLOBAL_VALID_SAMPLE_POOL_TOO_BROAD
- DEEP_TAIL_DRIVES_RAW_MAX_EXCURSION
- BODY_OF_DISTRIBUTION_PLAUSIBLE
- USER_A_PLUS_FILTER_REQUIRED
- UNIT_CONVERSION_GUARDED
- STRATEGY_2_REMAINS_RESEARCH_ONLY
- NO_LIVE_DEPLOYMENT_DECISION

## Next Step

Strategy 2-only next branch: `feat/strategy-2-manual-sample-profile-comparison` after real manual labels are provided.
"""


def write_research_doc(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_research_doc(), encoding="utf-8")
    return str(path)


__all__ = ["render_manual_label_report", "render_research_doc", "write_manual_label_analysis_outputs", "write_research_doc"]
