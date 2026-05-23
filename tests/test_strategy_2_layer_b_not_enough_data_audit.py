from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.strategy_2_layer_b_not_enough_data_audit import (
    CAUSE_EDGE_OF_DATASET,
    CAUSE_MISSING_CANDLES,
    CAUSE_WINDOW_TOO_SHORT,
    build_not_enough_data_audit,
    candle_window_counts,
    classify_likely_cause,
    grouped_rate_table,
    session_bucket,
    write_not_enough_data_audit_outputs,
)


def _feature_row(
    sample_id: str,
    *,
    direction: str = "LONG",
    descriptor: str = "NOT_ENOUGH_DATA",
    decision_time: str = "",
    start: str = "2026-01-01T00:00:00+00:00",
    end: str = "",
) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "h1_context_id": sample_id.split("_previous")[0],
        "direction_candidate": direction,
        "layer_a_state": "VALID_LONG" if direction == "LONG" else "VALID_SHORT",
        "layer_b_eligible": True,
        "sweep_timestamp": start,
        "decision_time": decision_time,
        "feature_time_boundary": decision_time,
        "data_window_start": start,
        "data_window_end": end,
        "range_reentry_detected": "UNKNOWN" if descriptor == "NOT_ENOUGH_DATA" else "TRUE",
        "reaction_descriptor": descriptor,
        "layer_b_candidate_label": "UNKNOWN_REACTION_CANDIDATE" if descriptor == "NOT_ENOUGH_DATA" else "STRONG_REACTION_CANDIDATE",
        "missing_required_data": descriptor == "NOT_ENOUGH_DATA",
        "null_feature_reasons": "DECISION_TIME_MISSING" if descriptor == "NOT_ENOUGH_DATA" else "",
    }


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    input_path = tmp_path / "layer_b_reaction_features_per_sample.csv"
    pd.DataFrame(
        [
            _feature_row("XAUUSD_20260101000000+0000_previous_h1_containing_LONG", direction="LONG"),
            _feature_row(
                "XAUUSD_20260101140000+0000_previous_h1_containing_SHORT",
                direction="SHORT",
                start="2026-01-01T14:00:00+00:00",
            ),
            _feature_row(
                "XAUUSD_20260101010000+0000_previous_h1_containing_LONG",
                direction="LONG",
                descriptor="FAST_REENTRY",
                decision_time="2026-01-01T01:02:00+00:00",
                start="2026-01-01T01:00:00+00:00",
                end="2026-01-01T01:02:00+00:00",
            ),
            _feature_row(
                "XAUUSD_20260101020000+0000_previous_h1_containing_SHORT",
                direction="SHORT",
                descriptor="CHOP_AFTER_SWEEP_CANDIDATE",
                decision_time="2026-01-01T02:02:00+00:00",
                start="2026-01-01T02:00:00+00:00",
                end="2026-01-01T02:02:00+00:00",
            ),
        ]
    ).to_csv(input_path, index=False)
    state_split = tmp_path / "state_split_per_sample.csv"
    pd.DataFrame({"sample_id": ["placeholder"]}).to_csv(state_split, index=False)
    data_dir = tmp_path / "data"
    symbol_dir = data_dir / "XAUUSD"
    symbol_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            ["2025.12.31 22:00", 100, 101, 99, 100, 1, 0],
            ["2026.01.01 00:00", 100, 101, 99, 100, 1, 0],
            ["2026.01.01 01:00", 100, 101, 99, 100, 1, 0],
            ["2026.01.01 01:01", 100, 101, 99, 100, 1, 0],
            ["2026.01.01 01:02", 100, 101, 99, 100, 1, 0],
            ["2026.01.01 02:00", 100, 101, 99, 100, 1, 0],
            ["2026.01.01 02:02", 100, 101, 99, 100, 1, 0],
            ["2026.01.01 14:00", 100, 101, 99, 100, 1, 0],
            ["2026.01.01 16:00", 100, 101, 99, 100, 1, 0],
        ]
    ).to_csv(symbol_dir / "M1.csv", index=False, header=False)
    return input_path, state_split, data_dir


def test_identifies_not_enough_data_rows_and_rate(tmp_path: Path):
    input_path, state_split, data_dir = _write_fixture(tmp_path)
    result = build_not_enough_data_audit(input_path, state_split_path=state_split, data_dir=data_dir)
    assert len(result.not_enough_data_samples) == 2
    assert result.summary["not_enough_data_count"] == 2
    assert result.summary["not_enough_data_rate"] == 0.5


def test_groups_by_direction_correctly(tmp_path: Path):
    input_path, state_split, data_dir = _write_fixture(tmp_path)
    result = build_not_enough_data_audit(input_path, state_split_path=state_split, data_dir=data_dir)
    by_direction = result.by_direction.set_index("direction_candidate")
    assert by_direction.loc["LONG", "not_enough_data_count"] == 1
    assert by_direction.loc["SHORT", "not_enough_data_count"] == 1


def test_groups_by_hour_session_and_weekday(tmp_path: Path):
    input_path, state_split, data_dir = _write_fixture(tmp_path)
    result = build_not_enough_data_audit(input_path, state_split_path=state_split, data_dir=data_dir)
    by_hour = result.by_hour.set_index("hour_utc")
    assert by_hour.loc[0.0, "not_enough_data_count"] == 1
    assert by_hour.loc[14.0, "not_enough_data_count"] == 1
    assert session_bucket(0) == "ASIA"
    assert session_bucket(14) == "NY"
    by_weekday = result.by_weekday.set_index("weekday")
    assert by_weekday.loc["Thursday", "not_enough_data_count"] == 2


