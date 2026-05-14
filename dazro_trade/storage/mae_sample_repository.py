from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from dazro_trade.storage.database import DEFAULT_MAE_DB_PATH, get_connection, init_db

log = logging.getLogger(__name__)

XAU_ASSET = "XAUUSD"
XAU_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "H1"
DEFAULT_SETUP_TYPE = "manipulation_distribution"
DEFAULT_QUERY_LIMIT = 1000
DEFAULT_RETENTION_PER_BUCKET = 5000

_VALID_REFERENCE_TYPES = {"H1_HIGH", "H1_LOW"}

_SAMPLE_COLUMNS = [
    "created_at",
    "candle_time",
    "asset",
    "symbol",
    "timeframe",
    "session",
    "reference_type",
    "reference_price",
    "h1_open",
    "h1_high",
    "h1_low",
    "h1_close",
    "sample_open",
    "sample_high",
    "sample_low",
    "sample_close",
    "manipulation_extreme",
    "manipulation_depth",
    "distribution_direction",
    "distribution_reached",
    "distribution_reach_max_price",
    "distribution_reach_distance",
    "max_favorable_excursion_price",
    "mfe_distance",
    "tp1_reached",
    "tp2_reached",
    "tp3_reached",
    "tp4_reached",
    "setup_type",
    "volatility_regime",
    "valid_sample",
    "rejection_reason",
    "notes",
]


def _compute_manipulation_depth(reference_type: str, reference_price: float, sample_high: float | None, sample_low: float | None) -> float:
    if reference_type == "H1_HIGH":
        if sample_high is None:
            raise ValueError("sample_high required for H1_HIGH manipulation depth")
        return float(sample_high) - float(reference_price)
    if reference_type == "H1_LOW":
        if sample_low is None:
            raise ValueError("sample_low required for H1_LOW manipulation depth")
        return float(reference_price) - float(sample_low)
    raise ValueError(f"invalid reference_type: {reference_type}")


def save_mae_sample(sample: dict[str, Any], *, db_path: str = DEFAULT_MAE_DB_PATH) -> int | None:
    payload = dict(sample)
    payload["asset"] = XAU_ASSET
    payload["symbol"] = XAU_SYMBOL
    payload.setdefault("timeframe", DEFAULT_TIMEFRAME)
    payload.setdefault("setup_type", DEFAULT_SETUP_TYPE)
    payload.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    payload.setdefault("valid_sample", 1)

    reference_type = payload.get("reference_type")
    if reference_type not in _VALID_REFERENCE_TYPES:
        log.info("sample rejected because reference_type invalid: %s", reference_type)
        return None
    if payload.get("reference_price") in (None, "", 0):
        log.info("sample rejected because reference_price missing")
        return None

    if payload.get("manipulation_depth") in (None, ""):
        try:
            payload["manipulation_depth"] = _compute_manipulation_depth(
                reference_type,
                float(payload["reference_price"]),
                payload.get("sample_high"),
                payload.get("sample_low"),
            )
        except ValueError as exc:
            log.info("sample rejected because manipulation_depth uncomputable: %s", exc)
            return None

    depth = float(payload["manipulation_depth"])
    if depth <= 0:
        log.info("sample rejected because manipulation_depth <= 0 (depth=%s)", depth)
        return None
    payload["manipulation_depth"] = depth

    columns = ", ".join(_SAMPLE_COLUMNS)
    placeholders = ", ".join("?" for _ in _SAMPLE_COLUMNS)
    values = [payload.get(col) for col in _SAMPLE_COLUMNS]

    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(f"INSERT INTO mae_samples ({columns}) VALUES ({placeholders})", values)
        sample_id = cursor.lastrowid
    log.info("sample saved id=%s symbol=%s reference_type=%s depth=%.2f", sample_id, payload["symbol"], reference_type, depth)
    return sample_id


def get_mae_samples(
    *,
    timeframe: str = DEFAULT_TIMEFRAME,
    session: str | None = None,
    reference_type: str | None = None,
    setup_type: str = DEFAULT_SETUP_TYPE,
    volatility_regime: str | None = None,
    limit: int = DEFAULT_QUERY_LIMIT,
    db_path: str = DEFAULT_MAE_DB_PATH,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    limit = min(int(limit), DEFAULT_QUERY_LIMIT)
    where = [
        "asset = ?",
        "symbol = ?",
        "timeframe = ?",
        "setup_type = ?",
        "valid_sample = 1",
    ]
    params: list[Any] = [XAU_ASSET, XAU_SYMBOL, timeframe, setup_type]
    if session is not None:
        where.append("session = ?")
        params.append(session)
    if reference_type is not None:
        where.append("reference_type = ?")
        params.append(reference_type)
    if volatility_regime is not None:
        where.append("volatility_regime = ?")
        params.append(volatility_regime)
    sql = f"SELECT * FROM mae_samples WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    log.info("query limited to max_samples_per_bucket=%s returned=%s", limit, len(rows))
    return [dict(row) for row in rows]


def cleanup_old_mae_samples(
    *,
    max_samples_per_bucket: int = DEFAULT_RETENTION_PER_BUCKET,
    db_path: str = DEFAULT_MAE_DB_PATH,
) -> int:
    init_db(db_path)
    deleted_total = 0
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT asset, symbol, timeframe, session, reference_type, setup_type, volatility_regime, COUNT(*) AS n "
            "FROM mae_samples WHERE asset = ? AND symbol = ? GROUP BY asset, symbol, timeframe, session, reference_type, setup_type, volatility_regime",
            (XAU_ASSET, XAU_SYMBOL),
        )
        buckets = cursor.fetchall()
        for bucket in buckets:
            count = int(bucket["n"])
            if count <= max_samples_per_bucket:
                continue
            to_delete = count - max_samples_per_bucket
            where = [
                "asset = ?",
                "symbol = ?",
                "timeframe = ?",
                "setup_type = ?",
            ]
            params: list[Any] = [bucket["asset"], bucket["symbol"], bucket["timeframe"], bucket["setup_type"]]
            if bucket["session"] is None:
                where.append("session IS NULL")
            else:
                where.append("session = ?")
                params.append(bucket["session"])
            if bucket["reference_type"] is None:
                where.append("reference_type IS NULL")
            else:
                where.append("reference_type = ?")
                params.append(bucket["reference_type"])
            if bucket["volatility_regime"] is None:
                where.append("volatility_regime IS NULL")
            else:
                where.append("volatility_regime = ?")
                params.append(bucket["volatility_regime"])
            delete_sql = (
                f"DELETE FROM mae_samples WHERE id IN ("
                f"SELECT id FROM mae_samples WHERE {' AND '.join(where)} "
                f"ORDER BY created_at ASC LIMIT ?)"
            )
            params.append(to_delete)
            cursor.execute(delete_sql, params)
            deleted_total += cursor.rowcount
    log.info("cleanup completed: %s old samples deleted", deleted_total)
    return deleted_total


__all__ = [
    "DEFAULT_QUERY_LIMIT",
    "DEFAULT_RETENTION_PER_BUCKET",
    "cleanup_old_mae_samples",
    "get_mae_samples",
    "save_mae_sample",
]
