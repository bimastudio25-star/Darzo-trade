from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from dazro_trade.backtest.data_loader import REQUIRED_COLUMNS, SUPPORTED_TIMEFRAMES, _load_single_csv

log = logging.getLogger(__name__)

EXPECTED_INTERVAL_MINUTES: dict[str, int] = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}

GAP_TOLERANCE_FACTOR = 1.5
WEEKEND_GAP_MAX_HOURS = 75


@dataclass(frozen=True)
class TimeframeValidation:
    timeframe: str
    path: str
    rows: int
    first_time: str | None
    last_time: str | None
    missing_columns: list[str] = field(default_factory=list)
    duplicate_timestamps: int = 0
    non_monotonic_rows: int = 0
    naive_timestamps: int = 0
    high_lt_low_rows: int = 0
    negative_or_zero_prices: int = 0
    suspected_gaps: list[dict[str, Any]] = field(default_factory=list)
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "path": self.path,
            "rows": self.rows,
            "first_time": self.first_time,
            "last_time": self.last_time,
            "missing_columns": list(self.missing_columns),
            "duplicate_timestamps": self.duplicate_timestamps,
            "non_monotonic_rows": self.non_monotonic_rows,
            "naive_timestamps": self.naive_timestamps,
            "high_lt_low_rows": self.high_lt_low_rows,
            "negative_or_zero_prices": self.negative_or_zero_prices,
            "suspected_gaps": list(self.suspected_gaps),
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ValidationReport:
    symbol: str
    data_dir: str
    per_timeframe: dict[str, TimeframeValidation]

    @property
    def ok(self) -> bool:
        return all(v.ok for v in self.per_timeframe.values()) and bool(self.per_timeframe)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "data_dir": self.data_dir,
            "ok": self.ok,
            "per_timeframe": {tf: v.to_dict() for tf, v in self.per_timeframe.items()},
        }


def _validate_dataframe(tf: str, df: pd.DataFrame) -> TimeframeValidation:
    path = str(df.attrs.get("source_path", ""))
    rows = len(df)
    missing = sorted(REQUIRED_COLUMNS - set(df.columns))
    errors: list[str] = []
    warnings: list[str] = []
    if missing:
        errors.append(f"missing_columns={missing}")
        return TimeframeValidation(
            timeframe=tf,
            path=path,
            rows=rows,
            first_time=None,
            last_time=None,
            missing_columns=missing,
            ok=False,
            errors=errors,
        )

    times = pd.to_datetime(df["time"], utc=False, errors="coerce")
    naive_count = int(times.apply(lambda t: t is pd.NaT or t.tzinfo is None).sum())
    times_utc = pd.to_datetime(df["time"], utc=True, errors="coerce")
    times_sorted = times_utc.is_monotonic_increasing
    non_monotonic = 0 if times_sorted else int((times_utc.diff().dropna() < pd.Timedelta(0)).sum())
    dup = int(times_utc.duplicated().sum())

    highs = pd.to_numeric(df["high"], errors="coerce")
    lows = pd.to_numeric(df["low"], errors="coerce")
    closes = pd.to_numeric(df["close"], errors="coerce")
    opens = pd.to_numeric(df["open"], errors="coerce")
    high_lt_low = int(((highs < lows) & highs.notna() & lows.notna()).sum())
    negatives = int(((opens <= 0) | (highs <= 0) | (lows <= 0) | (closes <= 0)).sum())

    interval = EXPECTED_INTERVAL_MINUTES.get(tf)
    suspected_gaps: list[dict[str, Any]] = []
    if interval is not None and times_sorted and rows >= 2:
        diffs = times_utc.diff().dropna()
        expected = pd.Timedelta(minutes=interval)
        threshold = expected * GAP_TOLERANCE_FACTOR
        weekend_cap = pd.Timedelta(hours=WEEKEND_GAP_MAX_HOURS)
        flagged = diffs[(diffs > threshold) & (diffs <= weekend_cap)]
        flagged = flagged.head(20)
        for idx, delta in flagged.items():
            prev_time = times_utc.iloc[idx - 1]
            cur_time = times_utc.iloc[idx]
            suspected_gaps.append(
                {
                    "after": prev_time.isoformat() if pd.notna(prev_time) else None,
                    "before": cur_time.isoformat() if pd.notna(cur_time) else None,
                    "delta_minutes": round(delta.total_seconds() / 60, 2),
                    "expected_minutes": interval,
                }
            )

    if dup > 0:
        errors.append(f"duplicate_timestamps={dup}")
    if non_monotonic > 0:
        errors.append(f"non_monotonic_rows={non_monotonic}")
    if high_lt_low > 0:
        errors.append(f"high_lt_low_rows={high_lt_low}")
    if negatives > 0:
        errors.append(f"negative_or_zero_prices={negatives}")
    if naive_count > 0:
        warnings.append(f"naive_timestamps={naive_count} (will be assumed UTC)")
    if suspected_gaps:
        warnings.append(f"suspected_gaps={len(suspected_gaps)}")

    first_time = times_utc.min().isoformat() if rows > 0 and pd.notna(times_utc.min()) else None
    last_time = times_utc.max().isoformat() if rows > 0 and pd.notna(times_utc.max()) else None

    return TimeframeValidation(
        timeframe=tf,
        path=path,
        rows=rows,
        first_time=first_time,
        last_time=last_time,
        missing_columns=missing,
        duplicate_timestamps=dup,
        non_monotonic_rows=non_monotonic,
        naive_timestamps=naive_count,
        high_lt_low_rows=high_lt_low,
        negative_or_zero_prices=negatives,
        suspected_gaps=suspected_gaps,
        ok=not errors,
        errors=errors,
        warnings=warnings,
    )


