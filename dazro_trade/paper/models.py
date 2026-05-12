from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LedgerTrade:
    timestamp: str
    signal_id: str
    setup_type: str
    direction: str
    entry: float
    sl: float
    tp: float
    rr: float
    lot_size: float
    risk_pct: float
    final_decision: str
    rejection_reason: str | None = None
