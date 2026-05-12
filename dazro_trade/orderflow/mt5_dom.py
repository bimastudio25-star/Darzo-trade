from __future__ import annotations

from dazro_trade.orderflow.metrics import compute_book_metrics
from dazro_trade.orderflow.provider_base import OrderflowProvider


class MT5DOMProvider(OrderflowProvider):
    confidence_level = "LOW"

    def __init__(self, mt5_module=None):
        self.mt5 = mt5_module

    def snapshot(self, symbol: str) -> dict:
        if self.mt5 is None:
            import MetaTrader5 as mt5  # type: ignore

            self.mt5 = mt5
        if not self.mt5.market_book_add(symbol):
            return {"state": "unavailable", "reason": "market_book_add_failed", "confidence": "LOW"}
        try:
            book = self.mt5.market_book_get(symbol) or []
            bids = []
            asks = []
            for item in book:
                if isinstance(item, dict):
                    price = float(item.get("price"))
                    volume = float(item.get("volume", 0))
                    typ = item.get("type", "")
                else:
                    price = float(getattr(item, "price"))
                    volume = float(getattr(item, "volume", 0))
                    typ = getattr(item, "type", "")
                if str(typ).lower() in {"1", "buy", "bid"}:
                    bids.append((price, volume))
                else:
                    asks.append((price, volume))
            bids.sort(key=lambda x: x[0], reverse=True)
            asks.sort(key=lambda x: x[0])
            metrics = compute_book_metrics({"bids": bids, "asks": asks})
            metrics.update({"state": "ready", "symbol": symbol, "note": "MT5 DOM is low confidence for XAUUSD CFD/spot and can only confirm or reject existing signals."})
            return metrics
        finally:
            self.mt5.market_book_release(symbol)
