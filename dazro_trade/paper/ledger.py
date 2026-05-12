from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class PaperLedger:
    columns = [
        "timestamp",
        "signal_id",
        "setup_type",
        "direction",
        "crt_type",
        "structure_context",
        "liquidity_context",
        "qb_context",
        "smt_state",
        "macro_state",
        "orderflow_state",
        "ai_decision",
        "final_decision",
        "rejection_reason",
        "entry",
        "sl",
        "tp",
        "rr",
        "lot_size",
        "risk_pct",
        "simulated_status",
        "result",
        "notes",
    ]

    def __init__(self, db_path: str = "data/dazro_ledger.sqlite"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create()

    def _create(self) -> None:
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS trades (
            timestamp TEXT,
            signal_id TEXT PRIMARY KEY,
            setup_type TEXT,
            direction TEXT,
            crt_type TEXT,
            structure_context TEXT,
            liquidity_context TEXT,
            qb_context TEXT,
            smt_state TEXT,
            macro_state TEXT,
            orderflow_state TEXT,
            ai_decision TEXT,
            final_decision TEXT,
            rejection_reason TEXT,
            entry REAL,
            sl REAL,
            tp REAL,
            rr REAL,
            lot_size REAL,
            risk_pct REAL,
            simulated_status TEXT,
            result TEXT,
            notes TEXT
        )"""
        )
        self.conn.commit()

    def insert_trade(self, row: dict[str, Any]) -> None:
        normalized = self._normalize(row)
        placeholders = ",".join("?" for _ in self.columns)
        self.conn.execute(
            f"INSERT OR REPLACE INTO trades ({','.join(self.columns)}) VALUES ({placeholders})",
            [normalized.get(column) for column in self.columns],
        )
        self.conn.commit()

    def fetch_trade(self, signal_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM trades WHERE signal_id=?", (signal_id,)).fetchone()
        return dict(row) if row else None

    def all_trades(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute("SELECT * FROM trades ORDER BY timestamp")]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

    def _normalize(self, row: dict[str, Any]) -> dict[str, Any]:
        aliases = {"ts": "timestamp", "tp1": "tp"}
        out = {aliases.get(key, key): value for key, value in row.items()}
        for key in ["structure_context", "liquidity_context", "qb_context", "ai_decision"]:
            if isinstance(out.get(key), (dict, list)):
                out[key] = json.dumps(out[key], sort_keys=True)
        out.setdefault("timestamp", "")
        out.setdefault("setup_type", "unknown")
        out.setdefault("direction", "")
        out.setdefault("final_decision", "paper")
        out.setdefault("simulated_status", "open")
        out.setdefault("result", "open")
        out.setdefault("notes", "")
        return out
