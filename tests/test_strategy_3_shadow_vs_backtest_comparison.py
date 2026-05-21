from __future__ import annotations

import csv
import importlib
import json
from pathlib import Path


def _module():
    return importlib.import_module("scripts.compare_strategy_3_shadow_vs_backtest")


def _config(module, tmp_path: Path, paper_dir: Path | None = None):
    return module.CompareConfig(
        paper_dir=paper_dir or tmp_path / "paper",
        data_dir="data",
        output_dir=tmp_path / "comparison",
        symbol="XAUUSD",
        strategy="strategy_3_vwap_1r",
        cooldown_minutes=120,
        price_tolerance_usd=0.01,
        timestamp_tolerance_seconds=0,
    )


def _paper_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "signal_timestamp": "2026-05-14T22:45:00+00:00",
        "symbol": "XAUUSD",
        "strategy": "strategy_3_vwap_1r",
        "mode": "paper_shadow",
        "dry_run": "True",
        "cooldown_minutes": "120",
        "direction": "LONG",
        "entry_price": "100.0",
        "stop_loss": "99.0",
        "take_profit": "101.0",
        "setup_mode": "trend_following",
        "band_touched": "vwap",
        "cooldown_accepted": "True",
        "order_sent": "False",
        "telegram_sent": "False",
        "broker_called": "False",
        "live_trading_enabled": "False",
        "order_execution_enabled": "False",
        "telegram_enabled": "False",
        "vwap_value": "100.0",
        "sigma_1_upper": "101.0",
        "sigma_1_lower": "99.0",
        "sigma_2_upper": "102.0",
        "sigma_2_lower": "98.0",
    }
    row.update(updates)
    return row


def _backtest_row(**updates: object) -> dict[str, object]:
    row = {
        "signal_timestamp": "2026-05-14T22:45:00+00:00",
        "symbol": "XAUUSD",
        "strategy": "strategy_3_vwap_1r",
        "direction": "LONG",
        "entry_price": 100.0,
        "stop_loss": 99.0,
        "take_profit": 101.0,
        "setup_mode": "trend_following",
        "band_touched": "vwap",
        "cooldown_accepted": True,
        "vwap_value": 100.0,
        "sigma_1_upper": 101.0,
        "sigma_1_lower": 99.0,
        "sigma_2_upper": 102.0,
        "sigma_2_lower": 98.0,
    }
    row.update(updates)
    return row


