"""
Tests for the Adelin candle-behavior profiler (analytics package).

Covers:
- candle_features: geometry / volume / displacement / sweep / fvg / labels
- zone_features: touch detection, htf extraction
- zone_reactions: sweep+reclaim, break+continue, neutral reject, horizons
- candle_behavior_report: iterator, aggregations, ranking, markdown, writer
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from dazro_trade.analytics.candle_behavior_report import (
    NEWS_PROXIMITY_TODO_LABEL,
    aggregate_by_pattern,
    aggregate_by_pattern_zone_combo,
    aggregate_by_session,
    aggregate_by_zone_type,
    build_report,
    iterate_candle_behavior_records,
    rank_combos,
    render_markdown,
    write_report_files,
)
from dazro_trade.analytics.candle_features import (
    compute_candle_features,
    compute_candle_geometry,
    compute_displacement_score,
    compute_relative_volume,
    detect_fvg_ifvg,
    detect_sweep,
    label_candle_behavior,
)
from dazro_trade.analytics.zone_features import (
    Zone,
    ZoneTouch,
    candle_touches_zone,
    detect_touches,
    extract_htf_liquidity_zones,
)
from dazro_trade.analytics.zone_reactions import compute_reaction


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _series(o: float, h: float, l: float, c: float, vol: float = 100.0, t: datetime | None = None) -> pd.Series:
    data = {"open": o, "high": h, "low": l, "close": c, "tick_volume": vol}
    if t is not None:
        data["time"] = t
    return pd.Series(data)


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------
# candle_features.geometry
# ----------------------------------------------------------------------

def test_bullish_marubozu_geometry():
    g = compute_candle_geometry(_series(4700, 4710, 4699.5, 4709.5))
    assert g.direction == "BULL"
    assert g.body_to_range_ratio > 0.85
    assert g.close_position_in_range > 0.9


def test_doji_geometry_low_body_ratio():
    g = compute_candle_geometry(_series(4700, 4705, 4695, 4700.1))
    assert g.body_to_range_ratio < 0.05


def test_geometry_handles_zero_range():
    g = compute_candle_geometry(_series(4700, 4700, 4700, 4700))
    assert g.candle_range == 0.0
    assert g.body_to_range_ratio == 0.0


# ----------------------------------------------------------------------
# candle_features.volume + displacement
# ----------------------------------------------------------------------

def test_relative_volume_none_when_history_too_short():
    candle = _series(4700, 4710, 4690, 4705, vol=200)
    hist = _df([{"open": 4700, "high": 4705, "low": 4695, "close": 4702, "tick_volume": 100} for _ in range(5)])
    assert compute_relative_volume(candle, hist, lookback=20) is None


def test_relative_volume_ratio_computed():
    candle = _series(4700, 4710, 4690, 4705, vol=500)
    hist = _df([{"open": 4700, "high": 4705, "low": 4695, "close": 4702, "tick_volume": 100} for _ in range(20)])
    assert compute_relative_volume(candle, hist, lookback=20) == 5.0


def test_displacement_score_zero_without_history():
    candle = _series(4700, 4710, 4690, 4708)
    assert compute_displacement_score(candle, pd.DataFrame(), lookback=20) == 0.0


def test_displacement_score_large_when_body_far_above_mean():
    candle = _series(4700, 4730, 4699, 4728)
    hist = _df([{"open": 4700, "high": 4705, "low": 4695, "close": 4702, "tick_volume": 100} for _ in range(25)])
    score = compute_displacement_score(candle, hist, lookback=20)
    assert score >= 10.0


# ----------------------------------------------------------------------
# candle_features.sweep + fvg
# ----------------------------------------------------------------------

def test_detect_sweep_above_and_reclaim():
    hist = _df([{"open": 4700, "high": 4710, "low": 4695, "close": 4705, "tick_volume": 100} for _ in range(10)])
    candle = _series(4700, 4720, 4699, 4708)
    info = detect_sweep(candle, hist, lookback=10)
    assert info.swept_high is True
    assert info.reclaim_after_sweep is True


def test_detect_fvg_bullish_gap():
    win = _df([
        {"open": 4700, "high": 4705, "low": 4695, "close": 4702, "tick_volume": 100},
        {"open": 4702, "high": 4720, "low": 4700, "close": 4718, "tick_volume": 200},
        {"open": 4718, "high": 4725, "low": 4707, "close": 4722, "tick_volume": 150},
    ])
    info = detect_fvg_ifvg(win)
    assert info.fvg_created is True
    assert info.fvg_direction == "BULL"


def test_label_behavior_continuation_when_displacement_and_strong_body():
    geometry = compute_candle_geometry(_series(4700, 4720, 4699, 4718))
    labels = label_candle_behavior(geometry, displacement=2.5, sweep=detect_sweep(_series(4700, 4720, 4699, 4718), _df([{"open": 4700, "high": 4705, "low": 4695, "close": 4702, "tick_volume": 100} for _ in range(5)])), fvg=detect_fvg_ifvg(pd.DataFrame()))
    assert labels["continuation_candidate"] is True


def test_compute_candle_features_end_to_end():
    hist = _df([{"open": 4700, "high": 4705, "low": 4695, "close": 4702, "tick_volume": 100} for _ in range(25)])
    candle = _series(4700, 4730, 4699, 4728, vol=500)
    feats = compute_candle_features(candle, hist)
    assert feats["direction"] == "BULL"
    assert feats["continuation_candidate"] is True
    assert feats["swept_high"] is True


# ----------------------------------------------------------------------
# zone_features
# ----------------------------------------------------------------------

def test_candle_touches_zone_band():
    z = Zone(type="fvg", top=4710, bottom=4705)
    res = candle_touches_zone(4708, 4706, z)
    assert res is not None
    assert res.touched_center is True


def test_candle_touches_zone_no_overlap():
    z = Zone(type="fvg", top=4710, bottom=4705)
    res = candle_touches_zone(4704, 4700, z)
    assert res is None


def test_detect_touches_thin_zone():
    z = Zone(type="h1_liquidity", top=4700, bottom=4700)
    candle = _series(4700, 4702, 4699, 4701, t=datetime(2026, 5, 1, tzinfo=timezone.utc))
    res = detect_touches(candle, [z])
    assert len(res) == 1


def test_extract_htf_liquidity_zones_respects_cutoff():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    h1 = _df([
        {"time": base + timedelta(hours=i), "open": 4700, "high": 4710 + i, "low": 4690 - i, "close": 4705}
        for i in range(20)
    ])
    zones = extract_htf_liquidity_zones({"H1": h1}, cutoff=base + timedelta(hours=10), lookback_per_tf={"H1": 5})
    assert len(zones) == 10
    assert all(z.type == "h1_liquidity" for z in zones)


# ----------------------------------------------------------------------
# zone_reactions
# ----------------------------------------------------------------------

def test_compute_reaction_sell_side_sweep_and_reclaim():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    z = Zone(type="h1_liquidity", top=4690, bottom=4690, side="sell_side")
    touch = ZoneTouch(zone=z, candle_time=base, candle_high=4691.5, candle_low=4685.0, touched_top=True, touched_bottom=True, touched_center=True)
    future = _df([{"time": base + timedelta(minutes=i + 1), "open": 4691 + i, "high": 4693 + i, "low": 4690 + i - 1, "close": 4692 + i, "tick_volume": 50} for i in range(5)])
    r = compute_reaction(touch, touch_candle_close=4691.0, touch_candle_volume=150.0, future=future)
    assert r.did_sweep is True
    assert r.did_reclaim is True


def test_compute_reaction_buy_side_break_and_continue():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    z = Zone(type="h1_liquidity", top=4700, bottom=4700, side="buy_side")
    touch = ZoneTouch(zone=z, candle_time=base, candle_high=4705.0, candle_low=4699.5, touched_top=True, touched_bottom=True, touched_center=True)
    future = _df([{"time": base + timedelta(minutes=i + 1), "open": 4705 + i * 2, "high": 4708 + i * 2, "low": 4704 + i * 2, "close": 4707 + i * 2, "tick_volume": 50} for i in range(5)])
    r = compute_reaction(touch, touch_candle_close=4705.0, touch_candle_volume=150.0, future=future)
    assert r.did_break_and_continue is True
    assert r.did_reclaim is False


def test_compute_reaction_horizons_partial_when_future_short():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    z = Zone(type="fvg", top=4710, bottom=4705, side="neutral")
    touch = ZoneTouch(zone=z, candle_time=base, candle_high=4708, candle_low=4706, touched_top=False, touched_bottom=False, touched_center=True)
    future = _df([{"time": base + timedelta(minutes=1), "open": 4707, "high": 4708, "low": 4706, "close": 4707, "tick_volume": 50}])
    r = compute_reaction(touch, touch_candle_close=4707.0, touch_candle_volume=100.0, future=future, horizons=(1, 3, 5))
    assert r.reaction_at[1] is not None
    assert r.reaction_at[3] is None
    assert r.reaction_at[5] is None


def test_compute_reaction_no_future_returns_none_horizons():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    z = Zone(type="fvg", top=4710, bottom=4705, side="neutral")
    touch = ZoneTouch(zone=z, candle_time=base, candle_high=4708, candle_low=4706, touched_top=False, touched_bottom=False, touched_center=True)
    r = compute_reaction(touch, touch_candle_close=4707.0, touch_candle_volume=100.0, future=pd.DataFrame())
    assert all(v is None for v in r.reaction_at.values())


# ----------------------------------------------------------------------
# candle_behavior_report
# ----------------------------------------------------------------------

def _synthetic_market(n: int = 60) -> pd.DataFrame:
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        sign = 1 if i % 3 == 0 else -1
        rows.append({
            "time": base + timedelta(minutes=i * 5),
            "open": 4700 + i,
            "high": 4710 + i,
            "low": 4690 + i,
            "close": 4702 + i * sign * 0.5,
            "tick_volume": 100 + i,
        })
    return pd.DataFrame(rows)


def test_iterate_candle_behavior_records_basic():
    df = _synthetic_market(60)
    zones = [Zone(type="h1_liquidity", top=4750, bottom=4750, side="buy_side", timeframe="H1")]
    records = iterate_candle_behavior_records(df, zones)
    assert len(records) > 0
    assert all(r.pattern_label in {"none", "absorption", "continuation", "rejection"} or r.pattern_label.startswith("multiple:") for r in records)


def test_aggregate_by_pattern_creates_buckets():
    df = _synthetic_market(80)
    zones = [Zone(type="h1_liquidity", top=4750, bottom=4750, side="buy_side", timeframe="H1")]
    records = iterate_candle_behavior_records(df, zones)
    agg = aggregate_by_pattern(records)
    assert "none" in agg or "continuation" in agg


def test_aggregate_by_zone_type():
    df = _synthetic_market(80)
    zones = [
        Zone(type="h1_liquidity", top=4750, bottom=4750, side="buy_side", timeframe="H1"),
        Zone(type="fvg", top=4720, bottom=4715, side="neutral", timeframe="M5"),
    ]
    records = iterate_candle_behavior_records(df, zones)
    agg = aggregate_by_zone_type(records)
    assert "h1_liquidity" in agg or "fvg" in agg


def test_aggregate_by_session_uses_provided_session_fn():
    df = _synthetic_market(60)
    zones = [Zone(type="h1_liquidity", top=4750, bottom=4750, side="buy_side", timeframe="H1")]
    records = iterate_candle_behavior_records(df, zones, session_for_time=lambda t: "London")
    agg = aggregate_by_session(records)
    assert "London" in agg


def test_rank_combos_returns_best_and_worst_keys():
    df = _synthetic_market(80)
    zones = [Zone(type="h1_liquidity", top=4750, bottom=4750, side="buy_side", timeframe="H1")]
    records = iterate_candle_behavior_records(df, zones)
    combos = aggregate_by_pattern_zone_combo(records)
    ranking = rank_combos(combos, horizon=5, min_touches=1)
    assert "best_combos" in ranking
    assert "worst_combos" in ranking


def test_build_report_includes_all_sections():
    df = _synthetic_market(80)
    zones = [Zone(type="h1_liquidity", top=4750, bottom=4750, side="buy_side", timeframe="H1")]
    records = iterate_candle_behavior_records(df, zones)
    report = build_report(records, min_touches_for_ranking=1)
    for k in ("overall", "by_pattern", "by_zone_type", "by_pattern_zone_combo", "by_session", "ranking", "config"):
        assert k in report
    assert report["config"]["news_proximity"] == NEWS_PROXIMITY_TODO_LABEL


def test_render_markdown_smoke():
    df = _synthetic_market(80)
    zones = [Zone(type="h1_liquidity", top=4750, bottom=4750, side="buy_side", timeframe="H1")]
    records = iterate_candle_behavior_records(df, zones)
    report = build_report(records, min_touches_for_ranking=1)
    md = render_markdown(report)
    for header in ("# Adelin candle-behavior + zone-reaction profile", "## Overall", "### By candle pattern", "### By zone type", "## Best / worst combos"):
        assert header in md


def test_write_report_files_creates_both_json_and_md():
    df = _synthetic_market(80)
    zones = [Zone(type="h1_liquidity", top=4750, bottom=4750, side="buy_side", timeframe="H1")]
    records = iterate_candle_behavior_records(df, zones)
    report = build_report(records, min_touches_for_ranking=1)
    with tempfile.TemporaryDirectory() as tmp:
        paths = write_report_files(output_dir=tmp, report=report)
        assert Path(paths["report_json"]).exists()
        assert Path(paths["report_md"]).exists()
        payload = json.loads(Path(paths["report_json"]).read_text(encoding="utf-8"))
        assert "overall" in payload
        assert "by_pattern" in payload


# ----------------------------------------------------------------------
# Edge cases
# ----------------------------------------------------------------------

def test_iterate_returns_empty_when_min_history_too_large():
    df = _synthetic_market(10)
    zones = [Zone(type="h1_liquidity", top=4750, bottom=4750, side="buy_side", timeframe="H1")]
    records = iterate_candle_behavior_records(df, zones)
    assert records == []
