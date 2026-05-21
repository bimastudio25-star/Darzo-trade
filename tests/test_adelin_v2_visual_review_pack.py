from __future__ import annotations

import ast
import csv
import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.adelin_v2_visual_review_pack import (
    INSUFFICIENT_EXECUTION_DATA,
    MANUAL_LABEL_COLUMNS,
    PRE_REGISTERED_DECISION_CRITERIA_TEXT,
    RESEARCH_WARNING,
    REVIEWABLE_M1_M5,
    REVIEWABLE_M5_ONLY,
    VisualReviewSample,
    WEAK_M1_ONLY,
    VisualReviewPackConfig,
    _annotate_sample_metadata,
    _daily_atr14_context,
    create_visual_review_pack,
    is_near_number_theory_level,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_frame(path: Path, start: datetime, rows: int, minutes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "open", "high", "low", "close", "tick_volume", "spread"])
        price = 4900.0
        for i in range(rows):
            ts = start + timedelta(minutes=minutes * i)
            open_ = price
            close = price + (0.2 if i % 2 == 0 else -0.15)
            high = max(open_, close) + 0.4
            low = min(open_, close) - 0.4
            if i == 24:
                high = 4910.5
                close = 4908.8
            if i == 36:
                low = 4889.5
                close = 4891.2
            writer.writerow([ts.strftime("%Y-%m-%d %H:%M:%S"), open_, high, low, close, 100 + i, 0])
            price = close + 0.03


def _make_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    _write_frame(data_dir / "XAUUSD" / "M1.csv", start, 1800, 1)
    _write_frame(data_dir / "XAUUSD" / "M5.csv", start, 400, 5)
    _write_frame(data_dir / "XAUUSD" / "M15.csv", start, 96, 15)
    _write_frame(data_dir / "XAUUSD" / "H1.csv", start, 80, 60)
    return data_dir


def _make_m15_only_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "m15_only_data"
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    _write_frame(data_dir / "XAUUSD" / "M15.csv", start, 96, 15)
    _write_frame(data_dir / "XAUUSD" / "H1.csv", start, 80, 60)
    return data_dir


def _make_m5_only_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "m5_only_data"
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    _write_frame(data_dir / "XAUUSD" / "M5.csv", start, 400, 5)
    _write_frame(data_dir / "XAUUSD" / "M15.csv", start, 96, 15)
    _write_frame(data_dir / "XAUUSD" / "H1.csv", start, 80, 60)
    return data_dir


def _make_m1_only_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "m1_only_data"
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    _write_frame(data_dir / "XAUUSD" / "M1.csv", start, 1800, 1)
    _write_frame(data_dir / "XAUUSD" / "M15.csv", start, 96, 15)
    _write_frame(data_dir / "XAUUSD" / "H1.csv", start, 80, 60)
    return data_dir


def test_module_import_is_safe():
    module = importlib.import_module("dazro_trade.analytics.adelin_v2_visual_review_pack")
    assert hasattr(module, "create_visual_review_pack")


def test_cli_parser_import_does_not_execute_generation():
    module = importlib.import_module("scripts.create_adelin_v2_visual_review_pack")
    args = module.parse_args(["--symbol", "XAUUSD", "--max-samples", "3"])
    assert args.symbol == "XAUUSD"
    assert args.max_samples == 3
    assert args.max_samples_per_week == 20


def test_visual_pack_creates_output_files_and_respects_sample_cap(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    output_dir = tmp_path / "pack"
    summary = create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=output_dir,
            trades_path=tmp_path / "missing_trades.csv",
            audit_path=tmp_path / "missing_audit.csv",
            max_samples=4,
            dry_run=True,
        )
    )
    assert summary["total_samples"] <= 4
    assert summary["candidate_windows_generated"] == summary["total_samples"]
    assert (output_dir / "index.html").exists()
    assert (output_dir / "manual_labels_template.csv").exists()
    assert (output_dir / "review_pack_summary.json").exists()
    assert (output_dir / "README_manual_review.md").exists()
    assert summary["charts_generated"] == summary["total_samples"]
    assert summary["html_pages_generated"] == summary["total_samples"]
    assert summary["reviewable_samples"] == summary["total_samples"]


def test_empty_missing_trades_file_does_not_crash(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    summary = create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=tmp_path / "pack",
            trades_path=tmp_path / "does_not_exist.csv",
            audit_path=tmp_path / "also_missing.csv",
            max_samples=2,
        )
    )
    assert "TRADES_PATH_MISSING" in summary["limitations"]
    assert summary["total_samples"] <= 2


