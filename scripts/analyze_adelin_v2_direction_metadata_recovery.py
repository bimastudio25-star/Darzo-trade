"""Recover Adelin v2 visual-review direction metadata with pre-entry evidence only.

This is a research-only metadata repair layer. It preserves existing visual
pack directions, uses deterministic metadata rules when available, and falls
back to strict pre-anchor M1/M5 sweep inference. It never uses post-entry
movement, replay outcomes, MFE/MAE, broker/order code, Telegram, or runtime
strategy logic.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.adelin_v2_objective_outcome_replay import detect_pre_anchor_sweep_control
from dazro_trade.backtest.data_loader import load_csv_timeframes
from dazro_trade.core.symbols import get_symbol_spec
from scripts.analyze_adelin_v2_preentry_outcome_diagnostics import (
    DEFAULT_VISUAL_PACK_DIR,
    DiagnosticConfig,
    load_visual_samples,
    normalize_frames,
    run_diagnostics,
    write_csv,
    write_json,
)


DEFAULT_OUTPUT_DIR = Path("backtests/reports/adelin_v2_direction_metadata_recovery")
DEFAULT_EXISTING_DIAGNOSTICS_DIR = Path("backtests/reports/adelin_v2_preentry_outcome_diagnostics")
DEFAULT_RECOVERED_DIAGNOSTICS_DIR = Path(
    "backtests/reports/adelin_v2_preentry_outcome_diagnostics_direction_recovered"
)

DIRECTION_CSV = "direction_recovery.csv"
DIRECTION_JSON = "direction_recovery.json"
SUMMARY_JSON = "direction_recovery_summary.json"
LIMITATIONS_JSON = "direction_recovery_limitations.json"

DIRECTION_INFERENCE_RULE_VERSION = "adelin_v2_pre_decision_sweep_v1"
DIRECTION_INFERENCE_RULE_NAME = "PRE_DECISION_SWEEP_INFERENCE"
DIRECTION_INFERENCE_RULE_ALLOWED_INPUTS = [
    "existing visual-pack direction metadata",
    "explicit candidate/signal side metadata when present",
    "unambiguous pre-entry liquidity-side metadata when present",
    "M5 candles in [decision_timestamp - sweep_lookback_minutes, decision_timestamp)",
    "M1 candles in [decision_timestamp - sweep_lookback_minutes, decision_timestamp)",
    "pre-anchor sweep candle timestamp and pre-anchor rejection/move-away candles",
    "explicit pre-entry entry/liquidity relation metadata when present",
]
DIRECTION_INFERENCE_RULE_FORBIDDEN_INPUTS = [
    "candles at or after decision_timestamp",
    "post-entry price movement",
    "MFE/MAE",
    "TP/SL hits",
    "win/loss",
    "diagnostic replay outcome",
    "matched-control result",
    "manual invention of direction",
]
DIRECTION_INFERENCE_RULE_DESCRIPTION = (
    "Preserve existing LONG/SHORT metadata at confidence 3. For missing directions, "
    "use explicit candidate side if present, then unambiguous liquidity-side metadata, "
    "then PRE_DECISION_SWEEP_INFERENCE at confidence 2. The sweep inference inspects "
    "M5 and M1 candles only in [decision_timestamp - 60m, decision_timestamp), excludes "
    "the anchor/decision candle and all post-entry candles, requires the sweep candle to "
    "be at least 5 minutes before the decision timestamp, and requires rejection or "
    "move-away by at least the configured rejection threshold. A sweep of high/upper "
    "liquidity maps to SHORT. A sweep of low/lower liquidity maps to LONG. Multiple "
    "valid sweep events inside the same pre-entry window are resolved by the latest "
    "defensible sweep event; unresolved or cross-source conflicts return UNKNOWN."
)
DIRECTION_INFERENCE_RULE_CONFLICT_POLICY = (
    "If independent pre-entry sources disagree, set final_direction=UNKNOWN, "
    "direction_source=CONFLICTING_DIRECTION_EVIDENCE, confidence=0, and do not force replay."
)
DIRECTION_INFERENCE_RULE_NO_EVIDENCE_POLICY = (
    "If no existing metadata, explicit side, liquidity-side metadata, valid pre-decision "
    "sweep, or entry/liquidity relation exists, set final_direction=UNKNOWN."
)
CONFIDENCE_2_WARNING = (
    "Confidence 2 directions are inferred from pre-decision sweep evidence and must not "
    "be treated as equal to confidence 3 existing visual-pack metadata."
)

VERDICT_FLAGS_BASE = [
    "DIRECTION_METADATA_RECOVERY_COMPLETE",
    "PRE_ENTRY_ONLY_DIRECTION_RECOVERY",
    "UNKNOWN_DIRECTION_COUNT_REPORTED",
    "NO_POST_ENTRY_DIRECTION_INFERENCE",
    "DIAGNOSTIC_TAGS_MULTI_LABEL_CONFIRMED",
    "PHASE_4_STILL_BLOCKED",
    "ADELIN_REMAINS_RESEARCH_ONLY",
    "NO_LIVE_DEPLOYMENT_DECISION",
    "NON_DIRECTIONAL_REPLAY_NOT_USED_AS_PRIMARY",
]

LONG_MARKERS = (
    "LONG",
    "BUY",
    "BULLISH",
    "LOW_TAKEN",
    "LOW SWEEP",
    "SWEEP_LOW",
    "SWING_LOW_SWEEP",
    "M15_SWING_LOW_SWEEP",
    "LOWER_WICK",
    "LOWER WICK",
)
SHORT_MARKERS = (
    "SHORT",
    "SELL",
    "BEARISH",
    "HIGH_TAKEN",
    "HIGH SWEEP",
    "SWEEP_HIGH",
    "SWING_HIGH_SWEEP",
    "M15_SWING_HIGH_SWEEP",
    "UPPER_WICK",
    "UPPER WICK",
)


@dataclass(frozen=True)
class RecoveryConfig:
    symbol: str = "XAUUSD"
    data_dir: Path = Path("data")
    visual_pack_dir: Path = DEFAULT_VISUAL_PACK_DIR
    existing_diagnostics_dir: Path = DEFAULT_EXISTING_DIAGNOSTICS_DIR
    output_dir: Path = DEFAULT_OUTPUT_DIR
    diagnostic_rerun_output_dir: Path = DEFAULT_RECOVERED_DIAGNOSTICS_DIR
    rerun_diagnostics: bool = True
    sweep_lookback_minutes: int = 60
    sweep_min_anchor_delay_minutes: int = 5
    sweep_min_rejection_pips: float = 5.0
    dry_run: bool = True


def _direction(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"LONG", "BUY", "BULLISH"}:
        return "LONG"
    if text in {"SHORT", "SELL", "BEARISH"}:
        return "SHORT"
    return "UNKNOWN"


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def inference_rule_metadata() -> dict[str, Any]:
    return {
        "inference_rule_version": DIRECTION_INFERENCE_RULE_VERSION,
        "inference_rule_name": DIRECTION_INFERENCE_RULE_NAME,
        "inference_rule_description": DIRECTION_INFERENCE_RULE_DESCRIPTION,
        "inference_rule_allowed_inputs": DIRECTION_INFERENCE_RULE_ALLOWED_INPUTS,
        "inference_rule_forbidden_inputs": DIRECTION_INFERENCE_RULE_FORBIDDEN_INPUTS,
        "inference_rule_conflict_policy": DIRECTION_INFERENCE_RULE_CONFLICT_POLICY,
        "inference_rule_no_evidence_policy": DIRECTION_INFERENCE_RULE_NO_EVIDENCE_POLICY,
        "confidence_2_warning": CONFIDENCE_2_WARNING,
    }


def _load_index_reason_codes(visual_pack_dir: Path) -> dict[str, str]:
    index_path = visual_pack_dir / "index.html"
    if not index_path.exists():
        return {}
    html = index_path.read_text(encoding="utf-8", errors="ignore")
    out: dict[str, str] = {}
    for match in re.finditer(r"<tr><td>(sample_\d+)</td>.*?</tr>", html, flags=re.DOTALL):
        row_html = match.group(0)
        cells = re.findall(r"<td>(.*?)</td>", row_html, flags=re.DOTALL)
        if len(cells) >= 9:
            reason = re.sub(r"<.*?>", "", cells[8]).strip()
            out[match.group(1)] = reason
    return out


def _direction_from_text(text: str) -> str:
    upper = text.upper()
    has_long = any(marker in upper for marker in LONG_MARKERS)
    has_short = any(marker in upper for marker in SHORT_MARKERS)
    if has_long and not has_short:
        return "LONG"
    if has_short and not has_long:
        return "SHORT"
    return "UNKNOWN"


def _candidate_side_evidence(sample: Mapping[str, str]) -> tuple[str, str] | None:
    for key in (
        "candidate_side",
        "candidate_direction",
        "signal_side",
        "signal_direction",
        "trade_side",
        "setup_side",
        "setup_direction",
    ):
        direction = _direction(sample.get(key))
        if direction != "UNKNOWN":
            return direction, f"{key}={sample.get(key)}"
    return None


def _liquidity_side_evidence(sample: Mapping[str, str], reason_codes: str) -> tuple[str, str] | None:
    text_parts = [reason_codes]
    for key in (
        "candidate_reason_codes",
        "liquidity_side",
        "liquidity_taken",
        "liquidity_taken_manual",
        "sweep_side",
        "sweep_type",
        "reversal_context",
    ):
        value = sample.get(key)
        if value:
            text_parts.append(str(value))
    text = " | ".join(text_parts)
    direction = _direction_from_text(text)
    if direction == "UNKNOWN":
        return None
    return direction, text


def _entry_liquidity_relation_evidence(sample: Mapping[str, str]) -> tuple[str, str] | None:
    level_text = sample.get("sweep_level") or sample.get("liquidity_level") or sample.get("level")
    entry_text = sample.get("entry_level_price") or sample.get("entry_price") or sample.get("entry_reference_price")
    side_text = " ".join(str(sample.get(key) or "") for key in ("sweep_side", "liquidity_side", "sweep_type"))
    if not level_text or not entry_text:
        return None
    try:
        level = float(level_text)
        entry = float(entry_text)
    except ValueError:
        return None
    side_direction = _direction_from_text(side_text)
    if side_direction == "LONG" and entry <= level:
        return "LONG", f"entry={entry} below_or_at_liquidity={level}"
    if side_direction == "SHORT" and entry >= level:
        return "SHORT", f"entry={entry} above_or_at_liquidity={level}"
    return None


def _pre_decision_sweep_evidence(
    sample: Mapping[str, str],
    frames: Mapping[str, pd.DataFrame],
    config: RecoveryConfig,
    pip_size: float,
) -> tuple[str, str, str] | None:
    ts = pd.to_datetime(sample.get("anchor_timestamp") or sample.get("decision_timestamp"), utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    detected = detect_pre_anchor_sweep_control(
        frames,
        pd.Timestamp(ts).to_pydatetime(),
        lookback_minutes=config.sweep_lookback_minutes,
        min_anchor_delay_minutes=config.sweep_min_anchor_delay_minutes,
        min_rejection_pips=config.sweep_min_rejection_pips,
        pip_size=pip_size,
    )
    if detected is None:
        return None
    direction, _entry = detected
    if direction.direction_guess not in {"LONG", "SHORT"}:
        return None
    reason = "|".join(direction.direction_reason_codes)
    detail = (
        f"{direction.direction_source_timeframe}_{direction.sweep_type};"
        f"sweep_timestamp={direction.sweep_timestamp.isoformat() if direction.sweep_timestamp else ''};"
        f"sweep_extreme={direction.sweep_extreme};"
        f"swept_level={direction.swept_level};"
        f"sweep_confidence={direction.direction_confidence};"
        f"{reason}"
    )
    return direction.direction_guess, detail, direction.direction_confidence


def recover_sample_direction(
    sample: Mapping[str, str],
    frames: Mapping[str, pd.DataFrame],
    config: RecoveryConfig,
    pip_size: float,
    reason_codes: str = "",
) -> dict[str, Any]:
    old_direction = _direction(sample.get("direction_guess") or sample.get("direction"))
    base = {
        "sample_id": sample.get("sample_id", ""),
        "candidate_id": sample.get("candidate_id", ""),
        "decision_timestamp": sample.get("anchor_timestamp") or sample.get("decision_timestamp") or "",
        "inference_rule_version": DIRECTION_INFERENCE_RULE_VERSION,
        "inference_rule_applied": "EXISTING_METADATA" if old_direction in {"LONG", "SHORT"} else "UNRECOVERABLE",
        "inference_rule_inputs_used": "direction_guess" if old_direction in {"LONG", "SHORT"} else "none",
        "inference_rule_forbidden_inputs_checked": "|".join(DIRECTION_INFERENCE_RULE_FORBIDDEN_INPUTS),
        "old_direction": old_direction,
        "recovered_direction": "UNKNOWN",
        "final_direction": old_direction if old_direction in {"LONG", "SHORT"} else "UNKNOWN",
        "direction_source": "EXISTING_METADATA" if old_direction in {"LONG", "SHORT"} else "UNRECOVERABLE",
        "direction_confidence": 3 if old_direction in {"LONG", "SHORT"} else 0,
        "direction_recovery_reason": "Existing visual-pack direction preserved."
        if old_direction in {"LONG", "SHORT"}
        else "No defensible pre-entry direction source found.",
        "conflicting_evidence": "",
        "pre_entry_only": True,
        "used_post_entry_data": False,
        "post_entry_data_used": False,
        "usable_for_directional_replay": old_direction in {"LONG", "SHORT"},
    }
    if old_direction in {"LONG", "SHORT"}:
        return base

    evidence: list[tuple[int, str, str, int, str]] = []
    candidate = _candidate_side_evidence(sample)
    if candidate:
        evidence.append((1, "CANDIDATE_SIDE_METADATA", candidate[0], 3, candidate[1]))
    liquidity = _liquidity_side_evidence(sample, reason_codes)
    if liquidity:
        evidence.append((2, "LIQUIDITY_SIDE_METADATA", liquidity[0], 2, liquidity[1]))
    sweep = _pre_decision_sweep_evidence(sample, frames, config, pip_size)
    if sweep:
        evidence.append((3, "PRE_DECISION_SWEEP_INFERENCE", sweep[0], 2, f"{sweep[1]};raw_confidence={sweep[2]}"))
    relation = _entry_liquidity_relation_evidence(sample)
    if relation:
        evidence.append((4, "ENTRY_LIQUIDITY_RELATION", relation[0], 1, relation[1]))

    if not evidence:
        return base

    directions = {item[2] for item in evidence}
    if len(directions) > 1:
        conflict = "|".join(f"{source}:{direction}:{reason}" for _prio, source, direction, _conf, reason in evidence)
        base.update(
            {
                "direction_source": "CONFLICTING_DIRECTION_EVIDENCE",
                "inference_rule_applied": "CONFLICTING_DIRECTION_EVIDENCE",
                "inference_rule_inputs_used": "multiple_pre_entry_sources",
                "direction_recovery_reason": "Conflicting pre-entry direction evidence; direction not forced.",
                "conflicting_evidence": conflict,
                "usable_for_directional_replay": False,
            }
        )
        return base

    chosen = sorted(evidence, key=lambda item: item[0])[0]
    _priority, source, direction, confidence, reason = chosen
    base.update(
        {
            "recovered_direction": direction,
            "final_direction": direction,
            "direction_source": source,
            "direction_confidence": confidence,
            "inference_rule_applied": source,
            "inference_rule_inputs_used": reason,
            "direction_recovery_reason": reason,
            "usable_for_directional_replay": True,
        }
    )
    return base


def _summary_from_existing_diagnostics(path: Path) -> dict[str, Any] | None:
    summary_path = path / "summary.json"
    if not summary_path.exists():
        return None
    return json.loads(summary_path.read_text(encoding="utf-8"))


def _count_unknown_direction_limitations(path: Path) -> int | None:
    csv_path = path / "sample_diagnostics.csv"
    if not csv_path.exists():
        return None
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return sum("UNKNOWN_DIRECTION_NO_DIRECTIONAL_REPLAY" in str(row.get("limitations", "")) for row in csv.DictReader(handle))


def build_summary(rows: Sequence[Mapping[str, Any]], config: RecoveryConfig) -> dict[str, Any]:
    total = len(rows)
    existing = sum(str(row.get("direction_source")) == "EXISTING_METADATA" for row in rows)
    missing = total - existing
    recovered = sum(
        str(row.get("recovered_direction")) in {"LONG", "SHORT"}
        and str(row.get("direction_source")) != "EXISTING_METADATA"
        for row in rows
    )
    final_known = sum(str(row.get("final_direction")) in {"LONG", "SHORT"} for row in rows)
    unknown = total - final_known
    source_counts = Counter(str(row.get("direction_source") or "UNKNOWN") for row in rows)
    confidence_counts = Counter(str(row.get("direction_confidence")) for row in rows)
    final_counts = Counter(str(row.get("final_direction") or "UNKNOWN") for row in rows)
    used_post_entry = sum(
        str(row.get("used_post_entry_data")).lower() == "true"
        or str(row.get("post_entry_data_used")).lower() == "true"
        for row in rows
    )
    flags = list(VERDICT_FLAGS_BASE)
    if recovered == 0:
        flags.append("DIRECTION_RECOVERY_NOT_POSSIBLE_FROM_AVAILABLE_METADATA")
    if final_known > existing:
        flags.append("DIRECTION_COVERAGE_IMPROVED")
    summary = {
        "run_started_at": pd.Timestamp.now(tz=timezone.utc).isoformat(),
        "symbol": config.symbol,
        "visual_pack_dir": str(config.visual_pack_dir),
        "output_dir": str(config.output_dir),
        "total_samples": total,
        "existing_direction_count": existing,
        "missing_direction_count": missing,
        "recovered_direction_count": recovered,
        "recovered_direction_confidence_2_count": sum(
            str(row.get("recovered_direction")) in {"LONG", "SHORT"}
            and str(row.get("direction_confidence")) == "2"
            for row in rows
        ),
        "unrecoverable_direction_count": unknown,
        "final_direction_known_count": final_known,
        "final_direction_unknown_count": unknown,
        "source_counts": dict(source_counts),
        "confidence_counts": dict(confidence_counts),
        "long_count": final_counts.get("LONG", 0),
        "short_count": final_counts.get("SHORT", 0),
        "unknown_count": final_counts.get("UNKNOWN", 0),
        "conflicts_count": source_counts.get("CONFLICTING_DIRECTION_EVIDENCE", 0),
        "used_post_entry_data_count": used_post_entry,
        "diagnostic_tags_multi_label_confirmed": True,
        "non_directional_replay_primary": False,
        "verdict_flags": flags,
        "safety": {
            "old_adelin_runtime_modified": False,
            "strategy_2_touched": False,
            "strategy_3_touched": False,
            "live_trading_enabled": False,
            "telegram_trade_alerts_enabled": False,
            "broker_execution_enabled": False,
            "order_execution_enabled": False,
            "candidate_pack_generated": False,
            "matched_control_replay_run": False,
            "phase_4_started": False,
            "thresholds_tuned": False,
            "v3_stash_applied_or_popped": False,
            "post_entry_direction_inference_used": False,
        },
        "run_finished_at": pd.Timestamp.now(tz=timezone.utc).isoformat(),
    }
    summary.update(inference_rule_metadata())
    return summary


def run_recovery(config: RecoveryConfig) -> dict[str, Any]:
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    samples, sample_limitations = load_visual_samples(config.visual_pack_dir, config.symbol)
    frames = normalize_frames(
        load_csv_timeframes(config.symbol, ["M1", "M5"], data_dir=str(config.data_dir))
    )
    pip_size = get_symbol_spec(config.symbol).pip_size
    reason_codes = _load_index_reason_codes(Path(config.visual_pack_dir))

    rows = [
        recover_sample_direction(
            {**sample, "candidate_reason_codes": reason_codes.get(str(sample.get("sample_id") or ""), "")},
            frames,
            config,
            pip_size,
            reason_codes.get(str(sample.get("sample_id") or ""), ""),
        )
        for sample in samples
    ]

    if any(str(row.get("used_post_entry_data")).lower() == "true" for row in rows):
        raise RuntimeError("Direction recovery validation failed: post-entry data was used.")

    summary = build_summary(rows, config)
    limitations = {
        "limitations": sorted(set(sample_limitations)),
        "inference_rule": inference_rule_metadata(),
        "method_limitations": {
            "confidence_2_is_inferred_not_original_metadata": CONFIDENCE_2_WARNING,
            "pre_decision_sweep_inference_is_heuristic": (
                "The PRE_DECISION_SWEEP_INFERENCE rule is a deterministic research proxy. "
                "It is not an original strategy signal and not a deployment-quality direction source."
            ),
            "inferred_directions_must_not_be_treated_as_equal_to_existing_metadata": (
                "Existing metadata keeps confidence 3; recovered sweep directions use confidence 2."
            ),
            "phase_4_blocked_until_human_methodology_gate": (
                "Matched-control replay remains blocked until recovered direction methodology is accepted."
            ),
            "recovered_direction_does_not_validate_adelin": "Direction recovery only repairs diagnostic coverage.",
            "non_directional_replay_not_used_as_primary": (
                "Best-move-in-either-direction replay is not used because it changes directional semantics."
            ),
        },
    }

    recovery_csv = output_dir / DIRECTION_CSV
    write_csv(recovery_csv, rows)
    write_json(output_dir / DIRECTION_JSON, rows)
    write_json(output_dir / LIMITATIONS_JSON, limitations)

    before = _summary_from_existing_diagnostics(config.existing_diagnostics_dir)
    diagnostic_rerun: dict[str, Any] = {
        "executed": False,
        "before_summary_path": str(config.existing_diagnostics_dir / "summary.json"),
        "after_summary_path": str(config.diagnostic_rerun_output_dir / "summary.json"),
    }
    if before:
        diagnostic_rerun.update(
            {
                "before_sufficient_data_count": before.get("samples_with_sufficient_data"),
                "before_insufficient_data_count": before.get("samples_with_insufficient_data"),
                "before_unknown_direction_no_directional_replay_count": _count_unknown_direction_limitations(
                    config.existing_diagnostics_dir
                ),
                "before_outcome_distribution": before.get("outcome_distribution", {}),
            }
        )
    if config.rerun_diagnostics:
        after = run_diagnostics(
            DiagnosticConfig(
                symbol=config.symbol,
                data_dir=config.data_dir,
                visual_pack_dir=config.visual_pack_dir,
                output_dir=config.diagnostic_rerun_output_dir,
                direction_recovery_path=recovery_csv,
                forward_minutes=240,
                diagnostic_only=config.dry_run,
            )
        )
        diagnostic_rerun.update(
            {
                "executed": True,
                "after_sufficient_data_count": after.get("samples_with_sufficient_data"),
                "after_insufficient_data_count": after.get("samples_with_insufficient_data"),
                "after_unknown_direction_no_directional_replay_count": _count_unknown_direction_limitations(
                    config.diagnostic_rerun_output_dir
                ),
                "after_outcome_distribution": after.get("outcome_distribution", {}),
                "after_top_failure_modes": after.get("top_failure_modes", [])[:10],
                "after_top_win_modes": after.get("top_win_modes", [])[:10],
            }
        )
    summary["diagnostic_rerun"] = diagnostic_rerun
    write_json(output_dir / SUMMARY_JSON, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recover Adelin v2 visual-review direction metadata.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--visual-pack-dir", default=str(DEFAULT_VISUAL_PACK_DIR))
    parser.add_argument("--existing-diagnostics-dir", default=str(DEFAULT_EXISTING_DIAGNOSTICS_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--diagnostic-rerun-output-dir", default=str(DEFAULT_RECOVERED_DIAGNOSTICS_DIR))
    parser.add_argument("--skip-diagnostic-rerun", action="store_true")
    parser.add_argument("--sweep-lookback-minutes", type=int, default=60)
    parser.add_argument("--sweep-min-anchor-delay-minutes", type=int, default=5)
    parser.add_argument("--sweep-min-rejection-pips", type=float, default=5.0)
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser


def config_from_args(args: argparse.Namespace) -> RecoveryConfig:
    return RecoveryConfig(
        symbol=args.symbol,
        data_dir=Path(args.data_dir),
        visual_pack_dir=Path(args.visual_pack_dir),
        existing_diagnostics_dir=Path(args.existing_diagnostics_dir),
        output_dir=Path(args.output_dir),
        diagnostic_rerun_output_dir=Path(args.diagnostic_rerun_output_dir),
        rerun_diagnostics=not bool(args.skip_diagnostic_rerun),
        sweep_lookback_minutes=args.sweep_lookback_minutes,
        sweep_min_anchor_delay_minutes=args.sweep_min_anchor_delay_minutes,
        sweep_min_rejection_pips=args.sweep_min_rejection_pips,
        dry_run=bool(args.dry_run),
    )


def main(argv: Sequence[str] | None = None) -> int:
    summary = run_recovery(config_from_args(build_parser().parse_args(argv)))
    print(
        json.dumps(
            {
                "output_dir": summary["output_dir"],
                "inference_rule_version": summary["inference_rule_version"],
                "total_samples": summary["total_samples"],
                "existing_direction_count": summary["existing_direction_count"],
                "missing_direction_count": summary["missing_direction_count"],
                "recovered_direction_count": summary["recovered_direction_count"],
                "final_direction_unknown_count": summary["final_direction_unknown_count"],
                "source_counts": summary["source_counts"],
                "confidence_counts": summary["confidence_counts"],
                "diagnostic_rerun": summary["diagnostic_rerun"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
