from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from dazro_trade.core.context import SignalContext

Direction = Literal["BUY", "SELL"]
SetupState = Literal["WATCH", "ARMED", "TRIGGERED", "ENTERED", "INVALIDATED", "EXPIRED"]
ZoneRole = Literal["HTF_CONTEXT", "LTF_SETUP", "ENTRY_TRIGGER", "TARGET"]


@dataclass
class TradeSignal:
    signal_id: str
    symbol: str
    direction: Direction
    entry: float
    sl: float
    tp1: float
    rr: float
    confidence: float
    invalidation_level: float
    risk_pct: float
    lot_size: float
    setup_type: str = "unknown"
    tp2: float | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SetupZone:
    id: str
    symbol: str
    timeframe: str
    zone_type: str
    role: ZoneRole
    state: SetupState
    direction: Direction | None
    low: float
    high: float
    reason_codes: list[str] = field(default_factory=list)
    score: int = 0
    distance_from_price: float | None = None
    touched: bool = False
    entry_area_touched: bool = False
    first_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    invalidated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def midpoint(self) -> float:
        return round((self.low + self.high) / 2, 2)

    @property
    def fingerprint(self) -> str:
        return f"{self.symbol}:{self.direction}:{self.timeframe}:{self.zone_type}:{round(self.low, 1)}:{round(self.high, 1)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "zone_type": self.zone_type,
            "role": self.role,
            "state": self.state,
            "direction": self.direction,
            "low": self.low,
            "high": self.high,
            "midpoint": self.midpoint,
            "reason_codes": list(self.reason_codes),
            "score": self.score,
            "distance_from_price": self.distance_from_price,
            "touched": self.touched,
            "entry_area_touched": self.entry_area_touched,
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "invalidated_at": self.invalidated_at.isoformat() if self.invalidated_at else None,
            "metadata": dict(self.metadata),
            "fingerprint": self.fingerprint,
        }


@dataclass
class ScalpingDecision:
    symbol: str
    setup_type: str
    direction: Literal["LONG", "SHORT", "WAIT"]
    state: SetupState
    score: int
    confidence: float
    htf_context: dict[str, Any]
    intraday_context: dict[str, Any]
    liquidity: dict[str, Any]
    primary_zone: SetupZone | None = None
    entry_area: tuple[float, float] | None = None
    stop: float | None = None
    targets: list[dict[str, Any]] = field(default_factory=list)
    invalidation: float | None = None
    reason_codes: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    signal_id: str | None = None
    timestamp_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_operational_signal(self) -> bool:
        return self.state == "TRIGGERED" and self.score >= 85 and self.direction in {"LONG", "SHORT"} and self.primary_zone is not None

    @property
    def telegram_allowed(self) -> bool:
        return self.is_operational_signal

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "setup_type": self.setup_type,
            "direction": self.direction,
            "state": self.state,
            "score": self.score,
            "confidence": self.confidence,
            "htf_context": self.htf_context,
            "intraday_context": self.intraday_context,
            "liquidity": self.liquidity,
            "primary_zone": self.primary_zone.to_dict() if self.primary_zone else None,
            "entry_area": self.entry_area,
            "stop": self.stop,
            "targets": list(self.targets),
            "invalidation": self.invalidation,
            "reason_codes": list(self.reason_codes),
            "rejection_reasons": list(self.rejection_reasons),
            "events": list(self.events),
            "signal_id": self.signal_id,
            "timestamp_utc": self.timestamp_utc.isoformat(),
        }


__all__ = ["Direction", "SignalContext", "TradeSignal", "SetupState", "ZoneRole", "SetupZone", "ScalpingDecision"]
