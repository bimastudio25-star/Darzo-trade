from __future__ import annotations

import pandas as pd

from dazro_trade.analysis.statistical_scalp import evaluate_statistical_scalp


def m5_vwap_frame(center: float = 2002.0) -> pd.DataFrame:
    rows = []
    for idx in range(100):
        price = center - 1.0 if idx % 2 == 0 else center + 1.0
        rows.append({"o": price, "h": price + 0.1, "l": price - 0.1, "c": price, "vol": 100})
    return pd.DataFrame(rows)


def test_statistical_scalp_long_at_lower_two_sigma_with_number_theory():
    out = evaluate_statistical_scalp(m5_vwap_frame(), current_price=2000.04, symbol="XAUUSD")
    assert out is not None
    assert out.direction == "LONG"
    assert out.rr == 1.0
    assert out.entry < out.vwap
    assert out.stop < out.entry
    assert out.tp > out.entry
    assert "statistical_mean_reversion" in out.reason_codes


def test_statistical_scalp_rejects_near_vwap():
    assert evaluate_statistical_scalp(m5_vwap_frame(), current_price=2002.0, symbol="XAUUSD") is None


def test_statistical_scalp_rejects_without_number_theory_confluence():
    assert evaluate_statistical_scalp(m5_vwap_frame(center=2001.33), current_price=1999.37, symbol="XAUUSD") is None
