from __future__ import annotations

import csv
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd


STRATEGY_NAME = "strategy_5_asymmetric_liquidity_reclaim_2r3r"
OUTPUT_FIELDS = [
    "signal_timestamp",
    "direction",
    "setup_mode",
    "rr_mode",
    "swept_level_type",
    "swept_level_price",
    "reclaim_level",
    "cisd_detected",
    "mss_detected",
    "fvg_detected",
    "ifvg_detected",
    "bpr_detected",
    "entry_price",
    "stop_loss",
    "risk_distance",
    "target_price",
    "target_R",
    "nearest_structural_target_type",
    "nearest_structural_target_price",
    "min_rr_gate_passed",
    "rejection_reason",
    "session",
    "timeframe",
    "outcome",
    "order_sent",
    "telegram_sent",
    "broker_called",
]

RRMode = Literal["fixed_2r", "fixed_3r", "partial_2r_runner_3r", "structural_min_2r"]
RR_MODES: tuple[RRMode, ...] = ("fixed_2r", "fixed_3r", "partial_2r_runner_3r", "structural_min_2r")

SAFETY = {
    "research_only": True,
    "live_trading": False,
    "telegram_trade_alerts": False,
    "broker_execution": False,
    "order_send": False,
    "optimization": False,
    "parameter_mining": False,
    "xauusd_only": True,
}


@dataclass(frozen=True)
class Strategy5Config:
    symbol: str = "XAUUSD"
    timeframe: str = "M15"
    pip_buffer: float = 0.3
    min_rr: float = 2.0
    structural_cap_r: float = 4.0
    max_retest_candles: int = 6
    max_forward_candles: int = 32
    max_context_candles: int = 900


def _ensure_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]
    if "time" not in out.columns:
        return pd.DataFrame()
    out["time"] = pd.to_datetime(out["time"], utc=True, errors="coerce")
    for col in ("open", "high", "low", "close"):
        if col not in out.columns:
            return pd.DataFrame()
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if "tick_volume" in out.columns:
        out["tick_volume"] = pd.to_numeric(out["tick_volume"], errors="coerce").fillna(1)
    else:
        out["tick_volume"] = 1.0
    return out.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time").reset_index(drop=True)


def session_for_timestamp(ts: pd.Timestamp) -> str:
    hour = int(ts.hour)
    if 0 <= hour < 6:
        return "asia"
    if 6 <= hour < 12:
        return "london"
    if 12 <= hour < 17:
        return "ny_am"
    if 17 <= hour < 22:
        return "ny_pm"
    return "rollover"


def _level(level_type: str, price: float) -> dict[str, Any]:
    return {"type": level_type, "price": round(float(price), 4)}


