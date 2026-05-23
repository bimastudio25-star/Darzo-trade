from __future__ import annotations

import csv
import hashlib
import importlib
import json
from pathlib import Path


def _module():
    return importlib.import_module("scripts.analyze_strategy_3_paper_lifecycle_outcomes")


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
    entry: float = 100.0,
    stop: float = 99.0,
    tp: float = 101.0,
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
        "risk_distance": abs(entry - stop),
        "cooldown_status": "accepted" if accepted else "blocked",
        "cooldown_accepted": str(accepted),
        "cooldown_blocked": str(not accepted),
        "cooldown_block_reason": "" if accepted else "STRATEGY_3_COOLDOWN_BLOCKED",
        "data_context_hash": "ctx" if context else "",
        "order_sent": "False",
        "telegram_sent": "False",
        "broker_called": "False",
    }


def _m1(path: Path, rows: list[dict[str, object]]) -> Path:
    data_path = path / "data" / "XAUUSD" / "M1.csv"
    _write_csv(data_path, rows, ["time", "open", "high", "low", "close", "tick_volume", "spread"])
    return data_path


def _fixture(tmp_path: Path, paper_rows: list[dict[str, object]], m1_rows: list[dict[str, object]], *, fill_model: str | None = None):
    module = _module()
    paper = tmp_path / "paper_signals.csv"
    _write_csv(paper, paper_rows)
    data_file = _m1(tmp_path, m1_rows)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"context": {"context_gate_status": "PASSED"}, "gate_status": {"context_gate": "PASSED"}}), encoding="utf-8")
    dashboard = tmp_path / "dashboard.json"
    dashboard.write_text(json.dumps({"sample_size": {"sample_size_status": "INSUFFICIENT_N"}}), encoding="utf-8")
    cfg = module.LifecycleConfig(
        symbol="XAUUSD",
        data_dir=str(tmp_path / "data"),
        paper_signals_path=paper,
        evidence_refresh_summary_path=evidence,
        dashboard_summary_path=dashboard,
        output_dir=tmp_path / "out",
        docs_path=tmp_path / "docs" / "lifecycle.md",
        dry_run=True,
        clean_context_only=True,
        include_legacy=False,
        fill_model=fill_model or module.FILL_MODEL_REFERENCE,
        forward_timeframe="M1",
        fallback_timeframe="M5",
        max_forward_bars=3,
    )
    return module, cfg, data_file


def _base_candle(time: str, high: float, low: float, close: float) -> dict[str, object]:
    return {"time": time, "open": close, "high": high, "low": low, "close": close, "tick_volume": 1, "spread": 4}


def test_import_safe_and_cli_defaults():
    module = _module()
    args = module.parse_args([])
    assert args.symbol == "XAUUSD"
    assert args.fill_model == module.FILL_MODEL_REFERENCE
    assert args.max_forward_bars == 480


def test_lifecycle_output_files_are_created(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal()],
        [
            _base_candle("2026-05-21T00:00:00+00:00", 100.1, 99.9, 100.0),
            _base_candle("2026-05-21T00:01:00+00:00", 101.2, 100.2, 101.0),
        ],
    )
    summary = module.run_tracker(cfg)

    assert summary["accepted_signals"] == 1
    assert (cfg.output_dir / "paper_lifecycle_events.csv").exists()
    assert (cfg.output_dir / "paper_signal_outcomes.csv").exists()
    assert (cfg.output_dir / "paper_open_positions.json").exists()
    assert (cfg.output_dir / "paper_lifecycle_summary.json").exists()
    assert (cfg.output_dir / "paper_lifecycle_outcome_tracker.md").exists()
    assert cfg.docs_path.exists()


def test_fill_model_is_documented(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal()],
        [_base_candle("2026-05-21T00:01:00+00:00", 101.2, 100.2, 101.0)],
    )
    summary = module.run_tracker(cfg)
    text = cfg.docs_path.read_text(encoding="utf-8")

    assert summary["methodology"]["fill_model"] == module.FILL_MODEL_REFERENCE
    assert "PAPER_REFERENCE_FILL_AT_SIGNAL" in text
    assert "forward closed candles" in text


def test_accepted_signal_can_become_tp_hit(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal(direction="LONG", entry=100.0, stop=99.0, tp=101.0)],
        [_base_candle("2026-05-21T00:01:00+00:00", 101.1, 100.0, 101.0)],
    )
    summary = module.run_tracker(cfg)

    assert summary["tp_hit_count"] == 1
    assert summary["sl_hit_count"] == 0
    assert summary["decisive_win_rate_tp_vs_sl_only"] == 1.0


def test_accepted_signal_can_become_sl_hit(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal(direction="LONG", entry=100.0, stop=99.0, tp=101.0)],
        [_base_candle("2026-05-21T00:01:00+00:00", 100.2, 98.9, 99.0)],
    )
    summary = module.run_tracker(cfg)

    assert summary["tp_hit_count"] == 0
    assert summary["sl_hit_count"] == 1
    assert summary["decisive_win_rate_tp_vs_sl_only"] == 0.0


