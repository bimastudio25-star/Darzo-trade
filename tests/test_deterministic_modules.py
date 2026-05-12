from __future__ import annotations

from datetime import datetime

from dazro_trade.analysis.crt import detect_crt
from dazro_trade.analysis.turtle_soup import detect_turtle_soup
from dazro_trade.liquidity.acceptance import acceptance_after_sweep
from dazro_trade.liquidity.pools import detect_equal_highs, infer_liquidity_pools
from dazro_trade.liquidity.rejection import rejection_after_sweep
from dazro_trade.liquidity.sweeps import detect_sweep
from dazro_trade.macro.dxy import classify_dxy
from dazro_trade.macro.news import NewsClient
from dazro_trade.orderflow.absorption import absorption_heuristic
from dazro_trade.orderflow.imbalance import imbalance_state
from dazro_trade.orderflow.metrics import compute_book_metrics
from dazro_trade.quarterly.qb import qb_proximity
from dazro_trade.quarterly.quarterly_theory import classify_quarter, directional_weight, quarterly_phase
from dazro_trade.smt.divergence import detect_smt_divergence
from dazro_trade.structure.bos import accepted_breakout, close_based_bos
from dazro_trade.structure.choch import detect_choch
from dazro_trade.structure.line_structure import infer_structure
from dazro_trade.structure.msnr import detect_msnr_retest


def test_line_structure_bos_choch_msnr():
    assert close_based_bos([1, 2, 3], 2.5, "bullish")
    assert accepted_breakout([1, 3], 2, "bullish").accepted
    assert infer_structure([1, 2, 3, 4, 5]) == "bullish"
    assert detect_choch([1, 5], prior_swing_high=4, prior_swing_low=0, prev_bias="bearish")["choch"]
    assert detect_msnr_retest([3, 2.05, 2.4], 2, "BUY", tolerance=0.1)["accepted"]


def test_liquidity_pools_sweeps_acceptance_rejection():
    candles = [{"h": 10, "l": 8, "c": 9}, {"h": 10.03, "l": 8.02, "c": 9.5}]
    assert detect_equal_highs(candles, tolerance=0.05)
    assert infer_liquidity_pools(candles)
    sweep = detect_sweep({"h": 10.5, "l": 9, "c": 9.8}, 10, "high")
    assert sweep["confirmed"]
    assert acceptance_after_sweep([10.2], 10, "BUY")["accepted"]
    assert rejection_after_sweep({"c": 9.8}, 10, "SELL")["rejected"]


def test_crt_and_turtle_soup():
    candles = [
        {"o": 9.5, "h": 10, "l": 8, "c": 9},
        {"o": 9.8, "h": 10.5, "l": 8.5, "c": 10.2},
        {"o": 10.1, "h": 10.2, "l": 7.5, "c": 7.8},
    ]
    crt = detect_crt(candles, min_rr=1)
    assert crt["type"] == "bearish_crt"
    turtle = detect_turtle_soup(candles + [{"o": 8, "h": 11, "l": 7.9, "c": 8.5}], lookback=3, min_rr=1)
    assert turtle["type"] in {"bearish_turtle_soup", "none"}


def test_qb_smt_macro_and_orderflow_degrade():
    assert classify_quarter(5) == "Q2"
    assert quarterly_phase(datetime(2026, 5, 1))["monthly_role"] == "quarter_expansion"
    assert directional_weight(75, 0, 100)["bias"] == "bearish"
    assert qb_proximity(100.2, [100], tolerance=0.5)["state"] == "near_qb"
    assert detect_smt_divergence([1, 2], [2, 1])["state"] == "bullish"
    assert classify_dxy([1, 2, 3])["state"] == "bearish_gold"
    assert NewsClient().high_impact_usd_block()["state"] == "uncertain"
    metrics = compute_book_metrics({"bids": [(99, 4), (98, 1)], "asks": [(100, 1), (101, 1)]})
    assert metrics["book_imbalance"] > 0
    assert imbalance_state(metrics)["state"] == "bid_heavy"
    assert absorption_heuristic(metrics)["confidence_delta"] >= 0
