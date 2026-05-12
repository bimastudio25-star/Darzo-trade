from __future__ import annotations


def compute_book_metrics(levels: dict) -> dict:
    bids = levels.get("bids", [])[:5]
    asks = levels.get("asks", [])[:5]
    best_bid = bids[0][0] if bids else None
    best_ask = asks[0][0] if asks else None
    bid_depth = sum(float(size) for _, size in bids)
    ask_depth = sum(float(size) for _, size in asks)
    spread = (best_ask - best_bid) if best_bid is not None and best_ask is not None else None
    total = bid_depth + ask_depth
    imbalance = (bid_depth - ask_depth) / total if total else 0.0
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "top5_bids": bids,
        "top5_asks": asks,
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
        "book_imbalance": imbalance,
        "liquidity_wall_above": max(asks, key=lambda x: x[1], default=None),
        "liquidity_wall_below": max(bids, key=lambda x: x[1], default=None),
        "confidence": "LOW",
    }
