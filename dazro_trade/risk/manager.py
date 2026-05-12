from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from dazro_trade.core.config import Settings
from dazro_trade.risk.sizing import suggested_lot_size
from dazro_trade.risk.validation import validate_trade


@dataclass
class RiskState:
    signals_today: int = 0
    consecutive_losses: int = 0
    daily_pnl: float = 0.0
    last_loss_at: datetime | None = None
    last_invalidation_at: datetime | None = None
    seen_signal_ids: set[str] = field(default_factory=set)


class RiskManager:
    def __init__(self, settings: Settings | None = None, max_daily_signals: int | None = None, max_consecutive_losses: int | None = None):
        self.settings = settings or Settings()
        self.max_daily_signals = max_daily_signals if max_daily_signals is not None else self.settings.max_daily_signals
        self.max_consecutive_losses = max_consecutive_losses if max_consecutive_losses is not None else self.settings.max_consecutive_losses
        self.state = RiskState()

    @property
    def signals_today(self) -> int:
        return self.state.signals_today

    @property
    def consecutive_losses(self) -> int:
        return self.state.consecutive_losses

    def can_signal(self) -> bool:
        return self.state.signals_today < self.max_daily_signals and self.state.consecutive_losses < self.max_consecutive_losses

    def validate(self, signal: dict, spread: float = 0.0, session: str | None = None) -> dict:
        reasons = []
        if not self.can_signal():
            reasons.append("daily_or_loss_limit_reached")
        signal_id = signal.get("signal_id")
        if signal_id and signal_id in self.state.seen_signal_ids:
            reasons.append("duplicate_signal")
        if self._cooldown_active(self.state.last_loss_at):
            reasons.append("cooldown_after_loss")
        if self._cooldown_active(self.state.last_invalidation_at):
            reasons.append("cooldown_after_invalidation")
        if self.state.daily_pnl <= -self.settings.account_balance * self.settings.max_daily_drawdown:
            reasons.append("max_daily_drawdown_reached")
        validation = validate_trade(signal, self.settings, spread=spread, session=session)
        reasons.extend(validation["rejection_reasons"])
        lot_size = suggested_lot_size(
            self.settings.account_balance,
            self.settings.risk_per_trade,
            float(signal.get("entry", 0) or 0),
            float(signal.get("sl", 0) or 0),
        )
        return {"accepted": not reasons, "rejection_reasons": reasons, "rr": validation.get("rr"), "lot_size": lot_size, "risk_pct": self.settings.risk_per_trade}

    def register_signal(self, signal_id: str | None = None):
        self.state.signals_today += 1
        if signal_id:
            self.state.seen_signal_ids.add(signal_id)

    def register_result(self, pnl_r: float):
        self.state.daily_pnl += pnl_r * self.settings.account_balance * self.settings.risk_per_trade
        if pnl_r < 0:
            self.state.consecutive_losses += 1
            self.state.last_loss_at = datetime.now(timezone.utc)
        else:
            self.state.consecutive_losses = 0

    def register_invalidation(self) -> None:
        self.state.last_invalidation_at = datetime.now(timezone.utc)

    @staticmethod
    def _cooldown_active(ts: datetime | None, minutes: int = 30) -> bool:
        return bool(ts and datetime.now(timezone.utc) - ts < timedelta(minutes=minutes))
