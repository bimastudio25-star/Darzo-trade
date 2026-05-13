from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from dazro_trade.adelin import format_adelin_signal, format_rejection_summary, format_vp_summary, run_adelin_scan
from dazro_trade.adelin.confluence_engine import calculate_scalp_levels, calculate_vwap_scalp, score_setup
from dazro_trade.adelin.liquidity_map import build_liquidity_map, find_swept_level
from dazro_trade.adelin.number_theory import get_number_theory_levels, is_near_nt_level, nearest_number_theory, score_number_theory_confluence
from dazro_trade.adelin.sweep_detector import calculate_vwap, calculate_vwap_bands, find_liquidity_sweep
from dazro_trade.adelin.volume_profile import build_multi_anchor_volume_profiles, build_volume_profile, crack_covers_fvg, price_in_volume_crack
from dazro_trade.core.config import Settings
from dazro_trade.core.symbols import pips_to_price, price_to_pips
from dazro_trade.runtime.scanner import ScalpingScanner
from dazro_trade.runtime.telegram_runtime import TelegramCommandRuntime, VISIBLE_COMMANDS

PIP = 0.10


def frame(rows):
    return pd.DataFrame(rows, columns=["o", "h", "l", "c"]).assign(vol=100)


def trend_frame(base=100.0, rows=40):
    data = []
    for idx in range(rows):
        price = base + idx * 0.1
        data.append((price, price + 0.4, price - 0.4, price + 0.1))
    return frame(data)


def test_adelin_xauusd_pip_convention():
    assert PIP == 0.10
    assert pips_to_price("XAUUSD", 10) == 1.00
    assert pips_to_price("XAUUSD", 50) == 5.00
    assert pips_to_price("XAUUSD", 100) == 10.00
    assert pips_to_price("XAUUSD", 300) == 30.00
    assert pips_to_price("XAUUSD", 500) == 50.00
    assert price_to_pips("XAUUSD", 1.00) == 10
    assert price_to_pips("XAUUSD", 5.00) == 50
    assert price_to_pips("XAUUSD", 10.00) == 100
    assert price_to_pips("XAUUSD", 30.00) == 300
    assert price_to_pips("XAUUSD", 50.00) == 500
    assert price_to_pips("XAUUSD", 0.20) == 2


def test_number_theory_levels_weights_and_fvg_confluence():
    levels = get_number_theory_levels(2010.10, lookback_range=1.0, pip=PIP)
    by_level = {item["level"]: item for item in levels}
    assert by_level[2010.0]["weight"] == 3
    assert by_level[2010.5]["weight"] == 2
    assert by_level[2010.25]["weight"] == 1
    assert nearest_number_theory(2010.10, tolerance_pips=2, pip=PIP)["confluence"]
    assert not nearest_number_theory(2010.30, tolerance_pips=0.2, pip=PIP)["confluence"]
    assert is_near_nt_level(2010.04, tolerance_pips=1, min_weight=3, pip=PIP)
    scored = score_number_theory_confluence(2010.10, 2010.30, 2009.90, pip=PIP)
    assert scored["confluence"]
    assert scored["score"] > 0


def test_volume_profile_cracks_and_multi_anchor_profiles():
    rows = []
    for idx in range(40):
        rows.append((100 + idx * 0.02, 100.2 + idx * 0.02, 99.9 + idx * 0.02, 100.1 + idx * 0.02, 200))
    for idx in range(40):
        rows.append((104 + idx * 0.02, 104.2 + idx * 0.02, 103.9 + idx * 0.02, 104.1 + idx * 0.02, 200))
    df = pd.DataFrame(rows, columns=["o", "h", "l", "c", "vol"])
    vp = build_volume_profile(df, 105.0, 100.0, n_bins=50, pip=PIP, min_crack_pips=2)
    assert 100.0 <= vp["poc"] <= 105.0
    assert vp["vah"] > vp["val"]
    assert all(100.0 <= item <= 105.0 for item in vp["hvn"])
    assert vp["volume_cracks"]
    crack_mid = (vp["volume_cracks"][0]["low"] + vp["volume_cracks"][0]["high"]) / 2
    assert price_in_volume_crack(crack_mid, vp, tolerance_pips=1, pip=PIP)["confluence"]
    assert crack_covers_fvg(vp["volume_cracks"][0]["high"], vp["volume_cracks"][0]["low"], vp)["confluence"]
    profiles = build_multi_anchor_volume_profiles({"D1": frame([(99, 106, 98, 104), (100, 105, 99, 103)]), "H1": trend_frame(), "H4": trend_frame(), "M15": df, "M5": df}, [], 103.0, PIP)
    assert "daily_current" in profiles
    assert "h1_swing" in profiles
    assert "h4_swing" in profiles


