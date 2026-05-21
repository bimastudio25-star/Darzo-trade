from __future__ import annotations

import csv
import importlib
from pathlib import Path

from dazro_trade.analytics.strategy_2_manual_benchmark import (
    MANUAL_BENCHMARK_FIELDS,
    build_manual_benchmark_analysis,
    compute_outcome_metrics,
    normalize_manual_benchmark_row,
    validate_manual_benchmark_rows,
    write_manual_benchmark_outputs,
    write_manual_benchmark_template,
)


def _row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {field: "" for field in MANUAL_BENCHMARK_FIELDS}
    row.update(
        {
            "sample_id": "S2_MANUAL_001",
            "symbol": "XAUUSD",
            "session": "London",
            "h1_open_time": "2026-05-20T09:00:00+00:00",
            "decision_time": "2026-05-20T09:18:00+00:00",
            "direction": "long",
            "h1_reference_mode": "previous_h1",
            "h1_liquidity_level_type": "h1_low",
            "h1_liquidity_level_price": "2400.0",
            "h1_range_high": "2410.0",
            "h1_range_low": "2400.0",
            "h1_range_size": "10.0",
            "first_m15_open_time": "2026-05-20T09:15:00+00:00",
            "first_m15_high": "2407.0",
            "first_m15_low": "2398.0",
            "opposite_m15_level_taken_first": "false",
            "liquidity_level_taken": "true",
            "m15_sequence_valid": "true",
            "sweep_depth_usd": "4.5",
            "reaction_type": "reclaim",
            "reclaim_detected": "true",
            "rejection_detected": "false",
            "price_reentered_range": "true",
            "reaction_speed_label": "fast",
            "mae_reference_used": "manual",
            "entry_price": "2395.0",
            "stop_loss": "2383.0",
            "tp1": "2416.0",
            "tp2": "2433.0",
            "tp3": "2450.0",
            "tp4": "2467.0",
            "tp_anchor_level": "2400.0",
            "be_after_tp1": "true",
            "expected_management": "partial_tp1_then_be",
            "user_decision": "TAKE",
            "user_quality": "A_PLUS",
            "user_reason_text": "Clean manual benchmark example.",
            "measurable_reason_tags": "m15_sequence_valid;reentered_range",
            "discretionary_reason_tags": "clean_feel",
            "actual_outcome": "TP1",
            "final_r_multiple": "0.5",
            "screenshot_before_path": "screenshots/before.png",
        }
    )
    row.update(updates)
    return row


def test_label_schema_validates_take_sample_and_computes_distances():
    validation = validate_manual_benchmark_rows([_row()], pip_factor=10)
    assert validation["valid"] is True
    normalized = validation["normalized_rows"][0]
    assert normalized["sweep_depth_pips"] == "45"
    assert normalized["sl_distance_usd"] == "12"
    assert normalized["sl_distance_warning"] == "FALSE"
    assert normalized["tp_anchor_valid"] == "TRUE"


def test_take_samples_require_entry_stop_tp1_and_reason():
    validation = validate_manual_benchmark_rows([_row(entry_price="", stop_loss="", tp1="", user_reason_text="")])
    assert validation["valid"] is False
    fields = {error["field"] for error in validation["errors"]}
    assert {"entry_price", "stop_loss", "tp1", "user_reason_text"}.issubset(fields)


def test_skip_samples_do_not_require_outcome_or_trade_prices():
    validation = validate_manual_benchmark_rows(
        [
            _row(
                sample_id="S2_SKIP_001",
                user_decision="SKIP",
                user_quality="C",
                entry_price="",
                stop_loss="",
                tp1="",
                actual_outcome="",
                final_r_multiple="",
                user_reason_text="M15 sequence had already consumed the move.",
                measurable_reason_tags="opposite_m15_taken_first",
                be_after_tp1="unknown",
            )
        ]
    )
    assert validation["valid"] is True
    assert validation["normalized_rows"][0]["actual_outcome"] == "UNKNOWN"


def test_user_reason_text_is_required_for_all_rows():
    validation = validate_manual_benchmark_rows([_row(user_decision="UNCERTAIN", user_reason_text="")])
    assert validation["valid"] is False
    assert any(error["field"] == "user_reason_text" for error in validation["errors"])


def test_tp_anchor_check_and_sl_warning_work():
    normalized = normalize_manual_benchmark_row(_row(tp_anchor_level="2395.0", stop_loss="2375.0"), pip_factor=10)
    assert normalized["tp_anchor_valid"] == "FALSE"
    assert normalized["sl_distance_usd"] == "20"
    assert normalized["sl_distance_warning"] == "TRUE"


