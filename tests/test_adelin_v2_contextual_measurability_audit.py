from __future__ import annotations

import ast
import csv
import importlib
import json
from pathlib import Path

from dazro_trade.analytics.adelin_v2_contextual_measurability_audit import (
    CONCEPT_MATRIX,
    MEASURABLE_NOW,
    REQUIRED_FIELDS,
    VALID_CATEGORIES,
    VALID_RISKS,
    category_summary,
    validate_concept_matrix,
    write_concept_matrix,
)


REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_CONCEPTS = {
    "HTF liquidity",
    "LTF liquidity",
    "internal liquidity",
    "external liquidity",
    "H1 liquidity sweep",
    "M15 sequence validity",
    "FVG",
    "IFVG",
    "volume profile",
    "volume cracks",
    "number theory",
    "round levels",
    "reaction zones",
    "rejection quality",
    "reclaim quality",
    "accumulation before expansion",
    "immediate expansion",
    "runner expansion",
    "wick/body behavior",
    "displacement",
    "compression before expansion",
    "time-of-day context",
    "session context",
    "multi-timeframe alignment",
    "candle close quality",
    "continuation behavior",
    "failed continuation",
    "volatility regime",
    "trend/range regime",
}


def test_module_import_is_safe():
    module = importlib.import_module(
        "dazro_trade.analytics.adelin_v2_contextual_measurability_audit"
    )
    assert hasattr(module, "CONCEPT_MATRIX")
    assert hasattr(module, "write_concept_matrix")


def test_concept_classification_schema_validates():
    validate_concept_matrix(CONCEPT_MATRIX)
    summary = category_summary(CONCEPT_MATRIX)
    assert sum(summary.values()) == len(CONCEPT_MATRIX)
    assert set(summary).issubset(VALID_CATEGORIES)


def test_every_required_concept_and_field_is_present():
    concept_names = {row.concept_name for row in CONCEPT_MATRIX}
    assert REQUIRED_CONCEPTS.issubset(concept_names)

    for row in CONCEPT_MATRIX:
        row_dict = row.to_csv_row()
        assert set(REQUIRED_FIELDS).issubset(row_dict)
        for field_name in REQUIRED_FIELDS:
            assert row_dict[field_name] not in ("", None)


def test_risk_fields_are_present_and_valid():
    for row in CONCEPT_MATRIX:
        assert row.leakage_risk in VALID_RISKS
        assert row.subjectivity_risk in VALID_RISKS


def test_continuation_is_not_classified_as_positive_feature():
    continuation = next(row for row in CONCEPT_MATRIX if row.concept_name == "continuation behavior")
    assert continuation.category != MEASURABLE_NOW
    assert continuation.pre_entry_available is False
    assert "BANNED_AS_POSITIVE_FEATURE" in continuation.notes
    assert "risk" in continuation.notes.lower()


def test_write_concept_matrix_outputs_csv_and_json(tmp_path: Path):
    paths = write_concept_matrix(tmp_path)
    assert paths["csv"].exists()
    assert paths["json"].exists()

    with paths["csv"].open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert len(rows) == len(CONCEPT_MATRIX)
    assert set(REQUIRED_FIELDS).issubset(rows[0])

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["audit_type"] == "ADELIN_V2_CONTEXTUAL_MEASURABILITY_AUDIT"
    assert payload["safety"]["live_trading_enabled"] is False
    assert payload["safety"]["telegram_trade_alerts_enabled"] is False
    assert payload["safety"]["broker_execution_enabled"] is False
    assert payload["safety"]["order_execution_enabled"] is False
    assert payload["safety"]["strategy_2_touched"] is False
    assert payload["safety"]["strategy_3_touched"] is False
    assert payload["safety"]["adelin_runtime_logic_modified"] is False
    assert payload["safety"]["backtest_run"] is False


def test_module_has_no_trading_runtime_imports_or_calls():
    module_path = (
        REPO_ROOT / "dazro_trade" / "analytics" / "adelin_v2_contextual_measurability_audit.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    forbidden_import_roots = {
        "telegram_bot",
        "mt5_handler",
        "backtest",
        "main",
        "reverse_manager",
        "risk_manager",
    }
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
