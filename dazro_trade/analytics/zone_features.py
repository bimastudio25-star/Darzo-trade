"""
Zone definitions + touch detection for the Adelin behaviour profiler.

A `Zone` is a price band (top / bottom) with a `type` label and the
timeframe it was extracted from. The profiler treats every M1 / M5
candle whose [low, high] interval overlaps a zone as a "touch" and
records the candle / zone pair for downstream reaction analysis.

Supported zone types follow Adelin's confluence vocabulary:
    internal_liquidity      sweep candidates produced on M5 / M1
    external_liquidity      H4 / H1 highs and lows that have not yet
                            been swept
    fvg                     fair value gap (top -> bottom)
    ifvg                    inverse fair value gap
    gap_liquidity           liquidity gap created by a fast move
    liquidity_crack         volume-profile crack / low-volume node
    vp_node                 volume-profile POC / HVN
    vwap_band               VWAP ±Nσ envelope
    number_theory           round / NT levels
    h1_liquidity            previous H1 high / low
    h4_liquidity            previous H4 high / low
    daily_liquidity         previous day high / low

The module is intentionally generic; the upstream extractor that
populates `Zone` from market_data lives outside this file so the
profiler can be unit-tested with synthetic zones.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Literal

import pandas as pd

ZoneType = Literal[
    "internal_liquidity",
    "external_liquidity",
    "fvg",
    "ifvg",
    "gap_liquidity",
    "liquidity_crack",
    "vp_node",
    "vwap_band",
    "number_theory",
    "h1_liquidity",
    "h4_liquidity",
    "daily_liquidity",
]


@dataclass(frozen=True)
class Zone:
    type: ZoneType
    top: float
    bottom: float
    timeframe: str = ""
    label: str = ""
    side: Literal["buy_side", "sell_side", "neutral"] = "neutral"
    created_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def center(self) -> float:
        return (float(self.top) + float(self.bottom)) / 2.0

    @property
    def height(self) -> float:
        return abs(float(self.top) - float(self.bottom))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "top": float(self.top),
            "bottom": float(self.bottom),
            "timeframe": self.timeframe,
            "label": self.label,
            "side": self.side,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ZoneTouch:
    zone: Zone
    candle_time: datetime
    candle_high: float
    candle_low: float
    touched_top: bool
    touched_bottom: bool
    touched_center: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone.to_dict(),
            "candle_time": self.candle_time.isoformat() if hasattr(self.candle_time, "isoformat") else str(self.candle_time),
            "candle_high": float(self.candle_high),
            "candle_low": float(self.candle_low),
            "touched_top": self.touched_top,
            "touched_bottom": self.touched_bottom,
            "touched_center": self.touched_center,
        }


# ----------------------------------------------------------------------
# Touch detection
# ----------------------------------------------------------------------

def candle_touches_zone(
    candle_high: float,
    candle_low: float,
    zone: Zone,
    *,
    tolerance: float = 0.0,
) -> ZoneTouch | None:
    """Return a ZoneTouch when [candle_low, candle_high] overlaps the
    zone band (extended by `tolerance` price units), else None."""
    z_top = max(float(zone.top), float(zone.bottom))
    z_bot = min(float(zone.top), float(zone.bottom))
    z_top_ext = z_top + float(tolerance)
    z_bot_ext = z_bot - float(tolerance)
    h = float(candle_high)
    l = float(candle_low)
    if h < z_bot_ext or l > z_top_ext:
        return None
    touched_top = l <= z_top_ext and h >= z_top
    touched_bottom = h >= z_bot_ext and l <= z_bot
    center = zone.center
    touched_center = l <= center <= h
    return ZoneTouch(
        zone=zone,
        candle_time=datetime.now() if False else None,  # filled by caller
        candle_high=h,
        candle_low=l,
        touched_top=touched_top,
        touched_bottom=touched_bottom,
        touched_center=touched_center,
    )


def detect_touches(
    candle: Any,
    zones: Iterable[Zone],
    *,
    tolerance: float = 0.0,
) -> list[ZoneTouch]:
    """Iterate `zones` and yield every ZoneTouch hit by the candle."""
    h = float(candle["h"] if "h" in candle else candle["high"])
    l = float(candle["l"] if "l" in candle else candle["low"])
    t = candle.get("time") if hasattr(candle, "get") else (candle["time"] if "time" in candle else None)
    touches: list[ZoneTouch] = []
    for zone in zones:
        raw = candle_touches_zone(h, l, zone, tolerance=tolerance)
        if raw is None:
            continue
        touches.append(
            ZoneTouch(
                zone=raw.zone,
                candle_time=t,  # type: ignore[arg-type]
                candle_high=raw.candle_high,
                candle_low=raw.candle_low,
                touched_top=raw.touched_top,
                touched_bottom=raw.touched_bottom,
                touched_center=raw.touched_center,
            )
        )
    return touches


# ----------------------------------------------------------------------
# Lightweight zone extractors from market_data (HTF liquidity levels)
# ----------------------------------------------------------------------

def _normalize_window(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rename: dict[str, str] = {}
    if "high" in out.columns and "h" not in out.columns:
        rename["high"] = "h"
    if "low" in out.columns and "l" not in out.columns:
        rename["low"] = "l"
    if rename:
        out = out.rename(columns=rename)
    return out


def extract_htf_liquidity_zones(
    market_data: dict[str, pd.DataFrame],
    *,
    cutoff: datetime | None = None,
    lookback_per_tf: dict[str, int] | None = None,
) -> list[Zone]:
    """Build a flat list of htf-liquidity Zones (h1 / h4 / daily highs &
    lows) from the standard market_data dict produced by the loader.

    Only candles closed before `cutoff` are considered. Each high / low
    becomes a thin (0-height) Zone tagged with the appropriate type.
    """
    lookback_per_tf = lookback_per_tf or {"H1": 24, "H4": 14, "D1": 10}
    zones: list[Zone] = []
    mapping = {
        "H1": ("h1_liquidity", "H1"),
        "H4": ("h4_liquidity", "H4"),
        "D1": ("daily_liquidity", "D1"),
    }
    for tf, (zone_type, tf_label) in mapping.items():
        df = market_data.get(tf)
        if df is None or len(df) == 0:
            continue
        norm = _normalize_window(df)
        if "time" in norm.columns and cutoff is not None:
            ts = pd.Timestamp(cutoff)
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
            norm = norm[pd.to_datetime(norm["time"], utc=True) < ts]
        n = lookback_per_tf.get(tf, 10)
        tail = norm.tail(n)
        for _, row in tail.iterrows():
            high = float(row["h"])
            low = float(row["l"])
            ts_row = row["time"].to_pydatetime() if "time" in row and hasattr(row["time"], "to_pydatetime") else None
            zones.append(Zone(type=zone_type, top=high, bottom=high, timeframe=tf_label, label=f"{tf_label}_high", side="buy_side", created_at=ts_row))
            zones.append(Zone(type=zone_type, top=low, bottom=low, timeframe=tf_label, label=f"{tf_label}_low", side="sell_side", created_at=ts_row))
    return zones


__all__ = [
    "Zone",
    "ZoneTouch",
    "ZoneType",
    "candle_touches_zone",
    "detect_touches",
    "extract_htf_liquidity_zones",
]
