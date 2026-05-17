"""
Tests for trade-link + trade-linked edge report modules.
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from dazro_trade.analytics.candle_behavior_report import CandleBehaviorRecord
from dazro_trade.analytics.trade_link import TradeLink, link_records_to_trades
from dazro_trade.analytics.trade_linked_edge_report import (
    FILTER_KEYS_FOR_A_PLUS,
    TradeLinkedConfig,
    build_linked_trades,
    build_trade_linked_report,
    find_a_plus_subsets,
    render_trade_linked_markdown,
    write_trade_linked_files,
)
from dazro_trade.backtest.simulator import BacktestSignal, BacktestTrade


def _record(ts: datetime, **feats) -> CandleBehaviorRecord:
    base_features = {
        "swept_high": False, "swept_low": False, "reclaim_after_sweep": False,
        "fvg_created": False, "ifvg_created": False,
        "absorption_candidate": False, "continuation_candidate": False, "rejection_candidate": False,
        "displacement_score": 1.0, "relative_volume_20": 1.0,
    }
    base_features.update(feats)
    return CandleBehaviorRecord(timestamp=ts, session="London", features=base_features, touches=[], reactions=[])


def _signal(ts: datetime, **kw) -> BacktestSignal:
    defaults = dict(
        symbol="XAUUSD", strategy="strategy_1_adelin_scalp",
        direction="LONG", entry=4700.0, stop=4697.0, tp1=4706.0, rr_tp1=2.0,
        score=70, session="London", metadata={"setup_mode": "LIQ_VP_NT_FVG_SCALP"},
    )
    defaults.update(kw)
    return BacktestSignal(timestamp=ts, **defaults)


def _trade(sig: BacktestSignal, r: float) -> BacktestTrade:
    outcome = "TP1" if r > 0 else ("SL" if r < 0 else "BE")
    return BacktestTrade(signal=sig, outcome=outcome, exit_time=sig.timestamp,
                         exit_price=4706 if r > 0 else 4697, r_multiple=r,
                         mae=1.0, mfe=2.0, bars_held=10)


# ----------------------------------------------------------------------
# trade_link.link_records_to_trades
# ----------------------------------------------------------------------

def test_link_records_to_trades_finds_closest_signal_within_window():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    records = [_record(base + timedelta(minutes=i * 5)) for i in range(5)]
    sig = _signal(base + timedelta(minutes=5))  # closest to record idx=1
    trade = _trade(sig, 2.0)
    links = link_records_to_trades(records, [sig], [trade], timeframe_minutes=5, link_window_bars=20)
    assert 1 in links
    assert links[1].nearest_signal_timestamp == sig.timestamp
    assert links[1].trade_outcome == "TP1"
    assert links[1].distance_to_signal_bars == 0


def test_link_records_outside_window_skipped():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    records = [_record(base), _record(base + timedelta(hours=10))]
    sig = _signal(base)
    trade = _trade(sig, 2.0)
    links = link_records_to_trades(records, [sig], [trade], timeframe_minutes=5, link_window_bars=20)
    assert 0 in links and 1 not in links


def test_link_returns_empty_when_no_signals():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    records = [_record(base)]
    links = link_records_to_trades(records, [], [])
    assert links == {}


def test_link_only_matches_target_strategy():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    records = [_record(base)]
    sig = _signal(base)
    sig_s2 = _signal(base, strategy="strategy_2_liquidity_expansion")
    links = link_records_to_trades(records, [sig_s2], [], strategy="strategy_1_adelin_scalp")
    assert links == {}
    links2 = link_records_to_trades(records, [sig], [_trade(sig, 2.0)], strategy="strategy_1_adelin_scalp")
    assert 0 in links2


def test_link_skips_no_data_trade_outcome():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    records = [_record(base)]
    sig = _signal(base)
    sig.accepted = False
    sig.rejection_reasons.append("test_rejection")
    trade = BacktestTrade(signal=sig, outcome="NO_DATA", exit_time=None, exit_price=None,
                          r_multiple=0.0, mae=0, mfe=0, bars_held=0)
    links = link_records_to_trades(records, [sig], [trade])
    # The link is created (record close to signal) but trade_outcome is None
    assert 0 in links
    assert links[0].nearest_signal_accepted is False
    # No-data trades are excluded by build_linked_trades downstream
    linked = build_linked_trades(records, links)
    assert linked == []


# ----------------------------------------------------------------------
# build_linked_trades
# ----------------------------------------------------------------------

def test_build_linked_trades_one_per_signal_pick_closest():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    sig = _signal(base + timedelta(minutes=12))
    records = [_record(base + timedelta(minutes=i * 5)) for i in range(5)]
    trade = _trade(sig, 2.0)
    links = link_records_to_trades(records, [sig], [trade], timeframe_minutes=5, link_window_bars=20)
    linked = build_linked_trades(records, links)
    assert len(linked) == 1
    assert linked[0].r_multiple == 2.0


# ----------------------------------------------------------------------
# Stats & filters
# ----------------------------------------------------------------------

def test_overall_stats_balanced_wins_losses():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    records = [_record(base + timedelta(hours=i)) for i in range(6)]
    sigs = [_signal(records[i].timestamp) for i in range(6)]
    trades = [_trade(sigs[i], 2.0 if i % 2 == 0 else -1.0) for i in range(6)]
    links = link_records_to_trades(records, sigs, trades, timeframe_minutes=60)
    report = build_trade_linked_report(records, links)
    overall = report["overall"]
    assert overall["n_trades"] == 6
    assert overall["wins"] == 3
    assert overall["losses"] == 3
    assert overall["win_rate"] == 0.5


def test_by_pattern_segregates_buckets():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    records = [
        _record(base, continuation_candidate=True),
        _record(base + timedelta(minutes=5), rejection_candidate=True),
    ]
    sigs = [_signal(records[0].timestamp), _signal(records[1].timestamp)]
    trades = [_trade(sigs[0], 2.0), _trade(sigs[1], -1.0)]
    links = link_records_to_trades(records, sigs, trades, timeframe_minutes=5)
    report = build_trade_linked_report(records, links)
    assert "continuation" in report["by_pattern"]
    assert "rejection" in report["by_pattern"]


def test_by_flag_with_vs_without():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    records = [
        _record(base, swept_high=True, reclaim_after_sweep=True),
        _record(base + timedelta(minutes=5)),
    ]
    sigs = [_signal(records[0].timestamp), _signal(records[1].timestamp)]
    trades = [_trade(sigs[0], 2.0), _trade(sigs[1], -1.0)]
    links = link_records_to_trades(records, sigs, trades, timeframe_minutes=5)
    report = build_trade_linked_report(records, links)
    assert report["by_flag"]["swept_high"]["with"]["wins"] == 1
    assert report["by_flag"]["swept_high"]["without"]["losses"] == 1


def test_displacement_buckets():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    records = [
        _record(base, displacement_score=0.5),
        _record(base + timedelta(minutes=5), displacement_score=2.0),
    ]
    sigs = [_signal(records[0].timestamp), _signal(records[1].timestamp)]
    trades = [_trade(sigs[0], -1.0), _trade(sigs[1], 2.0)]
    links = link_records_to_trades(records, sigs, trades, timeframe_minutes=5)
    report = build_trade_linked_report(records, links)
    by_d = report["by_displacement_bucket"]
    assert "d_lt_1.0" in by_d
    assert "d_1.5_to_2.5" in by_d


# ----------------------------------------------------------------------
# A+ subset finder
# ----------------------------------------------------------------------

def test_a_plus_subset_found_when_filter_yields_pf_above_1():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    records = []
    sigs = []
    trades = []
    # 25 trades with swept_high + reclaim -> all winners
    for i in range(25):
        rec = _record(base + timedelta(minutes=i * 5), swept_high=True, reclaim_after_sweep=True)
        records.append(rec)
        s = _signal(rec.timestamp, score=85)
        sigs.append(s)
        trades.append(_trade(s, 2.0))
    # 25 trades without -> all losers
    for i in range(25, 50):
        rec = _record(base + timedelta(minutes=i * 5))
        records.append(rec)
        s = _signal(rec.timestamp, score=65)
        sigs.append(s)
        trades.append(_trade(s, -1.0))
    links = link_records_to_trades(records, sigs, trades, timeframe_minutes=5)
    cfg = TradeLinkedConfig(min_trades_for_a_plus=20, a_plus_min_profit_factor=1.0, a_plus_min_avg_r=0.0)
    linked = build_linked_trades(records, links)
    a_plus = find_a_plus_subsets(linked, cfg=cfg)
    assert len(a_plus) > 0
    top = a_plus[0]
    assert "swept_high" in top["filter"] or "reclaim_after_sweep" in top["filter"]
    assert top["profit_factor"] >= 1.0


def test_a_plus_subset_empty_when_no_filter_above_threshold():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    records = [_record(base + timedelta(minutes=i * 5)) for i in range(40)]
    sigs = [_signal(r.timestamp) for r in records]
    trades = [_trade(s, -1.0) for s in sigs]  # all losses
    links = link_records_to_trades(records, sigs, trades, timeframe_minutes=5)
    cfg = TradeLinkedConfig(min_trades_for_a_plus=20, a_plus_min_profit_factor=1.0, a_plus_min_avg_r=0.0)
    linked = build_linked_trades(records, links)
    assert find_a_plus_subsets(linked, cfg=cfg) == []


# ----------------------------------------------------------------------
# Markdown + writer
# ----------------------------------------------------------------------

def test_render_trade_linked_markdown_contains_required_sections():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    records = [_record(base, continuation_candidate=True)]
    sigs = [_signal(records[0].timestamp)]
    trades = [_trade(sigs[0], 2.0)]
    links = link_records_to_trades(records, sigs, trades, timeframe_minutes=5)
    report = build_trade_linked_report(records, links)
    md = render_trade_linked_markdown(report)
    for header in ("# Adelin trade-linked edge report", "## Overall", "### By candle pattern", "## A+ subsets"):
        assert header in md


def test_write_trade_linked_files_creates_json_and_md():
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    records = [_record(base, continuation_candidate=True)]
    sigs = [_signal(records[0].timestamp)]
    trades = [_trade(sigs[0], 2.0)]
    links = link_records_to_trades(records, sigs, trades, timeframe_minutes=5)
    report = build_trade_linked_report(records, links)
    with tempfile.TemporaryDirectory() as tmp:
        paths = write_trade_linked_files(output_dir=tmp, report=report)
        assert Path(paths["trade_linked_json"]).exists()
        assert Path(paths["trade_linked_md"]).exists()
        payload = json.loads(Path(paths["trade_linked_json"]).read_text(encoding="utf-8"))
        assert "overall" in payload


# ----------------------------------------------------------------------
# Filter keys completeness
# ----------------------------------------------------------------------

def test_filter_keys_cover_main_features():
    expected = {"swept_high", "swept_low", "reclaim_after_sweep",
                "fvg_created", "ifvg_created", "continuation", "rejection"}
    assert set(FILTER_KEYS_FOR_A_PLUS) == expected
