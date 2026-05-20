from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


def _module():
    return importlib.import_module("scripts.repair_strategy_3_h4_data")


def _row(ts: datetime, price: float, volume: int = 10) -> dict:
    return {
        "time": ts,
        "open": price,
        "high": price + 1,
        "low": price - 1,
        "close": price + 0.5,
        "tick_volume": volume,
        "spread": 4,
    }


def _write_no_header_utf16_h4(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.strftime("%Y.%m.%d %H:%M")
    df.to_csv(path, index=False, header=False, encoding="utf-16", lineterminator="\n")


def _write_candidate(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.strftime("%Y.%m.%d %H:%M")
    df.to_csv(path, index=False, encoding="utf-8")


def _diagnostic(base: datetime, *, match_rate=0.9965, material_mismatches=1, timezone_shift=False, recommendation="MT5_H4_SOURCE_MISMATCH_MANUAL_REVIEW") -> dict:
    overlap_count = 300
    return {
        "recommendation": recommendation,
        "local_h4": {
            "latest_timestamp": base.isoformat(),
            "duplicate_count": 0,
            "invalid_ohlc_rows": 0,
            "non_monotonic_timestamps": 0,
        },
        "mt5_h4": {
            "latest_closed_timestamp": (base + timedelta(hours=8)).isoformat(),
        },
        "overlap": {
            "overlap_count": overlap_count,
            "match_count_ohlc": overlap_count - material_mismatches,
            "match_rate_ohlc": match_rate,
            "first_ohlc_mismatch_timestamp": base.isoformat(),
            "last_ohlc_mismatch_timestamp": base.isoformat(),
        },
        "append_rebuild_diagnostic": {
            "missing_closed_bars_after_local_latest": 2,
        },
        "timezone_boundary_diagnostics": {
            "best_shift_by_match_rate": 0 if not timezone_shift else 1,
            "timezone_shift_suspected": timezone_shift,
        },
    }


def _fixture(tmp_path: Path, *, diagnostic_overrides: dict | None = None):
    module = _module()
    base = datetime(2026, 5, 19, tzinfo=timezone.utc)
    local_rows = [
        _row(base - timedelta(hours=8), 100),
        _row(base - timedelta(hours=4), 104),
        _row(base, 108, volume=0),
    ]
    mt5_rows = [
        _row(base - timedelta(hours=8), 100),
        _row(base - timedelta(hours=4), 104),
        _row(base, 106, volume=99),
        _row(base + timedelta(hours=4), 110),
        _row(base + timedelta(hours=8), 114),
    ]
    h4_path = tmp_path / "data" / "XAUUSD" / "H4.csv"
    diag_dir = tmp_path / "diag"
    _write_no_header_utf16_h4(h4_path, local_rows)
    _write_candidate(diag_dir / "h4_mt5_candidate.csv", mt5_rows)
    diagnostic = _diagnostic(base)
    if diagnostic_overrides:
        for key, value in diagnostic_overrides.items():
            if isinstance(value, dict) and isinstance(diagnostic.get(key), dict):
                diagnostic[key].update(value)
            else:
                diagnostic[key] = value
    (diag_dir / "h4_data_source_diagnostic.json").write_text(json.dumps(diagnostic), encoding="utf-8")
    cfg = module.RepairConfig(
        symbol="XAUUSD",
        data_dir=tmp_path / "data",
        diagnostic_dir=diag_dir,
        output_dir=tmp_path / "reports",
        dry_run=True,
        apply=False,
        max_material_mismatches=1,
        required_ohlc_match_rate=0.99,
        expected_conflict_timestamp=base.isoformat(),
        preserve_existing_format=True,
    )
    return module, cfg, h4_path, base


def test_import_safe_and_cli_parse_does_not_run(tmp_path):
    module = _module()
    args = module.parse_args([])
    assert args.symbol == "XAUUSD"
    assert not (tmp_path / "reports").exists()


def test_dry_run_does_not_modify_h4_and_creates_candidate(tmp_path):
    module, cfg, h4_path, _ = _fixture(tmp_path)
    before = h4_path.read_bytes()

    summary = module.build_repair(cfg)

    assert summary["repair_status"] == "DRY_RUN_REPAIR_CANDIDATE_CREATED"
    assert h4_path.read_bytes() == before
    assert (tmp_path / "reports" / "H4.repaired_candidate.csv").exists()


def test_apply_requires_explicit_apply(tmp_path):
    module, cfg, h4_path, _ = _fixture(tmp_path)
    before = h4_path.read_bytes()

    summary = module.build_repair(cfg)

    assert summary["apply"] is False
    assert summary["data_h4_modified"] is not True
    assert h4_path.read_bytes() == before


def test_apply_creates_backup_before_h4_write_and_preserves_format(tmp_path):
    module, cfg, h4_path, _ = _fixture(tmp_path)
    apply_cfg = module.RepairConfig(**{**cfg.__dict__, "apply": True, "dry_run": False})

    summary = module.build_repair(apply_cfg)

    assert summary["backup_path"]
    assert Path(summary["backup_path"]).exists()
    assert summary["data_h4_modified"] is True
    fmt = module.detect_h4_format(h4_path)
    assert fmt["encoding"] == "utf-16"
    assert fmt["header_present"] is False
    assert summary["rows_replaced_count"] == 1
    assert summary["rows_appended_count"] == 2


def test_repair_aborts_if_ohlc_match_rate_too_low(tmp_path):
    module, cfg, _, _ = _fixture(tmp_path, diagnostic_overrides={"overlap": {"match_rate_ohlc": 0.98}})

    summary = module.build_repair(cfg)

    assert summary["repair_status"] == "REPAIR_ABORTED_SAFETY_CHECK_FAILED"
    assert "OHLC_MATCH_RATE_BELOW_REQUIRED" in summary["failed_safety_checks"]


def test_repair_aborts_if_material_mismatches_exceed_limit(tmp_path):
    base = datetime(2026, 5, 19, tzinfo=timezone.utc)
    module, cfg, _, base = _fixture(
        tmp_path,
        diagnostic_overrides={"overlap": {"overlap_count": 300, "match_count_ohlc": 298, "last_ohlc_mismatch_timestamp": (base + timedelta(hours=4)).isoformat()}},
    )

    summary = module.build_repair(cfg)

    assert "TOO_MANY_MATERIAL_MISMATCHES" in summary["failed_safety_checks"]


def test_repair_aborts_if_timezone_shift_suspected(tmp_path):
    module, cfg, _, _ = _fixture(
        tmp_path,
        diagnostic_overrides={"timezone_boundary_diagnostics": {"best_shift_by_match_rate": 1, "timezone_shift_suspected": True}},
    )

    summary = module.build_repair(cfg)

    assert "TIMEZONE_SHIFT_SUSPECTED" in summary["failed_safety_checks"]


def test_repair_replaces_only_expected_conflict_and_appends_missing(tmp_path):
    module, cfg, _, base = _fixture(tmp_path)
    local, mt5, _, _, _ = module.load_required_inputs(cfg)

    repaired, details = module.build_repaired_h4(local, mt5, base.isoformat())

    assert details["rows_replaced_count"] == 1
    assert details["rows_appended_count"] == 2
    assert len(repaired) == len(local) + 2
    conflict = repaired[pd.to_datetime(repaired["time"], utc=True) == pd.Timestamp(base)]
    assert float(conflict.iloc[0]["open"]) == 106


def test_repaired_output_has_no_duplicate_timestamps(tmp_path):
    module, cfg, _, base = _fixture(tmp_path)
    local, mt5, _, _, _ = module.load_required_inputs(cfg)

    repaired, _ = module.build_repaired_h4(local, mt5, base.isoformat())
    validation = module.validate_frame(repaired, "H4")

    assert validation["duplicate_timestamps"] == 0
    assert validation["non_monotonic_timestamps"] == 0


def test_scanner_remains_blocked_if_post_repair_freshness_fails(monkeypatch, tmp_path):
    module, cfg, _, _ = _fixture(tmp_path)
    apply_cfg = module.RepairConfig(**{**cfg.__dict__, "apply": True, "dry_run": False})
    monkeypatch.setattr(
        module,
        "_post_repair_freshness",
        lambda *a, **kw: {"paper_signals_clean_for_validation": False, "h4_quarantine_status": "stale_blocking"},
    )

    summary = module.build_repair(apply_cfg)

    assert summary["repair_status"] == "REPAIR_APPLIED_BUT_STILL_STALE"
    assert summary["scanner_should_remain_blocked"] is True
    assert summary["paper_signals_clean_for_validation"] is False