def build_liquidity_levels(m15: pd.DataFrame, h1: pd.DataFrame, idx: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    row = m15.iloc[idx]
    ts = pd.Timestamp(row["time"])
    day_start = ts.floor("D")
    previous_day = m15[(m15["time"] >= day_start - pd.Timedelta(days=1)) & (m15["time"] < day_start)]
    current_day_before = m15[(m15["time"] >= day_start) & (m15["time"] < ts)]
    h1_before = h1[h1["time"] < ts].tail(8)
    lows: list[dict[str, Any]] = []
    highs: list[dict[str, Any]] = []
    if not previous_day.empty:
        lows.append(_level("previous_day_low", previous_day["low"].min()))
        highs.append(_level("previous_day_high", previous_day["high"].max()))
    for label, start_h, end_h in [("asia_range", 0, 6), ("london_range", 6, 11), ("ny_opening_range", 12, 14)]:
        window = current_day_before[
            (current_day_before["time"].dt.hour >= start_h) & (current_day_before["time"].dt.hour < end_h)
        ]
        if not window.empty:
            lows.append(_level(f"{label}_low", window["low"].min()))
            highs.append(_level(f"{label}_high", window["high"].max()))
    if not h1_before.empty:
        lows.append(_level("h1_swing_low", h1_before["low"].min()))
        highs.append(_level("h1_swing_high", h1_before["high"].max()))
    if len(current_day_before) >= 4:
        midpoint = (float(current_day_before["high"].max()) + float(current_day_before["low"].min())) / 2
        lows.append(_level("session_midpoint", midpoint))
        highs.append(_level("session_midpoint", midpoint))
        typical = (current_day_before["high"] + current_day_before["low"] + current_day_before["close"]) / 3
        volume = current_day_before["tick_volume"].replace(0, 1)
        vwap = float((typical * volume).sum() / volume.sum())
        lows.append(_level("vwap", vwap))
        highs.append(_level("vwap", vwap))
    return lows, highs


def _cisd(direction: str, confirmation: pd.Series, prior: pd.Series) -> bool:
    body = abs(float(confirmation["close"]) - float(confirmation["open"]))
    rng = max(float(confirmation["high"]) - float(confirmation["low"]), 0.0001)
    if direction == "LONG":
        return float(confirmation["close"]) > float(confirmation["open"]) and body / rng >= 0.45 and float(confirmation["close"]) > float(prior["high"])
    return float(confirmation["close"]) < float(confirmation["open"]) and body / rng >= 0.45 and float(confirmation["close"]) < float(prior["low"])


def _mss(direction: str, frame: pd.DataFrame, confirmation_idx: int) -> bool:
    lookback = frame.iloc[max(0, confirmation_idx - 5):confirmation_idx]
    if lookback.empty:
        return False
    current = frame.iloc[confirmation_idx]
    if direction == "LONG":
        return float(current["high"]) > float(lookback["high"].max())
    return float(current["low"]) < float(lookback["low"].min())


def _fvg(direction: str, frame: pd.DataFrame, confirmation_idx: int) -> bool:
    if confirmation_idx < 2:
        return False
    left = frame.iloc[confirmation_idx - 2]
    right = frame.iloc[confirmation_idx]
    if direction == "LONG":
        return float(right["low"]) > float(left["high"])
    return float(right["high"]) < float(left["low"])


def _nearest_target(direction: str, entry: float, levels: list[dict[str, Any]]) -> tuple[str | None, float | None]:
    if direction == "LONG":
        candidates = [lvl for lvl in levels if float(lvl["price"]) > entry]
        candidates.sort(key=lambda item: float(item["price"]))
    else:
        candidates = [lvl for lvl in levels if float(lvl["price"]) < entry]
        candidates.sort(key=lambda item: float(item["price"]), reverse=True)
    if not candidates:
        return None, None
    first = candidates[0]
    return str(first["type"]), float(first["price"])


def target_for_mode(direction: str, entry: float, risk: float, rr_mode: RRMode, structural_target: float | None, config: Strategy5Config) -> tuple[float | None, float | None]:
    if risk <= 0:
        return None, None
    if rr_mode == "fixed_2r":
        r = 2.0
    elif rr_mode == "fixed_3r":
        r = 3.0
    elif rr_mode == "partial_2r_runner_3r":
        r = 3.0
    else:
        if structural_target is None:
            return None, None
        raw_r = abs(float(structural_target) - float(entry)) / risk
        r = min(raw_r, config.structural_cap_r)
    target = entry + risk * r if direction == "LONG" else entry - risk * r
    return round(float(target), 4), round(float(r), 4)


def evaluate_outcome(direction: str, forward: pd.DataFrame, stop: float, target: float) -> str:
    if forward.empty:
        return "STILL_OPEN"
    for _, row in forward.iterrows():
        if direction == "LONG":
            hit_stop = float(row["low"]) <= stop
            hit_target = float(row["high"]) >= target
        else:
            hit_stop = float(row["high"]) >= stop
            hit_target = float(row["low"]) <= target
        if hit_stop and hit_target:
            return "AMBIGUOUS_SAME_CANDLE"
        if hit_target:
            return "TARGET_HIT"
        if hit_stop:
            return "STOP_HIT"
    last = pd.Timestamp(forward.iloc[-1]["time"])
    if last.date() != pd.Timestamp(forward.iloc[0]["time"]).date():
        return "EOD"
    return "TIMEOUT"


def empty_rejection(timestamp: Any, reason: str, *, rr_mode: RRMode = "fixed_2r") -> dict[str, Any]:
    return {
        "signal_timestamp": str(timestamp),
        "direction": "",
        "setup_mode": "manipulation_reclaim_confirmation_retest_expansion",
        "rr_mode": rr_mode,
        "swept_level_type": "",
        "swept_level_price": "",
        "reclaim_level": "",
        "cisd_detected": False,
        "mss_detected": False,
        "fvg_detected": False,
        "ifvg_detected": False,
        "bpr_detected": False,
        "entry_price": "",
        "stop_loss": "",
        "risk_distance": "",
        "target_price": "",
        "target_R": "",
        "nearest_structural_target_type": "",
        "nearest_structural_target_price": "",
        "min_rr_gate_passed": False,
        "rejection_reason": reason,
        "session": "",
        "timeframe": "M15",
        "outcome": "",
        "order_sent": False,
        "telegram_sent": False,
        "broker_called": False,
    }


def scan_strategy_5(market_data: dict[str, pd.DataFrame], config: Strategy5Config | None = None) -> dict[str, Any]:
    cfg = config or Strategy5Config()
    m15 = _ensure_frame(market_data.get("M15", pd.DataFrame()))
    h1 = _ensure_frame(market_data.get("H1", pd.DataFrame()))
    if m15.empty or h1.empty:
        row = empty_rejection("", "REQUIRED_DATA_MISSING")
        return _result([row], [], [row], cfg)

    candidates: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    start_idx = max(1, len(m15) - cfg.max_context_candles)
    for idx in range(start_idx, len(m15) - cfg.max_forward_candles - 1):
        row = m15.iloc[idx]
        prior = m15.iloc[idx - 1]
        lows, highs = build_liquidity_levels(m15, h1, idx)
        directions = [
            ("LONG", lows, highs, "low"),
            ("SHORT", highs, lows, "high"),
        ]
        for direction, sweep_levels, target_levels, side in directions:
            for level in sweep_levels:
                price = float(level["price"])
                swept = float(row["low"]) < price if direction == "LONG" else float(row["high"]) > price
                reclaimed = float(row["close"]) > price if direction == "LONG" else float(row["close"]) < price
                if not swept:
                    continue
                base = {
                    "signal_timestamp": pd.Timestamp(row["time"]).isoformat(),
                    "direction": direction,
                    "setup_mode": "manipulation_reclaim_confirmation_retest_expansion",
                    "swept_level_type": level["type"],
                    "swept_level_price": round(price, 4),
                    "reclaim_level": round(price, 4),
                    "session": session_for_timestamp(pd.Timestamp(row["time"])),
                    "timeframe": cfg.timeframe,
                    "order_sent": False,
                    "telegram_sent": False,
                    "broker_called": False,
                }
                if not reclaimed:
                    rejected.extend(_rows_for_all_modes(base, "NO_RECLAIM", cfg))
                    candidates.extend(_rows_for_all_modes(base, "NO_RECLAIM", cfg))
                    continue
                confirmation_idx = idx + 1
                confirmation = m15.iloc[confirmation_idx]
                cisd = _cisd(direction, confirmation, prior)
                mss = _mss(direction, m15, confirmation_idx)
                fvg = _fvg(direction, m15, confirmation_idx)
                displacement = cisd or mss
                if not displacement:
                    rejected.extend(_rows_for_all_modes(base | {"cisd_detected": cisd, "mss_detected": mss, "fvg_detected": fvg}, "NO_CISD_OR_MSS", cfg))
                    candidates.extend(_rows_for_all_modes(base | {"cisd_detected": cisd, "mss_detected": mss, "fvg_detected": fvg}, "NO_CISD_OR_MSS", cfg))
                    continue
                if not fvg:
                    rejected.extend(_rows_for_all_modes(base | {"cisd_detected": cisd, "mss_detected": mss, "fvg_detected": fvg}, "NO_DISPLACEMENT_ZONE", cfg))
                    candidates.extend(_rows_for_all_modes(base | {"cisd_detected": cisd, "mss_detected": mss, "fvg_detected": fvg}, "NO_DISPLACEMENT_ZONE", cfg))
                    continue
                retest_window = m15.iloc[confirmation_idx + 1: confirmation_idx + 1 + cfg.max_retest_candles]
                if retest_window.empty:
                    rejected.extend(_rows_for_all_modes(base | {"cisd_detected": cisd, "mss_detected": mss, "fvg_detected": fvg}, "REQUIRED_DATA_MISSING", cfg))
                    continue
                if direction == "LONG":
                    entry_hits = retest_window[retest_window["low"] <= price]
                    sweep_extreme = float(row["low"])
                    stop = round(sweep_extreme - cfg.pip_buffer, 4)
                else:
                    entry_hits = retest_window[retest_window["high"] >= price]
                    sweep_extreme = float(row["high"])
                    stop = round(sweep_extreme + cfg.pip_buffer, 4)
                if entry_hits.empty:
                    rejected.extend(_rows_for_all_modes(base | {"cisd_detected": cisd, "mss_detected": mss, "fvg_detected": fvg}, "NO_RETEST_ENTRY", cfg))
                    candidates.extend(_rows_for_all_modes(base | {"cisd_detected": cisd, "mss_detected": mss, "fvg_detected": fvg}, "NO_RETEST_ENTRY", cfg))
                    continue
                entry_row_idx = int(entry_hits.index[0])
                entry = round(price, 4)
                risk = round(abs(entry - stop), 4)
                target_type, structural_target = _nearest_target(direction, entry, target_levels)
                base_trade = base | {
                    "cisd_detected": cisd,
                    "mss_detected": mss,
                    "fvg_detected": fvg,
                    "ifvg_detected": False,
                    "bpr_detected": False,
                    "entry_price": entry,
                    "stop_loss": stop,
                    "risk_distance": risk,
                    "nearest_structural_target_type": target_type or "",
                    "nearest_structural_target_price": round(structural_target, 4) if structural_target is not None else "",
                }
                for mode in RR_MODES:
                    target, target_r = target_for_mode(direction, entry, risk, mode, structural_target, cfg)
                    min_gate = target_r is not None and target_r >= cfg.min_rr
                    row_out = _complete_row(base_trade, mode, target, target_r, min_gate, "")
                    candidates.append(row_out)
                    if risk <= 0:
                        rejected.append(row_out | {"rejection_reason": "ENTRY_TOO_FAR_OR_INVALID_RISK", "min_rr_gate_passed": False})
                    elif not min_gate:
                        rejected.append(row_out | {"rejection_reason": "TARGET_BELOW_2R", "min_rr_gate_passed": False})
                    elif structural_target is not None and target_r is not None and abs(structural_target - entry) / risk < target_r:
                        rejected.append(row_out | {"rejection_reason": "OPPOSING_RESISTANCE_BEFORE_2R", "min_rr_gate_passed": False})
                    else:
                        forward = m15.iloc[entry_row_idx + 1: entry_row_idx + 1 + cfg.max_forward_candles]
                        accepted.append(row_out | {"outcome": evaluate_outcome(direction, forward, stop, float(target))})
    return _result(candidates, accepted, rejected, cfg)


def _complete_row(base: dict[str, Any], mode: RRMode, target: float | None, target_r: float | None, min_gate: bool, reason: str) -> dict[str, Any]:
    return {
        **{field: "" for field in OUTPUT_FIELDS},
        **base,
        "rr_mode": mode,
        "target_price": "" if target is None else target,
        "target_R": "" if target_r is None else target_r,
        "min_rr_gate_passed": bool(min_gate),
        "rejection_reason": reason,
        "outcome": "",
        "order_sent": False,
        "telegram_sent": False,
        "broker_called": False,
    }


def _rows_for_all_modes(base: dict[str, Any], reason: str, cfg: Strategy5Config) -> list[dict[str, Any]]:
    return [_complete_row(base, mode, None, None, False, reason) for mode in RR_MODES]


def _result(candidates: list[dict[str, Any]], accepted: list[dict[str, Any]], rejected: list[dict[str, Any]], cfg: Strategy5Config) -> dict[str, Any]:
    summary = build_summary(candidates, accepted, rejected, cfg)
    return {"candidates": candidates, "accepted": accepted, "rejected": rejected, "summary": summary}


def build_summary(candidates: list[dict[str, Any]], accepted: list[dict[str, Any]], rejected: list[dict[str, Any]], cfg: Strategy5Config) -> dict[str, Any]:
    accepted_by_mode = Counter(str(row.get("rr_mode", "")) for row in accepted)
    rejected_reasons = Counter(str(row.get("rejection_reason", "")) for row in rejected)
    outcomes = Counter(str(row.get("outcome", "")) for row in accepted)
    mode_rows = []
    for mode in RR_MODES:
        mode_accepted = [r for r in accepted if r.get("rr_mode") == mode]
        mode_rows.append({
            "rr_mode": mode,
            "accepted": len(mode_accepted),
            "target_hit": sum(1 for r in mode_accepted if r.get("outcome") == "TARGET_HIT"),
            "stop_hit": sum(1 for r in mode_accepted if r.get("outcome") == "STOP_HIT"),
            "still_open_timeout_eod": sum(1 for r in mode_accepted if r.get("outcome") in {"STILL_OPEN", "TIMEOUT", "EOD"}),
        })
    verdicts = ["MECHANICS_BUILT_RESEARCH_ONLY", "REQUIRES_MANUAL_VISUAL_REVIEW"]
    if not accepted:
        verdicts.append("NO_2R_SPACE_FOUND")
    elif len(accepted) < 20:
        verdicts.append("SIGNALS_FOUND_BUT_SAMPLE_TOO_SMALL")
    else:
        verdicts.append("ASYMMETRIC_RR_PROMISING_REQUIRES_OOS")
    if accepted_by_mode.get("fixed_3r", 0) < accepted_by_mode.get("fixed_2r", 0):
        verdicts.append("MODE_3R_TOO_STRICT")
    if accepted_by_mode.get("structural_min_2r", 0) > 0:
        verdicts.append("STRUCTURAL_TARGET_MODE_REQUIRES_REVIEW")
    if rejected_reasons.get("TARGET_BELOW_2R", 0) > len(candidates) * 0.5 if candidates else False:
        verdicts.append("MIN_RR_GATE_TOO_RESTRICTIVE")
    return {
        "strategy": STRATEGY_NAME,
        "config": cfg.__dict__,
        "safety": SAFETY,
        "candidates_count": len(candidates),
        "accepted_count": len(accepted),
        "accepted_count_by_rr_mode": dict(accepted_by_mode),
        "rejected_count": len(rejected),
        "rejection_reason_distribution": dict(rejected_reasons),
        "long_short_split": dict(Counter(str(r.get("direction", "")) for r in candidates if r.get("direction"))),
        "session_split": dict(Counter(str(r.get("session", "")) for r in candidates if r.get("session"))),
        "swept_level_type_split": dict(Counter(str(r.get("swept_level_type", "")) for r in candidates if r.get("swept_level_type"))),
        "tag_distribution": {
            "cisd": sum(1 for r in candidates if r.get("cisd_detected") is True),
            "mss": sum(1 for r in candidates if r.get("mss_detected") is True),
            "fvg": sum(1 for r in candidates if r.get("fvg_detected") is True),
            "ifvg": sum(1 for r in candidates if r.get("ifvg_detected") is True),
            "bpr": sum(1 for r in candidates if r.get("bpr_detected") is True),
        },
        "min_rr_gate": {
            "pass": sum(1 for r in candidates if r.get("min_rr_gate_passed") is True),
            "fail": sum(1 for r in candidates if r.get("min_rr_gate_passed") is False),
        },
        "outcome_distribution": dict(outcomes),
        "mode_comparison": mode_rows,
        "verdicts": verdicts,
    }


def write_outputs(result: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "candidates": output_dir / "strategy_5_candidates.csv",
        "accepted": output_dir / "strategy_5_accepted_trades.csv",
        "rejected": output_dir / "strategy_5_rejected_candidates.csv",
        "summary": output_dir / "strategy_5_summary.json",
        "diagnostic": output_dir / "strategy_5_diagnostic.md",
        "mode_comparison": output_dir / "strategy_5_mode_comparison.csv",
    }
    _write_csv(paths["candidates"], result["candidates"])
    _write_csv(paths["accepted"], result["accepted"])
    _write_csv(paths["rejected"], result["rejected"])
    paths["summary"].write_text(json.dumps(result["summary"], indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(paths["mode_comparison"], result["summary"]["mode_comparison"])
    paths["diagnostic"].write_text(render_markdown(result["summary"]), encoding="utf-8")
    return {key: str(value) for key, value in paths.items()}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = OUTPUT_FIELDS if path.name != "strategy_5_mode_comparison.csv" else ["rr_mode", "accepted", "target_hit", "stop_hit", "still_open_timeout_eod"]
    if rows and path.name == "strategy_5_mode_comparison.csv":
        fieldnames = list(rows[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Strategy 5 Asymmetric Liquidity Reclaim 2R/3R Diagnostic",
        "",
        "Research-only diagnostic. No live readiness claim.",
        "",
        "## Safety",
        "- Strategy 5 only.",
        "- No Strategy 2/3/4, Adelin, live trading, broker execution, order_send, or Telegram trade alerts.",
        "- XAUUSD CSV files are read-only inputs.",
        "- No optimization or parameter mining.",
        "",
        "## Counts",
        f"- Candidates: {summary['candidates_count']}",
        f"- Accepted: {summary['accepted_count']}",
        f"- Rejected: {summary['rejected_count']}",
        "",
        "## RR Modes",
    ]
    for row in summary["mode_comparison"]:
        lines.append(f"- {row['rr_mode']}: accepted={row['accepted']}, target_hit={row['target_hit']}, stop_hit={row['stop_hit']}, still_open_timeout_eod={row['still_open_timeout_eod']}")
    lines.extend([
        "",
        "## Rejection Reasons",
        json.dumps(summary["rejection_reason_distribution"], indent=2, sort_keys=True),
        "",
        "## Splits",
        f"- Long/short: `{json.dumps(summary['long_short_split'], sort_keys=True)}`",
        f"- Session: `{json.dumps(summary['session_split'], sort_keys=True)}`",
        f"- Swept level type: `{json.dumps(summary['swept_level_type_split'], sort_keys=True)}`",
        f"- Tags: `{json.dumps(summary['tag_distribution'], sort_keys=True)}`",
        f"- Min RR gate: `{json.dumps(summary['min_rr_gate'], sort_keys=True)}`",
        f"- STILL_OPEN/TIMEOUT/EOD distribution included in outcomes: `{json.dumps(summary['outcome_distribution'], sort_keys=True)}`",
        "",
        "## Verdicts",
    ])
    lines.extend(f"- {verdict}" for verdict in summary["verdicts"])
    lines.extend([
        "",
        "## Limitation",
        "This is a deterministic diagnostic approximation of Manipulation -> Reclaim -> Confirmation -> Retest -> Expansion. It is not Strategy 3 with TP stretched, not a 1R strategy, and not deployable.",
    ])
    return "\n".join(lines) + "\n"
