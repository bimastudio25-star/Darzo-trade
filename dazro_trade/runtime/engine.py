from __future__ import annotations

import logging
from datetime import datetime, timezone

from dazro_trade.core.config import Settings
from dazro_trade.paper.ledger import PaperLedger
from dazro_trade.risk.manager import RiskManager

log = logging.getLogger(__name__)


class RuntimeEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.risk = RiskManager(settings)
        self.ledger = PaperLedger(settings.ledger_db_path)

    def boot(self):
        validation = self.settings.validate_runtime()
        for warning in validation.warnings:
            log.warning(warning)
        if validation.errors:
            raise ValueError("; ".join(validation.errors))
        log.info("Runtime booted | paper=%s demo=%s live=%s", self.settings.paper_mode, self.settings.demo_execution, self.settings.live_execution)

    def audit_reject(self, reason: str):
        log.info("REJECTED_SETUP | reason=%s", reason)

    def persist_signal(self, signal_row: dict):
        self.ledger.insert_trade(signal_row)

    @staticmethod
    def utc_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
