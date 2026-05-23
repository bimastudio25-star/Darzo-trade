from __future__ import annotations

import importlib
from pathlib import Path


def _module():
    return importlib.import_module("scripts.strategy_3_data_context")


def _write_csv(path: Path, rows: list[str], *, encoding: str = "utf-8", header: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if header:
        lines.append("time,open,high,low,close,tick_volume,spread")
    lines.extend(rows)
    path.write_text("\n".join(lines) + "\n", encoding=encoding)


def test_data_context_hash_is_stable_for_same_file_contents(tmp_path):
    module = _module()
    data_dir = tmp_path / "data"
    _write_csv(data_dir / "XAUUSD" / "H4.csv", ["2026-05-20T00:00:00+00:00,1,2,0,1,10,4"])

    first = module.compute_data_context(symbol="XAUUSD", data_dir=data_dir, timeframes=["H4"])
    second = module.compute_data_context(symbol="XAUUSD", data_dir=data_dir, timeframes=["H4"])

    assert first["combined_data_context_hash"] == second["combined_data_context_hash"]
    assert first["files"]["H4"]["sha256"] == second["files"]["H4"]["sha256"]


def test_data_context_hash_changes_when_h4_file_changes(tmp_path):
    module = _module()
    data_dir = tmp_path / "data"
    path = data_dir / "XAUUSD" / "H4.csv"
    _write_csv(path, ["2026-05-20T00:00:00+00:00,1,2,0,1,10,4"])
    first = module.compute_data_context(symbol="XAUUSD", data_dir=data_dir, timeframes=["H4"])

    _write_csv(path, ["2026-05-20T00:00:00+00:00,1,3,0,1,10,4"])
    second = module.compute_data_context(symbol="XAUUSD", data_dir=data_dir, timeframes=["H4"])

    assert first["combined_data_context_hash"] != second["combined_data_context_hash"]
    assert first["files"]["H4"]["sha256"] != second["files"]["H4"]["sha256"]


def test_utf16_no_header_h4_is_hashed_and_summarized(tmp_path):
    module = _module()
    data_dir = tmp_path / "data"
    path = data_dir / "XAUUSD" / "H4.csv"
    _write_csv(
        path,
        ["2026.05.20 00:00,1,2,0,1,10,4", "2026.05.20 04:00,2,3,1,2,12,4"],
        encoding="utf-16",
        header=False,
    )

    context = module.compute_data_context(symbol="XAUUSD", data_dir=data_dir, timeframes=["H4"])
    h4 = context["files"]["H4"]

    assert h4["exists"] is True
    assert h4["detected_encoding"] == "utf-16"
    assert h4["header_present"] is False
    assert h4["row_count"] == 2
    assert h4["latest_timestamp"] == "2026-05-20T04:00:00+00:00"


def test_missing_file_is_reported_without_crash(tmp_path):
    module = _module()
    context = module.compute_data_context(symbol="XAUUSD", data_dir=tmp_path / "data", timeframes=["H4"])
    h4 = context["files"]["H4"]
    assert h4["exists"] is False
    assert h4["parse_warning"] == "file_missing"
    assert context["combined_data_context_hash"]


def test_diff_contexts_reports_match_missing_and_mismatch(tmp_path):
    module = _module()
    data_dir = tmp_path / "data"
    path = data_dir / "XAUUSD" / "H4.csv"
    _write_csv(path, ["2026-05-20T00:00:00+00:00,1,2,0,1,10,4"])
    paper = module.compute_data_context(symbol="XAUUSD", data_dir=data_dir, timeframes=["H4"])
    backtest = module.compute_data_context(symbol="XAUUSD", data_dir=data_dir, timeframes=["H4"])
    assert module.diff_contexts(paper, backtest)["data_context_match"] is True

    _write_csv(path, ["2026-05-20T00:00:00+00:00,1,3,0,1,10,4"])
    changed = module.compute_data_context(symbol="XAUUSD", data_dir=data_dir, timeframes=["H4"])
    diff = module.diff_contexts(paper, changed)
    assert diff["data_context_match"] is False
    assert diff["mismatched_timeframes"] == ["H4"]
    assert "DATA_CONTEXT_MISMATCH" in diff["verdict_flags"]

    missing = module.diff_contexts(None, changed)
    assert missing["data_context_missing"] is True
    assert "DATA_CONTEXT_MISSING" in missing["verdict_flags"]


def test_prefix_hash_stays_compatible_when_future_rows_are_appended(tmp_path):
    module = _module()
    data_dir = tmp_path / "data"
    path = data_dir / "XAUUSD" / "M15.csv"
    _write_csv(
        path,
        [
            "2026-05-21T02:15:00+00:00,1,2,0,1,10,4",
            "2026-05-21T02:30:00+00:00,2,3,1,2,11,4",
        ],
    )
    before = module.summarize_timeframe_prefix(path, "2026-05-21T02:30:00+00:00")
    _write_csv(
        path,
        [
            "2026-05-21T02:15:00+00:00,1,2,0,1,10,4",
            "2026-05-21T02:30:00+00:00,2,3,1,2,11,4",
            "2026-05-21T02:45:00+00:00,3,4,2,3,12,4",
        ],
    )
    after = module.summarize_timeframe_prefix(path, "2026-05-21T02:30:00+00:00")
    full = module.summarize_timeframe_file(path)

    assert before["raw_prefix_hash"] == after["raw_prefix_hash"]
    assert before["canonical_prefix_hash"] == after["canonical_prefix_hash"]
    assert full["latest_timestamp"] == "2026-05-21T02:45:00+00:00"


def test_prefix_hash_changes_when_historical_row_changes(tmp_path):
    module = _module()
    data_dir = tmp_path / "data"
    path = data_dir / "XAUUSD" / "M15.csv"
    _write_csv(
        path,
        [
            "2026-05-21T02:15:00+00:00,1,2,0,1,10,4",
            "2026-05-21T02:30:00+00:00,2,3,1,2,11,4",
        ],
    )
    before = module.summarize_timeframe_prefix(path, "2026-05-21T02:30:00+00:00")
    _write_csv(
        path,
        [
            "2026-05-21T02:15:00+00:00,1,5,0,1,10,4",
            "2026-05-21T02:30:00+00:00,2,3,1,2,11,4",
        ],
    )
    after = module.summarize_timeframe_prefix(path, "2026-05-21T02:30:00+00:00")

    assert before["raw_prefix_hash"] != after["raw_prefix_hash"]
    assert before["canonical_prefix_hash"] != after["canonical_prefix_hash"]


def test_utf16_no_header_prefix_hash_is_supported(tmp_path):
    module = _module()
    data_dir = tmp_path / "data"
    path = data_dir / "XAUUSD" / "H4.csv"
    _write_csv(
        path,
        ["2026.05.21 00:00,1,2,0,1,10,4", "2026.05.21 04:00,2,3,1,2,12,4"],
        encoding="utf-16",
        header=False,
    )

    prefix = module.summarize_timeframe_prefix(path, "2026-05-21T00:00:00+00:00")

    assert prefix["detected_encoding"] == "utf-16"
    assert prefix["header_present"] is False
    assert prefix["row_count_in_prefix"] == 1
    assert prefix["latest_timestamp_in_prefix"] == "2026-05-21T00:00:00+00:00"
    assert prefix["raw_prefix_hash"]


def test_recorded_prefix_compatibility_detects_append_only_context(tmp_path):
    module = _module()
    data_dir = tmp_path / "data"
    path = data_dir / "XAUUSD" / "M15.csv"
    _write_csv(
        path,
        [
            "2026-05-21T02:15:00+00:00,1,2,0,1,10,4",
            "2026-05-21T02:30:00+00:00,2,3,1,2,11,4",
        ],
    )
    recorded = module.summarize_timeframe_prefix(path, "2026-05-21T02:30:00+00:00")
    _write_csv(
        path,
        [
            "2026-05-21T02:15:00+00:00,1,2,0,1,10,4",
            "2026-05-21T02:30:00+00:00,2,3,1,2,11,4",
            "2026-05-21T02:45:00+00:00,3,4,2,3,12,4",
        ],
    )

    result = module.evaluate_recorded_prefix_compatibility(
        {
            "signal_timestamp": "2026-05-21T02:30:00+00:00",
            "data_context_hash": "full-file-at-signal",
            "m15_hash": recorded["raw_prefix_hash"],
            "m15_latest_timestamp": "2026-05-21T02:30:00+00:00",
        },
        symbol="XAUUSD",
        data_dir=data_dir,
        timeframes=["M15"],
    )

    assert result["prefix_compatible"] is True
    assert result["checked_timeframes"] == ["M15"]


def test_recorded_prefix_compatibility_blocks_historical_mismatch(tmp_path):
    module = _module()
    data_dir = tmp_path / "data"
    path = data_dir / "XAUUSD" / "M15.csv"
    _write_csv(path, ["2026-05-21T02:30:00+00:00,2,3,1,2,11,4"])
    recorded = module.summarize_timeframe_prefix(path, "2026-05-21T02:30:00+00:00")
    _write_csv(path, ["2026-05-21T02:30:00+00:00,2,4,1,2,11,4"])

    result = module.evaluate_recorded_prefix_compatibility(
        {
            "signal_timestamp": "2026-05-21T02:30:00+00:00",
            "data_context_hash": "full-file-at-signal",
            "m15_hash": recorded["raw_prefix_hash"],
            "m15_latest_timestamp": "2026-05-21T02:30:00+00:00",
        },
        symbol="XAUUSD",
        data_dir=data_dir,
        timeframes=["M15"],
    )

    assert result["prefix_compatible"] is False
    assert result["incompatible_timeframes"] == ["M15"]
