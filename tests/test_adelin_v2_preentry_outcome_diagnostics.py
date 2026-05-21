from __future__ import annotations

import ast
import csv
import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from scripts.analyze_adelin_v2_preentry_outcome_diagnostics import (
    DiagnosticConfig,
    compute_sample_diagnostic,
    feature_flags,
    run_diagnostics,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _frame(start: datetime, rows: int, minutes: int, base: float = 1000.0) -> pd.DataFrame:
    data = []
    for i in range(rows):
        ts = pd.Timestamp(start + timedelta(minutes=i * minutes))
        price = base + i * 0.2
        data.append(
            {
                "time": ts,
                "open": price,
                "high": price + 0.8,
                "low": price - 0.4,
                "close": price + 0.2,
                "tick_volume": 100 + i,
            }
        )
    return pd.DataFrame(data)


def _frames() -> dict[str, pd.DataFrame]:
    start = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    m1 = _frame(start, 90, 1)
    # Force strong favorable move immediately after 08:30 for LONG.
    for idx in range(31, 45):
        m1.loc[idx, "high"] = 1018.0
        m1.loc[idx, "low"] = 1005.9
        m1.loc[idx, "close"] = 1017.0
    return {
        "M1": m1,
        "M5": _frame(start, 24, 5),
        "M15": _frame(start, 12, 15),
        "H1": _frame(start, 4, 60),
    }


def test_module_import_is_safe():
    module = importlib.import_module("scripts.analyze_adelin_v2_preentry_outcome_diagnostics")
    assert hasattr(module, "run_diagnostics")


def test_long_replay_computes_good_fast_reaction():
    decision = "2026-01-01T08:30:00+00:00"
    row = compute_sample_diagnostic(
        {
            "sample_id": "s1",
            "symbol": "XAUUSD",
            "direction_guess": "LONG",
            "anchor_timestamp": decision,
            "execution_data_status": "REVIEWABLE_M1_M5",
        },
        _frames(),
        "XAUUSD",
        0.1,
        60,
    )
    assert row["post_entry_replay_available"] is True
    assert row["max_favorable_pips"] >= 100
    assert "FAST_REACTION" in row["win_mode_tags"]
    assert row["final_diagnostic_outcome"] == "GOOD_FAST_REACTION"


def test_unknown_direction_is_insufficient_not_guessed():
    row = compute_sample_diagnostic(
        {
            "sample_id": "s_unknown",
            "symbol": "XAUUSD",
            "direction_guess": "UNKNOWN",
            "anchor_timestamp": "2026-01-01T08:30:00+00:00",
        },
        _frames(),
        "XAUUSD",
        0.1,
        60,
    )
    assert row["post_entry_replay_available"] is False
    assert row["final_diagnostic_outcome"] == "INSUFFICIENT_DATA"
    assert "UNKNOWN_DIRECTION_NO_DIRECTIONAL_REPLAY" in row["limitations"]


def test_feature_flags_are_pre_entry_only_metadata():
    row = {
        "numeric_level_confluence_20p": True,
        "nearest_fvg_ifvg_distance_pips": 5.0,
        "expansion_before_decision_proxy": False,
        "compression_overlap_proxy": True,
        "volume_crack_proxy": False,
        "session": "LONDON_OPEN",
        "volatility_range_context": "MID",
        "target_space_proxy_pips": 120.0,
    }
    flags = feature_flags(row)
    assert flags["numeric_level_confluence_20p"] is True
    assert flags["fvg_ifvg_near_20p"] is True
    assert flags["premium_session_open"] is True
    assert flags["clean_target_space_proxy"] is True


def test_run_diagnostics_writes_expected_outputs(tmp_path: Path):
    data_dir = tmp_path / "data"
    symbol_dir = data_dir / "XAUUSD"
    symbol_dir.mkdir(parents=True)
    start = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    for tf, rows, step in [("M1", 90, 1), ("M5", 24, 5), ("M15", 12, 15), ("H1", 4, 60)]:
        frame = _frame(start, rows, step)
        frame.to_csv(symbol_dir / f"{tf}.csv", index=False)

    visual_dir = tmp_path / "visual"
    visual_dir.mkdir()
    with (visual_dir / "manual_labels_template.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["sample_id", "source_mode", "symbol", "direction_guess", "anchor_timestamp"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "sample_id": "sample_001",
                "source_mode": "CANDIDATE_WINDOW_MODE",
                "symbol": "XAUUSD",
                "direction_guess": "LONG",
                "anchor_timestamp": "2026-01-01T08:30:00+00:00",
            }
        )

    output_dir = tmp_path / "out"
    summary = run_diagnostics(
        DiagnosticConfig(
            symbol="XAUUSD",
            data_dir=data_dir,
            visual_pack_dir=visual_dir,
            output_dir=output_dir,
            forward_minutes=60,
        )
    )
    assert summary["total_samples_analyzed"] == 1
    assert (output_dir / "sample_diagnostics.csv").exists()
    assert (output_dir / "feature_outcome_summary.csv").exists()
    assert (output_dir / "summary.json").exists()


def test_generated_smoke_summary_has_required_flags():
    path = REPO_ROOT / "backtests" / "reports" / "adelin_v2_preentry_outcome_diagnostics" / "summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["total_samples_analyzed"] == 40
    assert payload["samples_with_sufficient_data"] + payload["samples_with_insufficient_data"] == 40
    assert "STATIC_LABELING_NOT_USABLE" in payload["verdict_flags"]
    assert payload["safety"]["matched_control_replay_run"] is False
    assert payload["safety"]["v3_stash_applied_or_popped"] is False


def test_script_has_no_broker_order_telegram_calls():
    path = REPO_ROOT / "scripts" / "analyze_adelin_v2_preentry_outcome_diagnostics.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden_import_roots = {"telegram", "MetaTrader5", "mt5_handler", "main", "runtime"}
    forbidden_call_names = {"order_send", "send_message"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_import_roots
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_import_roots
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                assert func.id not in forbidden_call_names
            if isinstance(func, ast.Attribute):
                assert func.attr not in forbidden_call_names