def test_gross_wr_decisive_wr_and_be_rate_are_separate():
    rows = [
        normalize_manual_benchmark_row(_row(sample_id="WIN", actual_outcome="TP1", final_r_multiple="0.5")),
        normalize_manual_benchmark_row(_row(sample_id="BE", actual_outcome="BE", final_r_multiple="0")),
        normalize_manual_benchmark_row(_row(sample_id="SL", actual_outcome="SL", final_r_multiple="-1")),
        normalize_manual_benchmark_row(_row(sample_id="TO", actual_outcome="TIMEOUT", final_r_multiple="-0.2")),
    ]
    metrics = compute_outcome_metrics(rows)
    assert metrics["gross_wr_including_be_timeout"] == 0.25
    assert metrics["decisive_wr_excluding_be"] == 0.3333
    assert metrics["be_rate"] == 0.25


def test_template_and_analysis_outputs_are_created(tmp_path: Path):
    template_paths = write_manual_benchmark_template(tmp_path / "template")
    template_path = Path(template_paths["manual_labels_template_csv"])
    with template_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        headers = next(reader)
    assert headers == MANUAL_BENCHMARK_FIELDS

    labels_path = tmp_path / "labels.csv"
    with labels_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANUAL_BENCHMARK_FIELDS)
        writer.writeheader()
        writer.writerow(_row())
        writer.writerow(
            _row(
                sample_id="S2_SKIP_001",
                user_decision="SKIP",
                user_quality="C",
                user_reason_text="Skipped because the move was consumed.",
                measurable_reason_tags="move_consumed",
                entry_price="",
                stop_loss="",
                tp1="",
                actual_outcome="",
                final_r_multiple="",
                be_after_tp1="unknown",
            )
        )
    result = build_manual_benchmark_analysis(labels_path)
    assert result.summary["take_count"] == 1
    assert result.summary["skip_count"] == 1
    paths = write_manual_benchmark_outputs(result, tmp_path / "output", docs_path=tmp_path / "doc.md")
    assert Path(paths["validation_json"]).exists()
    assert Path(paths["summary_json"]).exists()
    assert Path(paths["take_samples_csv"]).exists()
    assert Path(paths["skip_samples_csv"]).exists()
    assert Path(paths["feature_distribution_csv"]).exists()
    assert Path(paths["reason_tags_summary_csv"]).exists()
    assert Path(paths["docs_md"]).exists()


def test_verdict_flags_keep_strategy_research_only():
    validation = validate_manual_benchmark_rows([_row()])
    result = build_manual_benchmark_analysis_from_rows(validation["normalized_rows"])
    assert "STRATEGY_2_MANUAL_SAMPLE_TOO_SMALL_FOR_EDGE" in result.summary["verdict_flags"]
    assert "STRATEGY_2_REMAINS_RESEARCH_ONLY" in result.summary["verdict_flags"]
    assert "NO_LIVE_DEPLOYMENT_DECISION" in result.summary["verdict_flags"]
    assert "live-ready" not in result.report_markdown.lower()


def test_new_code_does_not_import_forbidden_runtime_paths_or_write_market_data():
    paths = [
        Path("dazro_trade/analytics/strategy_2_manual_benchmark.py"),
        Path("scripts/create_strategy_2_manual_label_template.py"),
        Path("scripts/analyze_strategy_2_manual_benchmark.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden_strategy = "strategy" + "_3"
    forbidden_adelin_import = "dazro_trade." + "adelin"
    assert forbidden_strategy not in combined
    assert forbidden_adelin_import not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "open(\"data/xauusd" not in combined
    assert "order_send(" not in combined
    assert "telegram_bot" not in combined
    assert "mt5_handler" not in combined


def test_scripts_are_import_safe():
    create_module = importlib.import_module("scripts.create_strategy_2_manual_label_template")
    analyze_module = importlib.import_module("scripts.analyze_strategy_2_manual_benchmark")
    assert hasattr(create_module, "main")
    assert hasattr(analyze_module, "main")


def build_manual_benchmark_analysis_from_rows(rows: list[dict[str, object]]):
    tmp = Path.cwd() / ".pytest_tmp_manual_benchmark"
    tmp.mkdir(exist_ok=True)
    labels = tmp / "labels.csv"
    try:
        with labels.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=MANUAL_BENCHMARK_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return build_manual_benchmark_analysis(labels)
    finally:
        if labels.exists():
            labels.unlink()
        try:
            tmp.rmdir()
        except OSError:
            pass
