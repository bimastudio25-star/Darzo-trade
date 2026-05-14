from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

DEFAULT_MAE_DB_PATH = "data/darzo_trade.db"


MAE_SAMPLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS mae_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    candle_time TEXT,
    asset TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    session TEXT,
    reference_type TEXT NOT NULL,
    reference_price REAL NOT NULL,
    h1_open REAL,
    h1_high REAL,
    h1_low REAL,
    h1_close REAL,
    sample_open REAL,
    sample_high REAL,
    sample_low REAL,
    sample_close REAL,
    manipulation_extreme REAL,
    manipulation_depth REAL NOT NULL,
    distribution_direction TEXT,
    distribution_reached INTEGER DEFAULT 0,
    distribution_reach_max_price REAL,
    distribution_reach_distance REAL,
    max_favorable_excursion_price REAL,
    mfe_distance REAL,
    tp1_reached INTEGER DEFAULT 0,
    tp2_reached INTEGER DEFAULT 0,
    tp3_reached INTEGER DEFAULT 0,
    tp4_reached INTEGER DEFAULT 0,
    setup_type TEXT DEFAULT 'manipulation_distribution',
    volatility_regime TEXT,
    valid_sample INTEGER DEFAULT 1,
    rejection_reason TEXT,
    notes TEXT
);
"""

MAE_SAMPLES_INDEX_LOOKUP = """
CREATE INDEX IF NOT EXISTS idx_mae_samples_lookup
ON mae_samples (
    asset,
    symbol,
    timeframe,
    session,
    reference_type,
    setup_type,
    valid_sample,
    created_at
);
"""

MAE_SAMPLES_INDEX_XAU_REFERENCE = """
CREATE INDEX IF NOT EXISTS idx_mae_samples_xau_reference
ON mae_samples (
    symbol,
    reference_type,
    valid_sample
);
"""


def _ensure_parent_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def init_db(db_path: str = DEFAULT_MAE_DB_PATH) -> str:
    _ensure_parent_dir(db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(MAE_SAMPLES_SCHEMA)
        cursor.execute(MAE_SAMPLES_INDEX_LOOKUP)
        cursor.execute(MAE_SAMPLES_INDEX_XAU_REFERENCE)
        conn.commit()
    log.info("database initialized path=%s", db_path)
    return db_path


@contextmanager
def get_connection(db_path: str = DEFAULT_MAE_DB_PATH) -> Iterator[sqlite3.Connection]:
    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


__all__ = ["DEFAULT_MAE_DB_PATH", "get_connection", "init_db"]
