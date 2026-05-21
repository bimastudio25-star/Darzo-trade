from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median
from typing import Any, Callable

import pandas as pd


PRIMARY_MODEL = "containing"
VALID_SAMPLE_STATUSES = {
    "VALID_SAMPLE_TRADE_TRIGGERED",
    "VALID_SAMPLE_NO_ENTRY_MAE_NOT_REACHED",
    "VALID_SAMPLE_NO_ENTRY_NO_RANGE_REENTRY",
}
TARGET_LABEL = "BAD_EXPOST_RATIO"
EX_POST_UPPER_BOUND_NAME = "EX_POST_EXPANSION_MAE_RATIO_P25"

SAFETY = {
    "research_only": True,
    "dry_run": True,
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "broker_called": False,
    "order_sent": False,
    "order_send_called": False,
    "signals_generated": False,
    "runtime_registration": False,
    "parameters_optimized": False,
    "grid_search_used": False,
    "machine_learning_used": False,
    "market_data_written": False,
    "profit_or_pf_used": False,
}


@dataclass(frozen=True)
class HypothesisValidationResult:
    samples: pd.DataFrame
    feature_summary: pd.DataFrame
    proxy_results: pd.DataFrame
    r_profile_impact: pd.DataFrame
    leakage_audit: pd.DataFrame
    ex_post_upper_bound: pd.DataFrame
    summary: dict[str, Any]
    report_markdown: str


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([pd.NA] * len(frame), index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _values(frame: pd.DataFrame, column: str) -> list[float]:
    return [float(value) for value in _numeric(frame, column).dropna().tolist()]


def _mean(values: list[float]) -> float | None:
    return round(fmean(values), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(median(values), 4) if values else None


def percentile(values: list[float], q: float) -> float | None:
    vals = sorted(values)
    if not vals:
        return None
    if len(vals) == 1:
        return round(vals[0], 4)
    pos = (len(vals) - 1) * q
    low = int(pos)
    high = min(low + 1, len(vals) - 1)
    weight = pos - low
    return round(vals[low] * (1 - weight) + vals[high] * weight, 4)


def _pct(count: int | float, total: int | float) -> float:
    return round(float(count) / float(total) * 100.0, 2) if total else 0.0


def price_to_pips(distance: float | None, pip_factor: float) -> float | None:
    return None if distance is None else round(float(distance) * float(pip_factor), 4)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value


def conservative_sl_distance(max_excursion: float | None) -> float | None:
    return None if max_excursion is None else round(float(max_excursion) * 1.25, 4)


def tp_quartiles(max_expansion: float | None) -> dict[str, float | None]:
    if max_expansion is None:
        return {"tp1": None, "tp2": None, "tp3": None, "tp4": None}
    value = max(0.0, float(max_expansion))
    return {
        "tp1": round(value * 0.25, 4),
        "tp2": round(value * 0.50, 4),
        "tp3": round(value * 0.75, 4),
        "tp4": round(value, 4),
    }


def _sample_key(row: pd.Series | dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("h1_context_timestamp", "")),
            str(row.get("h1_reference_type", "")),
            str(row.get("direction", "")),
            str(row.get("h1_liquidity_level", "")),
        ]
    )


def _parse_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=True)


def _minutes_between(later: pd.Series, earlier: pd.Series) -> pd.Series:
    return (later - earlier).dt.total_seconds() / 60.0


def load_validation_samples(mechanical_dir: str | Path, *, pip_factor: float = 10.0) -> pd.DataFrame:
    path = Path(mechanical_dir) / "corrected_mechanical_samples.csv"
    if not path.exists():
        raise FileNotFoundError(f"corrected mechanical sample file missing: {path}")
    frame = pd.read_csv(path)
    required = {"m15_filter_model", "sample_status", "manipulation_depth_usd", "expansion_usd", "entry_valid"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"corrected mechanical sample file missing required columns: {missing}")
    enriched = enrich_samples(frame, pip_factor=pip_factor)
    containing = enriched[enriched["m15_filter_model"].astype(str).eq(PRIMARY_MODEL)].copy()
    return containing[containing["is_valid_sample"]].copy()


