from __future__ import annotations

import ast
import csv
import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dazro_trade.analytics.adelin_v2_visual_review_pack import (
    INSUFFICIENT_EXECUTION_DATA,
    MANUAL_LABEL_COLUMNS,
    RESEARCH_WARNING,
    REVIEWABLE_M1_M5,
    REVIEWABLE_M5_ONLY,
    WEAK_M1_ONLY,
    VisualReviewPackConfig,
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
    assert summary["decision_criteria_preregistered"] is True
    assert summary["expanded_pack_generation_verdict"] in {
        "CONTINUE_DETECTOR_REFINEMENT",
        "STOP_ARCHIVE_ADELIN_V2_DETECTOR",
        "REPEAT_EXPANSION_ONCE",
        "INCONCLUSIVE_DATA_QUALITY_LIMITATION",
    }


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
    assert {"candidate_source_type", "entry_level_source", "entry_level_confidence", "session", "month", "volatility_bucket"}.issubset(rows[0].keys())


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
