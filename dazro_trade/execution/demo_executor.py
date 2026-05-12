from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from dazro_trade.core.config import Settings

log = logging.getLogger(__name__)


class DemoExecutor:
    def __init__(self, settings: Settings | None = None, mt5_module: Any | None = None, enabled: bool | None = None):
        self.settings = settings or Settings(demo_execution=bool(enabled))
        if enabled is not None:
            self.settings = replace(self.settings, demo_execution=enabled)
        self.mt5 = mt5_module

    def place_order(self, signal: dict, risk_validation: dict | None = None) -> dict:
        log.info("Demo order attempt signal_id=%s", signal.get("signal_id"))
        if not self.settings.demo_execution:
            return {"ok": False, "reason": "demo_execution_disabled"}
        if self.settings.live_execution:
            return {"ok": False, "reason": "live_execution_forbidden"}
        if not self.settings.ledger_db_path:
            return {"ok": False, "reason": "paper_ledger_required"}
        if risk_validation and not risk_validation.get("accepted", False):
            return {"ok": False, "reason": "risk_validation_rejected", "details": risk_validation.get("rejection_reasons", [])}
        account = self._account_info()
        if not self._appears_demo(account):
            return {"ok": False, "reason": "account_type_unverified_or_live"}
        return self._send_order(signal)

    def _account_info(self):
        if self.mt5 is None:
            import MetaTrader5 as mt5  # type: ignore

            self.mt5 = mt5
        return self.mt5.account_info()

    @staticmethod
    def _appears_demo(account: Any) -> bool:
        if account is None:
            return False
        trade_mode = str(getattr(account, "trade_mode", "")).lower()
        server = str(getattr(account, "server", "")).lower()
        name = str(getattr(account, "name", "")).lower()
        return "demo" in trade_mode or "demo" in server or "demo" in name

    def _send_order(self, signal: dict) -> dict:
        if self.mt5 is None:
            return {"ok": False, "reason": "mt5_unavailable"}
        request = {
            "symbol": signal.get("symbol", self.settings.mt5_symbol),
            "type": signal.get("direction"),
            "volume": signal.get("lot_size"),
            "price": signal.get("entry"),
            "sl": signal.get("sl"),
            "tp": signal.get("tp"),
            "comment": "Dazro paper/demo only",
        }
        result = self.mt5.order_send(request)
        ok = bool(getattr(result, "retcode", 0) in {0, 10009} or getattr(result, "ok", False))
        return {"ok": ok, "ticket": getattr(result, "order", None), "raw": str(result)}
