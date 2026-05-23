from __future__ import annotations

import csv
import hashlib
import importlib
import json
from pathlib import Path


def _module():
    return importlib.import_module("scripts.analyze_strategy_3_fill_model_ambiguity_governance")


def _write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _audit_row(
    event_id: str = "e1",
    timestamp: str = "2026-05-21T00:00:00+00:00",
    *,
    direction: str = "LONG",
    entry: object = 100.0,
    stop: object = 99.0,
    tp: object = 101.0,
    reference_status: str = "TP_HIT",
    pending_status: str = "TP_HIT",
    conservative_status: str = "TP_HIT",
    changed_conservative: bool = False,
    changed_pending: bool = False,
    conservative_entry_timestamp: str = "2026-05-21T00:01:00+00:00",
) -> dict[str, object]:
    flags = {
        "PAPER_REFERENCE_FILL_AT_SIGNAL": reference_status == "AMBIGUOUS_INTRABAR",
        "PAPER_PENDING_ENTRY_TOUCH": pending_status == "AMBIGUOUS_INTRABAR",
        "CONSERVATIVE_NEXT_CANDLE_FILL_OR_TOUCH": conservative_status == "AMBIGUOUS_INTRABAR",
    }
    return {
        "event_id": event_id,
        "signal_id": event_id,
        "decision_timestamp": timestamp,
        "symbol": "XAUUSD",
        "direction": direction,
        "signal_status": "SIGNAL_ACCEPTED",
        "entry_reference_price": entry,
        "stop_loss": stop,
        "take_profit": tp,
        "risk_distance_usd": abs(float(entry) - float(stop)) if str(entry) and str(stop) else "",
        "risk_distance_pips": (abs(float(entry) - float(stop)) * 10) if str(entry) and str(stop) else "",
        "reference_outcome_status": reference_status,
        "pending_touch_outcome_status": pending_status,
        "conservative_outcome_status": conservative_status,
        "reference_fill_outcome_status": reference_status,
        "reference_outcome_r": 1.0 if reference_status == "TP_HIT" else -1.0 if reference_status == "SL_HIT" else "",
        "pending_touch_outcome_r": 1.0 if pending_status == "TP_HIT" else -1.0 if pending_status == "SL_HIT" else "",
        "conservative_outcome_r": 1.0 if conservative_status == "TP_HIT" else -1.0 if conservative_status == "SL_HIT" else "",
        "pending_touch_entry_timestamp": conservative_entry_timestamp,
        "conservative_entry_timestamp": conservative_entry_timestamp,
        "changed_under_conservative_flag": str(changed_conservative),
        "changed_under_pending_touch_flag": str(changed_pending),
        "ambiguous_intrabar_flag_by_model": json.dumps(flags),
        "paper_only": True,
    }


def _candle(time: str, high: float, low: float, close: float) -> dict[str, object]:
    return {"time": time, "open": close, "high": high, "low": low, "close": close, "tick_volume": 1, "spread": 4}


def _fixture(tmp_path: Path, audit_rows: list[dict[str, object]], m1_rows: list[dict[str, object]]):
    module = _module()
    audit_dir = tmp_path / "audit"
    _write_csv(audit_dir / "fill_model_audit_per_signal.csv", audit_rows)
    (audit_dir / "fill_model_audit_summary.json").write_text(
        json.dumps(
            {
                "alignment": {"fill_model_alignment": "ALIGNED"},
                "fill_model_audit_gate": "BLOCKED",
                "paper_signal_stream_gate": "BLOCKED",
            }
        ),
        encoding="utf-8",
    )
    (audit_dir / "fill_model_sensitivity_flags.json").write_text(json.dumps({"fill_model_sensitivity_status": "HIGH"}), encoding="utf-8")
    data_file = tmp_path / "data" / "XAUUSD" / "M1.csv"
    _write_csv(data_file, m1_rows, ["time", "open", "high", "low", "close", "tick_volume", "spread"])
    cfg = module.AmbiguityGovernanceConfig(
        symbol="XAUUSD",
        data_dir=str(tmp_path / "data"),
        fill_model_audit_dir=audit_dir,
        lifecycle_outcomes_path=tmp_path / "lifecycle.csv",
        paper_signals_path=tmp_path / "paper.csv",
        output_dir=tmp_path / "out",
        docs_path=tmp_path / "docs" / "governance.md",
        dry_run=True,
        forward_timeframe="M1",
        fallback_timeframe="M5",
    )
    return module, cfg, data_file


