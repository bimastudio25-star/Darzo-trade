from __future__ import annotations

import ast
import csv
import importlib
import json
import subprocess
import sys
from pathlib import Path

from dazro_trade.analytics.adelin_v2_operational_audit import (
    AdelinV2AuditConfig,
    AdelinV2SetupClass,
    audit_trade_row,
    nearest_number_theory_level,
    number_theory_distance_pips,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_module_import_is_safe():
    module = importlib.import_module("dazro_trade.analytics.adelin_v2_operational_audit")
    assert hasattr(module, "audit_trade_row")


def test_continuation_trades_are_blocked_by_v2_label():
    record = audit_trade_row(
        {
            "strategy": "strategy_1_adelin_scalp",
            "continuation": "true",
            "entry_price": "4900.0",
            "stop_loss": "4898.0",
        }
    )
    assert record.final_adelin_v2_label == AdelinV2SetupClass.NO_TRADE_CONTINUATION_BLOCKED
    assert record.continuation_blocked is True
    assert "OLD_ADELIN_CONTINUATION_TOXIC_AND_BLOCKED" in record.reason_codes


def test_missing_context_returns_unknown_not_invented_confidence():
    record = audit_trade_row(
        {
            "strategy": "strategy_1_adelin_scalp",
            "entry_price": "4900.0",
            "stop_loss": "4898.0",
            "score": "82",
        }
    )
    assert record.final_adelin_v2_label == AdelinV2SetupClass.UNKNOWN_INSUFFICIENT_DATA
    assert "MISSING_REACTION_ZONE_CONTEXT" in record.limitations
    assert "EXISTING_EXPORT_MISSING_ADELIN_V2_CONTEXT" in record.reason_codes
    assert "OLD_SCORE_NOT_PREDICTIVE" in record.reason_codes


def test_sl_over_40_pips_is_flagged():
    record = audit_trade_row(
        {
            "strategy": "strategy_1_adelin_scalp",
            "entry_price": "4900.0",
            "stop_loss": "4895.0",
            "reaction_zone_type": "OLD_REJECTION",
            "target_liquidity_available": "true",
        }
    )
    assert record.required_sl_pips == 50.0
    assert record.sl_within_40_pips is False
    assert record.final_adelin_v2_label == AdelinV2SetupClass.NO_TRADE_SL_TOO_WIDE
    assert "REQUIRED_SL_EXCEEDS_ADELIN_V2_MAX" in record.reason_codes


def test_rejection_non_continuation_is_candidate_not_a_plus():
    record = audit_trade_row(
        {
            "strategy": "strategy_1_adelin_scalp",
            "rejection": "true",
            "continuation": "false",
            "entry_price": "4900.0",
            "stop_loss": "4898.0",
        }
    )
    assert record.final_adelin_v2_label == AdelinV2SetupClass.VALID_REVERSAL
    assert record.final_adelin_v2_label != AdelinV2SetupClass.A_PLUS_REVERSAL
    assert "VALID_REVERSAL_CANDIDATE_REQUIRES_VISUAL_REVIEW" in record.reason_codes


def test_number_theory_detection_for_levels_ending_in_zero():
    assert nearest_number_theory_level(4900.2) == 4900.0
    assert nearest_number_theory_level(4910.3) == 4910.0
    assert nearest_number_theory_level(4829.8) == 4830.0
    level, distance = number_theory_distance_pips(4910.2, pip_size=0.1)
    assert level == 4910.0
    assert distance == 2.0
    record = audit_trade_row(
        {"strategy": "strategy_1_adelin_scalp", "entry_price": "4910.2"},
        AdelinV2AuditConfig(number_theory_threshold_pips=5.0),
    )
    assert record.number_theory_confluence is True
    assert record.distance_to_number_level_pips == 2.0


def test_script_writes_csv_json_and_markdown_and_ignores_strategy_2(tmp_path: Path):
    trades_path = tmp_path / "executed_trades.csv"
    output_dir = tmp_path / "audit"
    rows = [
        {
            "trade_id": "a1",
            "strategy": "strategy_1_adelin_scalp",
            "signal_timestamp": "2026-01-01T09:00:00Z",
            "direction": "LONG",
            "entry_price": "4900.0",
            "stop_loss": "4898.0",
            "continuation": "true",
        },
        {
            "trade_id": "s2",
            "strategy": "strategy_2_liquidity_expansion",
            "signal_timestamp": "2026-01-01T10:00:00Z",
            "direction": "SHORT",
            "entry_price": "4905.0",
            "stop_loss": "4907.0",
        },
        {
            "trade_id": "a2",
            "strategy": "Adelin",
            "signal_timestamp": "2026-01-01T15:30:00Z",
            "direction": "SHORT",
            "entry_price": "4910.1",
            "stop_loss": "4912.0",
            "rejection": "true",
        },
    ]
    with trades_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = sorted({key for row in rows for key in row})
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "analyze_adelin_v2_operational_audit.py"),
            "--symbol",
            "XAUUSD",
            "--data-dir",
            str(tmp_path / "data"),
            "--trades-path",
            str(trades_path),
            "--output-dir",
            str(output_dir),
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "trades_audited" in result.stdout
    csv_path = output_dir / "adelin_v2_trade_audit.csv"
    json_path = output_dir / "adelin_v2_audit_summary.json"
    md_path = output_dir / "adelin_v2_operational_audit.md"
    assert csv_path.exists()
    assert json_path.exists()
    assert md_path.exists()
    summary = json.loads(json_path.read_text(encoding="utf-8"))
    assert summary["source_rows_loaded"] == 3
    assert summary["trades_audited"] == 2
    assert summary["continuation_blocked_count"] == 1
    assert summary["possible_reversal_count"] == 1
    audited_rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    assert [row["trade_id"] for row in audited_rows] == ["a1", "a2"]


def test_no_live_telegram_or_order_imports_are_used():
    paths = [
        REPO_ROOT / "dazro_trade" / "analytics" / "adelin_v2_operational_audit.py",
        REPO_ROOT / "scripts" / "analyze_adelin_v2_operational_audit.py",
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
        assert "order_send" not in path.read_text(encoding="utf-8")
