from __future__ import annotations

import csv
import importlib
import json
from pathlib import Path


def _context_module():
    return importlib.import_module("scripts.strategy_3_data_context")


def _comparison_module():
    return importlib.import_module("scripts.compare_strategy_3_paper_vs_backtest")


def _write_tf(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("time,open,high,low,close,tick_volume,spread\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _paper_row(timestamp: str, context_hash: str, m15_hash: str) -> dict[str, object]:
    return {
        "signal_timestamp": timestamp,
        "symbol": "XAUUSD",
        "strategy": "strategy_3_vwap_1r",
        "direction": "LONG",
        "entry_price": "4500.00",
        "stop_loss": "4498.00",
        "take_profit": "4502.00",
        "setup_mode": "trend_following",
        "band_touched": "vwap",
        "cooldown_accepted": "True",
        "order_sent": "False",
        "telegram_sent": "False",
        "broker_called": "False",
        "data_context_hash": context_hash,
        "m15_hash": m15_hash,
        "m15_latest_timestamp": timestamp,
    }


def test_multiple_row_contexts_are_segmented_by_prefix_compatibility(tmp_path):
    context = _context_module()
    data_dir = tmp_path / "data"
    m15_path = data_dir / "XAUUSD" / "M15.csv"
    _write_tf(m15_path, ["2026-05-21T02:30:00+00:00,1,2,0,1,10,4"])
    first_hash = context.summarize_timeframe_prefix(m15_path, "2026-05-21T02:30:00+00:00")["raw_prefix_hash"]
    _write_tf(
        m15_path,
        [
            "2026-05-21T02:30:00+00:00,1,2,0,1,10,4",
            "2026-05-21T03:00:00+00:00,2,3,1,2,11,4",
        ],
    )
    second_hash = context.summarize_timeframe_prefix(m15_path, "2026-05-21T03:00:00+00:00")["raw_prefix_hash"]

    report = context.build_prefix_compatibility_report(
        [
            _paper_row("2026-05-21T02:30:00+00:00", "ctx-a", first_hash),
            _paper_row("2026-05-21T03:00:00+00:00", "ctx-b", second_hash),
        ],
        symbol="XAUUSD",
        data_dir=data_dir,
        timeframes=["M15"],
    )

    assert report["unique_full_data_contexts"] == 2
    assert report["prefix_compatible_rows"] == 2
    assert report["prefix_incompatible_rows"] == 0
    assert "DATA_CONTEXT_FULL_HASH_DIFF_BUT_PREFIX_OK" in report["verdict_flags"]


def test_prefix_mismatch_blocks_clean_context_diff(tmp_path):
    comparison = _comparison_module()
    prefix_report = {
        "all_required_rows_compatible": False,
        "prefix_compatible_rows": 0,
        "prefix_incompatible_rows": 1,
        "insufficient_context_rows": 0,
        "verdict_flags": ["DATA_CONTEXT_PREFIX_MISMATCH"],
    }
    paper_context = {"combined_data_context_hash": "ctx", "files": {"M15": {"sha256": "same"}}}
    backtest_context = {"combined_data_context_hash": "ctx", "files": {"M15": {"sha256": "same"}}}
    cfg = comparison.PaperVsBacktestConfig(
        symbol="XAUUSD",
        data_dir=str(tmp_path / "data"),
        paper_signals_path=tmp_path / "paper.csv",
        scanner_summary_path=tmp_path / "scanner.json",
        pipeline_summary_path=tmp_path / "pipeline.json",
        output_dir=tmp_path / "out",
        cooldown_minutes=120,
        timestamp_tolerance_seconds=0,
        price_tolerance=0.01,
        dry_run=True,
        require_data_context=True,
        exclude_legacy_without_context=True,
        clean_context_only=True,
    )

    diff = comparison.clean_context_data_context_diff(
        paper_context=paper_context,
        backtest_context=backtest_context,
        segmentation={"data_context_hash_counts": {"ctx-a": 1}, "context_tagged_rows": 1, "legacy_without_context_rows": 0},
        cfg=cfg,
        prefix_report=prefix_report,
    )

    assert diff["data_context_match"] is False
    assert "DATA_CONTEXT_PREFIX_MISMATCH" in diff["verdict_flags"]
    assert "COMPARISON_NOT_CLEAN_VALIDATION" in diff["verdict_flags"]


def test_segmented_outputs_are_written(tmp_path):
    comparison = _comparison_module()
    summary = {
        "run_finished_at": "2026-05-23T00:00:00+00:00",
        "symbol": "XAUUSD",
        "total_paper_rows": 2,
        "legacy_without_context_rows": 0,
        "context_tagged_rows": 2,
        "unique_data_context_hashes": 2,
        "data_context_hash_counts": {"ctx-a": 1, "ctx-b": 1},
        "match_rate_all_detected": 1.0,
        "match_rate_accepted_only": 1.0,
        "verdict_flags": ["DATA_CONTEXT_SEGMENTED_COMPATIBLE"],
        "data_context": {
            "prefix_compatibility": {
                "context_cutoff_policy": "paper_latest_per_timeframe",
                "prefix_compatible_rows": 2,
                "prefix_incompatible_rows": 0,
                "insufficient_context_rows": 0,
                "details": [
                    {
                        "signal_timestamp": "2026-05-21T02:30:00+00:00",
                        "data_context_hash": "ctx-a",
                        "prefix_compatible": True,
                        "prefix_insufficient": False,
                        "checked_timeframes": ["M15"],
                        "compatible_timeframes": ["M15"],
                        "incompatible_timeframes": [],
                        "insufficient_timeframes": [],
                        "unverified_timeframes": ["H4"],
                        "context_generation_mode": "PREFIX_COMPATIBLE_RECONSTRUCTED_FROM_RECORDED_TIMEFRAME_HASHES",
                        "timeframes": {},
                    }
                ],
            }
        },
    }

    comparison.write_segmentation_outputs(tmp_path / "segmentation", summary)

    assert (tmp_path / "segmentation" / "data_context_segmentation_summary.json").exists()
    with (tmp_path / "segmentation" / "data_context_prefix_compatibility.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["prefix_compatible"] == "True"