def test_liquidity_map_sides_and_swept_level_priority():
    h4 = frame([(100, 101, 98, 100), (100, 102, 99, 101), (101, 103, 100, 102), (102, 102, 99, 100), (100, 103, 98, 101), (101, 102, 99, 100), (100, 101, 98, 99)])
    h1 = h4.copy()
    m15 = h4.copy()
    m5 = h4.copy()
    liq = build_liquidity_map(h4, h1, m15, m5, PIP)
    assert any(item["name"] == "PWH" for item in liq)
    assert any(item["name"] == "PDL" for item in liq)
    assert any(item["kind"] == "swing_high" and item["side"] == "buy_side" for item in liq)
    assert any(item["kind"] == "swing_low" and item["side"] == "sell_side" for item in liq)
    assert any(item["scope"] == "internal" for item in liq)
    swept = find_swept_level(103.0, liq, tolerance_pips=5, pip=PIP)
    assert swept is not None
    assert swept["side"] == "buy_side"


def test_sweep_detector_uses_liquidity_map_then_equal_high_fallback():
    liq = [{"name": "PDL", "level": 100.0, "side": "sell_side", "kind": "range_low", "priority": 90}]
    m5 = frame([(101, 102, 100.5, 101), (101, 101.5, 100.2, 101), (100.8, 101.0, 99.6, 100.4)])
    m1 = frame([(99.7, 100.0, 99.5, 99.8), (99.8, 99.9, 99.7, 99.85), (100.2, 100.9, 100.2, 100.8), (100.3, 101.4, 100.2, 101.2)])
    sweep = find_liquidity_sweep(m5, m1, liq_map=liq, pip=PIP)
    assert sweep is not None
    assert sweep["source"] == "liquidity_map"
    assert sweep["close_back_inside"]
    assert sweep["m1_displacement"]
    assert sweep["fvg_after_liquidity"]
    assert 0 <= sweep["confidence"] <= 1
    no_displacement = find_liquidity_sweep(m5, frame([(100, 100.1, 99.9, 100.0)] * 5), liq_map=liq, pip=PIP)
    assert no_displacement is not None
    assert not no_displacement["m1_displacement"]
    fallback = find_liquidity_sweep(frame([(100, 101, 99, 100), (100, 101.05, 99, 100), (100, 101.3, 99.5, 100.8)]), frame([(101, 101, 100.5, 100.6)] * 5), liq_map=None, pip=PIP)
    assert fallback is not None


def test_confluence_engine_modes_and_levels():
    sweep = {"liquidity_swept": True, "close_back_inside": True, "fvg_after_liquidity": True, "ifvg_after_liquidity": True}
    levels = calculate_scalp_levels("LONG", 100.0, 95.0, PIP)
    assert 35 <= levels["sl_pips"] <= 65
    assert levels["sl"] < levels["entry"]
    assert levels["tp1"]["rr"] == 2.0
    sell = calculate_scalp_levels("SHORT", 100.0, 100.5, PIP)
    assert sell["sl"] > sell["entry"]
    full = score_setup(sweep=sweep, volume_confluence={"confluence": True}, number_theory={"confluence": True}, levels=levels, spread_pips=2.0)
    assert full["score"] <= 100
    assert full["setup_mode"] == "LIQ_VP_NT_FVG_A_PLUS"
    assert score_setup(sweep=None, volume_confluence={"confluence": True}, number_theory={"confluence": True}, levels=levels, spread_pips=2.0)["score"] == 0
    a_plus_with_only_nt = score_setup(sweep=sweep, volume_confluence={"confluence": False}, number_theory={"confluence": True}, levels=levels, spread_pips=2.0)
    assert a_plus_with_only_nt["setup_mode"] == "LIQ_VP_NT_FVG_A_PLUS"
    a_plus_with_only_vc = score_setup(sweep=sweep, volume_confluence={"confluence": True}, number_theory={"confluence": False}, levels=levels, spread_pips=2.0)
    assert a_plus_with_only_vc["setup_mode"] == "LIQ_VP_NT_FVG_A_PLUS"
    neither_vc_nor_nt = score_setup(sweep=sweep, volume_confluence={"confluence": False}, number_theory={"confluence": False}, levels=levels, spread_pips=2.0)
    assert neither_vc_nor_nt["setup_mode"] == "NO_TRADE"
    assert "volume_crack_and_number_theory_both_missing" in neither_vc_nor_nt["rejected"]
    assert calculate_vwap_scalp("LONG", 100.0, {"vwap": 101.0, "std": 1.0}, PIP)["setup_mode"] == "VWAP_STD_RESEARCH_1R"