def test_missing_candle_data_gives_valid_summary_with_limitations(tmp_path: Path):
    output_dir = tmp_path / "empty_pack"
    summary = create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=tmp_path / "missing_data",
            output_dir=output_dir,
            trades_path=tmp_path / "missing_trades.csv",
            audit_path=tmp_path / "missing_audit.csv",
            max_samples=5,
        )
    )
    assert summary["total_samples"] == 0
    assert "NO_CANDLE_DATA_LOADED" in summary["limitations"]
    assert summary["reviewable_samples"] == 0
    assert (output_dir / "index.html").exists()
    assert (output_dir / "manual_labels_template.csv").exists()


def test_manual_label_template_contains_required_columns(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    output_dir = tmp_path / "pack"
    create_visual_review_pack(
        VisualReviewPackConfig(data_dir=data_dir, output_dir=output_dir, trades_path=tmp_path / "missing.csv", audit_path=tmp_path / "missing_audit.csv", max_samples=1)
    )
    with (output_dir / "manual_labels_template.csv").open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
    assert header == MANUAL_LABEL_COLUMNS
    assert "execution_data_status" in header
    assert "anchor_iso_week" in header
    assert "daily_atr_at_anchor" in header
    assert "m1_candles_count" in header
    assert "m5_candles_count" in header
    assert "m15_candles_count" in header
    assert "reviewer_should_skip_due_to_missing_ltf_data_manual" in header


def test_index_html_contains_research_only_no_signal_warning(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    output_dir = tmp_path / "pack"
    create_visual_review_pack(
        VisualReviewPackConfig(data_dir=data_dir, output_dir=output_dir, trades_path=tmp_path / "missing.csv", audit_path=tmp_path / "missing_audit.csv", max_samples=1)
    )
    html = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "Research-only" in html
    assert RESEARCH_WARNING in html
    assert "Not validation" in html
    assert "execution_data_status" in html
    assert "M1 count" in html


def test_summary_json_includes_safety_flags_all_false(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    output_dir = tmp_path / "pack"
    create_visual_review_pack(
        VisualReviewPackConfig(data_dir=data_dir, output_dir=output_dir, trades_path=tmp_path / "missing.csv", audit_path=tmp_path / "missing_audit.csv", max_samples=1)
    )
    summary = json.loads((output_dir / "review_pack_summary.json").read_text(encoding="utf-8"))
    assert all(value is False for value in summary["safety"].values())
    assert "reviewable_samples" in summary
    assert "reviewable_m1_m5_count" in summary
    assert "insufficient_execution_data_count" in summary


def test_no_live_notification_or_execution_imports_are_used():
    paths = [
        REPO_ROOT / "dazro_trade" / "analytics" / "adelin_v2_visual_review_pack.py",
        REPO_ROOT / "scripts" / "create_adelin_v2_visual_review_pack.py",
    ]
    blocked_import_terms = {"telegram", "mt5", "execution", "broker", "order"}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name.lower() for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module.lower())
        assert not any(any(term in name for term in blocked_import_terms) for name in imported)
        source = path.read_text(encoding="utf-8")
        assert "order_send" not in source
        assert "send_message(" not in source


def test_strategy_2_strategy_3_and_vwap_are_not_imported():
    source = (REPO_ROOT / "dazro_trade" / "analytics" / "adelin_v2_visual_review_pack.py").read_text(encoding="utf-8")
    assert "strategy_3_vwap_1r" not in source
    assert "liquidity_expansion" not in source
    assert "analysis.vwap" not in source


def test_candidate_window_mode_marks_samples_as_visual_candidates_not_signals(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    output_dir = tmp_path / "pack"
    summary = create_visual_review_pack(
        VisualReviewPackConfig(data_dir=data_dir, output_dir=output_dir, trades_path=tmp_path / "missing.csv", audit_path=tmp_path / "missing_audit.csv", max_samples=3)
    )
    assert "CANDIDATE_WINDOW_MODE" in summary["source_modes_used"]
    index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "not trade signals" in index_html
    with (output_dir / "manual_labels_template.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert all(row["source_mode"] == "CANDIDATE_WINDOW_MODE" for row in rows)
    assert all(row["execution_data_status"] == REVIEWABLE_M1_M5 for row in rows)


def test_m15_without_m1_m5_is_marked_insufficient_execution_data(tmp_path: Path):
    data_dir = _make_m15_only_data_dir(tmp_path)
    output_dir = tmp_path / "pack"
    summary = create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=output_dir,
            trades_path=tmp_path / "missing.csv",
            audit_path=tmp_path / "missing_audit.csv",
            max_samples=2,
            include_insufficient_execution_debug=True,
        )
    )
    assert summary["total_samples"] > 0
    assert summary["reviewable_samples"] == 0
    assert summary["insufficient_execution_data_count"] == summary["total_samples"]
    with (output_dir / "manual_labels_template.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert all(row["execution_data_status"] == INSUFFICIENT_EXECUTION_DATA for row in rows)
    sample_page = (output_dir / rows[0]["html_path"]).read_text(encoding="utf-8")
    assert "INSUFFICIENT EXECUTION DATA - do not label as A+." in sample_page


def test_default_generator_excludes_insufficient_execution_samples(tmp_path: Path):
    data_dir = _make_m15_only_data_dir(tmp_path)
    summary = create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=tmp_path / "pack",
            trades_path=tmp_path / "missing.csv",
            audit_path=tmp_path / "missing_audit.csv",
            max_samples=5,
        )
    )
    assert summary["total_samples"] == 0
    assert summary["samples_skipped_due_to_missing_ltf_data"] > 0
    assert "PACK_NOT_FILLED_DUE_TO_COVERAGE_OR_REGIME_CONSTRAINTS" in summary["limitations"]


def test_m5_only_is_skipped_by_default_for_expanded_review_quality(tmp_path: Path):
    data_dir = _make_m5_only_data_dir(tmp_path)
    output_dir = tmp_path / "pack"
    summary = create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=output_dir,
            trades_path=tmp_path / "missing.csv",
            audit_path=tmp_path / "missing_audit.csv",
            max_samples=3,
        )
    )
    assert summary["total_samples"] == 0
    assert summary["samples_skipped_due_to_missing_ltf_data"] > 0


