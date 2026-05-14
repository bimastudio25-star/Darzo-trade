from __future__ import annotations

import pytest

from dazro_trade.analysis.liquidity_expansion import calculate_h1_liquidity_levels
from dazro_trade.storage import init_db, save_mae_sample
from dazro_trade.strategy.mae_engine import load_mae_stats_for_bucket


def _approx(a: float, b: float, tol: float = 0.05) -> bool:
    return abs(float(a) - float(b)) <= tol


def test_h1_high_levels_with_no_stats_use_static_defaults():
    levels = calculate_h1_liquidity_levels(4679.0, "H1_HIGH")
    assert _approx(levels.entry, 4724.9)
    assert _approx(levels.sl_risk, 4777.8)
    assert _approx(levels.sl_conservative, 4802.5)
    assert _approx(levels.tp1, 4582.2)
    assert _approx(levels.tp2, 4485.4)
    assert _approx(levels.tp3, 4388.6)
    assert _approx(levels.tp4, 4291.8)


def test_h1_low_levels_with_no_stats_use_static_defaults():
    levels = calculate_h1_liquidity_levels(4679.0, "H1_LOW")
    assert _approx(levels.entry, 4633.1)
    assert _approx(levels.sl_risk, 4580.2)
    assert _approx(levels.sl_conservative, 4555.5)
    assert _approx(levels.tp1, 4775.8)
    assert _approx(levels.tp2, 4872.6)
    assert _approx(levels.tp3, 4969.4)
    assert _approx(levels.tp4, 5066.2)


def test_mae_stats_override_distances_in_levels():
    stats = {
        "entry_distance": 30.0,
        "sl_risk_distance": 60.0,
        "sl_conservative_distance": 80.0,
        "tp1_distance": 50.0,
        "tp2_distance": 100.0,
        "tp3_distance": 150.0,
        "tp4_distance": 200.0,
    }
    levels = calculate_h1_liquidity_levels(4679.0, "H1_HIGH", mae_stats=stats)
    assert _approx(levels.entry, 4709.0)
    assert _approx(levels.sl_risk, 4739.0)
    assert _approx(levels.sl_conservative, 4759.0)
    assert _approx(levels.tp1, 4629.0)


def test_load_mae_stats_returns_static_when_db_empty(tmp_path):
    db = str(tmp_path / "empty.db")
    init_db(db)
    stats = load_mae_stats_for_bucket(session="London", reference_type="H1_HIGH", db_path=db)
    assert stats["uses_static_fallback"] is True
    assert stats["confidence_level"] == "LOW_STATIC_FALLBACK"
    assert _approx(stats["entry_distance"], 45.9)
    assert _approx(stats["sl_risk_distance"], 98.8)


def test_load_mae_stats_uses_dynamic_when_30_plus_samples(tmp_path):
    db = str(tmp_path / "with_samples.db")
    init_db(db)
    for i in range(40):
        save_mae_sample(
            {
                "reference_type": "H1_HIGH",
                "reference_price": 4679.0,
                "sample_high": 4679.0 + 30 + (i % 20),
                "session": "London",
            },
            db_path=db,
        )
    stats = load_mae_stats_for_bucket(session="London", reference_type="H1_HIGH", db_path=db)
    assert stats["uses_static_fallback"] is False
    assert stats["sample_count"] == 40
    assert stats["confidence_level"] == "LOW"


def test_load_mae_stats_query_limit_enforced(tmp_path):
    db = str(tmp_path / "many.db")
    init_db(db)
    for i in range(1500):
        save_mae_sample(
            {
                "reference_type": "H1_HIGH",
                "reference_price": 4679.0,
                "sample_high": 4679.0 + 30 + (i % 30),
                "session": "London",
            },
            db_path=db,
        )
    stats = load_mae_stats_for_bucket(session="London", reference_type="H1_HIGH", db_path=db)
    assert stats["sample_count"] == 1000
    assert stats["confidence_level"] == "HIGH"


def test_load_mae_stats_isolates_buckets(tmp_path):
    db = str(tmp_path / "buckets.db")
    init_db(db)
    for i in range(35):
        save_mae_sample(
            {
                "reference_type": "H1_HIGH",
                "reference_price": 4679.0,
                "sample_high": 4679.0 + 50,
                "session": "London",
            },
            db_path=db,
        )
    london_high = load_mae_stats_for_bucket(session="London", reference_type="H1_HIGH", db_path=db)
    london_low = load_mae_stats_for_bucket(session="London", reference_type="H1_LOW", db_path=db)
    ny_high = load_mae_stats_for_bucket(session="NY", reference_type="H1_HIGH", db_path=db)
    assert london_high["sample_count"] == 35
    assert london_low["uses_static_fallback"] is True
    assert ny_high["uses_static_fallback"] is True


def test_mae_db_failure_falls_back_to_static(tmp_path):
    bad_path = str(tmp_path / "nonexistent_dir" / "missing.db")
    # init_db will create the dir/file even if missing — so this still returns valid static stats
    stats = load_mae_stats_for_bucket(session="London", reference_type="H1_HIGH", db_path=bad_path)
    assert stats["uses_static_fallback"] is True