def _write_paper_dir(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    module = _module()
    path.mkdir(parents=True, exist_ok=True)
    fieldnames = fields or list(dict.fromkeys(module.REQUIRED_PAPER_FIELDS + list(_paper_row().keys())))
    with (path / "paper_signals.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    (path / "scanner_summary.json").write_text(json.dumps({"scanner_run_id": "test"}), encoding="utf-8")


def test_import_safe_and_defaults():
    module = _module()
    args = module.parse_args([])
    assert args.price_tolerance_usd == 0.01
    assert args.timestamp_tolerance_seconds == 0
    assert hasattr(module, "main")


def test_empty_paper_signals_writes_summary_and_report(tmp_path):
    module = _module()
    paper = tmp_path / "paper"
    _write_paper_dir(paper, [])

    summary = module.run_comparison(_config(module, tmp_path, paper))

    assert summary["paper_signals_count"] == 0
    assert summary["backtest_signals_count"] == 0
    assert summary["match_rate"] is None
    assert "SHADOW_COMPARISON_NO_PAPER_SIGNALS_YET" in summary["verdict_flags"]
    assert "FRAMEWORK_READY" in summary["verdict_flags"]
    assert "NO_BACKTEST_COMPARISON_PERFORMED" in summary["verdict_flags"]
    assert (tmp_path / "comparison" / "comparison_summary.json").exists()
    assert (tmp_path / "comparison" / "comparison_report.md").exists()
    assert summary["safety"]["order_sent"] is False
    assert summary["safety"]["telegram_sent"] is False
    assert summary["safety"]["broker_called"] is False


def test_missing_schema_fields_are_detected(tmp_path):
    module = _module()
    paper = tmp_path / "paper"
    fields = [field for field in module.REQUIRED_PAPER_FIELDS if field != "broker_called"]
    _write_paper_dir(paper, [_paper_row()], fields=fields)

    summary = module.run_comparison(_config(module, tmp_path, paper))

    assert "broker_called" in summary["missing_schema_fields"]
    assert "SHADOW_SIGNAL_SCHEMA_INCOMPLETE" in summary["verdict_flags"]
    assert summary["mismatch_categories"]["SCHEMA_MISSING_FIELD"] == 1


def test_perfect_match_produces_match_rate_one():
    module = _module()
    result = module.compare_signals([_paper_row()], [_backtest_row()])
    assert result["match_rate"] == 1.0
    assert len(result["matched"]) == 1
    assert not result["mismatched"]


def test_price_and_direction_mismatch_are_categorized():
    module = _module()
    result = module.compare_signals(
        [_paper_row(direction="LONG", entry_price="100.0")],
        [_backtest_row(direction="SHORT", entry_price=100.02)],
        price_tolerance_usd=0.01,
    )
    categories = result["mismatch_categories"]
    assert categories["DIRECTION_MISMATCH"] == 1
    assert categories["ENTRY_PRICE_MISMATCH"] == 1
    assert result["match_rate"] == 0.0


def test_missing_and_extra_are_categorized():
    module = _module()
    missing = module.compare_signals([_paper_row(signal_timestamp="2026-05-14T22:45:00+00:00")], [])
    assert missing["mismatch_categories"]["MISSING_IN_BACKTEST"] == 1
    assert missing["match_rate"] == 0.0

    extra = module.compare_signals([], [_backtest_row()])
    assert extra["mismatch_categories"]["EXTRA_IN_BACKTEST"] == 1
    assert extra["match_rate"] == 0.0


def test_match_rate_formula_uses_max_denominator():
    module = _module()
    result = module.compare_signals([_paper_row()], [_backtest_row(), _backtest_row(signal_timestamp="2026-05-14T23:00:00+00:00")])
    assert result["match_rate"] == 0.5


def test_asymmetric_zero_verdicts():
    module = _module()
    assert "BACKTEST_GENERATES_BUT_SCANNER_DOES_NOT" in module.verdict_flags(
        paper_count=0,
        backtest_count=1,
        match_rate=0,
        missing_schema=[],
        safety_regression=False,
    )
    assert "SCANNER_GENERATES_BUT_BACKTEST_DOES_NOT" in module.verdict_flags(
        paper_count=1,
        backtest_count=0,
        match_rate=0,
        missing_schema=[],
        safety_regression=False,
    )


def test_comparison_window_uses_two_hour_and_five_minute_buffers(tmp_path):
    module = _module()
    cfg = _config(module, tmp_path)
    window = module.paper_window(
        [
            _paper_row(signal_timestamp="2026-05-14T22:45:00+00:00"),
            _paper_row(signal_timestamp="2026-05-14T23:00:00+00:00"),
        ],
        cfg,
    )
    assert window["backtest_from"] == "2026-05-14T20:45:00+00:00"
    assert window["backtest_to"] == "2026-05-14T23:05:00+00:00"


def test_run_comparison_uses_mocked_backtest_for_paper_signal(monkeypatch, tmp_path):
    module = _module()
    paper = tmp_path / "paper"
    _write_paper_dir(paper, [_paper_row()])
    monkeypatch.setattr(module, "build_backtest_comparable_signals", lambda cfg, window: [_backtest_row()])

    summary = module.run_comparison(_config(module, tmp_path, paper))

    assert summary["paper_signals_count"] == 1
    assert summary["backtest_signals_count"] == 1
    assert summary["matched_count"] == 1
    assert summary["match_rate"] == 1.0
    assert "SHADOW_BACKTEST_MATCH_CONFIRMED" in summary["verdict_flags"]
