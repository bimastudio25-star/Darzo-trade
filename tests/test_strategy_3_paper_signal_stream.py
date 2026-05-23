from __future__ import annotations

import csv
import hashlib
import importlib
import json
from pathlib import Path


def _module():
    return importlib.import_module("scripts.run_strategy_3_paper_signal_stream")


def _write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _paper_row(
    timestamp: str = "2026-05-21T02:30:00+00:00",
    *,
    accepted: bool = True,
    direction: str = "LONG",
    context: bool = True,
) -> dict[str, object]:
    return {
        "signal_timestamp": timestamp,
        "symbol": "XAUUSD",
        "strategy": "strategy_3_vwap_1r",
        "direction": direction,
        "entry_price": 4538.58,
        "stop_loss": 4537.76,
        "take_profit": 4539.40,
        "risk_distance": 0.82,
        "cooldown_status": "accepted" if accepted else "blocked",
        "cooldown_accepted": str(accepted),
        "cooldown_blocked": str(not accepted),
        "cooldown_block_reason": "" if accepted else "STRATEGY_3_COOLDOWN_BLOCKED",
        "data_context_hash": "ctx-1" if context else "",
        "session": "Sydney + Tokyo",
    }


def _regime_row(timestamp: str = "2026-05-21T02:30:00+00:00", direction: str = "LONG") -> dict[str, object]:
    return {
        "decision_time": timestamp,
        "direction": direction,
        "session_bucket": "Sydney + Tokyo",
        "vwap_slope_bucket": "down",
        "vwap_distance_sigma_bucket": "1_to_2_sigma",
        "h1_bias": "up",
        "h4_bias": "up",
        "volatility_bucket": "low_volatility",
        "context_prefix_compatible": "True",
    }


def _fixture(tmp_path: Path, rows: list[dict[str, object]] | None = None, *, governance: bool = True):
    module = _module()
    paper = tmp_path / "paper_signals.csv"
    if rows is not None:
        _write_csv(paper, rows)
    regime = tmp_path / "regime.csv"
    _write_csv(regime, [_regime_row()])
    policy = tmp_path / "governance" / "ambiguity_governance_policy.json"
    summary = tmp_path / "governance" / "ambiguity_governance_summary.json"
    if governance:
        policy.parent.mkdir(parents=True, exist_ok=True)
        policy.write_text(
            json.dumps(
                {
                    "ambiguity_governance_gate": "WARNING",
                    "paper_signal_stream_gate_policy": "WARNING",
                    "primary_outcome_policy": "REFERENCE_PRIMARY_WITH_AMBIGUOUS_EXCLUDED_FROM_DECISIVE_WR",
                    "ambiguous_intrabar_policy": "AMBIGUOUS_NOT_COUNTED_AS_WIN_AND_EXCLUDED_FROM_DECISIVE_WR",
                    "live_gate": "BLOCKED",
                    "deployment_gate": "BLOCKED",
                    "order_send_gate": "BLOCKED",
                    "broker_gate": "BLOCKED",
                }
            ),
            encoding="utf-8",
        )
        summary.write_text(json.dumps({"ambiguity_governance_gate": "WARNING"}), encoding="utf-8")
    data_file = tmp_path / "data" / "XAUUSD" / "M1.csv"
    _write_csv(data_file, [{"time": "2026-05-21T02:31:00+00:00", "open": 1, "high": 1, "low": 1, "close": 1}])
    cfg = module.PaperSignalStreamConfig(
        symbol="XAUUSD",
        data_dir=tmp_path / "data",
        paper_signals_path=paper,
        scanner_summary_path=tmp_path / "scanner_summary.json",
        pipeline_summary_path=tmp_path / "pipeline_summary.json",
        regime_diagnostics_path=regime,
        ambiguity_governance_policy_path=policy,
        ambiguity_governance_summary_path=summary,
        output_dir=tmp_path / "out",
        docs_path=tmp_path / "docs" / "stream.md",
        dry_run=True,
        watch=False,
        poll_seconds=1,
        max_watch_iterations=None,
        enable_paper_telegram=False,
        notify_blocked=False,
        force_resend=False,
        allow_missing_governance_dry_run=False,
        include_legacy=False,
    )
    return module, cfg, data_file


