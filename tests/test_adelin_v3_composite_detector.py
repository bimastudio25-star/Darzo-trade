from __future__ import annotations

import ast
import csv
import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.adelin_v3_composite_detector import (
    DAILY_SWING,
    FVG,
    H1_SWING,
    IFVG,
    LONG,
    SHORT,
    SWING_HIGH,
    SWING_LOW,
    AdelinV3Config,
    ReactionZone,
    SwingLevel,
    SweepEvent,
    _direction_consistent,
    detect_reaction_zone,
    detect_sweep_event,
    generate_v3_candidate_pack,
    nearest_v3_round_level,
    round_confluence,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _frame(rows: list[tuple[datetime, float, float, float, float, int]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "tick_volume"])


def _level(level_type: str = SWING_LOW, price: float = 4900.0) -> SwingLevel:
    return SwingLevel(
        "test_level",
        DAILY_SWING if level_type == SWING_LOW else H1_SWING,
        "D1" if level_type == SWING_LOW else "H1",
        level_type,
        price,
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
        datetime(2026, 1, 3, tzinfo=timezone.utc),
        "HIGH",
    )


def _event(direction: str = LONG) -> SweepEvent:
    level_type = SWING_LOW if direction == LONG else SWING_HIGH
    price = 4900.0
    return SweepEvent(
        direction,
        _level(level_type, price),
        datetime(2026, 1, 10, 0, 40, tzinfo=timezone.utc),
        4897.0 if direction == LONG else 4903.0,
        ("TEST_SWEEP",),
    )


def _write_frame(path: Path, start: datetime, rows: int, minutes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "open", "high", "low", "close", "tick_volume"])
        for idx in range(rows):
            ts = start + timedelta(minutes=idx * minutes)
            price = 4900.0 + (idx % 5) * 0.1
            writer.writerow([ts.strftime("%Y-%m-%d %H:%M:%S"), price, price + 0.2, price - 0.2, price, 100])


def _minimal_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _write_frame(data_dir / "XAUUSD" / "M1.csv", start, 180, 1)
    _write_frame(data_dir / "XAUUSD" / "M5.csv", start, 60, 5)
    _write_frame(data_dir / "XAUUSD" / "M15.csv", start, 30, 15)
    _write_frame(data_dir / "XAUUSD" / "H1.csv", start, 24, 60)
    _write_frame(data_dir / "XAUUSD" / "H4.csv", start, 12, 240)
    _write_frame(data_dir / "XAUUSD" / "D1.csv", start, 10, 1440)
    return data_dir


def test_module_import_is_safe():
    module = importlib.import_module("dazro_trade.analytics.adelin_v3_composite_detector")
    assert hasattr(module, "generate_v3_candidate_pack")


def test_script_import_is_safe():
    module = importlib.import_module("scripts.create_adelin_v3_composite_candidate_pack")
    args = module.parse_args(["--symbol", "XAUUSD", "--max-candidates", "5"])
    assert args.symbol == "XAUUSD"
    assert args.max_candidates == 5


def test_no_live_telegram_broker_or_order_imports_are_used():
    paths = [
        REPO_ROOT / "dazro_trade" / "analytics" / "adelin_v3_composite_detector.py",
        REPO_ROOT / "scripts" / "create_adelin_v3_composite_candidate_pack.py",
    ]
    blocked_import_terms = {"telegram", "mt5", "execution", "broker", "order"}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name.lower() for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module.lower())
        assert not any(any(term in name for term in blocked_import_terms) for name in imported)
        source = path.read_text(encoding="utf-8")
        assert "order_send" not in source
        assert "send_message(" not in source


def test_round_number_confluence_uses_10_usd_levels():
    assert nearest_v3_round_level(4907.0) == 4910.0
    ok, level, distance = round_confluence(4901.9, 0.1, 20)
    assert ok is True
    assert level == 4900.0
    assert distance == 19.0
    assert round_confluence(4902.5, 0.1, 20)[0] is False


def test_c5_corrected_direction_requires_zone_beyond_swept_level():
    long_event = _event(LONG)
    assert _direction_consistent(
        long_event,
        ReactionZone(FVG, 4895.0, 4896.0, datetime(2026, 1, 10, tzinfo=timezone.utc), "M5", "MEDIUM", ()),
    )
    assert not _direction_consistent(
        long_event,
        ReactionZone(FVG, 4901.0, 4902.0, datetime(2026, 1, 10, tzinfo=timezone.utc), "M5", "MEDIUM", ()),
    )
    short_event = _event(SHORT)
    assert _direction_consistent(
        short_event,
        ReactionZone(FVG, 4904.0, 4905.0, datetime(2026, 1, 10, tzinfo=timezone.utc), "M5", "MEDIUM", ()),
    )
    assert not _direction_consistent(
        short_event,
        ReactionZone(FVG, 4896.0, 4897.0, datetime(2026, 1, 10, tzinfo=timezone.utc), "M5", "MEDIUM", ()),
    )


