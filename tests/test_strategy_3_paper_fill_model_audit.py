from __future__ import annotations

import csv
import hashlib
import importlib
import json
from pathlib import Path


def _module():
    return importlib.import_module("scripts.analyze_strategy_3_paper_fill_model_audit")


def _write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _signal(
    timestamp: str = "2026-05-21T00:00:00+00:00",
    *,
    accepted: bool = True,
    direction: str = "LONG",
    entry: object = 100.0,
    stop: object = 99.0,
    tp: object = 101.0,
    context: bool = True,
) -> dict[str, object]:
    return {
        "signal_timestamp": timestamp,
        "symbol": "XAUUSD",
        "strategy": "strategy_3_vwap_1r",
        "direction": direction,
        "entry_price": entry,
        "stop_loss": stop,
        "take_profit": tp,
        "risk_distance": abs(float(entry) - float(stop)) if str(entry) and str(stop) else "",
        "cooldown_status": "accepted" if accepted else "blocked",
        "cooldown_accepted": str(accepted),
        "cooldown_block_reason": "" if accepted else "STRATEGY_3_COOLDOWN_BLOCKED",
        "data_context_hash": "ctx" if context else "",
    }


def _candle(time: str, high: float, low: float, close: float) -> dict[str, object]:
    return {"time": time, "open": close, "high": high, "low": low, "close": close, "tick_volume": 1, "spread": 4}


def _fixture(tmp_path: Path, paper_rows: list[dict[str, object]], m1_rows: list[dict[str, object]], lifecycle_rows: list[dict[str, object]] | None = None):
    module = _module()
    paper = tmp_path / "paper_signals.csv"
    _write_csv(paper, paper_rows)
    data_file = tmp_path / "data" / "XAUUSD" / "M1.csv"
    _write_csv(data_file, m1_rows, ["time", "open", "high", "low", "close", "tick_volume", "spread"])
    lifecycle = tmp_path / "lifecycle" / "paper_signal_outcomes.csv"
    if lifecycle_rows is None:
        lifecycle_rows = []
    _write_csv(lifecycle, lifecycle_rows or [{"decision_timestamp": "", "direction": "", "outcome_status": ""}])
    lifecycle_summary = tmp_path / "lifecycle" / "paper_lifecycle_summary.json"
    lifecycle_summary.write_text(
        json.dumps(
            {
                "methodology": {"fill_model": "PAPER_REFERENCE_FILL_AT_SIGNAL"},
                "tp_hit_count": 1,
                "sl_hit_count": 0,
                "ambiguous_intrabar_count": 0,
                "decisive_win_rate_tp_vs_sl_only": 1.0,
                "total_outcome_r": 1.0,
            }
        ),
        encoding="utf-8",
    )
    cfg = module.FillAuditConfig(
        symbol="XAUUSD",
        data_dir=str(tmp_path / "data"),
        paper_signals_path=paper,
        lifecycle_outcomes_path=lifecycle,
        lifecycle_summary_path=lifecycle_summary,
        evidence_gate_status_path=tmp_path / "gate_status.json",
        evidence_refresh_summary_path=tmp_path / "refresh_summary.json",
        output_dir=tmp_path / "out",
        docs_path=tmp_path / "docs" / "fill_audit.md",
        dry_run=True,
        include_legacy=False,
        forward_timeframe="M1",
        fallback_timeframe="M5",
        max_forward_bars=3,
    )
    return module, cfg, data_file


def _summary_by_model(summary: dict[str, object]) -> dict[str, dict[str, object]]:
    return {row["fill_model"]: row for row in summary["fill_model_comparison"]}  # type: ignore[index]


def test_import_safe_and_cli_defaults():
    module = _module()
    args = module.parse_args([])
    assert args.symbol == "XAUUSD"
    assert args.max_forward_bars == 480
    assert hasattr(module, "run_audit")


def test_audit_output_files_are_created(tmp_path):
    lifecycle_rows = [{"decision_timestamp": "2026-05-21T00:00:00+00:00", "direction": "LONG", "outcome_status": "TP_HIT"}]
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal()],
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 100.0, 101.0)],
        lifecycle_rows,
    )
    summary = module.run_audit(cfg)

    assert summary["selection"]["accepted_signals"] == 1
    assert (cfg.output_dir / "fill_model_audit_per_signal.csv").exists()
    assert (cfg.output_dir / "fill_model_comparison_summary.csv").exists()
    assert (cfg.output_dir / "fill_model_audit_summary.json").exists()
    assert (cfg.output_dir / "fill_model_sensitivity_flags.json").exists()
    assert (cfg.output_dir / "paper_fill_model_audit.md").exists()


def test_reference_fill_model_reproduces_current_lifecycle_for_controlled_input(tmp_path):
    lifecycle_rows = [{"decision_timestamp": "2026-05-21T00:00:00+00:00", "direction": "LONG", "outcome_status": "TP_HIT"}]
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal()],
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 100.0, 101.0)],
        lifecycle_rows,
    )
    summary = module.run_audit(cfg)
    models = _summary_by_model(summary)

    assert models[module.REFERENCE_MODEL]["tp_hit_count"] == 1
    assert models[module.REFERENCE_MODEL]["decisive_win_rate_tp_vs_sl_only"] == 1.0
    rows = module._read_csv(cfg.output_dir / "fill_model_audit_per_signal.csv")
    assert rows[0]["current_lifecycle_outcome_status"] == "TP_HIT"
    assert rows[0]["reference_fill_outcome_status"] == "TP_HIT"