def test_detects_h1_context_concentration(tmp_path: Path):
    input_path, state_split, data_dir = _write_fixture(tmp_path)
    frame = pd.read_csv(input_path)
    frame.loc[1, "h1_context_id"] = frame.loc[0, "h1_context_id"]
    frame.to_csv(input_path, index=False)
    result = build_not_enough_data_audit(input_path, state_split_path=state_split, data_dir=data_dir)
    top = result.by_h1_context.iloc[0]
    assert top["not_enough_data_count"] == 2


def test_handles_missing_decision_time_safely(tmp_path: Path):
    input_path, state_split, data_dir = _write_fixture(tmp_path)
    result = build_not_enough_data_audit(input_path, state_split_path=state_split, data_dir=data_dir)
    assert result.not_enough_data_samples["decision_time"].fillna("").eq("").all()
    assert set(result.not_enough_data_samples["likely_not_enough_data_cause"]) == {CAUSE_WINDOW_TOO_SHORT}


def test_detects_dataset_boundary_proximity():
    row = {
        "near_dataset_start": True,
        "near_dataset_end": False,
        "is_weekend_or_market_gap": False,
        "data_window_start_parsed": pd.Timestamp("2026-01-01T00:00:00Z"),
        "data_window_end_parsed": pd.Timestamp("2026-01-01T00:02:00Z"),
        "expected_candle_count": 3,
        "missing_candle_count": 0,
        "event_timestamp": pd.Timestamp("2026-01-01T00:00:00Z"),
    }
    assert classify_likely_cause(row) == CAUSE_EDGE_OF_DATASET


def test_computes_available_missing_expected_candle_counts():
    ohlc = pd.DataFrame({"time": pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T00:02:00Z"], utc=True)})
    counts = candle_window_counts(
        {
            "data_window_start_parsed": pd.Timestamp("2026-01-01T00:00:00Z"),
            "data_window_end_parsed": pd.Timestamp("2026-01-01T00:02:00Z"),
        },
        ohlc,
    )
    assert counts["expected_candle_count"] == 3
    assert counts["available_candle_count"] == 2
    assert counts["missing_candle_count"] == 1


def test_assigns_missing_candle_cause_conservatively():
    row = {
        "near_dataset_start": False,
        "near_dataset_end": False,
        "is_weekend_or_market_gap": False,
        "data_window_start_parsed": pd.Timestamp("2026-01-01T00:00:00Z"),
        "data_window_end_parsed": pd.Timestamp("2026-01-01T00:02:00Z"),
        "expected_candle_count": 3,
        "missing_candle_count": 1,
        "event_timestamp": pd.Timestamp("2026-01-01T00:00:00Z"),
    }
    assert classify_likely_cause(row) == CAUSE_MISSING_CANDLES


def test_does_not_modify_layer_b_labels_or_descriptors(tmp_path: Path):
    input_path, state_split, data_dir = _write_fixture(tmp_path)
    before = pd.read_csv(input_path)[["sample_id", "reaction_descriptor", "layer_b_candidate_label"]].copy()
    result = build_not_enough_data_audit(input_path, state_split_path=state_split, data_dir=data_dir)
    after = pd.read_csv(input_path)[["sample_id", "reaction_descriptor", "layer_b_candidate_label"]].copy()
    pd.testing.assert_frame_equal(before, after)
    assert set(result.not_enough_data_samples["reaction_descriptor"]) == {"NOT_ENOUGH_DATA"}


def test_grouped_rate_table_computes_rates():
    eligible = pd.DataFrame({"direction": ["LONG", "LONG", "SHORT"]})
    ned = pd.DataFrame({"direction": ["LONG"]})
    result = grouped_rate_table(eligible, ned, "direction", "direction").set_index("direction")
    assert result.loc["LONG", "not_enough_data_rate"] == 0.5
    assert result.loc["SHORT", "not_enough_data_rate"] == 0.0


def test_write_outputs_creates_required_files(tmp_path: Path):
    input_path, state_split, data_dir = _write_fixture(tmp_path)
    result = build_not_enough_data_audit(input_path, state_split_path=state_split, data_dir=data_dir)
    paths = write_not_enough_data_audit_outputs(result, tmp_path / "output", docs_path=tmp_path / "doc.md")
    for key in [
        "not_enough_data_samples",
        "by_direction",
        "by_hour",
        "by_session",
        "by_weekday",
        "by_h1_context",
        "cause_breakdown",
        "comparison",
        "summary",
        "report",
        "docs",
    ]:
        assert Path(paths[key]).exists()


def test_no_forbidden_imports_no_data_writes_no_manual_pack_or_metrics():
    paths = [
        Path("dazro_trade/analytics/strategy_2_layer_b_not_enough_data_audit.py"),
        Path("scripts/analyze_strategy_2_layer_b_not_enough_data_audit.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden_strategy = "strategy" + "_3"
    forbidden_adelin = "dazro_trade." + "adelin"
    assert forbidden_strategy not in combined
    assert forbidden_adelin not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "open(\"data/xauusd" not in combined
    assert "order_send(" not in combined
    assert "generate_signal" not in combined
    assert "send_signal" not in combined
    assert "profit_factor" not in combined
    assert "r_multiple" not in combined
    assert "win_rate" not in combined
    assert "grid_search" not in combined


def test_import_safe_script():
    module = importlib.import_module("scripts.analyze_strategy_2_layer_b_not_enough_data_audit")
    assert hasattr(module, "main")
    assert hasattr(module, "run")