def test_tp_sl_same_candle_becomes_ambiguous_intrabar(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal(direction="LONG", entry=100.0, stop=99.0, tp=101.0)],
        [_base_candle("2026-05-21T00:01:00+00:00", 101.1, 98.9, 100.0)],
    )
    summary = module.run_tracker(cfg)

    assert summary["ambiguous_intrabar_count"] == 1
    assert summary["tp_hit_count"] == 0
    assert summary["sl_hit_count"] == 0
    assert summary["decisive_win_rate_tp_vs_sl_only"] is None


def test_insufficient_forward_data_and_still_open_paths(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [
            _signal("2026-05-21T00:00:00+00:00"),
            _signal("2026-05-21T00:05:00+00:00"),
        ],
        [_base_candle("2026-05-21T00:01:00+00:00", 100.2, 99.8, 100.0)],
    )
    summary = module.run_tracker(cfg)
    statuses = {row["outcome_status"] for row in module._read_csv(cfg.output_dir / "paper_signal_outcomes.csv")}

    assert "STILL_OPEN" in statuses
    assert "INSUFFICIENT_FORWARD_DATA" in statuses
    assert summary["still_open_count"] == 1
    assert summary["insufficient_forward_data_count"] == 1


def test_timeout_close_is_reported_and_not_counted_as_decisive_win(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal(direction="LONG", entry=100.0, stop=99.0, tp=101.0)],
        [
            _base_candle("2026-05-21T00:01:00+00:00", 100.2, 99.8, 100.1),
            _base_candle("2026-05-21T00:02:00+00:00", 100.3, 99.9, 100.2),
            _base_candle("2026-05-21T00:03:00+00:00", 100.4, 99.9, 100.3),
        ],
    )
    summary = module.run_tracker(cfg)

    assert summary["timeout_count"] == 1
    assert summary["accepted_with_outcome"] == 1
    assert summary["gross_win_rate"] == 0.0
    assert summary["decisive_win_rate_tp_vs_sl_only"] is None
    assert summary["gross_win_rate_denominator"] == "accepted_signals"
    assert summary["decisive_win_rate_denominator"] == "tp_hit_count + sl_hit_count"


def test_blocked_signals_are_not_converted_into_trades(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal(accepted=False)],
        [_base_candle("2026-05-21T00:01:00+00:00", 101.1, 98.9, 100.0)],
    )
    summary = module.run_tracker(cfg)
    rows = module._read_csv(cfg.output_dir / "paper_signal_outcomes.csv")

    assert summary["accepted_signals"] == 0
    assert summary["blocked_signals"] == 1
    assert rows[0]["signal_status"] == "SIGNAL_BLOCKED"
    assert rows[0]["entry_status"] == "ENTRY_NOT_TRIGGERED"


def test_risk_pips_conversion_uses_project_convention(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal(entry=100.0, stop=98.5, tp=101.5)],
        [_base_candle("2026-05-21T00:01:00+00:00", 101.6, 99.8, 101.5)],
    )
    summary = module.run_tracker(cfg)
    rows = module._read_csv(cfg.output_dir / "paper_signal_outcomes.csv")

    assert float(rows[0]["risk_distance_usd"]) == 1.5
    assert float(rows[0]["risk_distance_pips"]) == 15.0
    assert summary["methodology"]["project_pip_convention"] == "1_USD_10_PIPS"


def test_lifecycle_gate_blocks_unresolved_fill_model(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_signal()],
        [_base_candle("2026-05-21T00:01:00+00:00", 101.2, 100.2, 101.0)],
        fill_model=_module().FILL_MODEL_UNRESOLVED,
    )
    summary = module.run_tracker(cfg)

    assert summary["lifecycle_gate"] == "BLOCKED"
    assert "FILL_MODEL_UNRESOLVED" in summary["verdict_flags"]
    assert summary["live_gate"] == "BLOCKED"
    assert summary["deployment_gate"] == "BLOCKED"
    assert summary["order_send_gate"] == "BLOCKED"
    assert summary["broker_gate"] == "BLOCKED"


def test_no_strategy_runtime_or_data_mutation(tmp_path):
    module, cfg, data_file = _fixture(
        tmp_path,
        [_signal()],
        [_base_candle("2026-05-21T00:01:00+00:00", 101.2, 100.2, 101.0)],
    )
    before = hashlib.sha256(data_file.read_bytes()).hexdigest()
    summary = module.run_tracker(cfg)
    after = hashlib.sha256(data_file.read_bytes()).hexdigest()

    assert before == after
    assert summary["safety"]["strategy_3_runtime_logic_changed"] is False
    assert summary["safety"]["vwap_sigma_cooldown_logic_changed"] is False
    assert summary["safety"]["strategy_2_touched"] is False
    assert summary["safety"]["adelin_touched"] is False
    assert summary["safety"]["data_xauusd_mutated"] is False
    assert summary["safety"]["telegram_enabled"] is False