def test_pending_touch_model_can_produce_entry_not_triggered(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal()],
        [
            _candle("2026-05-21T00:01:00+00:00", 101.2, 100.2, 101.0),
            _candle("2026-05-21T00:02:00+00:00", 102.0, 101.1, 101.5),
        ],
    )
    summary = module.run_audit(cfg)
    models = _summary_by_model(summary)

    assert models[module.REFERENCE_MODEL]["tp_hit_count"] == 1
    assert models[module.PENDING_TOUCH_MODEL]["entry_not_triggered_count"] == 1


def test_pending_touch_model_can_change_tp_to_sl_when_forward_candles_justify_it(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal()],
        [
            _candle("2026-05-21T00:01:00+00:00", 101.2, 100.2, 101.0),
            _candle("2026-05-21T00:02:00+00:00", 100.1, 99.0, 99.2),
        ],
    )
    summary = module.run_audit(cfg)
    models = _summary_by_model(summary)
    rows = module._read_csv(cfg.output_dir / "fill_model_audit_per_signal.csv")

    assert models[module.REFERENCE_MODEL]["tp_hit_count"] == 1
    assert models[module.PENDING_TOUCH_MODEL]["sl_hit_count"] == 1
    assert rows[0]["changed_under_pending_touch_flag"] == "True"


def test_conservative_model_does_not_allow_same_candle_favorable_fill(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal()],
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 99.8, 100.5)],
    )
    summary = module.run_audit(cfg)
    models = _summary_by_model(summary)

    assert models[module.PENDING_TOUCH_MODEL]["tp_hit_count"] == 1
    assert models[module.CONSERVATIVE_MODEL]["ambiguous_intrabar_count"] == 1


def test_tp_sl_same_candle_is_ambiguous_intrabar(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal()],
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 98.8, 100.0)],
    )
    summary = module.run_audit(cfg)
    models = _summary_by_model(summary)

    assert models[module.REFERENCE_MODEL]["ambiguous_intrabar_count"] == 1
    assert models[module.PENDING_TOUCH_MODEL]["ambiguous_intrabar_count"] == 1


def test_sensitivity_flags_classify_high_when_wr_or_total_r_changes_materially(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal()],
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 100.2, 101.0)],
    )
    summary = module.run_audit(cfg)

    assert summary["sensitivity"]["fill_model_sensitivity_status"] == "HIGH"
    assert summary["fill_model_audit_gate"] == "BLOCKED"
    assert summary["paper_signal_stream_gate"] == "BLOCKED"


def test_max_losing_streak_uses_signal_order_not_outcome_buckets(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [
            _signal("2026-05-21T00:00:00+00:00", entry=100.0, stop=99.0, tp=101.0),
            _signal("2026-05-21T00:10:00+00:00", entry=100.0, stop=99.0, tp=101.0),
            _signal("2026-05-21T00:20:00+00:00", entry=100.0, stop=99.0, tp=101.0),
        ],
        [
            _candle("2026-05-21T00:01:00+00:00", 101.2, 100.0, 101.0),
            _candle("2026-05-21T00:11:00+00:00", 100.0, 98.8, 99.0),
            _candle("2026-05-21T00:21:00+00:00", 101.2, 100.0, 101.0),
        ],
    )
    summary = module.run_audit(cfg)
    models = _summary_by_model(summary)

    assert models[module.REFERENCE_MODEL]["tp_hit_count"] == 2
    assert models[module.REFERENCE_MODEL]["sl_hit_count"] == 1
    assert models[module.REFERENCE_MODEL]["max_losing_streak"] == 1


def test_missing_required_fields_produce_not_computable_not_false_pass(tmp_path):
    bad = _signal(entry="", stop="", tp="")
    module, cfg, _data_file = _fixture(
        tmp_path,
        [bad],
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 100.2, 101.0)],
    )
    summary = module.run_audit(cfg)
    models = _summary_by_model(summary)

    assert models[module.REFERENCE_MODEL]["model_status"] == module.NOT_COMPUTABLE
    assert summary["sensitivity"]["fill_model_sensitivity_status"] == "NOT_COMPUTABLE"
    assert summary["fill_model_audit_gate"] == "BLOCKED"


def test_gates_remain_blocked_for_live_broker_order_send_and_deployment(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal()],
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 100.0, 101.0)],
    )
    summary = module.run_audit(cfg)

    assert summary["live_gate"] == "BLOCKED"
    assert summary["deployment_gate"] == "BLOCKED"
    assert summary["order_send_gate"] == "BLOCKED"
    assert summary["broker_gate"] == "BLOCKED"
    assert summary["safety"]["telegram_enabled"] is False


def test_no_strategy_runtime_or_data_mutation(tmp_path):
    module, cfg, data_file = _fixture(
        tmp_path,
        [_signal()],
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 100.0, 101.0)],
    )
    before = hashlib.sha256(data_file.read_bytes()).hexdigest()
    summary = module.run_audit(cfg)
    after = hashlib.sha256(data_file.read_bytes()).hexdigest()

    assert before == after
    assert summary["safety"]["strategy_3_runtime_logic_changed"] is False
    assert summary["safety"]["vwap_sigma_cooldown_logic_changed"] is False
    assert summary["safety"]["strategy_2_touched"] is False
    assert summary["safety"]["adelin_touched"] is False
    assert summary["safety"]["data_xauusd_mutated"] is False
