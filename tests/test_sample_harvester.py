from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from dazro_trade.core.config import Settings
from dazro_trade.runtime.scanner import ScalpingScanner
from dazro_trade.storage import init_db
from dazro_trade.storage.database import get_connection
from dazro_trade.strategy.sample_harvester import (
    classify_volatility_regime,
    detect_manipulation_distribution,
    persist_harvested_sample,
)


def _h1_df(rows: list[tuple[float, float, float, float]], start: datetime | None = None) -> pd.DataFrame:
    base = start or datetime(2026, 5, 13, 6, 0, tzinfo=timezone.utc)
    return pd.DataFrame([
        {"time": base + timedelta(hours=idx), "o": o, "h": h, "l": l, "c": c, "vol": 100}
        for idx, (o, h, l, c) in enumerate(rows)
    ])


def _m15_df(rows: list[tuple[datetime, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame([
        {"time": t, "o": o, "h": h, "l": l, "c": c, "vol": 50} for (t, o, h, l, c) in rows
    ])


def test_detect_h1_high_manipulation_distribution(tmp_path):
    rows = [
        (4670.0, 4685.0, 4665.0, 4680.0),
        (4680.0, 4695.0, 4670.0, 4671.0),
        (4671.0, 4675.0, 4660.0, 4665.0),
    ]
    h1 = _h1_df(rows)
    dist_time = pd.Timestamp(h1.iloc[1]["time"]).to_pydatetime()
    m15 = _m15_df([
        (dist_time, 4680.0, 4695.0, 4678.0, 4690.0),
        (dist_time + timedelta(minutes=15), 4690.0, 4692.0, 4682.0, 4684.0),
        (dist_time + timedelta(minutes=30), 4684.0, 4684.5, 4672.0, 4673.0),
        (dist_time + timedelta(minutes=45), 4673.0, 4675.0, 4670.0, 4671.0),
    ])
    sample = detect_manipulation_distribution(h1, m15, session="London")
    assert sample is not None
    assert sample.reference_type == "H1_HIGH"
    assert sample.reference_price == 4685.0
    assert sample.manipulation_depth > 0
    assert sample.distribution_direction == "bearish"
    assert sample.session == "London"


def test_detect_h1_low_manipulation_distribution():
    rows = [
        (4680.0, 4685.0, 4670.0, 4675.0),
        (4675.0, 4683.0, 4655.0, 4682.0),
        (4682.0, 4685.0, 4670.0, 4673.0),
    ]
    h1 = _h1_df(rows)
    dist_time = pd.Timestamp(h1.iloc[1]["time"]).to_pydatetime()
    m15 = _m15_df([
        (dist_time + timedelta(minutes=15), 4680.0, 4682.0, 4655.0, 4666.0),
        (dist_time + timedelta(minutes=30), 4666.0, 4683.0, 4660.0, 4682.0),
    ])
    sample = detect_manipulation_distribution(h1, m15, session="NY")
    assert sample is not None
    assert sample.reference_type == "H1_LOW"
    assert sample.distribution_direction == "bullish"


def test_no_manipulation_returns_none():
    rows = [
        (4670.0, 4685.0, 4665.0, 4680.0),
        (4680.0, 4684.0, 4670.0, 4682.0),
        (4682.0, 4684.0, 4675.0, 4680.0),
    ]
    h1 = _h1_df(rows)
    assert detect_manipulation_distribution(h1, pd.DataFrame()) is None


def test_volatility_regime_normal_when_atr_close_to_median():
    rows = []
    base_time = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
    for i in range(120):
        rows.append({
            "time": base_time + timedelta(minutes=15 * i),
            "o": 4700.0,
            "h": 4702.0,
            "l": 4698.0,
            "c": 4701.0,
            "vol": 10,
        })
    regime = classify_volatility_regime(pd.DataFrame(rows))
    assert regime == "normal"


def test_volatility_regime_high_when_atr_expands():
    rows = []
    base_time = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
    for i in range(100):
        rows.append({
            "time": base_time + timedelta(minutes=15 * i),
            "o": 4700.0,
            "h": 4702.0,
            "l": 4698.0,
            "c": 4701.0,
            "vol": 10,
        })
    for i in range(20):
        rows.append({
            "time": base_time + timedelta(minutes=15 * (100 + i)),
            "o": 4700.0,
            "h": 4720.0,
            "l": 4685.0,
            "c": 4715.0,
            "vol": 10,
        })
    regime = classify_volatility_regime(pd.DataFrame(rows))
    assert regime == "high_volatility"


def test_volatility_regime_unknown_when_insufficient_data():
    rows = [{"time": datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc), "o": 4700.0, "h": 4701.0, "l": 4699.0, "c": 4700.5, "vol": 10}]
    assert classify_volatility_regime(pd.DataFrame(rows)) == "unknown"


def test_persist_harvested_sample_enforces_xau(tmp_path):
    rows = [
        (4670.0, 4685.0, 4665.0, 4680.0),
        (4680.0, 4695.0, 4670.0, 4671.0),
        (4671.0, 4675.0, 4660.0, 4665.0),
    ]
    h1 = _h1_df(rows)
    dist_time = pd.Timestamp(h1.iloc[1]["time"]).to_pydatetime()
    m15 = _m15_df([
        (dist_time + timedelta(minutes=15), 4685.0, 4695.0, 4675.0, 4671.0),
    ])
    sample = detect_manipulation_distribution(h1, m15, session="London")
    assert sample is not None
    db = str(tmp_path / "harvest.db")
    init_db(db)
    sample_id = persist_harvested_sample(sample, db_path=db)
    assert sample_id is not None
    with get_connection(db) as conn:
        row = conn.execute("SELECT * FROM mae_samples WHERE id = ?", (sample_id,)).fetchone()
    assert row["symbol"] == "XAUUSD"
    assert row["asset"] == "XAUUSD"
    assert row["reference_type"] == "H1_HIGH"


def test_scanner_analisi_includes_mae_section(tmp_path):
    db = str(tmp_path / "stats.db")
    init_db(db)
    settings = Settings(
        telegram_token="x",
        telegram_chat_id="1",
        mae_db_path=db,
        mae_engine_enabled=True,
        mae_sample_harvest_enabled=False,
    )
    scanner = ScalpingScanner(settings)
    scanner.latest_volatility_regime = "normal"
    scanner.latest_mae_stats_long = {
        "sample_count": 0,
        "mae_mean": 45.9,
        "mae_median": 45.9,
        "mae_p90": 98.8,
        "mae_p95": 123.5,
        "mae_max": 123.5,
        "confidence_level": "LOW_STATIC_FALLBACK",
        "uses_static_fallback": True,
    }
    scanner.latest_mae_stats_short = scanner.latest_mae_stats_long
    section = scanner._format_coordinator_section()
    assert "MAE STATS BUCKET" in section
    assert "H1_LOW (LONG side)" in section
    assert "H1_HIGH (SHORT side)" in section
    assert "static fallback" in section