def test_import_safe_and_cli_defaults():
    module = _module()
    args = module.parse_args([])
    assert args.symbol == "XAUUSD"
    assert args.forward_timeframe == "M1"
    assert hasattr(module, "run_governance")


def test_output_files_are_created(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_audit_row(reference_status="AMBIGUOUS_INTRABAR", pending_status="AMBIGUOUS_INTRABAR", conservative_status="AMBIGUOUS_INTRABAR")],
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 98.8, 100.0)],
    )
    summary = module.run_governance(cfg)

    assert summary["counts"]["ambiguity_candidate_count"] == 1
    assert (cfg.output_dir / "ambiguity_governance_per_signal.csv").exists()
    assert (cfg.output_dir / "ambiguity_type_summary.csv").exists()
    assert (cfg.output_dir / "ambiguity_impact_summary.csv").exists()
    assert (cfg.output_dir / "ambiguity_governance_summary.json").exists()
    assert (cfg.output_dir / "ambiguity_governance_policy.json").exists()
    assert (cfg.output_dir / "strategy_3_fill_model_ambiguity_governance.md").exists()


def test_ambiguous_same_candle_classified_as_true_tp_sl_or_entry_exit(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_audit_row(reference_status="AMBIGUOUS_INTRABAR", pending_status="AMBIGUOUS_INTRABAR", conservative_status="AMBIGUOUS_INTRABAR")],
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 98.8, 100.0)],
    )
    module.run_governance(cfg)
    rows = module._read_csv(cfg.output_dir / "ambiguity_governance_per_signal.csv")

    assert rows[0]["ambiguity_type"] in {"TRUE_TP_SL_SAME_CANDLE", "ENTRY_AND_EXIT_SAME_CANDLE"}
    assert rows[0]["recommended_outcome_handling"] == "EXCLUDE_FROM_DECISIVE_WR"


def test_conservative_policy_artifact_can_be_classified_separately(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [
            _audit_row(
                reference_status="TP_HIT",
                pending_status="TP_HIT",
                conservative_status="AMBIGUOUS_INTRABAR",
                changed_conservative=True,
            )
        ],
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 100.0, 101.0)],
    )
    module.run_governance(cfg)
    rows = module._read_csv(cfg.output_dir / "ambiguity_governance_per_signal.csv")

    assert rows[0]["ambiguity_type"] == "CONSERVATIVE_POLICY_ARTIFACT"
    assert rows[0]["ambiguity_source"] == "CONSERVATIVE_MODEL"


def test_ambiguous_cases_are_excluded_from_decisive_primary_wr(tmp_path):
    audit_rows = [
        _audit_row("tp", reference_status="TP_HIT", pending_status="TP_HIT", conservative_status="TP_HIT"),
        _audit_row("amb", reference_status="AMBIGUOUS_INTRABAR", pending_status="AMBIGUOUS_INTRABAR", conservative_status="AMBIGUOUS_INTRABAR"),
    ]
    module, cfg, _data_file = _fixture(
        tmp_path,
        audit_rows,
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 98.8, 100.0)],
    )
    summary = module.run_governance(cfg)
    impact = {row["mode"]: row for row in summary["ambiguity_impact_summary"]}

    assert impact["AMBIGUOUS_EXCLUDED_PRIMARY"]["excluded_count"] == 1
    assert impact["AMBIGUOUS_EXCLUDED_PRIMARY"]["deterministic_outcome_count"] == 1
    assert impact["AMBIGUOUS_EXCLUDED_PRIMARY"]["decisive_wr"] == 1.0


