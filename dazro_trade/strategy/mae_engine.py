from __future__ import annotations

import logging
import statistics
from typing import Any, Iterable, Literal

from dazro_trade.storage.database import DEFAULT_MAE_DB_PATH
from dazro_trade.storage.mae_sample_repository import DEFAULT_QUERY_LIMIT, get_mae_samples

log = logging.getLogger(__name__)

ReferenceType = Literal["H1_HIGH", "H1_LOW"]
ConfidenceLevel = Literal["LOW_STATIC_FALLBACK", "LOW", "MEDIUM", "HIGH"]

MIN_SAMPLES_LOW = 30
MIN_SAMPLES_MEDIUM = 100
MIN_SAMPLES_HIGH = 300

DEFAULT_XAUUSD_MAE_STATS: dict[str, float] = {
    "mae_mean": 45.9,
    "mae_median": 45.9,
    "mae_p75": 45.9,
    "mae_p90": 98.8,
    "mae_p95": 123.5,
    "mae_max": 123.5,
    "sl_risk_distance": 98.8,
    "sl_conservative_distance": 123.5,
    "tp1_distance": 96.8,
    "tp2_distance": 193.6,
    "tp3_distance": 290.4,
    "tp4_distance": 387.2,
}

MAE_DISTANCE_CONSTANTS: dict[str, float] = {
    "entry_distance": 45.9,
    "sl_risk_distance": 98.8,
    "sl_conservative_distance": 123.5,
    "tp1_distance": 96.8,
    "tp2_distance": 193.6,
    "tp3_distance": 290.4,
    "tp4_distance": 387.2,
}


def calculate_manipulation_depth(
    reference_type: str,
    reference_price: float,
    sample_high: float | None = None,
    sample_low: float | None = None,
) -> float:
    if reference_type == "H1_HIGH":
        if sample_high is None:
            raise ValueError("sample_high required for H1_HIGH")
        return float(sample_high) - float(reference_price)
    if reference_type == "H1_LOW":
        if sample_low is None:
            raise ValueError("sample_low required for H1_LOW")
        return float(reference_price) - float(sample_low)
    raise ValueError(f"invalid reference_type: {reference_type}")


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pct = max(0.0, min(100.0, pct))
    k = (len(sorted_values) - 1) * (pct / 100.0)
    floor = int(k)
    ceil = min(floor + 1, len(sorted_values) - 1)
    if floor == ceil:
        return float(sorted_values[floor])
    fraction = k - floor
    return float(sorted_values[floor] + (sorted_values[ceil] - sorted_values[floor]) * fraction)


def _confidence(sample_count: int) -> ConfidenceLevel:
    if sample_count < MIN_SAMPLES_LOW:
        return "LOW_STATIC_FALLBACK"
    if sample_count < MIN_SAMPLES_MEDIUM:
        return "LOW"
    if sample_count < MIN_SAMPLES_HIGH:
        return "MEDIUM"
    return "HIGH"


def _extract_depths(samples: Iterable[Any]) -> list[float]:
    depths: list[float] = []
    for item in samples:
        if isinstance(item, (int, float)):
            depths.append(float(item))
            continue
        if isinstance(item, dict) and item.get("manipulation_depth") is not None:
            try:
                depths.append(float(item["manipulation_depth"]))
            except (TypeError, ValueError):
                continue
    return [d for d in depths if d > 0]


def calculate_mae_stats(samples: Iterable[Any], *, entry_mode: str = "mean") -> dict[str, Any]:
    depths = _extract_depths(samples)
    sample_count = len(depths)
    confidence = _confidence(sample_count)
    uses_static = confidence == "LOW_STATIC_FALLBACK"

    if uses_static:
        log.info("using static XAUUSD MAE defaults because sample_count < minimum_samples (got=%s)", sample_count)
        stats = dict(DEFAULT_XAUUSD_MAE_STATS)
        entry_distance = stats["mae_mean"] if entry_mode != "median" else stats["mae_median"]
        return {
            "sample_count": sample_count,
            "mae_mean": stats["mae_mean"],
            "mae_median": stats["mae_median"],
            "mae_p75": stats["mae_p75"],
            "mae_p90": stats["mae_p90"],
            "mae_p95": stats["mae_p95"],
            "mae_max": stats["mae_max"],
            "outlier_count": 0,
            "confidence_level": confidence,
            "uses_static_fallback": True,
            "entry_distance": entry_distance,
            "sl_risk_distance": stats["sl_risk_distance"],
            "sl_conservative_distance": stats["sl_conservative_distance"],
            "tp1_distance": stats["tp1_distance"],
            "tp2_distance": stats["tp2_distance"],
            "tp3_distance": stats["tp3_distance"],
            "tp4_distance": stats["tp4_distance"],
        }

    log.info("using dynamic XAUUSD MAE stats from %s samples", sample_count)
    mean = statistics.fmean(depths)
    median = statistics.median(depths)
    p75 = _percentile(depths, 75)
    p90 = _percentile(depths, 90)
    p95 = _percentile(depths, 95)
    maximum = max(depths)
    outlier_count = sum(1 for d in depths if d > p95)
    entry_distance = mean if entry_mode != "median" else median
    return {
        "sample_count": sample_count,
        "mae_mean": round(mean, 4),
        "mae_median": round(median, 4),
        "mae_p75": round(p75, 4),
        "mae_p90": round(p90, 4),
        "mae_p95": round(p95, 4),
        "mae_max": round(maximum, 4),
        "outlier_count": outlier_count,
        "confidence_level": confidence,
        "uses_static_fallback": False,
        "entry_distance": round(entry_distance, 4),
        "sl_risk_distance": round(p90, 4),
        "sl_conservative_distance": round(p95, 4),
        "tp1_distance": DEFAULT_XAUUSD_MAE_STATS["tp1_distance"],
        "tp2_distance": DEFAULT_XAUUSD_MAE_STATS["tp2_distance"],
        "tp3_distance": DEFAULT_XAUUSD_MAE_STATS["tp3_distance"],
        "tp4_distance": DEFAULT_XAUUSD_MAE_STATS["tp4_distance"],
    }


def load_mae_stats_for_bucket(
    *,
    session: str | None,
    reference_type: ReferenceType,
    volatility_regime: str | None = None,
    timeframe: str = "H1",
    setup_type: str = "manipulation_distribution",
    limit: int = DEFAULT_QUERY_LIMIT,
    db_path: str = DEFAULT_MAE_DB_PATH,
    entry_mode: str = "mean",
) -> dict[str, Any]:
    try:
        rows = get_mae_samples(
            timeframe=timeframe,
            session=session,
            reference_type=reference_type,
            setup_type=setup_type,
            volatility_regime=volatility_regime,
            limit=limit,
            db_path=db_path,
        )
    except Exception as exc:
        log.warning("load_mae_stats_for_bucket failed: %s — using static fallback", exc)
        rows = []
    return calculate_mae_stats(rows, entry_mode=entry_mode)


__all__ = [
    "DEFAULT_XAUUSD_MAE_STATS",
    "MAE_DISTANCE_CONSTANTS",
    "ReferenceType",
    "calculate_mae_stats",
    "calculate_manipulation_depth",
    "load_mae_stats_for_bucket",
]
