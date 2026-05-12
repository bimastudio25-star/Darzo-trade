from __future__ import annotations

from dazro_trade.paper.ledger import PaperLedger


def replay_ledger(db_path: str) -> list[dict]:
    return PaperLedger(db_path).all_trades()