def test_adelin_telegram_format_uses_retail_pips_and_vwap_warning():
    signal = {
        "symbol": "XAUUSD",
        "setup_mode": "LIQ_VP_NT_FVG_A_PLUS",
        "direction": "LONG",
        "score": 90,
        "entry_zone": (100.0, 100.4),
        "entry": 100.2,
        "sl": 95.2,
        "sl_pips": 50,
        "tp1": {"price": 110.2, "distance_pips": 100, "rr": 2.0, "basis": "liquidity"},
        "tp2": {"price": 115.2, "distance_pips": 150, "rr": 3.0, "basis": "runner"},
        "volume_confluence": {"reason": "volume_crack_covers_fvg"},
        "number_theory": {"reason": "number_theory_inside_fvg"},
        "fvg": {"type": "bullish_fvg"},
        "sweep": {"level_name": "PDL"},
    }
    text = format_adelin_signal(signal, {"vp_summary": {"profiles": ["daily_current"], "best_poc": 101.0}})
    assert "LONG" in text
    assert "Entry" in text
    assert "SL" in text
    assert "TP1" in text
    assert "Score" in text
    assert "LIQ_VP_NT_FVG_A_PLUS" in text
    assert "50 pips / 5.00$" in text
    assert "100 pips / 10.00$" in text
    research = {**signal, "setup_mode": "VWAP_STD_RESEARCH_1R"}
    assert "PAPER ONLY" in format_adelin_signal(research, {})
    assert "NO TRADE" in format_rejection_summary({"setup_mode": "NO_TRADE", "rejected": ["liquidity_sweep_missing"]})
    assert "POC" in format_vp_summary({"profiles": ["daily_current"], "best_poc": 101.0})


def test_adelin_pipeline_gates_and_output_shape():
    result = run_adelin_scan(market_data={}, settings=Settings(adelin_session_gate_enabled=False), now_utc=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert result["signal"] is None
    assert "no_candle_data" in result["rejected"]
    frames = {"D1": trend_frame(98), "H4": trend_frame(98), "H1": trend_frame(98), "M15": trend_frame(98), "M5": trend_frame(98), "M1": trend_frame(98)}
    news = [{"title": "FOMC", "time": datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)}]
    blocked = run_adelin_scan(market_data=frames, current_price=101.0, settings=Settings(adelin_session_gate_enabled=False), news_events=news, now_utc=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc))
    assert any(reason.startswith("news_gate") for reason in blocked["rejected"])
    session_blocked = run_adelin_scan(market_data=frames, current_price=101.0, settings=Settings(adelin_session_gate_enabled=True), now_utc=datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc))
    assert "outside_adelin_session_window" in session_blocked["rejected"]
    assert set(result) == {"timestamp", "signal", "rejected", "score_detail", "vp_summary", "vwap_data", "setup_mode", "debug"}


def test_runtime_integration_commands_and_first_scan_silent():
    class Sender:
        def __init__(self):
            self.sent = []

        def send_text(self, text):
            self.sent.append(text)
            return {"ok": True}

    scanner = ScalpingScanner(Settings(telegram_token="x", telegram_chat_id="1", adelin_session_gate_enabled=False), telegram_bot=Sender())
    scanner.latest_adelin_result = {"setup_mode": "NO_TRADE", "rejected": ["liquidity_sweep_missing"], "vp_summary": {"profiles": ["daily_current"], "best_poc": 100}}
    scanner.latest_analysis = None
    assert {item[0] for item in VISIBLE_COMMANDS} >= {"status", "analisi", "watch", "scan", "plan", "trades", "stop", "resume", "help"}
    assert isinstance(TelegramCommandRuntime(scanner), TelegramCommandRuntime)
    assert "Adelin" in scanner.format_status()
    assert scanner._maybe_send_adelin_signal({"signal": {"symbol": "XAUUSD", "setup_mode": "LIQ_VP_NT_FVG_SCALP", "direction": "LONG", "entry": 100, "sl": 95, "tp1": {"price": 110}, "tp2": {"price": 115}}}, "London", datetime.now(timezone.utc))
    assert not scanner._maybe_send_adelin_signal({"signal": {"symbol": "XAUUSD", "setup_mode": "LIQ_VP_NT_FVG_SCALP", "direction": "LONG", "entry": 100, "sl": 95, "tp1": {"price": 110}, "tp2": {"price": 115}}}, "London", datetime.now(timezone.utc))
