from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

SUPPORTED_TIMEFRAMES = ("M1", "M5", "M15", "H1", "H4", "D1")
REQUIRED_COLUMNS = {"time", "open", "high", "low", "close"}
ENCODING_FALLBACKS = ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1252", "latin-1")
SEPARATOR_FALLBACKS = (None, ",", ";", "\t", "|")
MIN_EXPECTED_COLUMNS = 4


def _detect_encoding(path: Path) -> str:
    with path.open("rb") as f:
        head = f.read(4)
    if head.startswith(b"\xff\xfe\x00\x00"):
        return "utf-32-le"
    if head.startswith(b"\x00\x00\xfe\xff"):
        return "utf-32-be"
    if head.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if head.startswith(b"\xfe\xff"):
        return "utf-16-be"
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    return "utf-8"


def _detect_separator(path: Path, encoding: str) -> str | None:
    try:
        with path.open("r", encoding=encoding, errors="strict", newline="") as f:
            sample = f.read(8192)
    except Exception:
        return None
    if not sample:
        return None
    head_line = sample.splitlines()[0] if sample.splitlines() else sample
    candidates = {sep: head_line.count(sep) for sep in (",", ";", "\t", "|")}
    best = max(candidates.items(), key=lambda kv: kv[1])
    if best[1] <= 0:
        return None
    return best[0]


def _read_csv_robust(path: Path) -> pd.DataFrame:
    detected_encoding = _detect_encoding(path)
    encodings = [detected_encoding] + [e for e in ENCODING_FALLBACKS if e != detected_encoding]
    last_exc: Exception | None = None
    for enc in encodings:
        try:
            sniffed_sep = _detect_separator(path, enc)
        except Exception:
            sniffed_sep = None
        separators = [sniffed_sep] if sniffed_sep else []
        for sep in separators + list(SEPARATOR_FALLBACKS):
            try:
                if sep is None:
                    df = pd.read_csv(path, encoding=enc, sep=None, engine="python")
                else:
                    df = pd.read_csv(path, encoding=enc, sep=sep)
            except UnicodeError as exc:
                last_exc = exc
                break
            except Exception as exc:
                last_exc = exc
                continue
            if len(df.columns) >= MIN_EXPECTED_COLUMNS:
                df.attrs["source_encoding"] = enc
                df.attrs["source_separator"] = sep if sep is not None else "sniff"
                return df
            last_exc = ValueError(f"parsed_columns_too_few={list(df.columns)}")
    raise ValueError(f"could not parse {path} with any encoding/separator combination: {last_exc}")


def _coerce_utc(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, utc=True, errors="coerce")
    return parsed


def _load_single_csv(path: Path) -> pd.DataFrame:
    df = _read_csv_robust(path)
    df.columns = [str(c).strip().strip("<>").lower() for c in df.columns]
    if "date" in df.columns and "time" in df.columns:
        df["time"] = df["date"].astype(str).str.strip() + " " + df["time"].astype(str).str.strip()
        df = df.drop(columns=["date"])
    elif "date" in df.columns and "time" not in df.columns:
        df = df.rename(columns={"date": "time"})
    rename_aliases = [
        ("tickvol", "tick_volume"),
        ("vol", "tick_volume"),
        ("volume", "tick_volume"),
        ("real_volume", "real_volume"),
        ("spr", "spread"),
    ]
    rename: dict[str, str] = {}
    taken_aliases: set[str] = set(df.columns)
    for col, alias in rename_aliases:
        if col in df.columns and alias not in taken_aliases:
            rename[col] = alias
            taken_aliases.add(alias)
    if rename:
        df = df.rename(columns=rename)
    drop_dupes = [c for c in ("vol", "tickvol", "volume", "real_volume", "spr") if c in df.columns and c not in rename.values()]
    if drop_dupes:
        df = df.drop(columns=drop_dupes)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"csv {path} missing columns: {sorted(missing)} | "
            f"found columns: {list(df.columns)} | "
            f"encoding={df.attrs.get('source_encoding')} "
            f"separator={df.attrs.get('source_separator')!r}"
        )
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
