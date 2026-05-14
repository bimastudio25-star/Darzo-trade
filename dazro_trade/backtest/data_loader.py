from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

SUPPORTED_TIMEFRAMES = ("M1", "M5", "M15", "H1", "H4", "D1")
REQUIRED_COLUMNS = {"time", "open", "high", "low", "close"}


def _coerce_utc(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, utc=True, errors="coerce")
    return parsed


def _load_single_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols_lower = {c.lower(): c for c in df.columns}
    rename = {}
    for canonical in ("time", "open", "high", "low", "close", "tick_volume", "spread"):
        if canonical in cols_lower:
            rename[cols_lower[canonical]] = canonical
        elif canonical == "tick_volume" and "volume" in cols_lower:
            rename[cols_lower["volume"]] = "tick_volume"
    df = df.rename(columns=rename)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"csv {path} missing columns: {missing}")
    df["time"] = _coerce_utc(df["time"])
    df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    return df


def load_csv_timeframes(
    symbol: str,
    timeframes: list[str],
    *,
    data_dir: str = "data",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, pd.DataFrame]:
    base = Path(data_dir) / symbol
    out: dict[str, pd.DataFrame] = {}
    for tf in timeframes:
        if tf not in SUPPORTED_TIMEFRAMES:
            log.warning("backtest_unknown_timeframe tf=%s", tf)
            continue
        path = base / f"{tf}.csv"
        if not path.exists():
            log.warning("backtest_csv_missing path=%s", path)
            continue
        df = _load_single_csv(path)
        if date_from is not None:
            df = df[df["time"] >= _utc_timestamp(date_from)]
        if date_to is not None:
            df = df[df["time"] <= _utc_timestamp(date_to)]
        df = df.reset_index(drop=True)
        out[tf] = df
        log.info("backtest_csv_loaded tf=%s rows=%s path=%s", tf, len(df), path)
    return out


def _utc_timestamp(value: datetime) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def slice_market_data_up_to(market_data: dict[str, pd.DataFrame], cutoff: datetime) -> dict[str, pd.DataFrame]:
    cutoff_ts = _utc_timestamp(cutoff)
    sliced: dict[str, pd.DataFrame] = {}
    for tf, df in market_data.items():
        if df is None or len(df) == 0:
            sliced[tf] = df if df is not None else pd.DataFrame()
            continue
        sliced[tf] = df[df["time"] <= cutoff_ts].reset_index(drop=True)
    return sliced


__all__ = ["SUPPORTED_TIMEFRAMES", "load_csv_timeframes", "slice_market_data_up_to"]
