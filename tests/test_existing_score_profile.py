from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from dazro_trade.analytics.existing_score_profile import (
    ScoreProfileRecord,
    build_existing_score_profile,
    distance_bucket,
    score_bucket,
    stats,
)


def _record(
    ts: datetime,
    score: float | None,
    r: float,
    *,
    setup_mode: str = "LIQ_VP_NT_FVG_SCALP",
    continuation: bool = False,
    rejection: bool = False,
    distance: float | None = None,
) -> ScoreProfileRecord:
    return ScoreProfileRecord(
        signal_timestamp=ts,
        score=score,
        r_multiple=r,
        setup_mode=setup_mode,
        continuation=continuation,
        rejection=rejection,
        swept_high=False,
        swept_low=False,
        reclaim_after_sweep=False,
        fvg_created=False,
        ifvg_created=False,
        distance_to_liquidity_pips=distance,
        side="LONG",
    )


def test_score_bucket_assignment():
    assert score_bucket(67) == "65-69"
    assert score_bucket(82) == "80-84"
    assert score_bucket(None) == "UNKNOWN"


def test_stats_per_bucket_math():
    rows = [
        _record(datetime(2026, 1, 1, tzinfo=timezone.utc), 80, 2.0),
        _record(datetime(2026, 1, 2, tzinfo=timezone.utc), 80, -1.0),
        _record(datetime(2026, 1, 3, tzinfo=timezone.utc), 80, -1.0),
    ]
    out = stats(rows)
    assert out["count"] == 3
    assert out["wins"] == 1
    assert out["losses"] == 2
    assert out["win_rate"] == 0.3333
    assert out["profit_factor"] == 1.0
    assert out["avg_r"] == 0.0


def test_report_includes_full_is_oos_stats():
    rows = [
        _record(datetime(2026, 1, 1, tzinfo=timezone.utc), 80, 2.0),
        _record(datetime(2026, 1, 2, tzinfo=timezone.utc), 80, -1.0),
        _record(datetime(2026, 1, 3, tzinfo=timezone.utc), 90, 2.0),
    ]
    report = build_existing_score_profile(
        rows,
        train_end=datetime(2026, 1, 2, 23, 59, tzinfo=timezone.utc),
        source_metadata={"distance_to_liquidity_pips_available": False},
    )
    bucket = report["score_bucket_profile"]["80-84"]
    assert bucket["full"]["count"] == 2
    assert bucket["in_sample"]["count"] == 2
    assert bucket["out_of_sample"]["count"] == 0
    assert report["overall"]["out_of_sample"]["count"] == 1


def test_setup_mode_grouping():
    rows = [
        _record(datetime(2026, 1, 1, tzinfo=timezone.utc), 80, 2.0, setup_mode="A"),
        _record(datetime(2026, 1, 2, tzinfo=timezone.utc), 80, -1.0, setup_mode="B"),
    ]
    report = build_existing_score_profile(rows, train_end=None, source_metadata={})
    assert report["setup_mode_breakdown"]["A"]["full"]["count"] == 1
    assert report["setup_mode_breakdown"]["B"]["full"]["count"] == 1


def test_none_safe_report_generation():
    rows = [
        ScoreProfileRecord(
            signal_timestamp=None,
            score=None,
            r_multiple=2.0,
            setup_mode=None,
            continuation=None,
            rejection=None,
        )
    ]
    report = build_existing_score_profile(rows, train_end=None, source_metadata={})
    assert report["score_bucket_profile"]["UNKNOWN"]["full"]["count"] == 1
    assert report["setup_mode_breakdown"]["UNKNOWN"]["full"]["count"] == 1


def test_continuation_damage_section_separates_true_false():
    rows = [
        _record(datetime(2026, 1, 1, tzinfo=timezone.utc), 80, -1.0, continuation=True),
        _record(datetime(2026, 1, 2, tzinfo=timezone.utc), 80, 2.0, continuation=False),
    ]
    report = build_existing_score_profile(rows, train_end=None, source_metadata={})
    assert report["continuation_damage"]["continuation=true"]["full"]["count"] == 1
    assert report["continuation_damage"]["continuation=false"]["full"]["count"] == 1


def test_rejection_sanity_section_separates_true_false():
    rows = [
        _record(datetime(2026, 1, 1, tzinfo=timezone.utc), 80, 2.0, rejection=True),
        _record(datetime(2026, 1, 2, tzinfo=timezone.utc), 80, -1.0, rejection=False),
    ]
    report = build_existing_score_profile(rows, train_end=None, source_metadata={})
    assert report["rejection_sanity_check"]["rejection=true"]["full"]["count"] == 1
    assert report["rejection_sanity_check"]["rejection=false"]["full"]["count"] == 1


def test_distance_bucket_assignment():
    assert distance_bucket(5) == "0-10 pips"
    assert distance_bucket(25) == "20-40 pips"
    assert distance_bucket(170) == "150+ pips"


def test_distance_field_missing_does_not_crash():
    rows = [_record(datetime(2026, 1, 1, tzinfo=timezone.utc), 80, 2.0)]
    report = build_existing_score_profile(
        rows,
        train_end=None,
        source_metadata={"distance_to_liquidity_pips_available": False},
    )
    assert report["distance_bucket_profile"]["status"] == "field_not_available_skip"
    assert "DISTANCE_FIELD_NOT_AVAILABLE" in report["warnings"]


def test_backward_compatibility_with_minimal_records():
    rows = [
        ScoreProfileRecord(signal_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), score=None, r_multiple=-1.0),
    ]
    report = build_existing_score_profile(rows, train_end=None, source_metadata={})
    assert report["record_count"] == 1
    assert report["overall"]["full"]["losses"] == 1


def test_dynamic_sl_not_imported_by_profile_module():
    module_path = Path("dazro_trade/analytics/existing_score_profile.py")
    source = module_path.read_text(encoding="utf-8").lower()
    assert "dynamic sl" not in source
    assert "dynamic_sl" not in source