def test_m5_only_can_be_included_as_debug_insufficient_context(tmp_path: Path):
    data_dir = _make_m5_only_data_dir(tmp_path)
    output_dir = tmp_path / "pack"
    summary = create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=output_dir,
            trades_path=tmp_path / "missing.csv",
            audit_path=tmp_path / "missing_audit.csv",
            max_samples=3,
            include_insufficient_execution_debug=True,
        )
    )
    assert summary["total_samples"] == 3
    assert summary["reviewable_m5_only_count"] == 3
    with (output_dir / "manual_labels_template.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert all(row["execution_data_status"] == REVIEWABLE_M5_ONLY for row in rows)


def test_m1_only_is_excluded_by_default_and_allowed_explicitly(tmp_path: Path):
    data_dir = _make_m1_only_data_dir(tmp_path)
    default_summary = create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=tmp_path / "pack_default",
            trades_path=tmp_path / "missing.csv",
            audit_path=tmp_path / "missing_audit.csv",
            max_samples=3,
        )
    )
    assert default_summary["total_samples"] == 0
    assert default_summary["samples_skipped_due_to_missing_ltf_data"] > 0
    allowed_output = tmp_path / "pack_allowed"
    allowed_summary = create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=allowed_output,
            trades_path=tmp_path / "missing.csv",
            audit_path=tmp_path / "missing_audit.csv",
            max_samples=3,
            allow_weak_m1_only=True,
        )
    )
    assert allowed_summary["total_samples"] == 3
    assert allowed_summary["weak_m1_only_count"] == 3
    with (allowed_output / "manual_labels_template.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert all(row["execution_data_status"] == WEAK_M1_ONLY for row in rows)


def test_generator_prefers_samples_with_m1_m5_coverage(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    output_dir = tmp_path / "pack"
    summary = create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=output_dir,
            trades_path=tmp_path / "missing.csv",
            audit_path=tmp_path / "missing_audit.csv",
            max_samples=5,
            min_sample_spacing_minutes=0,
        )
    )
    assert summary["total_samples"] == 5
    assert summary["reviewable_m1_m5_count"] == 5
    assert summary["insufficient_execution_data_count"] == 0


