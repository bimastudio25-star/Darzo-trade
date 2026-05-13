from __future__ import annotations

import pandas as pd

from dazro_trade.analysis.indicators import ema_context, rsi_context


def frame(closes):
    return pd.DataFrame({"c": closes, "o": closes, "h": [v + 0.1 for v in closes], "l": [v - 0.1 for v in closes]})


def test_ema_bullish_alignment():
    closes = [100 + i * 0.1 for i in range(240)]
    ctx = ema_context(frame(closes), closes[-1], timeframe="M15")
    assert ctx["ema_alignment"] == "bullish"
    assert ctx["price_vs_ema50"] == "above"


def test_ema_bearish_alignment():
    closes = [130 - i * 0.1 for i in range(240)]
    ctx = ema_context(frame(closes), closes[-1], timeframe="M15")
    assert ctx["ema_alignment"] == "bearish"
    assert ctx["price_vs_ema50"] == "below"


def test_ema_mixed_range():
    closes = [100 + (0.1 if i % 2 else -0.1) for i in range(240)]
    ctx = ema_context(frame(closes), 100.0, timeframe="M15")
    assert ctx["ema_alignment"] == "mixed"
    assert ctx["trend_state"] == "range"


def test_rsi_overbought_and_oversold_states():
    overbought = rsi_context(frame([100 + i for i in range(40)]), timeframe="M5")
    oversold = rsi_context(frame([140 - i for i in range(40)]), timeframe="M5")
    assert overbought["rsi_state"] == "overbought"
    assert oversold["rsi_state"] == "oversold"


def test_rsi_momentum_labels():
    bullish = rsi_context(frame([100] * 20 + [100.2, 100.4, 100.7, 101.0, 101.2]), timeframe="M5")
    bearish = rsi_context(frame([101] * 20 + [100.8, 100.5, 100.2, 99.9, 99.7]), timeframe="M5")
    assert bullish["rsi_momentum"] in {"rising", "flat"}
    assert bearish["rsi_momentum"] in {"falling", "flat"}