def enrich_samples(frame: pd.DataFrame, *, pip_factor: float = 10.0) -> pd.DataFrame:
    out = frame.copy()
    out["sample_key"] = out.apply(_sample_key, axis=1)
    out["is_valid_sample"] = out["sample_status"].astype(str).isin(VALID_SAMPLE_STATUSES)
    out["entry_valid_bool"] = out.get("entry_valid", pd.Series(False, index=out.index)).map(_to_bool)
    out["manipulation_depth_usd"] = _numeric(out, "manipulation_depth_usd")
    out["manipulation_depth_pips"] = out["manipulation_depth_usd"] * float(pip_factor)
    out["expansion_usd"] = _numeric(out, "expansion_usd")
    out["expansion_pips"] = out["expansion_usd"] * float(pip_factor)
    out["h1_reference_range"] = _numeric(out, "h1_reference_range")
    out["hour"] = _numeric(out, "hour")
    out["dominant_contains_internal_count"] = _numeric(out, "dominant_contains_internal_count")
    out["expansion_mae_ratio"] = out["expansion_usd"] / out["manipulation_depth_usd"].where(out["manipulation_depth_usd"] > 0)
    context_ts = _parse_utc(out.get("h1_context_timestamp", pd.Series(pd.NaT, index=out.index)))
    take_ts = _parse_utc(out.get("h1_level_take_timestamp", pd.Series(pd.NaT, index=out.index)))
    mae_ts = _parse_utc(out.get("mae_reached_timestamp", pd.Series(pd.NaT, index=out.index)))
    reentry_ts = _parse_utc(out.get("range_reentry_timestamp", pd.Series(pd.NaT, index=out.index)))
    out["level_take_minute_in_h1"] = _minutes_between(take_ts, context_ts)
    out["mae_reach_minute_in_h1"] = _minutes_between(mae_ts, context_ts)
    out["reentry_minute_in_h1"] = _minutes_between(reentry_ts, context_ts)
    out["time_from_h1_open_to_take"] = out["level_take_minute_in_h1"]
    out["time_from_take_to_mae"] = _minutes_between(mae_ts, take_ts)
    out["time_from_mae_to_reentry"] = _minutes_between(reentry_ts, mae_ts)
    ratio_p25 = percentile(_values(out[out["is_valid_sample"]], "expansion_mae_ratio"), 0.25)
    out["bad_expost_ratio"] = out["expansion_mae_ratio"] <= float(ratio_p25) if ratio_p25 is not None else False
    out["tail_gt_12"] = out["manipulation_depth_usd"] > 12
    out["tail_gt_20"] = out["manipulation_depth_usd"] > 20
    out["tail_gt_40"] = out["manipulation_depth_usd"] > 40
    out["tail_gt_100"] = out["manipulation_depth_usd"] > 100
    out["body_le_12"] = out["manipulation_depth_usd"] <= 12
    out["body_le_8"] = out["manipulation_depth_usd"] <= 8
    out["pip_factor_used"] = float(pip_factor)
    return out


def r_profile_for_samples(samples: pd.DataFrame, *, label: str, pip_factor: float = 10.0) -> dict[str, Any]:
    mae = _values(samples, "manipulation_depth_usd")
    expansion = _values(samples, "expansion_usd")
    avg_mae = _mean(mae)
    max_excursion = round(max(mae), 4) if mae else None
    conservative_sl = conservative_sl_distance(max_excursion)
    effective_risk = None
    if conservative_sl is not None and avg_mae is not None:
        effective_risk = round(max(conservative_sl - avg_mae, 0.0), 4)
    max_expansion = round(max(expansion), 4) if expansion else None
    tps = tp_quartiles(max_expansion)

    def rr(tp_distance: float | None) -> float | None:
        if tp_distance is None or avg_mae is None or effective_risk is None or effective_risk <= 0:
            return None
        return round((avg_mae + tp_distance) / effective_risk, 4)

    return {
        "profile_label": label,
        "samples": int(len(samples)),
        "mae_avg_usd": avg_mae,
        "mae_median_usd": _median(mae),
        "mae_p90_usd": percentile(mae, 0.90),
        "mae_p95_usd": percentile(mae, 0.95),
        "max_excursion_usd": max_excursion,
        "conservative_sl_usd": conservative_sl,
        "max_excursion_pips": price_to_pips(max_excursion, pip_factor),
        "conservative_sl_pips": price_to_pips(conservative_sl, pip_factor),
        "avg_expansion_usd": _mean(expansion),
        "max_expansion_usd": max_expansion,
        "tp1_distance_usd": tps["tp1"],
        "tp2_distance_usd": tps["tp2"],
        "tp3_distance_usd": tps["tp3"],
        "tp4_distance_usd": tps["tp4"],
        "tp1_R": rr(tps["tp1"]),
        "tp2_R": rr(tps["tp2"]),
        "tp3_R": rr(tps["tp3"]),
        "tp4_R": rr(tps["tp4"]),
        "pip_factor_used": float(pip_factor),
        "unit_note": "USD fields are XAUUSD price-distance/USD units; pips = USD * pip_factor.",
    }