def test_import_safe_and_cli_defaults():
    module = _module()
    args = module.parse_args([])
    assert args.symbol == "XAUUSD"
    assert args.dry_run is True
    assert args.enable_paper_telegram is False
    assert hasattr(module, "run_stream")


def test_output_files_are_created_for_dry_run(tmp_path):
    module, cfg, _data_file = _fixture(tmp_path, [_paper_row(), _paper_row("2026-05-21T02:45:00+00:00", accepted=False)])
    summary = module.run_stream_once(cfg)

    assert summary["accepted_count"] == 1
    assert summary["blocked_count"] == 1
    assert (cfg.output_dir / "paper_signal_stream_events.csv").exists()
    assert (cfg.output_dir / "paper_signal_stream_events.jsonl").exists()
    assert (cfg.output_dir / "paper_signal_stream_latest_state.json").exists()
    assert (cfg.output_dir / "paper_signal_stream_session_summary.json").exists()
    assert (cfg.output_dir / "weekly_manual_review_template.csv").exists()
    assert (cfg.output_dir / "paper_signal_stream.md").exists()


def test_accepted_event_generates_safe_paper_message(tmp_path):
    module, cfg, _data_file = _fixture(tmp_path, [_paper_row()])
    module.run_stream_once(cfg)
    payload = json.loads((cfg.output_dir / "paper_signal_stream_events.jsonl").read_text(encoding="utf-8").splitlines()[0])
    message = payload["notification_message"]

    assert message.startswith(module.MESSAGE_PREFIX)
    assert message.endswith(module.MESSAGE_SUFFIX)
    assert module.AMBIGUITY_POLICY_NOTE in message
    assert module.validate_notification_message(message) == []


def test_blocked_no_signal_and_error_events_are_logged_locally(tmp_path):
    module, cfg, _data_file = _fixture(tmp_path, [_paper_row(accepted=False)])
    summary = module.run_stream_once(cfg)
    assert summary["blocked_count"] == 1
    assert summary["alerts_sent"] == 0
    assert _read_csv(cfg.output_dir / "paper_signal_stream_events.csv")[0]["alert_delivery_status"] == "BLOCKED_LOCAL_LOG_ONLY"

    module2, cfg2, _data_file2 = _fixture(tmp_path / "empty", [])
    summary2 = module2.run_stream_once(cfg2)
    assert summary2["no_signal_count"] == 1

    module3, cfg3, _data_file3 = _fixture(tmp_path / "missing", None)
    summary3 = module3.run_stream_once(cfg3)
    assert summary3["error_count"] == 1


