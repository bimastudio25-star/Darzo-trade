from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Direction = Literal["BUY", "SELL", "NONE"]


@dataclass
class SignalContext:
    symbol: str
    current_price: float
    spread: float
    session: str
    timestamp_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    h1_bias: str | None = None
    h4_bias: str | None = None
    line_structure_state: str = "unknown"
    msnr_retest_state: str = "unknown"
    liquidity_pools: list[dict[str, Any]] = field(default_factory=list)
    sweep_state: str = "none"
    crt_turtle_state: str = "none"
    fvg_ifvg_state: str = "unknown"
    ob_state: str = "unknown"
    smt_state: str = "neutral"
    quarterly_qb_state: str = "neutral"
    macro_state: str = "uncertain"
    orderflow_state: str = "disabled"
    candidate_direction: Direction = "NONE"
    candidate_entry: float | None = None
    candidate_sl: float | None = None
    candidate_tp: float | None = None
    invalidation_level: float | None = None
    deterministic_reason_codes: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)

    @property
    def has_deterministic_candidate(self) -> bool:
        return (
            self.candidate_direction in {"BUY", "SELL"}
            and self.candidate_entry is not None
            and self.candidate_sl is not None
            and self.candidate_tp is not None
            and not self.rejection_reasons
        )

    def to_safe_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp_utc"] = self.timestamp_utc.isoformat()
        return data
