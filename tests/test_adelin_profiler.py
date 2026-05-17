"""
Tests for the Adelin edge profiler (read-only diagnostic).

Covers:
- profile_adelin output structure
- score / SL bucket labels and aggregations
- score x SL matrix
- confluence with/without split
- micro_confluence full split
- build_recommendations heuristics
- render_markdown smoke
- write_profile_files file emission
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from dazro_trade.backtest.adelin_profile_report import (
    CONFLUENCE_FLAGS,
    RecommendationConfig,
    build_recommendations,
    render_markdown,
    write_profile_files,
)
from dazro_trade.backtest.adelin_profiler import (
    ADELIN_STRATEGY_NAME,
    ProfilerConfig,
    profile_adelin,
)
from dazro_trade.backtest.simulator import BacktestSignal, BacktestTrade


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _signal(
    *,
    sl_distance: float = 3.5,
    score: int = 70,
    setup_mode: str = "LIQ_VP_NT_FVG_SCALP",
    direction: str = "LONG",
    session: str = "London",
    has_sweep: bool = True,
    has_fvg: bool = False,
    has_volume_confluence: bool = False,
    has_number_theory: bool = False,
    micro_all_pass: bool = False,
    when: datetime | None = None,
) -> BacktestSignal:
    entry = 4700.0
    stop = entry - sl_distance if direction == "LONG" else entry + sl_distance
    return BacktestSignal(
        timestamp=when or datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
        symbol="XAUUSD",
        strategy=ADELIN_STRATEGY_NAME,
        direction=direction,
        entry=entry,
        stop=round(stop, 2),
        tp1=entry + sl_distance * 2 if direction == "LONG" else entry - sl_distance * 2,
        rr_tp1=2.0,
        score=score,
        session=session,
        metadata={
            "setup_mode": setup_mode,
            "has_sweep": has_sweep,
            "has_fvg": has_fvg,
            "has_volume_confluence": has_volume_confluence,
            "has_number_theory": has_number_theory,
            "micro_confluence": {"all_pass": micro_all_pass},
        },
    )


def _trade(sig: BacktestSignal, r: float) -> BacktestTrade:
    outcome = "TP1" if r > 0 else ("SL" if r < 0 else "BE")
    return BacktestTrade(
        signal=sig,
        outcome=outcome,
        exit_time=sig.timestamp,
        exit_price=sig.entry + r,
        r_multiple=r,
        mae=1.0,
        mfe=2.0,
        bars_held=10,
    )


# ----------------------------------------------------------------------
# Structure
# ----------------------------------------------------------------------

def test_profile_returns_expected_top_level_keys():
    profile = profile_adelin([], [])
    assert profile["strategy"] == ADELIN_STRATEGY_NAME
    for key in (
        "overall", "by_score_bucket", "by_sl_bucket", "score_x_sl_matrix",
        "by_setup_mode", "by_session", "by_direction", "by_confluence",
        "micro_confluence_split", "config",
    ):
        assert key in profile


def test_profile_filters_non_adelin_signals():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    s_adelin = _signal()
    s_other = BacktestSignal(
        timestamp=base, symbol="XAUUSD", strategy="strategy_2_liquidity_expansion",
        direction="LONG", entry=4700.0, stop=4690.0, tp1=4710.0, rr_tp1=1.0,
    )
    profile = profile_adelin([s_adelin, s_other], [_trade(s_adelin, 2.0)])
    assert profile["overall"]["total_signals"] == 1


# ----------------------------------------------------------------------
# Score / SL bucket labels
# ----------------------------------------------------------------------

@pytest.mark.parametrize("score,expected_bucket", [
    (60, "lt_65"),
    (65, "65_to_69"),
    (74, "70_to_74"),
    (89, "85_to_89"),
    (90, "ge_90"),
    (100, "ge_90"),
])
def test_score_bucket_classification(score, expected_bucket):
    sig = _signal(score=score)
    profile = profile_adelin([sig], [_trade(sig, 2.0)])
    assert expected_bucket in profile["by_score_bucket"]


@pytest.mark.parametrize("sl,expected_bucket", [
    (3.5, "le_4.00"),
    (4.0, "le_4.00"),
    (4.5, "4.01_to_5.00"),
    (5.0, "4.01_to_5.00"),
    (6.5, "5.01_to_6.50"),
    (7.0, "6.51_to_7.00"),
    (8.0, "gt_7.00"),
])
def test_sl_bucket_classification(sl, expected_bucket):
    sig = _signal(sl_distance=sl)
    profile = profile_adelin([sig], [_trade(sig, 2.0)])
    assert expected_bucket in profile["by_sl_bucket"]


# ----------------------------------------------------------------------
# Aggregations
# ----------------------------------------------------------------------

def test_only_winners_produces_high_pf_sentinel():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    sigs = [_signal(when=base + timedelta(hours=i)) for i in range(10)]
    trades = [_trade(s, 2.0) for s in sigs]
    profile = profile_adelin(sigs, trades)
    assert profile["overall"]["wins"] == 10
    assert profile["overall"]["losses"] == 0
    assert profile["overall"]["profit_factor"] == 999.0


def test_only_losers_produces_zero_pf_and_negative_avg_r():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    sigs = [_signal(when=base + timedelta(hours=i)) for i in range(10)]
    trades = [_trade(s, -1.0) for s in sigs]
    profile = profile_adelin(sigs, trades)
    assert profile["overall"]["losses"] == 10
    assert profile["overall"]["wins"] == 0
    assert profile["overall"]["profit_factor"] == 0.0
    assert profile["overall"]["avg_r"] == -1.0


def test_be_trades_counted_separately_from_wins_and_losses():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    sigs = [_signal(when=base + timedelta(hours=i)) for i in range(3)]
    trades = [_trade(sigs[0], 2.0), _trade(sigs[1], -1.0), _trade(sigs[2], 0.0)]
    profile = profile_adelin(sigs, trades)
    assert profile["overall"]["wins"] == 1
    assert profile["overall"]["losses"] == 1
    assert profile["overall"]["be"] == 1
    assert profile["overall"]["valid_trades"] == 3


def test_statistical_significance_threshold():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    sigs = [_signal(when=base + timedelta(hours=i)) for i in range(29)]
    trades = [_trade(s, 2.0) for s in sigs]
    profile = profile_adelin(sigs, trades)
    assert profile["overall"]["statistically_significant"] is False
    sigs.append(_signal(when=base + timedelta(hours=30)))
    trades.append(_trade(sigs[-1], 2.0))
    profile = profile_adelin(sigs, trades)
    assert profile["overall"]["statistically_significant"] is True


# ----------------------------------------------------------------------
# Matrix and breakdowns
# ----------------------------------------------------------------------

def test_score_x_sl_matrix_populated():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    sigs = [
        _signal(score=70, sl_distance=3.5, when=base),
        _signal(score=88, sl_distance=6.0, when=base + timedelta(hours=1)),
    ]
    trades = [_trade(sigs[0], 2.0), _trade(sigs[1], -1.0)]
    profile = profile_adelin(sigs, trades)
    matrix = profile["score_x_sl_matrix"]
    assert "70_to_74" in matrix
    assert "le_4.00" in matrix["70_to_74"]
    assert "85_to_89" in matrix
    assert "5.01_to_6.50" in matrix["85_to_89"]


def test_confluence_split_with_vs_without():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    sigs = [
        _signal(has_fvg=True, when=base),
        _signal(has_fvg=False, when=base + timedelta(hours=1)),
    ]
    trades = [_trade(sigs[0], 2.0), _trade(sigs[1], -1.0)]
    profile = profile_adelin(sigs, trades)
    assert profile["by_confluence"]["has_fvg"]["with"]["valid_trades"] == 1
    assert profile["by_confluence"]["has_fvg"]["without"]["valid_trades"] == 1


def test_micro_confluence_full_split():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    sigs = [
        _signal(micro_all_pass=True, when=base),
        _signal(micro_all_pass=False, when=base + timedelta(hours=1)),
    ]
    trades = [_trade(sigs[0], 2.0), _trade(sigs[1], -1.0)]
    profile = profile_adelin(sigs, trades)
    assert profile["micro_confluence_split"]["with_full_micro_confluence"]["valid_trades"] == 1
    assert profile["micro_confluence_split"]["without_full_micro_confluence"]["valid_trades"] == 1


# ----------------------------------------------------------------------
# Recommendations
# ----------------------------------------------------------------------

def test_recommendations_find_best_min_score():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    sigs = []
    trades = []
    # 40 winners in score 85-89, 60 losers in score 65-69
    for i in range(40):
        s = _signal(score=88, sl_distance=3.5, when=base + timedelta(hours=i))
        sigs.append(s)
        trades.append(_trade(s, 2.0))
    for i in range(60):
        s = _signal(score=66, sl_distance=3.5, when=base + timedelta(hours=40 + i))
        sigs.append(s)
        trades.append(_trade(s, -1.0))
    profile = profile_adelin(sigs, trades)
    rec = build_recommendations(profile)
    assert rec["best_min_score"] == 85


def test_recommendations_find_best_max_sl_when_higher_buckets_negative():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    sigs = []
    trades = []
    # le_4.00: 40 winners
    for i in range(40):
        s = _signal(score=88, sl_distance=3.5, when=base + timedelta(hours=i))
        sigs.append(s)
        trades.append(_trade(s, 2.0))
    # 4.01-5.00: 40 losers
    for i in range(40):
        s = _signal(score=88, sl_distance=4.5, when=base + timedelta(hours=40 + i))
        sigs.append(s)
        trades.append(_trade(s, -1.0))
    profile = profile_adelin(sigs, trades)
    rec = build_recommendations(profile)
    assert rec["best_max_sl_usd"] == 4.0


def test_recommendations_toxic_buckets_flagged():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    sigs = [_signal(score=66, sl_distance=3.5, when=base + timedelta(hours=i)) for i in range(40)]
    trades = [_trade(s, -1.0) for s in sigs]
    profile = profile_adelin(sigs, trades)
    rec = build_recommendations(profile)
    score_toxic = [t for t in rec["toxic_buckets"] if t["dimension"] == "score_bucket"]
    assert any(t["label"] == "65_to_69" for t in score_toxic)


def test_recommendations_useful_vs_useless_confluence():
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    sigs = []
    trades = []
    # has_fvg = True -> wins
    for i in range(40):
        s = _signal(score=88, has_fvg=True, when=base + timedelta(hours=i))
        sigs.append(s)
        trades.append(_trade(s, 2.0))
    # has_fvg = False -> losses
    for i in range(40):
        s = _signal(score=88, has_fvg=False, when=base + timedelta(hours=40 + i))
        sigs.append(s)
        trades.append(_trade(s, -1.0))
    profile = profile_adelin(sigs, trades)
    rec = build_recommendations(profile)
    useful_flags = {u["flag"] for u in rec["useful_confluences"]}
    assert "has_fvg" in useful_flags


# ----------------------------------------------------------------------
# Markdown rendering + writer
# ----------------------------------------------------------------------

def test_render_markdown_contains_required_sections():
    sigs = [_signal()]
    trades = [_trade(sigs[0], 2.0)]
    profile = profile_adelin(sigs, trades)
    rec = build_recommendations(profile)
    md = render_markdown(profile, rec)
    for header in (
        "# Adelin edge profile",
        "## Overall",
        "## Recommendations",
        "### By score bucket",
        "### By SL bucket",
        "### By setup_mode",
        "### Confluence split",
    ):
        assert header in md, f"missing section: {header}"


def test_write_profile_files_creates_json_and_md():
    sigs = [_signal()]
    trades = [_trade(sigs[0], 2.0)]
    profile = profile_adelin(sigs, trades)
    rec = build_recommendations(profile)
    with tempfile.TemporaryDirectory() as tmp:
        paths = write_profile_files(output_dir=tmp, profile=profile, recommendations=rec)
        assert Path(paths["profile_json"]).exists()
        assert Path(paths["profile_md"]).exists()
        payload = json.loads(Path(paths["profile_json"]).read_text(encoding="utf-8"))
        assert "profile" in payload
        assert "recommendations" in payload


# ----------------------------------------------------------------------
# Confluence flag completeness
# ----------------------------------------------------------------------

def test_confluence_flags_cover_all_expected_fields():
    expected = {"has_sweep", "has_fvg", "has_volume_confluence", "has_number_theory"}
    assert set(CONFLUENCE_FLAGS) == expected
