"""Research-only Adelin v2 operational audit labels.

This module intentionally contains no broker, Telegram, MT5, or live strategy
imports. It classifies already exported historical trade rows against the
Adelin v2 operational specification using only fields present in those rows.
Missing context remains unknown; the audit must not invent liquidity, reaction,
news, or execution quality evidence.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class AdelinV2SetupClass(str, Enum):
    A_PLUS_REVERSAL = "A_PLUS_REVERSAL"
    VALID_REVERSAL = "VALID_REVERSAL"
    DIRTY_REVERSAL = "DIRTY_REVERSAL"
    NO_TRADE_TOO_SHALLOW = "NO_TRADE_TOO_SHALLOW"
    NO_TRADE_GAP_CONTAMINATION = "NO_TRADE_GAP_CONTAMINATION"
    NO_TRADE_FRESH_REJECTION = "NO_TRADE_FRESH_REJECTION"
    NO_TRADE_NO_REACTION_ZONE = "NO_TRADE_NO_REACTION_ZONE"
    NO_TRADE_NO_TARGET_LIQUIDITY = "NO_TRADE_NO_TARGET_LIQUIDITY"
    NO_TRADE_CONTINUATION_BLOCKED = "NO_TRADE_CONTINUATION_BLOCKED"
    NO_TRADE_SL_TOO_WIDE = "NO_TRADE_SL_TOO_WIDE"
    CONTINUATION_RARE_IFVG_CANDIDATE = "CONTINUATION_RARE_IFVG_CANDIDATE"
    UNKNOWN_INSUFFICIENT_DATA = "UNKNOWN_INSUFFICIENT_DATA"


class AdelinV2LiquidityClass(str, Enum):
    HTF_EXTERNAL = "HTF_EXTERNAL"
    HTF_INTERNAL = "HTF_INTERNAL"
    LTF_EXTERNAL = "LTF_EXTERNAL"
    LTF_INTERNAL = "LTF_INTERNAL"
    MULTI_TF_ALIGNED = "MULTI_TF_ALIGNED"
    SHALLOW_INTERNAL = "SHALLOW_INTERNAL"
    DEEP_VALID = "DEEP_VALID"
    ALREADY_CONSUMED = "ALREADY_CONSUMED"
    UNCOLLECTED_TARGET = "UNCOLLECTED_TARGET"
    UNKNOWN = "UNKNOWN"


class AdelinV2ReactionZoneType(str, Enum):
    FVG = "FVG"
    IFVG = "IFVG"
    VOLUME_CRACK = "VOLUME_CRACK"
    VOLUME_PROFILE_SWING = "VOLUME_PROFILE_SWING"
    OLD_REJECTION = "OLD_REJECTION"
    OLD_RANGE_REJECTION = "OLD_RANGE_REJECTION"
    NUMBER_THEORY = "NUMBER_THEORY"
    FRESH_REJECTION_INVALID = "FRESH_REJECTION_INVALID"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


class AdelinV2ManagementFlag(str, Enum):
    MOVE_TO_BE_AFTER_STRONG_REACTION = "MOVE_TO_BE_AFTER_STRONG_REACTION"
    EARLY_CLOSE_ACCUMULATION = "EARLY_CLOSE_ACCUMULATION"
    EARLY_CLOSE_M1_ENGULFING_AGAINST = "EARLY_CLOSE_M1_ENGULFING_AGAINST"
    HOLD_RUNNER_TO_TARGET_LIQUIDITY = "HOLD_RUNNER_TO_TARGET_LIQUIDITY"
    PARTIAL_ALLOWED_ONLY_1_LOT_PLUS = "PARTIAL_ALLOWED_ONLY_1_LOT_PLUS"
    NEWS_TAGGED_HIGH_RISK = "NEWS_TAGGED_HIGH_RISK"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AdelinV2AuditConfig:
    symbol: str = "XAUUSD"
    pip_size: float | None = None
    normal_sl_pips: float = 20.0
    max_sl_pips: float = 40.0
    number_theory_threshold_pips: float = 5.0


@dataclass(frozen=True)
class AdelinV2DiagnosticRecord:
    symbol: str
    trade_id: str | None = None
    signal_timestamp: datetime | None = None
    entry_timestamp: datetime | None = None
    direction: str | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    old_strategy_name: str | None = None
    old_score: float | None = None
    old_setup_mode: str | None = None
    old_continuation_flag: bool | None = None
    old_rejection_flag: bool | None = None
    liquidity_timeframes_available: tuple[str, ...] = ()
    htf_liquidity_class: AdelinV2LiquidityClass = AdelinV2LiquidityClass.UNKNOWN
    ltf_liquidity_class: AdelinV2LiquidityClass = AdelinV2LiquidityClass.UNKNOWN
    multi_tf_alignment: bool | None = None
    reaction_zone_type: AdelinV2ReactionZoneType = AdelinV2ReactionZoneType.UNKNOWN
    reaction_zone_age_minutes: float | None = None
    reaction_zone_is_fresh_invalid: bool | None = None
    number_theory_confluence: bool | None = None
    nearest_number_theory_level: float | None = None
    distance_to_number_level_pips: float | None = None
    volume_profile_context_available: bool | None = None
    volume_crack_detected: bool | None = None
    gap_contamination_flag: bool | None = None
    asian_open_gap_flag: bool | None = None
    weekly_open_gap_flag: bool | None = None
    required_sl_pips: float | None = None
    sl_within_20_pips: bool | None = None
    sl_within_40_pips: bool | None = None
    target_liquidity_available: bool | None = None
    next_reaction_zone_available: bool | None = None
    continuation_blocked: bool = False
    rare_ifvg_continuation_candidate: bool | None = None
    post_entry_reaction_available: bool | None = None
    post_entry_immediate_reaction_pips: float | None = None
    post_entry_accumulation_flag: bool | None = None
    post_entry_m1_engulfing_against: bool | None = None
    management_flags: tuple[AdelinV2ManagementFlag, ...] = ()
    final_adelin_v2_label: AdelinV2SetupClass = AdelinV2SetupClass.UNKNOWN_INSUFFICIENT_DATA
    reason_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


STRATEGY_COLUMNS = (
    "strategy",
    "strategy_name",
    "old_strategy_name",
    "source_strategy",
    "signal_strategy",
    "module",
)
TRADE_ID_COLUMNS = ("trade_id", "id", "ticket", "order_id", "position_id")
SIGNAL_TIMESTAMP_COLUMNS = (
    "signal_timestamp",
    "nearest_signal_timestamp",
    "timestamp",
    "time",
    "open_time",
)
ENTRY_TIMESTAMP_COLUMNS = ("entry_timestamp", "entry_time", "fill_time", "opened_at")
ENTRY_PRICE_COLUMNS = ("entry_price", "entry", "open_price", "price", "current_price")
STOP_LOSS_COLUMNS = ("stop_loss", "sl", "stop", "stop_price")
TAKE_PROFIT_COLUMNS = ("take_profit", "tp", "tp1", "target", "target_price")
SCORE_COLUMNS = ("old_score", "score", "signal_score", "nearest_signal_score")
SETUP_MODE_COLUMNS = ("old_setup_mode", "setup_mode", "mode", "signal_mode")
CONTINUATION_COLUMNS = (
    "old_continuation_flag",
    "continuation",
    "continuation_flag",
    "continuation_candidate",
    "feature_continuation_candidate",
    "is_continuation",
)
REJECTION_COLUMNS = (
    "rejection",
    "rejection_flag",
    "rejection_candidate",
    "feature_rejection_candidate",
    "old_rejection_flag",
    "is_rejection",
)

CRITICAL_CONTEXT_LIMITATIONS = (
    "MISSING_HTF_LIQUIDITY_CONTEXT",
    "MISSING_LTF_LIQUIDITY_CONTEXT",
    "MISSING_REACTION_ZONE_CONTEXT",
    "MISSING_TARGET_LIQUIDITY_CONTEXT",
)


def pip_size_for_symbol(symbol: str) -> float:
    text = symbol.upper()
    if text == "XAUUSD":
        return 0.1
    if text.endswith("JPY"):
        return 0.01
    return 0.0001


def nearest_number_theory_level(price: float, *, level_step: float = 10.0) -> float:
    """Return the nearest whole-number level ending in 0, e.g. 4900/4910."""
    if level_step <= 0:
        raise ValueError("level_step must be positive")
    return math.floor(price / level_step + 0.5) * level_step


def number_theory_distance_pips(price: float, *, pip_size: float, level_step: float = 10.0) -> tuple[float, float]:
    level = nearest_number_theory_level(price, level_step=level_step)
    return level, round(abs(price - level) / pip_size, 4)


def _normalise_key(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _normalised_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {_normalise_key(str(k)): v for k, v in row.items()}


def _first(row: Mapping[str, Any], names: Sequence[str]) -> Any:
    normalised = _normalised_row(row)
    for name in names:
        key = _normalise_key(name)
        if key in normalised:
            return normalised[key]
    return None


def _has_any_field(row: Mapping[str, Any], names: Sequence[str]) -> bool:
    normalised = _normalised_row(row)
    return any(_normalise_key(name) in normalised for name in names)


def _parse_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return text


def _parse_bool(value: Any) -> bool | None:
    text = _parse_text(value)
    if text is None:
        return None
    lowered = text.lower()
    if lowered in {"true", "1", "yes", "y", "on"}:
        return True
    if lowered in {"false", "0", "no", "n", "off"}:
        return False
    return None


def _parse_float(value: Any) -> float | None:
    text = _parse_text(value)
    if text is None:
        return None
    try:
        out = float(text)
    except ValueError:
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _parse_datetime(value: Any) -> datetime | None:
    text = _parse_text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _enum_from_text(enum_type: type[Enum], value: Any, default: Enum) -> Enum:
    text = _parse_text(value)
    if text is None:
        return default
    normalised = text.upper().replace(" ", "_").replace("-", "_")
    for item in enum_type:
        if normalised == item.value or normalised == item.name:
            return item
    if "HTF" in normalised and "EXTERNAL" in normalised:
        return AdelinV2LiquidityClass.HTF_EXTERNAL
    if "HTF" in normalised and "INTERNAL" in normalised:
        return AdelinV2LiquidityClass.HTF_INTERNAL
    if "LTF" in normalised and "EXTERNAL" in normalised:
        return AdelinV2LiquidityClass.LTF_EXTERNAL
    if "LTF" in normalised and "INTERNAL" in normalised:
        return AdelinV2LiquidityClass.LTF_INTERNAL
    if "SHALLOW" in normalised:
        return AdelinV2LiquidityClass.SHALLOW_INTERNAL
    if "DEEP" in normalised:
        return AdelinV2LiquidityClass.DEEP_VALID
    if "IFVG" in normalised:
        return AdelinV2ReactionZoneType.IFVG
    if "FVG" in normalised:
        return AdelinV2ReactionZoneType.FVG
    if "VOLUME" in normalised and "CRACK" in normalised:
        return AdelinV2ReactionZoneType.VOLUME_CRACK
    if "PROFILE" in normalised or "SWING" in normalised:
        return AdelinV2ReactionZoneType.VOLUME_PROFILE_SWING
    if "OLD_RANGE" in normalised or ("RANGE" in normalised and "REJECTION" in normalised):
        return AdelinV2ReactionZoneType.OLD_RANGE_REJECTION
    if "FRESH" in normalised and "REJECTION" in normalised:
        return AdelinV2ReactionZoneType.FRESH_REJECTION_INVALID
    if "REJECTION" in normalised:
        return AdelinV2ReactionZoneType.OLD_REJECTION
    if "NUMBER" in normalised or "ROUND" in normalised:
        return AdelinV2ReactionZoneType.NUMBER_THEORY
    if normalised in {"NONE", "NO", "FALSE"}:
        return AdelinV2ReactionZoneType.NONE
    return default


def _parse_timeframes(value: Any) -> tuple[str, ...]:
    text = _parse_text(value)
    if text is None:
        return ()
    cleaned = text.replace("|", ",").replace(";", ",").replace("/", ",")
    return tuple(part.strip().upper() for part in cleaned.split(",") if part.strip())


def is_adelin_trade(row: Mapping[str, Any]) -> bool:
    strategy_bits = [
        _parse_text(_first(row, STRATEGY_COLUMNS)),
        _parse_text(_first(row, SETUP_MODE_COLUMNS)),
        _parse_text(_first(row, ("signal_name", "name", "source"))),
    ]
    text = " ".join(bit for bit in strategy_bits if bit).lower()
    if not text:
        return False
    if "strategy_2" in text or "strategy_3" in text:
        return False
    return "adelin" in text or "strategy_1_adelin" in text


def filter_adelin_trade_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """Filter mixed exports to old Adelin rows.

    If no strategy columns are present at all, the caller's explicit file is
    treated as Adelin-only and all rows are kept with a metadata limitation.
    """
    has_strategy_context = any(_has_any_field(row, STRATEGY_COLUMNS + SETUP_MODE_COLUMNS) for row in rows)
    if not has_strategy_context:
        return list(rows), {
            "filter_mode": "no_strategy_columns_assumed_explicit_adelin_export",
            "filter_limitation": "MISSING_STRATEGY_COLUMN",
        }
    return [row for row in rows if is_adelin_trade(row)], {
        "filter_mode": "filtered_strategy_1_adelin_rows",
        "filter_limitation": None,
    }


def _sl_pips(row: Mapping[str, Any], entry_price: float | None, stop_loss: float | None, pip_size: float) -> float | None:
    explicit = _first(
        row,
        (
            "required_sl_pips",
            "sl_pips",
            "stop_loss_pips",
            "risk_pips",
            "stop_distance_pips",
        ),
    )
    parsed = _parse_float(explicit)
    if parsed is not None:
        return abs(parsed)
    if entry_price is None or stop_loss is None:
        return None
    return round(abs(entry_price - stop_loss) / pip_size, 4)


def _infer_reaction_zone(row: Mapping[str, Any]) -> AdelinV2ReactionZoneType:
    explicit = _first(row, ("reaction_zone_type", "zone_type", "reaction_type", "v2_reaction_zone_type"))
    if explicit is not None:
        return _enum_from_text(AdelinV2ReactionZoneType, explicit, AdelinV2ReactionZoneType.UNKNOWN)  # type: ignore[return-value]
    if _parse_bool(_first(row, ("ifvg", "ifvg_created", "feature_ifvg_created", "ifvg_touched"))) is True:
        return AdelinV2ReactionZoneType.IFVG
    if _parse_bool(_first(row, ("fvg", "fvg_created", "feature_fvg_created", "fvg_touched"))) is True:
        return AdelinV2ReactionZoneType.FVG
    if _parse_bool(_first(row, ("volume_crack_detected", "volume_crack", "vp_crack"))) is True:
        return AdelinV2ReactionZoneType.VOLUME_CRACK
    if _parse_bool(_first(row, ("volume_profile_context_available", "vp_swing_level", "volume_profile_swing"))) is True:
        return AdelinV2ReactionZoneType.VOLUME_PROFILE_SWING
    if _parse_bool(_first(row, REJECTION_COLUMNS)) is True:
        return AdelinV2ReactionZoneType.OLD_REJECTION
    if _parse_bool(_first(row, ("reaction_zone_available", "has_reaction_zone"))) is False:
        return AdelinV2ReactionZoneType.NONE
    return AdelinV2ReactionZoneType.UNKNOWN


def _build_limitations(
    *,
    htf_liquidity_class: AdelinV2LiquidityClass,
    ltf_liquidity_class: AdelinV2LiquidityClass,
    reaction_zone_type: AdelinV2ReactionZoneType,
    target_liquidity_available: bool | None,
    gap_contamination_flag: bool | None,
    required_sl_pips: float | None,
    entry_price: float | None,
    post_entry_reaction_available: bool | None,
) -> list[str]:
    limitations: list[str] = []
    if htf_liquidity_class == AdelinV2LiquidityClass.UNKNOWN:
        limitations.append("MISSING_HTF_LIQUIDITY_CONTEXT")
    if ltf_liquidity_class == AdelinV2LiquidityClass.UNKNOWN:
        limitations.append("MISSING_LTF_LIQUIDITY_CONTEXT")
    if reaction_zone_type == AdelinV2ReactionZoneType.UNKNOWN:
        limitations.append("MISSING_REACTION_ZONE_CONTEXT")
    if target_liquidity_available is None:
        limitations.append("MISSING_TARGET_LIQUIDITY_CONTEXT")
    if gap_contamination_flag is None:
        limitations.append("MISSING_GAP_CONTEXT")
    if required_sl_pips is None:
        limitations.append("MISSING_STOP_DISTANCE_CONTEXT")
    if entry_price is None:
        limitations.append("MISSING_ENTRY_PRICE_FOR_NUMBER_THEORY")
    if post_entry_reaction_available is None:
        limitations.append("MISSING_POST_ENTRY_REACTION_CONTEXT")
    return limitations


def _classify(
    *,
    old_continuation_flag: bool | None,
    rare_ifvg_continuation_candidate: bool | None,
    gap_contamination_flag: bool | None,
    reaction_zone_is_fresh_invalid: bool | None,
    htf_liquidity_class: AdelinV2LiquidityClass,
    ltf_liquidity_class: AdelinV2LiquidityClass,
    reaction_zone_type: AdelinV2ReactionZoneType,
    target_liquidity_available: bool | None,
    next_reaction_zone_available: bool | None,
    required_sl_pips: float | None,
    max_sl_pips: float,
    old_rejection_flag: bool | None,
    old_score: float | None,
    limitations: Sequence[str],
) -> tuple[AdelinV2SetupClass, list[str]]:
    reasons: list[str] = []
    if old_score is not None:
        reasons.append("OLD_SCORE_NOT_PREDICTIVE")
    if old_continuation_flag is True:
        if rare_ifvg_continuation_candidate is True:
            reasons.append("RARE_IFVG_CONTINUATION_REQUIRES_FUTURE_RESEARCH")
            reasons.append("CONTINUATION_REMAINS_BLOCKED_FOR_ACTIVE_SIGNALS")
            return AdelinV2SetupClass.CONTINUATION_RARE_IFVG_CANDIDATE, reasons
        reasons.append("OLD_ADELIN_CONTINUATION_TOXIC_AND_BLOCKED")
        return AdelinV2SetupClass.NO_TRADE_CONTINUATION_BLOCKED, reasons
    if gap_contamination_flag is True:
        reasons.append("GAP_CONTAMINATION_BLOCKS_ADELIN_V2_RESEARCH_SETUP")
        return AdelinV2SetupClass.NO_TRADE_GAP_CONTAMINATION, reasons
    if reaction_zone_is_fresh_invalid is True:
        reasons.append("FRESH_REJECTION_ZONE_INVALID_FOR_ADELIN_V2")
        return AdelinV2SetupClass.NO_TRADE_FRESH_REJECTION, reasons
    if htf_liquidity_class == AdelinV2LiquidityClass.SHALLOW_INTERNAL or ltf_liquidity_class == AdelinV2LiquidityClass.SHALLOW_INTERNAL:
        reasons.append("SHALLOW_INTERNAL_LIQUIDITY_TRAP")
        return AdelinV2SetupClass.NO_TRADE_TOO_SHALLOW, reasons
    if reaction_zone_type == AdelinV2ReactionZoneType.NONE:
        reasons.append("NO_VALID_REACTION_ZONE_EXPORTED")
        return AdelinV2SetupClass.NO_TRADE_NO_REACTION_ZONE, reasons
    if target_liquidity_available is False and next_reaction_zone_available is False:
        reasons.append("NO_TARGET_LIQUIDITY_OR_NEXT_REACTION_ZONE_EXPORTED")
        return AdelinV2SetupClass.NO_TRADE_NO_TARGET_LIQUIDITY, reasons
    if required_sl_pips is not None and required_sl_pips > max_sl_pips:
        reasons.append("REQUIRED_SL_EXCEEDS_ADELIN_V2_MAX")
        return AdelinV2SetupClass.NO_TRADE_SL_TOO_WIDE, reasons
    if old_rejection_flag is True:
        reasons.append("VALID_REVERSAL_CANDIDATE_REQUIRES_VISUAL_REVIEW")
        if any(item in limitations for item in CRITICAL_CONTEXT_LIMITATIONS):
            reasons.append("CANDIDATE_CONTEXT_INCOMPLETE")
        return AdelinV2SetupClass.VALID_REVERSAL, reasons
    if any(item in limitations for item in CRITICAL_CONTEXT_LIMITATIONS):
        reasons.append("EXISTING_EXPORT_MISSING_ADELIN_V2_CONTEXT")
        return AdelinV2SetupClass.UNKNOWN_INSUFFICIENT_DATA, reasons
    reasons.append("NO_CONFIDENT_ADELIN_V2_CLASSIFIER_RULE_MATCHED")
    return AdelinV2SetupClass.UNKNOWN_INSUFFICIENT_DATA, reasons


def audit_trade_row(row: Mapping[str, Any], config: AdelinV2AuditConfig | None = None) -> AdelinV2DiagnosticRecord:
    cfg = config or AdelinV2AuditConfig()
    symbol = _parse_text(_first(row, ("symbol", "instrument"))) or cfg.symbol
    pip_size = cfg.pip_size or pip_size_for_symbol(symbol)
    trade_id = _parse_text(_first(row, TRADE_ID_COLUMNS))
    signal_timestamp = _parse_datetime(_first(row, SIGNAL_TIMESTAMP_COLUMNS))
    entry_timestamp = _parse_datetime(_first(row, ENTRY_TIMESTAMP_COLUMNS))
    direction = _parse_text(_first(row, ("direction", "side", "trade_direction")))
    entry_price = _parse_float(_first(row, ENTRY_PRICE_COLUMNS))
    stop_loss = _parse_float(_first(row, STOP_LOSS_COLUMNS))
    take_profit = _parse_float(_first(row, TAKE_PROFIT_COLUMNS))
    old_strategy_name = _parse_text(_first(row, STRATEGY_COLUMNS))
    old_score = _parse_float(_first(row, SCORE_COLUMNS))
    old_setup_mode = _parse_text(_first(row, SETUP_MODE_COLUMNS))
    old_continuation_flag = _parse_bool(_first(row, CONTINUATION_COLUMNS))
    old_rejection_flag = _parse_bool(_first(row, REJECTION_COLUMNS))
    if old_continuation_flag is None and old_setup_mode and "continuation" in old_setup_mode.lower():
        old_continuation_flag = True

    liquidity_timeframes_available = _parse_timeframes(_first(row, ("liquidity_timeframes_available", "liquidity_timeframe", "zone_timeframe")))
    htf_liquidity_class = _enum_from_text(
        AdelinV2LiquidityClass,
        _first(row, ("htf_liquidity_class", "htf_liquidity", "liquidity_class")),
        AdelinV2LiquidityClass.UNKNOWN,
    )
    ltf_liquidity_class = _enum_from_text(
        AdelinV2LiquidityClass,
        _first(row, ("ltf_liquidity_class", "ltf_liquidity")),
        AdelinV2LiquidityClass.UNKNOWN,
    )
    multi_tf_alignment = _parse_bool(_first(row, ("multi_tf_alignment", "multi_timeframe_alignment", "mtf_alignment")))
    reaction_zone_type = _infer_reaction_zone(row)
    reaction_zone_age_minutes = _parse_float(_first(row, ("reaction_zone_age_minutes", "zone_age_minutes")))
    reaction_zone_is_fresh_invalid = _parse_bool(
        _first(row, ("reaction_zone_is_fresh_invalid", "fresh_rejection_invalid", "fresh_rejection_zone"))
    )
    if reaction_zone_type == AdelinV2ReactionZoneType.FRESH_REJECTION_INVALID:
        reaction_zone_is_fresh_invalid = True

    explicit_nt = _parse_bool(_first(row, ("number_theory_confluence", "nt_confluence")))
    explicit_nt_distance = _parse_float(_first(row, ("distance_to_number_level_pips", "nt_distance_pips")))
    nearest_nt_level: float | None = None
    nt_distance = explicit_nt_distance
    if entry_price is not None and nt_distance is None:
        nearest_nt_level, nt_distance = number_theory_distance_pips(entry_price, pip_size=pip_size)
    number_theory_confluence = explicit_nt
    if number_theory_confluence is None and nt_distance is not None:
        number_theory_confluence = nt_distance <= cfg.number_theory_threshold_pips

    volume_profile_context_available = _parse_bool(
        _first(row, ("volume_profile_context_available", "vp_context_available", "volume_profile_available"))
    )
    volume_crack_detected = _parse_bool(_first(row, ("volume_crack_detected", "volume_crack", "vp_crack")))
    asian_open_gap_flag = _parse_bool(_first(row, ("asian_open_gap_flag", "asian_open_gap", "asia_open_gap")))
    weekly_open_gap_flag = _parse_bool(_first(row, ("weekly_open_gap_flag", "weekly_open_gap", "new_week_gap", "weekend_gap")))
    gap_contamination_flag = _parse_bool(_first(row, ("gap_contamination_flag", "gap_contamination", "gap_contaminated")))
    if gap_contamination_flag is None and (asian_open_gap_flag is not None or weekly_open_gap_flag is not None):
        gap_contamination_flag = bool(asian_open_gap_flag or weekly_open_gap_flag)

    required_sl_pips = _sl_pips(row, entry_price, stop_loss, pip_size)
    sl_within_20_pips = None if required_sl_pips is None else required_sl_pips <= cfg.normal_sl_pips
    sl_within_40_pips = None if required_sl_pips is None else required_sl_pips <= cfg.max_sl_pips
    target_liquidity_available = _parse_bool(
        _first(row, ("target_liquidity_available", "target_liquidity", "has_target_liquidity"))
    )
    next_reaction_zone_available = _parse_bool(
        _first(row, ("next_reaction_zone_available", "has_next_reaction_zone", "target_reaction_zone_available"))
    )
    rare_ifvg_continuation_candidate = _parse_bool(
        _first(row, ("rare_ifvg_continuation_candidate", "ifvg_continuation_candidate"))
    )
    post_entry_reaction_available = _parse_bool(
        _first(row, ("post_entry_reaction_available", "immediate_reaction_available", "reaction_after_entry"))
    )
    post_entry_immediate_reaction_pips = _parse_float(
        _first(row, ("post_entry_immediate_reaction_pips", "immediate_reaction_pips", "post_entry_reaction_pips"))
    )
    if post_entry_reaction_available is None and post_entry_immediate_reaction_pips is not None:
        post_entry_reaction_available = True
    post_entry_accumulation_flag = _parse_bool(
        _first(row, ("post_entry_accumulation_flag", "accumulation_after_entry", "post_entry_accumulation"))
    )
    post_entry_m1_engulfing_against = _parse_bool(
        _first(row, ("post_entry_m1_engulfing_against", "m1_engulfing_against", "engulfing_against"))
    )

    management_flags: list[AdelinV2ManagementFlag] = []
    if post_entry_immediate_reaction_pips is not None and post_entry_immediate_reaction_pips >= 100.0:
        management_flags.append(AdelinV2ManagementFlag.MOVE_TO_BE_AFTER_STRONG_REACTION)
    if post_entry_accumulation_flag is True:
        management_flags.append(AdelinV2ManagementFlag.EARLY_CLOSE_ACCUMULATION)
    if post_entry_m1_engulfing_against is True:
        management_flags.append(AdelinV2ManagementFlag.EARLY_CLOSE_M1_ENGULFING_AGAINST)
    if target_liquidity_available is True:
        management_flags.append(AdelinV2ManagementFlag.HOLD_RUNNER_TO_TARGET_LIQUIDITY)

    limitations = _build_limitations(
        htf_liquidity_class=htf_liquidity_class,  # type: ignore[arg-type]
        ltf_liquidity_class=ltf_liquidity_class,  # type: ignore[arg-type]
        reaction_zone_type=reaction_zone_type,
        target_liquidity_available=target_liquidity_available,
        gap_contamination_flag=gap_contamination_flag,
        required_sl_pips=required_sl_pips,
        entry_price=entry_price,
        post_entry_reaction_available=post_entry_reaction_available,
    )
    final_label, reasons = _classify(
        old_continuation_flag=old_continuation_flag,
        rare_ifvg_continuation_candidate=rare_ifvg_continuation_candidate,
        gap_contamination_flag=gap_contamination_flag,
        reaction_zone_is_fresh_invalid=reaction_zone_is_fresh_invalid,
        htf_liquidity_class=htf_liquidity_class,  # type: ignore[arg-type]
        ltf_liquidity_class=ltf_liquidity_class,  # type: ignore[arg-type]
        reaction_zone_type=reaction_zone_type,
        target_liquidity_available=target_liquidity_available,
        next_reaction_zone_available=next_reaction_zone_available,
        required_sl_pips=required_sl_pips,
        max_sl_pips=cfg.max_sl_pips,
        old_rejection_flag=old_rejection_flag,
        old_score=old_score,
        limitations=limitations,
    )
    continuation_blocked = bool(old_continuation_flag is True)

    return AdelinV2DiagnosticRecord(
        symbol=symbol,
        trade_id=trade_id,
        signal_timestamp=signal_timestamp,
        entry_timestamp=entry_timestamp,
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        old_strategy_name=old_strategy_name,
        old_score=old_score,
        old_setup_mode=old_setup_mode,
        old_continuation_flag=old_continuation_flag,
        old_rejection_flag=old_rejection_flag,
        liquidity_timeframes_available=liquidity_timeframes_available,
        htf_liquidity_class=htf_liquidity_class,  # type: ignore[arg-type]
        ltf_liquidity_class=ltf_liquidity_class,  # type: ignore[arg-type]
        multi_tf_alignment=multi_tf_alignment,
        reaction_zone_type=reaction_zone_type,
        reaction_zone_age_minutes=reaction_zone_age_minutes,
        reaction_zone_is_fresh_invalid=reaction_zone_is_fresh_invalid,
        number_theory_confluence=number_theory_confluence,
        nearest_number_theory_level=nearest_nt_level,
        distance_to_number_level_pips=nt_distance,
        volume_profile_context_available=volume_profile_context_available,
        volume_crack_detected=volume_crack_detected,
        gap_contamination_flag=gap_contamination_flag,
        asian_open_gap_flag=asian_open_gap_flag,
        weekly_open_gap_flag=weekly_open_gap_flag,
        required_sl_pips=required_sl_pips,
        sl_within_20_pips=sl_within_20_pips,
        sl_within_40_pips=sl_within_40_pips,
        target_liquidity_available=target_liquidity_available,
        next_reaction_zone_available=next_reaction_zone_available,
        continuation_blocked=continuation_blocked,
        rare_ifvg_continuation_candidate=rare_ifvg_continuation_candidate,
        post_entry_reaction_available=post_entry_reaction_available,
        post_entry_immediate_reaction_pips=post_entry_immediate_reaction_pips,
        post_entry_accumulation_flag=post_entry_accumulation_flag,
        post_entry_m1_engulfing_against=post_entry_m1_engulfing_against,
        management_flags=tuple(management_flags) if management_flags else (AdelinV2ManagementFlag.UNKNOWN,),
        final_adelin_v2_label=final_label,
        reason_codes=tuple(reasons),
        limitations=tuple(limitations),
    )


def _serialise(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return "|".join(_serialise(item) for item in value)
    return value


def diagnostic_to_row(record: AdelinV2DiagnosticRecord) -> dict[str, Any]:
    return {field_name: _serialise(getattr(record, field_name)) for field_name in record.__dataclass_fields__}


def build_audit_summary(
    records: Sequence[AdelinV2DiagnosticRecord],
    *,
    source_rows_loaded: int = 0,
    source_path: str | None = None,
    data_limitations: Iterable[str] = (),
) -> dict[str, Any]:
    labels = [record.final_adelin_v2_label for record in records]
    limitations = sorted({item for record in records for item in record.limitations} | set(data_limitations))
    if not records:
        limitations = sorted(set(limitations) | {"NO_ADELIN_TRADES_AUDITED"})
    return {
        "source_path": source_path,
        "source_rows_loaded": int(source_rows_loaded),
        "total_old_adelin_trades_loaded": int(len(records)),
        "trades_audited": int(len(records)),
        "missing_data_count": int(sum(1 for record in records if record.limitations)),
        "continuation_flagged_count": int(sum(1 for record in records if record.old_continuation_flag is True)),
        "continuation_blocked_count": int(sum(1 for record in records if record.continuation_blocked)),
        "possible_reversal_count": int(sum(1 for label in labels if label in {AdelinV2SetupClass.A_PLUS_REVERSAL, AdelinV2SetupClass.VALID_REVERSAL})),
        "dirty_reversal_count": int(sum(1 for label in labels if label in {AdelinV2SetupClass.DIRTY_REVERSAL, AdelinV2SetupClass.NO_TRADE_SL_TOO_WIDE})),
        "unknown_insufficient_data_count": int(sum(1 for label in labels if label == AdelinV2SetupClass.UNKNOWN_INSUFFICIENT_DATA)),
        "gap_contamination_count": int(sum(1 for record in records if record.gap_contamination_flag is True)),
        "fresh_rejection_invalid_count": int(sum(1 for record in records if record.reaction_zone_is_fresh_invalid is True)),
        "sl_over_40_pips_count": int(sum(1 for record in records if record.required_sl_pips is not None and record.required_sl_pips > 40.0)),
        "no_target_liquidity_count": int(sum(1 for record in records if record.target_liquidity_available is False and record.next_reaction_zone_available is False)),
        "number_theory_confluence_count": int(sum(1 for record in records if record.number_theory_confluence is True)),
        "multi_tf_alignment_available_count": int(sum(1 for record in records if record.multi_tf_alignment is not None)),
        "reaction_zone_available_count": int(sum(1 for record in records if record.reaction_zone_type not in {AdelinV2ReactionZoneType.UNKNOWN, AdelinV2ReactionZoneType.NONE})),
        "data_limitations": limitations,
        "research_only_warning": (
            "Existing historical Adelin exports do not contain enough context to fully classify "
            "Adelin v2 logic. This audit is a structural gap analysis, not final validation."
        ),
    }


def output_fieldnames() -> list[str]:
    return list(AdelinV2DiagnosticRecord.__dataclass_fields__.keys())


__all__ = [
    "AdelinV2AuditConfig",
    "AdelinV2DiagnosticRecord",
    "AdelinV2LiquidityClass",
    "AdelinV2ManagementFlag",
    "AdelinV2ReactionZoneType",
    "AdelinV2SetupClass",
    "audit_trade_row",
    "build_audit_summary",
    "diagnostic_to_row",
    "filter_adelin_trade_rows",
    "is_adelin_trade",
    "nearest_number_theory_level",
    "number_theory_distance_pips",
    "output_fieldnames",
    "pip_size_for_symbol",
]