def test_telegram_disabled_by_default_and_missing_env_does_not_crash(tmp_path, monkeypatch):
    module, cfg, _data_file = _fixture(tmp_path, [_paper_row()])
    monkeypatch.delenv("STRATEGY3_PAPER_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("STRATEGY3_PAPER_TELEGRAM_CHAT_ID", raising=False)
    summary = module.run_stream_once(cfg)
    assert summary["telegram_enabled"] is False
    assert summary["telegram_configured"] is False

    cfg2 = module.PaperSignalStreamConfig(**{**cfg.__dict__, "dry_run": False, "enable_paper_telegram": True, "force_resend": True})
    summary2 = module.run_stream_once(cfg2)
    rows = _read_csv(cfg.output_dir / "paper_signal_stream_events.csv")
    assert summary2["telegram_enabled"] is True
    assert rows[0]["alert_delivery_status"] == "TELEGRAM_NOT_CONFIGURED"


def test_no_secret_values_are_written_to_outputs(tmp_path, monkeypatch):
    secret = "123456:SECRET_TOKEN_VALUE"
    chat_id = "987654321"
    module, cfg, _data_file = _fixture(tmp_path, [_paper_row()])
    monkeypatch.setenv("STRATEGY3_PAPER_TELEGRAM_BOT_TOKEN", secret)
    monkeypatch.setenv("STRATEGY3_PAPER_TELEGRAM_CHAT_ID", chat_id)
    cfg2 = module.PaperSignalStreamConfig(**{**cfg.__dict__, "enable_paper_telegram": True})
    module.run_stream_once(cfg2)

    combined = "\n".join(path.read_text(encoding="utf-8") for path in cfg.output_dir.glob("*") if path.is_file())
    assert secret not in combined
    assert chat_id not in combined


def test_duplicate_alerts_are_suppressed_by_default(tmp_path):
    module, cfg, _data_file = _fixture(tmp_path, [_paper_row()])
    first = module.run_stream_once(cfg)
    second = module.run_stream_once(cfg)
    rows = _read_csv(cfg.output_dir / "paper_signal_stream_events.csv")

    assert first["notification_message_count"] == 1
    assert second["notification_message_count"] == 0
    assert rows[0]["alert_delivery_status"] == "DUPLICATE_SUPPRESSED"


def test_missing_ambiguity_governance_suppresses_notification_unless_allowed(tmp_path):
    module, cfg, _data_file = _fixture(tmp_path, [_paper_row()], governance=False)
    summary = module.run_stream_once(cfg)
    rows = _read_csv(cfg.output_dir / "paper_signal_stream_events.csv")
    assert summary["ambiguity_policy_summary"]["ambiguity_governance_gate"] == "MISSING"
    assert rows[0]["alert_delivery_status"] == "GOVERNANCE_MISSING_SUPPRESSED"

    cfg2 = module.PaperSignalStreamConfig(**{**cfg.__dict__, "allow_missing_governance_dry_run": True, "force_resend": True})
    module.run_stream_once(cfg2)
    rows2 = _read_csv(cfg.output_dir / "paper_signal_stream_events.csv")
    assert rows2[0]["alert_delivery_status"] == "DRY_RUN"


def test_weekly_manual_review_template_has_required_columns(tmp_path):
    _module_obj, cfg, _data_file = _fixture(tmp_path, [_paper_row()])
    _module_obj.run_stream_once(cfg)
    with (cfg.output_dir / "weekly_manual_review_template.csv").open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == _module_obj.WEEKLY_REVIEW_FIELDS


def test_gates_remain_blocked_and_governance_metadata_is_included(tmp_path):
    module, cfg, _data_file = _fixture(tmp_path, [_paper_row()])
    summary = module.run_stream_once(cfg)
    row = _read_csv(cfg.output_dir / "paper_signal_stream_events.csv")[0]

    assert row["ambiguity_governance_gate"] == "WARNING"
    assert row["paper_signal_stream_gate"] == "WARNING"
    assert summary["gates"]["live_gate"] == "BLOCKED"
    assert summary["gates"]["deployment_gate"] == "BLOCKED"
    assert summary["gates"]["order_send_gate"] == "BLOCKED"
    assert summary["gates"]["broker_gate"] == "BLOCKED"


def test_legacy_rows_are_excluded_and_data_is_not_mutated(tmp_path):
    module, cfg, data_file = _fixture(tmp_path, [_paper_row(context=False), _paper_row("2026-05-21T03:00:00+00:00")])
    before = hashlib.sha256(data_file.read_bytes()).hexdigest()
    summary = module.run_stream_once(cfg)
    after = hashlib.sha256(data_file.read_bytes()).hexdigest()

    assert before == after
    assert summary["selection"]["legacy_excluded"] == 1
    assert summary["events_observed"] == 1
    assert summary["safety"]["strategy_3_runtime_logic_changed"] is False
    assert summary["safety"]["vwap_sigma_cooldown_logic_changed"] is False
    assert summary["safety"]["strategy_2_touched"] is False
    assert summary["safety"]["adelin_touched"] is False
    assert summary["safety"]["data_xauusd_mutated"] is False