def test_expanded_spacing_rule_is_enforced(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    output_dir = tmp_path / "pack"
    create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=output_dir,
            trades_path=tmp_path / "missing.csv",
            audit_path=tmp_path / "missing_audit.csv",
            max_samples=4,
            min_sample_spacing_minutes=240,
        )
    )
    with (output_dir / "manual_labels_template.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    anchors = [datetime.fromisoformat(row["anchor_timestamp"]) for row in rows]
    assert all(
        abs((right - left).total_seconds()) >= 240 * 60
        for index, left in enumerate(anchors)
        for right in anchors[index + 1 :]
    )


def test_expanded_max_samples_per_day_is_enforced(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    output_dir = tmp_path / "pack"
    summary = create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=output_dir,
            trades_path=tmp_path / "missing.csv",
            audit_path=tmp_path / "missing_audit.csv",
            max_samples=10,
            max_samples_per_day=1,
            min_sample_spacing_minutes=0,
        )
    )
    assert summary["samples_per_day_max_observed"] <= 1
    assert summary["samples_skipped_max_per_day"] >= 0


def test_expanded_summary_includes_regime_metadata_and_decision_criteria(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    output_dir = tmp_path / "pack"
    summary = create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=output_dir,
            trades_path=tmp_path / "missing.csv",
            audit_path=tmp_path / "missing_audit.csv",
            max_samples=3,
            min_sample_spacing_minutes=0,
        )
    )
    assert "date_range_coverage_days" in summary
    assert "LOCAL_DATA_COVERAGE_BELOW_REQUESTED_MIN_DATE_RANGE" in summary["limitations"]
    assert isinstance(summary["candidate_source_counts"], dict)
    assert isinstance(summary["entry_level_source_counts"], dict)
    assert isinstance(summary["session_distribution"], dict)
    assert isinstance(summary["samples_per_month_distribution"], dict)
    assert isinstance(summary["volatility_bucket_distribution"], dict)
    assert "atr_p25" in summary
    assert "atr_p75" in summary
    assert "volatility_imbalance_warning" in summary
    assert "date_range_coverage" in summary
    assert "anti_lookahead_guarantees_by_source" in summary
    assert summary["decision_criteria_preregistered"] is True
    assert summary["pre_registered_decision_criteria"] == PRE_REGISTERED_DECISION_CRITERIA_TEXT
    assert summary["expanded_pack_generation_verdict"] in {
        "CONTINUE_DETECTOR_REFINEMENT",
        "STOP_ARCHIVE_DETECTOR",
        "REPEAT_EXPANSION_ONCE",
        "INCONCLUSIVE",
    }
    criteria_path = output_dir / "decision_criteria.md"
    assert criteria_path.exists()
    assert criteria_path.read_text(encoding="utf-8").strip() == PRE_REGISTERED_DECISION_CRITERIA_TEXT


def test_manual_template_includes_entry_source_metadata(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    output_dir = tmp_path / "pack"
    create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=output_dir,
            trades_path=tmp_path / "missing.csv",
            audit_path=tmp_path / "missing_audit.csv",
            max_samples=2,
            min_sample_spacing_minutes=0,
        )
    )
    with (output_dir / "manual_labels_template.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert {
        "candidate_source_type",
        "entry_level_source",
        "entry_level_confidence",
        "session",
        "anchor_iso_week",
        "month",
        "volatility_bucket",
        "daily_atr_at_anchor",
    }.issubset(rows[0].keys())


def test_weekly_cap_is_enforced_when_configured(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    output_dir = tmp_path / "pack"
    summary = create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=output_dir,
            trades_path=tmp_path / "missing.csv",
            audit_path=tmp_path / "missing_audit.csv",
            max_samples=10,
            max_samples_per_week=1,
            min_sample_spacing_minutes=0,
        )
    )
    assert summary["samples_per_week_max_observed"] <= 1
    assert "samples_skipped_max_per_week_cap" in summary


def test_atr14_volatility_context_is_deterministic_and_uses_prior_day():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(20):
        rows.append(
            {
                "time": base + timedelta(days=i),
                "open": 4900 + i,
                "high": 4905 + i,
                "low": 4895 + i,
                "close": 4901 + i,
            }
        )
    frames = {"D1": pd.DataFrame(rows)}
    limitations: list[str] = []
    anchor_end = base + timedelta(days=10)
    buckets, atr_by_date, p25, p75 = _daily_atr14_context(frames, limitations, eligible_end=anchor_end)
    changed_rows = list(rows)
    changed_rows[10] = dict(changed_rows[10], high=9999.0, low=1.0)
    changed_buckets, changed_atr_by_date, changed_p25, changed_p75 = _daily_atr14_context({"D1": pd.DataFrame(changed_rows)}, [], eligible_end=anchor_end)
    anchor_date = "2026-01-11"
    assert atr_by_date[anchor_date] == changed_atr_by_date[anchor_date]
    assert buckets[anchor_date] == changed_buckets[anchor_date]
    assert p25 is not None and p75 is not None and p25 <= p75
    assert changed_p25 is not None and changed_p75 is not None