def test_conservative_loss_mode_is_diagnostic_only(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_audit_row(reference_status="TP_HIT", pending_status="TP_HIT", conservative_status="AMBIGUOUS_INTRABAR", changed_conservative=True)],
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 100.0, 101.0)],
    )
    summary = module.run_governance(cfg)
    impact = {row["mode"]: row for row in summary["ambiguity_impact_summary"]}

    assert impact["CONSERVATIVE_DIAGNOSTIC_ONLY"]["interpretation_status"] == "CONSERVATIVE_DIAGNOSTIC_ONLY_NOT_PRIMARY"
    assert summary["governance_policy"]["conservative_mode_policy"] == "CONSERVATIVE_LOSS_DIAGNOSTIC_ONLY_NOT_PRIMARY"


def test_governance_policy_marks_live_deployment_order_send_broker_blocked(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_audit_row(reference_status="AMBIGUOUS_INTRABAR", pending_status="AMBIGUOUS_INTRABAR", conservative_status="AMBIGUOUS_INTRABAR")],
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 98.8, 100.0)],
    )
    summary = module.run_governance(cfg)

    assert summary["governance_policy"]["live_gate"] == "BLOCKED"
    assert summary["governance_policy"]["deployment_gate"] == "BLOCKED"
    assert summary["governance_policy"]["order_send_gate"] == "BLOCKED"
    assert summary["governance_policy"]["broker_gate"] == "BLOCKED"


def test_paper_signal_stream_gate_follows_ambiguity_gate(tmp_path):
    rows = [_audit_row(f"e{i}", conservative_status="TP_HIT") for i in range(5)]
    rows[0] = _audit_row("e0", conservative_status="AMBIGUOUS_INTRABAR", changed_conservative=True)
    module, cfg, _data_file = _fixture(
        tmp_path,
        rows,
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 100.0, 101.0)],
    )
    summary = module.run_governance(cfg)

    assert summary["ambiguity_governance_gate"] == "PASSED"
    assert summary["paper_signal_stream_gate"] == "ELIGIBLE_FOR_PAPER_ONLY_SIGNAL_STREAM"
    assert summary["governance_policy"]["paper_signal_stream_gate_policy"] == summary["paper_signal_stream_gate"]


def test_missing_required_fields_produce_blocked_not_false_pass(tmp_path):
    module, cfg, _data_file = _fixture(
        tmp_path,
        [_audit_row(entry="", stop="", tp="", reference_status="AMBIGUOUS_INTRABAR")],
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 98.8, 100.0)],
    )
    summary = module.run_governance(cfg)

    assert summary["ambiguity_governance_gate"] == "BLOCKED"
    assert summary["paper_signal_stream_gate"] == "BLOCKED"
    assert summary["counts"]["missing_required_fields_count"] == 1


def test_no_strategy_runtime_or_data_mutation(tmp_path):
    module, cfg, data_file = _fixture(
        tmp_path,
        [_audit_row(reference_status="AMBIGUOUS_INTRABAR", pending_status="AMBIGUOUS_INTRABAR", conservative_status="AMBIGUOUS_INTRABAR")],
        [_candle("2026-05-21T00:01:00+00:00", 101.2, 98.8, 100.0)],
    )
    before = hashlib.sha256(data_file.read_bytes()).hexdigest()
    summary = module.run_governance(cfg)
    after = hashlib.sha256(data_file.read_bytes()).hexdigest()

    assert before == after
    assert summary["safety"]["strategy_3_runtime_logic_changed"] is False
    assert summary["safety"]["vwap_sigma_cooldown_logic_changed"] is False
    assert summary["safety"]["strategy_2_touched"] is False
    assert summary["safety"]["adelin_touched"] is False
    assert summary["safety"]["data_xauusd_mutated"] is False
    assert summary["safety"]["telegram_enabled"] is False