def test_sweep_detection_excludes_anchor_candle_and_requires_delay():
    anchor = datetime(2026, 1, 10, 1, 0, tzinfo=timezone.utc)
    level = _level(SWING_LOW, 4900.0)
    anchor_candle_only = _frame(
        [
            (anchor - timedelta(minutes=20), 4901, 4902, 4900.5, 4901, 100),
            (anchor - timedelta(minutes=15), 4901, 4902, 4900.5, 4901, 100),
            (anchor - timedelta(minutes=10), 4901, 4902, 4900.5, 4901, 100),
            (anchor - timedelta(minutes=5), 4901, 4902, 4897.0, 4901, 100),
        ]
    )
    assert detect_sweep_event({"M5": anchor_candle_only}, [level], anchor, pip_size=0.1) is None

    delayed_sweep = anchor_candle_only.copy()
    delayed_sweep.loc[2, "low"] = 4897.0
    event = detect_sweep_event({"M5": delayed_sweep}, [level], anchor, pip_size=0.1)
    assert event is not None
    assert event.direction == LONG
    assert event.sweep_timestamp == anchor - timedelta(minutes=10)


def test_ifvg_retest_only_by_anchor_candle_is_rejected():
    anchor = datetime(2026, 1, 10, 1, 0, tzinfo=timezone.utc)
    rows = [
        (anchor - timedelta(minutes=50), 4893.0, 4895.0, 4892.5, 4894.5, 100),
        (anchor - timedelta(minutes=45), 4894.5, 4894.8, 4894.0, 4894.6, 100),
        (anchor - timedelta(minutes=40), 4896.5, 4897.0, 4896.0, 4896.8, 100),
        (anchor - timedelta(minutes=35), 4898.0, 4898.5, 4897.2, 4898.0, 100),
        (anchor - timedelta(minutes=30), 4898.0, 4898.4, 4897.4, 4898.0, 100),
        (anchor - timedelta(minutes=25), 4898.0, 4898.4, 4897.4, 4898.0, 100),
        (anchor - timedelta(minutes=20), 4898.0, 4898.4, 4897.4, 4898.0, 100),
        (anchor - timedelta(minutes=15), 4898.0, 4898.4, 4897.4, 4898.0, 100),
        (anchor - timedelta(minutes=10), 4898.0, 4898.4, 4897.4, 4898.0, 100),
        (anchor - timedelta(minutes=5), 4898.0, 4898.4, 4895.5, 4896.0, 100),
    ]
    cfg = AdelinV3Config()
    assert detect_reaction_zone({"M5": _frame(rows)}, _event(LONG), anchor, cfg, 0.1) is None


def test_ifvg_retested_by_last_completed_pre_anchor_m5_is_accepted():
    anchor = datetime(2026, 1, 10, 1, 0, tzinfo=timezone.utc)
    rows = [
        (anchor - timedelta(minutes=50), 4893.0, 4895.0, 4892.5, 4894.5, 100),
        (anchor - timedelta(minutes=45), 4894.5, 4894.8, 4894.0, 4894.6, 100),
        (anchor - timedelta(minutes=40), 4896.5, 4897.0, 4896.0, 4896.8, 100),
        (anchor - timedelta(minutes=35), 4896.8, 4898.5, 4894.5, 4898.0, 100),
        (anchor - timedelta(minutes=30), 4898.0, 4898.4, 4897.4, 4898.0, 100),
        (anchor - timedelta(minutes=25), 4898.0, 4898.4, 4897.4, 4898.0, 100),
        (anchor - timedelta(minutes=20), 4898.0, 4898.4, 4897.4, 4898.0, 100),
        (anchor - timedelta(minutes=15), 4898.0, 4898.4, 4897.4, 4898.0, 100),
        (anchor - timedelta(minutes=10), 4898.0, 4898.4, 4895.5, 4896.0, 100),
    ]
    cfg = AdelinV3Config()
    zone = detect_reaction_zone({"M5": _frame(rows)}, _event(LONG), anchor, cfg, 0.1)
    assert zone is not None
    assert zone.zone_type in {FVG, IFVG}


def test_pack_generation_writes_empty_valid_summary_when_no_candidates(tmp_path: Path):
    data_dir = _minimal_data_dir(tmp_path)
    output_dir = tmp_path / "pack"
    summary = generate_v3_candidate_pack(
        AdelinV3Config(data_dir=data_dir, output_dir=output_dir, max_candidates=5, dry_run=True)
    )
    assert summary["candidate_pack_verdict"] == "INSUFFICIENT_SAMPLE"
    assert (output_dir / "candidate_pack.csv").exists()
    assert (output_dir / "generation_summary.json").exists()
    assert (output_dir / "rejection_breakdown.csv").exists()
    assert (output_dir / "decision_criteria.md").exists()
    assert (output_dir / "index.html").exists()
    saved = (output_dir / "generation_summary.json").read_text(encoding="utf-8")
    assert "live_trading_enabled" in saved
    assert "INSUFFICIENT_SAMPLE" in saved


def test_temp_input_data_is_not_modified(tmp_path: Path):
    data_dir = _minimal_data_dir(tmp_path)
    m1_path = data_dir / "XAUUSD" / "M1.csv"
    before = m1_path.read_bytes()
    generate_v3_candidate_pack(
        AdelinV3Config(data_dir=data_dir, output_dir=tmp_path / "pack", max_candidates=1, dry_run=True)
    )
    assert m1_path.read_bytes() == before