def test_sweep_extreme_metadata_ignores_post_anchor_candles():
    anchor = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
    pre_times = [anchor - timedelta(minutes=30), anchor - timedelta(minutes=20), anchor - timedelta(minutes=10)]
    post_times = [anchor + timedelta(minutes=1), anchor + timedelta(minutes=2), anchor + timedelta(minutes=3)]
    rows = [
        {"time": t, "open": 4900.0, "high": 4901.0, "low": 4899.0, "close": 4900.0}
        for t in pre_times
    ] + [
        {"time": post_times[0], "open": 4900.0, "high": 4925.0, "low": 4899.0, "close": 4900.0},
        {"time": post_times[1], "open": 4900.0, "high": 4901.0, "low": 4880.0, "close": 4900.0},
        {"time": post_times[2], "open": 4900.0, "high": 4901.0, "low": 4899.0, "close": 4900.0},
    ]
    frames = {"M1": pd.DataFrame(rows), "M5": pd.DataFrame(rows)}
    sample = VisualReviewSample(
        sample_id="",
        source_mode="CANDIDATE_WINDOW_MODE",
        symbol="XAUUSD",
        direction_guess="UNKNOWN",
        anchor_timestamp=anchor,
        anchor_timeframe="M1",
        window_start=anchor - timedelta(minutes=90),
        window_end=anchor + timedelta(minutes=180),
        candidate_reason_codes=("TEST_POST_ANCHOR_ONLY",),
    )
    _annotate_sample_metadata(sample, frames, VisualReviewPackConfig(), {}, {})
    assert sample.candidate_source_type == "UNKNOWN"
    assert sample.entry_level_source == "UNKNOWN"


def test_visual_pack_generation_does_not_modify_input_candle_data(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    m1_path = data_dir / "XAUUSD" / "M1.csv"
    before = m1_path.read_bytes()
    create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=tmp_path / "pack",
            trades_path=tmp_path / "missing.csv",
            audit_path=tmp_path / "missing_audit.csv",
            max_samples=2,
            min_sample_spacing_minutes=0,
        )
    )
    assert m1_path.read_bytes() == before


def test_number_theory_helper_detects_prices_near_levels_ending_in_zero():
    near, level, distance = is_near_number_theory_level(4910.2, symbol="XAUUSD", threshold_pips=5.0)
    assert near is True
    assert level == 4910.0
    assert distance == 2.0
    far, _, far_distance = is_near_number_theory_level(4914.0, symbol="XAUUSD", threshold_pips=5.0)
    assert far is False
    assert far_distance == 40.0


def test_trade_review_mode_uses_audit_rows_when_available(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    audit_path = tmp_path / "audit.csv"
    with audit_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "symbol",
                "trade_id",
                "signal_timestamp",
                "direction",
                "entry_price",
                "stop_loss",
                "take_profit",
                "final_adelin_v2_label",
                "reason_codes",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "symbol": "XAUUSD",
                "trade_id": "old1",
                "signal_timestamp": "2026-01-01T06:00:00Z",
                "direction": "LONG",
                "entry_price": "4900.0",
                "stop_loss": "4898.0",
                "take_profit": "4920.0",
                "final_adelin_v2_label": "NO_TRADE_CONTINUATION_BLOCKED",
                "reason_codes": "OLD_ADELIN_CONTINUATION_TOXIC_AND_BLOCKED",
            }
        )
    output_dir = tmp_path / "pack"
    summary = create_visual_review_pack(
        VisualReviewPackConfig(
            data_dir=data_dir,
            output_dir=output_dir,
            trades_path=tmp_path / "missing.csv",
            audit_path=audit_path,
            max_samples=1,
            include_candidate_windows=False,
        )
    )
    assert summary["audit_rows_loaded"] == 1
    assert summary["source_modes_used"] == ["TRADE_REVIEW_MODE"]
    with (output_dir / "manual_labels_template.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["source_mode"] == "TRADE_REVIEW_MODE"