def feature_summary(samples: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for feature in [
        "h1_reference_range",
        "level_take_minute_in_h1",
        "mae_reach_minute_in_h1",
        "reentry_minute_in_h1",
        "time_from_take_to_mae",
        "time_from_mae_to_reentry",
        "dominant_contains_internal_count",
        "hour",
    ]:
        values = _values(samples, feature)
        rows.append(
            {
                "feature": feature,
                "available_count": len(values),
                "missing_count": int(len(samples) - len(values)),
                "mean": _mean(values),
                "median": _median(values),
                "p25": percentile(values, 0.25),
                "p75": percentile(values, 0.75),
                "p90": percentile(values, 0.90),
                "p95": percentile(values, 0.95),
                "uses_only_pre_entry_data": True,
                "leakage_flag": "",
            }
        )
    for feature in ["expansion_usd", "expansion_mae_ratio", "final_result", "pnl", "r_multiple"]:
        rows.append(
            {
                "feature": feature,
                "available_count": int(samples[feature].notna().sum()) if feature in samples.columns else 0,
                "missing_count": int(samples[feature].isna().sum()) if feature in samples.columns else len(samples),
                "uses_only_pre_entry_data": False,
                "leakage_flag": "LEAKAGE_FEATURE" if feature in {"expansion_usd", "expansion_mae_ratio", "final_result", "pnl", "r_multiple"} else "",
            }
        )
    return pd.DataFrame(rows)


def leakage_audit() -> pd.DataFrame:
    rows = [
        ("expansion_mae_ratio", False, "LEAKAGE_FEATURE", "Requires future expansion after entry; target/upper-bound only."),
        ("expansion_usd", False, "LEAKAGE_FEATURE", "Future expansion after setup."),
        ("max_favorable_excursion", False, "LEAKAGE_FEATURE", "Future path after entry."),
        ("tp_reached", False, "LEAKAGE_FEATURE", "Future outcome."),
        ("final_result", False, "LEAKAGE_FEATURE", "Future outcome."),
        ("pnl", False, "LEAKAGE_FEATURE", "Performance outcome."),
        ("r_multiple", False, "LEAKAGE_FEATURE", "Performance outcome."),
        ("h1_reference_range", True, "", "Known before the level-take setup."),
        ("direction", True, "", "Known from H1 liquidity side."),
        ("hour", True, "", "Known before or at entry."),
        ("session", True, "", "Known before or at entry."),
        ("level_take_minute_in_h1", True, "", "Known before entry after level take."),
        ("mae_reach_minute_in_h1", True, "", "Known at MAE reach."),
        ("reentry_minute_in_h1", True, "", "Known at entry/re-entry."),
        ("time_from_take_to_mae", True, "", "Known at MAE reach."),
        ("time_from_mae_to_reentry", True, "", "Known at entry/re-entry."),
    ]
    return pd.DataFrame(rows, columns=["feature", "uses_only_pre_entry_data", "leakage_flag", "reason"])


def _proxy_row(
    samples: pd.DataFrame,
    *,
    proxy_name: str,
    description: str,
    flag_mask: pd.Series,
    uses_only_pre_entry_data: bool,
    leakage_flag: str,
    pip_factor: float,
) -> dict[str, Any]:
    flag_mask = flag_mask.reindex(samples.index).fillna(False).astype(bool)
    flagged = samples[flag_mask].copy()
    kept = samples[~flag_mask].copy()
    total_bad = int(samples["bad_expost_ratio"].sum())
    total_body12 = int(samples["body_le_12"].sum())
    total_body8 = int(samples["body_le_8"].sum())
    total_tail12 = int(samples["tail_gt_12"].sum())
    total_tail20 = int(samples["tail_gt_20"].sum())
    total_tail40 = int(samples["tail_gt_40"].sum())
    bad_caught = int(flagged["bad_expost_ratio"].sum())
    body12_removed = int(flagged["body_le_12"].sum())
    body8_removed = int(flagged["body_le_8"].sum())
    tail12_caught = int(flagged["tail_gt_12"].sum())
    tail20_caught = int(flagged["tail_gt_20"].sum())
    tail40_caught = int(flagged["tail_gt_40"].sum())
    before = r_profile_for_samples(samples, label="RAW_CONTAINING", pip_factor=pip_factor)
    after = r_profile_for_samples(kept, label=proxy_name, pip_factor=pip_factor)
    body_false_positive_pct = _pct(body12_removed, total_body12)
    bad_caught_pct = _pct(bad_caught, total_bad)
    tail20_caught_pct = _pct(tail20_caught, total_tail20)
    if leakage_flag:
        verdict = "REJECTED_LEAKAGE"
    elif len(kept) < 30:
        verdict = "INSUFFICIENT_DATA"
    elif body_false_positive_pct > 30:
        verdict = "REJECTED_TOO_BROAD"
    elif bad_caught_pct >= 45 and tail20_caught_pct >= 35 and body_false_positive_pct <= 25:
        verdict = "PROMISING_PRE_ENTRY_PROXY"
    elif bad_caught_pct < 25 or tail20_caught_pct < 20:
        verdict = "WEAK_PROXY"
    else:
        verdict = "WEAK_PROXY"
    return {
        "proxy_name": proxy_name,
        "proxy_description": description,
        "uses_only_pre_entry_data": bool(uses_only_pre_entry_data),
        "leakage_flag": leakage_flag,
        "samples_flagged": int(len(flagged)),
        "samples_kept": int(len(kept)),
        "bad_expost_ratio_caught_pct": bad_caught_pct,
        "bad_expost_ratio_missed_pct": _pct(total_bad - bad_caught, total_bad),
        "body_false_positive_pct": body_false_positive_pct,
        "tail_gt_12_caught_pct": _pct(tail12_caught, total_tail12),
        "tail_gt_20_caught_pct": tail20_caught_pct,
        "tail_gt_40_caught_pct": _pct(tail40_caught, total_tail40),
        "body_le_12_removed_pct": body_false_positive_pct,
        "body_le_8_removed_pct": _pct(body8_removed, total_body8),
        "max_excursion_after": after["max_excursion_usd"],
        "conservative_sl_after": after["conservative_sl_usd"],
        "tp4_R_after": after["tp4_R"],
        "max_excursion_before": before["max_excursion_usd"],
        "conservative_sl_before": before["conservative_sl_usd"],
        "tp4_R_before": before["tp4_R"],
        "sample_size_after_filter": int(len(kept)),
        "profit_or_pf_used": False,
        "verdict": verdict,
    }


def _threshold_masks(samples: pd.DataFrame, feature: str) -> list[tuple[str, str, pd.Series]]:
    values = _values(samples, feature)
    p25 = percentile(values, 0.25)
    p75 = percentile(values, 0.75)
    p90 = percentile(values, 0.90)
    p95 = percentile(values, 0.95)
    masks: list[tuple[str, str, pd.Series]] = []
    if feature == "h1_reference_range":
        for label, threshold in [("P75", p75), ("P90", p90), ("P95", p95)]:
            if threshold is not None:
                masks.append((f"H1_RANGE_GT_{label}", f"H1 range > {label} ({threshold})", samples[feature] > threshold))
    else:
        if p25 is not None:
            masks.append((f"{feature.upper()}_LE_P25", f"{feature} <= p25 ({p25})", samples[feature] <= p25))
        if p75 is not None:
            masks.append((f"{feature.upper()}_GE_P75", f"{feature} >= p75 ({p75})", samples[feature] >= p75))
    return masks


def proxy_validation_results(samples: pd.DataFrame, *, pip_factor: float = 10.0) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    pre_entry_features = [
        "h1_reference_range",
        "level_take_minute_in_h1",
        "mae_reach_minute_in_h1",
        "reentry_minute_in_h1",
        "time_from_take_to_mae",
        "time_from_mae_to_reentry",
    ]
    for feature in pre_entry_features:
        if feature not in samples.columns:
            continue
        for proxy_name, description, mask in _threshold_masks(samples, feature):
            rows.append(
                _proxy_row(
                    samples,
                    proxy_name=proxy_name,
                    description=description,
                    flag_mask=mask,
                    uses_only_pre_entry_data=True,
                    leakage_flag="",
                    pip_factor=pip_factor,
                )
            )
    rows.append(
        _proxy_row(
            samples,
            proxy_name="H1_REFERENCE_DOMINANT",
            description="h1_reference_type == dominant_h1",
            flag_mask=samples.get("h1_reference_type", pd.Series("", index=samples.index)).astype(str).eq("dominant_h1"),
            uses_only_pre_entry_data=True,
            leakage_flag="",
            pip_factor=pip_factor,
        )
    )
    for direction in sorted(str(item) for item in samples.get("direction", pd.Series(dtype=str)).dropna().unique()):
        rows.append(
            _proxy_row(
                samples,
                proxy_name=f"DIRECTION_{direction}",
                description=f"direction == {direction}",
                flag_mask=samples.get("direction", pd.Series("", index=samples.index)).astype(str).eq(direction),
                uses_only_pre_entry_data=True,
                leakage_flag="",
                pip_factor=pip_factor,
            )
        )
    for hour in (4, 14):
        rows.append(
            _proxy_row(
                samples,
                proxy_name=f"HOUR_EQ_{hour}",
                description=f"hour == {hour} (previously flagged diagnostic hour)",
                flag_mask=samples.get("hour", pd.Series(pd.NA, index=samples.index)).eq(hour),
                uses_only_pre_entry_data=True,
                leakage_flag="",
                pip_factor=pip_factor,
            )
        )
    for session in sorted(str(item) for item in samples.get("session", pd.Series(dtype=str)).dropna().unique()):
        rows.append(
            _proxy_row(
                samples,
                proxy_name=f"SESSION_{session}",
                description=f"session == {session}",
                flag_mask=samples.get("session", pd.Series("", index=samples.index)).astype(str).eq(session),
                uses_only_pre_entry_data=True,
                leakage_flag="",
                pip_factor=pip_factor,
            )
        )
    # Explicit leakage upper-bound candidates are reported and rejected.
    ratio_p25 = percentile(_values(samples, "expansion_mae_ratio"), 0.25)
    if ratio_p25 is not None:
        rows.append(
            _proxy_row(
                samples,
                proxy_name=EX_POST_UPPER_BOUND_NAME,
                description=f"expansion_mae_ratio <= p25 ({ratio_p25}); upper bound only",
                flag_mask=samples["expansion_mae_ratio"] <= ratio_p25,
                uses_only_pre_entry_data=False,
                leakage_flag="LEAKAGE_FEATURE",
                pip_factor=pip_factor,
            )
        )
    mae_p90 = percentile(_values(samples, "manipulation_depth_usd"), 0.90)
    if mae_p90 is not None:
        rows.append(
            _proxy_row(
                samples,
                proxy_name="EX_POST_MAE_GT_P90",
                description=f"manipulation_depth_usd > p90 ({mae_p90}); diagnostic only",
                flag_mask=samples["manipulation_depth_usd"] > mae_p90,
                uses_only_pre_entry_data=False,
                leakage_flag="LEAKAGE_FEATURE",
                pip_factor=pip_factor,
            )
        )
    results = pd.DataFrame(rows)
    return add_limited_combinations(samples, results, pip_factor=pip_factor)


def add_limited_combinations(samples: pd.DataFrame, results: pd.DataFrame, *, pip_factor: float) -> pd.DataFrame:
    clean = results[(results["leakage_flag"].eq("")) & (~results["verdict"].eq("REJECTED_TOO_BROAD"))].copy()
    clean = clean.sort_values(["bad_expost_ratio_caught_pct", "tail_gt_20_caught_pct", "body_false_positive_pct"], ascending=[False, False, True]).head(3)
    rows = results.to_dict(orient="records")
    masks_by_name = proxy_masks_by_name(samples)
    names = [str(name) for name in clean["proxy_name"].tolist() if str(name) in masks_by_name]
    for i, first in enumerate(names):
        for second in names[i + 1 :]:
            combined = masks_by_name[first] | masks_by_name[second]
            rows.append(
                _proxy_row(
                    samples,
                    proxy_name=f"COMBO_{first}__OR__{second}",
                    description=f"Limited two-factor diagnostic combination: {first} OR {second}",
                    flag_mask=combined,
                    uses_only_pre_entry_data=True,
                    leakage_flag="",
                    pip_factor=pip_factor,
                )
            )
    return pd.DataFrame(rows)


def proxy_masks_by_name(samples: pd.DataFrame) -> dict[str, pd.Series]:
    masks: dict[str, pd.Series] = {}
    for feature in [
        "h1_reference_range",
        "level_take_minute_in_h1",
        "mae_reach_minute_in_h1",
        "reentry_minute_in_h1",
        "time_from_take_to_mae",
        "time_from_mae_to_reentry",
    ]:
        for name, _description, mask in _threshold_masks(samples, feature):
            masks[name] = mask
    masks["H1_REFERENCE_DOMINANT"] = samples.get("h1_reference_type", pd.Series("", index=samples.index)).astype(str).eq("dominant_h1")
    for direction in sorted(str(item) for item in samples.get("direction", pd.Series(dtype=str)).dropna().unique()):
        masks[f"DIRECTION_{direction}"] = samples.get("direction", pd.Series("", index=samples.index)).astype(str).eq(direction)
    for hour in (4, 14):
        masks[f"HOUR_EQ_{hour}"] = samples.get("hour", pd.Series(pd.NA, index=samples.index)).eq(hour)
    for session in sorted(str(item) for item in samples.get("session", pd.Series(dtype=str)).dropna().unique()):
        masks[f"SESSION_{session}"] = samples.get("session", pd.Series("", index=samples.index)).astype(str).eq(session)
    return masks


def ex_post_upper_bound_comparison(results: pd.DataFrame) -> pd.DataFrame:
    upper = results[results["proxy_name"].eq(EX_POST_UPPER_BOUND_NAME)].copy()
    clean = results[(results["leakage_flag"].eq("")) & (~results["proxy_name"].str.startswith("COMBO_", na=False))].copy()
    if upper.empty:
        return pd.DataFrame()
    upper_row = upper.iloc[0].to_dict()
    rows = []
    for _, row in clean.iterrows():
        rows.append(
            {
                "proxy_name": row["proxy_name"],
                "bad_expost_ratio_caught_gap_vs_upper_bound": round(float(upper_row["bad_expost_ratio_caught_pct"]) - float(row["bad_expost_ratio_caught_pct"]), 4),
                "tail_gt_20_caught_gap_vs_upper_bound": round(float(upper_row["tail_gt_20_caught_pct"]) - float(row["tail_gt_20_caught_pct"]), 4),
                "body_false_positive_delta_vs_upper_bound": round(float(row["body_false_positive_pct"]) - float(upper_row["body_false_positive_pct"]), 4),
                "upper_bound_not_deployable": True,
            }
        )
    return pd.DataFrame(rows)


def r_profile_impact(results: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "proxy_name",
        "samples_kept",
        "max_excursion_before",
        "max_excursion_after",
        "conservative_sl_before",
        "conservative_sl_after",
        "tp4_R_before",
        "tp4_R_after",
        "leakage_flag",
        "verdict",
    ]
    return results[columns].copy()


def best_pre_entry_proxy(results: pd.DataFrame) -> dict[str, Any] | None:
    clean = results[(results["leakage_flag"].eq("")) & (results["verdict"].eq("PROMISING_PRE_ENTRY_PROXY"))].copy()
    if clean.empty:
        ranked = results[(results["leakage_flag"].eq("")) & (~results["verdict"].eq("REJECTED_TOO_BROAD"))].copy()
        if ranked.empty:
            return None
        ranked = ranked.sort_values(["bad_expost_ratio_caught_pct", "tail_gt_20_caught_pct", "body_false_positive_pct"], ascending=[False, False, True])
        row = ranked.iloc[0].to_dict()
        row["best_is_promising"] = False
        return row
    clean = clean.sort_values(["bad_expost_ratio_caught_pct", "tail_gt_20_caught_pct", "body_false_positive_pct"], ascending=[False, False, True])
    row = clean.iloc[0].to_dict()
    row["best_is_promising"] = True
    return row


def final_verdict(best: dict[str, Any] | None, samples: pd.DataFrame) -> str:
    if best is None:
        return "NO_FAITHFUL_PRE_ENTRY_PROXY_FOUND"
    if best.get("best_is_promising") is True:
        return "PRE_ENTRY_PROXY_FOUND_DIAGNOSTIC_ONLY"
    if len(samples) < 100:
        return "INCONCLUSIVE_NEEDS_MORE_DATA"
    return "NO_FAITHFUL_PRE_ENTRY_PROXY_FOUND"


def verdict_flags(verdict: str, results: pd.DataFrame) -> list[str]:
    flags = [
        "HARDENING_HYPOTHESIS_VALIDATION_COMPLETE",
        "EX_POST_UPPER_BOUND_NOT_DEPLOYABLE",
        "R_PROFILE_STILL_STRUCTURALLY_WEAK",
        "STRATEGY_2_REMAINS_RESEARCH_ONLY",
        "NO_LIVE_DEPLOYMENT_DECISION",
    ]
    flags.append(verdict)
    if results["leakage_flag"].eq("LEAKAGE_FEATURE").any():
        flags.append("LEAKAGE_FEATURES_REJECTED")
    return flags


def build_hypothesis_validation(
    tail_dir: str | Path,
    containing_dir: str | Path,
    mechanical_dir: str | Path,
    *,
    pip_factor: float = 10.0,
) -> HypothesisValidationResult:
    started = time.perf_counter()
    samples = load_validation_samples(mechanical_dir, pip_factor=pip_factor)
    features = feature_summary(samples)
    leakage = leakage_audit()
    results = proxy_validation_results(samples, pip_factor=pip_factor)
    r_impact = r_profile_impact(results)
    upper_bound = ex_post_upper_bound_comparison(results)
    best = best_pre_entry_proxy(results)
    verdict = final_verdict(best, samples)
    runtime = round(time.perf_counter() - started, 4)
    flags = verdict_flags(verdict, results)
    summary = _json_safe({
        "runtime_seconds": runtime,
        "tail_dir": str(tail_dir),
        "containing_dir": str(containing_dir),
        "mechanical_dir": str(mechanical_dir),
        "samples_loaded": int(len(samples)),
        "bad_expost_ratio_threshold_p25": percentile(_values(samples, "expansion_mae_ratio"), 0.25),
        "bad_expost_ratio_count": int(samples["bad_expost_ratio"].sum()),
        "proxy_candidates_evaluated": int(len(results[results["leakage_flag"].eq("")])),
        "leakage_features_rejected": int(len(results[results["leakage_flag"].ne("")])),
        "best_pre_entry_proxy": best,
        "final_verdict": verdict,
        "ex_post_upper_bound_result": results[results["proxy_name"].eq(EX_POST_UPPER_BOUND_NAME)].to_dict(orient="records"),
        "r_profile_raw": r_profile_for_samples(samples, label="RAW_CONTAINING", pip_factor=pip_factor),
        "r_profile_after_best_proxy": _best_r_profile_from_results(results, best),
        "pip_factor_used": float(pip_factor),
        "unit_note": "USD fields are XAUUSD price-distance/USD units; pips = USD * pip_factor.",
        "safety": SAFETY,
        "verdict_flags": flags,
    })
    return HypothesisValidationResult(
        samples=samples,
        feature_summary=features,
        proxy_results=results,
        r_profile_impact=r_impact,
        leakage_audit=leakage,
        ex_post_upper_bound=upper_bound,
        summary=summary,
        report_markdown=validation_report_markdown(summary, features, results, r_impact, leakage, upper_bound),
    )


def _best_r_profile_from_results(results: pd.DataFrame, best: dict[str, Any] | None) -> dict[str, Any]:
    if not best:
        return {}
    match = results[results["proxy_name"].eq(best.get("proxy_name"))]
    if match.empty:
        return {}
    row = match.iloc[0]
    return {
        "proxy_name": row.get("proxy_name"),
        "samples_kept": row.get("samples_kept"),
        "max_excursion_after": row.get("max_excursion_after"),
        "conservative_sl_after": row.get("conservative_sl_after"),
        "tp4_R_after": row.get("tp4_R_after"),
    }


def write_hypothesis_validation_outputs(
    result: HypothesisValidationResult,
    output_dir: str | Path,
    *,
    docs_path: str | Path | None = None,
) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "feature_summary": output / "proxy_feature_summary.csv",
        "proxy_results": output / "proxy_validation_results.csv",
        "r_profile_impact": output / "proxy_r_profile_impact.csv",
        "leakage_audit": output / "leakage_audit.csv",
        "ex_post_upper_bound": output / "ex_post_upper_bound_comparison.csv",
        "summary": output / "hypothesis_validation_summary.json",
        "report": output / "hypothesis_validation_report.md",
    }
    result.feature_summary.to_csv(paths["feature_summary"], index=False)
    result.proxy_results.to_csv(paths["proxy_results"], index=False)
    result.r_profile_impact.to_csv(paths["r_profile_impact"], index=False)
    result.leakage_audit.to_csv(paths["leakage_audit"], index=False)
    result.ex_post_upper_bound.to_csv(paths["ex_post_upper_bound"], index=False)
    paths["summary"].write_text(json.dumps(result.summary, indent=2, sort_keys=True), encoding="utf-8")
    paths["report"].write_text(result.report_markdown, encoding="utf-8")
    if docs_path:
        docs = Path(docs_path)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(result.report_markdown, encoding="utf-8")
        paths["docs"] = docs
    return {key: str(path) for key, path in paths.items()}


