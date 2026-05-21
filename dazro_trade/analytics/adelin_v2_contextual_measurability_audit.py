"""Research-only Adelin v2 contextual measurability audit.

This module defines a static concept matrix for deciding which discretionary
Adelin concepts can become deterministic pre-entry metrics. It intentionally
does not import strategy runtime, broker, MT5, Telegram, or order code.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


MEASURABLE_NOW = "MEASURABLE_NOW"
MEASURABLE_WITH_NEW_DATA = "MEASURABLE_WITH_NEW_DATA"
HEURISTIC_ONLY = "HEURISTIC_ONLY"
DISCRETIONARY_ONLY = "DISCRETIONARY_ONLY"
NOT_RELIABLY_MEASURABLE = "NOT_RELIABLY_MEASURABLE"

VALID_CATEGORIES = {
    MEASURABLE_NOW,
    MEASURABLE_WITH_NEW_DATA,
    HEURISTIC_ONLY,
    DISCRETIONARY_ONLY,
    NOT_RELIABLY_MEASURABLE,
}

VALID_RISKS = {"LOW", "MEDIUM", "HIGH"}

VERDICT_FLAGS = [
    "ADELIN_REMAINS_RESEARCH_ONLY",
    "NO_LIVE_DEPLOYMENT_DECISION",
    "NO_BACKTEST_RUN",
    "NO_RUNTIME_LOGIC_CHANGE",
    "CONTINUATION_POSITIVE_FEATURE_BANNED",
    "CONTEXTUAL_MEASURABILITY_AUDIT_COMPLETE",
]

OUTPUT_DIR = Path("backtests/reports/adelin_v2_contextual_measurability_audit")


@dataclass(frozen=True)
class ConceptAuditRow:
    concept_name: str
    category: str
    deterministic_definition_candidate: str
    pre_entry_available: bool
    required_timeframes: tuple[str, ...]
    required_data: tuple[str, ...]
    requires_tick_data: bool
    requires_real_volume: bool
    leakage_risk: str
    subjectivity_risk: str
    expected_failure_modes: str
    possible_metric_formula: str
    minimum_sample_size_for_future_test: int
    future_validation_method: str
    notes: str

    def to_csv_row(self) -> dict[str, str | int | bool]:
        row = asdict(self)
        row["required_timeframes"] = "|".join(self.required_timeframes)
        row["required_data"] = "|".join(self.required_data)
        return row


REQUIRED_FIELDS = tuple(ConceptAuditRow.__dataclass_fields__.keys())


def _row(
    concept_name: str,
    category: str,
    deterministic_definition_candidate: str,
    pre_entry_available: bool,
    required_timeframes: Sequence[str],
    required_data: Sequence[str],
    requires_tick_data: bool,
    requires_real_volume: bool,
    leakage_risk: str,
    subjectivity_risk: str,
    expected_failure_modes: str,
    possible_metric_formula: str,
    minimum_sample_size_for_future_test: int,
    future_validation_method: str,
    notes: str,
) -> ConceptAuditRow:
    return ConceptAuditRow(
        concept_name=concept_name,
        category=category,
        deterministic_definition_candidate=deterministic_definition_candidate,
        pre_entry_available=pre_entry_available,
        required_timeframes=tuple(required_timeframes),
        required_data=tuple(required_data),
        requires_tick_data=requires_tick_data,
        requires_real_volume=requires_real_volume,
        leakage_risk=leakage_risk,
        subjectivity_risk=subjectivity_risk,
        expected_failure_modes=expected_failure_modes,
        possible_metric_formula=possible_metric_formula,
        minimum_sample_size_for_future_test=minimum_sample_size_for_future_test,
        future_validation_method=future_validation_method,
        notes=notes,
    )


CONCEPT_MATRIX: tuple[ConceptAuditRow, ...] = (
    _row(
        "HTF liquidity",
        HEURISTIC_ONLY,
        "Pre-anchor D1/H4/H1 swing highs/lows with age and untouched-state rules.",
        True,
        ("D1", "H4", "H1"),
        ("OHLC candles",),
        False,
        False,
        "MEDIUM",
        "HIGH",
        "Swing definitions can overfit; liquidity relevance depends on range structure and discretionary importance.",
        "aged_swing_level_exists and not pre_anchor_taken",
        300,
        "Pre-register swing rules, then test with temporal split and OOS replay.",
        "Measurable only as a proxy; human liquidity importance is richer than a swing rule.",
    ),
    _row(
        "LTF liquidity",
        HEURISTIC_ONLY,
        "Pre-anchor M15/M5/M1 local swing points and recent range extremes.",
        True,
        ("M15", "M5", "M1"),
        ("OHLC candles",),
        False,
        False,
        "MEDIUM",
        "MEDIUM",
        "Short lookbacks create noisy micro-swings; same event can be counted repeatedly.",
        "local_swing_count_near_anchor / recent_range_width",
        300,
        "Pre-register lookback and spacing; compare against matched controls.",
        "Useful for context, but not sufficient as a standalone Adelin feature.",
    ),
    _row(
        "internal liquidity",
        HEURISTIC_ONLY,
        "Swing point inside a higher-timeframe range whose outer high/low remains untaken before anchor.",
        True,
        ("H4", "H1", "M15"),
        ("OHLC candles", "range state"),
        False,
        False,
        "MEDIUM",
        "HIGH",
        "Range boundaries are subjective; naive definitions can leak if future range completion is used.",
        "swing_inside_pre_anchor_range and range_extremes_not_taken",
        300,
        "Freeze range construction rules before any outcome replay.",
        "Must use only already formed ranges, never future range boundaries.",
    ),
    _row(
        "external liquidity",
        HEURISTIC_ONLY,
        "Swing point outside the recent pre-anchor range using a fixed lookback window.",
        True,
        ("H1", "M15", "M5", "M1"),
        ("OHLC candles", "range state"),
        False,
        False,
        "MEDIUM",
        "MEDIUM",
        "External classification changes with lookback; shallow external levels can be low quality.",
        "swing_high > max(previous_n_highs) or swing_low < min(previous_n_lows)",
        300,
        "Test only after fixed lookback and depth gates are registered.",
        "Should be a context feature, not an entry trigger by itself.",
    ),
    _row(
        "H1 liquidity sweep",
        MEASURABLE_NOW,
        "An H1 swing high/low is taken by pre-anchor candles and closes back inside or stalls beyond it.",
        True,
        ("H1", "M15", "M5"),
        ("OHLC candles",),
        False,
        False,
        "LOW",
        "MEDIUM",
        "Close-back and stall definitions can be tuned; wick-only sweeps can be over-counted.",
        "sweep_distance_pips and close_back_flag before anchor",
        300,
        "Temporal split with source/session matched controls.",
        "Measurable now, but old simple sweep evidence is not sufficient for deployability.",
    ),
    _row(
        "M15 sequence validity",
        HEURISTIC_ONLY,
        "Ordered pre-anchor M15 structure: approach, sweep, displacement or stall.",
        True,
        ("M15", "M5"),
        ("OHLC candles",),
        False,
        False,
        "MEDIUM",
        "HIGH",
        "Sequence grammar can become discretionary or tuned to outcomes.",
        "ordered_event_flags = approach_then_sweep_then_reaction_zone_touch",
        300,
        "Use locked grammar and visual spot-checking before replay.",
        "Requires strict anti-leakage because post-entry reaction is tempting to include.",
    ),
    _row(
        "FVG",
        MEASURABLE_NOW,
        "Three-candle imbalance with gap between candle 1 and candle 3 on a fixed timeframe.",
        True,
        ("M5", "M15"),
        ("OHLC candles",),
        False,
        False,
        "LOW",
        "MEDIUM",
        "Mitigation rules and gap-size thresholds can be overfit.",
        "bullish: low_c3 > high_c1; bearish: high_c3 < low_c1; gap_size_pips >= threshold",
        300,
        "Pre-register timeframe, min gap, mitigation state, and replay split.",
        "Deterministic if timeframe and mitigation rules are locked.",
    ),
    _row(
        "IFVG",
        MEASURABLE_NOW,
        "Previously formed FVG that is mitigated pre-anchor and retested from the opposite side pre-anchor.",
        True,
        ("M5", "M15"),
        ("OHLC candles",),
        False,
        False,
        "MEDIUM",
        "MEDIUM",
        "Retest quality can become subjective; anchor-candle-only retests are leakage-prone.",
        "fvg_exists and mitigated_before_anchor and last_completed_candle_touches_zone",
        300,
        "Use completed pre-anchor candles only; run OOS replay after fixed definition.",
        "Measurable, but stricter than generic FVG and easy to mislabel if anchor candle is used.",
    ),
    _row(
        "volume profile",
        MEASURABLE_WITH_NEW_DATA,
        "Rolling pre-anchor volume-at-price profile with HVN/LVN bins.",
        True,
        ("M5", "M1"),
        ("tick volume", "volume-at-price bins or approximated candle volume"),
        True,
        True,
        "MEDIUM",
        "HIGH",
        "Broker tick volume may not represent real volume; bin size and lookback change labels.",
        "rolling_24h_volume_by_price_bin with HVN/LVN quantiles",
        300,
        "Validate with fixed binning and broker-data sensitivity checks.",
        "Needs better volume data before it should carry much weight.",
    ),
    _row(
        "volume cracks",
        MEASURABLE_WITH_NEW_DATA,
        "Pre-anchor candle with exceptional volume and body dominance breaking through a level.",
        True,
        ("M5", "M1"),
        ("OHLC candles", "tick or real volume"),
        True,
        True,
        "MEDIUM",
        "MEDIUM",
        "Volume source quality varies; large candles during news may distort interpretation.",
        "volume >= 2.5 * rolling_volume_avg and body / range >= 0.70",
        300,
        "Register volume source and compare against news/session buckets.",
        "Potentially measurable, but only after volume data quality is audited.",
    ),
    _row(
        "number theory",
        MEASURABLE_NOW,
        "Distance from swept or reaction level to round-number prices ending in 0.",
        True,
        ("M1", "M5", "M15", "H1"),
        ("OHLC candles", "price levels"),
        False,
        False,
        "LOW",
        "LOW",
        "Can be over-weighted despite being only confluence; too many nearby levels reduce selectivity.",
        "abs(level - nearest_round_ending_0) / pip_size <= threshold",
        300,
        "Test only as pre-registered confluence, not as standalone signal.",
        "Measurable now, but must never be treated as sufficient by itself.",
    ),
    _row(
        "round levels",
        MEASURABLE_NOW,
        "Static price grid where significant digits end in zero, measured by distance to candidate level.",
        True,
        ("M1", "M5", "M15", "H1"),
        ("price levels",),
        False,
        False,
        "LOW",
        "LOW",
        "Threshold choice can inflate matches; grid alone has no edge evidence.",
        "nearest_round_level and distance_pips",
        300,
        "Use source-matched controls around the same grid.",
        "Round levels are context only, not entry evidence.",
    ),
    _row(
        "reaction zones",
        HEURISTIC_ONLY,
        "Pre-anchor confluence zone from FVG, IFVG, volume crack, profile, or old rejection definitions.",
        True,
        ("M15", "M5", "M1"),
        ("OHLC candles", "optional volume", "optional volume profile"),
        True,
        True,
        "MEDIUM",
        "HIGH",
        "Zone boundaries and age rules can become discretionary; overlap logic can be tuned.",
        "union_of_registered_zone_types within max_distance_pips of swept_level",
        300,
        "Validate each zone subtype separately before using composite labels.",
        "The concept is central to Adelin, but only proxy-zone definitions are objectively measurable.",
    ),
    _row(
        "rejection quality",
        HEURISTIC_ONLY,
        "Pre-entry wick/body and close-location behavior at a level before anchor.",
        True,
        ("M5", "M1"),
        ("OHLC candles",),
        False,
        False,
        "MEDIUM",
        "HIGH",
        "Humans judge rejection with context; wick ratios alone misread news and spread artifacts.",
        "wick_ratio, close_location_value, rejection_candle_range_pips",
        300,
        "Use locked candle morphology features plus manual review calibration.",
        "Potential feature, but previous rejection subset was not robust OOS.",
    ),
    _row(
        "reclaim quality",
        HEURISTIC_ONLY,
        "Pre-anchor close back above/below swept level after taking liquidity.",
        True,
        ("M5", "M1"),
        ("OHLC candles",),
        False,
        False,
        "MEDIUM",
        "MEDIUM",
        "Waiting for reclaim can change the intended early-entry idea; late reclaim may be post-entry confirmation.",
        "close_back_distance_pips and candles_since_sweep",
        300,
        "Register whether reclaim is context-only or a separate late-entry hypothesis.",
        "Useful for risk tagging, but may conflict with Adelin's no-full-confirmation entry concept.",
    ),
    _row(
        "accumulation before expansion",
        HEURISTIC_ONLY,
        "Pre-anchor narrow range around a level for a fixed number of candles before directional expansion.",
        True,
        ("M5", "M1"),
        ("OHLC candles",),
        False,
        False,
        "HIGH",
        "HIGH",
        "Expansion is often known only after anchor; pre-entry accumulation definitions can leak.",
        "pre_anchor_range_pips <= threshold over n candles",
        300,
        "Separate pre-anchor compression from post-anchor expansion outcome.",
        "Only the accumulation part is pre-entry; expansion must be measured later.",
    ),
    _row(
        "immediate expansion",
        NOT_RELIABLY_MEASURABLE,
        "Post-entry movement speed after anchor, measured as an outcome rather than a pre-entry feature.",
        False,
        ("M5", "M1"),
        ("OHLC candles",),
        False,
        False,
        "HIGH",
        "LOW",
        "Using this before entry would be direct leakage; it is valid only as replay outcome.",
        "mfe_pips_within_5_15_30_minutes",
        100,
        "Measure only in forward replay after pre-registered entry hypothesis.",
        "Outcome metric, not a valid pre-entry feature.",
    ),
    _row(
        "runner expansion",
        NOT_RELIABLY_MEASURABLE,
        "Large favorable movement after entry, treated only as replay outcome.",
        False,
        ("M5", "M1", "H1"),
        ("OHLC candles",),
        False,
        False,
        "HIGH",
        "LOW",
        "Cannot be known pre-entry; long windows can overstate quality on XAUUSD.",
        "max_favorable_pips within fixed forward window",
        100,
        "Measure with capped forward replay and matched controls.",
        "Never use as an entry filter.",
    ),
    _row(
        "wick/body behavior",
        MEASURABLE_NOW,
        "Pre-anchor candle morphology: wick ratios, body ratio, close location, and range.",
        True,
        ("M5", "M1"),
        ("OHLC candles",),
        False,
        False,
        "LOW",
        "MEDIUM",
        "Morphology ignores context and spread; thresholds can be tuned.",
        "body/range, upper_wick/range, lower_wick/range, close_location_value",
        300,
        "Use fixed feature bins and OOS profile comparison.",
        "Measurable, but should be contextual metadata rather than standalone signal.",
    ),
    _row(
        "displacement",
        MEASURABLE_NOW,
        "Large pre-anchor candle or sequence with body and range above rolling baseline.",
        True,
        ("M5", "M1"),
        ("OHLC candles",),
        False,
        False,
        "LOW",
        "MEDIUM",
        "Large news candles can look like displacement; baseline choice matters.",
        "range_pips / rolling_median_range and body_ratio",
        300,
        "Temporal split by session and volatility regime.",
        "Measurable now as a candle feature.",
    ),
    _row(
        "compression before expansion",
        HEURISTIC_ONLY,
        "Pre-anchor decline in range/ATR before a candidate level interaction.",
        True,
        ("M15", "M5", "M1"),
        ("OHLC candles",),
        False,
        False,
        "MEDIUM",
        "MEDIUM",
        "Expansion half of the phrase is post-anchor; compression thresholds are regime-sensitive.",
        "rolling_range_percentile <= threshold before anchor",
        300,
        "Use only pre-anchor compression; test outcomes separately.",
        "Useful as regime/context metadata, not proof of setup quality.",
    ),
    _row(
        "time-of-day context",
        MEASURABLE_NOW,
        "Anchor timestamp bucketed by UTC/local hour.",
        True,
        ("timestamp",),
        ("timestamps",),
        False,
        False,
        "LOW",
        "LOW",
        "DST/session calendar mistakes can misbucket events.",
        "hour_bucket(anchor_timestamp_utc)",
        100,
        "Compare metrics by fixed hour buckets.",
        "Measurable now and safe as metadata.",
    ),
    _row(
        "session context",
        MEASURABLE_NOW,
        "Anchor timestamp mapped to Asia, London, New York, opens, or other.",
        True,
        ("timestamp",),
        ("timestamps", "session calendar"),
        False,
        False,
        "LOW",
        "LOW",
        "DST and broker-time conversion mistakes can create false session effects.",
        "session_bucket(anchor_timestamp_utc)",
        100,
        "Use session-matched controls.",
        "Measurable now and required for fair baseline comparison.",
    ),
    _row(
        "multi-timeframe alignment",
        HEURISTIC_ONLY,
        "Distance and directional agreement among pre-anchor HTF and LTF levels.",
        True,
        ("D1", "H4", "H1", "M15", "M5", "M1"),
        ("OHLC candles", "derived swing levels"),
        False,
        False,
        "MEDIUM",
        "HIGH",
        "Alignment can be made too broad; level source mismatch can create false positives.",
        "min_distance_between_htf_ltf_levels_pips <= threshold and direction_agrees",
        300,
        "Pre-register source hierarchy and distance thresholds.",
        "Composite alignment is promising only if all sub-definitions are locked first.",
    ),
    _row(
        "candle close quality",
        HEURISTIC_ONLY,
        "Pre-anchor close location relative to swept level, zone edge, and candle range.",
        True,
        ("M5", "M1"),
        ("OHLC candles",),
        False,
        False,
        "MEDIUM",
        "HIGH",
        "Close quality is often judged visually; late confirmation may conflict with early entry.",
        "close_location_value and close_relative_to_level_pips",
        300,
        "Lock whether close quality is context-only or an entry gate.",
        "Measurable as proxy, but subjective as a discretionary phrase.",
    ),
    _row(
        "continuation behavior",
        NOT_RELIABLY_MEASURABLE,
        "Continuation patterns after old Adelin signals are tracked only as risk/negative context.",
        False,
        ("M5", "M1"),
        ("OHLC candles", "old signal exports if audited"),
        False,
        False,
        "HIGH",
        "HIGH",
        "Old continuation behavior was toxic; positive use invites selection bias and strategy drift.",
        "negative_risk_flag_only; no positive feature score",
        300,
        "If studied, test as a banned/blocked risk label, never as positive feature.",
        "BANNED_AS_POSITIVE_FEATURE; may only be reframed as risk or no-trade context.",
    ),
    _row(
        "failed continuation",
        HEURISTIC_ONLY,
        "Pre-anchor failed attempt to continue toward target after liquidity was taken.",
        True,
        ("M15", "M5", "M1"),
        ("OHLC candles", "derived liquidity targets"),
        False,
        False,
        "MEDIUM",
        "HIGH",
        "Failure is hard to know before the move has played out; target definition can leak.",
        "attempted_target_move_then_rejection_before_anchor",
        300,
        "Use only completed pre-anchor failure structure and matched controls.",
        "Can be a reversal-risk context, not evidence for generic continuation.",
    ),
    _row(
        "volatility regime",
        MEASURABLE_NOW,
        "Pre-anchor ATR/range percentile bucket using only completed candles.",
        True,
        ("D1", "H1", "M15"),
        ("OHLC candles",),
        False,
        False,
        "LOW",
        "LOW",
        "Small samples can collapse in one regime; ATR lookback must be fixed.",
        "pre_anchor_atr_percentile_bucket",
        100,
        "Require no single regime bucket collapse in OOS validation.",
        "Measurable now and important for stratification.",
    ),
    _row(
        "trend/range regime",
        HEURISTIC_ONLY,
        "Pre-anchor directional slope and range compression/expansion state.",
        True,
        ("H4", "H1", "M15"),
        ("OHLC candles",),
        False,
        False,
        "MEDIUM",
        "MEDIUM",
        "Trend/range definitions vary and can overfit; regime labels can lag.",
        "adx_proxy, ma_slope, range_width_percentile",
        300,
        "Freeze regime definition and report performance by regime bucket.",
        "Measurable as a proxy, but not a discretionary truth label.",
    ),
)


def category_summary(rows: Iterable[ConceptAuditRow] = CONCEPT_MATRIX) -> dict[str, int]:
    counts = Counter(row.category for row in rows)
    return {category: counts.get(category, 0) for category in sorted(VALID_CATEGORIES)}


def validate_concept_matrix(rows: Sequence[ConceptAuditRow] = CONCEPT_MATRIX) -> None:
    if not rows:
        raise ValueError("Concept matrix is empty")

    names: set[str] = set()
    for row in rows:
        if row.concept_name in names:
            raise ValueError(f"Duplicate concept_name: {row.concept_name}")
        names.add(row.concept_name)

        if row.category not in VALID_CATEGORIES:
            raise ValueError(f"{row.concept_name}: invalid category {row.category}")
        if row.leakage_risk not in VALID_RISKS:
            raise ValueError(f"{row.concept_name}: invalid leakage risk {row.leakage_risk}")
        if row.subjectivity_risk not in VALID_RISKS:
            raise ValueError(
                f"{row.concept_name}: invalid subjectivity risk {row.subjectivity_risk}"
            )

        for field_name in REQUIRED_FIELDS:
            value = getattr(row, field_name)
            if value is None or value == "" or value == ():
                raise ValueError(f"{row.concept_name}: missing {field_name}")

    continuation_rows = [row for row in rows if row.concept_name == "continuation behavior"]
    if len(continuation_rows) != 1:
        raise ValueError("Exactly one continuation behavior row is required")
    continuation = continuation_rows[0]
    if continuation.category == MEASURABLE_NOW:
        raise ValueError("Continuation behavior must not be classified as a positive feature")
    if "BANNED_AS_POSITIVE_FEATURE" not in continuation.notes:
        raise ValueError("Continuation behavior must be explicitly banned as a positive feature")


def concept_matrix_as_json(rows: Sequence[ConceptAuditRow] = CONCEPT_MATRIX) -> dict[str, object]:
    validate_concept_matrix(rows)
    return {
        "audit_type": "ADELIN_V2_CONTEXTUAL_MEASURABILITY_AUDIT",
        "verdict_flags": VERDICT_FLAGS,
        "category_summary": category_summary(rows),
        "concept_count": len(rows),
        "concepts": [asdict(row) for row in rows],
        "safety": {
            "live_trading_enabled": False,
            "telegram_trade_alerts_enabled": False,
            "broker_execution_enabled": False,
            "order_execution_enabled": False,
            "strategy_2_touched": False,
            "strategy_3_touched": False,
            "adelin_runtime_logic_modified": False,
            "backtest_run": False,
            "data_modified": False,
        },
    }


def write_concept_matrix(output_dir: Path | str = OUTPUT_DIR) -> dict[str, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    csv_path = output_path / "concept_matrix.csv"
    json_path = output_path / "concept_matrix.json"

    validate_concept_matrix(CONCEPT_MATRIX)
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=REQUIRED_FIELDS)
        writer.writeheader()
        for row in CONCEPT_MATRIX:
            writer.writerow(row.to_csv_row())

    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(concept_matrix_as_json(CONCEPT_MATRIX), json_file, indent=2)
        json_file.write("\n")

    return {"csv": csv_path, "json": json_path}


def main() -> None:
    paths = write_concept_matrix()
    print(f"Wrote {paths['csv']}")
    print(f"Wrote {paths['json']}")


if __name__ == "__main__":
    main()