def validate_csv_timeframes(symbol: str, timeframes: list[str], *, data_dir: str = "data") -> ValidationReport:
    base = Path(data_dir) / symbol
    per_tf: dict[str, TimeframeValidation] = {}
    for tf in timeframes:
        if tf not in SUPPORTED_TIMEFRAMES:
            per_tf[tf] = TimeframeValidation(
                timeframe=tf,
                path="",
                rows=0,
                first_time=None,
                last_time=None,
                ok=False,
                errors=[f"unsupported_timeframe={tf}"],
            )
            continue
        path = base / f"{tf}.csv"
        if not path.exists():
            per_tf[tf] = TimeframeValidation(
                timeframe=tf,
                path=str(path),
                rows=0,
                first_time=None,
                last_time=None,
                ok=False,
                errors=[f"csv_missing={path}"],
            )
            continue
        try:
            df = _load_single_csv(path)
            df.attrs["source_path"] = str(path)
        except Exception as exc:
            per_tf[tf] = TimeframeValidation(
                timeframe=tf,
                path=str(path),
                rows=0,
                first_time=None,
                last_time=None,
                ok=False,
                errors=[f"csv_load_failed={exc}"],
            )
            continue
        per_tf[tf] = _validate_dataframe(tf, df)
    return ValidationReport(symbol=symbol, data_dir=data_dir, per_timeframe=per_tf)


def format_validation_report(report: ValidationReport) -> str:
    lines = [f"DATA VALIDATION REPORT — symbol={report.symbol} dir={report.data_dir}",
             f"Overall OK: {report.ok}", ""]
    for tf, v in report.per_timeframe.items():
        lines.append(f"[{tf}] ok={v.ok} rows={v.rows} first={v.first_time} last={v.last_time}")
        lines.append(f"   path: {v.path}")
        lines.append(f"   duplicates={v.duplicate_timestamps} non_monotonic={v.non_monotonic_rows} naive_ts={v.naive_timestamps} high_lt_low={v.high_lt_low_rows} bad_prices={v.negative_or_zero_prices}")
        if v.suspected_gaps:
            lines.append(f"   suspected_gaps={len(v.suspected_gaps)} (first 3):")
            for gap in v.suspected_gaps[:3]:
                lines.append(f"     after {gap.get('after')} -> before {gap.get('before')} delta={gap.get('delta_minutes')} min (expected {gap.get('expected_minutes')})")
        if v.errors:
            lines.append(f"   errors: {', '.join(v.errors)}")
        if v.warnings:
            lines.append(f"   warnings: {', '.join(v.warnings)}")
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "TimeframeValidation",
    "ValidationReport",
    "format_validation_report",
    "validate_csv_timeframes",
]
