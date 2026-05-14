from __future__ import annotations

import os
import tempfile

import pytest

from dazro_trade.strategy.mae_engine import (
    DEFAULT_XAUUSD_MAE_STATS,
    calculate_manipulation_depth,
    calculate_mae_stats,
)
from dazro_trade.storage import (
    DEFAULT_MAE_DB_PATH,
    cleanup_old_mae_samples,
    get_mae_samples,
    init_db,
    save_mae_sample,
)
from dazro_trade.storage.database import get_connection


@pytest.fixture()
def temp_db(tmp_path):
    db_path = str(tmp_path / "mae_test.db")
    init_db(db_path)
    yield db_path


def _approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(float(a) - float(b)) <= tol


def test_manipulation_depth_h1_high():
    depth = calculate_manipulation_depth("H1_HIGH", 4679.0, sample_high=4724.9)
    assert _approx(depth, 45.9)


def test_manipulation_depth_h1_low():
    depth = calculate_manipulation_depth("H1_LOW", 4679.0, sample_low=4633.1)
    assert _approx(depth, 45.9)


def test_manipulation_depth_invalid_reference_type():
    with pytest.raises(ValueError):
        calculate_manipulation_depth("H4_HIGH", 4679.0, sample_high=4700.0)


def test_stats_static_fallback_when_few_samples():
    stats = calculate_mae_stats([41, 53, 36, 69])
    assert stats["sample_count"] == 4
    assert stats["uses_static_fallback"] is True
    assert stats["confidence_level"] == "LOW_STATIC_FALLBACK"
    assert stats["mae_mean"] == DEFAULT_XAUUSD_MAE_STATS["mae_mean"]
    assert stats["sl_risk_distance"] == DEFAULT_XAUUSD_MAE_STATS["sl_risk_distance"]


def test_stats_high_confidence_with_300_samples():
    depths = [40.0 + (i % 50) for i in range(300)]
    stats = calculate_mae_stats(depths)
    assert stats["sample_count"] == 300
    assert stats["confidence_level"] == "HIGH"
    assert stats["uses_static_fallback"] is False
    assert stats["mae_mean"] > 0


def test_stats_levels_static_match_expected_values_h1_high():
    reference_price = 4679.0
    stats = calculate_mae_stats([])
    assert _approx(stats["entry_distance"], 45.9)
    assert _approx(stats["sl_risk_distance"], 98.8)
    assert _approx(stats["sl_conservative_distance"], 123.5)
    assert _approx(stats["tp1_distance"], 96.8)
    assert _approx(stats["tp2_distance"], 193.6)
    assert _approx(stats["tp3_distance"], 290.4)
    assert _approx(stats["tp4_distance"], 387.2)
    entry = reference_price + stats["entry_distance"]
    assert _approx(entry, 4724.9)


def test_stats_levels_static_h1_low():
    reference_price = 4679.0
    stats = calculate_mae_stats([])
    entry = reference_price - stats["entry_distance"]
    tp1 = reference_price + stats["tp1_distance"]
    tp4 = reference_price + stats["tp4_distance"]
    assert _approx(entry, 4633.1)
    assert _approx(tp1, 4775.8)
    assert _approx(tp4, 5066.2)


def test_save_sample_enforces_xau_only(temp_db):
    sample_id = save_mae_sample(
        {
            "reference_type": "H1_HIGH",
            "reference_price": 4679.0,
            "sample_high": 4724.9,
            "session": "London",
            "asset": "BTCUSD",
            "symbol": "BTCUSD",
        },
        db_path=temp_db,
    )
    rows = get_mae_samples(reference_type="H1_HIGH", session="London", db_path=temp_db)
    assert sample_id is not None
    assert len(rows) == 1
    assert rows[0]["asset"] == "XAUUSD"
    assert rows[0]["symbol"] == "XAUUSD"


def test_save_sample_defaults_to_xauusd(temp_db):
    save_mae_sample(
        {
            "reference_type": "H1_HIGH",
            "reference_price": 4679.0,
            "sample_high": 4724.9,
        },
        db_path=temp_db,
    )
    rows = get_mae_samples(db_path=temp_db)
    assert len(rows) == 1
    assert rows[0]["asset"] == "XAUUSD"
    assert rows[0]["symbol"] == "XAUUSD"


def test_save_sample_rejects_negative_depth(temp_db):
    sample_id = save_mae_sample(
        {
            "reference_type": "H1_HIGH",
            "reference_price": 4679.0,
            "sample_high": 4670.0,
        },
        db_path=temp_db,
    )
    assert sample_id is None
    rows = get_mae_samples(db_path=temp_db)
    assert rows == []


def test_get_mae_samples_applies_query_limit(temp_db):
    for i in range(1200):
        save_mae_sample(
            {
                "reference_type": "H1_HIGH",
                "reference_price": 4679.0,
                "sample_high": 4679.0 + 30 + (i % 50),
                "session": "London",
            },
            db_path=temp_db,
        )
    rows_default = get_mae_samples(session="London", reference_type="H1_HIGH", db_path=temp_db)
    assert len(rows_default) == 1000
    rows_explicit_higher = get_mae_samples(session="London", reference_type="H1_HIGH", limit=99999, db_path=temp_db)
    assert len(rows_explicit_higher) == 1000


def test_distance_mode_values_unchanged():
    stats = calculate_mae_stats([])
    assert stats["entry_distance"] == 45.9
    assert stats["sl_risk_distance"] == 98.8
    assert stats["sl_conservative_distance"] == 123.5


def test_cleanup_keeps_only_latest_per_bucket(temp_db):
    for i in range(50):
        save_mae_sample(
            {
                "reference_type": "H1_HIGH",
                "reference_price": 4679.0,
                "sample_high": 4679.0 + 30 + (i % 30),
                "session": "London",
            },
            db_path=temp_db,
        )
    with get_connection(temp_db) as conn:
        count_before = conn.execute("SELECT COUNT(*) FROM mae_samples").fetchone()[0]
    assert count_before == 50
    deleted = cleanup_old_mae_samples(max_samples_per_bucket=10, db_path=temp_db)
    assert deleted == 40
    with get_connection(temp_db) as conn:
        count_after = conn.execute("SELECT COUNT(*) FROM mae_samples").fetchone()[0]
    assert count_after == 10