def validation_report_markdown(
    summary: dict[str, Any],
    features: pd.DataFrame,
    results: pd.DataFrame,
    r_impact: pd.DataFrame,
    leakage: pd.DataFrame,
    upper_bound: pd.DataFrame,
) -> str:
    clean = results[results["leakage_flag"].eq("")].copy()
    clean = clean.sort_values(["bad_expost_ratio_caught_pct", "tail_gt_20_caught_pct", "body_false_positive_pct"], ascending=[False, False, True]).head(12)
    ex_post = results[results["proxy_name"].eq(EX_POST_UPPER_BOUND_NAME)].to_dict(orient="records")
    lines = [
        "# Strategy 2 Hardening Hypothesis Validation",
        "",
        "## Context",
        "",
        "Tail-risk hardening found that low expansion/MAE ratio was the strongest separator, but that ratio is ex-post and cannot be used operationally. This branch tests whether faithful pre-entry mechanical proxies can approximate that separator.",
        "",
        "## Safety",
        "",
        "- Strategy 3 untouched.",
        "- data/XAUUSD/*.csv untouched.",
        "- No live trading, Telegram, broker execution, orders, optimization, signal generation, grid search, ML, or runtime registration.",
        "",
        "## Leakage Rules",
        "",
        "- Allowed: H1 reference metadata, direction, hour/session, level-take timing, MAE timing, re-entry timing, and other values known before or at entry.",
        "- Forbidden: future expansion, MFE, TP reached, final result, PnL, R multiple, or expansion/MAE ratio as a deployable feature.",
        "- Ex-post expansion/MAE ratio is used only as the target/upper bound.",
        "",
        "## Method",
        "",
        f"- Target label: `{TARGET_LABEL}` = expansion/MAE ratio <= p25 ({summary.get('bad_expost_ratio_threshold_p25')}).",
        "- Proxy candidates are one-factor descriptive thresholds plus a small limited set of two-factor combinations from top single proxies.",
        "- No PnL/PF and no threshold optimization are used.",
        f"- Unit conversion: pips = USD/price distance * {summary.get('pip_factor_used')}.",
        "",
        "## Ex-Post Upper Bound",
        "",
    ]
    if ex_post:
        row = ex_post[0]
        lines.extend(
            [
                f"- Upper bound: `{row['proxy_name']}`.",
                f"- Bad ex-post ratio caught: {row['bad_expost_ratio_caught_pct']}%.",
                f"- Tail >20 caught: {row['tail_gt_20_caught_pct']}%.",
                f"- Body false positive: {row['body_false_positive_pct']}%.",
                "- Status: EX_POST_UPPER_BOUND_NOT_DEPLOYABLE.",
            ]
        )
    lines.extend(["", "## Pre-Entry Proxy Results", "", "| Proxy | Bad caught % | >20 tail caught % | Body FP % | SL after | TP4_R after | Verdict |"])
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for _, row in clean.iterrows():
        lines.append(
            f"| {row['proxy_name']} | {row['bad_expost_ratio_caught_pct']} | {row['tail_gt_20_caught_pct']} | {row['body_false_positive_pct']} | {row['conservative_sl_after']} | {row['tp4_R_after']} | {row['verdict']} |"
        )
    lines.extend(
        [
            "",
            "## Best Proxy",
            "",
            f"- Best pre-entry proxy: `{summary.get('best_pre_entry_proxy', {}).get('proxy_name') if summary.get('best_pre_entry_proxy') else None}`.",
            f"- Final verdict: `{summary.get('final_verdict')}`.",
            "",
            "## R-Profile Impact",
            "",
            f"- Raw TP4_R: {summary.get('r_profile_raw', {}).get('tp4_R')}.",
            f"- Raw conservative SL: {summary.get('r_profile_raw', {}).get('conservative_sl_usd')} USD.",
            f"- After best proxy TP4_R: {summary.get('r_profile_after_best_proxy', {}).get('tp4_R_after')}.",
            f"- After best proxy conservative SL: {summary.get('r_profile_after_best_proxy', {}).get('conservative_sl_after')} USD.",
            "",
            "## Leakage Audit",
            "",
            "| Feature | Pre-entry? | Leakage flag | Reason |",
            "|---|---|---|---|",
        ]
    )
    for _, row in leakage.iterrows():
        lines.append(f"| {row['feature']} | {row['uses_only_pre_entry_data']} | {row['leakage_flag']} | {row['reason']} |")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- The target is ex-post and diagnostic only.",
            "- No manual labels are available.",
            "- No live/signal validation is made.",
            "- A proxy that helps diagnostically is not a deployment decision.",
            "",
            "## Verdict Flags",
            "",
            *[f"- {flag}" for flag in summary.get("verdict_flags", [])],
            "",
            "## Next Strategy 2-Only Step",
            "",
            "- If promising proxy: feat/strategy-2-pre-entry-proxy-limited-diagnostic",
            "- If no proxy: feat/strategy-2-research-pause-summary",
            "- If inconclusive: feat/strategy-2-proxy-data-enrichment",
        ]
    )
    return "\n".join(lines) + "\n"
